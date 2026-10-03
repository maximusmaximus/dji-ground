"""Base class and data contracts for drone communication bridges."""

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class TelemetryData:
    """Standardized aircraft telemetry packet emitted at 10-20 Hz."""

    timestamp_ms: float = 0.0
    latitude: float = 37.7749
    longitude: float = -122.4194
    altitude_agl: float = 0.0
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    vz: float = 0.0
    battery_percent: int = 100
    gps_satellite_count: int = 14
    signal_quality: int = 95
    flight_mode: str = "P-GPS"
    is_flying: bool = False
    gimbal_pitch: float = 0.0
    obstacle_detected: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert telemetry to dictionary."""
        return asdict(self)


class BaseBridge(ABC):
    """Abstract interface for communicating with DJI aircraft."""

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection to telemetry, video, and command channels."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close all network sockets and reset state."""

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if connection to aircraft/bridge is alive."""

    @abstractmethod
    async def send_sticks(self, pitch: float, roll: float, yaw: float, throttle: float) -> bool:
        """Send virtual stick values in range [-1.0, 1.0]."""

    @abstractmethod
    async def send_command(self, cmd: str) -> bool:
        """Send discrete aircraft command (takeoff, land, rth, emergency_stop, release_to_rc)."""

    @abstractmethod
    def get_latest_telemetry(self) -> TelemetryData:
        """Retrieve the most recent telemetry packet."""

    @abstractmethod
    async def get_video_chunk(self) -> bytes | None:
        """Retrieve next H.264 video bytes chunk."""
