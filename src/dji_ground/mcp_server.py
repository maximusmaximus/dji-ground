"""FastMCP flight authority server exposing the stable 20 tools plus 3D scanner tools."""

import argparse
import asyncio
import base64
import io
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from fastmcp import FastMCP
from PIL import Image

from .authority import Authority
from .bridge.fake import FakeBridge
from .bridge.opendji import OpenDJIBridge
from .config import FIXTURES_DIR, Settings, get_settings
from .db import SessionDB
from .modeling_3d import ReconstructionEngine3D
from .modes import ModeManager
from .safety_gates import PLACEHOLDER_AGE_MS, placeholder_frame, scan_without_confirm
from .scene import FakeDetector, FakeVLMClient, ScenePipeline, VeniceVLMClient, YoloDetector
from .screen import ScreenCapturer
from .triggers import TriggerEngine
from .video import VideoPipeline

logger = logging.getLogger("dji_ground")

SAMPLE_FRAME_PATH = str(FIXTURES_DIR / "sample_frame.jpg")
SAMPLE_VIDEO_PATH = str(FIXTURES_DIR / "sample_h264_stream.h264")

# Runtime ownership: only the context that actually started the runtime stops it.
_runtime_started: bool = False
_reconnect_task: asyncio.Task | None = None


@asynccontextmanager
async def _mcp_lifespan(_server: FastMCP):
    """Start bridge, video, and the safety loop on the MCP server's own event loop."""
    started_here = await start_runtime()
    try:
        yield {}
    finally:
        if started_here:
            await stop_runtime()


# Global server instance
mcp = FastMCP("dji-ground", lifespan=_mcp_lifespan)

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

    if enable_3d is not None:
        _settings.enable_3d_modeling = enable_3d

    if _authority is not None:
        return

    _settings = get_settings()

    # Bridge selection
    if _settings.bridge_mode == "opendji":
        _bridge = OpenDJIBridge(
            host=_settings.bridge_host,
            telemetry_port=_settings.telemetry_port,
            video_port=_settings.video_port,
            command_port=_settings.command_port,
        )
    else:
        _bridge = FakeBridge(fixture_video_path=SAMPLE_VIDEO_PATH)

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

    detector = YoloDetector() if _settings.enable_yolo else FakeDetector()
    _scene = ScenePipeline(detector=detector, vlm_client=vlm_client)
    _triggers = TriggerEngine(_db)
    _authority = Authority(_bridge, _settings)
    _modes = ModeManager(_authority, _scene, _triggers)
    _modeler = ReconstructionEngine3D(
        db=_db,
        export_dir=_settings.model_3d_export_dir,
        resolution=_settings.model_3d_resolution,
        max_points=_settings.model_3d_max_points,
    )


async def _reconnect_loop() -> None:
    """Keep retrying the bridge so the operator can plug the phone in after startup."""
    while True:
        await asyncio.sleep(_settings.bridge_reconnect_s)
        if _bridge.is_connected():
            continue
        try:
            if await _bridge.connect():
                logger.info("Bridge connected (%s mode).", _settings.bridge_mode)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Bridge reconnect failed: %s", exc)


async def start_runtime() -> bool:
    """Connect the bridge and start video + authority loops. Idempotent.

    Returns True only for the caller that actually started the runtime (the owner).
    """
    global _runtime_started, _reconnect_task
    init_subsystems()
    if _runtime_started:
        return False
    _runtime_started = True

    connected = await _bridge.connect()
    if not connected:
        logger.warning(
            "Bridge not reachable at %s:%s-%s (%s mode). Running DISCONNECTED and retrying "
            "every %.0fs. Check the phone app and `adb forward` ports.",
            _settings.bridge_host,
            _settings.telemetry_port,
            _settings.command_port,
            _settings.bridge_mode,
            _settings.bridge_reconnect_s,
        )
    await _video.start()
    await _authority.start()
    _reconnect_task = asyncio.create_task(_reconnect_loop())
    return True


async def stop_runtime() -> None:
    """Stop loops and disconnect the bridge (zeroes sticks via Authority.stop)."""
    global _runtime_started, _reconnect_task
    if not _runtime_started:
        return
    if _reconnect_task:
        _reconnect_task.cancel()
        try:
            await _reconnect_task
        except asyncio.CancelledError:
            pass
        _reconnect_task = None
    await _authority.stop()
    await _video.stop()
    await _bridge.disconnect()
    _runtime_started = False


def _modeling_disabled_response() -> dict[str, Any]:
    return {
        "status": "3d_modeling_disabled",
        "message": (
            "3D modeling is off. Restart with --enable-3d-modeling (MCP), "
            "`dji-station --enable-3d`, or set DJI_ENABLE_3D_MODELING=true."
        ),
    }


def _fallback_image() -> Image.Image:
    if os.path.exists(SAMPLE_FRAME_PATH):
        return Image.open(SAMPLE_FRAME_PATH)
    return Image.new("RGB", (640, 480), color=(180, 200, 220))


# ------------------------------------------------------------------------------
# Core 20 MCP Tools (Exact Names Guaranteed)
# ------------------------------------------------------------------------------


@mcp.tool()
def get_status() -> dict[str, Any]:
    """Retrieve full drone flight status, battery, telemetry, and authority state."""
    init_subsystems()
    status = _authority.get_status()
    status["bridge_mode"] = _settings.bridge_mode
    status["modeling_3d_enabled"] = _settings.enable_3d_modeling
    status["modeling_3d_active_session"] = _modeler.active_session_id if _modeler.is_active() else None
    status["vlm"] = "venice" if _settings.venice_configured else "offline_stub"
    status["mission_progress"] = _modes.mission_progress
    return status


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
        return placeholder_frame(b64)

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
        # No live video: caption a fallback image but report it as STALE so the
        # authority's stale-video gate is never fooled by a placeholder.
        img = _fallback_image()
        frame_id = 0
        age_ms = PLACEHOLDER_AGE_MS
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
    if not frame:
        desc["source"] = "placeholder"

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
    img = frame.image if frame else _fallback_image()
    return _scene.detector.detect(img, filter_labels=labels)


@mcp.tool()
async def set_baseline() -> dict[str, Any]:
    """Capture current camera frame and scene analysis as reference baseline for sentinel mode."""
    init_subsystems()
    curr_desc = await describe_scene()
    frame = await _video.get_latest_frame()
    img = frame.image if frame else _fallback_image()
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
    """Engage one of the seven flight modes (narrate, sentinel, follow, orbit, indoor_grid, outdoor_box, manual_sidecar).

    Optional params: orbit {radius}, indoor_grid {width, depth, spacing}, outdoor_box {side},
    follow {bbox}. Translating modes require a token from arm_motion(<mode>).
    """
    init_subsystems()
    mode_clean = mode.lower().strip()
    p = params or {}

    # Assign matching controller
    cb = None
    if mode_clean == "narrate":
        cb = _modes.get_narrate_controller()
    elif mode_clean == "sentinel":
        cb = _modes.get_sentinel_controller()
    elif mode_clean == "follow":
        if "bbox" in p:
            _modes.set_follow_target(p["bbox"])
        cb = _modes.get_follow_controller()
    elif mode_clean == "orbit":
        cb = _modes.get_orbit_controller(radius=float(p.get("radius", 3.0)))
    elif mode_clean == "indoor_grid":
        cb = _modes.get_indoor_grid_controller(
            width=float(p.get("width", 4.0)),
            depth=float(p.get("depth", 4.0)),
            spacing=float(p.get("spacing", 1.0)),
        )
    elif mode_clean == "outdoor_box":
        cb = _modes.get_outdoor_box_controller(side=float(p.get("side", 10.0)))
    elif mode_clean == "manual_sidecar":
        cb = _modes.get_manual_sidecar_controller()

    return await _authority.set_mode(
        mode_clean, token=token if token else None, params=params, controller_cb=cb
    )


@mcp.tool()
def get_mode() -> dict[str, Any]:
    """Return currently active flight mode, state, runtime parameters, and mission progress."""
    init_subsystems()
    return {
        "active_mode": _authority.active_mode.value,
        "state": _authority.state.value,
        "params": _authority.mode_params,
        "geofence_points": len(_authority.local_geofence),
        "mission_progress": _modes.mission_progress,
    }


# ------------------------------------------------------------------------------
# 3D Modeling Tools (Flag / Config Controlled)
# ------------------------------------------------------------------------------


@mcp.tool()
def start_3d_scan(target_label: str = "", resolution: str = "high") -> dict[str, Any]:
    """Start live 3D reconstruction session accumulating synchronized point clouds."""
    init_subsystems()
    if not _settings.enable_3d_modeling:
        return _modeling_disabled_response()
    session_id = _modeler.start_session(
        target_label=target_label if target_label else None,
        resolution=resolution,
    )
    return {"status": "3d_scan_started", "session_id": session_id, "resolution": resolution}


@mcp.tool()
def stop_3d_scan() -> dict[str, Any]:
    """Stop active 3D scanning session and export point cloud to PLY, OBJ, and GLTF files."""
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
async def scan_target_object(
    target_label: str, radius_m: float = 3.0, confirm_token: str | None = None
) -> dict[str, Any]:
    """Autonomous high-level task: Find object X in viewport, orbit POI, and generate 3D model.

    Safety: Without confirm_token from operator arm_motion('orbit'), this tool proposes
    the scan and matched bounding box but refuses to self-arm motion.
    """
    init_subsystems()
    if not _settings.enable_3d_modeling:
        return _modeling_disabled_response()

    # 1. Search viewport for target
    objs = await detect_objects(labels=[target_label])
    matched = None
    for o in objs:
        if o["label"].lower() == target_label.lower():
            matched = o
            break

    if not confirm_token:
        return scan_without_confirm(target_label, matched)

    if not matched:
        return {
            "status": "target_not_found",
            "searched_label": target_label,
            "action": "hover",
            "message": f"Target '{target_label}' was not visible in current camera viewport.",
        }

    # 2. Engage orbit first: if the token is rejected, no scan session is left dangling.
    await _authority.set_mode(
        "orbit",
        token=confirm_token,
        params={"target": target_label, "bbox": matched["bbox"], "radius": radius_m},
        controller_cb=_modes.get_orbit_controller(radius=radius_m),
    )

    # 3. Start 3D scan session
    session_id = _modeler.start_session(target_label=target_label, resolution="high")

    # 4. Capture initial frame
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
    """Entrypoint for running FastMCP server over stdio (HTTP is served by dji-station at /mcp)."""
    parser = argparse.ArgumentParser(description="dji-ground FastMCP server")
    parser.add_argument(
        "--enable-3d-modeling", action="store_true", help="Enable 3D modeling engine"
    )
    args, _ = parser.parse_known_args()

    # stdout is the MCP protocol channel: keep all logs on stderr.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    init_subsystems(enable_3d=args.enable_3d_modeling or _settings.enable_3d_modeling)

    # Bridge, video, and the safety loop start inside the FastMCP lifespan so they run
    # on the same event loop that serves tool calls.
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
