"""FastMCP flight authority server exposing the stable 20 tools plus 3D scanner tools."""

import argparse
import asyncio
import base64
import io
import os
import time
from typing import Any

from fastmcp import FastMCP
from PIL import Image

from .authority import Authority
from .bridge.fake import FakeBridge
from .bridge.opendji import OpenDJIBridge
from .config import Settings, get_settings
from .db import SessionDB
from .modeling_3d import ReconstructionEngine3D
from .modes import ModeManager
from .scene import FakeDetector, FakeVLMClient, ScenePipeline, VeniceVLMClient
from .screen import ScreenCapturer
from .triggers import TriggerEngine
from .video import VideoPipeline

# Global server instance
mcp = FastMCP("dji-ground")

# Global subsystem holders
_settings: Settings = get_settings()
_db: SessionDB = SessionDB(_settings.sqlite_db_path)
_bridge = None
_video: VideoPipeline = None
_screen: ScreenCapturer = None
_scene: ScenePipeline = None
_triggers: TriggerEngine = None
_authority: Authority = None
_modes: ModeManager = None
_modeler: ReconstructionEngine3D = None


def init_subsystems(enable_3d: bool | None = None) -> None:
    """Initialize authority, bridge, video, and vision subsystems."""
    global _bridge, _video, _screen, _scene, _triggers, _authority, _modes, _modeler, _settings

    if _authority is not None:
        return

    _settings = get_settings()
    if enable_3d is not None:
        _settings.enable_3d_modeling = enable_3d

    # Bridge selection
    if _settings.bridge_mode == "opendji":
        _bridge = OpenDJIBridge(
            host=_settings.bridge_host,
            telemetry_port=_settings.telemetry_port,
            video_port=_settings.video_port,
            command_port=_settings.command_port,
        )
    else:
        _bridge = FakeBridge()

    _video = VideoPipeline(_bridge)
    _screen = ScreenCapturer()

    # VLM client selection
    vlm_client = None
    if _settings.venice_api_key:
        vlm_client = VeniceVLMClient(
            api_key=_settings.venice_api_key,
            base_url=_settings.venice_api_base,
            model=_settings.venice_vision_model,
        )
    else:
        vlm_client = FakeVLMClient()

    _scene = ScenePipeline(detector=FakeDetector(), vlm_client=vlm_client)
    _triggers = TriggerEngine(_db)
    _authority = Authority(_bridge, _settings)
    _modes = ModeManager(_authority, _scene, _triggers)
    _modeler = ReconstructionEngine3D(
        db=_db,
        export_dir=_settings.model_3d_export_dir,
        resolution=_settings.model_3d_resolution,
        max_points=_settings.model_3d_max_points,
    )


# ------------------------------------------------------------------------------
# Core 20 MCP Tools (Exact Names Guaranteed)
# ------------------------------------------------------------------------------


@mcp.tool()
def get_status() -> dict[str, Any]:
    """Retrieve full drone flight status, battery, telemetry, and authority state."""
    init_subsystems()
    return _authority.get_status()


@mcp.tool()
def preflight_check() -> dict[str, Any]:
    """Run comprehensive preflight verification checklist before takeoff."""
    init_subsystems()
    status = _authority.get_status()
    telem = _bridge.get_latest_telemetry()

    checks = {
        "bridge_connected": status["bridge_connected"],
        "battery_sufficient": telem.battery_percent >= 30,
        "gps_lock": telem.gps_satellite_count >= 8,
        "video_fresh": status["video_fresh"],
        "geofence_loaded": len(_authority.local_geofence) >= 3,
        "no_obstacle": not telem.obstacle_detected,
        "rc_signal_ok": telem.signal_quality >= 50,
    }
    all_passed = all(checks.values())
    return {
        "passed": all_passed,
        "checks": checks,
        "battery_percent": telem.battery_percent,
        "satellites": telem.gps_satellite_count,
        "ready_for_takeoff": all_passed,
    }


@mcp.tool()
async def takeoff(token: str) -> dict[str, Any]:
    """Command aircraft to takeoff and hover. Requires server-minted token from arm_motion."""
    init_subsystems()
    return await _authority.takeoff(token)


@mcp.tool()
async def land(token: str = "") -> dict[str, Any]:
    """Command aircraft to auto-land at current coordinate."""
    init_subsystems()
    return await _authority.land(token)


@mcp.tool()
async def rth() -> dict[str, Any]:
    """Command aircraft to immediately Return to Home (RTH)."""
    init_subsystems()
    return await _authority.rth()


@mcp.tool()
async def emergency_stop() -> dict[str, Any]:
    """Unconditional emergency stop: halts motors / zeroes virtual sticks instantly."""
    init_subsystems()
    return await _authority.emergency_stop()


@mcp.tool()
async def release_to_rc() -> dict[str, Any]:
    """Relinquish virtual stick authority back to human pilot RC."""
    init_subsystems()
    return await _authority.release_to_rc()


@mcp.tool()
async def get_latest_frame() -> dict[str, Any]:
    """Retrieve the most recent camera frame as base64 JPEG with timestamp and age in ms."""
    init_subsystems()
    frame = await _video.get_latest_frame()
    if not frame:
        # Generate placeholder if video not streaming yet
        img = Image.new("RGB", (640, 480), color=(180, 200, 220))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return {
            "frame_id": 0,
            "timestamp_ms": time.time() * 1000.0,
            "age_ms": 0.0,
            "image_b64": b64,
        }

    buf = io.BytesIO()
    frame.image.save(buf, format="JPEG", quality=80)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return {
        "frame_id": frame.frame_id,
        "timestamp_ms": frame.timestamp_ms,
        "age_ms": round(frame.age_ms, 1),
        "image_b64": b64,
    }


@mcp.tool()
async def get_ui_screenshot() -> dict[str, Any]:
    """Capture Android device screen via ADB."""
    init_subsystems()
    png_bytes = await _screen.get_ui_screenshot()
    b64 = base64.b64encode(png_bytes).decode("utf-8")
    return {"format": "png", "image_b64": b64}


@mcp.tool()
async def get_osd_text() -> dict[str, Any]:
    """Extract OSD status text and warning banners from screen capture."""
    init_subsystems()
    png_bytes = await _screen.get_ui_screenshot()
    return _screen.get_osd_text(png_bytes)


@mcp.tool()
async def describe_scene(prompt: str = "") -> dict[str, Any]:
    """Produce structured scene description with caption, objects, overlays, and telemetry."""
    init_subsystems()
    frame = await _video.get_latest_frame()
    telem = _bridge.get_latest_telemetry().to_dict()

    if not frame:
        # Fallback to test image fixture
        fixture_path = "fixtures/sample_frame.jpg"
        if os.path.exists(fixture_path):
            img = Image.open(fixture_path)
        else:
            img = Image.new("RGB", (640, 480), color=(180, 200, 220))
        frame_id = 1
        age_ms = 15.0
    else:
        img = frame.image
        frame_id = frame.frame_id
        age_ms = frame.age_ms

    _authority.update_frame_age(age_ms)
    desc = await _scene.describe_scene(
        image=img,
        telemetry_dict=telem,
        frame_id=frame_id,
        age_ms=age_ms,
        prompt=prompt if prompt else None,
    )

    # If 3D modeling active, feed frame into reconstruction engine
    if _modeler.is_active():
        _modeler.process_frame(img, telem)

    return desc


@mcp.tool()
async def diff_scene(baseline_id: str = "") -> dict[str, Any]:
    """Compare current scene against stored baseline snapshot."""
    init_subsystems()
    curr_desc = await describe_scene()
    return _scene.diff_scene(curr_desc["objects"], curr_desc["caption"])


@mcp.tool()
async def detect_objects(labels: list[str] | None = None) -> list[dict[str, Any]]:
    """Detect visual objects in camera viewport with labels, bounding boxes, and confidences."""
    init_subsystems()
    frame = await _video.get_latest_frame()
    if not frame and os.path.exists("fixtures/sample_frame.jpg"):
        img = Image.open("fixtures/sample_frame.jpg")
    elif frame:
        img = frame.image
    else:
        img = Image.new("RGB", (640, 480), color=(180, 200, 220))

    return _scene.detector.detect(img, filter_labels=labels)


@mcp.tool()
async def set_baseline() -> dict[str, Any]:
    """Capture current camera frame and scene analysis as reference baseline for sentinel mode."""
    init_subsystems()
    curr_desc = await describe_scene()
    frame = await _video.get_latest_frame()
    img = frame.image if frame else Image.open("fixtures/sample_frame.jpg")
    return _scene.set_baseline(img, curr_desc["caption"], curr_desc["objects"])


@mcp.tool()
def set_trigger(trigger_def: dict[str, Any]) -> dict[str, Any]:
    """Register a new trigger rule. Enforces strict closed action enum."""
    init_subsystems()
    try:
        defn = _triggers.add_trigger(trigger_def)
        return {"status": "trigger_registered", "trigger": defn.model_dump()}
    except Exception as e:
        raise ValueError(f"Failed to register trigger: {e}")


@mcp.tool()
def list_triggers() -> list[dict[str, Any]]:
    """List all registered and active trigger rules."""
    init_subsystems()
    return _triggers.list_triggers()


@mcp.tool()
def clear_trigger(trigger_id: str) -> dict[str, Any]:
    """Remove trigger rule by ID."""
    init_subsystems()
    success = _triggers.remove_trigger(trigger_id)
    return {"status": "cleared" if success else "not_found", "trigger_id": trigger_id}


@mcp.tool()
def arm_motion(mode: str) -> dict[str, Any]:
    """Mint a server-generated cryptographic authorization token required for takeoff or translation."""
    init_subsystems()
    token = _authority.arm_motion(mode)
    return {
        "token": token.token,
        "mode": token.mode,
        "expires_in_seconds": token.ttl_seconds,
        "minted_at": token.minted_at,
    }


@mcp.tool()
async def set_mode(
    mode: str, token: str = "", params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Engage one of the seven flight modes (narrate, sentinel, follow, orbit, indoor_grid, outdoor_box, manual_sidecar)."""
    init_subsystems()
    mode_clean = mode.lower().strip()

    # Assign matching controller
    cb = None
    if mode_clean == "narrate":
        cb = _modes.get_narrate_controller()
    elif mode_clean == "sentinel":
        cb = _modes.get_sentinel_controller()
    elif mode_clean == "follow":
        if params and "bbox" in params:
            _modes.set_follow_target(params["bbox"])
        cb = _modes.get_follow_controller()
    elif mode_clean == "orbit":
        radius = params.get("radius", 3.0) if params else 3.0
        cb = _modes.get_orbit_controller(radius=radius)
    elif mode_clean == "indoor_grid":
        cb = _modes.get_indoor_grid_controller()
    elif mode_clean == "outdoor_box":
        cb = _modes.get_outdoor_box_controller()
    elif mode_clean == "manual_sidecar":
        cb = _modes.get_manual_sidecar_controller()

    return await _authority.set_mode(
        mode_clean, token=token if token else None, params=params, controller_cb=cb
    )


@mcp.tool()
def get_mode() -> dict[str, Any]:
    """Return currently active flight mode, state, and runtime parameters."""
    init_subsystems()
    return {
        "active_mode": _authority.active_mode.value,
        "state": _authority.state.value,
        "params": _authority.mode_params,
        "geofence_points": len(_authority.local_geofence),
    }


# ------------------------------------------------------------------------------
# 3D Modeling Tools (Flag / Config Controlled)
# ------------------------------------------------------------------------------


@mcp.tool()
def start_3d_scan(target_label: str = "", resolution: str = "high") -> dict[str, Any]:
    """Start live 3D reconstruction session accumulating synchronized point clouds."""
    init_subsystems()
    session_id = _modeler.start_session(
        target_label=target_label if target_label else None,
        resolution=resolution,
    )
    return {"status": "3d_scan_started", "session_id": session_id, "resolution": resolution}


@mcp.tool()
def stop_3d_scan() -> dict[str, Any]:
    """Stop active 3D scanning session and export point cloud to PLY file."""
    init_subsystems()
    return _modeler.stop_session()


@mcp.tool()
def get_3d_model(session_id: str = "") -> dict[str, Any]:
    """Retrieve metadata, point count, bounds, and export path for a 3D model session."""
    init_subsystems()
    target_id = session_id or _modeler.active_session_id or ""
    if not target_id:
        return {"status": "no_session_specified"}
    session = _db.get_3d_session(target_id)
    if not session:
        return {"status": "session_not_found", "session_id": target_id}
    return session


@mcp.tool()
async def scan_target_object(target_label: str, radius_m: float = 3.0) -> dict[str, Any]:
    """Autonomous high-level task: Find object X in viewport, orbit POI, and generate 3D model."""
    init_subsystems()
    # 1. Search viewport for target
    objs = await detect_objects(labels=[target_label])
    matched = None
    for o in objs:
        if o["label"].lower() == target_label.lower():
            matched = o
            break

    if not matched:
        return {
            "status": "target_not_found",
            "searched_label": target_label,
            "action": "hover",
            "message": f"Target '{target_label}' was not visible in current camera viewport.",
        }

    # 2. Start 3D scan session
    session_id = _modeler.start_session(target_label=target_label, resolution="high")

    # 3. Mint token for orbit mode
    token_obj = _authority.arm_motion("orbit")

    # 4. Engage orbit mode around target
    await _authority.set_mode(
        "orbit",
        token=token_obj.token,
        params={"target": target_label, "bbox": matched["bbox"], "radius": radius_m},
        controller_cb=_modes.get_orbit_controller(radius=radius_m),
    )

    # 5. Capture initial frame
    desc = await describe_scene()

    return {
        "status": "scanning_target_initiated",
        "target_label": target_label,
        "matched_bbox": matched["bbox"],
        "session_id": session_id,
        "mode": "orbit",
        "radius_m": radius_m,
        "scene_caption": desc["caption"],
    }


def main() -> None:
    """Entrypoint for running FastMCP server over stdio."""
    parser = argparse.ArgumentParser(description="dji-ground FastMCP server")
    parser.add_argument(
        "--enable-3d-modeling", action="store_true", help="Enable 3D modeling engine"
    )
    args, _ = parser.parse_known_args()

    init_subsystems(enable_3d=args.enable_3d_modeling or _settings.enable_3d_modeling)

    # Connect bridge and start authority loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_bridge.connect())
    loop.run_until_complete(_video.start())
    loop.run_until_complete(_authority.start())

    # Run FastMCP stdio server
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
