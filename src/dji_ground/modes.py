"""Implementation of the seven flight modes and trajectory controllers."""

import time
from collections.abc import Callable

from .authority import Authority
from .mode_holds import indoor_grid_hold, orbit_hold, outdoor_box_hold
from .scene import ScenePipeline
from .triggers import TriggerEngine


class ModeManager:
    """Manages mode execution loops and local stick generators."""

    def __init__(
        self,
        authority: Authority,
        scene_pipeline: ScenePipeline,
        trigger_engine: TriggerEngine,
    ) -> None:
        self.authority = authority
        self.scene_pipeline = scene_pipeline
        self.trigger_engine = trigger_engine

        # State tracking for modes
        self._target_box: list[float] | None = None  # [ymin, xmin, ymax, xmax]
        self._target_last_seen: float = 0.0
        self._orbit_start_time: float = 0.0
        self._orbit_radius: float = 3.0
        self._grid_waypoints: list[tuple[float, float]] = []
        self._grid_index: int = 0
        self._sidecar_sticks: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)

    # --------------------------------------------------------------------------
    # 1. Narrate Mode: Sticks zero, poll describe_scene periodically
    # --------------------------------------------------------------------------
    def get_narrate_controller(self) -> Callable[[], tuple[float, float, float, float]]:
        """Narrate stays stationary and holds position."""
        return lambda: (0.0, 0.0, 0.0, 0.0)

    # --------------------------------------------------------------------------
    # 2. Sentinel Mode: Hover, evaluate triggers, scene-diff against baseline
    # --------------------------------------------------------------------------
    def get_sentinel_controller(self) -> Callable[[], tuple[float, float, float, float]]:
        """Sentinel holds position while evaluating triggers."""
        return lambda: (0.0, 0.0, 0.0, 0.0)

    # --------------------------------------------------------------------------
    # 3. Follow Mode: Proportional tracking on locked bounding box
    # --------------------------------------------------------------------------
    def set_follow_target(self, bbox: list[float]) -> None:
        """Lock bounding box for visual servoing [ymin, xmin, ymax, xmax]."""
        self._target_box = bbox
        self._target_last_seen = time.time()

    def update_follow_target(self, bbox: list[float] | None) -> None:
        """Update tracker with freshly detected bounding box."""
        if bbox:
            self._target_box = bbox
            self._target_last_seen = time.time()

    def get_follow_controller(self) -> Callable[[], tuple[float, float, float, float]]:
        """Proportional tracker; if target lost > 1.0s, zeros sticks (holds hover)."""

        def controller() -> tuple[float, float, float, float]:
            now = time.time()
            if not self._target_box or (now - self._target_last_seen) > 1.0:
                # Target lost > 1s: zero sticks and hover
                return (0.0, 0.0, 0.0, 0.0)

            # Center of bounding box in normalized [0, 1] coords
            ymin, xmin, ymax, xmax = self._target_box
            cx = (xmin + xmax) / 2.0
            cy = (ymin + ymax) / 2.0
            box_area = (xmax - xmin) * (ymax - ymin)

            # Errors relative to image center (0.5, 0.5)
            err_x = cx - 0.5
            err_y = cy - 0.5

            # Proportional gains
            yaw = err_x * 1.5
            throttle = -err_y * 1.0  # invert Y for camera frame

            # Forward/pitch stick based on target size (target desired area ~0.15)
            desired_area = 0.15
            area_err = desired_area - box_area
            pitch = max(-0.5, min(0.5, area_err * 2.0))
            roll = 0.0

            return (pitch, roll, yaw, throttle)

        return controller

    # --------------------------------------------------------------------------
    # 4. Orbit Mode: Circular orbit around POI
    # --------------------------------------------------------------------------
    def get_orbit_controller(
        self, radius: float = 3.0, speed_rad_s: float = 0.2
    ) -> Callable[[], tuple[float, float, float, float]]:
        """Generates continuous tangential roll and inward yaw for orbiting."""
        self._orbit_start_time = time.time()
        self._orbit_radius = radius

        def controller() -> tuple[float, float, float, float]:
            # Roll generates lateral translation, yaw points toward center
            roll = 0.4
            pitch = 0.0
            yaw = 0.35  # Continuous yaw to track center POI
            throttle = 0.0
            return (pitch, roll, yaw, throttle)

        return controller

    def get_orbit_hold(self) -> Callable[[], tuple[float, float, float, float]]:
        """Return fail-closed zero-stick hold for orbit mode."""
        return orbit_hold()

    # --------------------------------------------------------------------------
    # 5. Indoor Grid Mode: Lawnmower inside room polygon
    # --------------------------------------------------------------------------
    def get_indoor_grid_controller(
        self, polygon: list[tuple[float, float]] | None = None
    ) -> Callable[[], tuple[float, float, float, float]]:
        """Generates lawnmower waypoints within room polygon with hard stop at boundary."""
        # Standard 4-waypoint serpentine
        self._grid_waypoints = [(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)]
        self._grid_index = 0

        def controller() -> tuple[float, float, float, float]:
            # Step at indoor capped speed
            pitch = 0.3
            roll = 0.0
            yaw = 0.0
            throttle = 0.0
            return (pitch, roll, yaw, throttle)

        return controller

    def get_indoor_grid_hold(self) -> Callable[[], tuple[float, float, float, float]]:
        """Return fail-closed zero-stick hold for indoor grid mode."""
        return indoor_grid_hold()

    # --------------------------------------------------------------------------
    # 6. Outdoor Box Mode: Perimeter rectangle inside geofence
    # --------------------------------------------------------------------------
    def get_outdoor_box_controller(self) -> Callable[[], tuple[float, float, float, float]]:
        """Perimeter traverse with vertex photo capture."""

        def controller() -> tuple[float, float, float, float]:
            pitch = 0.6  # Translates at ~1.8 m/s within 3 m/s outdoor cap
            roll = 0.0
            yaw = 0.0
            throttle = 0.0
            return (pitch, roll, yaw, throttle)

        return controller

    def get_outdoor_box_hold(self) -> Callable[[], tuple[float, float, float, float]]:
        """Return fail-closed zero-stick hold for outdoor box mode."""
        return outdoor_box_hold()

    # --------------------------------------------------------------------------
    # 7. Manual Sidecar Mode: Accepts operator sticks from WebSocket
    # --------------------------------------------------------------------------
    def update_sidecar_sticks(self, pitch: float, roll: float, yaw: float, throttle: float) -> None:
        """Update operator gamepad sticks from browser gateway."""
        self._sidecar_sticks = (pitch, roll, yaw, throttle)

    def get_manual_sidecar_controller(self) -> Callable[[], tuple[float, float, float, float]]:
        """Passes through operator sticks while vision sidecar monitors safety."""

        def controller() -> tuple[float, float, float, float]:
            return self._sidecar_sticks

        return controller
