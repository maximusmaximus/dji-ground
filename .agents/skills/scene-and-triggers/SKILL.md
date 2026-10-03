---
name: scene-and-triggers
description: Specification for describe_scene schema, OSD text extraction, and closed trigger action enum.
---

# Scene Analysis & Closed Trigger Action Enum

## 1. Frame Representation & `describe_scene` Contract
The `describe_scene` tool provides a comprehensive snapshot of what the drone's primary camera sees:

```python
{
    "caption": "A warehouse corridor with shelving units and a forklift parked on the left.",
    "objects": [
        {
            "label": "forklift",
            "conf": 0.94,
            "bbox": [0.12, 0.45, 0.38, 0.88],  # [ymin, xmin, ymax, xmax] normalized
            "source": "detector"                # or "vlm"
        }
    ],
    "overlays": ["GEOFENCE_ACTIVE", "BATTERY_OK"],
    "telemetry_stamp": {
        "timestamp_ms": 1727918400123,
        "altitude_agl": 2.4,
        "heading_deg": 182.5,
        "battery_percent": 84
    },
    "frame_id": 4821,
    "age_ms": 42.5  # Crucial: if > 1000, authority enforces hover
}
```

## 2. Screen & OSD Extraction (`screen.py`)
- Screen captures are retrieved from the connected Android device via ADB (`adb exec-out screencap -p`).
- **Strict Rule**: The flight codebase must NEVER import `scrcpy`.
- Optical Character Recognition (OCR) and regex pattern matching parse the OSD banner for critical flight alerts:
  - `"Obstacle detected"` -> Forces `EMERGENCY_HOVER`
  - `"Weak signal"` / `"Disconnection"` -> Alerts operator, readies failsafe
  - `"Braking"` -> Confirms safety intervention

## 3. Closed Trigger Action Enum
Triggers evaluate conditions against object detections, scene descriptions, OSD alerts, and telemetry.
Any trigger registering an action outside this closed enum is strictly rejected with a validation error:

1. `notify`: Log the event and stream a notification card to the Web UI / Telegram chat.
2. `photo`: Save high-resolution camera still and register it in the session SQLite database.
3. `hover`: Immediately halt forward/lateral translation and hover stationary in place.
4. `yaw_toward`: Rotate the aircraft heading toward the target's azimuth without translating.
5. `start_mode`: Request transition into an authorized mode (e.g. `sentinel` or `orbit`).
6. `rth`: Initiate Return-To-Home procedure.
7. `land`: Initiate auto-landing procedure at current coordinate.

**No other action strings are permitted.**
Models are prohibited from commanding arbitrary velocities, stick deltas, or custom motion scripts through triggers.
