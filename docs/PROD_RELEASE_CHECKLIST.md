# Prod Release Checklist

Перед релизом на прод-БД обязательно сделай backup/export в Neon/PostgreSQL.
GitHub rollback откатывает код, но не откатывает схему и данные.

## Local Gate

```powershell
python -m pip install -r src\requirements.txt
python -m compileall src
$env:PYTHONPATH="src"; python scripts\smoke_import.py
```

Для интеграционных тестов нужна отдельная PostgreSQL база:

```powershell
$env:TEST_DATABASE_URL="postgresql://..."
pytest
```

Тесты сами очищают `public` schema в `TEST_DATABASE_URL`. Никогда не указывай
туда продовую базу.

## Prod DB Gate

1. Сделать backup/export продовой БД.
2. Задеплоить код.
3. Открыть один cold start, чтобы прошёл `init_db()`.
4. Проверить таблицу `schema_migrations`: должны появиться версии миграций.
5. Проверить, что отключённые админом предметы/офферы не включились обратно.

## Manual Telegram Smoke

1. `/start` открывает главное меню.
2. Новый пользователь открывает развлечения и принимает fun-consent.
3. Магазин открывается, daily freebie выдаётся один раз.
4. Инвентарь показывает полученный предмет.
5. Питомец выбирается, действие работает, старые callback-и без питомца не создают кота.
6. PvP-комната создаётся, второй пользователь входит, несколько ходов редактируют доски без спама.
7. Рынок: выставить предмет, купить вторым пользователем, проверить комиссию 25%.
8. Админ открывает `profile:admin` без принятия fun-consent.
9. Админ-экономика показывает журнал и подозрительные лоты.

## Rollback

Если сломался только код, откатить релиз через GitHub.
Если сломалась схема или данные, восстановить БД из backup/export.
