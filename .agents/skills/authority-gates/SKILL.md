---
name: authority-gates
description: Enforcing motion tokens, the 500ms watchdog, geofence, and velocity caps. Never weaken these to make a test pass.
---

# Authority Gates, Tokens, Watchdogs & Geofences

## Core Rules
Under NO circumstances should any safety gate, token validation, watchdog timer, or geofence boundary check be disabled, bypassed, or relaxed. If a test fails because a gate rejected an action, the test setpoint or test flow was incorrect, NOT the gate.

## 1. Server-Minted Motion Tokens (`arm_motion`)
- Translating flight modes (`follow`, `orbit`, `indoor_grid`, `outdoor_box`, `manual_sidecar`) and `takeoff` require an arming token.
- Minted by calling `authority.arm_motion(mode)`.
- Token properties:
  - Cryptographically secure random UUID or hex string.
  - Linked to a specific target mode.
  - Expiration lease (default: 30 seconds to begin mode).
  - Single-use consumption upon mode activation.
- Untrusted callers cannot fabricate tokens. An invalid, unassigned, or expired token raises `PermissionError` and halts operation.

## 2. 500 ms Watchdog Loop
- An internal background loop executes at 10–20 Hz (default: 15 Hz) to send virtual sticks to the bridge.
- The authority tracks `last_heartbeat_timestamp`.
- Every active mode or manual control loop must refresh this heartbeat.
- If `now - last_heartbeat_timestamp > 0.500s`:
  - Watchdog trips immediately.
  - All stick velocities (pitch, roll, yaw, throttle) are zeroed (`0.0, 0.0, 0.0, 0.0`).
  - Flight mode transitions to `EMERGENCY_HOVER`.
  - Event is recorded in the structured audit log.

## 3. Video Freshness Check (1000 ms limit)
- Decoded video frames report `age_ms = (now - frame_timestamp) * 1000`.
- In `describe_scene()` or authority evaluation:
  - If `age_ms > 1000`:
    - Video is classified as **LOST**.
    - Authority forces translational sticks to zero and transitions to hover.
    - Model requests for motion during stale video are rejected.

## 4. Hard Safety Caps
- Loaded strictly from `config.py` / environment:
  - **Indoor**: Max speed $1.0\text{ m/s}$, Max altitude $3.0\text{ m AGL}$, Max bounding box $15.0\text{ m}$.
  - **Outdoor**: Max speed $3.0\text{ m/s}$, Max altitude $30.0\text{ m AGL}$, Geofence file check.
- Stick outputs from any tracking or waypoint generator are clamped:
  $$\vec{v}_{\text{command}} = \text{clamp}(\vec{v}, -v_{\text{max}}, v_{\text{max}})$$

## 5. Geofence Boundary Check
- Geofence is defined as a 2D/3D polygon.
- Every prospective waypoint or current coordinate is checked before issuing translational sticks:
  - If coordinate falls outside the safe boundary (with a 0.5m buffer), translation toward the boundary is blocked.
  - Vehicle enters hover if boundary breach is detected.
