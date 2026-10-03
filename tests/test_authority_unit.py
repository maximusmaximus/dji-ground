"""Unit tests for flight authority token gates, watchdog, and frame freshness."""

import asyncio
import time

import pytest

from dji_ground.authority import Authority, FlightState


@pytest.mark.asyncio
async def test_invented_token_rejected(running_authority: Authority):
    """Test that a forged/invented token is rejected for takeoff."""
    with pytest.raises(PermissionError, match="invalid, expired, or invented token"):
        await running_authority.takeoff("invented_token_12345")


@pytest.mark.asyncio
async def test_expired_token_rejected(running_authority: Authority):
    """Test that an expired token past TTL is rejected."""
    token = running_authority.arm_motion("takeoff")
    # Artificially expire the token
    token.minted_at = time.time() - 100.0

    with pytest.raises(PermissionError, match="invalid, expired, or invented token"):
        await running_authority.takeoff(token.token)


@pytest.mark.asyncio
async def test_each_translating_mode_refuses_without_arm_motion(running_authority: Authority):
    """Test that every translating mode refuses activation without arm_motion token."""
    # First takeoff with valid token
    tok = running_authority.arm_motion("takeoff")
    await running_authority.takeoff(tok.token)

    translating_modes = ["follow", "orbit", "indoor_grid", "outdoor_box", "manual_sidecar"]
    for mode_name in translating_modes:
        with pytest.raises(PermissionError, match="requires a valid server-minted token"):
            await running_authority.set_mode(mode_name, token=None)

        with pytest.raises(PermissionError, match="requires a valid server-minted token"):
            await running_authority.set_mode(mode_name, token="fake_forged_token")


@pytest.mark.asyncio
async def test_watchdog_zeros_sticks_after_500ms(running_authority: Authority):
    """Test that cessation of heartbeat causes watchdog to zero sticks after 500ms."""
    tok = running_authority.arm_motion("takeoff")
    await running_authority.takeoff(tok.token)

    # Arm follow mode with controller generating forward stick
    m_tok = running_authority.arm_motion("follow")
    await running_authority.set_mode(
        "follow", token=m_tok.token, controller_cb=lambda: (0.4, 0.0, 0.0, 0.0)
    )

    assert running_authority.state == FlightState.ARMED_ACTIVE
    await asyncio.sleep(0.1)
    # Stalling heartbeat
    running_authority.last_heartbeat = time.time() - 0.600

    # Wait for watchdog check in stick loop
    await asyncio.sleep(0.15)
    assert running_authority.pitch == 0.0
    assert running_authority.roll == 0.0
    assert running_authority.state == FlightState.EMERGENCY_HOVER


@pytest.mark.asyncio
async def test_stale_frame_forces_hover(running_authority: Authority):
    """Test that frame older than 1s forces hover and zeroes translational sticks."""
    tok = running_authority.arm_motion("takeoff")
    await running_authority.takeoff(tok.token)

    m_tok = running_authority.arm_motion("orbit")
    await running_authority.set_mode(
        "orbit", token=m_tok.token, controller_cb=lambda: (0.0, 0.4, 0.3, 0.0)
    )

    assert running_authority.state == FlightState.ARMED_ACTIVE
    await asyncio.sleep(0.1)

    # Frame age exceeds 1000ms
    running_authority.update_frame_age(1200.0)
    await asyncio.sleep(0.15)

    assert running_authority.state == FlightState.EMERGENCY_HOVER
    assert running_authority.pitch == 0.0
    assert running_authority.roll == 0.0
