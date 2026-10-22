#!/bin/bash
# Скрипт инициализации RuCaster на Raspberry Pi
set -e

echo "=== RuCaster Setup ==="

# Обновление системы
echo "[1/4] Обновление системы..."
sudo apt update && sudo apt upgrade -y

# Установка зависимостей
echo "[2/4] Установка зависимостей..."
sudo apt install -y python3 python3-venv python3-pip git curl

# Создание пользователя
echo "[3/4] Создание пользователя rucaster..."
sudo useradd --create-home --shell /bin/bash rucaster 2>/dev/null || true
sudo mkdir -p /opt/rucaster/backend /opt/rucaster/data
sudo chown rucaster:rucaster /opt/rucaster

# Клонирование репозитория
cd /opt/rucaster
if [ ! -d "backend" ]; then
    echo "  Клонирую репозиторий..."
    git clone https://github.com/YOUR-USERNAME/RuCaster.git backend
else
    echo "  Репозиторий уже существует"
fi

# Настройка виртуального окружения
cd /opt/rucaster/backend
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -e ".[dev]"
fi

# Настройка .env
if [ ! -f ".env" ]; then
    cp ../.env.example .env
    echo "  Скопирован .env.example — НЕ ЗАБЫТЬ изменить JWT_SECRET_KEY!"
fi

# Настройка systemd
echo "[4/4] Установка systemd-сервиса..."
sudo cp ../deploy/systemd/rucaster.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable rucaster
sudo systemctl start rucaster

echo ""
echo "=== Установка завершена ==="
echo "  API:      http://localhost:8001"
echo "  NTRIP:    localhost:2101"
echo "  Статус:   sudo systemctl status rucaster"
echo "  Логи:     sudo journalctl -u rucaster -f"
