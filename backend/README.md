# RuCaster backend

FastAPI-приложение NTRIP-кастера: REST API, WebSocket, NTRIP-сервер.

## Запуск (dev)

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS
pip install -e ".[dev]"
python -m app.main
```

HTTP API: http://localhost:8001 (docs: /docs в debug-режиме)
NTRIP: port 2101

## Конфигурация

Скопируйте `.env.example` в `.env` и задайте `JWT_SECRET_KEY`.
