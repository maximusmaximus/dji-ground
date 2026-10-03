"""Configuration settings for dji-ground using Pydantic Settings."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for flight authority, safety gates, and bridges."""

    model_config = SettingsConfigDict(
        env_prefix="DJI_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Bridge networking
    bridge_host: str = Field(default="127.0.0.1", description="OpenDJI bridge host IP")
    telemetry_port: int = Field(default=8001, description="Telemetry stream TCP port")
    video_port: int = Field(default=8002, description="H.264 video stream TCP port")
    command_port: int = Field(default=8003, description="Command & stick TCP port")
    bridge_mode: Literal["fake", "opendji"] = Field(
        default="fake", description="Bridge implementation to use"
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
        default="fixtures/geofence_sample.json", description="Path to geofence GeoJSON/JSON file"
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
        default="./data/models_3d", description="Directory for 3D model exports"
    )

    # Database
    sqlite_db_path: str = Field(
        default="dji_ground_session.sqlite", description="Path to SQLite database"
    )

    # Venice AI API & Telegram
    venice_api_key: str | None = Field(default=None, description="Venice AI API key")
    venice_api_base: str = Field(
        default="https://api.venice.ai/api/v1", description="Venice AI base URL"
    )
    venice_model: str = Field(default="llama-3.3-70b", description="Venice LLM model name")
    venice_vision_model: str = Field(default="qwen-2.5-vl-72b", description="Venice VLM model name")
    telegram_bot_token: str | None = Field(default=None, description="Telegram bot token")
    telegram_allowed_users: str = Field(default="", description="Comma-separated Telegram user IDs")

    # Opt-in safety gates for live flight
    indoor_arm: int = Field(default=0, description="Explicit human confirmation for indoor flight")
    outdoor_arm: int = Field(
        default=0, description="Explicit human confirmation for outdoor flight"
    )


# Singleton instance
settings = Settings()


def get_settings() -> Settings:
    """Return the global configuration instance."""
    return settings
