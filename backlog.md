# Backlog RuCaster

Баги и задачи, обнаруженные в процессе разработки. Фиксируются по мере нахождения.

## Баги

### B-001. `sources.py`: некорректная проверка существования mountpoint
- **Файл:** `backend/app/api/sources.py`, строка ~47 (`create_source`)
- **Суть:** `if await session.execute(stmt):` — объект результата `execute()` всегда
  истинен, поэтому создание источника всегда получает 400 «mountpoint уже существует».
- **Как в эталоне:** так же, как было исправлено в `auth.py` (B-001-fix): заменить на
  `if (await session.execute(stmt)).scalar_one_or_none():`.
- **Приоритет:** высокий (ломает основной сценарий добавления базы).
- **Статус:** открыт.

## Доработки MVP (заглушки, помеченные TODO)

### T-001. `get_current_user` / `/api/auth/me` — не читает cookie
- **Файл:** `backend/app/api/auth.py`
- **Суть:** зависимость выбрасывает `NotImplementedError` / 401. Нужен разбор cookie
  `ntrip_session` (JWT) → загрузка пользователя из БД.
- **Блокирует:** все защищённые эндпоинты, привязка владельца к источникам.

### T-002. Источники: owner захардкожен (`owner_id = "demo-owner"`)
- **Файл:** `backend/app/api/sources.py:create_source`
- **Блокируется:** T-001.

### T-003. Мониторинг возвращает пустые заглушки
- **Файл:** `backend/app/api/monitoring.py`
- **Суть:** `/status`, `/clients`, `/positions`, `/connections`, `/statistics` не
  подключены к `NtripHub`. Нужен общий стор состояния (hub уже хранит сессии).

### T-004. NTRIP: пароль SOURCE не проверяется корректно
- **Файл:** `backend/app/ntrip/hub.py:handle_source`
- **Суть:** пароли источников в БД лежат открытым текстом (`SourceModel.password`),
  а сравнение идёт через `verify_password` (bcrypt). Нужно либо хешировать пароли
  источников при создании, либо сравнивать напрямую + constant-time compare.

### T-005. GGA от роверов не парсится из восходящего потока
- **Файл:** `backend/app/ntrip/hub.py:_read_source_stream`
- **Суть:** данные только ретранслируются; вызов `parse_gga`/`parse_rtcm3` не встроен.
  Из-за этого `/positions` всегда пуст, карта без роверов.

### T-006. WebSocket: /ws работает как echo
- **Файл:** `backend/app/main.py:ws_endpoint`
- **Суть:** нет авторизации по JWT и нет push-событий из hub
  (source online/offline, client connected, stats).

### T-007. Запись статики (records) — заглушки 501
- **Файл:** `backend/app/api/records.py`
- **Суть:** начать запись в `settings.records_dir`, ротация, zip по дням, ретенция.

### T-008. Подмена координат (proxy) — заглушки 501
- **Файл:** `backend/app/api/proxy.py`
- **Суть:** relay/absolute/offset + публикация `<mp>_SHIFTED`/`<mp>_RELAY`.

### T-009. Анализ RTCM-потока не реализован
- **Модуль:** `backend/app/services/` (пусто)
- **Суть:** окно 60 с, счётчики кадров/CRC, типы сообщений, вердикт rtk_ready (pyrtcm).

### T-010. Admin API — заглушки 501
- **Файл:** `backend/app/api/admin.py`
- **Суть:** approve/reject/block/quota + проверка роли admin.

### T-011. Гео-утилиты: remote-station / remote-mountpoints — заглушки
- **Файл:** `backend/app/api/geo.py`
- **Суть:** подключение к внешним кастерам (httpx), чтение sourcetable/1005/1006.

## Качество

### Q-001. Тесты покрывают только `gnss/parsers`
- Добавить: API (httpx AsyncClient + tmp SQLite), NTRIP (сокеты), hub-рассылку,
  security (bcrypt/JWT/лок-аут).

### Q-002. mypy strict ещё не проходит
- **Файл:** `backend/pyproject.toml` — strict включён, но код не размечен.
  Прогонять точечно (`--follow-imports=skip` по модулям).

### Q-003. Frontend не собран/не проверен
- **Файл:** `frontend/`
- **Суть:** `svelte-check` падает (CI-джоб помечен `continue-on-error`), конкретно:
  - `src/app.html` — отсутствуют плейсхолдеры `%sveltekit.head%` и `%sveltekit.body%`,
    из-за чего SvelteKit не может загрузить конфиг («Loading Svelte config from Vite
    config failed: src/app.html is missing %sveltekit.head%»);
  - `src/lib/i18n/index.ts` — `$lang` не является валидным rune-синтаксисом вне
    `.svelte`-файла; нужен `get(lang)` из `svelte/store` внутри `t()`;
  - `src/routes/+layout.svelte` — `<slot />` устарел для Svelte 5, нужен `{@render children()}`;
  - нет `src/lib/components/*.svelte` (карта Leaflet, таблицы, KPI-компоненты);
  - нет `package-lock.json` → CI использует `npm install` вместо `npm ci`.
- **Приоритет:** высокий (блокирует сборку фронтенда).
- **Статус:** открыт.

### Q-005. CI: фронтенд-джоб не блокирует пайплайн
- **Файл:** `.github/workflows/ci.yml`
- **Суть:** `continue-on-error: true` для джоба `frontend` поставлен как временная мера.
  Убрать после закрытия Q-003, вернуть `npm ci` + кэш по `package-lock.json`.
- **Приоритет:** средний (не скрывать реальные поломки фронтенда в будущем).
- **Статус:** открыт.

### Q-004. Нет Alembic-миграций
- Сейчас `create_all` в lifespan. Для прода — `alembic init` + первая ревизия.

## Инфраструктура

### I-001. Docker-образы не собирались (на машине разработчика нет Docker)
- Проверить `deploy/Dockerfile.backend|frontend` и `docker-compose.yml` на хосте с Docker.

### I-002. systemd-юнит рассчитывает на фронтенд?
- `deploy/systemd/rucaster.service` поднимает только backend. Нужен второй юнит
  для SvelteKit (node build) или политика «фронт отдаёт nginx статикой».

### I-003. Скрипты `.sh` не имеют Windows-аналогов
- Добавить `scripts/setup.ps1` / `run-dev.ps1` (разработка на Windows).

### I-004. `deploy/Dockerfile.frontend` не проверен на реальной сборке
- **Файл:** `deploy/Dockerfile.frontend`
- **Суть:** использует `npm install` + `npm run build`; при отсутствии
  `package-lock.json` сборка недетерминирована. После Q-003 заменить на `npm ci`.
- **Приоритет:** низкий.

### I-005. Нет `package-lock.json` в репозитории
- **Суть:** lock-файл не сгенерирован (`npm install --package-lock-only` не запускался).
  Без него CI и Docker-сборки не воспроизводимы.
- **Связано:** Q-003, Q-005, I-004.

### I-006. В репозитории нет `.env` — только `.env.example`
- **Суть:** это правильно, но README/`scripts/setup.sh` не проверяют, что
  `JWT_SECRET_KEY` изменён перед запуском. Добавить валидацию на старте
  (предупреждение, если остался дефолтный плейсхолдер).
- **Приоритет:** средний (безопасность).

### I-007. Снимки референсов остались локально
- **Суть:** `reference-snapshot-*/` в `.gitignore`. Если они нужны команде —
  вынести в отдельный приватный репозиторий; в публичном их быть не должно.
- **Статус:** решено (исключены из публикации).

### I-008. `docs/architecture-recommendations.md` ссылается на «Референс A/B»
- **Суть:** адреса источников анонимизированы. При внутреннем использовании
  сопоставление A/B ↔ конкретные сервисы хранить вне репозитория.
- **Статус:** решено.

## История релизов

### v0.1.0 — 2026-10-22 (initial scaffold)
- Первый публичный коммит: `5c383c6`, CI-фикс: `3074f4b`.
- Backend: NTRIP-сервер (sourcetable v1.0/2.0, SOURCE, client stream),
  REST API (auth/sources/monitoring/records/proxy/admin/geo), WebSocket-хаб,
  GNSS-парсеры (RTCM3, NMEA GGA, WGS84↔UTM), 12 тестов, ruff чист.
- Frontend: SvelteKit-каркас (7 страниц, API/WS-клиенты, i18n RU/EN) — не собран.
- Deploy: docker-compose, nginx (rate-limit, TLS-ready), systemd-юнит.
- CI: backend зелёный; frontend `continue-on-error` (Q-003, Q-005).
- Репозиторий: https://github.com/AlksSAV/RuCaster
