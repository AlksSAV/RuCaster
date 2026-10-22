# Разбор референса Референс A (замеры 2026-10-21)

Все факты ниже сняты с живого сервиса. Непроверенное помечено явно.

## 1. Топология и стек

- HTTP-панель: порт 8001, сервер `uvicorn` (ASGI), схема FastAPI: `/docs`, `/redoc`,
  `/openapi.json` отдаются без авторизации (200).
- NTRIP: порт 2101 (в `/status` — `host: 0.0.0.0`, `port: 2101`).
- TLS не используется: панель и NTRIP работают по открытому HTTP.
- Порт 443 на хосте открыт, содержимое не исследовалось (к кастеру не относится).
- Источник потока — входящее TCP-соединение SOURCE; в замере `peer = 127.0.0.1:50250`,
  то есть источник поднят на том же хосте (ретрансляция чужой базы DEMO_MP).

## 2. Аутентификация и роли

- `POST /api/auth/login` `{username, password}` возвращает `{username, role}` и ставит cookie
  `ntrip_session` (`HttpOnly`, `Max-Age=604800`, `Path=/`, `SameSite=lax`).
- `GET /api/auth/me` возвращает `{username, role, status, overrides, contact, created_at,
  internal, can_record, quotas:{sources, substitutions}}`.
- Роли: `user` и `admin`. Роль `user` получает 403 на `/api/users` (все методы),
  `/api/rover-feed`, `/api/settings/*`, `/admin/users`.
- Квоты по умолчанию: 10 источников, 10 подмен.
- Регистрация: `GET /register` (200 без входа) и `POST /api/auth/register`;
  заявка ждёт одобрения админом.
- `POST /api/auth/logout` возвращает `{"ok":true}` и сбрасывает cookie (`Max-Age=0`);
  после выхода тот же cookie даёт 401.
- Без cookie: страницы `/`, `/base/{mp}`, `/substitute`, `/records`, `/admin/users`
  отдают 302 на `/login`; все `/api/*`, `/status`, `/connections` — 401;
  `/login`, `/register`, `/static/*`, `/openapi.json`, `/docs`, `/redoc` — 200.
- Ошибка входа: 401 `{"error":"неверный логин/пароль или аккаунт не одобрен"}`.
- HEAD и OPTIONS на страницы дают 405; CORS-заголовков нет (один origin).

## 3. HTTP API — 47 путей (полностью в `api/openapi.json`)

Страницы: `/login`, `/register`, `/`, `/base/{mp}`, `/substitute`, `/admin/users`, `/records`.

Мониторинг (требует сессии): `/status`, `/mountpoints`, `/stats`, `/statistics`,
`/connections?limit=N`, `/positions`, `/clients`.

Источники: `GET/POST /api/sources`, `DELETE /api/sources/{mp}`
(тело `SourceRequest{mountpoint, password}`).

Анализ потока: `POST /api/collect/{mountpoint}` возвращает `{"started":[...]}`,
`GET /api/analysis`, `GET /api/rover-feed?mountpoint=` (только admin).

Запись (статика): `POST /api/record/{mp}` с `{duration}`, `GET /api/record`,
`DELETE /api/record/{pid}`, `GET /api/records/{mp}`, `GET /api/records/{mp}/{fname}`,
`GET /api/records/{mp}/day/{date}` (zip за день).

Подмена координат: `GET/POST /api/proxy`, `DELETE /api/proxy/{pid}`,
`GET /api/proxy/{pid}/check-upstream`. Тело `ProxyRequest` (26 полей): `mountpoint`,
`mode` (absolute, offset, relay), `coord_format` (ecef, wgs84, utm), `x, y, z`,
`lat, lon, height`, `utm_zone, utm_north, utm_easting, utm_northing, utm_height`,
`de, dn, du`, `listen_port`, `serve_mountpoint`, `src_host, src_port, src_mountpoint,
src_user, src_password`, `gga_lat, gga_lon, gga_interval`.

Гео и чужие кастеры: `GET /api/to-utm?lat&lon` возвращает `{zone, north, easting,
northing}`; `GET /api/remote-station?host&port&mountpoint&user&password&gga_lat&gga_lon&timeout`
возвращает `{found, ecef, latitude, longitude, height}`;
`GET /api/remote-mountpoints?host&port&user&password` возвращает `{mountpoints:[...]}`.

Админ: `GET/POST /api/users`, `POST /api/users/{u}/approve|reject|block|unblock`,
`DELETE /api/users/{u}`, `PATCH /api/users/{u}/quota`,
`POST /api/users/{u}/can-record`, `POST /api/settings/anonymous-rovers`,
`/api/settings/registration`, `/api/settings/auto-approve`,
`/api/settings/default-quotas`.

Форматы ошибок: доменные — `{"error":"текст"}`; валидация FastAPI — 422 с `detail`;
битый JSON — 422 `json_invalid` (проверено на `POST /api/proxy`).

## 4. NTRIP (порт 2101)

- Sourcetable отдаётся без авторизации, запрос `GET /`:
  - HTTP/1.0: ответ `HTTP/1.0 200 OK`, `Content-Type: text/plain`, тело
    `SOURCETABLE 200 OK ... ENDSOURCETABLE`;
  - HTTP/1.1 с `Ntrip-Version: Ntrip/2.0`: ответ `HTTP/1.1 200 OK`,
    `Server: NTRIP ntrip-caster/1.0`, `Content-Type: gnss/sourcetable`,
    `Content-Length`, `Connection: close`.
  - Строка STR: `STR;<mp>;<ident>;RTCM 3;;2;GPS+GLO+GAL+BDS;;;<lat>;<lon>;0;0;;none;N;N;9600`.
    Значения `9600` и `none` — константы кастера, не реальные параметры базы.
- Стрим: `GET /<mp>` с Basic-auth даёт `ICY 200 OK` и сразу бинарный RTCM3.
  Без авторизации или с неверным паролем: `HTTP/1.0 401 Unauthorized` и
  `WWW-Authenticate: Basic realm="NTRIP"`.
- Несуществующий mountpoint даёт тот же 401, а не 404: существование маунтов
  не раскрывается.
- `SOURCE <pass> /<mp>` с неверным паролем даёт `ICY 401 Unauthorized`.
- Входящий GGA парсится. Проверено: `$GNGGA` (fix 4, 12 спутников, HDOP 0.8,
  alt 150, geoid_sep 14, age 1.0) — значения появились в `/clients` и `/positions`.
  Значит восходящий NMEA читается и используется для карты и VRS.
- Срез `samples/stream-sample.rtcm`: 4277 Б за 4 с, 26 кадров, 0 мусорных байт;
  типы 1004, 1006, 1012, 1077, 1087, 1097, 1127, 1230 (legacy и MSM7, 1 Гц).

## 5. Модели данных (примеры в `api/`)

- `/status`: `{status, host, port, running, sources:[{mountpoint, alive, peer,
  clients, last_seen, bytes_received, latitude, longitude, height, ecef, antenna,
  receiver}], clients:{mp:count}, total_clients, active_connections,
  rejected_connections, max_connections:2000, max_connections_per_ip:50}`.
- `/mountpoints`: `{sources, clients}`; `/stats` — счётчики текущего состояния;
  `/statistics` — накопительные (`total_sources`, `total_clients`,
  `unique_mountpoints`, `active_sources`, `active_clients`).
- `/connections` — кольцевой журнал: при `limit=50` вернулось ровно 50 записей.
  Поля `{id, type: source|client, mountpoint, ip_address, connected_at,
  disconnected_at, bytes_sent, bytes_received}`.
- `/clients`: `{clients:[{mountpoint, ip, user_agent, connected_s, fix_quality,
  num_sats, latitude, longitude, age_seconds}]}`. Позиция появляется после GGA.
- `/positions`: `{positions:[{mountpoint, ip, latitude, longitude, fix_quality,
  num_sats, hdop, altitude, geoid_sep, age, updated_at, age_seconds}]}`.
- `/api/analysis`: `{window_s: 60, mountpoints:{mp:{state: collecting|done|error,
  progress, connected, updated_at, error, report}}}`. Поле `report` содержит
  `{pyrtcm, session:{duration_s, bytes_total, frames_ok, crc_errors, junk_bytes,
  parse_errors}, messages:[{id, name, count, rate_hz, avg_size, last_seen}],
  station:{station_id, ecef, latitude, longitude, height, gps, glonass, galileo,
  antenna_height}, constellations:{GPS|GLONASS|Galileo|BeiDou:{msm_levels, n_sats,
  satellites, frequencies, mean_cnr}}, satellites_total, coord_transformations,
  texts, ephemeris, details, verdict:{rtk_ready, checks:[{name, ok, note}]}}`.
  Замер: 502 кадра, 0 CRC-ошибок, 34 спутника, MSM7 по 4 системам, `rtk_ready=true`.
- `/api/record`: `{recording:[{id, mountpoint, owner, started_at, duration, alive}],
  disk:{mountpoints:[{mountpoint, bytes, files}], total_bytes, free_bytes},
  defaults:{duration: 28800, max_duration: 86400, retention_days: 3}}`.
- `/api/records/{mp}`: `{mountpoint, files:[{name, bytes}]}`. Имя содержит
  `_ГГГГММДД_ЧЧММ.rtcm`, по нему строится группировка по дням и zip за день.
- `/api/proxy`: `{proxies:[{id, source, mountpoint, serve_mountpoint, dest_port,
  mode, x, y, z, de, dn, du, alive, uptime_s, restart_count, last_error, error,
  owner}]}`. Набор полей восстановлен из клиентского JS, живой ответ был пустым.
- `/api/sources`: `{sources:[{mountpoint, connected, owner, mine, editable}]}`.
- `/api/rover-feed`: `{rovers:[{ip, user, connected_s, user_agent, gga:{fix_quality,
  num_sats, hdop, age, altitude, geoid_sep, updated_s}, sentences:[{age_s, line}]}]}`.

## 6. UI

- Страницы — отдельные HTML без фреймворка: инлайн `<style>` и инлайн `<script>`.
  Общие модули: `/static/auth.js` (профиль, редирект на `/login` при 401, выход),
  `/static/i18n.js` (RU и EN заменой подстрок по словарю плюс `MutationObserver`;
  язык в `localStorage["ntrip_lang"]`).
- `/` — KPI (статус, источники, клиенты, роверы, скорость), карта Leaflet с
  OSM-тайлами (CDN; без сети карта деградирует, остальное работает), спарклайн
  скорости (12 замеров, производная `bytes_received`), таблицы источников,
  клиентов и подключений, форма добавления источника, поллинг 5 с. При
  `document.hidden` опрос пропускается.
- `/base/{mp}` — при открытии делает `POST /api/collect/{mp}` (окно 60 с), затем
  поллинг 1.5 с во время сбора и 10 с после. Карточки: донат «Спутники» по
  системам, донат «Сообщения» по типам, таблица сообщений с поиском по ID,
  «Станция» (1005/1006), «Вердикт RTK», панель подмены, дамп `details`.
  Блоки «роверы» и «запись» рисуются только при правах (admin или `can_record`).
- `/substitute` — источник: своя база или чужой кастер (host, port, mp, логин,
  пароль, загрузка mountpoints, опция отправки GGA для VRS). Режимы `relay`,
  `absolute` (ECEF, WGS84, UTM), `offset` (ENU, высота эллипсоидальная).
  Результат публикуется на своём кастере как `<mp>_SHIFTED` или `<mp>_RELAY`.
  Список подмен обновляется каждые 4 с, у админа есть кнопка проверки апстрима.
- `/records` — активные записи (владелец, начало, длительность, остаток, стоп),
  файлы по базам с группировкой по дням и zip за день, сводка по диску и
  ретенции; поллинг 20 с.
- `/admin/users` — только для админа, остальным 403.

## 7. Слабости референса (что делаем иначе)

1. Нет TLS ни на панели, ни на NTRIP; cookie без `Secure` — пароли открытым текстом.
2. `/docs`, `/redoc`, `/openapi.json` открыты анонимно — полная карта API наружу.
3. Sourcetable анонимный (по стандарту допустимо, но раскрывает маунты).
4. Тривиальные пароли; защиты от перебора не обнаружено (специально не проверялась).
5. Константы `9600` и `none` в sourcetable не отражают реальные параметры базы.
6. `POST /api/collect` доступен любому авторизованному и запускает 60-секундный
   сбор на сервере — вектор нагрузки.
7. Подмена координат доступна роли `user` в пределах квоты — мощная операция без
   отдельного подтверждения.
8. `/statistics` смешивает накопительные счётчики и `unique_mountpoints` при одном
   активном — нужен явный контракт.
9. Два формата ошибок (`error` и FastAPI `detail`) — неудобно клиенту.
10. Политика лимитов описана только числами в `/status` (2000 и 50 на IP).

## 8. Что не проверено

- Поведение при переполнении лимитов 2000 и 50 — нагрузку не создавали.
- Формат успешного SOURCE-подключения — источником не подключались.
- `/api/users` и `/admin/users` — 403 для роли `user`.
- Внутренняя реализация анализа (в отчёте указан `pyrtcm` — вероятно, Python-парсер).
- Ретенция и ротация записей на практике — записей не было.
