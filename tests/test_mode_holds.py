"""Tests for fail-closed stub flight mode holds."""

from dji_ground.mode_holds import indoor_grid_hold, orbit_hold, outdoor_box_hold


def test_orbit_hold_returns_zero_sticks():
    ctrl = orbit_hold(radius=5.0, speed_rad_s=0.3)
    sticks = ctrl()
    assert sticks == (0.0, 0.0, 0.0, 0.0)


def test_indoor_grid_hold_returns_zero_sticks():
    ctrl = indoor_grid_hold()
    sticks = ctrl()
    assert sticks == (0.0, 0.0, 0.0, 0.0)


def test_outdoor_box_hold_returns_zero_sticks():
    ctrl = outdoor_box_hold()
    sticks = ctrl()
    assert sticks == (0.0, 0.0, 0.0, 0.0)
