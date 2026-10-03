# Hermes Skill: Emergency & Overrides

## Goal
Execute immediate failsafe overrides when conditions warrant.

## Tools
- `emergency_stop()`:
  - Unconditionally stops translation, zeroes virtual sticks, and enters emergency hover/failsafe within <100ms.
  - Call immediately if:
    - Operator commands "STOP", "HALT", "ABORT", or "FREEZE".
    - Video drops for > 1 second.
    - Unexpected obstacle or flyaway behavior is detected.
- `release_to_rc()`:
  - Immediately relinquishes virtual stick control back to the physical RC in the pilot's hands.
  - Call whenever the human pilot wants manual control.
