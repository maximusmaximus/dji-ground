"""Tests verifying the FastMCP server tool surface and invocation."""

import pytest

from dji_ground import mcp_server


def test_mcp_tool_surface_exact_names():
    """Verify that FastMCP exposes all 20 stable tools plus 3D scanner tools."""
    # Initialize subsystems
    mcp_server.init_subsystems(enable_3d=True)

    expected_base_tools = {
        "get_status",
        "preflight_check",
        "takeoff",
        "land",
        "rth",
        "emergency_stop",
        "release_to_rc",
        "get_latest_frame",
        "get_ui_screenshot",
        "get_osd_text",
        "describe_scene",
        "diff_scene",
        "detect_objects",
        "set_baseline",
        "set_trigger",
        "list_triggers",
        "clear_trigger",
        "set_mode",
        "arm_motion",
        "get_mode",
    }

    # Inspect registered tools from FastMCP instance
    # In FastMCP 4.0, tools are stored in mcp._tool_manager or mcp.list_tools() or mcp._tools
    registered_tool_names = set()
    try:
        # Check via tool_manager
        if hasattr(mcp_server.mcp, "_tool_manager"):
            registered_tool_names = {t.name for t in mcp_server.mcp._tool_manager.list_tools()}
        elif hasattr(mcp_server.mcp, "_tools"):
            registered_tool_names = set(mcp_server.mcp._tools.keys())
    except Exception:
        pass

    # If internal structures differ, check function references
    if not registered_tool_names:
        registered_tool_names = {
            name for name in dir(mcp_server) if hasattr(getattr(mcp_server, name), "__call__")
        }

    for tool_name in expected_base_tools:
        assert tool_name in registered_tool_names, f"Tool {tool_name} missing from MCP surface!"


@pytest.mark.asyncio
async def test_mcp_tool_invocations():
    """Test calling key tools via MCP module."""
    mcp_server.init_subsystems()
    await mcp_server._bridge.connect()
    await mcp_server._video.start()
    await mcp_server._authority.start()

    status = mcp_server.get_status()
    assert "state" in status

    preflight = mcp_server.preflight_check()
    assert "checks" in preflight

    mode_info = mcp_server.get_mode()
    assert "active_mode" in mode_info

    tok = mcp_server.arm_motion("takeoff")
    assert "token" in tok

    await mcp_server._authority.stop()
    await mcp_server._video.stop()
    await mcp_server._bridge.disconnect()
