"""Модели SQLAlchemy."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ---------- пользователь ----------
class UserModel(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum("user", "admin", name="user_role"), default="user", nullable=False)
    status = Column(
        Enum("pending", "approved", "blocked", name="user_status"),
        default="pending",
        nullable=False,
    )
    quotas_sources = Column(Integer, default=10)
    quotas_substitutions = Column(Integer, default=10)
    can_record = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    sources = relationship("SourceModel", back_populates="owner")
    records = relationship("RecordModel", back_populates="owner")
    proxies = relationship("ProxyModel", back_populates="owner")


# ---------- источник (база) ----------
class SourceModel(Base):
    __tablename__ = "sources"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mountpoint = Column(String(50), unique=True, nullable=False, index=True)
    password = Column(String(128), nullable=False)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    host = Column(String(45), nullable=True)
    port = Column(Integer, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    height = Column(Float, nullable=True)
    antenna = Column(Text, nullable=True)
    receiver = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    owner = relationship("UserModel", back_populates="sources")
    clients = relationship("ClientModel", back_populates="source")


# ---------- клиент (ровер) ----------
class ClientModel(Base):
    __tablename__ = "clients"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mountpoint_id = Column(String(36), ForeignKey("sources.id"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    ip_address = Column(String(45), nullable=False)
    user_agent = Column(Text, nullable=True)
    connected_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    disconnected_at = Column(DateTime(timezone=True), nullable=True)
    bytes_sent = Column(Integer, default=0)
    bytes_received = Column(Integer, default=0)
    fix_quality = Column(Integer, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    num_sats = Column(Integer, nullable=True)
    hdop = Column(Float, nullable=True)

    source = relationship("SourceModel", back_populates="clients")


# ---------- запись (статика) ----------
class RecordModel(Base):
    __tablename__ = "records"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mountpoint_id = Column(String(36), ForeignKey("sources.id"), nullable=False)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    duration = Column(Integer, nullable=False)
    file_path = Column(Text, nullable=True)
    bytes_total = Column(Integer, default=0)
    is_active = Column(Boolean, default=False)

    owner = relationship("UserModel", back_populates="records")


# ---------- подмена координат ----------
class ProxyModel(Base):
    __tablename__ = "proxies"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    source_mountpoint = Column(String(50), nullable=False)
    target_mountpoint = Column(String(50), unique=True, nullable=False)
    mode = Column(Enum("relay", "absolute", "offset", name="proxy_mode"), nullable=False)
    x = Column(Float, nullable=True)
    y = Column(Float, nullable=True)
    z = Column(Float, nullable=True)
    de = Column(Float, nullable=True)
    dn = Column(Float, nullable=True)
    du = Column(Float, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    owner = relationship("UserModel", back_populates="proxies")


# ---------- индекс для быстрого поиска ----------
Index("ix_clients_mountpoint_id", ClientModel.mountpoint_id)
Index("ix_clients_ip", ClientModel.ip_address)
