"""Simulation mission: emulator + DJI Bridge App + DJI Assistant 2 simulator."""

import asyncio

from dji_ground import mcp_server


async def run_sim_mission() -> None:
    print("[SIM MISSION] Initializing flight authority against simulator...")
    mcp_server.init_subsystems()
    await mcp_server._bridge.connect()
    await mcp_server._video.start()
    await mcp_server._authority.start()

    # 1. Preflight
    print("[SIM MISSION] Running preflight check...")
    preflight = mcp_server.preflight_check()
    print(f"Preflight status: {preflight}")

    # 2. Status
    status = mcp_server.get_status()
    print(f"Authority Status: {status['state']}, Mode: {status['mode']}")

    # 3. Takeoff with arm token
    print("[SIM MISSION] Arming motion for takeoff...")
    token_data = mcp_server.arm_motion("takeoff")
    print(f"Token minted: {token_data['token'][:8]}...")

    takeoff_res = await mcp_server.takeoff(token_data["token"])
    print(f"Takeoff result: {takeoff_res}")

    # 4. Narrate mode
    print("[SIM MISSION] Engaging narrate mode...")
    await mcp_server.set_mode("narrate")
    desc = await mcp_server.describe_scene()
    print(f"Narrate scene caption: '{desc['caption']}'")

    # 5. Land
    print("[SIM MISSION] Landing aircraft...")
    await mcp_server.land()

    await mcp_server._authority.stop()
    await mcp_server._video.stop()
    await mcp_server._bridge.disconnect()
    print("[SIM MISSION] Mission completed successfully.")


if __name__ == "__main__":
    asyncio.run(run_sim_mission())
