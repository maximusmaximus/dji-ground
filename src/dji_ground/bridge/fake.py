"""Simulated aircraft bridge for automated testing, CI, and hardware-free development."""

import asyncio
import os
import time

from .base import BaseBridge, TelemetryData


class FakeBridge(BaseBridge):
    """Fake drone bridge providing deterministic physics, video playback, and fault injection."""

    def __init__(self, fixture_video_path: str = "fixtures/sample_h264_stream.h264") -> None:
        self.fixture_video_path = fixture_video_path
        self._connected: bool = False
        self._telemetry = TelemetryData(timestamp_ms=time.time() * 1000)
        self._running: bool = False
        self._loop_task: asyncio.Task | None = None

        # State variables
        self.x: float = 0.0
        self.y: float = 0.0
        self.z: float = 0.0  # altitude
        self.yaw_deg: float = 0.0
        self.curr_pitch: float = 0.0
        self.curr_roll: float = 0.0
        self.curr_yaw: float = 0.0
        self.curr_throttle: float = 0.0

        # Command & stick audit trail for tests
        self.command_history: list[tuple[float, str]] = []
        self.stick_history: list[tuple[float, float, float, float, float]] = []

        # Fault injection
        self._video_drop_until: float = 0.0
        self._link_dropped: bool = False

        # Video chunk buffer
        self._video_bytes: bytes = b""
        self._video_offset: int = 0
        self._load_fixture_video()

    def _load_fixture_video(self) -> None:
        if os.path.exists(self.fixture_video_path):
            with open(self.fixture_video_path, "rb") as f:
                self._video_bytes = f.read()

    async def connect(self) -> bool:
        """Connect and start the simulated physics & telemetry loop."""
        self._connected = True
        self._running = True
        self._telemetry.timestamp_ms = time.time() * 1000
        if not self._loop_task or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._simulation_loop())
        return True

    async def disconnect(self) -> None:
        """Disconnect and stop simulation loop."""
        self._running = False
        self._connected = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

    def is_connected(self) -> bool:
        return self._connected and not self._link_dropped

    async def send_sticks(self, pitch: float, roll: float, yaw: float, throttle: float) -> bool:
        """Apply virtual sticks and record for verification."""
        now = time.time()
        self.curr_pitch = pitch
        self.curr_roll = roll
        self.curr_yaw = yaw
        self.curr_throttle = throttle
        self.stick_history.append((now, pitch, roll, yaw, throttle))
        return True

    async def send_command(self, cmd: str) -> bool:
        """Execute discrete flight command."""
        now = time.time()
        self.command_history.append((now, cmd))

        if cmd == "takeoff":
            self._telemetry.is_flying = True
            self.z = 1.2
            self._telemetry.altitude_agl = 1.2
        elif cmd == "land":
            self._telemetry.is_flying = False
            self.z = 0.0
            self._telemetry.altitude_agl = 0.0
            self.curr_pitch = self.curr_roll = self.curr_yaw = self.curr_throttle = 0.0
        elif cmd == "rth":
            # Reposition toward home (0,0)
            self.x *= 0.5
            self.y *= 0.5
        elif cmd == "emergency_stop":
            # Immediately zero sticks and halt
            self.curr_pitch = self.curr_roll = self.curr_yaw = self.curr_throttle = 0.0
        elif cmd == "release_to_rc":
            # Zero simulated sticks
            self.curr_pitch = self.curr_roll = self.curr_yaw = self.curr_throttle = 0.0
        return True

    def get_latest_telemetry(self) -> TelemetryData:
        return self._telemetry

    async def get_video_chunk(self) -> bytes | None:
        """Return next chunk of H.264 stream unless video drop injected."""
        if time.time() < self._video_drop_until:
            # Video lost
            return None
        if not self._video_bytes:
            return None

        # Simulate streaming rate and yield to event loop
        await asyncio.sleep(0.02)
        chunk_size = 4096
        start = self._video_offset
        end = start + chunk_size
        chunk = self._video_bytes[start:end]
        self._video_offset = end if end < len(self._video_bytes) else 0
        return chunk

    async def _simulation_loop(self) -> None:
        """15 Hz physics integration loop."""
        dt = 1.0 / 15.0
        while self._running:
            now = time.time()
            if self._telemetry.is_flying:
                # Update positions based on sticks
                # Pitch -> Y, Roll -> X, Throttle -> Z, Yaw -> Yaw
                self.x += self.curr_roll * 1.5 * dt
                self.y += self.curr_pitch * 1.5 * dt
                self.z = max(0.0, self.z + self.curr_throttle * 1.0 * dt)
                self.yaw_deg = (self.yaw_deg + self.curr_yaw * 45.0 * dt) % 360.0

            self._telemetry.timestamp_ms = now * 1000
            self._telemetry.altitude_agl = round(self.z, 2)
            self._telemetry.yaw = round(self.yaw_deg, 1)
            self._telemetry.pitch = round(self.curr_pitch * 15.0, 1)
            self._telemetry.roll = round(self.curr_roll * 15.0, 1)
            self._telemetry.vx = round(self.curr_roll * 1.5, 2)
            self._telemetry.vy = round(self.curr_pitch * 1.5, 2)
            self._telemetry.vz = round(self.curr_throttle * 1.0, 2)

            await asyncio.sleep(dt)

    # Fault injection helpers
    def inject_video_loss(self, duration_s: float) -> None:
        """Inject video signal loss for specified duration in seconds."""
        self._video_drop_until = time.time() + duration_s

    def inject_battery_level(self, percent: int) -> None:
        """Override battery percentage."""
        self._telemetry.battery_percent = percent

    def inject_obstacle(self, detected: bool = True) -> None:
        """Simulate obstacle detection alert."""
        self._telemetry.obstacle_detected = detected

    def inject_link_loss(self) -> None:
        """Simulate complete connection loss."""
        self._link_dropped = True
