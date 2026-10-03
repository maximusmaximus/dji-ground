"""Runtime / gateway UX: link recovery, single-owner runtime, health, scan flow, stick WS safety."""

import asyncio
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from dji_ground import gateway, mcp_server
from dji_ground.authority import FlightMode, FlightState

# ------------------------------------------------------------------ authority link recovery


async def test_link_loss_zeroes_sticks_and_recovery_never_resumes_mode(running_authority):
    authority = running_authority
    bridge = authority.bridge
    tok = authority.arm_motion("takeoff")
    await authority.takeoff(tok.token)
    authority.update_frame_age(10)
    authority.refresh_heartbeat()
    mtok = authority.arm_motion("manual_sidecar")
    await authority.set_mode("manual_sidecar", token=mtok.token, controller_cb=lambda: (0.5, 0.5, 0, 0))

    bridge.inject_link_loss()
    await asyncio.sleep(0.15)
    assert authority.state == FlightState.DISCONNECTED
    assert (authority.pitch, authority.roll) == (0.0, 0.0)
    assert authority._mode_controller_cb is None

    bridge._link_dropped = False  # link comes back
    await asyncio.sleep(0.15)
    assert authority.state == FlightState.EMERGENCY_HOVER  # still flying: hover, never resume
    assert authority.active_mode == FlightMode.HOVER


async def test_recovery_on_ground_is_disarmed(running_authority):
    authority = running_authority
    authority.bridge.inject_link_loss()
    await asyncio.sleep(0.12)
    assert authority.state == FlightState.DISCONNECTED
    authority.bridge._link_dropped = False
    await asyncio.sleep(0.12)
    assert authority.state == FlightState.DISARMED


# ------------------------------------------------------------------ runtime ownership


async def test_start_runtime_is_idempotent_and_single_owner():
    if mcp_server._runtime_started:
        await mcp_server.stop_runtime()
    first = await mcp_server.start_runtime()
    second = await mcp_server.start_runtime()  # e.g. the FastMCP lifespan inside the gateway
    try:
        assert first is True
        assert second is False
        assert mcp_server._bridge.is_connected()
    finally:
        await mcp_server.stop_runtime()
    assert mcp_server._runtime_started is False


# ------------------------------------------------------------------ MCP tool behaviour


async def test_describe_scene_without_video_is_reported_stale(monkeypatch):
    mcp_server.init_subsystems()

    async def no_frame():
        return None

    monkeypatch.setattr(mcp_server._video, "get_latest_frame", no_frame)
    desc = await mcp_server.describe_scene()
    assert desc.get("source") == "placeholder"
    # The stale-video gate must see the placeholder as stale (> 1000 ms), never as live.
    assert mcp_server._authority.latest_frame_age_ms > 1000
    frame = await mcp_server.get_latest_frame()
    assert frame["source"] == "placeholder" and frame["age_ms"] > 1000


async def test_3d_tools_report_disabled_flag_clearly():
    mcp_server.init_subsystems(enable_3d=False)
    try:
        assert mcp_server.start_3d_scan("chair")["status"] == "3d_modeling_disabled"
        res = await mcp_server.scan_target_object("chair")
        assert res["status"] == "3d_modeling_disabled"
        assert "--enable-3d" in res["message"]
        assert mcp_server.get_status()["modeling_3d_enabled"] is False
    finally:
        mcp_server.init_subsystems(enable_3d=False)


def test_mcp_tool_surface_is_complete():
    async def names():
        return {t.name for t in await mcp_server.mcp.list_tools()}

    tools = asyncio.run(names())
    for required in (
        "get_status", "arm_motion", "takeoff", "set_mode", "emergency_stop", "release_to_rc",
        "describe_scene", "scan_target_object", "start_3d_scan", "stop_3d_scan",
    ):
        assert required in tools


# ------------------------------------------------------------------ gateway endpoints


@pytest.fixture
def asgi_client():
    mcp_server.init_subsystems()
    transport = httpx.ASGITransport(app=gateway.app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_health_endpoint(asgi_client):
    async with asgi_client as c:
        r = await c.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["bridge_mode"] == "fake"
    assert "state" in body


async def test_scan_target_endpoint_only_proposes_without_token(asgi_client):
    mcp_server.init_subsystems(enable_3d=True)
    try:
        async with asgi_client as c:
            r = await c.post("/api/scan_target", json={"target_label": "red_cone"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] in ("requires_arm", "target_not_found")
        assert "token" not in body and "confirm_token" not in body
    finally:
        mcp_server.init_subsystems(enable_3d=False)


async def test_scan_target_with_forged_token_is_403(asgi_client):
    mcp_server.init_subsystems(enable_3d=True)
    if mcp_server._modeler.is_active():
        mcp_server._modeler.stop_session()
    try:
        async with asgi_client as c:
            r = await c.post(
                "/api/scan_target",
                json={"target_label": "red_cone", "confirm_token": "forged-token"},
            )
        # Forged token: 403 if the target is visible, otherwise a harmless not-found hover.
        assert r.status_code in (403, 200)
        if r.status_code == 200:
            assert r.json()["status"] == "target_not_found"
        assert mcp_server._modeler.is_active() is False  # no orphaned scan session
    finally:
        mcp_server.init_subsystems(enable_3d=False)


def _wait_until(pred, timeout_s=1.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def test_manual_stick_ws_malformed_packets_zero_sticks_and_disconnect_centres():
    mcp_server.init_subsystems()
    modes = mcp_server._modes
    with TestClient(gateway.app) as client:
        with client.websocket_connect("/ws/manual_stick") as ws:
            ws.send_text(json.dumps({"pitch": 0.4, "roll": 0.2, "yaw": 0, "throttle": 0}))
            assert _wait_until(lambda: modes._sidecar_sticks[0] == 0.4)
            ws.send_text("{not json")
            assert _wait_until(lambda: modes._sidecar_sticks == (0.0, 0.0, 0.0, 0.0))
            ws.send_text(json.dumps({"pitch": 0.7, "roll": 0, "yaw": 0, "throttle": 0}))
            assert _wait_until(lambda: modes._sidecar_sticks[0] == 0.7)
            ws.send_text(json.dumps({"pitch": "abc"}))
            assert _wait_until(lambda: modes._sidecar_sticks == (0.0, 0.0, 0.0, 0.0))
            ws.send_text(json.dumps({"pitch": 0.3, "roll": 0, "yaw": 0, "throttle": 0}))
            assert _wait_until(lambda: modes._sidecar_sticks[0] == 0.3)
        # Socket closed: sticks must be centred.
        assert _wait_until(lambda: modes._sidecar_sticks == (0.0, 0.0, 0.0, 0.0))
