"""Telegram bot operator bridge with Venice AI inference and Hermes MCP tools."""

import asyncio
import io
import json
import os
import sys
import httpx

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_ALLOWED_USERS = [
    u.strip() for u in os.getenv("TELEGRAM_ALLOWED_USERS", "").split(",") if u.strip()
]
GATEWAY_URL = os.getenv("DJI_GATEWAY_URL", "http://localhost:8000")
VENICE_API_KEY = os.getenv("VENICE_API_KEY")
VENICE_API_BASE = os.getenv("VENICE_API_BASE", "https://api.venice.ai/api/v1")
VENICE_MODEL = os.getenv("VENICE_MODEL", "llama-3.3-70b")


def check_auth(user_id: int) -> bool:
    """Ensure caller is whitelisted in TELEGRAM_ALLOWED_USERS."""
    if not TELEGRAM_ALLOWED_USERS:
        return True  # Open if no whitelist configured
    return str(user_id) in TELEGRAM_ALLOWED_USERS


async def send_telegram_msg(chat_id: int, text: str) -> None:
    """Send text message to Telegram chat."""
    if not TELEGRAM_BOT_TOKEN:
        print(f"[Telegram Mock] Chat {chat_id}: {text}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})


async def send_telegram_photo(chat_id: int, image_bytes: bytes, caption: str = "") -> None:
    """Send JPEG photo to Telegram chat."""
    if not TELEGRAM_BOT_TOKEN:
        print(f"[Telegram Mock Photo] Chat {chat_id}: {len(image_bytes)} bytes photo, caption: {caption}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    files = {"photo": ("snapshot.jpg", image_bytes, "image/jpeg")}
    data = {"chat_id": chat_id, "caption": caption}
    async with httpx.AsyncClient() as client:
        await client.post(url, data=data, files=files)


async def send_telegram_doc(chat_id: int, file_path: str, caption: str = "") -> None:
    """Send 3D model document to Telegram chat."""
    if not TELEGRAM_BOT_TOKEN:
        print(f"[Telegram Mock Doc] Chat {chat_id}: {file_path}, caption: {caption}")
        return
    if not os.path.exists(file_path):
        await send_telegram_msg(chat_id, f"File {file_path} not found.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    filename = os.path.basename(file_path)
    with open(file_path, "rb") as f:
        file_bytes = f.read()
    files = {"document": (filename, file_bytes, "application/octet-stream")}
    data = {"chat_id": chat_id, "caption": caption}
    async with httpx.AsyncClient() as client:
        await client.post(url, data=data, files=files)


async def handle_command(chat_id: int, user_id: int, text: str) -> None:
    """Process incoming operator command."""
    if not check_auth(user_id):
        await send_telegram_msg(chat_id, "⛔ Unauthorized user ID. Command refused.")
        return

    cmd = text.strip()

    # Immediate emergency stop command (Bypasses LLM reasoning)
    if cmd.lower() in ("/stop", "stop", "abort", "halt"):
        async with httpx.AsyncClient() as client:
            res = await client.post(f"{GATEWAY_URL}/api/emergency_stop")
            await send_telegram_msg(chat_id, f"🛑 *EMERGENCY STOP TRIGGERED*: {res.json()}")
            return

    # Status check
    if cmd.startswith("/status"):
        async with httpx.AsyncClient() as client:
            res = await client.get(f"{GATEWAY_URL}/api/status")
            d = res.json()
            msg = (
                f"📡 *Flight Status*\n"
                f"• State: `{d['state']}` (Mode: `{d['mode']}`)\n"
                f"• Battery: `{d['battery_percent']}%`\n"
                f"• Altitude: `{d['altitude_agl']} m`\n"
                f"• Video Fresh: `{d['video_fresh']}` ({d['video_age_ms']} ms)\n"
                f"• Obstacle: `{d['obstacle_detected']}`"
            )
            await send_telegram_msg(chat_id, msg)
            return

    # Preflight check
    if cmd.startswith("/preflight"):
        async with httpx.AsyncClient() as client:
            res = await client.get(f"{GATEWAY_URL}/api/preflight")
            d = res.json()
            status_emoji = "✅" if d["passed"] else "❌"
            await send_telegram_msg(chat_id, f"{status_emoji} *Preflight Result*: `{'PASSED' if d['passed'] else 'FAILED'}`\nChecks: `{json.dumps(d['checks'])}`")
            return

    # Capture photo
    if cmd.startswith("/photo"):
        async with httpx.AsyncClient() as client:
            res = await client.get(f"{GATEWAY_URL}/api/get_latest_frame")
            d = res.json()
            if "image_b64" in d:
                import base64

                img_bytes = base64.b64decode(d["image_b64"])
                await send_telegram_photo(chat_id, img_bytes, caption=f"📸 Drone FPV Frame #{d.get('frame_id')} (Age: {d.get('age_ms')}ms)")
            else:
                await send_telegram_msg(chat_id, "⚠️ Camera frame unavailable.")
            return

    # Describe scene
    if cmd.startswith("/describe"):
        async with httpx.AsyncClient() as client:
            res = await client.get(f"{GATEWAY_URL}/api/describe_scene")
            d = res.json()
            objs = ", ".join([o["label"] for o in d.get("objects", [])]) or "None"
            msg = f"👁️ *Scene Caption*:\n{d['caption']}\n\n*Objects*: {objs}"

            frame_res = await client.get(f"{GATEWAY_URL}/api/get_latest_frame")
            frame_data = frame_res.json()
            if "image_b64" in frame_data:
                import base64

                img_bytes = base64.b64decode(frame_data["image_b64"])
                await send_telegram_photo(chat_id, img_bytes, caption=msg)
            else:
                await send_telegram_msg(chat_id, msg)
            return

    # 3D scan command: /scan <target_item>
    if cmd.startswith("/scan"):
        parts = cmd.split(" ", 1)
        target = parts[1] if len(parts) > 1 else "target"
        async with httpx.AsyncClient() as client:
            res = await client.post(f"{GATEWAY_URL}/api/3d_scan/start", json={"target_label": target, "resolution": "high"})
            await send_telegram_msg(chat_id, f"🛰️ *3D Scan Initiated* for `{target}`.\nSession: `{res.json().get('session_id')}`\nOrbiting target to accumulate point cloud.")
            return

    # Natural Language via Venice AI
    if VENICE_API_KEY:
        # Ask Venice LLM with system prompt
        system_prompt = (
            "You are a DJI drone copilot on Telegram. You help operators check status, "
            "trigger safe 3D scans, and describe scenes. The human is PIC. Never suggest reckless flight."
        )
        payload = {
            "model": VENICE_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            "max_tokens": 200,
        }
        headers = {"Authorization": f"Bearer {VENICE_API_KEY}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(f"{VENICE_API_BASE}/chat/completions", json=payload, headers=headers)
                reply = res.json()["choices"][0]["message"]["content"]
                await send_telegram_msg(chat_id, reply)
                return
        except Exception as e:
            await send_telegram_msg(chat_id, f"⚠️ Venice API error: {e}")
            return

    await send_telegram_msg(
        chat_id,
        "Available commands:\n• `/status`\n• `/preflight`\n• `/describe`\n• `/scan <item>`\n• `/stop` (emergency)",
    )


async def main() -> None:
    print("Telegram Bot Bridge running. Awaiting messages...")
    # Polling loop or webhook implementation
    if not TELEGRAM_BOT_TOKEN:
        print("Note: TELEGRAM_BOT_TOKEN not configured. Running in mock console mode.")
        return


if __name__ == "__main__":
    asyncio.run(main())
