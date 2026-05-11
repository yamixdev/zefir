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
    (
        "20260510_002_admin_ops_stability",
        """
            ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active_at TIMESTAMPTZ;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS last_action TEXT;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS last_chat_id BIGINT;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS ban_reason_code TEXT;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS ban_reason_text TEXT;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS banned_at TIMESTAMPTZ;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS banned_by BIGINT REFERENCES users(user_id);
            ALTER TABLE users ADD COLUMN IF NOT EXISTS bot_blocked_at TIMESTAMPTZ;

            CREATE INDEX IF NOT EXISTS idx_users_last_active
                ON users (last_active_at DESC);

            CREATE TABLE IF NOT EXISTS user_activity_events (
                id          BIGSERIAL PRIMARY KEY,
                user_id     BIGINT REFERENCES users(user_id),
                event_type  TEXT NOT NULL,
                action      TEXT NOT NULL,
                chat_id     BIGINT,
                context     JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_user_activity_user_created
                ON user_activity_events (user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_user_activity_created
                ON user_activity_events (created_at DESC);

            CREATE TABLE IF NOT EXISTS bot_incidents (
                id             BIGSERIAL PRIMARY KEY,
                user_id         BIGINT REFERENCES users(user_id),
                chat_id         BIGINT,
                event_type      TEXT NOT NULL DEFAULT 'auto',
                action          TEXT,
                status          TEXT NOT NULL DEFAULT 'open',
                title           TEXT NOT NULL,
                message         TEXT,
                traceback_text  TEXT,
                admin_note      TEXT,
                closed_by       BIGINT REFERENCES users(user_id),
                closed_at       TIMESTAMPTZ,
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                updated_at      TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_bot_incidents_status_created
                ON bot_incidents (status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_bot_incidents_user_created
                ON bot_incidents (user_id, created_at DESC);

            ALTER TABLE game_rooms ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ
                DEFAULT NOW() + INTERVAL '5 minutes';
            UPDATE game_rooms
               SET expires_at = COALESCE(expires_at, updated_at + INTERVAL '5 minutes', NOW() + INTERVAL '5 minutes')
             WHERE status IN ('waiting', 'active');
            CREATE INDEX IF NOT EXISTS idx_game_rooms_status_expires
                ON game_rooms (status, expires_at);
        """,
    ),
    (
        "20260511_001_content_time_and_pets",
        """
            ALTER TABLE game_reward_logs ADD COLUMN IF NOT EXISTS reward_date_msk DATE;
            UPDATE game_reward_logs
               SET reward_date_msk = COALESCE(reward_date_msk, reward_date)
             WHERE reward_date_msk IS NULL;
            ALTER TABLE game_reward_logs
                ALTER COLUMN reward_date SET DEFAULT ((NOW() AT TIME ZONE 'Europe/Moscow')::date),
                ALTER COLUMN reward_date_msk SET DEFAULT ((NOW() AT TIME ZONE 'Europe/Moscow')::date);
            CREATE INDEX IF NOT EXISTS idx_game_reward_logs_user_msk
                ON game_reward_logs (user_id, reward_date_msk);

            ALTER TABLE daily_claims
                ALTER COLUMN claim_date SET DEFAULT ((NOW() AT TIME ZONE 'Europe/Moscow')::date);
            ALTER TABLE pet_actions
                ALTER COLUMN action_date SET DEFAULT ((NOW() AT TIME ZONE 'Europe/Moscow')::date);

            ALTER TABLE cases ADD COLUMN IF NOT EXISTS required_key_item_id INT REFERENCES items(id);
            ALTER TABLE cases ADD COLUMN IF NOT EXISTS min_level INT NOT NULL DEFAULT 1;
            ALTER TABLE cases ADD COLUMN IF NOT EXISTS sort_order INT NOT NULL DEFAULT 100;

            CREATE TABLE IF NOT EXISTS shop_rotations (
                rotation_key TEXT PRIMARY KEY,
                starts_at    TIMESTAMPTZ NOT NULL,
                ends_at      TIMESTAMPTZ NOT NULL,
                created_at   TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS pet_homes (
                user_id      BIGINT PRIMARY KEY REFERENCES users(user_id),
                level        INT NOT NULL DEFAULT 1,
                active_room  TEXT NOT NULL DEFAULT 'kitchen',
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                updated_at   TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS pet_home_items (
                user_id      BIGINT REFERENCES users(user_id),
                room         TEXT NOT NULL,
                item_id      INT REFERENCES items(id),
                installed_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (user_id, room, item_id)
            );

            CREATE TABLE IF NOT EXISTS pet_status_events (
                id         BIGSERIAL PRIMARY KEY,
                user_id    BIGINT REFERENCES users(user_id),
                pet_id     BIGINT REFERENCES pets(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                text       TEXT NOT NULL,
                meta       JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_pet_status_events_user_created
                ON pet_status_events (user_id, created_at DESC);

            ALTER TABLE pets ADD COLUMN IF NOT EXISTS room TEXT NOT NULL DEFAULT 'kitchen';
            ALTER TABLE pets ADD COLUMN IF NOT EXISTS last_decay_at TIMESTAMPTZ;
            UPDATE pets SET last_decay_at = COALESCE(last_decay_at, updated_at, NOW()) WHERE last_decay_at IS NULL;
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
                ('soft_crumb', 'Мягкая крошка', 'Небольшой сувенир из обычных прогулок.', 'trash', 'collectible', 'collectible', '{}'::jsonb, 8, NULL, FALSE, TRUE, FALSE),
                ('paper_star', 'Бумажная звёздочка', 'Лёгкая коллекционная безделушка.', 'trash', 'collectible', 'collectible', '{}'::jsonb, 10, NULL, FALSE, TRUE, FALSE),
                ('ai_cookie', 'AI-печенька', 'Добавляет 10 бонусных AI-запросов.', 'uncommon', 'ai_bonus', 'tech', '{"ai_bonus": 10}'::jsonb, 60, 120, TRUE, TRUE, TRUE),
                ('ai_muffin', 'AI-маффин', 'Добавляет 25 бонусных AI-запросов.', 'rare', 'ai_bonus', 'tech', '{"ai_bonus": 25}'::jsonb, 150, 260, TRUE, TRUE, TRUE),

                ('cheap_food', 'Сухой корм', 'Недорогая еда: сытно, но без восторга.', 'common', 'pet_consumable', 'food', '{"hunger": 18, "health": -1, "mood": 1}'::jsonb, 20, 35, TRUE, TRUE, TRUE),
                ('fish_bits', 'Рыбные кусочки', 'Котики особенно ценят этот запах.', 'uncommon', 'pet_consumable', 'food', '{"hunger": 24, "mood": 5, "affection": 1}'::jsonb, 45, 75, TRUE, TRUE, TRUE),
                ('meat_bowl', 'Мясная миска', 'Плотный обед для активного питомца.', 'uncommon', 'pet_consumable', 'food', '{"hunger": 28, "energy": 4, "health": 1}'::jsonb, 55, 90, TRUE, TRUE, TRUE),
                ('veggie_mix', 'Овощной микс', 'Лёгкая еда, полезная для здоровья.', 'common', 'pet_consumable', 'food', '{"hunger": 16, "health": 3}'::jsonb, 30, 50, TRUE, TRUE, TRUE),
                ('nut_mix', 'Ореховая смесь', 'Белочка точно оценит запас на потом.', 'uncommon', 'pet_consumable', 'food', '{"hunger": 22, "mood": 4, "energy": 3}'::jsonb, 50, 85, TRUE, TRUE, TRUE),
                ('premium_food', 'Премиум-рагу', 'Качественная еда для здоровья и настроения.', 'rare', 'pet_consumable', 'food', '{"hunger": 35, "health": 4, "mood": 8, "affection": 2}'::jsonb, 140, 210, TRUE, TRUE, TRUE),
                ('chef_plate', 'Тарелка от шефа', 'Редкий ужин, после которого питомец заметно бодрее.', 'epic', 'pet_consumable', 'food', '{"hunger": 45, "health": 7, "mood": 12, "affection": 4}'::jsonb, 360, 560, TRUE, TRUE, TRUE),
                ('pet_snack', 'Лакомство питомца', 'Хороший перекус для питомца.', 'rare', 'pet_boost', 'food', '{"hunger": 25, "mood": 10, "energy": 10}'::jsonb, 120, 180, TRUE, TRUE, TRUE),
                ('marshmallow_treat', 'Зефирное лакомство', 'Маленькая сладость для хорошего настроения.', 'uncommon', 'pet_consumable', 'food', '{"hunger": 12, "mood": 14, "affection": 2}'::jsonb, 70, 115, TRUE, TRUE, TRUE),

                ('water_bottle', 'Бутылочка воды', 'Восстанавливает жажду питомца.', 'common', 'pet_consumable', 'drink', '{"thirst": 30, "health": 1}'::jsonb, 18, 30, TRUE, TRUE, TRUE),
                ('clean_water_bowl', 'Чистая миска воды', 'Простой и надёжный способ напоить питомца.', 'common', 'pet_consumable', 'drink', '{"thirst": 24, "mood": 1}'::jsonb, 22, 38, TRUE, TRUE, TRUE),
                ('berry_soda', 'Ягодная газировка', 'Сладко, бодро, но без лишней суеты.', 'uncommon', 'pet_consumable', 'drink', '{"thirst": 20, "mood": 10, "energy": 4}'::jsonb, 55, 90, TRUE, TRUE, TRUE),
                ('mint_drink', 'Мятный напиток', 'Освежает и немного успокаивает.', 'uncommon', 'pet_consumable', 'drink', '{"thirst": 28, "health": 2, "mood": 3}'::jsonb, 65, 100, TRUE, TRUE, TRUE),
                ('energy_drop', 'Бодрая капля', 'Немного энергии перед игрой.', 'rare', 'pet_consumable', 'drink', '{"thirst": 12, "energy": 18, "mood": 4}'::jsonb, 130, 210, TRUE, TRUE, TRUE),

                ('shampoo', 'Пенный шампунь', 'Чистота и приятный запах.', 'uncommon', 'pet_consumable', 'care', '{"cleanliness": 35, "health": 2, "mood": 3}'::jsonb, 70, 110, TRUE, TRUE, TRUE),
                ('soft_towel', 'Мягкое полотенце', 'Быстро возвращает уют после мытья.', 'common', 'pet_consumable', 'care', '{"cleanliness": 18, "mood": 4}'::jsonb, 35, 60, TRUE, TRUE, TRUE),
                ('pet_brush', 'Щётка для шерсти', 'Уход без спешки и лишнего стресса.', 'uncommon', 'pet_consumable', 'care', '{"cleanliness": 22, "affection": 3, "mood": 3}'::jsonb, 65, 105, TRUE, TRUE, TRUE),
                ('first_aid', 'Аптечка заботы', 'Помогает, если питомец устал или приболел.', 'rare', 'pet_consumable', 'care', '{"health": 24, "mood": 2, "energy": -2}'::jsonb, 150, 240, TRUE, TRUE, TRUE),
                ('spa_foam', 'Спа-пенка', 'Дорогой уход для чистоты и настроения.', 'epic', 'pet_consumable', 'care', '{"cleanliness": 45, "health": 5, "mood": 10, "affection": 3}'::jsonb, 320, 520, TRUE, TRUE, TRUE),

                ('toy_mouse', 'Игрушечная мышь', 'Игрушка для активной игры.', 'common', 'pet_toy', 'toy', '{"mood": 12, "energy": -8, "xp": 10}'::jsonb, 45, 80, TRUE, TRUE, TRUE),
                ('rubber_ball', 'Резиновый мячик', 'Простая игра на пару минут.', 'common', 'pet_toy', 'toy', '{"mood": 10, "energy": -6, "xp": 8}'::jsonb, 35, 65, TRUE, TRUE, TRUE),
                ('frisbee', 'Лёгкий фрисби', 'Подходит для двора и тренировки реакции.', 'uncommon', 'pet_toy', 'toy', '{"mood": 16, "energy": -10, "xp": 14}'::jsonb, 85, 140, TRUE, TRUE, TRUE),
                ('laser_pointer', 'Лазерная указка', 'Быстрая игра для внимательного питомца.', 'rare', 'pet_toy', 'toy', '{"mood": 22, "energy": -14, "xp": 20}'::jsonb, 180, 300, TRUE, TRUE, TRUE),
                ('puzzle_box', 'Коробка-головоломка', 'Питомец получает опыт, пока ищет решение.', 'rare', 'pet_toy', 'toy', '{"mood": 12, "energy": -8, "xp": 26, "affection": 2}'::jsonb, 210, 340, TRUE, TRUE, TRUE),
                ('training_tunnel', 'Тренировочный тоннель', 'Игрушка для активных забегов.', 'epic', 'pet_toy', 'toy', '{"mood": 24, "energy": -18, "xp": 34, "affection": 3}'::jsonb, 420, 680, TRUE, TRUE, TRUE),
                ('music_speaker', 'Мини-колонка', 'Включает питомцу музыку и поднимает настроение.', 'rare', 'pet_toy', 'tech', '{"mood": 22, "energy": 3, "xp": 8}'::jsonb, 220, 360, TRUE, TRUE, TRUE),
                ('pocket_player', 'Карманный плеер', 'Тихая музыка для отдыха питомца.', 'uncommon', 'pet_toy', 'tech', '{"mood": 14, "energy": 4, "xp": 6}'::jsonb, 120, 190, TRUE, TRUE, TRUE),

                ('ribbon', 'Ленточка питомца', 'Милый аксессуар для питомца.', 'common', 'cosmetic', 'clothes', '{"cosmetic_slot": "neck"}'::jsonb, 25, 60, TRUE, TRUE, FALSE),
                ('red_cap', 'Рыжая кепка', 'Стильная кепка для питомца.', 'uncommon', 'cosmetic', 'clothes', '{"cosmetic_slot": "head"}'::jsonb, 95, 150, TRUE, TRUE, FALSE),
                ('blue_cap', 'Синяя кепка', 'Спокойный образ на каждый день.', 'common', 'cosmetic', 'clothes', '{"cosmetic_slot": "head"}'::jsonb, 70, 120, TRUE, TRUE, FALSE),
                ('raincoat', 'Дождевик', 'Для прогулок, когда погода спорная.', 'rare', 'cosmetic', 'clothes', '{"cosmetic_slot": "body"}'::jsonb, 230, 380, TRUE, TRUE, FALSE),
                ('squirrel_hoodie', 'Худи Белочки', 'Рыжий образ для самых шумных прогулок.', 'epic', 'cosmetic', 'clothes', '{"cosmetic_slot": "body"}'::jsonb, 400, 650, TRUE, TRUE, FALSE),
                ('star_glasses', 'Звёздные очки', 'Питомец выглядит так, будто знает секрет.', 'rare', 'cosmetic', 'accessory', '{"cosmetic_slot": "face"}'::jsonb, 260, 430, TRUE, TRUE, FALSE),
                ('silver_collar', 'Серебряный ошейник', 'Аккуратная редкая косметика.', 'rare', 'cosmetic', 'accessory', '{"cosmetic_slot": "neck"}'::jsonb, 300, 480, TRUE, TRUE, FALSE),
                ('tiny_backpack', 'Маленький рюкзак', 'Питомец будто собрался в путешествие.', 'uncommon', 'cosmetic', 'accessory', '{"cosmetic_slot": "back"}'::jsonb, 150, 240, TRUE, TRUE, FALSE),
                ('royal_cape', 'Королевская накидка', 'Эпичный образ для важного питомца.', 'epic', 'cosmetic', 'clothes', '{"cosmetic_slot": "body"}'::jsonb, 520, 820, TRUE, TRUE, FALSE),
                ('moon_crown', 'Лунная корона', 'Легендарная косметика с мягким свечением.', 'legendary', 'cosmetic', 'accessory', '{"cosmetic_slot": "head"}'::jsonb, 1400, NULL, FALSE, TRUE, FALSE),
                ('sunny_halo', 'Солнечный нимб', 'Легендарный аксессуар для коллекции.', 'legendary', 'cosmetic', 'accessory', '{"cosmetic_slot": "head"}'::jsonb, 1600, NULL, FALSE, TRUE, FALSE),

                ('basic_bowl', 'Обычная миска', 'Предмет кухни: немного замедляет голод.', 'common', 'home_item', 'home', '{"room": "kitchen", "home_bonus": {"hunger_decay": -1}}'::jsonb, 80, 130, TRUE, TRUE, TRUE),
                ('warm_bed', 'Тёплая лежанка', 'Предмет спальни: питомец лучше отдыхает.', 'uncommon', 'home_item', 'home', '{"room": "bedroom", "home_bonus": {"energy_restore": 2}}'::jsonb, 160, 260, TRUE, TRUE, TRUE),
                ('scratch_post', 'Когтеточка', 'Предмет игровой: помогает настроению.', 'uncommon', 'home_item', 'home', '{"room": "playroom", "home_bonus": {"mood_decay": -1}}'::jsonb, 150, 250, TRUE, TRUE, TRUE),
                ('bath_mat', 'Коврик для ванной', 'Предмет ванной: уход проходит спокойнее.', 'common', 'home_item', 'home', '{"room": "bathroom", "home_bonus": {"cleanliness_decay": -1}}'::jsonb, 90, 150, TRUE, TRUE, TRUE),
                ('yard_lamp', 'Лампа для двора', 'Предмет двора: вечерние игры уютнее.', 'rare', 'home_item', 'home', '{"room": "yard", "home_bonus": {"mood": 2}}'::jsonb, 260, 430, TRUE, TRUE, TRUE),
                ('premium_bed', 'Премиум-лежанка', 'Эпичный предмет спальни для быстрого отдыха.', 'epic', 'home_item', 'home', '{"room": "bedroom", "home_bonus": {"energy_restore": 5, "health": 1}}'::jsonb, 620, 950, TRUE, TRUE, TRUE),
                ('smart_feeder', 'Умная кормушка', 'Редкий предмет кухни для стабильной сытости.', 'rare', 'home_item', 'home', '{"room": "kitchen", "home_bonus": {"hunger_decay": -2}}'::jsonb, 360, 580, TRUE, TRUE, TRUE),
                ('mini_fountain', 'Мини-фонтанчик', 'Предмет кухни: питомец чаще пьёт воду.', 'rare', 'home_item', 'home', '{"room": "kitchen", "home_bonus": {"thirst_decay": -2}}'::jsonb, 330, 540, TRUE, TRUE, TRUE),
                ('golden_room_set', 'Золотой набор домика', 'Легендарный набор для будущего большого дома.', 'legendary', 'home_item', 'home', '{"room": "all", "home_bonus": {"mood": 5, "health": 2}}'::jsonb, 2200, NULL, FALSE, TRUE, TRUE),

                ('second_pet_license', 'Лицензия на второго питомца', 'Открывает второго питомца при нужном уровне.', 'epic', 'unlock', 'collectible', '{"unlock_pet_slot": 2}'::jsonb, 800, NULL, FALSE, TRUE, FALSE),
                ('big_home_contract', 'Договор на большой домик', 'Редкий документ для третьего питомца.', 'legendary', 'unlock', 'collectible', '{"unlock_pet_slot": 3}'::jsonb, 1800, NULL, FALSE, TRUE, FALSE),
                ('bronze_key', 'Бронзовый ключ', 'Открывает бронзовый сундук.', 'rare', 'case_key', 'key', '{"case_key": "bronze"}'::jsonb, 220, NULL, FALSE, TRUE, FALSE),
                ('silver_key', 'Серебряный ключ', 'Открывает серебряный сундук.', 'epic', 'case_key', 'key', '{"case_key": "silver"}'::jsonb, 520, NULL, FALSE, TRUE, FALSE),
                ('gold_key', 'Золотой ключ', 'Открывает золотую капсулу.', 'legendary', 'case_key', 'key', '{"case_key": "gold"}'::jsonb, 1200, NULL, FALSE, TRUE, FALSE),
                ('golden_ticket', 'Золотой билет', 'Коллекционный билет для игровых событий.', 'epic', 'game_ticket', 'collectible', '{}'::jsonb, 350, NULL, FALSE, TRUE, FALSE),
                ('legend_star', 'Легендарная звезда', 'Редкий предмет для коллекции и торговли.', 'legendary', 'collectible', 'collectible', '{}'::jsonb, 1000, NULL, FALSE, TRUE, FALSE),
                ('season_crown_legend', 'Корона сезона', 'Легендарная награда за первое место в ranked-сезоне.', 'legendary', 'cosmetic', 'clothes', '{"cosmetic_slot": "head"}'::jsonb, 1200, NULL, FALSE, TRUE, FALSE),
                ('season_medal_epic', 'Медаль дуэлянта', 'Эпическая награда за топ-3 ranked-сезона.', 'epic', 'cosmetic', 'clothes', '{"cosmetic_slot": "neck"}'::jsonb, 650, NULL, FALSE, TRUE, FALSE),
                ('season_badge_rare', 'Значок рейтинга', 'Редкая награда за топ-10 ranked-сезона.', 'rare', 'cosmetic', 'clothes', '{"cosmetic_slot": "neck"}'::jsonb, 260, NULL, FALSE, TRUE, FALSE)
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

            INSERT INTO cases (code, name, description, price, required_key_item_id, min_level, sort_order, is_active)
            SELECT v.code, v.name, v.description, v.price, k.id, v.min_level, v.sort_order, TRUE
            FROM (VALUES
                ('starter', 'Стартовый кейс', 'Недорогой кейс с базовыми предметами.', 50, NULL, 1, 10),
                ('cozy', 'Уютный кейс', 'Еда, уход и предметы для домика.', 120, NULL, 1, 20),
                ('play', 'Игровой кейс', 'Игрушки, билеты и небольшой шанс ключа.', 220, NULL, 2, 30),
                ('bronze_chest', 'Бронзовый сундук', 'Улучшенные вещи. Нужен бронзовый ключ.', 0, 'bronze_key', 3, 40),
                ('silver_chest', 'Серебряный сундук', 'Эпические вещи. Нужен серебряный ключ.', 0, 'silver_key', 6, 50),
                ('gold_capsule', 'Золотая капсула', 'Лучший лут и легендарные предметы. Нужен золотой ключ.', 0, 'gold_key', 10, 60)
            ) AS v(code, name, description, price, key_code, min_level, sort_order)
            LEFT JOIN items k ON k.code = v.key_code
            ON CONFLICT (code) DO UPDATE
                SET name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    price = EXCLUDED.price,
                    required_key_item_id = EXCLUDED.required_key_item_id,
                    min_level = EXCLUDED.min_level,
                    sort_order = EXCLUDED.sort_order;

            INSERT INTO case_rewards (case_id, item_id, weight)
            SELECT c.id, i.id, v.weight
            FROM (VALUES
                ('starter', 'crumb', 35), ('starter', 'soft_crumb', 20), ('starter', 'cheap_food', 20), ('starter', 'water_bottle', 15), ('starter', 'ribbon', 8), ('starter', 'ai_cookie', 2),
                ('cozy', 'soft_towel', 18), ('cozy', 'shampoo', 16), ('cozy', 'basic_bowl', 15), ('cozy', 'warm_bed', 12), ('cozy', 'pet_brush', 12), ('cozy', 'premium_food', 10), ('cozy', 'smart_feeder', 4), ('cozy', 'silver_collar', 3),
                ('play', 'rubber_ball', 20), ('play', 'toy_mouse', 18), ('play', 'frisbee', 16), ('play', 'pocket_player', 12), ('play', 'laser_pointer', 8), ('play', 'golden_ticket', 6), ('play', 'bronze_key', 5), ('play', 'puzzle_box', 4),
                ('bronze_chest', 'red_cap', 20), ('bronze_chest', 'fish_bits', 18), ('bronze_chest', 'mini_fountain', 12), ('bronze_chest', 'star_glasses', 10), ('bronze_chest', 'first_aid', 10), ('bronze_chest', 'silver_key', 7), ('bronze_chest', 'raincoat', 6), ('bronze_chest', 'second_pet_license', 3),
                ('silver_chest', 'royal_cape', 18), ('silver_chest', 'training_tunnel', 16), ('silver_chest', 'spa_foam', 14), ('silver_chest', 'premium_bed', 12), ('silver_chest', 'squirrel_hoodie', 10), ('silver_chest', 'gold_key', 5), ('silver_chest', 'big_home_contract', 3), ('silver_chest', 'legend_star', 2),
                ('gold_capsule', 'moon_crown', 18), ('gold_capsule', 'sunny_halo', 16), ('gold_capsule', 'golden_room_set', 14), ('gold_capsule', 'big_home_contract', 12), ('gold_capsule', 'legend_star', 10), ('gold_capsule', 'season_crown_legend', 8), ('gold_capsule', 'gold_key', 5), ('gold_capsule', 'chef_plate', 4)
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
                ('cat', 'feed', 'happy', 'Котик довольно мурчит и остаётся рядом с миской ещё на минуту.'),
                ('cat', 'feed', 'sad', 'Котик ест спокойно, но явно ждёт больше внимания.'),
                ('cat', 'drink', 'normal', 'Котик делает несколько глотков и аккуратно умывается.'),
                ('cat', 'play', 'happy', 'Котик носится кругами и делает вид, что это всё случайно.'),
                ('cat', 'wash', 'normal', 'Котик терпит уход с важным видом, зато потом выглядит свежее.'),
                ('cat', 'sleep', 'normal', 'Котик сворачивается клубком и быстро находит удобное место.'),
                ('cat', 'heal', 'normal', 'Котик спокойно принимает заботу и чуть увереннее держится.'),
                ('cat', 'minigame', 'happy', 'Котик ловко просчитывает момент и делает красивый рывок.'),
                ('dog', 'feed', 'normal', 'Пёсель радостно виляет хвостом и просит добавки.'),
                ('dog', 'drink', 'normal', 'Пёсель шумно пьёт воду и сразу выглядит бодрее.'),
                ('dog', 'play', 'happy', 'Пёсель приносит игрушку обратно быстрее, чем ты успел моргнуть.'),
                ('dog', 'wash', 'normal', 'Пёсель сначала сомневается, но после ухода явно доволен.'),
                ('dog', 'sleep', 'normal', 'Пёсель укладывается рядом и быстро восстанавливает силы.'),
                ('dog', 'heal', 'normal', 'Пёсель спокойно даёт помочь и благодарно смотрит.'),
                ('dog', 'minigame', 'happy', 'Пёсель реагирует мгновенно и честно радуется результату.'),
                ('squirrel', 'feed', 'normal', 'Белочка хватает еду и смотрит так, будто у неё уже есть план.'),
                ('squirrel', 'drink', 'normal', 'Белочка быстро пьёт воду и возвращается проверять свои запасы.'),
                ('squirrel', 'play', 'happy', 'Белочка устраивает маленький хаос, но выглядит счастливой.'),
                ('squirrel', 'wash', 'normal', 'Белочка вертится на месте, но после ухода выглядит аккуратнее.'),
                ('squirrel', 'sleep', 'normal', 'Белочка прячет хвост удобнее и наконец отдыхает.'),
                ('squirrel', 'heal', 'normal', 'Белочка принимает помощь и ненадолго становится спокойнее.'),
                ('squirrel', 'minigame', 'happy', 'Белочка резко меняет маршрут и всё равно успевает первой.'),
                ('squirrel', 'drink', 'happy', 'Белочка делает глоток и выглядит заметно бодрее.')
            ON CONFLICT (species, action, mood, text) DO NOTHING;
        """)


async def close_db():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("🐘 Пул подключений закрыт")
