"""Fail-closed stick generators for modes that do not yet follow a path.

Orbit, indoor grid, and outdoor box previously returned a constant pitch or roll.
That translates forever. Until a waypoint follower exists, these return zero
translation.
"""

from collections.abc import Callable


def orbit_hold(radius: float = 3.0, speed_rad_s: float = 0.2) -> Callable[[], tuple[float, float, float, float]]:
    def controller() -> tuple[float, float, float, float]:
        _ = (radius, speed_rad_s)
        return (0.0, 0.0, 0.0, 0.0)

    return controller


def indoor_grid_hold() -> Callable[[], tuple[float, float, float, float]]:
    def controller() -> tuple[float, float, float, float]:
        return (0.0, 0.0, 0.0, 0.0)

    return controller


def outdoor_box_hold() -> Callable[[], tuple[float, float, float, float]]:
    def controller() -> tuple[float, float, float, float]:
        return (0.0, 0.0, 0.0, 0.0)

    return controller
