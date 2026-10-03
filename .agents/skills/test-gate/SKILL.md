---
name: test-gate
description: Definition of green test gate and automated verification criteria.
---

# Test Gate Specification: What Green Means

## Overview
A "Green" test gate means all unit and integration tests execute successfully without mocking away safety features, without requiring any physical drone or hardware attached, and without warnings treated as acceptable failures.

## Test Suite Components

### 1. Unit Tests (`tests/test_*_unit.py`, `tests/test_geofence_and_caps.py`, `tests/test_state_machine.py`)
- **Invented Token Rejection**:
  - `arm_motion` produces valid tokens with TTL.
  - Attempting takeoff or translation with a forged or invented token must raise `PermissionError`.
- **Geofence Enforcement**:
  - Waypoints outside the polygon boundaries are rejected.
  - Setpoint commands crossing the geofence perimeter immediately zero translational sticks and hold hover.
- **Watchdog Timeout**:
  - When stick command loop stalls for > 500 ms, watchdog timer zeros all sticks (`pitch=0, roll=0, yaw=0, throttle=0`).
- **Translation Protection**:
  - Every mode (`follow`, `orbit`, `indoor_grid`, `outdoor_box`, `manual_sidecar`) refuses to output translational velocity without prior valid `arm_motion`.
- **Closed Action Enum**:
  - Registering any trigger with an action outside `['notify', 'photo', 'hover', 'yaw_toward', 'start_mode', 'rth', 'land']` fails validation.
- **Stale Video Detection**:
  - A frame timestamp older than 1000 ms (`age_ms > 1000`) forces the authority into hover and refuses motion.
- **State Machine Completeness**:
  - Every transition edge in the state machine matrix is explicitly verified, including invalid transition rejections.

### 2. Integration Tests (`tests/test_integration.py`, `tests/test_mcp_server.py`, `tests/test_3d_modeling.py`)
- **PyAV H.264 Stream Pipeline**:
  - Reads `fixtures/sample_h264_stream.h264`, decodes frames, calls `get_latest_frame`, passes to `describe_scene`, and verifies a valid, non-empty scene descriptor with valid `age_ms`.
- **OSD OCR Extraction**:
  - Processes `fixtures/osd_warning_obstacle.png`, executes `get_osd_text`, and confirms presence of the obstacle warning string.
- **Trigger Execution**:
  - Red cone trigger fires `notify` + `hover` and strictly prevents translational motion.
- **Geofence Follow Boundary**:
  - Target tracking halts at the geofence boundary margin without crossing.
- **Emergency Stop Latency**:
  - `emergency_stop()` halts motion and dispatches command to the fake bridge in < 100 ms (well below 500 ms limit).
- **FastMCP Protocol**:
  - MCP client connects over stdio or in-memory transport, verifies exact 20 stable tools (+ 3D tools if enabled), and tests invocation.
- **3D Modeling & Timeline**:
  - Poses + frames accumulate point cloud; verify `.ply` export and timeline scrub at $t_1, t_2$.

### 3. Opt-in Mission Scripts (`scripts/`)
- Skipped automatically in normal CI runs unless opted in.
- `sim_mission.py`: Simulator mission against DJI Assistant 2.
- `indoor_mission.py`: Fails closed unless `INDOOR_ARM=1` and human on RC.
- `outdoor_mission.py`: Fails closed unless `OUTDOOR_ARM=1`, GPS lock, Remote ID, and VLOS confirmed.
- `scan_target_mission.py`: "Find item x and 3D model it" test with simulated target.
