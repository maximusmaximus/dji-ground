"""Regression: geofence must not treat velocity as position."""

from dji_ground.authority import Authority


def test_velocity_is_not_a_geofence_point(running_authority: Authority):
    """A fast in-bounds velocity must not be classified as outside the box."""
    # 15 m box. 25 m/s is a speed, not a coordinate.
    assert running_authority.is_point_inside_geofence(5.0, 5.0) is True
    assert running_authority.is_point_inside_geofence(25.0, 0.0) is False
    # Position starts at origin. One stick tick at 25 m/s is still inside.
    running_authority.local_x = 0.0
    running_authority.local_y = 0.0
    dt = 1.0 / float(running_authority.settings.stick_loop_freq_hz)
    running_authority.integrate_position(25.0, 0.0, dt)
    assert running_authority.is_point_inside_geofence(
        running_authority.local_x, running_authority.local_y
    ) is True


def test_outside_position_is_rejected(running_authority: Authority):
    running_authority.local_x = 25.0
    running_authority.local_y = 5.0
    assert running_authority.is_point_inside_geofence(
        running_authority.local_x, running_authority.local_y
    ) is False
