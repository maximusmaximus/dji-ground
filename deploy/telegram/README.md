# Telegram Operator Bridge Setup

The Telegram operator bridge connects a Telegram chat with the `dji-ground` FastMCP authority and uses Venice AI for natural language command processing.

## Prerequisites
1. **Telegram Bot Token**: Create a bot via [@BotFather](https://t.me/BotFather) and copy the HTTP API token.
2. **Your Telegram User ID**: Find your numeric user ID using [@userinfobot](https://t.me/userinfobot) to set up the whitelist.
3. **Venice AI API Key**: Get an API key from [Venice AI](https://venice.ai).

## Setup
Add the variables to your `.env` file:
```bash
TELEGRAM_BOT_TOKEN="your_bot_token"
TELEGRAM_ALLOWED_USERS="123456789,987654321"  # Whitelist numeric user IDs
VENICE_API_KEY="your_venice_api_key"
VENICE_API_BASE="https://api.venice.ai/api/v1"
VENICE_MODEL="llama-3.3-70b"
```

## Running the Bot
Make sure the `dji-ground` gateway is running:
```bash
python -m dji_ground.gateway
```

Then in a second terminal:
```bash
python deploy/telegram/bot.py
```

## Operator Commands
- `/status`: Real-time flight status, battery, altitude, and video health.
- `/preflight`: Run automated sensor and safety check.
- `/describe`: Query camera viewport and receive visual scene caption and objects.
- `/scan <target>`: Trigger "Find item X and 3D model it" autonomous orbit scan.
- `/stop`: **Unconditional emergency stop**. Bypasses LLM reasoning and halts motion within <100ms.
- Any natural language message: Processed by Hermes + Venice AI.
