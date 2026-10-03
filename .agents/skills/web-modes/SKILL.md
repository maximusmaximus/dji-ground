---
name: web-modes
description: Specification for the seven autonomous flight modes, sidecar control, and the emergency STOP button.
---

# Flight Modes & Web Interface Control

## The Seven Flight Modes

1. **`narrate`**:
   - Drone holds hover in place (sticks zeroed).
   - Periodically samples frames (e.g. every 2–5 seconds) and calls `describe_scene()`.
   - Streams descriptions to UI transcript and/or Telegram chat.

2. **`sentinel`**:
   - Drone hovers at designated observation post.
   - Captures an initial baseline scene snapshot via `set_baseline()`.
   - Continuously evaluates incoming frames with `diff_scene()` and checks active trigger rules.
   - Fires trigger action (e.g. `notify`, `photo`, `hover`) upon intrusion or anomaly.

3. **`follow`**:
   - Locks onto a bounding box (identified by click coordinate or label).
   - Local proportional tracking loop computes velocity setpoints to keep the target centered in the frame.
   - Velocity is strictly clamped to `max_speed` (1.0 m/s indoor, 3.0 m/s outdoor).
   - Geofence enforcement: If tracking would bring aircraft outside geofence, forward stick is cut.
   - If target is lost for > 1.0 second, stops advancing and holds hover.

4. **`orbit`**:
   - Circles a designated Point of Interest (POI) at a constant radius $R$ and altitude.
   - Controls pitch/roll to maintain circular track while continuous yaw points camera directly at the POI.
   - At each cardinal sector (0°, 90°, 180°, 270°), pauses briefly to take a photo or record a sector description.

5. **`indoor_grid`**:
   - Generates a lawnmower serpentine search pattern within an indoor room polygon.
   - Hard capped to `indoor_max_speed` (1.0 m/s) and `indoor_max_altitude` (3.0 m AGL).
   - Enforces a 0.5m buffer margin from walls; hard stops at polygon boundary.
   - Pauses at each grid cell centroid to describe the cell and inspect for anomalies.

6. **`outdoor_box`**:
   - Executes a perimeter rectangle inside the outdoor geofence boundary.
   - Capped to `outdoor_max_speed` (3.0 m/s) and `outdoor_max_altitude` (30.0 m AGL).
   - Pauses at each vertex to record high-resolution stills, GPS stamp, and scene notes.

7. **`manual_sidecar`**:
   - Operator flies manually using a connected gamepad or on-screen virtual sticks via WebSockets.
   - Sticks pass through safety filter (clamping velocity and geofence boundary checks).
   - The AI vision pipeline runs in parallel as a guardian sidecar: it can alert the operator and trigger automatic RTH/hover if safety hazards or boundary breaches occur, but never tampers with manual control sticks during safe flight.

## The STOP Control
- Persistent, prominent red button in the Web UI: **`EMERGENCY STOP`**.
- Accessible at all times, regardless of current mode or menu.
- Immediately issues `POST /api/emergency_stop`.
- Bypasses any confirmation dialogs or LLM reasoning.
- Authority unconditionally zeros all stick outputs and commands immediate hover/failsafe within < 100 ms.
