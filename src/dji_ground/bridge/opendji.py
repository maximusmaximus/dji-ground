"""OpenDJI TCP three-socket bridge client."""

import asyncio
import json
import struct
import time

from .base import BaseBridge, TelemetryData


class OpenDJIBridge(BaseBridge):
    """Client for OpenDJI Android USB-to-PC bridge (three sockets)."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        telemetry_port: int = 8001,
        video_port: int = 8002,
        command_port: int = 8003,
    ) -> None:
        self.host = host
        self.telemetry_port = telemetry_port
        self.video_port = video_port
        self.command_port = command_port

        self._connected = False
        self._telemetry = TelemetryData()

        # Socket readers and writers
        self._telem_reader: asyncio.StreamReader | None = None
        self._telem_writer: asyncio.StreamWriter | None = None
        self._video_reader: asyncio.StreamReader | None = None
        self._video_writer: asyncio.StreamWriter | None = None
        self._cmd_reader: asyncio.StreamReader | None = None
        self._cmd_writer: asyncio.StreamWriter | None = None

        self._telem_task: asyncio.Task | None = None

    async def connect(self) -> bool:
        """Connect to the 3 OpenDJI TCP sockets."""
        try:
            self._telem_reader, self._telem_writer = await asyncio.open_connection(
                self.host, self.telemetry_port
            )
            self._video_reader, self._video_writer = await asyncio.open_connection(
                self.host, self.video_port
            )
            self._cmd_reader, self._cmd_writer = await asyncio.open_connection(
                self.host, self.command_port
            )
            self._connected = True
            self._telem_task = asyncio.create_task(self._read_telemetry_loop())
            return True
        except Exception:
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect all sockets cleanly."""
        self._connected = False
        if self._telem_task:
            self._telem_task.cancel()
        for writer in [self._telem_writer, self._video_writer, self._cmd_writer]:
            if writer:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass

    def is_connected(self) -> bool:
        return self._connected

    async def send_sticks(self, pitch: float, roll: float, yaw: float, throttle: float) -> bool:
        """Send virtual stick values to command socket."""
        if not self._cmd_writer or not self._connected:
            return False
        try:
            # Packet: magic 'STIK' + 4 floats
            packet = struct.pack("!4sffff", b"STIK", pitch, roll, yaw, throttle)
            self._cmd_writer.write(packet)
            await self._cmd_writer.drain()
            return True
        except Exception:
            return False

    async def send_command(self, cmd: str) -> bool:
        """Send discrete text command to command socket."""
        if not self._cmd_writer or not self._connected:
            return False
        try:
            payload = json.dumps({"command": cmd}).encode("utf-8") + b"\n"
            self._cmd_writer.write(payload)
            await self._cmd_writer.drain()
            return True
        except Exception:
            return False

    def get_latest_telemetry(self) -> TelemetryData:
        return self._telemetry

    async def get_video_chunk(self) -> bytes | None:
        """Read up to 4096 bytes from video socket."""
        if not self._video_reader or not self._connected:
            return None
        try:
            return await self._video_reader.read(4096)
        except Exception:
            return None

    async def _read_telemetry_loop(self) -> None:
        """Read streaming lines of JSON telemetry."""
        while self._connected and self._telem_reader:
            try:
                line = await self._telem_reader.readline()
                if not line:
                    break
                data = json.loads(line.decode("utf-8"))
                self._telemetry.timestamp_ms = data.get("timestamp_ms", time.time() * 1000)
                self._telemetry.latitude = data.get("latitude", self._telemetry.latitude)
                self._telemetry.longitude = data.get("longitude", self._telemetry.longitude)
                self._telemetry.altitude_agl = data.get(
                    "altitude_agl", self._telemetry.altitude_agl
                )
                self._telemetry.roll = data.get("roll", self._telemetry.roll)
                self._telemetry.pitch = data.get("pitch", self._telemetry.pitch)
                self._telemetry.yaw = data.get("yaw", self._telemetry.yaw)
                self._telemetry.vx = data.get("vx", self._telemetry.vx)
                self._telemetry.vy = data.get("vy", self._telemetry.vy)
                self._telemetry.vz = data.get("vz", self._telemetry.vz)
                self._telemetry.battery_percent = data.get(
                    "battery_percent", self._telemetry.battery_percent
                )
                self._telemetry.gps_satellite_count = data.get(
                    "gps_satellite_count", self._telemetry.gps_satellite_count
                )
                self._telemetry.signal_quality = data.get(
                    "signal_quality", self._telemetry.signal_quality
                )
                self._telemetry.flight_mode = data.get("flight_mode", self._telemetry.flight_mode)
                self._telemetry.is_flying = data.get("is_flying", self._telemetry.is_flying)
                self._telemetry.gimbal_pitch = data.get(
                    "gimbal_pitch", self._telemetry.gimbal_pitch
                )
                self._telemetry.obstacle_detected = data.get("obstacle_detected", False)
            except Exception:
                await asyncio.sleep(0.05)
