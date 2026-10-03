"""Telegram operator bridge: long-polls Telegram and forwards commands to the dji-ground gateway.

The bot is a *client* of the gateway (the single flight authority). It never mints tokens on
its own initiative: motion only happens when an allow-listed human types `/confirm_scan`.
Free-text chat goes to Venice for a text reply and can never trigger flight actions.

Run with `dji-telegram` (standalone) or `dji-station --telegram` (in-process).
"""

from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path
from typing import Any

import httpx

from .config import Settings, get_settings

logger = logging.getLogger("dji_ground.telegram")

HELP_TEXT = (
    "dji-ground operator commands:\n"
    "/status - flight state, battery, altitude, video age\n"
    "/preflight - preflight checklist\n"
    "/photo - latest FPV frame\n"
    "/describe - caption the current view (Venice VLM)\n"
    "/scan <item> - find <item> and PROPOSE an orbit 3D scan (no motion)\n"
    "/confirm_scan <item> - you, the pilot, authorise the orbit scan\n"
    "/models - list recorded 3D models\n"
    "/download <session_id> - send a 3D model file\n"
    "/land - land now\n"
    "/rth - return to home\n"
    "/stop - EMERGENCY STOP (hover, always works)\n"
    "Anything else is answered by the Venice copilot (text only, never flies)."
)

STOP_WORDS = {"/stop", "stop", "abort", "halt", "/emergency_stop"}

VENICE_SYSTEM_PROMPT = (
    "You are a DJI drone copilot on Telegram for the dji-ground station. You explain status, "
    "help plan safe 3D scans, and describe scenes. You cannot fly the aircraft: tell the operator "
    "which slash command to use (e.g. /scan <item>, then /confirm_scan <item>). The human is pilot "
    "in command. Never suggest beyond-visual-line-of-sight or reckless flight. Keep replies short."
)


class TelegramBot:
    """Long-polling Telegram bot. HTTP clients are injectable for tests."""

    def __init__(
        self,
        settings: Settings | None = None,
        gateway_url: str | None = None,
        telegram_client: httpx.AsyncClient | None = None,
        gateway_client: httpx.AsyncClient | None = None,
        venice_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.gateway_url = (gateway_url or self.settings.gateway_url).rstrip("/")
        self.token = self.settings.telegram_bot_token
        self.allowed = self.settings.allowed_telegram_ids
        self.api = f"https://api.telegram.org/bot{self.token}"
        # Long-poll timeout is 25 s, so the Telegram client needs a longer read timeout.
        self.tg = telegram_client or httpx.AsyncClient(timeout=httpx.Timeout(40.0, connect=10.0))
        self.gw = gateway_client or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
        self.venice = venice_client or httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
        self.offset = 0

    # ------------------------------------------------------------------ auth

    def is_authorized(self, user_id: int | str) -> bool:
        """Fail closed: an empty allowlist authorises nobody."""
        return bool(self.allowed) and str(user_id) in self.allowed

    # ------------------------------------------------------------------ Telegram I/O

    async def send_message(self, chat_id: int, text: str) -> None:
        resp = await self.tg.post(
            f"{self.api}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        )
        if resp.status_code == 400:
            # Unbalanced Markdown (e.g. an underscore in a caption): resend as plain text.
            await self.tg.post(f"{self.api}/sendMessage", json={"chat_id": chat_id, "text": text})

    async def send_photo(self, chat_id: int, image_bytes: bytes, caption: str = "") -> None:
        await self.tg.post(
            f"{self.api}/sendPhoto",
            data={"chat_id": str(chat_id), "caption": caption[:1024]},
            files={"photo": ("frame.jpg", image_bytes, "image/jpeg")},
        )

    async def send_document(self, chat_id: int, path: Path, caption: str = "") -> None:
        await self.tg.post(
            f"{self.api}/sendDocument",
            data={"chat_id": str(chat_id), "caption": caption[:1024]},
            files={"document": (path.name, path.read_bytes(), "application/octet-stream")},
        )

    # ------------------------------------------------------------------ gateway I/O

    async def _get(self, path: str, **params: Any) -> Any:
        resp = await self.gw.get(f"{self.gateway_url}{path}", params=params or None)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, payload: dict[str, Any] | None = None) -> httpx.Response:
        return await self.gw.post(f"{self.gateway_url}{path}", json=payload or {})

    async def wait_for_gateway(self, attempts: int = 30, delay_s: float = 1.0) -> bool:
        for _ in range(attempts):
            try:
                resp = await self.gw.get(f"{self.gateway_url}/api/health")
                if resp.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            await asyncio.sleep(delay_s)
        return False

    # ------------------------------------------------------------------ commands

    async def handle_update(self, update: dict[str, Any]) -> None:
        msg = update.get("message") or update.get("edited_message")
        if not msg or "text" not in msg:
            return
        chat_id = msg["chat"]["id"]
        user_id = msg.get("from", {}).get("id", 0)
        try:
            await self.handle_command(chat_id, user_id, msg["text"])
        except httpx.HTTPError as exc:
            await self.send_message(
                chat_id, f"Gateway unreachable at {self.gateway_url} ({exc.__class__.__name__})."
            )
        except Exception as exc:  # never let one bad message kill the poll loop
            logger.exception("Command failed")
            await self.send_message(chat_id, f"Command failed: {exc}")

    async def handle_command(self, chat_id: int, user_id: int, text: str) -> None:
        if not self.is_authorized(user_id):
            hint = (
                " The bot has no allow-listed operators (TELEGRAM_ALLOWED_USERS is empty)."
                if not self.allowed
                else ""
            )
            await self.send_message(chat_id, f"Unauthorized (your id: {user_id}).{hint}")
            return

        cmd = text.strip()
        head, _, arg = cmd.partition(" ")
        head = head.lower().split("@", 1)[0]  # "/status@MyBot" in group chats
        arg = arg.strip()

        # Safety commands first; they bypass every other path.
        if cmd.lower() in STOP_WORDS or head in STOP_WORDS:
            resp = await self._post("/api/emergency_stop")
            await self.send_message(chat_id, f"EMERGENCY STOP sent. State: `{_state(resp)}`")
            return
        if head == "/land":
            resp = await self._post("/api/land")
            await self.send_message(chat_id, f"Landing. State: `{_state(resp)}`")
            return
        if head == "/rth":
            resp = await self._post("/api/rth")
            await self.send_message(chat_id, f"Returning home. State: `{_state(resp)}`")
            return

        if head in ("/start", "/help"):
            await self.send_message(chat_id, HELP_TEXT)
            return

        if head == "/status":
            d = await self._get("/api/status")
            prog = d.get("mission_progress") or {}
            lines = [
                "*Flight status*",
                f"State: `{d['state']}`  Mode: `{d['mode']}`",
                f"Battery: `{d['battery_percent']}%`  Alt: `{d['altitude_agl']} m`",
                f"Video: `{'fresh' if d['video_fresh'] else 'STALE'}` ({d['video_age_ms']} ms)",
                f"Bridge: `{d.get('bridge_mode', '?')}` connected=`{d['bridge_connected']}`",
                f"Obstacle: `{d['obstacle_detected']}`  3D: `{d.get('modeling_3d_enabled')}`",
            ]
            if prog:
                lines.append(f"Mission: `{prog}`")
            await self.send_message(chat_id, "\n".join(lines))
            return

        if head == "/preflight":
            d = await self._get("/api/preflight")
            failed = [k for k, ok in d["checks"].items() if not ok]
            verdict = "PASSED" if d["passed"] else "FAILED"
            detail = "all checks ok" if not failed else "failing: " + ", ".join(failed)
            await self.send_message(chat_id, f"Preflight *{verdict}* ({detail})")
            return

        if head == "/photo":
            d = await self._get("/api/get_latest_frame")
            if d.get("image_b64"):
                cap = f"Frame #{d.get('frame_id')} age {d.get('age_ms')} ms"
                await self.send_photo(chat_id, base64.b64decode(d["image_b64"]), cap)
            else:
                await self.send_message(chat_id, "Camera frame unavailable.")
            return

        if head == "/describe":
            d = await self._get("/api/describe_scene")
            objs = ", ".join(o["label"] for o in d.get("objects", [])) or "none"
            caption = f"{d.get('caption', '')}\n\nObjects: {objs}"
            frame = await self._get("/api/get_latest_frame")
            if frame.get("image_b64"):
                await self.send_photo(chat_id, base64.b64decode(frame["image_b64"]), caption)
            else:
                await self.send_message(chat_id, caption)
            return

        if head == "/scan":
            await self._scan(chat_id, arg, confirm=False)
            return

        if head == "/confirm_scan":
            await self._scan(chat_id, arg, confirm=True)
            return

        if head == "/models":
            resp = await self.gw.get(f"{self.gateway_url}/api/3d_models")
            sessions = resp.json() if resp.status_code == 200 else []
            if not sessions:
                await self.send_message(chat_id, "No 3D models yet. Try /scan <item>.")
                return
            lines = ["*Recorded 3D models*"]
            for s in sessions[:8]:
                label = s.get("target_label") or "-"
                lines.append(
                    f"`{s['session_id']}` {label}: {s.get('point_count', 0)} pts"
                    f"  (/download {s['session_id']})"
                )
            await self.send_message(chat_id, "\n".join(lines))
            return

        if head == "/download":
            if not arg:
                await self.send_message(chat_id, "Usage: /download <session_id>")
                return
            await self._download(chat_id, arg)
            return

        if cmd.startswith("/"):
            await self.send_message(chat_id, HELP_TEXT)
            return

        await self._venice_chat(chat_id, cmd)

    async def _scan(self, chat_id: int, target: str, confirm: bool) -> None:
        if not target:
            usage = "/confirm_scan <item>" if confirm else "/scan <item>"
            await self.send_message(chat_id, f"Usage: {usage}")
            return
        payload: dict[str, Any] = {"target_label": target}
        if confirm:
            # The allow-listed human explicitly authorised motion: mint a one-shot orbit token.
            arm = await self._post("/api/arm_motion", {"mode": "orbit"})
            arm.raise_for_status()
            payload["confirm_token"] = arm.json()["token"]

        resp = await self._post("/api/scan_target", payload)
        if resp.status_code in (403, 409):
            detail = resp.json().get("detail", resp.text)
            await self.send_message(chat_id, f"Scan refused: {detail}")
            return
        resp.raise_for_status()
        d = resp.json()
        status = d.get("status", "")

        if status == "3d_modeling_disabled":
            await self.send_message(chat_id, d.get("message", "3D modeling is disabled."))
        elif status == "scanning_target_initiated":
            await self.send_message(
                chat_id,
                f"Orbit scan started for `{target}` (r={d.get('radius_m')} m).\n"
                f"Session: `{d.get('session_id')}`. Send /stop at any time.",
            )
        elif status == "target_not_found" or (not confirm and not d.get("matched_bbox")):
            await self.send_message(
                chat_id, f"`{target}` is not visible right now. Point the camera at it and retry."
            )
        else:
            await self.send_message(
                chat_id,
                f"Found `{target}` at bbox `{d.get('matched_bbox')}`. Nothing is moving.\n"
                f"Aircraft must be airborne and armed. To orbit and 3D-model it, "
                f"you (the pilot) send:\n/confirm_scan {target}",
            )

    async def _download(self, chat_id: int, session_id: str) -> None:
        export_dir = Path(self.settings.model_3d_export_dir).resolve()
        for ext, kind in (("obj", "OBJ mesh"), ("ply", "PLY point cloud"), ("gltf", "glTF")):
            path = (export_dir / f"{session_id}.{ext}").resolve()
            if path.parent != export_dir:  # reject path traversal such as "../../secret"
                await self.send_message(chat_id, "Invalid session id.")
                return
            if path.exists():
                await self.send_document(chat_id, path, f"{kind} ({session_id})")
                return
        await self.send_message(chat_id, f"No model files for `{session_id}`. See /models.")

    async def _venice_chat(self, chat_id: int, text: str) -> None:
        if not self.settings.venice_configured:
            await self.send_message(chat_id, HELP_TEXT)
            return
        payload = {
            "model": self.settings.venice_model,
            "messages": [
                {"role": "system", "content": VENICE_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "max_tokens": 300,
        }
        headers = {"Authorization": f"Bearer {self.settings.venice_api_key}"}
        try:
            resp = await self.venice.post(
                f"{self.settings.venice_api_base}/chat/completions", json=payload, headers=headers
            )
            resp.raise_for_status()
            reply = resp.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            reply = f"Venice API error ({exc.__class__.__name__}). Slash commands still work."
        await self.send_message(chat_id, reply)

    # ------------------------------------------------------------------ polling

    async def poll_once(self) -> int:
        """Fetch one batch of updates (long poll) and process them. Returns the batch size."""
        resp = await self.tg.get(
            f"{self.api}/getUpdates",
            params={"offset": self.offset, "timeout": 25, "allowed_updates": '["message"]'},
        )
        if resp.status_code == 401:
            raise RuntimeError("Telegram rejected TELEGRAM_BOT_TOKEN (401). Check the token.")
        if resp.status_code == 409:
            raise RuntimeError("Another bot instance (or a webhook) is consuming this token (409).")
        resp.raise_for_status()
        updates = resp.json().get("result", [])
        for upd in updates:
            self.offset = max(self.offset, int(upd["update_id"]) + 1)
            await self.handle_update(upd)
        return len(updates)

    async def run(self) -> None:
        if not self.token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Create a bot with @BotFather.")
        if not self.allowed:
            logger.warning(
                "TELEGRAM_ALLOWED_USERS is empty: every command will be refused. "
                "Message @userinfobot to get your numeric id."
            )
        if not await self.wait_for_gateway():
            logger.warning("Gateway %s not reachable yet; commands will fail until it is up.",
                           self.gateway_url)
        logger.info("Telegram bot polling (gateway %s, %d operator(s)).",
                    self.gateway_url, len(self.allowed))
        backoff = 1.0
        while True:
            try:
                await self.poll_once()
                backoff = 1.0
            except RuntimeError:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("Telegram poll error (%s); retrying in %.0fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def aclose(self) -> None:
        for client in (self.tg, self.gw, self.venice):
            await client.aclose()


def _state(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("state", resp.status_code))
    except ValueError:
        return str(resp.status_code)


async def run_bot(settings: Settings | None = None, gateway_url: str | None = None) -> None:
    bot = TelegramBot(settings=settings, gateway_url=gateway_url)
    try:
        await bot.run()
    finally:
        await bot.aclose()


def main() -> None:
    """`dji-telegram`: run the bot against an already-running dji-station."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        pass
    except RuntimeError as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
