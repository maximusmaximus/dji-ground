# AGENTS.md: Always-On Rules & Flight Safety Invariants

## Core Safety Invariants (Non-Negotiable)

1. **Untrusted Models**:
   - The vision model (VLM) and chat model (LLM) are untrusted.
   - They **NEVER** calculate or publish stick values directly.
   - They only emit high-level actions from the closed action enum: `notify`, `photo`, `hover`, `yaw_toward`, `start_mode`, `rth`, `land`.

2. **Single Flight Authority**:
   - `dji_ground.authority.Authority` is the sole flight authority.
   - MCP tools, Hermes, web gateways, and Telegram bots are all clients calling the exact same authority methods.
   - There is NO secondary command authority, NO side channel, and NO flight by automated UI tapping or MAVLink.

3. **Server-Minted Motion Tokens**:
   - Takeoff and any mode that translates in 3D space strictly require a server-minted token (`arm_motion`).
   - The LLM/VLM cannot invent or forge a token. Forged or expired tokens are rejected.

4. **Independent Watchdog & Freshness Loop**:
   - A dedicated 10–20 Hz loop owns virtual stick generation and commands.
   - A 500 ms watchdog timer unconditionally zeros all sticks if no heartbeat or motion command is refreshed.
   - Video frames older than 1000 ms (`age_ms > 1000`) cause the authority to immediately declare lost video and force a transition to hover.

5. **Hard Safety Caps & Geofencing**:
   - Speed, altitude, and bounding boundaries are hardcoded in system configuration (`config.py`), never modifiable by chat prompts.
   - Indoor default: 1.0 m/s max speed, 3.0 m AGL max altitude, 15.0 m maximum box dimension.
   - Outdoor default: 3.0 m/s max speed, 30.0 m AGL max altitude, geofence polygon enforced.
   - Setpoints outside the geofence are immediately rejected and force hover.

6. **Instant Overrides**:
   - `emergency_stop()` and `release_to_rc()` always succeed unconditionally in any state.
   - Obstacle OSD alerts, critical battery (<20%), or link degradation trigger automated hover followed by RTH or land with zero model involvement.

7. **Human Pilot in Command & VLOS**:
   - There is no beyond-visual-line-of-sight (BVLOS) operation.
   - The human operator on the physical RC is always pilot in command.
   - Live aircraft tests are strictly opt-in and refused unless explicit arm files/environment variables (`INDOOR_ARM=1` or `OUTDOOR_ARM=1`) are verified.

8. **Test Rigor**:
   - Every mode transition edge must have a dedicated test.
   - Safety gates (token checks, watchdog, geofence) must NEVER be disabled or weakened to make tests pass.
