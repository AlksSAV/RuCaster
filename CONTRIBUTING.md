# Вклад в проект

Спасибо за интерес к RuCaster!

## Как помочь

1. **Найдите задачу** в [backlog.md](../backlog.md) или в Issues.
2. **Создайте ветку** от `main`: `git checkout -b feature/short-name` или `fix/short-name`.
3. **Разрабатывайте** с тестами: новые модули — с pytest-покрытием.
4. **Проверьте локально:**
   ```bash
   cd backend && ruff check app/ && ruff format --check app/ && pytest -q
   cd frontend && npm run check && npm run build
   ```
5. **Оформите PR** с описанием *что* и *зачем*. Ссылка на задачу — обязательна.

## Соглашения

- **Python:** 3.12+, ruff (line-length 99), докерстринги на русском допустимы.
- **TypeScript:** strict, prettier, Svelte 5 runes (`$state`, `$derived`, `$effect`).
- **Коммиты:** conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`).
- **API:** новые эндпоинты — со схемами pydantic в `app/db/schemas.py` и тестами.
- **NTRIP-протокол:** изменения — только со ссылкой на раздел NTRIP 1.0/2.0.

## Чего не делать

- Не коммитить `.env`, токены, пароли, приватные ключи.
- Не менять схему БД без alembic-миграции (когда они появятся, см. Q-004 в backlog).
- Не добавлять зависимости без обоснования в PR.

## Структура изменений

Ядро (NTRIP, GNSS-парсеры) меняем аккуратно: это протокольный код,
ошибки здесь стоят дороже удобства.
