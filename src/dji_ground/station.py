"""`dji-station`: one command that runs the whole ground station.

Starts the bridge, video pipeline, flight authority, web UI, REST/WebSocket gateway and the
MCP endpoint (http://localhost:PORT/mcp) in ONE process, so Hermes, the browser and Telegram all
share a single flight authority. Optionally runs the Telegram bot in the same event loop.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import threading
import webbrowser

from . import __version__
from .config import get_settings
from .doctor import Check, has_failures, render, run_checks

logger = logging.getLogger("dji_ground.station")


def build_parser() -> argparse.ArgumentParser:
    s = get_settings()
    p = argparse.ArgumentParser(
        prog="dji-station",
        description="DJI ground station: web UI + REST + MCP (/mcp) + optional Telegram bot.",
    )
    p.add_argument("--port", type=int, default=s.gateway_port, help=f"Port (default {s.gateway_port})")
    p.add_argument("--host", default=s.gateway_host, help=f"Bind host (default {s.gateway_host})")
    p.add_argument("--enable-3d", "--enable-3d-modeling", dest="enable_3d", action="store_true",
                   help="Enable the live 3D scanner (also DJI_ENABLE_3D_MODELING=true)")
    p.add_argument("--opendji", action="store_true",
                   help="Use the real OpenDJI phone bridge instead of the simulator")
    p.add_argument("--telegram", action="store_true",
                   help="Also run the Telegram bot (needs TELEGRAM_BOT_TOKEN + TELEGRAM_ALLOWED_USERS)")
    p.add_argument("--no-browser", action="store_true", help="Do not open the web UI automatically")
    p.add_argument("--check", action="store_true",
                   help="Only run the readiness checks and exit (non-zero on failure)")
    p.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    p.add_argument("--version", action="version", version=f"dji-ground {__version__}")
    return p


def apply_overrides(args: argparse.Namespace) -> None:
    """Push CLI flags into the shared Settings singleton before the gateway is imported."""
    s = get_settings()
    if args.enable_3d:
        s.enable_3d_modeling = True
        os.environ["DJI_ENABLE_3D_MODELING"] = "true"
    if args.opendji:
        s.bridge_mode = "opendji"
        os.environ["DJI_BRIDGE_MODE"] = "opendji"
    s.gateway_port = args.port
    s.gateway_host = args.host
    # The in-process Telegram bot talks to this exact server.
    if args.telegram:
        s.gateway_url = f"http://127.0.0.1:{args.port}"


def banner(args: argparse.Namespace, checks: list[Check]) -> str:
    s = get_settings()
    url = f"http://localhost:{args.port}"
    warn = [c for c in checks if c.status != "OK"]
    lines = [
        "=" * 72,
        f" dji-ground {__version__} - flight authority, 3D scanner, Hermes MCP gateway",
        "=" * 72,
        f"  Web UI ............ {url}",
        f"  MCP (Hermes) ...... {url}/mcp      (streamable HTTP)",
        f"  REST health ....... {url}/api/health",
        f"  Video MJPEG ....... {url}/video/mjpeg",
        f"  Bridge ............ {s.bridge_mode}"
        + (f" @ {s.bridge_host}:{s.telemetry_port}-{s.command_port}" if s.bridge_mode == "opendji" else " (simulator)"),
        f"  3D scanner ........ {'ON' if s.enable_3d_modeling else 'off (use --enable-3d)'}",
        f"  Scene VLM ......... {'Venice ' + s.venice_vision_model if s.venice_configured else 'offline stub (set VENICE_API_KEY)'}",
        f"  Telegram bot ...... {'ON' if args.telegram else 'off (use --telegram)'}",
        f"  Safety ............ watchdog {s.watchdog_timeout_ms} ms, stale video {s.video_stale_threshold_ms} ms,"
        f" indoor {s.indoor_max_speed} m/s, outdoor {s.outdoor_max_speed} m/s",
    ]
    if warn:
        lines.append("  Warnings:")
        for c in warn:
            lines.append(f"    - {c.name}: {c.detail}" + (f"  -> {c.fix}" if c.fix else ""))
    lines += ["  Press Ctrl+C to stop (sticks are zeroed on shutdown).", "=" * 72]
    return "\n".join(lines)


async def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    from .gateway import app  # imported after overrides so Settings are final

    config = uvicorn.Config(app, host=args.host, port=args.port, log_level=args.log_level)
    server = uvicorn.Server(config)
    tasks = [asyncio.create_task(server.serve(), name="gateway")]
    if args.telegram:
        from .telegram_bot import run_bot

        tasks.append(asyncio.create_task(run_bot(), name="telegram"))

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for t in done:
        if t.get_name() == "telegram" and t.exception() is not None:
            logger.error("Telegram bot stopped: %s (gateway keeps running)", t.exception())
            await asyncio.wait(pending)
            return
    server.should_exit = True
    for t in pending:
        if t.get_name() == "telegram":
            t.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    apply_overrides(args)
    checks = run_checks(get_settings(), port=args.port, telegram=args.telegram)

    if args.check:
        print(f"dji-ground {__version__} readiness check\n")
        print(render(checks))
        failed = has_failures(checks)
        print("\nResult: " + ("NOT READY (fix the FAIL items above)" if failed else "READY"))
        return 1 if failed else 0

    if has_failures(checks):
        print("dji-station cannot start:\n", file=sys.stderr)
        print(render([c for c in checks if c.status == "FAIL"]), file=sys.stderr)
        print("\nRun `dji-station --check` for the full report.", file=sys.stderr)
        return 1

    print(banner(args, checks), flush=True)

    if not args.no_browser:
        url = f"http://localhost:{args.port}"
        # Open once the server has had a moment to bind.
        threading.Timer(1.5, lambda: _open_browser(url)).start()

    try:
        asyncio.run(_serve(args))
    except KeyboardInterrupt:
        pass
    return 0


def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:  # headless boxes have no browser; that's fine
        pass


def cli() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    cli()
