# Hermes Skill: Safety Triggers Management

## Goal
Configure automated surveillance and safety trigger rules.

## Enforced Closed Action Enum
Any action in `set_trigger` MUST be one of:
- `notify`: Stream an event card to chat.
- `photo`: Capture a high-resolution still.
- `hover`: Immediately halt forward and lateral translation.
- `yaw_toward`: Rotate heading toward detected object azimuth.
- `start_mode`: Request transition into an authorized mode.
- `rth`: Command Return-to-Home.
- `land`: Command auto-landing.

## Procedure
To add a trigger:
```json
{
  "trigger_id": "trig_cone_detect",
  "name": "Stop on Safety Cone",
  "action": "hover",
  "condition_type": "object_detected",
  "condition_value": "red_cone"
}
```
Call `set_trigger(trigger_def={...})`.
To inspect rules, call `list_triggers()`.
To remove, call `clear_trigger(trigger_id="...")`.
