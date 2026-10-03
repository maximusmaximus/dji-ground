# Telegram operator bot

The operator bot is a thin client of the running `dji-station` gateway. It long-polls Telegram,
refuses everyone who is not on `TELEGRAM_ALLOWED_USERS` (an **empty list refuses everyone**),
and never mints a motion token on its own. Motion only happens when an allow-listed human sends
`/confirm_scan <item>`.

The code lives in [`src/dji_ground/telegram_bot.py`](../../src/dji_ground/telegram_bot.py);
`bot.py` here is a back-compat shim.

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. Get your numeric user id from [@userinfobot](https://t.me/userinfobot).
3. In the repo `.env`:

   ```bash
   TELEGRAM_BOT_TOKEN=123456789:AA...
   TELEGRAM_ALLOWED_USERS=111111111            # comma-separated for several pilots
   VENICE_API_KEY=...                          # optional: free-text copilot replies
   ```

4. Check, then run (one process, one flight authority):

   ```bash
   uv run dji-station --check --telegram
   uv run dji-station --telegram --enable-3d
   ```

   Or run the bot separately against an already-running station:
   `uv run dji-telegram` (uses `DJI_GATEWAY_URL`, default `http://127.0.0.1:8000`).

> One bot token can only be polled by one process. If you also run the Hermes Agent Telegram
> gateway, give Hermes its **own** bot token, otherwise Telegram returns 409 Conflict.

## Commands

| Command | Effect |
| :--- | :--- |
| `/status` | State, mode, battery, altitude, video age, bridge, mission progress |
| `/preflight` | Preflight checklist (lists failing checks) |
| `/photo` | Latest FPV frame |
| `/describe` | Scene caption (Venice VLM) + detected objects, with the frame |
| `/scan <item>` | Find the item and **propose** an orbit 3D scan. Nothing moves. |
| `/confirm_scan <item>` | You (PIC) authorise it: mints an orbit token and starts the scan. The aircraft must already be airborne and armed. |
| `/models` | Recorded 3D models |
| `/download <session_id>` | Sends the OBJ (or PLY/glTF) file |
| `/land`, `/rth` | Land / return to home |
| `/stop` (also `stop`, `abort`, `halt`) | Emergency stop: zero sticks and hover. Always works. |
| any other text | Venice copilot answers in text. It can never fly. |
