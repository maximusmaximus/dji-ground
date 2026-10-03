# dji-ground

A single-process local ground station for DJI aircraft with Hermes FastMCP flight authority, live 3D reconstruction, and an operator Web UI.

> [!IMPORTANT]
> **Human Pilot in Command**: The human operator holding the physical DJI Remote Controller (RC) is ALWAYS the Pilot in Command (PIC). There is **no beyond-visual-line-of-sight (BVLOS)** capability. Autonomous actions are constrained by non-negotiable safety gates, physical geofences, and server-minted motion tokens.

---

## 1. Architecture & Safety Invariants

```
                      +------------------------------------------------+
                      |         Telegram Bot (Operator on Mobile)      |
                      +------------------------------------------------+
                                              |
                                              v
                      +------------------------------------------------+
                      |          Hermes Agent + Venice AI API          |
                      +------------------------------------------------+
                                              | (stdio FastMCP)
                                              v
+------------------+  (WebSocket / HTTP) +--------------------+
|  Vite/React UI   | <-----------------> |   FastAPI Gateway  |
| (3D Scrubber HUD)|                     +--------------------+
+------------------+                              | (direct function call)
                                                  v
                                      +-----------------------+
                                      |   Flight Authority    |
                                      |    (Single Source     |
                                      |      of Truth)        |
                                      +-----------------------+
                                                  |
           +--------------------+-----------------+--------------------+
           |                    |                 |                    |
           v                    v                 v                    v
  +-----------------+  +-----------------+  +------------+  +------------------+
  |  Watchdog Loop  |  |  Safety Gates   |  |   Modes    |  |  OpenDJI Bridge  |
  |   (10-20 Hz)    |  | Geofence / Cap  |  | Controller |  |  (Live or Fake)  |
  +-----------------+  +-----------------+  +------------+  +------------------+
                                                  |                  |
                                                  v                  |
                                         +------------------+        |
                                         | 3D Model Builder |        |
                                         | & Timeline Store |        |
                                         +------------------+        |
                                                                     |
                                             +-----------------------+-----------------------+
                                             | (Telemetry Socket)    | (Video H.264 Socket)  | (Command/Stick Socket)
                                             v                       v                       v
                                        DJI Aircraft           PyAV Decoder           Virtual Sticks
```

### Safety Rules
1. **Untrusted Vision & Chat Models**: LLMs/VLMs never calculate or publish stick values. They only emit actions from the closed enum: `notify`, `photo`, `hover`, `yaw_toward`, `start_mode`, `rth`, `land`.
2. **Single Flight Authority**: All flight authority resides in `dji_ground.authority.Authority`. FastMCP tools and the browser gateway are clients of this same authority. No secondary authority exists.
3. **Server-Minted Motion Tokens**: Takeoff and all translating flight modes strictly require a token minted by `arm_motion()`. The token is cryptographically random with an expiration lease. An invented or expired token is rejected.
4. **500 ms Watchdog Loop**: A 10–20 Hz local control loop commands virtual sticks. If no command or heartbeat is received within 500 ms, sticks are immediately zeroed and vehicle enters hover.
5. **Video Freshness (<1000 ms)**: If decoded frame age > 1000 ms, authority declares lost video and forces immediate hover.
6. **Hard Safety Caps**:
   - Indoor default: 1.0 m/s max speed, 3.0 m AGL max altitude, 15 m box dimension.
   - Outdoor default: 3.0 m/s max speed, 30.0 m AGL max altitude, polygon geofence file.
7. **Instant Overrides**: `emergency_stop()` and `release_to_rc()` always succeed unconditionally in any state.
8. **What is NOT Allowed**:
   - No beyond-visual-line-of-sight (BVLOS) flights.
   - No flight by automated Android UI tapping.
   - No raw stick values commanded by chat models or vision detectors.

---

## 2. Flight Modes

1. **`narrate`**: Aircraft hovers in place (sticks zeroed) and periodically calls `describe_scene()`.
2. **`sentinel`**: Aircraft hovers, captures baseline scene, and evaluates triggers & scene diffs.
3. **`follow`**: Visual tracking on locked bounding box with capped velocity; if target lost for >1.0s, halts and hovers.
4. **`orbit`**: Circles a Point of Interest (POI) at configured radius $R$; records sector notes.
5. **`indoor_grid`**: Lawnmower search inside room polygon; hard stop at boundary margin.
6. **`outdoor_box`**: Perimeter box survey inside geofence; photo and scene note per vertex.
7. **`manual_sidecar`**: Human pilot commands sticks via web gamepad; AI vision sidecar alerts and failsafes.

---

## 3. Real-time 3D Reconstruction & Timeline Scrubbing

When enabled with `--enable-3d-modeling` or `DJI_ENABLE_3D_MODELING=true`, `dji-ground` synchronizes live video frames with 6-DOF telemetry poses and gimbal angles to build a real-time 3D point cloud:
- **Interactive 3D Viewport**: WebGL/Canvas renderer with mouse rotation, panning, and zoom.
- **Timeline Scrubber**: Scrub back and forth across flight time $[0, T]$ to view the drone position, camera snapshot, and point cloud accumulated up to that second.
- **Autonomous Workflow**: "*Find item X and 3D model it*":
  - Detects target object $X$ in camera viewport.
  - Returns proposal with matched bounding box requiring operator arming (`status: "requires_arm"`).
  - Operator mints motion token via `arm_motion('orbit')`.
  - Re-invokes with `confirm_token`, circles the target, accumulates dense 3D slices, and exports `.ply`, `.obj`, and `.gltf` model files.
- **Fail-Closed Mode Holds**: If an autonomous mode does not have an active waypoint track or operator stick input, it defaults to zero-translation holds (`mode_holds.py`).
- **Position-Integrated Geofencing**: Tracks estimated local ENU coordinates `(local_x, local_y)` through velocity integration over time, preventing runaway motion outside the geofence boundary.

---

## 4. Setup & Installation

### Prerequisites
- Python 3.12+
- `uv` (Fast Python package manager)
- (Optional for physical flight) Android phone with USB debugging and DJI RC

```bash
# 1. Clone the repository
git clone https://github.com/maximusmaximus/dji-ground.git
cd dji-ground

# 2. Create virtual environment and install package in editable mode
uv venv
uv pip install -e ".[dev]"

# 3. Copy environment template
cp .env.example .env
```

### Running the Test Gate
Verify the entire test gate (all 34 tests and ruff linter) locally without physical drone hardware:
```bash
uv run pytest -v
uv run ruff check src tests deploy scripts
```
All unit tests, integration pipelines, safety watchdog timers, geofence algorithms, and state machines will pass green in ~2 seconds.

---

## 5. How to Run

`dji-ground` supports multiple execution modes depending on whether you are running the unified web dashboard, the FastMCP stdio server for an AI agent, the Telegram mobile bridge, or standalone test missions.

### Option 1: Unified Ground Station (Web Dashboard + REST API + WebSockets)
Starts the single flight authority, video decode pipeline, telemetry socket, and browser UI:
```bash
# Using the installed CLI entrypoint:
uv run dji-station

# Or directly with python:
uv run python scripts/run_station.py --enable-3d
```
Options:
- `--port 8000`: Set HTTP/WebSocket gateway port.
- `--host 0.0.0.0`: Bind to network interfaces.
- `--enable-3d`: Enable real-time 3D point cloud accumulation and GLTF/OBJ/PLY export.
- `--opendji`: Connect to live OpenDJI bridge over ADB forward ports.
- `--no-browser`: Do not auto-launch browser tab.

Open **`http://localhost:8000/`** to view:
- **FPV Video Stream**: Low-latency H.264 decoded feed with HUD overlay.
- **Flight Authority HUD**: Current state, mode, battery %, altitude, and watchdog heartbeat.
- **Mode Selector**: Engage any of the 7 flight modes (translating modes require token confirmation).
- **Interactive 3D Viewport**: Real-time point cloud viewer with orbit/pan/zoom controls.
- **Timeline Scrubber**: Scrub backwards and forwards across flight time to inspect reconstructed geometry and pose slices.
- **HTML5 Gamepad Controller**: Plug in a USB or Bluetooth controller (e.g. Xbox, DualShock) to fly virtual sticks in `manual_sidecar` mode.

### Option 2: FastMCP Server (Hermes Agent / Claude Desktop / Cursor)
Exposes the flight authority and 3D modeling tools over `stdio` to any Model Context Protocol (MCP) client:
```bash
uv run python -m dji_ground.mcp_server --enable-3d-modeling
```
The server exposes 24 tools under strict safety enforcement (see Section 8 for tool reference).

### Option 3: Telegram Bot Operator Bridge
Allows authenticated operators on mobile to receive telemetry, photos, 3D model files, and issue failsafe commands:
```bash
# 1. Start gateway in terminal A
uv run dji-station

# 2. Start Telegram bot bridge in terminal B
uv run python deploy/telegram/bot.py
```

### Option 4: Automated Flight Missions
Pre-packaged scripts demonstrating end-to-end flight sequences against the simulator or live hardware:
```bash
# 1. Basic simulation mission (preflight -> takeoff -> narrate -> land):
uv run python scripts/sim_mission.py

# 2. Autonomous 3D scan mission ("Find item X and 3D model it"):
uv run python scripts/scan_target_mission.py "red_cone"

# 3. Guarded indoor grid mission (requires explicit opt-in):
INDOOR_ARM=1 uv run python scripts/indoor_mission.py

# 4. Guarded outdoor geofenced box mission (requires explicit opt-in):
OUTDOOR_ARM=1 uv run python scripts/outdoor_mission.py
```

### Option 5: Frontend Development (Optional)
If you want to edit or rebuild the React + TypeScript frontend dashboard:
```bash
cd web
npm install
npm run build   # Builds production bundle to web/dist/
npm run dev     # Starts Vite HMR dev server at http://localhost:5173/
```

---

## 6. Lab & Flight Connection Paths

### Path A: Lab Simulation (No Drone Hardware)
1. By default, `DJI_BRIDGE_MODE=fake` connects to an internal physics simulator with deterministic aerodynamics and camera feed.
2. For testing with Android DJI Bridge:
   - Launch Android Studio emulator with the **DJI Android Bridge App** installed.
   - Connect DJI Assistant 2 (Consumer Drones Series) simulator to the virtual drone.
   - Start `dji-station`.

### Path B: Phone Flight Path (Live Aircraft)
1. Connect Android phone to physical DJI Remote Controller (RC) via USB.
2. Launch **OpenDJI** (`Penkov-D/DJI-MSDK-to-PC`) on the phone.
3. Forward TCP ports over ADB:
   ```bash
   adb forward tcp:8001 tcp:8001  # Telemetry socket
   adb forward tcp:8002 tcp:8002  # Video stream socket
   adb forward tcp:8003 tcp:8003  # Command socket
   ```
4. Set `.env` to `DJI_BRIDGE_MODE=opendji`.
5. For live flight clearance, set `INDOOR_ARM=1` or `OUTDOOR_ARM=1`.
6. Maintain visual line of sight (VLOS) with hands on the physical RC sticks at all times.

---

## 7. Hermes Agent & Venice AI Setup

### FastMCP Server Configuration (`~/.hermes/hermes.json` or MCP settings)
```json
{
  "mcp_servers": {
    "dji-ground": {
      "command": "python",
      "args": [
        "-m",
        "dji_ground.mcp_server",
        "--enable-3d-modeling"
      ],
      "env": {
        "DJI_ENABLE_3D_MODELING": "true",
        "VENICE_API_KEY": "${VENICE_API_KEY}",
        "PYTHONPATH": "src"
      }
    }
  }
}
```

### Copy Hermes Pilot Skills
```bash
mkdir -p ~/.hermes/skills
cp deploy/hermes/SOUL.md ~/.hermes/
cp deploy/hermes/skills/*.md ~/.hermes/skills/
```

### Venice AI API Configuration
In your `.env`:
```bash
VENICE_API_KEY="your_venice_api_key"
VENICE_API_BASE="https://api.venice.ai/api/v1"
VENICE_MODEL="llama-3.3-70b"
VENICE_VISION_MODEL="qwen-2.5-vl-72b"
```

---

## 8. Telegram Bot Operator Bridge

The Telegram bot bridge allows authenticated operators to control and monitor flights from Telegram:

1. Create a bot with [@BotFather](https://t.me/BotFather) and get token.
2. Find your numeric Telegram ID with [@userinfobot](https://t.me/userinfobot).
3. Set `.env`:
   ```bash
   TELEGRAM_BOT_TOKEN="123456789:ABC..."
   TELEGRAM_ALLOWED_USERS="123456789"  # Whitelist operator user IDs
   ```
4. Start gateway and bot:
   ```bash
   uv run dji-station
   uv run python deploy/telegram/bot.py
   ```
5. Available Commands:
   - `/status`: Flight state, active mode, battery %, altitude, and video freshness.
   - `/preflight`: Run automated sensor, battery, GPS, and geofence check.
   - `/photo`: Capture and receive live high-resolution drone camera snapshot.
   - `/describe`: Receive visual scene description, object detections, and photo overlay.
   - `/scan <item>`: Execute autonomous "find item X and 3D model it" scan proposal.
   - `/models`: List stored 3D reconstruction models.
   - `/download <session_id>`: Download `.obj` or `.ply` 3D model directly to Telegram.
   - `/stop`: **Unconditional emergency stop** (bypasses LLM reasoning; zeroes sticks instantly).

---

## 9. MCP Tool Surface (Exact Names & Parameters)

| Tool Name | Parameters | Description |
| :--- | :--- | :--- |
| `get_status` | None | Full status, battery, telemetry, and authority state |
| `preflight_check` | None | Verify sensors, battery, geofence, and GPS lock |
| `takeoff` | `token: str` | Command takeoff (requires server-minted arm token) |
| `land` | `token: str = ""` | Auto-land at current coordinate |
| `rth` | None | Command Return-To-Home |
| `emergency_stop` | None | Immediate emergency stop / zero sticks |
| `release_to_rc` | None | Relinquish control back to physical RC |
| `get_latest_frame` | None | Base64 JPEG frame, timestamp, and age_ms (fails closed if stale) |
| `get_ui_screenshot` | None | Android ADB screen capture |
| `get_osd_text` | None | Extracted OSD warning banners and flight status |
| `describe_scene` | `prompt: str = ""` | VLM caption, objects, overlays, telemetry stamp |
| `diff_scene` | `baseline_id: str = ""` | Difference between current scene and baseline snapshot |
| `detect_objects` | `labels: list = None` | Bounding boxes, labels, and confidences |
| `set_baseline` | None | Set current frame as reference baseline snapshot |
| `set_trigger` | `trigger_def: dict` | Register trigger rule (enforces closed action enum) |
| `list_triggers` | None | List active triggers |
| `clear_trigger` | `trigger_id: str` | Remove trigger rule |
| `arm_motion` | `mode: str` | Mint server cryptographic token for motion (TTL lease) |
| `set_mode` | `mode: str, token: str, params: dict` | Switch into one of 7 flight modes |
| `get_mode` | None | Query active flight mode and parameters |
| `start_3d_scan` | `target_label: str, resolution: str` | Start live 3D reconstruction session |
| `stop_3d_scan` | None | Finalize 3D model and export `.ply`, `.obj`, and `.gltf` |
| `get_3d_model` | `session_id: str` | Query 3D model metadata, point count, and bounds |
| `scan_target_object` | `target_label: str, radius_m: float = 3.0, confirm_token: str = None` | "Find item X and 3D model it". Proposes scan; requires operator confirm token. |

---

## 10. License & Safety Disclaimer

MIT License.

**DISCLAIMER**: Autonomous aircraft operation carries inherent physical risks. Always comply with local civil aviation regulations (FAA Part 107, EASA, etc.). Maintain visual line of sight (VLOS) at all times. The human operator holding the physical DJI Remote Controller is ALWAYS the Pilot in Command (PIC) and must keep hands on the sticks ready to take manual control.

