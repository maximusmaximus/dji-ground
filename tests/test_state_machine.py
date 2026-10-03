"""Tests verifying all state machine transitions and invalid edge rejections."""

import pytest

from dji_ground.authority import Authority, FlightMode, FlightState


@pytest.mark.asyncio
async def test_normal_flight_cycle(running_authority: Authority):
    """Test full cycle: DISARMED -> ARMED_HOVER -> ARMED_ACTIVE -> ARMED_HOVER -> DISARMED."""
    assert running_authority.state == FlightState.DISARMED

    # Takeoff
    tok = running_authority.arm_motion("takeoff")
    await running_authority.takeoff(tok.token)
    assert running_authority.state == FlightState.ARMED_HOVER

    # Set mode narrate (no motion token required)
    await running_authority.set_mode("narrate")
    assert running_authority.state == FlightState.ARMED_ACTIVE
    assert running_authority.active_mode == FlightMode.NARRATE

    # Return to hover
    await running_authority.set_mode("hover")
    assert running_authority.state == FlightState.ARMED_HOVER
    assert running_authority.active_mode == FlightMode.HOVER

    # Land
    await running_authority.land()
    assert running_authority.state == FlightState.DISARMED
    assert running_authority.active_mode == FlightMode.DISARMED


@pytest.mark.asyncio
async def test_emergency_stop_always_succeeds(running_authority: Authority):
    """Test emergency stop from any active mode."""
    tok = running_authority.arm_motion("takeoff")
    await running_authority.takeoff(tok.token)

    tok2 = running_authority.arm_motion("orbit")
    await running_authority.set_mode(
        "orbit", token=tok2.token, controller_cb=lambda: (0.2, 0.2, 0.2, 0.0)
    )
    assert running_authority.state == FlightState.ARMED_ACTIVE

    # Emergency stop
    await running_authority.emergency_stop()
    assert running_authority.state == FlightState.EMERGENCY_HOVER
    assert running_authority.pitch == 0.0
    assert running_authority.roll == 0.0


@pytest.mark.asyncio
async def test_release_to_rc_always_succeeds(running_authority: Authority):
    """Test release to RC relinquishes control."""
    tok = running_authority.arm_motion("takeoff")
    await running_authority.takeoff(tok.token)

    await running_authority.release_to_rc()
    assert running_authority.state == FlightState.RELEASED_TO_RC
    assert running_authority.active_mode == FlightMode.DISARMED


@pytest.mark.asyncio
async def test_rth_transition(running_authority: Authority):
    """Test RTH transition to EMERGENCY_RTH."""
    tok = running_authority.arm_motion("takeoff")
    await running_authority.takeoff(tok.token)

    await running_authority.rth()
    assert running_authority.state == FlightState.EMERGENCY_RTH


@pytest.mark.asyncio
async def test_invalid_mode_transition_rejected(running_authority: Authority):
    """Test that engaging a translating mode from DISARMED state is rejected."""
    assert running_authority.state == FlightState.DISARMED
    tok = running_authority.arm_motion("indoor_grid")

    with pytest.raises(
        RuntimeError, match="Cannot engage mode indoor_grid while in state DISARMED"
    ):
        await running_authority.set_mode("indoor_grid", token=tok.token)
