# Разбор Референс B (замеры 2026-10-21)

Все факты сняты с живого сервиса. Непроверенное помечено явно.

## 1. Топология и стек

- **Backend:** CodeIgniter (PHP) — судя по `ci_session` cookie и структуре URL.
- **Frontend:** AngularJS 1.x (`angular.min.js` + `app.js`) для дашборда.
- **WebSocket:** `wss://Референс-B:4278` (или `ws://localhost:4278` для dev) — real-time обновления.
- **Карта:** Leaflet + MarkerCluster + GeoCoder (OpenStreetMap тайлы).
- **TLS:** есть (HTTPS), но NTRIP-порты не исследованы (предположительно 10173+).
- **Аналитика:** Яндекс.Метрика.

## 2. Аутентификация

- `POST /users/auth/` — `login` + `password` → `{"status":"ok"}` или `{"status":"fail"}`.
- Cookie: `ci_session` (HttpOnly, 2ч), `auth` (10 лет).
- `GET /Users/logout` — выход.
- `POST /users/reg_user/` — `email` + `username` + `password` → `{"errors":{}}` или редирект.
- Логин — email.

## 3. HTTP API

### Станции (BaseStations)
- `POST /BaseStations/getBS` — фильтрованный список станций (формат JSON):
  - Параметры: `networks`, `states`, `access_types` (POST form).
  - Возвращает массив объектов: `{mountpoint, lat, lon, port, dataSource, nav-system, format-details, fee, country}`.
- `GET /BaseStations/del/{id}` — удалить станцию.
- `GET /BaseStations/updSourcePasswd/{new_pass}` — сменить пароль источника.

### Пользователь
- `GET /Users/profile` — HTML-страница дашборда (Angular SPA).
- `GET /Users/logout` — выход.

### WebSocket (wss://Референс-B:4278)

**Команды клиент → сервер:**

| cmd | Назначение | Параметры |
|-----|-----------|-----------|
| 1 | Инициализация | `tp_cloud_user_id`, `socket_id`, `u_hash` |
| 111 | Получить веб-клиенты | — |
| 112 | Обновить credentials | `mountpoint`, `newMPname`, `newpasswd`, `tp_cloud_user_id`, `u_hash` |
| 193 | Получить LoRa настройки | `mountpoint`, `tp_cloud_user_id`, `u_hash` |
| 195 | Установить LoRa | `loraStn` (chunks_num, chunks_repeat, rtcm2transmit, air_bitrate, loraOnOff), `mountpoint`, `tp_cloud_user_id`, `u_hash` |
| 196 | Получить RTCM данные | `mountpoint`, `tp_cloud_user_id`, `u_hash` |
| 197 | Установить RTCM фильтры | `valKeyIds` (объект RTCM msg_id → 0/1), `mountpoint`, `tp_cloud_user_id`, `u_hash` |
| 198 | Kick сервер (отключить) | `mountpoint`, `tp_cloud_user_id`, `u_hash` |
| 199 | Получить подключённые роверы | `tp_cloud_user_id`, `u_hash`, `owner` |
| 200 | Получить подключённые референсы | `tp_cloud_user_id`, `u_hash`, `owner` |

**Ответы сервера (response_type):**

| type | Назначение | Данные |
|------|-----------|--------|
| 1 | socket_id от сервера | `socket_id` |
| 2 | RTCM сообщение | `mp`, `msg_id`, данные |
| 3 | Новый клиент (ровер) | `id`, `ip`, `conTime` |
| 5 | Список референсов | `data: [{mountPoint, ...}]` |
| 6 | Список всех роверов | `data: [...]` |
| 7 | Настройки RTCM | `data: {msg_id: 0/1}` |
| 8 | Веб-клиенты | `data: [...]` |
| 10 | LoRa настройки | `data: {air_bitrate, chunks_num, chunks_repeat, rtcm2transmit}` |

**Общая схема WebSocket:**
```
Клиент → cmd:1 → Сервер
Сервер → response_type:1 (socket_id)
Клиент → cmd:1 + socket_id
Далее — push-уведомления от сервера
```

## 4. Данные станций (bsData)

Массив из ~300+ станций. Поля:

```json
{
  "country": "",
  "dataSource": "Референс B",
  "dataSourceH": "ProviderB",
  "mountpoint": "Baza_Kledi",
  "lat": "41.2014",
  "lon": "19.4734",
  "format-details": "",
  "nav-system": "",
  "port": "10252",
  "fee": ""
}
```

- `fee: ""` — бесплатная, `fee: "Y"` — платная.
- `dataSource` — откуда поток (свой или ретрансляция).
- Порты: 10173 — 11869+ (динамическое распределение).

## 5. UI дашборда

- **Структура:** Angular SPA, загружается через `/Users/profile`.
- **Блоки:**
  - Статистика: totalRefs, totalRovers, connectedRefs[], connectedRovers[].
  - Таблица референсов с статусом (online/offline).
  - Таблица роверов (ip, коннект-тайм).
  - Настройки RTCM (включение/выключение типов сообщений).
  - Настройки LoRa (для беспроводной передачи).
  - Управление: kick, смена пароля, удаление станций.
- **WebSocket:** инициализируется при загрузке, reconnect при разрыве.

## 6. Что уникально у Референс B (чего нет у Референс A)

1. **WebSocket** — real-time push вместо polling (5 сек).
2. **LoRa-настройки** — конфигурация беспроводной передачи для баз.
3. **RTCМ-фильтры** — выборочная передача типов RTCM-сообщений.
4. **Платные/бесплатные станции** — система монетизации.
5. **Angular SPA** — более современный фронтенд (vs инлайн JS у Референс A).
6. **Динамические порты** — каждая станция на своём порту (10173+).
7. **Удалённые источники** — `dataSource` показывает, своя база или чужая.
8. **Кик сервера** — возможность отключить источник дистанционно.

## 7. Слабости Референс B

1. WebSocket на 4278 — нет информации о безопасности соединения.
2. `u_hash` — неясно как генерируется, возможно уязвимо к реконструкции.
3. Нет открытых документов API (OpenAPI/Swagger).
4. CORS не исследован.
5. Rate limiting на WebSocket — не проверен.

## 8. Артефакты в `reference-snapshot-Референс B/`

| Путь | Что |
|------|-----|
| `html/index.html` | Главная страница (14 КБ) |
| `html/network.html` | Карта станций (476 КБ, bsData встроен) |
| `html/dashboard.html` | Дашборд HTML (6.7 КБ) |
| `js/custom.js` | Основной JS (49 КБ) |
| `js/adm.js` | WebSocket-клиент (3 КБ) |
| `js/app.js` | Angular-контроллер (3.3 КБ) |
| `js/angular.min.js` | Angular 1.x (177 КБ) |
| `js/leaflet-listeo.js` | Карта станций (4.5 КБ) |
| `api/stations.json` | Полный список станций (414 КБ) |
| `api/user_profile.json` | Профиль пользователя (6.7 КБ) |
