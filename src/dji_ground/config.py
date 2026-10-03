"""Configuration settings for dji-ground using Pydantic Settings."""

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_project_root() -> Path:
    """Repo root for editable installs; fall back to CWD for wheel installs."""
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "pyproject.toml").exists():
        return candidate
    return Path.cwd()


PROJECT_ROOT: Path = _find_project_root()
FIXTURES_DIR: Path = PROJECT_ROOT / "fixtures"
WEB_DIST_DIR: Path = PROJECT_ROOT / "web" / "dist"


def resolve_path(path: str | Path) -> str:
    """Resolve a relative path against the project root so behaviour is CWD-independent."""
    p = Path(path)
    return str(p if p.is_absolute() else (PROJECT_ROOT / p))


def _is_placeholder(value: str | None) -> bool:
    if value is None:
        return True
    v = value.strip()
    return v == "" or v.lower().startswith("your_") or v.lower().startswith("your-")


class Settings(BaseSettings):
    """Central configuration for flight authority, safety gates, and bridges."""

    model_config = SettingsConfigDict(
        env_prefix="DJI_",
        # Project-root .env first, then CWD .env (later files win).
        env_file=(str(PROJECT_ROOT / ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # Bridge networking
    bridge_host: str = Field(default="127.0.0.1", description="OpenDJI bridge host IP")
    telemetry_port: int = Field(default=8001, description="Telemetry stream TCP port")
    video_port: int = Field(default=8002, description="H.264 video stream TCP port")
    command_port: int = Field(default=8003, description="Command & stick TCP port")
    bridge_mode: Literal["fake", "opendji"] = Field(
        default="fake", description="Bridge implementation to use"
    )
    bridge_reconnect_s: float = Field(
        default=3.0, description="Seconds between bridge reconnect attempts"
    )

    # Gateway
    gateway_host: str = Field(default="0.0.0.0", description="Web gateway bind host")
    gateway_port: int = Field(default=8000, description="Web gateway port")
    gateway_url: str = Field(
        default="http://127.0.0.1:8000", description="URL other processes use to reach the gateway"
    )

    # Flight caps (non-negotiable safety)
    indoor_max_speed: float = Field(default=1.0, description="Max indoor speed in m/s")
    indoor_max_altitude: float = Field(default=3.0, description="Max indoor altitude AGL in meters")
    indoor_max_box: float = Field(
        default=15.0, description="Max indoor bounding dimension in meters"
    )
    outdoor_max_speed: float = Field(default=3.0, description="Max outdoor speed in m/s")
    outdoor_max_altitude: float = Field(
        default=30.0, description="Max outdoor altitude AGL in meters"
    )
    outdoor_geofence_file: str = Field(
        default="config/geofence_default.json",
        validation_alias=AliasChoices("DJI_GEOFENCE_FILE", "DJI_OUTDOOR_GEOFENCE_FILE"),
        description="Path to geofence JSON file (local_polygon in meters, takeoff = origin)",
    )

    # Watchdog & Safety Loop
    watchdog_timeout_ms: int = Field(default=500, description="Watchdog timeout in ms")
    video_stale_threshold_ms: int = Field(
        default=1000, description="Max frame age before hover in ms"
    )
    stick_loop_freq_hz: int = Field(default=15, description="Virtual stick loop frequency in Hz")
    token_ttl_seconds: int = Field(
        default=30, description="Server-minted motion token TTL in seconds"
    )

    # Detector
    enable_yolo: bool = Field(default=False, description="Enable YOLO object detector")

    # 3D Modeling & Live Reconstruction
    enable_3d_modeling: bool = Field(
        default=False, description="Enable real-time 3D scanning engine"
    )
    model_3d_resolution: Literal["high", "medium", "low"] = Field(
        default="high", description="Point cloud voxel grid density"
    )
    model_3d_keyframe_ms: int = Field(
        default=250, description="Min interval between 3D keyframes in ms"
    )
    model_3d_max_points: int = Field(
        default=500000, description="Cap on total accumulated 3D points"
    )
    model_3d_export_dir: str = Field(
        default="data/models_3d", description="Directory for 3D model exports"
    )

    # Database
    sqlite_db_path: str = Field(
        default="data/dji_ground_session.sqlite", description="Path to SQLite database"
    )

    # Venice AI API & Telegram (documented without the DJI_ prefix; both accepted)
    venice_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("VENICE_API_KEY", "DJI_VENICE_API_KEY"),
        description="Venice AI API key",
    )
    venice_api_base: str = Field(
        default="https://api.venice.ai/api/v1",
        validation_alias=AliasChoices("VENICE_API_BASE", "DJI_VENICE_API_BASE"),
        description="Venice AI base URL",
    )
    venice_model: str = Field(
        default="llama-3.3-70b",
        validation_alias=AliasChoices("VENICE_MODEL", "DJI_VENICE_MODEL"),
        description="Venice LLM model name",
    )
    venice_vision_model: str = Field(
        default="qwen3-vl-235b-a22b",
        validation_alias=AliasChoices("VENICE_VISION_MODEL", "DJI_VENICE_VISION_MODEL"),
        description="Venice vision-language model name",
    )
    telegram_bot_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TELEGRAM_BOT_TOKEN", "DJI_TELEGRAM_BOT_TOKEN"),
        description="Telegram bot token",
    )
    telegram_allowed_users: str = Field(
        default="",
        validation_alias=AliasChoices("TELEGRAM_ALLOWED_USERS", "DJI_TELEGRAM_ALLOWED_USERS"),
        description="Comma-separated Telegram user IDs (empty = nobody may command)",
    )

    # Opt-in safety gates for live flight
    indoor_arm: int = Field(
        default=0,
        validation_alias=AliasChoices("INDOOR_ARM", "DJI_INDOOR_ARM"),
        description="Explicit human confirmation for indoor flight",
    )
    outdoor_arm: int = Field(
        default=0,
        validation_alias=AliasChoices("OUTDOOR_ARM", "DJI_OUTDOOR_ARM"),
        description="Explicit human confirmation for outdoor flight",
    )

    @field_validator("venice_api_key", "telegram_bot_token", mode="before")
    @classmethod
    def _blank_placeholders(cls, v: str | None) -> str | None:
        """Template values like 'your_venice_api_key_here' mean 'not configured'."""
        return None if _is_placeholder(v) else v.strip()

    @model_validator(mode="after")
    def _resolve_paths(self) -> "Settings":
        self.outdoor_geofence_file = resolve_path(self.outdoor_geofence_file)
        self.model_3d_export_dir = resolve_path(self.model_3d_export_dir)
        self.sqlite_db_path = resolve_path(self.sqlite_db_path)
        return self

    @property
    def allowed_telegram_ids(self) -> set[str]:
        return {u.strip() for u in self.telegram_allowed_users.split(",") if u.strip()}

    @property
    def venice_configured(self) -> bool:
        return self.venice_api_key is not None


# Singleton instance
settings = Settings()


def get_settings() -> Settings:
    """Return the global configuration instance."""
    return settings
