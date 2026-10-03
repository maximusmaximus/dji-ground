"""Tests for velocity clamping and geofence boundary checks."""

from dji_ground.authority import Authority


def test_velocity_clamping_indoor(running_authority: Authority):
    """Test that indoor speeds above 1.0 m/s are clamped to 1.0 m/s."""
    # Attempt 2.0 m/s forward and 2.0 m/s lateral
    vx, vy, vz = running_authority.clamp_velocity(2.0, 2.0, 0.0, is_outdoor=False)
    speed = (vx**2 + vy**2) ** 0.5
    assert speed <= 1.01
    assert round(speed, 2) == 1.0


def test_velocity_clamping_outdoor(running_authority: Authority):
    """Test that outdoor speeds above 3.0 m/s are clamped to 3.0 m/s."""
    vx, vy, vz = running_authority.clamp_velocity(4.0, 4.0, 0.0, is_outdoor=True)
    speed = (vx**2 + vy**2) ** 0.5
    assert speed <= 3.01
    assert round(speed, 2) == 3.0


def test_geofence_rejects_outside_point(running_authority: Authority):
    """Test that point outside geofence polygon is correctly identified as outside."""
    # Local polygon in fixtures is [0, 0] to [15, 15]
    assert running_authority.is_point_inside_geofence(5.0, 5.0) is True
    assert running_authority.is_point_inside_geofence(25.0, 5.0) is False
    assert running_authority.is_point_inside_geofence(-2.0, 5.0) is False
