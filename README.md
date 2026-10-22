# RuCaster

[![CI](https://github.com/AlksSAV/RuCaster/actions/workflows/ci.yml/badge.svg)](https://github.com/AlksSAV/RuCaster/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)

Современный NTRIP-кастер для GNSS RTK-коррекции.

## Стек

- **Backend:** FastAPI (Python 3.12) + async SQLAlchemy + WebSocket
- **Frontend:** SvelteKit + TypeScript
- **БД:** SQLite (WAL) / PostgreSQL (опционально)
- **NTRIP:** порт 2101, sourcetable v1.0/v2.0, RTCM3, NMEA GGA
- **Deploy:** Docker-compose / systemd / Raspberry Pi

## Быстрый старт

```bash
# 1. Клонировать
git clone https://github.com/YOUR-USERNAME/RuCaster.git
cd RuCaster

# 2. Backend (dev)
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -e ".[dev]"
cp ../.env.example .env       # ОБЯЗАТЕЛЬНО изменить JWT_SECRET_KEY!
python -m app.main

# 3. Frontend (dev)
cd ../frontend
npm install
npm run dev
```

- **API:** http://localhost:8001
- **NTRIP:** порт 2101 (TCP)
- **Docs:** http://localhost:8001/docs (только debug)

## Структура

```
RuCaster/
├── backend/app/          # FastAPI: API, NTRIP, WS, GNSS, сервисы
│   ├── api/              # REST-эндпоинты (auth, sources, monitoring...)
│   ├── core/             # config, security (JWT, bcrypt)
│   ├── db/               # SQLAlchemy модели и схемы
│   ├── gnss/             # RTCM3, NMEA GGA парсеры, гео-конвертации
│   ├── ntrip/            # NTRIP-сервер (sourcetable, SOURCE, CLIENT)
│   ├── services/         # source_manager, recorder, proxy
│   ├── ws/               # WebSocket-хаб
│   └── main.py           # Точка входа
├── frontend/src/         # SvelteKit SPA
│   ├── routes/           # /dashboard, /stations, /login, /register, /admin
│   ├── lib/api/          # HTTP + WebSocket клиенты
│   ├── lib/stores/       # Svelte stores (user, status)
│   └── lib/i18n/         # RU/EN
├── deploy/               # docker-compose, nginx, systemd
├── docs/                 # анализ референсов, архитектура
├── scripts/              # setup.sh, run-dev.sh
└── data/                 # SQLite, RTCM-записи
```

## Фичи MVP

- NTRIP SOURCE (входящий RTCM3-поток от баз)
- NTRIP CLIENT (исходящий стрим для роверов, Basic-auth)
- Sourcetable v1.0/v2.0 (анонимный, стандарт)
- NMEA GGA парсинг → позиции роверов
- REST API: login/register/logout, CRUD источников, мониторинг
- WebSocket real-time push для дашборда
- Подмена координат (relay/absolute/offset)
- Запись статики (RTCM-файлы, zip по дням)
- Админ-панель (модерация, квоты, роли)
- i18n RU/EN
- OpenAPI/Swagger

## Безопасность

- TLS (Let's Encrypt) через nginx
- Secure cookie + HttpOnly
- bcrypt с salt rounds=12
- Rate limiting на login (5 попыток / 5 мин)
- 401 вместо 404 для несуществующих mountpoints

## Лицензия

MIT
