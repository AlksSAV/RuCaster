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
- **Статус:** ✅ закрыто (`414fc17`).

### B-002. `security.py`: rate-limit на login никогда не срабатывал
- **Файл:** `backend/app/core/security.py:check_login_lockout`
- **Суть:** `check_login_lockout` при каждой разрешённой проверке обнулял
  `entry["attempts"]`. Реальный поток `/login` — «проверка → попытка», поэтому
  счётчик неудач не мог вырасти до порога: блокировка «5 попыток / 5 мин»
  (обещана в README) не включалась никогда.
- **Как в эталоне:** проверка не должна менять состояние; сброс счётчика —
  только по истечении окна или при успешном входе.
- **Приоритет:** высокий (Brute-force защита отсутствовала).
- **Статус:** ✅ закрыто (этот коммит). `check_login_lockout` стал чистой
  функцией; `record_login_attempt` ведёт скользящее окно `first_at` +
  сброс по успеху/истечении окна. Покрытие: `test_security.py`,
  `test_auth_api.py::TestLogin::test_lockout_*`.

## Доработки MVP (заглушки, помеченные TODO)

### T-001. `get_current_user` / `/api/auth/me` — не читает cookie
- **Файл:** `backend/app/api/auth.py`
- **Суть:** зависимость выбрасывает `NotImplementedError` / 401. Нужен разбор cookie
  `ntrip_session` (JWT) → загрузка пользователя из БД.
- **Блокирует:** все защищённые эндпоинты, привязка владельца к источникам.
- **Статус:** ✅ закрыто (`b48931b`, `ded4d65`). Реализованы `decode_access_token()`,
  `get_optional_user()`, `get_current_user()` и `/me` с `Depends`.

### T-002. Источники: owner захардкожен (`owner_id = "demo-owner"`)
- **Файл:** `backend/app/api/sources.py:create_source`
- **Блокируется:** T-001.
- **Статус:** ✅ закрыто (`3d26e91`). Owner берётся из JWT; `mine`/`editable`
  считаются по совпадению `owner_id` с ID текущего пользователя.

### T-003. Мониторинг возвращает пустые заглушки
- **Файл:** `backend/app/api/monitoring.py`
- **Суть:** `/status`, `/clients`, `/positions`, `/connections`, `/statistics` не
  подключены к `NtripHub`. Нужен общий стор состояния (hub уже хранит сессии).

### T-004. NTRIP: пароль SOURCE не проверялся корректно
- **Файл:** `backend/app/ntrip/hub.py:handle_source`, `backend/app/api/sources.py`
- **Суть:** пароли источников лежали открытым текстом, а сравнение шло через
  `verify_password` (bcrypt) — ни одна база не могла авторизоваться.
- **Статус:** ✅ закрыто (`aa84e4a`). Пароль хешируется bcrypt при создании источника,
  `verify_password` в `hub.py` корректно проверяет.
- **Остаток:** записи, созданные до фикса (plaintext в БД), не авторизуются —
  пересоздать вручную; автоматической миграции нет (см. Q-004).

### T-005. GGA от роверов не парсится из восходящего потока
- **Файл:** `backend/app/ntrip/hub.py:_read_source_stream`
- **Суть:** данные только ретранслировались; вызов `parse_gga`/`parse_rtcm3` не был
  встроен. Из-за этого `/positions` всегда пуст, карта без роверов.
- **Статус:** ✅ закрыто (`1607ca9`). Восходящий поток клиента буферизуется
  (`extract_nmea_lines`), валидный GGA (fix≠0) обновляет `position`/`position_at`
  сессии; `/positions` и `/clients` отдают координаты. RTCM-разбор — вне T-005 (T-009).

### T-006. WebSocket: /ws работает как echo
- **Файл:** `backend/app/main.py:ws_endpoint`
- **Суть:** нет авторизации по JWT и нет push-событий из hub
  (source online/offline, client connected, stats).
- **Статус:** ✅ закрыто. `/ws` авторизуется по cookie `ntrip_session` (JWT),
  при отсутствии/невалидности — close 4401 (фронт не переподключается).
  Из `NtripHub` пушатся события `source_connected/disconnected`,
  `client_connected/disconnected` (текстовые JSON-кадры `{type, data}`);
  ошибки WS не влияют на NTRIP-сессии. Дашборд подписан через `onWs`
  (мгновенный refresh + polling 5 с как fallback), индикатор «● live».

### T-007. Запись статики (records) — заглушки 501
- **Файл:** `backend/app/api/records.py`
- **Суть:** начать запись в `settings.records_dir`, ротация, zip по дням, ретенция.
- **Статус:** ✅ закрыто. `app/services/recorder.py`: `RecordManager` + `Recording`.
  `NtripHub.add_sink/remove_sink` — подписка на чанки потока источника, ошибка
  получателя не рвёт NTRIP. Запись идёт через `asyncio.Queue` (2048 чанков) и
  задачу-писатель `aiofiles`, поэтому диск не тормозит ретрансляцию; при
  переполнении очереди чанки отбрасываются со счётчиком `dropped_chunks`.
  Файлы: `<records_dir>/<mountpoint>/<ГГГГММДД>_<ЧЧММ>.rtcm`, ротация по смене
  календарных суток (UTC). Ретенция — фоновая задача раз в час по дате из имени
  файла (`retention_days`), пустые каталоги удаляются. Менеджер подключён в
  `lifespan`, при shutdown активные записи дописывают очередь и закрывают файлы.
  API: `POST /api/record/{mp}` (владелец/админ, проверка `can_record`, 409 при
  активной записи, лимит `max_record_duration_s`), `GET /api/record` (активные +
  диск + defaults), `DELETE /api/record/{pid}` (владелец/админ), `GET
  /api/record/{mp}` (файлы), `GET /api/record/{mp}/{fname}` (скачивание),
  `GET /api/record/{mp}/day/{date}` (zip за день). Имена файлов валидируются
  регуляркой — выхода за каталог нет. Тесты: `test_records.py` (24).

### T-008. Подмена координат (proxy) — заглушки 501
- **Файл:** `backend/app/api/proxy.py`
- **Суть:** relay/absolute/offset + публикация `<mp>_SHIFTED`/`<mp>_RELAY`.

### T-009. Анализ RTCM-потока не реализован
- **Модуль:** `backend/app/services/` (пусто)
- **Суть:** окно 60 с, счётчики кадров/CRC, типы сообщений, вердикт rtk_ready (pyrtcm).
- **Статус:** ✅ закрыто. `app/services/rtcm_analysis.py`: `RtcmAnalyzer` —
  скользящее окно 60 с (deque), счётчики frames_ok/crc_errors/junk_bytes,
  статистика по типам сообщений (count, rate_hz, avg_size, last_seen),
  категории созвездий, вердикт `rtk_ready` из 5 проверок (координаты станции
  1005/1006, наблюдения MSM/legacy, эфемериды, чистый CRC, источник онлайн).
  `Hub.feed_rtcm` подключён к `_read_source_stream`; API
  `GET /analysis/{mountpoint}` (владелец/админ; 404/403/409).
  Попутно исправлен парсер: RTCM3 CRC — 3 байта (CRC-24Q), а не 2; теперь
  реально валидируется (`crc24q` в `gnss/parsers.py`, сверен с pyrtcm).
  Полное декодирование содержимого (спутники, CNR, ARP станции) — отложено.
  Тесты: `test_rtcm_analysis.py` (17), обновлены `test_gnss.py`.

### T-010. Admin API — заглушки 501
- **Файл:** `backend/app/api/admin.py`
- **Суть:** approve/reject/block/quota + проверка роли admin.
- **Статус:** ✅ закрыто. `require_admin` (роль admin из JWT), список пользователей,
  approve/reject/block/unblock/delete/quota/can-record. Защита: нельзя трогать свою
  учётку; удаление только при отсутствии источников у пользователя (409).

### T-011. Гео-утилиты: remote-station / remote-mountpoints — заглушки
- **Файл:** `backend/app/api/geo.py`
- **Суть:** подключение к внешним кастерам (httpx), чтение sourcetable/1005/1006.

### T-012. `create_source` не проверяет квоту пользователя
- **Файл:** `backend/app/api/sources.py:create_source`
- **Суть:** `UserModel.quotas_sources` нигде не учитывается — можно создать
  неограниченное число mountpoint'ов. Нужна проверка счётчика источников
  владельца перед вставкой (403 при превышении).
- **Приоритет:** средний.
- **Статус:** ✅ закрыто (`c2a77ab`, `236b366`). Проверка `count >= quota` перед
  вставкой. Покрытие тестами: `test_sources_quota.py`.

## Качество

### Q-001. Тесты покрывают только `gnss/parsers`
- Добавить: API (httpx AsyncClient + tmp SQLite), NTRIP (сокеты), hub-рассылку,
  security (bcrypt/JWT/лок-аут).
- **Важно:** `get_current_user` / `get_optional_user` / `decode_access_token` и
  права на `sources` (T-001, T-002, T-004) закрыты без тестов — проверка только
  ruff + импорт. Приоритет вырос: эти пути надо покрыть в первую очередь.
- **Статус:** ✅ закрыто. Покрыто:
  - `test_security.py` — bcrypt, JWT (в т.ч. просрочка/чужой секрет), лок-аут;
    обнаружен и исправлен B-002 (rate-limit не срабатывал).
  - `test_auth_api.py` — register/login/logout/me через httpx + tmp SQLite,
    реальные `get_current_user`/`get_optional_user` (cookie → JWT → БД),
    лок-аут по IP на 5 попытках.
  - `test_ntrip_server.py` — `parse_basic_auth`, `build_sourcetable`,
    `_handle_client`/`_dispatch` (SOURCE/GET/sourcetable/401) на фейковых
    reader/writer без реального TCP.
  - `test_sources_quota.py` — квота T-012; `test_monitoring*.py`,
    `test_ws_events.py` — hub и API мониторинга, WS-события.
  - Остаток (не блокирует): интеграционный прогон SOURCE+CLIENT через реальный
    сокет 2101 с ретрансляцией байтов — удобно добавить вместе с T-009.
  - 98 passed, ruff чистый.

### Q-002. mypy strict ещё не проходит
- **Файл:** `backend/pyproject.toml` — strict включён, но код не размечен.
  Прогонять точечно (`--follow-imports=skip` по модулям).

### Q-003. Frontend не собран/не проверен
- **Файл:** `frontend/`
- **Суть:** `svelte-check` падал (CI-джоб помечен `continue-on-error`), конкретно:
  - ❌ ~~`src/app.html` — отсутствуют плейсхолдеры `%sveltekit.head%` и `%sveltekit.body%`~~ — закрыто (`58e77ea`)
  - ❌ ~~`src/lib/i18n/index.ts` — `$lang` невалиден вне `.svelte`-файла~~ — закрыто (`58e77ea`)
  - ❌ ~~`src/routes/+layout.svelte` — `<slot />` устарел для Svelte 5~~ — закрыто (`58e77ea`)
  - ✅ нет `src/lib/components/*.svelte` (карта Leaflet, таблицы, KPI-компоненты) — **в работе**
  - ❌ ~~`package-lock.json` отсутствует~~ — закрыто (`58e77ea`)
- **Приоритет:** высокий (блокирует сборку фронтенда).
- **Статус:** ✅ `svelte-check` и `vite build` проходят (0 ошибок). Осталось реализовать компоненты (Q-003-остаток).

### Q-005. CI: фронтенд-джоб не блокирует пайплайн
- **Файл:** `.github/workflows/ci.yml`
- **Суть:** `continue-on-error: true` для джоба `frontend` поставлен как временная мера.
  Убрать после закрытия Q-003, вернуть `npm ci` + кэш по `package-lock.json`.
- **Приоритет:** средний (не скрывать реальные поломки фронтенда в будущем).
- **Статус:** ⏳ ожидает Q-003-остаток (компоненты). `npm ci` уже возможен благодаря I-005.

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
- **Статус:** закрыт (`58e77ea`) — lock-файл закоммичен.

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

### v0.1.1 — 2026-10-27 (auth, sources, frontend build)
- Backend:
  - B-001: `create_source` — исправлена проверка уникальности mountpoint
    (`scalar_one_or_none()` вместо `execute()` truthiness).
  - T-001: JWT-аутентификация по cookie `ntrip_session` — `get_current_user`,
    `get_optional_user`, `/api/auth/me`.
  - T-002: `create_source` использует реальный `owner_id` из JWT, `mine`/`editable`
    считаются по совпадению.
  - T-004: пароль источника хешируется bcrypt при создании, корректно проверяется
    в NTRIP SOURCE-сессии.
- Frontend:
  - Q-003 (основное): `app.html` — плейсхолдеры SvelteKit, `i18n` — `get(lang)`
    вместо `$lang`, `+layout.svelte` — `{@render children()}`.
  - I-005: `package-lock.json` закоммичен.
  - `vite build` и `svelte-check` проходят (0 ошибок).
- CI: frontend-джоб пока `continue-on-error` (ожидает компоненты Q-003-остаток).
- Репозиторий: https://github.com/AlksSAV/RuCaster
