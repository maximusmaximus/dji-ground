"""Indoor mission: Grid within room polygon, marker follow, obstacle abort. Requires INDOOR_ARM=1 and human on RC."""

import asyncio
import os
import sys

from dji_ground import mcp_server


async def run_indoor_mission() -> None:
    # Strict Opt-in verification
    if os.getenv("INDOOR_ARM") != "1":
        print("ERROR: Indoor live flight refused. INDOOR_ARM=1 must be set in environment.")
        print("A human operator MUST be holding the physical RC with hands on sticks.")
        sys.exit(1)

    print("[INDOOR MISSION] Initializing flight authority...")
    mcp_server.init_subsystems()
    await mcp_server._bridge.connect()
    await mcp_server._video.start()
    await mcp_server._authority.start()

    # 1. Preflight
    preflight = mcp_server.preflight_check()
    if not preflight["passed"]:
        print(f"Preflight failed: {preflight['checks']}")
        sys.exit(1)

    # 2. Arm Takeoff
    token_takeoff = mcp_server.arm_motion("takeoff")
    await mcp_server.takeoff(token_takeoff["token"])

    # 3. Indoor Grid Mode
    token_grid = mcp_server.arm_motion("indoor_grid")
    await mcp_server.set_mode("indoor_grid", token=token_grid["token"])
    print("[INDOOR MISSION] Running indoor grid...")
    await asyncio.sleep(2.0)

    # 4. Marker follow
    objs = await mcp_server.detect_objects(labels=["red_cone", "landing_pad"])
    if objs:
        token_follow = mcp_server.arm_motion("follow")
        await mcp_server.set_mode("follow", token=token_follow["token"], params={"bbox": objs[0]["bbox"]})
        print(f"[INDOOR MISSION] Tracking target: {objs[0]['label']}")
        await asyncio.sleep(2.0)

    # 5. Obstacle abort simulation
    print("[INDOOR MISSION] Simulating obstacle alert...")
    mcp_server._bridge.inject_obstacle(True)
    await asyncio.sleep(0.5)

    status = mcp_server.get_status()
    print(f"Post-obstacle status: State={status['state']} (Expect EMERGENCY_HOVER)")

    # 6. Safe Land
    await mcp_server.land()
    await mcp_server._authority.stop()
    await mcp_server._video.stop()
    await mcp_server._bridge.disconnect()
    print("[INDOOR MISSION] Indoor mission finished.")


if __name__ == "__main__":
    asyncio.run(run_indoor_mission())
