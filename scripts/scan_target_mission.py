"""Autonomous 3D scan mission: Find item X, orbit POI, accumulate point cloud, export model."""

import asyncio
import os
import sys

from dji_ground import mcp_server


async def run_scan_mission(target_label: str = "red_cone") -> None:
    print(f"[3D SCAN MISSION] Starting mission to find and 3D model '{target_label}'...")
    mcp_server.init_subsystems(enable_3d=True)
    await mcp_server._bridge.connect()
    await mcp_server._video.start()
    await mcp_server._authority.start()

    # Preflight
    preflight = mcp_server.preflight_check()
    if not preflight["passed"]:
        print(f"Preflight failed: {preflight['checks']}")
        return

    # Takeoff
    tok = mcp_server.arm_motion("takeoff")
    await mcp_server.takeoff(tok["token"])

    # High-level tool: scan_target_object
    print(f"[3D SCAN MISSION] Calling scan_target_object('{target_label}')...")
    res = await mcp_server.scan_target_object(target_label, radius_m=3.0)
    print(f"Scan initiation result: {res}")

    # Orbit and accumulate for 3 seconds
    print("[3D SCAN MISSION] Orbiting target and accumulating 3D point cloud...")
    for _ in range(3):
        await asyncio.sleep(1.0)
        desc = await mcp_server.describe_scene()
        print(f"Scene update: {desc['caption']}")

    # Stop scan and export
    print("[3D SCAN MISSION] Finalizing 3D model...")
    export_res = mcp_server.stop_3d_scan()
    print(f"Export summary: {export_res}")

    # Return to Land
    await mcp_server.land()
    await mcp_server._authority.stop()
    await mcp_server._video.stop()
    await mcp_server._bridge.disconnect()
    print("[3D SCAN MISSION] Mission completed.")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "red_cone"
    asyncio.run(run_scan_mission(target))
