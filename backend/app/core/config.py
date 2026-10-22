"""
RuCaster — конфигурация.
Все значения читаются из .env, дефолты заданы здесь.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- приложение ---
    app_name: str = "RuCaster"
    version: str = "0.1.0"
    debug: bool = False

    # --- бд ---
    database_url: str = "sqlite+aiosqlite:///./data/rucaster.db"

    # --- JWT ---
    jwt_secret_key: str = "CHANGE_ME_TO_A_SECURE_RANDOM_STRING"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24 * 7  # 7 дней

    # --- NTRIP ---
    ntrip_host: str = "0.0.0.0"
    ntrip_port: int = 2101

    # --- HTTP сервер ---
    http_host: str = "0.0.0.0"
    http_port: int = 8001

    # --- лимиты ---
    max_connections: int = 2000
    max_connections_per_ip: int = 50

    # --- записи (статика) ---
    records_dir: str = "./data/records"
    default_record_duration_s: int = 8 * 60 * 60  # 8 часов
    max_record_duration_s: int = 24 * 60 * 60  # 24 часа
    retention_days: int = 3

    # --- WebSocket ---
    ws_heartbeat_interval_s: float = 30.0

    # --- безопасность ---
    bcrypt_rounds: int = 12
    max_login_attempts: int = 5
    login_lockout_seconds: int = 300  # 5 минут

    @property
    def is_dev(self) -> bool:
        return self.debug

    @property
    def data_dir(self) -> Path:
        """Каталог данных (SQLite, записи). Отсчитывается от корня backend."""
        return Path(__file__).resolve().parents[2] / "data"

    def ensure_dirs(self) -> None:
        """Создать каталоги данных до инициализации БД."""
        Path(self.records_dir).mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite"):
            db_path = self.database_url.split("///")[-1]
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
