"""Pydantic-схемы для API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------- Auth ----------
class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    username: str
    role: str


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


class UserResponse(BaseModel):
    username: str
    email: str
    role: str
    status: str
    quotas: dict[str, int] = Field(default_factory=dict)
    can_record: bool = True
    created_at: datetime | None = None


# ---------- Source ----------
class SourceCreate(BaseModel):
    mountpoint: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8)


class SourceResponse(BaseModel):
    id: str
    mountpoint: str
    connected: bool
    owner: str
    mine: bool = False
    editable: bool = False


class SourceFullResponse(SourceResponse):
    host: str | None = None
    port: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    height: float | None = None
    antenna: str | None = None
    receiver: str | None = None
    bytes_received: int = 0
    clients: int = 0
    last_seen: datetime | None = None


# ---------- Client / Rover ----------
class ClientResponse(BaseModel):
    mountpoint: str
    ip: str
    user_agent: str | None = None
    connected_s: float = 0.0
    fix_quality: int | None = None
    num_sats: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    age_seconds: float | None = None


class PositionResponse(BaseModel):
    mountpoint: str
    ip: str
    latitude: float | None = None
    longitude: float | None = None
    fix_quality: int | None = None
    num_sats: int | None = None
    hdop: float | None = None
    altitude: float | None = None
    geoid_sep: float | None = None
    age: float | None = None
    updated_at: datetime | None = None
    age_seconds: float | None = None


# ---------- Connection log ----------
class ConnectionResponse(BaseModel):
    id: str
    type: str  # "source" | "client"
    mountpoint: str | None = None
    ip_address: str
    connected_at: datetime | None = None
    disconnected_at: datetime | None = None
    bytes_sent: int = 0
    bytes_received: int = 0


# ---------- Status ----------
class StatusSource(BaseModel):
    mountpoint: str
    alive: bool = False
    peer: str | None = None
    clients: int = 0
    last_seen: datetime | None = None
    bytes_received: int = 0
    latitude: float | None = None
    longitude: float | None = None
    height: float | None = None
    antenna: str | None = None
    receiver: str | None = None


class StatusResponse(BaseModel):
    status: str = "OFFLINE"
    host: str = "0.0.0.0"
    port: int = 2101
    running: bool = False
    sources: list[StatusSource] = []
    clients: dict[str, int] = Field(default_factory=dict)
    total_clients: int = 0
    active_connections: int = 0
    rejected_connections: int = 0
    max_connections: int = 2000
    max_connections_per_ip: int = 50


# ---------- Statistics ----------
class StatisticsResponse(BaseModel):
    total_sources: int = 0
    total_clients: int = 0
    unique_mountpoints: int = 0
    active_sources: int = 0
    active_clients: int = 0


# ---------- Record ----------
class RecordStartRequest(BaseModel):
    duration: int = 8 * 3600


class RecordStartResponse(BaseModel):
    id: str
    mountpoint: str
    owner: str
    started_at: datetime | None = None
    duration: int = 0
    alive: bool = True


class RecordResponse(BaseModel):
    id: str
    mountpoint: str
    owner: str
    started_at: datetime | None = None
    duration: int = 0
    alive: bool = False


class DiskInfo(BaseModel):
    mountpoints: list[dict[str, Any]] = Field(default_factory=list)
    total_bytes: int = 0
    free_bytes: int = 0


class RecordFullResponse(BaseModel):
    recording: list[RecordResponse] = []
    disk: DiskInfo = Field(default_factory=DiskInfo)
    defaults: dict[str, int] = Field(
        default_factory=lambda: {
            "duration": 8 * 3600,
            "max_duration": 24 * 3600,
            "retention_days": 3,
        }
    )


# ---------- Proxy (подмена координат) ----------
class ProxyCreate(BaseModel):
    mountpoint: str = Field(min_length=1, max_length=50)
    mode: str = Field(pattern="^(relay|absolute|offset)$")
    # absolute
    x: float | None = None
    y: float | None = None
    z: float | None = None
    lat: float | None = None
    lon: float | None = None
    height: float | None = None
    # utm
    utm_zone: str | None = None
    utm_north: bool = True
    utm_easting: float | None = None
    utm_northing: float | None = None
    utm_height: float | None = None
    # offset
    de: float | None = None
    dn: float | None = None
    du: float | None = None
    # relay
    src_host: str | None = None
    src_port: int | None = None
    src_mountpoint: str | None = None
    src_user: str | None = None
    src_password: str | None = None
    listen_port: int | None = None
    serve_mountpoint: str | None = None
    # gga для VRS
    gga_lat: float | None = None
    gga_lon: float | None = None
    gga_interval: int = 10


class ProxyResponse(BaseModel):
    id: str
    source: str
    mountpoint: str
    serve_mountpoint: str | None = None
    dest_port: int | None = None
    mode: str
    x: float | None = None
    y: float | None = None
    z: float | None = None
    de: float | None = None
    dn: float | None = None
    du: float | None = None
    alive: bool = False
    uptime_s: float = 0.0
    restart_count: int = 0
    last_error: str | None = None
    error: str | None = None
    owner: str | None = None


# ---------- Admin ----------
class UserApproveRequest(BaseModel):
    user_id: str


class UserQuotaPatch(BaseModel):
    quotas_sources: int | None = None
    quotas_substitutions: int | None = None


class UserCanRecordPatch(BaseModel):
    can_record: bool


# ---------- Settings ----------
class SettingsAnonymousRovers(BaseModel):
    enabled: bool = False


class SettingsRegistration(BaseModel):
    enabled: bool = True
    auto_approve: bool = False


class SettingsDefaultQuotas(BaseModel):
    sources: int = 10
    substitutions: int = 10


# ---------- Analysis ----------
class AnalysisMessage(BaseModel):
    id: int
    name: str
    count: int
    rate_hz: float
    avg_size: float
    last_seen: str | None = None


class AnalysisVerdictCheck(BaseModel):
    name: str
    ok: bool
    note: str | None = None


class AnalysisVerdict(BaseModel):
    rtk_ready: bool
    checks: list[AnalysisVerdictCheck] = Field(default_factory=list)


class AnalysisMountpointReport(BaseModel):
    state: str = "collecting"  # collecting | done | error
    progress: float = 0.0
    connected: bool = False
    updated_at: datetime | None = None
    error: str | None = None
    report: dict[str, Any] = Field(default_factory=dict)


class AnalysisResponse(BaseModel):
    window_s: float = 60.0
    mountpoints: dict[str, AnalysisMountpointReport] = Field(default_factory=dict)


# ---------- Geo ----------
class UTMResponse(BaseModel):
    zone: str
    north: bool
    easting: float
    northing: float


class RemoteStationResponse(BaseModel):
    found: bool
    ecef: tuple[float, float, float] | None = None
    latitude: float | None = None
    longitude: float | None = None
    height: float | None = None


class RemoteMountpointResponse(BaseModel):
    mountpoints: list[dict[str, Any]] = Field(default_factory=list)
