"""Single flight authority module. Zero direct I/O: inject bridge and dependencies."""

import asyncio
import json
import os
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .bridge.base import BaseBridge
from .config import Settings, get_settings


class FlightState(str, Enum):
    """Core flight authority state machine states."""

    DISCONNECTED = "DISCONNECTED"
    DISARMED = "DISARMED"
    ARMED_HOVER = "ARMED_HOVER"
    ARMED_ACTIVE = "ARMED_ACTIVE"
    EMERGENCY_HOVER = "EMERGENCY_HOVER"
    EMERGENCY_RTH = "EMERGENCY_RTH"
    RELEASED_TO_RC = "RELEASED_TO_RC"


class FlightMode(str, Enum):
    """The closed set of authorized flight modes."""

    DISARMED = "disarmed"
    HOVER = "hover"
    NARRATE = "narrate"
    SENTINEL = "sentinel"
    FOLLOW = "follow"
    ORBIT = "orbit"
    INDOOR_GRID = "indoor_grid"
    OUTDOOR_BOX = "outdoor_box"
    MANUAL_SIDECAR = "manual_sidecar"


@dataclass
class ArmToken:
    """Server-minted motion authorization token."""

    token: str
    mode: str
    minted_at: float
    ttl_seconds: float
    consumed: bool = False

    @property
    def is_expired(self) -> bool:
        return time.time() > (self.minted_at + self.ttl_seconds)


class Authority:
    """The single authority controlling aircraft sticks, mode execution, and safety gates."""

    def __init__(self, bridge: BaseBridge, settings: Settings | None = None) -> None:
        self.bridge = bridge
        self.settings = settings or get_settings()

        self.state: FlightState = FlightState.DISCONNECTED
        self.active_mode: FlightMode = FlightMode.DISARMED
        self.mode_params: dict[str, Any] = {}

        # Server-minted tokens
        self._tokens: dict[str, ArmToken] = {}

        # Watchdog & Timing
        self.last_heartbeat: float = time.time()
        self.latest_frame_age_ms: float = 0.0

        # Virtual stick outputs (clamped and managed solely by Authority)
        self.pitch: float = 0.0
        self.roll: float = 0.0
        self.yaw: float = 0.0
        self.throttle: float = 0.0

        # Estimated local position in meters relative to arming origin (ENU: x=East, y=North)
        self.local_x: float = 0.0
        self.local_y: float = 0.0

        # Geofence boundary vertices (local 2D coordinates [x, y])
        self.local_geofence: list[tuple[float, float]] = []
        self._load_geofence()

        # 10-20 Hz stick loop
        self._running: bool = False
        self._control_task: asyncio.Task | None = None
        self._mode_controller_cb: Callable[[], tuple[float, float, float, float]] | None = None

    def _load_geofence(self) -> None:
        """Load polygon geofence from file or default to indoor box."""
        gf_path = self.settings.outdoor_geofence_file
        if os.path.exists(gf_path):
            try:
                with open(gf_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "local_polygon" in data:
                        self.local_geofence = [tuple(p) for p in data["local_polygon"]]
            except Exception:
                pass
        if not self.local_geofence:
            # Default indoor 15m box
            box = self.settings.indoor_max_box
            self.local_geofence = [(0.0, 0.0), (box, 0.0), (box, box), (0.0, box)]

    async def start(self) -> None:
        """Start authority control loop."""
        self._running = True
        if self.bridge.is_connected():
            self.state = FlightState.DISARMED
        else:
            self.state = FlightState.DISCONNECTED

        if not self._control_task or self._control_task.done():
            self._control_task = asyncio.create_task(self._stick_loop())

    async def stop(self) -> None:
        """Stop authority control loop and disarm."""
        self._running = False
        if self._control_task:
            self._control_task.cancel()
            try:
                await self._control_task
            except asyncio.CancelledError:
                pass
        await self.bridge.send_sticks(0.0, 0.0, 0.0, 0.0)

    # --------------------------------------------------------------------------
    # Motion Token Management
    # --------------------------------------------------------------------------

    def arm_motion(self, target_mode: str) -> ArmToken:
        """Mint a cryptographic motion authorization token for a translating mode or takeoff."""
        token_str = secrets.token_hex(16)
        token = ArmToken(
            token=token_str,
            mode=target_mode.lower(),
            minted_at=time.time(),
            ttl_seconds=float(self.settings.token_ttl_seconds),
        )
        self._tokens[token_str] = token
        return token

    def verify_and_consume_token(self, token_str: str, target_mode: str) -> bool:
        """Verify token validity, mode binding, and expiration lease. Consume upon use."""
        token = self._tokens.get(token_str)
        if not token:
            return False
        if token.consumed or token.is_expired:
            return False
        if token.mode != target_mode.lower():
            return False
        token.consumed = True
        return True

    # --------------------------------------------------------------------------
    # Heartbeat & Video Freshness
    # --------------------------------------------------------------------------

    def refresh_heartbeat(self) -> None:
        """Refresh the 500 ms watchdog heartbeat."""
        self.last_heartbeat = time.time()

    def update_frame_age(self, age_ms: float) -> None:
        """Update recent frame age from video pipeline."""
        self.latest_frame_age_ms = age_ms

    # --------------------------------------------------------------------------
    # Geofence & Velocity Clamping
    # --------------------------------------------------------------------------

    def integrate_position(self, vx: float, vy: float, dt: float) -> None:
        """Integrate horizontal velocities into local ENU coordinate estimate."""
        self.local_x += vx * dt
        self.local_y += vy * dt

    def is_point_inside_geofence(self, x: float, y: float) -> bool:
        """Point-in-polygon test (including edges) for local 2D coordinates."""
        poly = self.local_geofence
        if len(poly) < 3:
            return True

        n = len(poly)
        eps = 1e-7

        # Check if point lies directly on any boundary edge
        for i in range(n):
            p1x, p1y = poly[i]
            p2x, p2y = poly[(i + 1) % n]
            if (
                min(p1x, p2x) - eps <= x <= max(p1x, p2x) + eps
                and min(p1y, p2y) - eps <= y <= max(p1y, p2y) + eps
            ):
                cross = (x - p1x) * (p2y - p1y) - (y - p1y) * (p2x - p1x)
                if abs(cross) <= 1e-5:
                    return True

        # Ray-casting algorithm for interior
        inside = False
        p1x, p1y = poly[0]
        for i in range(1, n + 1):
            p2x, p2y = poly[i % n]
            if (p1y > y) != (p2y > y):
                xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y + 1e-12) + p1x
                if x < xinters:
                    inside = not inside
            p1x, p1y = p2x, p2y

        return inside

    def clamp_velocity(
        self, vx: float, vy: float, vz: float, is_outdoor: bool = False
    ) -> tuple[float, float, float]:
        """Strictly clamp velocities to system config caps."""
        max_speed = (
            self.settings.outdoor_max_speed if is_outdoor else self.settings.indoor_max_speed
        )
        # Normalize 2D speed
        speed_2d = (vx**2 + vy**2) ** 0.5
        if speed_2d > max_speed and speed_2d > 1e-4:
            scale = max_speed / speed_2d
            vx *= scale
            vy *= scale

        # Vertical velocity cap
        vz = max(-1.0, min(1.0, vz))
        return round(vx, 3), round(vy, 3), round(vz, 3)

    # --------------------------------------------------------------------------
    # State Machine Transitions & Mode Control
    # --------------------------------------------------------------------------

    async def takeoff(self, token: str) -> dict[str, Any]:
        """Initiate takeoff. Requires valid server-minted token."""
        if not self.verify_and_consume_token(token, "takeoff"):
            raise PermissionError("Takeoff rejected: invalid, expired, or invented token.")

        if self.state not in (FlightState.DISARMED, FlightState.RELEASED_TO_RC):
            raise RuntimeError(f"Cannot takeoff from state {self.state.value}")

        self.refresh_heartbeat()
        await self.bridge.send_command("takeoff")
        self.state = FlightState.ARMED_HOVER
        self.active_mode = FlightMode.HOVER
        return {"status": "taking_off", "state": self.state.value}

    async def land(self, token: str | None = None) -> dict[str, Any]:
        """Initiate landing."""
        self.refresh_heartbeat()
        await self.bridge.send_command("land")
        self.state = FlightState.DISARMED
        self.active_mode = FlightMode.DISARMED
        self._mode_controller_cb = None
        self.pitch = self.roll = self.yaw = self.throttle = 0.0
        return {"status": "landing", "state": self.state.value}

    async def rth(self) -> dict[str, Any]:
        """Initiate Return to Home."""
        self.refresh_heartbeat()
        await self.bridge.send_command("rth")
        self.state = FlightState.EMERGENCY_RTH
        self.active_mode = FlightMode.HOVER
        self._mode_controller_cb = None
        self.pitch = self.roll = self.yaw = self.throttle = 0.0
        return {"status": "returning_home", "state": self.state.value}

    async def emergency_stop(self) -> dict[str, Any]:
        """Unconditional emergency stop: always succeeds immediately."""
        self.pitch = self.roll = self.yaw = self.throttle = 0.0
        await self.bridge.send_sticks(0.0, 0.0, 0.0, 0.0)
        await self.bridge.send_command("emergency_stop")
        self.state = FlightState.EMERGENCY_HOVER
        self.active_mode = FlightMode.HOVER
        self._mode_controller_cb = None
        return {"status": "emergency_stop_triggered", "state": self.state.value}

    async def release_to_rc(self) -> dict[str, Any]:
        """Relinquish virtual stick authority back to human pilot RC."""
        self.pitch = self.roll = self.yaw = self.throttle = 0.0
        await self.bridge.send_sticks(0.0, 0.0, 0.0, 0.0)
        await self.bridge.send_command("release_to_rc")
        self.state = FlightState.RELEASED_TO_RC
        self.active_mode = FlightMode.DISARMED
        self._mode_controller_cb = None
        return {"status": "released_to_rc", "state": self.state.value}

    async def set_mode(
        self,
        mode_name: str,
        token: str | None = None,
        params: dict[str, Any] | None = None,
        controller_cb: Callable[[], tuple[float, float, float, float]] | None = None,
    ) -> dict[str, Any]:
        """Switch flight mode with token verification for translating modes."""
        mode_clean = mode_name.lower().strip()
        try:
            target_mode = FlightMode(mode_clean)
        except ValueError:
            raise ValueError(
                f"Unknown flight mode: {mode_name}. Must be one of {[m.value for m in FlightMode]}"
            )

        # Hover and Narrate do not translate; translating modes REQUIRE token
        translating_modes = {
            FlightMode.FOLLOW,
            FlightMode.ORBIT,
            FlightMode.INDOOR_GRID,
            FlightMode.OUTDOOR_BOX,
            FlightMode.MANUAL_SIDECAR,
        }

        if target_mode in translating_modes:
            if not token or not self.verify_and_consume_token(token, target_mode.value):
                raise PermissionError(
                    f"Mode {target_mode.value} requires a valid server-minted token via arm_motion()."
                )

        if self.state not in (FlightState.ARMED_HOVER, FlightState.ARMED_ACTIVE):
            raise RuntimeError(
                f"Cannot engage mode {target_mode.value} while in state {self.state.value}. Aircraft must be ARMED."
            )

        self.refresh_heartbeat()
        self.active_mode = target_mode
        self.mode_params = params or {}
        self._mode_controller_cb = controller_cb
        self.state = (
            FlightState.ARMED_ACTIVE if target_mode != FlightMode.HOVER else FlightState.ARMED_HOVER
        )

        return {"status": "mode_set", "mode": self.active_mode.value, "state": self.state.value}

    # --------------------------------------------------------------------------
    # 10-20 Hz Virtual Stick & Watchdog Loop
    # --------------------------------------------------------------------------

    async def _stick_loop(self) -> None:
        """Dedicated high-frequency loop commanding sticks with hard watchdog failsafes."""
        dt = 1.0 / float(self.settings.stick_loop_freq_hz)

        while self._running:
            now = time.time()
            telem = self.bridge.get_latest_telemetry()

            # 1. Check bridge link status
            if not self.bridge.is_connected():
                self.state = FlightState.DISCONNECTED
                await asyncio.sleep(dt)
                continue

            # Update integrated local position from telemetry velocities
            self.integrate_position(telem.vx, telem.vy, dt)

            # 2. Check battery level (< 20% triggers RTH)
            if (
                telem.is_flying
                and telem.battery_percent < 20
                and self.state != FlightState.EMERGENCY_RTH
            ):
                await self.rth()
                continue

            # 3. Check obstacle OSD alert
            if telem.obstacle_detected and self.state == FlightState.ARMED_ACTIVE:
                self.pitch = self.roll = self.yaw = self.throttle = 0.0
                self.state = FlightState.EMERGENCY_HOVER
                self.active_mode = FlightMode.HOVER
                self._mode_controller_cb = None

            # 4. Check video freshness (age > 1000 ms forces hover)
            if self.latest_frame_age_ms > float(self.settings.video_stale_threshold_ms):
                if self.state == FlightState.ARMED_ACTIVE:
                    self.pitch = self.roll = self.yaw = self.throttle = 0.0
                    self.state = FlightState.EMERGENCY_HOVER
                    self.active_mode = FlightMode.HOVER
                    self._mode_controller_cb = None

            # 5. Check 500 ms Watchdog timer
            watchdog_limit = float(self.settings.watchdog_timeout_ms) / 1000.0
            if (now - self.last_heartbeat) > watchdog_limit:
                # Watchdog tripped: zero sticks immediately
                self.pitch = self.roll = self.yaw = self.throttle = 0.0
                if self.state == FlightState.ARMED_ACTIVE:
                    self.state = FlightState.EMERGENCY_HOVER
                    self.active_mode = FlightMode.HOVER
                    self._mode_controller_cb = None

            # 6. Evaluate active mode controller if in ARMED_ACTIVE
            if self.state == FlightState.ARMED_ACTIVE and self._mode_controller_cb:
                try:
                    p, r, y, th = self._mode_controller_cb()
                    is_outdoor = self.active_mode == FlightMode.OUTDOOR_BOX
                    self.roll, self.pitch, self.throttle = self.clamp_velocity(r, p, th, is_outdoor)
                    self.yaw = max(-1.0, min(1.0, y))

                    # Geofence boundary check for translation
                    # If current position is near or outside boundary, zero translational sticks
                    if not self.is_point_inside_geofence(self.local_x, self.local_y):
                        self.pitch = self.roll = 0.0
                except Exception:
                    self.pitch = self.roll = self.yaw = self.throttle = 0.0
            elif self.state in (
                FlightState.ARMED_HOVER,
                FlightState.EMERGENCY_HOVER,
                FlightState.EMERGENCY_RTH,
            ):
                self.pitch = self.roll = self.yaw = self.throttle = 0.0

            # 7. Transmit sticks to bridge
            if self.state not in (FlightState.DISCONNECTED, FlightState.RELEASED_TO_RC):
                await self.bridge.send_sticks(self.pitch, self.roll, self.yaw, self.throttle)

            await asyncio.sleep(dt)

    def get_status(self) -> dict[str, Any]:
        """Return comprehensive authority and flight status dictionary."""
        telem = self.bridge.get_latest_telemetry()
        now = time.time()
        return {
            "state": self.state.value,
            "mode": self.active_mode.value,
            "is_flying": telem.is_flying,
            "battery_percent": telem.battery_percent,
            "altitude_agl": telem.altitude_agl,
            "latitude": telem.latitude,
            "longitude": telem.longitude,
            "heading_deg": telem.yaw,
            "velocities": {"vx": telem.vx, "vy": telem.vy, "vz": telem.vz},
            "local_position": {"x": round(self.local_x, 2), "y": round(self.local_y, 2)},
            "sticks": {
                "pitch": round(self.pitch, 2),
                "roll": round(self.roll, 2),
                "yaw": round(self.yaw, 2),
                "throttle": round(self.throttle, 2),
            },
            "watchdog_ok": (now - self.last_heartbeat)
            <= (self.settings.watchdog_timeout_ms / 1000.0),
            "video_age_ms": round(self.latest_frame_age_ms, 1),
            "video_fresh": self.latest_frame_age_ms <= self.settings.video_stale_threshold_ms,
            "obstacle_detected": telem.obstacle_detected,
            "bridge_connected": self.bridge.is_connected(),
        }
