"""Unified local launcher: starts bridge, video pipeline, authority, and web gateway."""

import argparse
import os
import webbrowser

import uvicorn

from dji_ground.config import get_settings


def run_station() -> None:
    parser = argparse.ArgumentParser(description="DJI Ground Station Unified Launcher")
    parser.add_argument("--port", type=int, default=8000, help="Web gateway port (default: 8000)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Web gateway host (default: 0.0.0.0)")
    parser.add_argument("--enable-3d", action="store_true", help="Enable 3D point cloud reconstruction")
    parser.add_argument("--opendji", action="store_true", help="Connect to physical OpenDJI bridge")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open browser")

    args = parser.parse_args()
    settings = get_settings()

    if args.enable_3d:
        settings.enable_3d_modeling = True
        os.environ["DJI_ENABLE_3D_MODELING"] = "true"

    if args.opendji:
        settings.bridge_mode = "opendji"
        os.environ["DJI_BRIDGE_MODE"] = "opendji"

    url = f"http://localhost:{args.port}"
    print("=" * 70)
    print(" DJI GROUND STATION - Flight Authority, 3D Scanner & Hermes Gateway")
    print("=" * 70)
    print(f" • Web UI & REST API:   {url}")
    print(f" • Video MJPEG Stream:  {url}/video/mjpeg")
    print(f" • Telemetry WebSocket: ws://localhost:{args.port}/ws/telemetry")
    print(f" • Bridge Mode:         {settings.bridge_mode.upper()}")
    print(f" • 3D Modeling:         {'ENABLED' if settings.enable_3d_modeling else 'DISABLED'}")
    print(f" • Watchdog:            {settings.watchdog_timeout_ms} ms")
    print(f" • Safety Caps:         Indoor {settings.indoor_max_speed} m/s, Outdoor {settings.outdoor_max_speed} m/s")
    print("=" * 70)

    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    uvicorn.run("dji_ground.gateway:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    run_station()
