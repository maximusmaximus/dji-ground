# Hermes Skill: Flight Telemetry & Health Monitoring

## Goal
Query aircraft telemetry, battery status, velocities, and link metrics.

## Procedure
1. Call `get_status()` to receive:
   - Aircraft altitude AGL, battery percentage, heading, and 3D velocity vectors.
   - Watchdog status (verifying loop updates within 500 ms).
   - Video freshness (verifying frame age <= 1000 ms).
2. Call `get_latest_frame()` to view the camera snapshot.
3. Call `describe_scene()` to receive VLM caption, detected objects, and overlays.
