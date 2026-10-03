import pytest

from dji_ground import mcp_server
from dji_ground.safety_gates import PLACEHOLDER_AGE_MS, placeholder_frame, scan_without_confirm


def test_placeholder_is_stale():
    frame = placeholder_frame("abc")
    assert frame["age_ms"] == PLACEHOLDER_AGE_MS
    assert frame["age_ms"] > 1000
    assert frame["source"] == "placeholder"


def test_scan_does_not_self_arm():
    result = scan_without_confirm("cone", {"bbox": [0.1, 0.1, 0.2, 0.2]})
    assert result["status"] == "requires_arm"
    assert "token" not in result


@pytest.mark.asyncio
async def test_mcp_scan_target_object_requires_confirm_token():
    mcp_server.init_subsystems(enable_3d=True)
    await mcp_server._bridge.connect()
    await mcp_server._video.start()
    await mcp_server._authority.start()

    # Call scan without token
    res = await mcp_server.scan_target_object("red_cone")
    assert res["status"] == "requires_arm"
    assert "token" not in res
    assert "Pass confirm_token from operator arm_motion('orbit')" in res["message"]

    # Now mint arm token and call with token
    tok = mcp_server.arm_motion("orbit")
    # Takeoff first to be in armable state
    t_tok = mcp_server.arm_motion("takeoff")
    await mcp_server.takeoff(t_tok["token"])

    res2 = await mcp_server.scan_target_object("red_cone", confirm_token=tok["token"])
    assert res2["status"] == "scanning_target_initiated"
    assert res2["mode"] == "orbit"

    await mcp_server._authority.stop()
    await mcp_server._video.stop()
    await mcp_server._bridge.disconnect()

