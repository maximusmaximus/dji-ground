"""Back-compat shim. Prefer `uv run dji-telegram` or `uv run dji-station --telegram`."""

from dji_ground.telegram_bot import TelegramBot, main, run_bot  # noqa: F401

if __name__ == "__main__":
    main()
