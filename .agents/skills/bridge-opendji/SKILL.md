---
name: bridge-opendji
description: Protocol specification for OpenDJI three-socket bridge and fake client contract.
---

# OpenDJI Bridge Protocol & Fake Client Contract

## Overview
The `bridge` package communicates with the aircraft via the OpenDJI protocol (Penkov-D/DJI-MSDK-to-PC), which runs on an Android device connected over USB to the DJI Remote Controller (RC). Alternatively, in simulation, it connects to the official DJI Android Bridge App paired with the DJI Assistant 2 simulator.

## Sockets Architecture

OpenDJI operates three distinct TCP sockets:

1. **Telemetry Socket (Default Port 8001)**:
   - Emits streaming JSON or framed telemetry packets at 10–20 Hz.
   - Contains:
     - `latitude`: float degrees
     - `longitude`: float degrees
     - `altitude_agl`: float meters
     - `roll`, `pitch`, `yaw`: float degrees (-180..180)
     - `battery_percent`: int 0..100
     - `gps_satellite_count`: int
     - `signal_quality`: int 0..100
     - `flight_mode`: str
     - `is_flying`: bool
     - `gimbal_pitch`: float degrees

2. **Video Socket (Default Port 8002)**:
   - Emits raw byte stream of Annex B H.264 NAL units (`0x00000001` or `0x000001` prefixes).
   - PyAV decodes the NAL units into RGB video frames.
   - Each frame is stamped with monotonic reception time (`timestamp_ms`).

3. **Command / Virtual Stick Socket (Default Port 8003)**:
   - Accepts virtual stick commands in normalized coordinates `[-1.0, 1.0]`:
     - `pitch`: Forward/backward translation velocity
     - `roll`: Right/left translation velocity
     - `yaw`: Angular yaw velocity
     - `throttle`: Vertical ascent/descent velocity
   - Discrete aircraft commands:
     - `takeoff`
     - `land`
     - `rth`
     - `emergency_stop`
     - `release_to_rc`

## Fake Bridge Contract (`FakeBridge`)
For unit tests, CI, and local development without hardware, `FakeBridge` provides:
- Deterministic synthetic telemetry loop running at 15 Hz.
- Playback of fixture H.264 video (`fixtures/sample_h264_stream.h264`).
- Physics simulation responding to stick inputs with velocity integration.
- Fault injection hooks:
  - `inject_video_loss(duration_s: float)`: Stops sending video frames to test >1000ms stale frame failsafe.
  - `inject_battery_level(percent: int)`: Triggers low-battery failsafe.
  - `inject_obstacle_detected()`: Simulates obstacle sensor alert.
  - `inject_link_loss()`: Simulates RC disconnect.
