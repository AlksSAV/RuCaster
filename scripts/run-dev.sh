#!/bin/bash
# Запуск локальной разработки
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Запуск RuCaster (dev) ==="

cd "$PROJECT_DIR/backend"

if [ ! -d ".venv" ]; then
    echo "Создаю виртуальное окружение..."
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -e ".[dev]"
fi

if [ ! -f ".env" ]; then
    cp ../.env.example .env
    echo "Скопирован .env.example"
fi

echo "Запуск сервера..."
.venv/bin/python -m app.main
