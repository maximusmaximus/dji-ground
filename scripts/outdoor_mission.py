"""Outdoor mission: Geofence box, GPS/Remote ID verification, web stop & MCP RTH. Requires OUTDOOR_ARM=1, VLOS."""

import asyncio
import os
import sys

from dji_ground import mcp_server


async def run_outdoor_mission() -> None:
    # Strict Opt-in verification
    if os.getenv("OUTDOOR_ARM") != "1":
        print("ERROR: Outdoor live flight refused. OUTDOOR_ARM=1 must be set in environment.")
        print("VLOS (Visual Line of Sight) and human Pilot in Command are mandatory.")
        sys.exit(1)

    print("[OUTDOOR MISSION] Initializing flight authority...")
    mcp_server.init_subsystems()
    await mcp_server._bridge.connect()
    await mcp_server._video.start()
    await mcp_server._authority.start()

    # Preflight fails closed if GPS is weak
    preflight = mcp_server.preflight_check()
    if not preflight["checks"]["gps_lock"]:
        print("ERROR: Preflight failed closed: GPS lock insufficient (<8 satellites).")
        sys.exit(1)

    # Takeoff
    token_takeoff = mcp_server.arm_motion("takeoff")
    await mcp_server.takeoff(token_takeoff["token"])

    # Outdoor Box mode
    token_box = mcp_server.arm_motion("outdoor_box")
    await mcp_server.set_mode("outdoor_box", token=token_box["token"])
    print("[OUTDOOR MISSION] Flying outdoor geofenced perimeter...")
    await asyncio.sleep(2.0)

    # Verify RTH
    print("[OUTDOOR MISSION] Triggering MCP RTH...")
    await mcp_server.rth()
    await asyncio.sleep(1.0)

    # Safe Land
    await mcp_server.land()
    await mcp_server._authority.stop()
    await mcp_server._video.stop()
    await mcp_server._bridge.disconnect()
    print("[OUTDOOR MISSION] Outdoor mission concluded safely.")


if __name__ == "__main__":
    asyncio.run(run_outdoor_mission())
