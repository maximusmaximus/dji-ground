"""FastAPI Gateway & WebSocket server. Shares the exact same flight authority as FastMCP."""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import mcp_server


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize shared subsystems
    mcp_server.init_subsystems()
    await mcp_server._bridge.connect()
    await mcp_server._video.start()
    await mcp_server._authority.start()
    yield
    await mcp_server._authority.stop()
    await mcp_server._video.stop()
    await mcp_server._bridge.disconnect()


app = FastAPI(title="dji-ground Gateway", lifespan=lifespan)

# Allow CORS for local Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request schemas
class ArmRequest(BaseModel):
    mode: str


class TakeoffRequest(BaseModel):
    token: str


class SetModeRequest(BaseModel):
    mode: str
    token: str | None = None
    params: dict[str, Any] | None = None


class TriggerRequest(BaseModel):
    trigger_id: str
    name: str
    action: str
    condition_type: str
    condition_value: str


class ScanRequest(BaseModel):
    target_label: str | None = None
    resolution: str = "high"


# ------------------------------------------------------------------------------
# REST Endpoints matching Authority & MCP tools
# ------------------------------------------------------------------------------


@app.get("/video/mjpeg")
async def video_mjpeg():
    """Live MJPEG video streaming endpoint."""
    return StreamingResponse(
        mcp_server._video.generate_mjpeg_stream(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/api/status")
def api_get_status():
    return mcp_server.get_status()


@app.get("/api/preflight")
def api_preflight():
    return mcp_server.preflight_check()


@app.post("/api/arm_motion")
def api_arm_motion(req: ArmRequest):
    return mcp_server.arm_motion(req.mode)


@app.post("/api/takeoff")
async def api_takeoff(req: TakeoffRequest):
    try:
        return await mcp_server.takeoff(req.token)
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/land")
async def api_land():
    return await mcp_server.land()


@app.post("/api/rth")
async def api_rth():
    return await mcp_server.rth()


@app.post("/api/emergency_stop")
async def api_emergency_stop():
    return await mcp_server.emergency_stop()


@app.post("/api/release_to_rc")
async def api_release_to_rc():
    return await mcp_server.release_to_rc()


@app.post("/api/set_mode")
async def api_set_mode(req: SetModeRequest):
    try:
        return await mcp_server.set_mode(req.mode, token=req.token or "", params=req.params)
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/get_mode")
def api_get_mode():
    return mcp_server.get_mode()


@app.get("/api/describe_scene")
async def api_describe_scene():
    return await mcp_server.describe_scene()


@app.get("/api/get_latest_frame")
async def api_get_latest_frame():
    return await mcp_server.get_latest_frame()


@app.get("/api/triggers")
def api_list_triggers():
    return mcp_server.list_triggers()


@app.post("/api/triggers")
def api_set_trigger(req: TriggerRequest):
    try:
        return mcp_server.set_trigger(req.model_dump())
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/triggers/{trigger_id}")
def api_clear_trigger(trigger_id: str):
    return mcp_server.clear_trigger(trigger_id)


# ------------------------------------------------------------------------------
# 3D Reconstruction Endpoints
# ------------------------------------------------------------------------------


@app.post("/api/3d_scan/start")
def api_start_3d_scan(req: ScanRequest):
    return mcp_server.start_3d_scan(
        target_label=req.target_label or "",
        resolution=req.resolution,
    )


@app.post("/api/3d_scan/stop")
def api_stop_3d_scan():
    return mcp_server.stop_3d_scan()


@app.get("/api/3d_model/{session_id}")
def api_get_3d_model(session_id: str):
    return mcp_server.get_3d_model(session_id)


@app.get("/api/3d_model/{session_id}/download/{file_format}")
def api_download_3d_model(session_id: str, file_format: str):
    """Download 3D model file in PLY, OBJ, or GLTF format."""
    clean_fmt = file_format.lower().strip().replace(".", "")
    if clean_fmt not in ("ply", "obj", "gltf"):
        raise HTTPException(status_code=400, detail="Supported formats are: ply, obj, gltf")

    export_dir = mcp_server._settings.model_3d_export_dir
    target_file = os.path.join(export_dir, f"{session_id}.{clean_fmt}")

    if not os.path.exists(target_file):
        raise HTTPException(status_code=404, detail=f"Model file {session_id}.{clean_fmt} not found")

    media_types = {
        "ply": "application/octet-stream",
        "obj": "text/plain",
        "gltf": "model/gltf+json",
    }
    return FileResponse(
        target_file,
        media_type=media_types.get(clean_fmt, "application/octet-stream"),
        filename=f"{session_id}.{clean_fmt}",
    )


@app.get("/api/3d_timeline/{session_id}")
def api_get_3d_timeline(session_id: str, time_ms: float):
    """Scrub 3D points and camera pose at specific timestamp."""
    return mcp_server._modeler.get_timeline_scrub(session_id, time_ms)


# ------------------------------------------------------------------------------
# WebSockets: Telemetry Streaming (15 Hz) & Sidecar Manual Sticks
# ------------------------------------------------------------------------------


@app.websocket("/ws/telemetry")
async def ws_telemetry(websocket: WebSocket):
    """Streams real-time aircraft telemetry packets to browser client."""
    await websocket.accept()
    try:
        while True:
            telem = mcp_server._bridge.get_latest_telemetry().to_dict()
            status = mcp_server._authority.get_status()
            payload = {"telemetry": telem, "status": status}
            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(0.066)  # ~15 Hz
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/manual_stick")
async def ws_manual_stick(websocket: WebSocket):
    """Receives gamepad stick commands from web operator for manual_sidecar mode."""
    await websocket.accept()
    try:
        while True:
            text = await websocket.receive_text()
            data = json.loads(text)
            p = float(data.get("pitch", 0.0))
            r = float(data.get("roll", 0.0))
            y = float(data.get("yaw", 0.0))
            th = float(data.get("throttle", 0.0))
            mcp_server._modes.update_sidecar_sticks(p, r, y, th)
            mcp_server._authority.refresh_heartbeat()
    except WebSocketDisconnect:
        mcp_server._modes.update_sidecar_sticks(0.0, 0.0, 0.0, 0.0)


# ------------------------------------------------------------------------------
# Serve Web Frontend (if built)
# ------------------------------------------------------------------------------
web_dist_dir = os.path.join(os.path.dirname(__file__), "..", "..", "web", "dist")
if os.path.exists(web_dist_dir):
    app.mount("/", StaticFiles(directory=web_dist_dir, html=True), name="static")


def main() -> None:
    """Run FastAPI gateway via uvicorn."""
    import uvicorn

    uvicorn.run("dji_ground.gateway:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
