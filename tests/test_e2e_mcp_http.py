"""End-to-end: a real dji-station server; an MCP client (like Hermes) and REST share ONE authority."""

import asyncio
import socket

import httpx
import uvicorn
from fastmcp import Client

from dji_ground import gateway, mcp_server


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_mcp_over_http_shares_authority_with_rest():
    if mcp_server._runtime_started:
        await mcp_server.stop_runtime()
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(gateway.app, host="127.0.0.1", port=port, log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.05)
        assert server.started, "gateway did not start"
        base = f"http://127.0.0.1:{port}"

        async with Client(f"{base}/mcp") as mcp:
            names = {t.name for t in await mcp.list_tools()}
            assert {"get_status", "arm_motion", "takeoff", "scan_target_object"} <= names

            status = (await mcp.call_tool("get_status", {})).data
            assert status["bridge_connected"] is True  # runtime started by the gateway lifespan

            # Earlier tests share the module-level authority; hand back to RC so takeoff is legal.
            await mcp.call_tool("release_to_rc", {})
            tok = (await mcp.call_tool("arm_motion", {"mode": "takeoff"})).data["token"]
            await mcp.call_tool("takeoff", {"token": tok})

            # The REST side sees the state change made over MCP: same authority.
            async with httpx.AsyncClient() as c:
                st = (await c.get(f"{base}/api/status")).json()
                assert st["state"] == "ARMED_HOVER"
                await c.post(f"{base}/api/emergency_stop")

            after = (await mcp.call_tool("get_status", {})).data
            assert after["state"] == "EMERGENCY_HOVER"
            assert after["sticks"] == {"pitch": 0.0, "roll": 0.0, "yaw": 0.0, "throttle": 0.0}
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=10)
    assert mcp_server._runtime_started is False  # gateway owned the runtime and stopped it
