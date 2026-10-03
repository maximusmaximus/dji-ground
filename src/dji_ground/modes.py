"""Implementation of the seven flight modes and trajectory controllers."""

import math
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
        self.mission_progress: dict = {}

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
    # Shared: bounded closed-loop waypoint follower
    # --------------------------------------------------------------------------
    def _waypoint_follower(
        self,
        mode: str,
        waypoints: list[tuple[float, float]],
        speed: float,
        tolerance_m: float = 0.3,
        face_point: tuple[float, float] | None = None,
    ) -> Callable[[], tuple[float, float, float, float]]:
        """Fly waypoints in the local ENU frame, then hold zero translation.

        Sticks follow the authority convention: roll = East velocity, pitch = North velocity.
        Waypoints outside the geofence are dropped up front so the path never targets them.
        """
        safe = [w for w in waypoints if self.authority.is_point_inside_geofence(*w)]
        dropped = len(waypoints) - len(safe)
        progress = {
            "mode": mode,
            "waypoint_index": 0,
            "total_waypoints": len(safe),
            "dropped_outside_geofence": dropped,
            "complete": len(safe) == 0,
        }
        self.mission_progress = progress

        def controller() -> tuple[float, float, float, float]:
            ax = self.authority
            i = progress["waypoint_index"]
            while i < len(safe):
                tx, ty = safe[i]
                if math.hypot(tx - ax.local_x, ty - ax.local_y) <= tolerance_m:
                    i += 1
                    continue
                break
            progress["waypoint_index"] = i
            if i >= len(safe):
                progress["complete"] = True
                return (0.0, 0.0, 0.0, 0.0)

            tx, ty = safe[i]
            dx, dy = tx - ax.local_x, ty - ax.local_y
            dist = math.hypot(dx, dy)
            v = min(speed, 1.5 * dist)  # slow down on approach
            east, north = dx / dist * v, dy / dist * v

            yaw = 0.0
            if face_point is not None:
                fx, fy = face_point[0] - ax.local_x, face_point[1] - ax.local_y
                bearing = math.degrees(math.atan2(fx, fy)) % 360.0  # 0 = North, clockwise
                heading = ax.bridge.get_latest_telemetry().yaw
                err = (bearing - heading + 540.0) % 360.0 - 180.0
                yaw = max(-1.0, min(1.0, err / 45.0))
            return (north, east, yaw, 0.0)

        return controller

    # --------------------------------------------------------------------------
    # 4. Orbit Mode: one full revolution around a POI, camera facing the centre
    # --------------------------------------------------------------------------
    def get_orbit_controller(
        self, radius: float = 3.0, speed_rad_s: float = 0.2, segments: int = 24
    ) -> Callable[[], tuple[float, float, float, float]]:
        """Orbit a point `radius` metres North of the current position, then hold."""
        self._orbit_start_time = time.time()
        self._orbit_radius = radius
        x0, y0 = self.authority.local_x, self.authority.local_y
        cx, cy = x0, y0 + radius
        start_angle = math.atan2(y0 - cy, x0 - cx)
        waypoints = [
            (
                cx + radius * math.cos(start_angle + 2 * math.pi * k / segments),
                cy + radius * math.sin(start_angle + 2 * math.pi * k / segments),
            )
            for k in range(1, segments + 1)
        ]
        return self._waypoint_follower(
            "orbit", waypoints, speed=speed_rad_s * radius, face_point=(cx, cy)
        )

    def get_orbit_hold(self) -> Callable[[], tuple[float, float, float, float]]:
        """Return fail-closed zero-stick hold for orbit mode."""
        return orbit_hold()

    # --------------------------------------------------------------------------
    # 5. Indoor Grid Mode: serpentine lawnmower around the current position
    # --------------------------------------------------------------------------
    def get_indoor_grid_controller(
        self,
        polygon: list[tuple[float, float]] | None = None,
        width: float = 4.0,
        depth: float = 4.0,
        spacing: float = 1.0,
    ) -> Callable[[], tuple[float, float, float, float]]:
        """Lawnmower lanes (East-West) stepping North; waypoints outside the fence are skipped."""
        x0, y0 = self.authority.local_x, self.authority.local_y
        lanes = max(1, int(depth / spacing) + 1)
        waypoints: list[tuple[float, float]] = []
        for lane in range(lanes):
            y = y0 + lane * spacing
            left, right = (x0 - width / 2, y), (x0 + width / 2, y)
            waypoints.extend([left, right] if lane % 2 == 0 else [right, left])
        self._grid_waypoints = waypoints
        self._grid_index = 0
        speed = self.authority.settings.indoor_max_speed
        return self._waypoint_follower("indoor_grid", waypoints, speed=speed)

    def get_indoor_grid_hold(self) -> Callable[[], tuple[float, float, float, float]]:
        """Return fail-closed zero-stick hold for indoor grid mode."""
        return indoor_grid_hold()

    # --------------------------------------------------------------------------
    # 6. Outdoor Box Mode: square perimeter centred on the current position
    # --------------------------------------------------------------------------
    def get_outdoor_box_controller(
        self, side: float = 10.0
    ) -> Callable[[], tuple[float, float, float, float]]:
        """Fly the perimeter of a square, then return to the start point and hold."""
        x0, y0 = self.authority.local_x, self.authority.local_y
        h = side / 2.0
        waypoints = [
            (x0 + h, y0 - h),
            (x0 + h, y0 + h),
            (x0 - h, y0 + h),
            (x0 - h, y0 - h),
            (x0 + h, y0 - h),
            (x0, y0),
        ]
        speed = self.authority.settings.outdoor_max_speed
        return self._waypoint_follower("outdoor_box", waypoints, speed=speed)

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
