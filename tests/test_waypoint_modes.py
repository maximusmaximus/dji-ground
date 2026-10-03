"""Translating modes fly bounded waypoint paths, finish, and then hold (no runaway sticks)."""

import math

import pytest

from dji_ground.authority import Authority
from dji_ground.bridge.fake import FakeBridge
from dji_ground.config import Settings
from dji_ground.modes import ModeManager


@pytest.fixture
def centred(tmp_path, scene_pipeline, trigger_engine):
    settings = Settings(
        _env_file=None,
        sqlite_db_path=str(tmp_path / "s.sqlite"),
        outdoor_geofence_file="config/geofence_default.json",  # +/-7.5 m around takeoff
    )
    authority = Authority(FakeBridge(), settings)
    return authority, ModeManager(authority, scene_pipeline, trigger_engine)


def _fly(authority, controller, steps=4000, dt=0.05):
    """Ideal kinematics: sticks are m/s (roll=East, pitch=North)."""
    path = []
    for _ in range(steps):
        p, r, _y, _t = controller()
        if (p, r) == (0.0, 0.0):
            break
        authority.local_x += r * dt
        authority.local_y += p * dt
        path.append((authority.local_x, authority.local_y))
    return path


def test_outdoor_box_completes_and_returns_to_start(centred):
    authority, modes = centred
    ctl = modes.get_outdoor_box_controller(side=6.0)
    path = _fly(authority, ctl)
    assert path, "controller never produced motion"
    assert modes.mission_progress["complete"] is True
    assert math.hypot(authority.local_x, authority.local_y) < 0.35
    assert max(abs(x) for x, _ in path) <= 3.3
    assert ctl() == (0.0, 0.0, 0.0, 0.0)  # holds after completion, forever


def test_box_respects_speed_and_first_leg_heads_south_east(centred):
    authority, modes = centred
    ctl = modes.get_outdoor_box_controller(side=6.0)
    p, r, _, _ = ctl()
    assert r > 0 and p < 0  # first waypoint is (+3, -3)
    assert math.hypot(p, r) <= authority.settings.outdoor_max_speed + 1e-9


def test_waypoints_outside_geofence_are_dropped(centred):
    authority, modes = centred
    modes.get_outdoor_box_controller(side=30.0)  # corners at +/-15 m, fence is +/-7.5 m
    prog = modes.mission_progress
    assert prog["dropped_outside_geofence"] == 5
    assert prog["total_waypoints"] == 1  # only the return-to-start point survives


def test_orbit_circles_and_returns_to_start(centred):
    authority, modes = centred
    ctl = modes.get_orbit_controller(radius=2.0)
    path = _fly(authority, ctl)
    assert modes.mission_progress["complete"] is True
    centre = (0.0, 2.0)
    radii = [math.hypot(x - centre[0], y - centre[1]) for x, y in path]
    assert min(radii) > 1.4 and max(radii) < 2.3
    assert max(y for _, y in path) > 3.5  # actually went round the far side
    assert math.hypot(authority.local_x, authority.local_y) < 0.35


def test_orbit_yaws_toward_centre(centred):
    authority, modes = centred
    authority.bridge.get_latest_telemetry().yaw = 180.0  # facing South, centre is North
    _, _, yaw, _ = modes.get_orbit_controller(radius=2.0)()
    assert abs(yaw) == pytest.approx(1.0)


def test_indoor_grid_serpentine_is_capped_and_finishes(centred):
    authority, modes = centred
    ctl = modes.get_indoor_grid_controller(width=4.0, depth=2.0, spacing=1.0)
    assert modes.mission_progress["total_waypoints"] == 6
    p, r, _, _ = ctl()
    assert math.hypot(p, r) <= authority.settings.indoor_max_speed + 1e-9
    _fly(authority, ctl)
    assert modes.mission_progress["complete"] is True
    assert ctl() == (0.0, 0.0, 0.0, 0.0)


def test_status_exposes_mission_progress(centred):
    _authority, modes = centred
    modes.get_outdoor_box_controller(side=4.0)
    assert modes.mission_progress["mode"] == "outdoor_box"
    assert modes.mission_progress["waypoint_index"] == 0
