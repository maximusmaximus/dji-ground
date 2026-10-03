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

## 4. Setup & Quickstart

### Prerequisites
- Python 3.12+
- `uv` (Fast Python package manager)

```bash
# Clone the repository
git clone https://github.com/maximusmaximus/dji-ground.git
cd dji-ground

# Create virtual environment and install dependencies
uv venv
uv pip install -e ".[dev]"

# Copy environment template
cp .env.example .env
```

### Running the Test Gate
Verify the entire test suite without physical drone hardware:
```bash
uv run pytest -v
uv run ruff check src tests
```
All 34 unit, integration, safety gate, and state machine tests pass green.

---

## 5. Lab & Flight Connection Paths

### Path A: Lab Simulation (No Drone Hardware)
1. Launch Android Studio emulator with the **DJI Android Bridge App** installed.
2. Connect DJI Assistant 2 (Consumer Drones Series) simulator to the virtual drone.
3. Start `dji-ground`:
   ```bash
   uv run python -m dji_ground.gateway
   ```
4. Open the Web UI at `http://localhost:8000/`.

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

---

## 6. Hermes Agent & Venice AI Setup

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

## 7. Telegram Bot Operator Bridge

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
   uv run python -m dji_ground.gateway
   uv run python deploy/telegram/bot.py
   ```
5. Commands:
   - `/status`: Flight health, battery, altitude, and video freshness.
   - `/preflight`: Run automated sensor check.
   - `/describe`: Receive visual scene description and detected objects.
   - `/scan <item>`: Execute autonomous "find item X and 3D model it".
   - `/stop`: **Unconditional emergency stop** (bypasses LLM reasoning).

---

## 8. MCP Tool Surface (Exact Names)

| Tool Name | Parameters | Description |
| :--- | :--- | :--- |
| `get_status` | None | Full status, battery, telemetry, and authority state |
| `preflight_check` | None | Verify sensors, battery, geofence, and GPS lock |
| `takeoff` | `token: str` | Command takeoff (requires arm token) |
| `land` | `token: str = ""` | Auto-land at current coordinate |
| `rth` | None | Command Return-To-Home |
| `emergency_stop` | None | Immediate emergency stop / zero sticks |
| `release_to_rc` | None | Relinquish control back to physical RC |
| `get_latest_frame` | None | Base64 JPEG frame, timestamp, and age_ms |
| `get_ui_screenshot` | None | Android ADB screen capture |
| `get_osd_text` | None | Extracted OSD warning banners and flight status |
| `describe_scene` | `prompt: str = ""` | VLM caption, objects, overlays, telemetry stamp |
| `diff_scene` | `baseline_id: str = ""` | Difference between current scene and baseline |
| `detect_objects` | `labels: list = None` | Bounding boxes, labels, and confidences |
| `set_baseline` | None | Set current frame as reference baseline |
| `set_trigger` | `trigger_def: dict` | Register trigger (enforces closed action enum) |
| `list_triggers` | None | List active triggers |
| `clear_trigger` | `trigger_id: str` | Remove trigger rule |
| `arm_motion` | `mode: str` | Mint server cryptographic token for motion |
| `set_mode` | `mode: str, token: str, params: dict` | Switch into one of 7 flight modes |
| `get_mode` | None | Query active flight mode and parameters |
| `start_3d_scan` | `target_label: str, resolution: str` | Start live 3D reconstruction session |
| `stop_3d_scan` | None | Finalize 3D model and export `.ply` |
| `get_3d_model` | `session_id: str` | Query 3D model metadata and point count |
| `scan_target_object` | `target_label: str, radius_m: float` | "Find item X and 3D model it" workflow |

---

## 9. License & Safety Disclaimer

MIT License.

**DISCLAIMER**: Autonomous aircraft operation carries inherent physical risks. Always comply with local civil aviation regulations (FAA Part 107, EASA, etc.). Maintain visual line of sight at all times. Keep hands on the physical RC sticks ready to take manual control.
