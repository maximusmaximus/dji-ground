# Hermes Skill: Preflight Verification Checklist

## Goal
Verify all safety preconditions before issuing any motion commands.

## Procedure
1. Call `get_status()` to inspect link state and video freshness.
2. Call `preflight_check()` to verify battery >= 30%, GPS satellites >= 8, geofence loaded, and obstacle sensors clear.
3. Call `get_osd_text()` to inspect screen for any active warnings or braking alerts.
4. If all checks return `passed: true`, prompt the human operator for confirmation:
   *"Preflight checks passed (Battery: XX%, Sats: YY). Ready for takeoff. Shall I proceed?"*
5. Do NOT call `takeoff()` until the operator explicitly confirms.
