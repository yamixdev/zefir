"""Подключение к PostgreSQL через pool.

На Neon free tier endpoint автосуспендится после 5 минут бездействия.
`check=AsyncConnectionPool.check_connection` делает `SELECT 1` перед
выдачей соединения. Но даже с ним бывает race: check прошёл, а коннект
умер до `execute`. Поэтому поверх пула стоит `with_db_retry` — ловит
OperationalError/InterfaceError, инвалидирует пул и повторяет запрос.

`min_size=0` — в serverless не держим idle-коннекты, открываем по запросу.
"""
import logging
from hashlib import sha256
from functools import wraps

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from bot.config import config

logger = logging.getLogger("зефирка.бд")

_pool: AsyncConnectionPool | None = None

RETRIABLE_DB_ERRORS = (
    psycopg.OperationalError,
    psycopg.InterfaceError,
)


async def get_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            conninfo=config.database_url,
            min_size=0,
            max_size=5,
            max_idle=300,
            open=False,
            check=AsyncConnectionPool.check_connection,
            kwargs={"row_factory": dict_row, "autocommit": True},
        )
        await _pool.open(wait=True, timeout=10)
        logger.info("🐘 Пул подключений к БД инициализирован")
    return _pool


def with_db_retry(fn):
    """Ретрай на мёртвых коннектах Neon после autosuspend.

    На OperationalError/InterfaceError (включая AdminShutdown) —
    закрывает пул, открывает новый и повторяет запрос один раз.
    """
    @wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except RETRIABLE_DB_ERRORS as e:
            logger.warning(
                f"🐘 Коннект сдох в {fn.__name__} — пересоздаю пул и повторяю: {e.__class__.__name__}"
            )
            await close_db()
            return await fn(*args, **kwargs)
    return wrapper


@with_db_retry
async def init_db():
    pool = await get_pool()
    async with pool.connection() as conn:
        await ensure_core_schema(conn)
        await _acquire_migration_lock(conn)
        try:
            await run_migrations(conn)
        finally:
            await _release_migration_lock(conn)
        await seed_default_content(conn)


MIGRATION_LOCK_ID = 773_001_20260508


async def _acquire_migration_lock(conn) -> None:
    await conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_ID,))


async def _release_migration_lock(conn) -> None:
    await conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_ID,))


async def ensure_core_schema(conn) -> None:
    await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id   BIGINT PRIMARY KEY,
                username  VARCHAR(255),
                first_name VARCHAR(255),
                last_name VARCHAR(255),
                is_banned BOOLEAN DEFAULT FALSE,
                ai_messages_used INT DEFAULT 0,
                ai_bonus INT DEFAULT 0,
                ai_limit_reset_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '12 hours',
                last_menu_msg_id BIGINT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            ALTER TABLE users ADD COLUMN IF NOT EXISTS last_menu_msg_id BIGINT;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_bonus INT DEFAULT 0;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS zefirki INT DEFAULT 0;

            CREATE TABLE IF NOT EXISTS transactions (
                id         SERIAL PRIMARY KEY,
                user_id    BIGINT REFERENCES users(user_id),
                amount     INT NOT NULL,
                reason     VARCHAR(100) NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_transactions_user_created
                ON transactions (user_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS tickets (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT REFERENCES users(user_id),
                message     TEXT NOT NULL,
                ai_summary  TEXT,
                status      VARCHAR(20) DEFAULT 'open',
                admin_reply TEXT,
                seen_at     TIMESTAMPTZ,
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            );

            ALTER TABLE tickets ADD COLUMN IF NOT EXISTS seen_at TIMESTAMPTZ;

            CREATE TABLE IF NOT EXISTS ai_conversations (
                id         SERIAL PRIMARY KEY,
                user_id    BIGINT REFERENCES users(user_id),
                role       VARCHAR(10) NOT NULL,
                content    TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS user_consents (
                user_id     BIGINT NOT NULL,
                doc_version TEXT NOT NULL,
                doc_hash    TEXT NOT NULL,
                accepted_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (user_id, doc_version)
            );
            
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    TEXT PRIMARY KEY,
                checksum   TEXT NOT NULL,
                applied_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)


MIGRATIONS: tuple[tuple[str, str], ...] = (
    (
        "20260508_001_game_economy_schema",
        """

            CREATE TABLE IF NOT EXISTS items (
                id          SERIAL PRIMARY KEY,
                code        TEXT UNIQUE NOT NULL,
                name        TEXT NOT NULL,
                description TEXT DEFAULT '',
                rarity      TEXT NOT NULL,
                item_type   TEXT NOT NULL,
                category    TEXT NOT NULL DEFAULT 'collectible',
                effect_json JSONB DEFAULT '{}'::jsonb,
                base_price  INT NOT NULL DEFAULT 10,
                shop_price  INT,
                is_shop_item BOOLEAN NOT NULL DEFAULT FALSE,
                sellable    BOOLEAN NOT NULL DEFAULT TRUE,
                usable      BOOLEAN NOT NULL DEFAULT FALSE,
                is_active   BOOLEAN NOT NULL DEFAULT TRUE,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );

            ALTER TABLE items ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'collectible';
            ALTER TABLE items ADD COLUMN IF NOT EXISTS effect_json JSONB DEFAULT '{}'::jsonb;
            ALTER TABLE items ADD COLUMN IF NOT EXISTS shop_price INT;
            ALTER TABLE items ADD COLUMN IF NOT EXISTS is_shop_item BOOLEAN NOT NULL DEFAULT FALSE;

            CREATE TABLE IF NOT EXISTS user_inventory (
                user_id    BIGINT REFERENCES users(user_id),
                item_id    INT REFERENCES items(id),
                quantity   INT NOT NULL DEFAULT 0,
                acquired_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (user_id, item_id)
            );

            CREATE TABLE IF NOT EXISTS cases (
                id          SERIAL PRIMARY KEY,
                code        TEXT UNIQUE NOT NULL,
                name        TEXT NOT NULL,
                description TEXT DEFAULT '',
                price       INT NOT NULL,
                is_active   BOOLEAN NOT NULL DEFAULT TRUE,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS case_rewards (
                id      SERIAL PRIMARY KEY,
                case_id INT REFERENCES cases(id) ON DELETE CASCADE,
                item_id INT REFERENCES items(id),
                weight  INT NOT NULL,
                UNIQUE (case_id, item_id)
            );

            CREATE TABLE IF NOT EXISTS market_listings (
                id         SERIAL PRIMARY KEY,
                seller_id  BIGINT REFERENCES users(user_id),
                item_id    INT REFERENCES items(id),
                price      INT NOT NULL,
                status     TEXT NOT NULL DEFAULT 'active',
                buyer_id   BIGINT REFERENCES users(user_id),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                closed_at  TIMESTAMPTZ
            );

            CREATE INDEX IF NOT EXISTS idx_market_active
                ON market_listings (status, created_at DESC);

            CREATE TABLE IF NOT EXISTS economy_events (
                id         SERIAL PRIMARY KEY,
                user_id    BIGINT REFERENCES users(user_id),
                amount     INT NOT NULL DEFAULT 0,
                reason     TEXT NOT NULL,
                item_id    INT REFERENCES items(id),
                listing_id INT REFERENCES market_listings(id),
                game_id    TEXT,
                meta       JSONB DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_economy_events_user_created
                ON economy_events (user_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS pets (
                id             BIGSERIAL PRIMARY KEY,
                owner_id       BIGINT NOT NULL REFERENCES users(user_id),
                user_id        BIGINT REFERENCES users(user_id),
                name           TEXT NOT NULL DEFAULT 'Зефирчик',
                level          INT NOT NULL DEFAULT 1,
                xp             INT NOT NULL DEFAULT 0,
                hunger         INT NOT NULL DEFAULT 70,
                mood           INT NOT NULL DEFAULT 70,
                energy         INT NOT NULL DEFAULT 70,
                species        TEXT NOT NULL DEFAULT 'cat',
                active         BOOLEAN NOT NULL DEFAULT TRUE,
                thirst         INT NOT NULL DEFAULT 70,
                cleanliness    INT NOT NULL DEFAULT 70,
                health         INT NOT NULL DEFAULT 90,
                affection      INT NOT NULL DEFAULT 50,
                cosmetic_item_id INT REFERENCES items(id),
                last_action_at TIMESTAMPTZ,
                created_at     TIMESTAMPTZ DEFAULT NOW(),
                updated_at     TIMESTAMPTZ DEFAULT NOW()
            );

            ALTER TABLE pets ADD COLUMN IF NOT EXISTS id BIGSERIAL;
            ALTER TABLE pets ADD COLUMN IF NOT EXISTS owner_id BIGINT REFERENCES users(user_id);
            ALTER TABLE pets ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES users(user_id);
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'pets' AND column_name = 'user_id'
                ) THEN
                    UPDATE pets SET owner_id = user_id WHERE owner_id IS NULL;
                END IF;
            END $$;
            ALTER TABLE pets ALTER COLUMN owner_id SET NOT NULL;
            DO $$
            DECLARE
                pk_cols text;
                pk_name text;
            BEGIN
                SELECT c.conname, string_agg(a.attname, ',' ORDER BY a.attnum)
                  INTO pk_name, pk_cols
                  FROM pg_constraint c
                  JOIN pg_class t ON t.oid = c.conrelid
                  JOIN unnest(c.conkey) ck(attnum) ON TRUE
                  JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ck.attnum
                 WHERE t.relname = 'pets' AND c.contype = 'p'
                 GROUP BY c.oid, c.conname;

                IF pk_cols IS NOT NULL AND pk_cols <> 'id' THEN
                    EXECUTE format('ALTER TABLE pets DROP CONSTRAINT %I', pk_name);
                END IF;
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint c
                    JOIN pg_class t ON t.oid = c.conrelid
                    WHERE t.relname = 'pets' AND c.contype = 'p'
                ) THEN
                    ALTER TABLE pets ADD PRIMARY KEY (id);
                END IF;
            END $$;
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'pets' AND column_name = 'user_id'
                ) THEN
                    ALTER TABLE pets ALTER COLUMN user_id DROP NOT NULL;
                END IF;
            END $$;
            ALTER TABLE pets ADD COLUMN IF NOT EXISTS cosmetic_item_id INT REFERENCES items(id);
            ALTER TABLE pets ADD COLUMN IF NOT EXISTS species TEXT NOT NULL DEFAULT 'cat';
            ALTER TABLE pets ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE;
            ALTER TABLE pets ADD COLUMN IF NOT EXISTS thirst INT NOT NULL DEFAULT 70;
            ALTER TABLE pets ADD COLUMN IF NOT EXISTS cleanliness INT NOT NULL DEFAULT 70;
            ALTER TABLE pets ADD COLUMN IF NOT EXISTS health INT NOT NULL DEFAULT 90;
            ALTER TABLE pets ADD COLUMN IF NOT EXISTS affection INT NOT NULL DEFAULT 50;
            UPDATE pets p
               SET active = FALSE
              FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY owner_id
                               ORDER BY active DESC, updated_at DESC, id DESC
                           ) AS rn
                    FROM pets
                   ) ranked
             WHERE p.id = ranked.id AND ranked.rn > 1 AND p.active = TRUE;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_pets_owner_species
                ON pets (owner_id, species);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_pets_one_active
                ON pets (owner_id) WHERE active = TRUE;

            CREATE TABLE IF NOT EXISTS pet_actions (
                user_id     BIGINT REFERENCES users(user_id),
                action      TEXT NOT NULL,
                action_date DATE NOT NULL DEFAULT CURRENT_DATE,
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (user_id, action, action_date)
            );

            CREATE TABLE IF NOT EXISTS pve_games (
                id         TEXT PRIMARY KEY,
                user_id    BIGINT REFERENCES users(user_id),
                game_type  TEXT NOT NULL,
                stake      INT NOT NULL DEFAULT 0,
                status     TEXT NOT NULL DEFAULT 'active',
                state      JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS game_rooms (
                id          TEXT PRIMARY KEY,
                game_type   TEXT NOT NULL,
                creator_id  BIGINT REFERENCES users(user_id),
                opponent_id BIGINT REFERENCES users(user_id),
                creator_chat_id BIGINT,
                creator_msg_id  BIGINT,
                opponent_chat_id BIGINT,
                opponent_msg_id  BIGINT,
                stake       INT NOT NULL DEFAULT 0,
                status      TEXT NOT NULL DEFAULT 'waiting',
                turn_user_id BIGINT,
                board       TEXT NOT NULL DEFAULT '.........',
                winner_id   BIGINT,
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_game_rooms_status_created
                ON game_rooms (status, created_at DESC);
            ALTER TABLE game_rooms ADD COLUMN IF NOT EXISTS creator_chat_id BIGINT;
            ALTER TABLE game_rooms ADD COLUMN IF NOT EXISTS creator_msg_id BIGINT;
            ALTER TABLE game_rooms ADD COLUMN IF NOT EXISTS opponent_chat_id BIGINT;
            ALTER TABLE game_rooms ADD COLUMN IF NOT EXISTS opponent_msg_id BIGINT;

            CREATE TABLE IF NOT EXISTS game_reward_logs (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT REFERENCES users(user_id),
                amount      INT NOT NULL,
                reward_date DATE NOT NULL DEFAULT CURRENT_DATE,
                game_id     TEXT,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS shop_offers (
                id         SERIAL PRIMARY KEY,
                item_id    INT REFERENCES items(id),
                price      INT NOT NULL,
                title      TEXT NOT NULL,
                is_daily   BOOLEAN NOT NULL DEFAULT FALSE,
                is_active  BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_shop_offers_daily_item
                ON shop_offers (item_id)
                WHERE is_daily = TRUE;

            CREATE TABLE IF NOT EXISTS item_effects (
                item_id INT PRIMARY KEY REFERENCES items(id),
                effect_json JSONB DEFAULT '{}'::jsonb,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS daily_claims (
                user_id    BIGINT REFERENCES users(user_id),
                claim_date DATE NOT NULL DEFAULT CURRENT_DATE,
                amount     INT NOT NULL DEFAULT 0,
                item_id    INT REFERENCES items(id),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (user_id, claim_date)
            );

            CREATE TABLE IF NOT EXISTS pet_reactions (
                id         SERIAL PRIMARY KEY,
                species    TEXT NOT NULL,
                action     TEXT NOT NULL,
                mood       TEXT NOT NULL DEFAULT 'normal',
                text       TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """,
    ),
    (
        "20260508_002_pet_reaction_uniqueness",
        """
            DELETE FROM pet_reactions a
            USING pet_reactions b
            WHERE a.ctid < b.ctid
              AND a.species = b.species
              AND a.action = b.action
              AND a.mood = b.mood
              AND a.text = b.text;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_pet_reactions_unique_text
                ON pet_reactions (species, action, mood, text);
        """,
    ),
    (
        "20260509_001_ranked_game_sessions",
        """
            CREATE TABLE IF NOT EXISTS game_sessions (
                id              TEXT PRIMARY KEY,
                game_type       TEXT NOT NULL,
                mode            TEXT NOT NULL DEFAULT 'pvp',
                status          TEXT NOT NULL DEFAULT 'waiting',
                creator_id      BIGINT NOT NULL REFERENCES users(user_id),
                chat_id         BIGINT,
                stake           INT NOT NULL DEFAULT 0,
                ranked          BOOLEAN NOT NULL DEFAULT FALSE,
                min_players     INT NOT NULL DEFAULT 2,
                max_players     INT NOT NULL DEFAULT 2,
                current_turn_id BIGINT REFERENCES users(user_id),
                winner_id       BIGINT REFERENCES users(user_id),
                result          TEXT,
                state           JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                updated_at      TIMESTAMPTZ DEFAULT NOW(),
                expires_at      TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '30 minutes'
            );

            CREATE INDEX IF NOT EXISTS idx_game_sessions_status_created
                ON game_sessions (status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_game_sessions_type_status
                ON game_sessions (game_type, status, created_at DESC);

            CREATE TABLE IF NOT EXISTS game_session_players (
                session_id TEXT NOT NULL REFERENCES game_sessions(id) ON DELETE CASCADE,
                user_id    BIGINT NOT NULL REFERENCES users(user_id),
                username   TEXT,
                first_name TEXT,
                seat       INT NOT NULL,
                status     TEXT NOT NULL DEFAULT 'active',
                joined_at  TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (session_id, user_id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_game_session_players_seat
                ON game_session_players (session_id, seat);

            CREATE TABLE IF NOT EXISTS game_session_messages (
                session_id TEXT NOT NULL REFERENCES game_sessions(id) ON DELETE CASCADE,
                user_id    BIGINT NOT NULL REFERENCES users(user_id),
                chat_id    BIGINT NOT NULL,
                message_id BIGINT NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (session_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS game_chat_messages (
                id           BIGSERIAL PRIMARY KEY,
                session_id   TEXT NOT NULL REFERENCES game_sessions(id) ON DELETE CASCADE,
                user_id      BIGINT NOT NULL REFERENCES users(user_id),
                display_name TEXT NOT NULL,
                text         TEXT NOT NULL,
                created_at   TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_game_chat_messages_session_created
                ON game_chat_messages (session_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS rating_seasons (
                id         SERIAL PRIMARY KEY,
                code       TEXT UNIQUE NOT NULL,
                starts_at  TIMESTAMPTZ NOT NULL,
                ends_at    TIMESTAMPTZ NOT NULL,
                status     TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_rating_one_active
                ON rating_seasons (status) WHERE status = 'active';

            CREATE TABLE IF NOT EXISTS user_ratings (
                season_id      INT NOT NULL REFERENCES rating_seasons(id) ON DELETE CASCADE,
                user_id        BIGINT NOT NULL REFERENCES users(user_id),
                elo            INT NOT NULL DEFAULT 1000,
                wins           INT NOT NULL DEFAULT 0,
                losses         INT NOT NULL DEFAULT 0,
                draws          INT NOT NULL DEFAULT 0,
                games          INT NOT NULL DEFAULT 0,
                reward_claimed BOOLEAN NOT NULL DEFAULT FALSE,
                updated_at     TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (season_id, user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_user_ratings_leaderboard
                ON user_ratings (season_id, elo DESC, games DESC);

            CREATE TABLE IF NOT EXISTS ranked_game_results (
                id         BIGSERIAL PRIMARY KEY,
                season_id  INT NOT NULL REFERENCES rating_seasons(id),
                session_id TEXT NOT NULL UNIQUE,
                game_type  TEXT NOT NULL,
                user_a     BIGINT NOT NULL REFERENCES users(user_id),
                user_b     BIGINT NOT NULL REFERENCES users(user_id),
                winner_id  BIGINT REFERENCES users(user_id),
                is_draw    BOOLEAN NOT NULL DEFAULT FALSE,
                old_a      INT NOT NULL,
                old_b      INT NOT NULL,
                new_a      INT NOT NULL,
                new_b      INT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            INSERT INTO rating_seasons (code, starts_at, ends_at, status)
            SELECT 'season-' || TO_CHAR(CURRENT_DATE, 'YYYYMMDD'),
                   NOW(),
                   NOW() + INTERVAL '14 days',
                   'active'
            WHERE NOT EXISTS (SELECT 1 FROM rating_seasons WHERE status = 'active');
        """,
    ),
    (
        "20260509_002_news_and_quiz_ranked",
        """
            CREATE TABLE IF NOT EXISTS news_posts (
                id                  BIGSERIAL PRIMARY KEY,
                kind                TEXT NOT NULL DEFAULT 'news',
                title               TEXT NOT NULL,
                body                TEXT NOT NULL,
                status              TEXT NOT NULL DEFAULT 'draft',
                release_version     TEXT,
                notify              BOOLEAN NOT NULL DEFAULT TRUE,
                published_at        TIMESTAMPTZ,
                notification_until  TIMESTAMPTZ,
                created_by          BIGINT REFERENCES users(user_id),
                created_at          TIMESTAMPTZ DEFAULT NOW(),
                updated_at          TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_news_posts_status_published
                ON news_posts (status, published_at DESC);
            CREATE INDEX IF NOT EXISTS idx_news_posts_kind_published
                ON news_posts (kind, published_at DESC);

            CREATE TABLE IF NOT EXISTS user_news_settings (
                user_id             BIGINT PRIMARY KEY REFERENCES users(user_id),
                notify_mode         TEXT NOT NULL DEFAULT 'all',
                last_seen_post_id   BIGINT REFERENCES news_posts(id),
                notice_post_id      BIGINT REFERENCES news_posts(id),
                notice_msg_id       BIGINT,
                notice_sent_at      TIMESTAMPTZ,
                updated_at          TIMESTAMPTZ DEFAULT NOW()
            );

            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'ranked_game_results_session_id_key'
                ) THEN
                    ALTER TABLE ranked_game_results DROP CONSTRAINT ranked_game_results_session_id_key;
                END IF;
            END $$;

            CREATE UNIQUE INDEX IF NOT EXISTS idx_ranked_game_results_pair
                ON ranked_game_results (session_id, user_a, user_b);
        """,
    ),
    (
        "20260510_001_prod_stabilization",
        """
            CREATE TABLE IF NOT EXISTS game_scheduled_events (
                id           BIGSERIAL PRIMARY KEY,
                session_id   TEXT NOT NULL REFERENCES game_sessions(id) ON DELETE CASCADE,
                event_type   TEXT NOT NULL,
                run_at       TIMESTAMPTZ NOT NULL,
                status       TEXT NOT NULL DEFAULT 'pending',
                payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                processed_at TIMESTAMPTZ
            );

            CREATE INDEX IF NOT EXISTS idx_game_scheduled_events_due
                ON game_scheduled_events (status, run_at);
            CREATE INDEX IF NOT EXISTS idx_game_session_players_user
                ON game_session_players (user_id, session_id);
            CREATE INDEX IF NOT EXISTS idx_game_sessions_status_expires
                ON game_sessions (status, expires_at);
            CREATE INDEX IF NOT EXISTS idx_game_sessions_creator_status
                ON game_sessions (creator_id, status);
            CREATE INDEX IF NOT EXISTS idx_market_listings_status_item_created
                ON market_listings (status, item_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_news_posts_notice_due
                ON news_posts (status, notification_until, published_at DESC);
        """,
    ),
)


def _migration_checksum(sql: str) -> str:
    return sha256(sql.encode("utf-8")).hexdigest()[:16]


async def run_migrations(conn) -> None:
    for version, sql in MIGRATIONS:
        checksum = _migration_checksum(sql)
        cur = await conn.execute(
            "SELECT checksum FROM schema_migrations WHERE version = %s",
            (version,),
        )
        existing = await cur.fetchone()
        if existing:
            if existing["checksum"] != checksum:
                raise RuntimeError(
                    f"Migration {version} checksum mismatch: "
                    f"{existing['checksum']} != {checksum}"
                )
            continue

        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute(
                """
                INSERT INTO schema_migrations (version, checksum)
                VALUES (%s, %s)
                """,
                (version, checksum),
            )


async def seed_default_content(conn) -> None:
    await conn.execute("""

            INSERT INTO items (code, name, description, rarity, item_type, category, effect_json, base_price, shop_price, is_shop_item, sellable, usable)
            VALUES
                ('crumb', 'Крошка зефира', 'Самая простая коллекционная мелочь.', 'trash', 'collectible', 'collectible', '{}'::jsonb, 5, NULL, FALSE, TRUE, FALSE),
                ('ribbon', 'Ленточка питомца', 'Милый аксессуар для питомца.', 'common', 'cosmetic', 'clothes', '{}'::jsonb, 25, 60, TRUE, TRUE, FALSE),
                ('ai_cookie', 'AI-печенька', 'Добавляет 10 бонусных AI-запросов.', 'uncommon', 'ai_bonus', 'tech', '{"ai_bonus": 10}'::jsonb, 60, 120, TRUE, TRUE, TRUE),
                ('pet_snack', 'Лакомство питомца', 'Хороший перекус для питомца.', 'rare', 'pet_boost', 'food', '{"hunger": 25, "mood": 10, "energy": 10}'::jsonb, 120, 180, TRUE, TRUE, TRUE),
                ('golden_ticket', 'Золотой билет', 'Коллекционный билет для игровых событий.', 'epic', 'game_ticket', 'collectible', '{}'::jsonb, 350, NULL, FALSE, TRUE, FALSE),
                ('legend_star', 'Легендарная звезда', 'Редкий предмет для коллекции и торговли.', 'legendary', 'collectible', 'collectible', '{}'::jsonb, 1000, NULL, FALSE, TRUE, FALSE),
                ('cheap_food', 'Сухой корм', 'Недорогая еда: сытно, но без восторга.', 'common', 'pet_consumable', 'food', '{"hunger": 18, "health": -1, "mood": 1}'::jsonb, 20, 35, TRUE, TRUE, TRUE),
                ('premium_food', 'Премиум-рагу', 'Качественная еда для здоровья и настроения.', 'rare', 'pet_consumable', 'food', '{"hunger": 35, "health": 4, "mood": 8, "affection": 2}'::jsonb, 140, 210, TRUE, TRUE, TRUE),
                ('water_bottle', 'Бутылочка воды', 'Восстанавливает жажду питомца.', 'common', 'pet_consumable', 'drink', '{"thirst": 30, "health": 1}'::jsonb, 18, 30, TRUE, TRUE, TRUE),
                ('berry_soda', 'Ягодная газировка', 'Сладко, бодро, чуть-чуть безумно.', 'uncommon', 'pet_consumable', 'drink', '{"thirst": 20, "mood": 10, "energy": 4}'::jsonb, 55, 90, TRUE, TRUE, TRUE),
                ('shampoo', 'Пенный шампунь', 'Чистота и приятный запах.', 'uncommon', 'pet_consumable', 'care', '{"cleanliness": 35, "health": 2, "mood": 3}'::jsonb, 70, 110, TRUE, TRUE, TRUE),
                ('toy_mouse', 'Игрушечная мышь', 'Игрушка для активной игры.', 'common', 'pet_toy', 'toy', '{"mood": 12, "energy": -8, "xp": 10}'::jsonb, 45, 80, TRUE, TRUE, TRUE),
                ('music_speaker', 'Мини-колонка', 'Включает питомцу музыку и поднимает настроение.', 'rare', 'pet_toy', 'tech', '{"mood": 22, "energy": 3, "xp": 8}'::jsonb, 220, 360, TRUE, TRUE, TRUE),
                ('red_cap', 'Рыжая кепка', 'Стильная кепка для питомца.', 'uncommon', 'cosmetic', 'clothes', '{}'::jsonb, 95, 150, TRUE, TRUE, FALSE),
                ('squirrel_hoodie', 'Худи Белочки', 'Мемный образ для самых шумных прогулок.', 'epic', 'cosmetic', 'clothes', '{}'::jsonb, 400, 650, TRUE, TRUE, FALSE),
                ('season_crown_legend', 'Корона сезона', 'Легендарная награда за первое место в ranked-сезоне.', 'legendary', 'cosmetic', 'clothes', '{}'::jsonb, 1200, NULL, FALSE, TRUE, FALSE),
                ('season_medal_epic', 'Медаль дуэлянта', 'Эпическая награда за топ-3 ranked-сезона.', 'epic', 'cosmetic', 'clothes', '{}'::jsonb, 650, NULL, FALSE, TRUE, FALSE),
                ('season_badge_rare', 'Значок рейтинга', 'Редкая награда за топ-10 ranked-сезона.', 'rare', 'cosmetic', 'clothes', '{}'::jsonb, 260, NULL, FALSE, TRUE, FALSE)
            ON CONFLICT (code) DO UPDATE
                SET name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    rarity = EXCLUDED.rarity,
                    item_type = EXCLUDED.item_type,
                    category = EXCLUDED.category,
                    effect_json = EXCLUDED.effect_json,
                    base_price = EXCLUDED.base_price,
                    shop_price = EXCLUDED.shop_price,
                    is_shop_item = EXCLUDED.is_shop_item,
                    sellable = EXCLUDED.sellable,
                    usable = EXCLUDED.usable;

            INSERT INTO cases (code, name, description, price, is_active)
            VALUES
                ('starter', 'Стартовый кейс', 'Недорогой кейс с базовыми предметами.', 50, TRUE),
                ('sweet', 'Сладкий кейс', 'Дороже, но шанс редких предметов выше.', 150, TRUE)
            ON CONFLICT (code) DO UPDATE
                SET name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    price = EXCLUDED.price;

            INSERT INTO case_rewards (case_id, item_id, weight)
            SELECT c.id, i.id, v.weight
            FROM (VALUES
                ('starter', 'crumb', 45),
                ('starter', 'ribbon', 30),
                ('starter', 'ai_cookie', 15),
                ('starter', 'pet_snack', 8),
                ('starter', 'golden_ticket', 2),
                ('sweet', 'ribbon', 35),
                ('sweet', 'ai_cookie', 25),
                ('sweet', 'pet_snack', 22),
                ('sweet', 'golden_ticket', 14),
                ('sweet', 'legend_star', 4)
            ) AS v(case_code, item_code, weight)
            JOIN cases c ON c.code = v.case_code
            JOIN items i ON i.code = v.item_code
            ON CONFLICT (case_id, item_id) DO UPDATE
                SET weight = EXCLUDED.weight;

            INSERT INTO shop_offers (item_id, price, title, is_daily, is_active)
            SELECT i.id, i.shop_price, i.name, TRUE, TRUE
            FROM items i
            WHERE i.is_shop_item = TRUE AND i.shop_price IS NOT NULL
            ON CONFLICT (item_id) WHERE is_daily = TRUE DO UPDATE
                SET price = EXCLUDED.price,
                    title = EXCLUDED.title;

            INSERT INTO item_effects (item_id, effect_json)
            SELECT id, effect_json FROM items
            ON CONFLICT (item_id) DO UPDATE
                SET effect_json = EXCLUDED.effect_json,
                    updated_at = NOW();

            DELETE FROM pet_reactions a
            USING pet_reactions b
            WHERE a.ctid < b.ctid
              AND a.species = b.species
              AND a.action = b.action
              AND a.mood = b.mood
              AND a.text = b.text;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_pet_reactions_unique_text
                ON pet_reactions (species, action, mood, text);

            INSERT INTO pet_reactions (species, action, mood, text)
            VALUES
                ('cat', 'feed', 'normal', 'Котик довольно щурится и аккуратно доедает миску.'),
                ('cat', 'play', 'happy', 'Котик носится кругами и делает вид, что это всё случайно.'),
                ('dog', 'feed', 'normal', 'Пёсель радостно виляет хвостом и просит добавки.'),
                ('dog', 'play', 'happy', 'Пёсель приносит игрушку обратно быстрее, чем ты успел моргнуть.'),
                ('squirrel', 'feed', 'normal', 'Белочка хватает еду и смотрит так, будто у неё уже есть план.'),
                ('squirrel', 'play', 'happy', 'Белочка устраивает маленький хаос, но выглядит счастливой.'),
                ('squirrel', 'drink', 'happy', 'Белочка делает глоток и заявляет: «ну всё, движ начинается».')
            ON CONFLICT (species, action, mood, text) DO NOTHING;
        """)


async def close_db():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("🐘 Пул подключений закрыт")
