# Сводный анализ и рекомендации по архитектуре RuCaster

Сравнение двух референсов: **Референс A** (FastAPI + собственный NTRIP) и **Референс B** (CodeIgniter + WebSocket).

---

## 1. Сводная таблица функциональности

| Функция | Референс A | Референс B | Рекомендация |
|---------|----------|----------------|--------------|
| **Аутентификация** | JWT/cookie, роли user/admin, квоты, регистрация с модерацией | email+password, cookie, регистрация без модерации | **Референс A** — роли + квоты + модерация |
| **NTRIP SOURCE** | порт 2101, RTCM3 парсинг, GGA парсинг | порты 10173+ (динамические), LoRa-настройки | **Оба** — динамические порты + RTCM3/GGA |
| **NTRIP CLIENT** | `GET /<mp>` Basic-auth, ICY 200 | `GET /<mp>` Basic-auth, ICY 200 | **Референс A** — 401 вместо 404 |
| **Sourcetable** | v1.0/v2.0, STR-строки | неизвестно (не исследовано) | **Референс A** |
| **Dashboard UI** | Инлайн HTML/CSS/JS, Leaflet+OSM, спарклайн, карты | AngularJS SPA, Leaflet+MarkerCluster | **Референс A** — проще, прозрачнее |
| **Real-time** | Polling 5 сек (fetch) | WebSocket push (wss://4278) | **Референс B** — WebSocket |
| **RTCM Analysis** | `POST /api/collect/{mp}` — 60 сек окно, pyrtcm, MSM7, вердикт rtk_ready | `cmd:196` — RTCM данные по WebSocket | **Референс A** — полный анализ |
| **RTCM Filters** | Нет | `cmd:197` — выборка типов сообщений | **Референс B** — полезно для экономии трафика |
| **Подмена координат** | `POST /api/proxy` — relay/absolute/offset, 26 полей | Нет | **Референс A** — мощная фича |
| **Запись статики** | `POST /api/record/{mp}` — длительность, ретенция, zip по дням | Нет | **Референс A** |
| **Гео-утилиты** | to-utm, remote-station, remote-mountpoints | Нет | **Референс A** |
| **LoRa-настройки** | Нет | `cmd:195` — chunks, bitrate, rtcm2transmit | **Референс B** — для беспроводных баз |
| **Кик источника** | Нет | `cmd:198` — отключение источника | **Референс B** |
| **Платные/бесплатные** | Нет | `fee` поле в станциях | **Референс B** — если нужна монетизация |
| **Карта станций** | Leaflet с маркерами, popup с информацией | Leaflet+MarkerCluster, фильтры по сети/статусу | **Референс B** — фильтрация + кластеризация |
| **Админ-панель** | `/admin/users` — approve/reject/block/quota | Нет (только профиль) | **Референс A** |
| **i18n** | RU/EN через `i18n.js` | Нет | **Референс A** |
| **OpenAPI/Swagger** | `openapi.json` + `/docs` + `/redoc` | Нет | **Референс A** |
| **Подключение чужих кастеров** | `remote-station`, `remote-mountpoints` | Нет | **Референс A** |
| **VRS через GGA** | Есть (GGA в proxy) | Есть (опция в подмене) | **Оба** |
| **Трафик-спарклайн** | SVG спарклайн 12 замеров | Нет | **Референс A** |
| **Статус референсов** | Таблица с alive/peer/clients | Таблица online/offline | **Референс A** |
| **Журнал подключений** | Кольцевой журнал `/connections` | Нет | **Референс A** |
| **Позиции роверов** | `/positions` — карта + координаты | `/positions` — только таблица | **Референс A** |

---

## 2. Что уникально у каждого

### Референс A (уникальное):
1. **Полный RTCM-анализ** — pyrtcm-парсер, MSM7, вердикт `rtk_ready`, CRC-ошибки, спутники по системам
2. **Подмена координат** — relay/absolute/offset, 26 параметров, публикация `<mp>_SHIFTED`
3. **Запись статики** — длительность, ретенция, zip за день
4. **OpenAPI/Swagger** — документация API
5. **i18n** — RU/EN
6. **Гео-утилиты** — WGS84→UTM, remote-station, remote-mountpoints
7. **Модерация регистрации** — заявка ждёт одобрения админа
8. **Sourcetable** — стандарт NTRIP v1.0/v2.0

### Референс B (уникальное):
1. **WebSocket real-time** — push вместо polling, 9 типов сообщений
2. **LoRa-настройки** — конфигурация беспроводной передачи
3. **RTCM-фильтры** — выборочная передача типов сообщений
4. **Динамические порты** — каждая станция на своём порту
5. **Платные/бесплатные станции** — `fee` поле
6. **Кик источника** — дистанционное отключение
7. **Фильтры карты** — по сети, статусу, типу доступа
8. **MarkerCluster** — группировка маркеров на карте

---

## 3. Архитектура RuCaster — рекомендации

### 3.1 Стек

```
┌─────────────────────────────────────────────────────────────┐
│                    RuCaster Architecture                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Frontend (SPA)                                             │
│  ├── React + TypeScript (Vite)                              │
│  ├── Leaflet + MarkerCluster (карта)                         │
│  ├── WebSocket client (real-time)                            │
│  └── TailwindCSS (стили)                                    │
│                                                             │
│  Backend (FastAPI)                                          │
│  ├── REST API (OpenAPI/Swagger)                             │
│  ├── WebSocket server (real-time push)                       │
│  ├── NTRIP server (port 2101)                               │
│  ├── RTCM3 parser (pyrtcm или GNSS-библиотека)              │
│  ├── NMEA GGA parser                                       │
│  └── File storage (RTCM записи, zip по дням)                │
│                                                             │
│  Database (PostgreSQL)                                      │
│  ├── Users, roles, quotas                                   │
│  ├── Sources (mountpoints, passwords, ports)                │
│  ├── Clients (rovers, sessions)                             │
│  ├── Records (файлы, ретенция)                              │
│  └── Proxies (подмена координат)                            │
│                                                             │
│  Infrastructure                                             │
│  ├── TLS (Let's Encrypt)                                    │
│  ├── Rate limiting (nginx/cloudflare)                       │
│  ├── Reverse proxy (nginx/caddy)                            │
│  └── Docker-compose (развёртывание)                         │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Модули

| Модуль | Источник | Комментарий |
|--------|----------|-------------|
| NTRIP server | Референс A | Порт 2101, sourcetable, ICY, Basic-auth |
| RTCM3 парсер | Референс A | MSM7, GPS+GLO+GAL+BDS, CRC, вердикт rtk_ready |
| REST API | Референс A | FastAPI + OpenAPI, 47 эндпоинтов |
| WebSocket | Референс B | Real-time push вместо polling |
| RTCM-фильтры | Референс B | Выборка типов сообщений |
| Подмена координат | Референс A | relay/absolute/offset |
| Запись статики | Референс A | Длительность, ретенция, zip |
| i18n | Референс A | RU/EN |
| Админ-панель | Референс A | Модерация, квоты, роли |
| Карта | Референс B | MarkerCluster + фильтры |
| LoRa-настройки | Референс B | Для беспроводных баз |
| Кик источника | Референс B | Дистанционное отключение |

### 3.3 WebSocket-протокол (гибридный)

```python
# Команды клиент → сервер
CMD_CLIENT_INFO = 1       # Инициализация (user_id, socket_id)
CMD_ROVER_STATUS = 2      # Статус ровера (GGA, позиция)
CMD_SOURCE_KICK = 3       # Кик источника (admin)
CMD_SOURCE_PASSWD = 4     # Смена пароля
CMD_RTCM_FILTER = 5       # RTCM-фильтр (msg_id: bool)
CMD_LORA_CONFIG = 6       # LoRa-конфигурация

# Ответы сервер → клиент
WS_SOURCE_ONLINE = 100    # Источник подключён
WS_SOURCE_OFFLINE = 101   # Источник отключён
WS_CLIENT_CONNECT = 102   # Ровер подключился
WS_CLIENT_DISCONNECT = 103 # Ровер отключился
WS_RTCM_DATA = 104        # RTCM-кадр (опционально)
WS_STATS = 105            # Статистика (байты, клиенты)
WS_POSITION = 106         # Позиция ровера (GGA)
WS_ERROR = 107            # Ошибка
```

### 3.4 REST API (основные эндпоинты)

```
# Аутентификация (Референс A)
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me

# Пользователи (Референс A)
GET    /api/users
POST   /api/users/{u}/approve|reject|block|unblock
DELETE /api/users/{u}
PATCH  /api/users/{u}/quota

# Источники (Референс A)
GET    /api/sources
POST   /api/sources
DELETE /api/sources/{mp}

# Мониторинг (Референс A)
GET /status
GET /connections?limit=N
GET /positions
GET /clients
GET /statistics

# Анализ потока (Референс A)
POST /api/collect/{mp}
GET  /api/analysis

# Подмена координат (Референс A)
GET  /api/proxy
POST /api/proxy
DELETE /api/proxy/{pid}

# Запись статики (Референс A)
POST /api/record/{mp}
GET  /api/record
DELETE /api/record/{pid}
GET  /api/records/{mp}
GET  /api/records/{mp}/day/{date}

# LoRa (Референс B)
GET  /api/lora/{mp}
POST /api/lora/{mp}

# Станции (Референс B)
POST /BaseStations/getBS  # Фильтрованный список (карта)
GET  /BaseStations/del/{id}
```

### 3.5 База данных (PostgreSQL)

```sql
-- Таблица пользователей
users (
    id UUID PK,
    username VARCHAR(50) UNIQUE,
    email VARCHAR(100) UNIQUE,
    password_hash VARCHAR(255),
    role ENUM('user', 'admin'),
    status ENUM('pending', 'approved', 'blocked'),
    quotas_sources INT DEFAULT 10,
    quotas_substitutions INT DEFAULT 10,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
);

-- Таблица источников (баз)
sources (
    id UUID PK,
    mountpoint VARCHAR(50) UNIQUE,
    password VARCHAR(128),
    owner_id UUID FK -> users.id,
    host VARCHAR(45),
    port INT,
    latitude DECIMAL(10, 7),
    longitude DECIMAL(10, 7),
    height DECIMAL(8, 2),
    antenna TEXT,
    receiver TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
);

-- Таблица подключённых клиентов (роверов)
clients (
    id UUID PK,
    mountpoint VARCHAR(50) FK -> sources.mountpoint,
    user_id UUID FK -> users.id,
    ip_address INET,
    user_agent TEXT,
    connected_at TIMESTAMPTZ,
    disconnected_at TIMESTAMPTZ,
    bytes_sent BIGINT,
    bytes_received BIGINT,
    fix_quality INT,
    latitude DECIMAL(10, 7),
    longitude DECIMAL(10, 7),
    num_sats INT,
    hdop DECIMAL(5, 2)
);

-- Таблица записей
records (
    id UUID PK,
    mountpoint VARCHAR(50),
    owner_id UUID FK -> users.id,
    started_at TIMESTAMPTZ,
    duration INT,
    file_path TEXT,
    bytes BIGINT,
    is_active BOOLEAN DEFAULT FALSE
);

-- Таблица подмен координат
proxies (
    id UUID PK,
    owner_id UUID FK -> users.id,
    source_mountpoint VARCHAR(50),
    target_mountpoint VARCHAR(50),
    mode ENUM('relay', 'absolute', 'offset'),
    x DECIMAL(12, 3), y DECIMAL(12, 3), z DECIMAL(12, 3),
    de DECIMAL(8, 3), dn DECIMAL(8, 3), du DECIMAL(8, 3),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ
);
```

### 3.6 NTRIP-сервер

```
Порт 2101 (TCP)
├── Sourcetable (GET /)
│   ├── HTTP/1.0 → "SOURCETABLE 200 OK"
│   └── HTTP/1.1 + Ntrip-Version → "SOURCETABLE 200 OK"
│
├── Стрим (GET /<mountpoint>)
│   ├── Basic-auth → ICY 200 OK + RTCM3
│   └── 401 Unauthorized (неверный пароль)
│
├── SOURCE (входящее подключение)
│   ├── SOURCE <password> /<mountpoint> → ICY 200 OK
│   └── 401 Unauthorized
│
└── NMEA GGA парсер
    ├── Парсит $GNGGA из восходящего потока
    ├── Обновляет /positions и /clients
    └── Используется для карты и VRS
```

### 3.7 Безопасность (исправляем слабости обоих референсов)

| Проблема | Референс A | Референс B | RuCaster |
|----------|----------|----------------|----------|
| TLS | ❌ | ✅ | ✅ (Let's Encrypt) |
| Secure cookie | ❌ | ❌ | ✅ |
| Rate limiting | ❌ | ❌ | ✅ (nginx) |
| Защита от перебора | ❌ | ❌ | ✅ (bcrypt + lockout) |
| Анонимный docs | ❌ | N/A | ✅ (закрыть) |
| Анонимный sourcetable | ⚠️ | ⚠️ | ⚠️ (допустимо по стандарту) |
| Сильные пароли | ❌ | ❌ | ✅ (генерация + валидация) |
| WebSocket auth | ❌ | ⚠️ (u_hash) | ✅ (JWT в WS URL) |

---

## 4. Приоритеты разработки

### Фаза 1: MVP (ядро)
1. NTRIP-сервер (port 2101) — sourcetable, стрим, SOURCE
2. REST API (FastAPI) — login, sources, status
3. База PostgreSQL — users, sources, clients
4. RTCM3 парсер — базовый (1004, 1006, 1008, 1012)
5. Dashboard (React) — источники, клиенты, карта

### Фаза 2: Продвинутые фичи
6. WebSocket real-time push
7. Подмена координат (proxy)
8. Запись статики
9. Анализ потока (RTCM analysis)
10. Админ-панель

### Фаза 3: Экосистема
11. RTCM-фильтры
12. LoRa-настройки
13. i18n (RU/EN)
14. OpenAPI/Swagger
15. Монетизация (платные/бесплатные)

---

## 5. Итог

**RuCaster берёт лучшее от обоих:**
- Ядро от **Референс A**: NTRIP, RTCM3-анализ, подмена координат, запись, админка, i18n, OpenAPI
- Real-time от **Референс B**: WebSocket push, RTCM-фильтры, LoRa, кик источника
- Безопасность выше обоих: TLS, Secure cookie, rate limiting, bcrypt

**Итого:** ~60 эндпоинтов (REST + WebSocket) + NTRIP-протокол.
