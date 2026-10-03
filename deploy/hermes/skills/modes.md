# Hermes Skill: Flight Modes Selection

## Goal
Select and transition into one of the 7 authorized flight modes safely.

## Permitted Modes
- `narrate`: Station keeping, periodic visual scene updates. No token required.
- `sentinel`: Station keeping, trigger rule evaluation, scene diffing against baseline.
- `follow`: Visual object tracking with speed cap and geofence boundary stop. (Token required)
- `orbit`: Circular inspection of a Point of Interest (POI). (Token required)
- `indoor_grid`: Lawnmower coverage inside room polygon. (Token required)
- `outdoor_box`: Perimeter rectangle inside geofence. (Token required)
- `manual_sidecar`: Human pilot on gamepad with AI vision safety guardian. (Token required)

## Procedure
1. If the requested mode is a translating mode (`follow`, `orbit`, `indoor_grid`, `outdoor_box`, `manual_sidecar`):
   - Call `arm_motion(mode="<mode_name>")` to obtain a motion token.
2. Call `set_mode(mode="<mode_name>", token="<token>", params={...})`.
3. Verify returned state is `ARMED_ACTIVE`.
