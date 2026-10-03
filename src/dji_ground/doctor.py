"""`dji-station --check`: verify a machine is ready to run dji-ground, with fix hints."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import FIXTURES_DIR, PROJECT_ROOT, WEB_DIST_DIR, Settings

OK, WARN, FAIL = "OK", "WARN", "FAIL"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


def _port_free(host: str, port: int) -> bool:
    bind_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    # Windows lets 127.0.0.1 bind beside a 0.0.0.0 listener, so a live connect is the
    # reliable "someone is already serving here" signal on every OS.
    if _tcp_open(bind_host, port, timeout=0.3):
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # On Windows SO_REUSEADDR lets you bind over a live listener, hiding conflicts.
        if os.name != "nt":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((bind_host, port))
            return True
        except OSError:
            return False


def _tcp_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _point_in_polygon(x: float, y: float, poly: list[list[float]]) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1:
            inside = not inside
    return inside


def _edge_distance(x: float, y: float, poly: list[list[float]]) -> float:
    """Shortest distance from (x, y) to any polygon edge."""
    best = float("inf")
    n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / L2))
        px, py = x1 + t * dx, y1 + t * dy
        best = min(best, ((x - px) ** 2 + (y - py) ** 2) ** 0.5)
    return best


TAKEOFF_MARGIN_M = 1.0


def run_checks(settings: Settings, port: int | None = None, telegram: bool = False) -> list[Check]:
    """Collect environment checks. Pure apart from filesystem/socket probes.

    `telegram=True` means the operator asked to run the bot, so a missing token or
    empty allowlist becomes a hard failure instead of a warning.
    """
    checks: list[Check] = []
    port = port or settings.gateway_port

    # Python
    py_ok = sys.version_info >= (3, 12)
    checks.append(
        Check(
            "Python >= 3.12",
            OK if py_ok else FAIL,
            sys.version.split()[0],
            "" if py_ok else "Install Python 3.12+ (uv python install 3.12).",
        )
    )

    # .env
    env_path = PROJECT_ROOT / ".env"
    checks.append(
        Check(
            ".env file",
            OK if env_path.exists() else WARN,
            str(env_path) if env_path.exists() else "not found (using defaults)",
            "" if env_path.exists() else "cp .env.example .env  (then edit keys)",
        )
    )

    # Bridge
    if settings.bridge_mode == "fake":
        has_video = (FIXTURES_DIR / "sample_h264_stream.h264").exists()
        checks.append(
            Check(
                "Bridge",
                OK if has_video else WARN,
                "fake simulator" + ("" if has_video else " (fixture video missing)"),
                "" if has_video else "Restore fixtures/sample_h264_stream.h264 from git.",
            )
        )
    else:
        ports = [settings.telemetry_port, settings.video_port, settings.command_port]
        open_ports = [p for p in ports if _tcp_open(settings.bridge_host, p)]
        all_open = len(open_ports) == len(ports)
        checks.append(
            Check(
                "OpenDJI bridge sockets",
                OK if all_open else FAIL,
                f"{settings.bridge_host} ports open: {open_ports or 'none'} of {ports}",
                ""
                if all_open
                else "Start OpenDJI on the phone, then: "
                + "; ".join(f"adb forward tcp:{p} tcp:{p}" for p in ports),
            )
        )
        has_adb = shutil.which("adb") is not None
        checks.append(
            Check(
                "adb on PATH",
                OK if has_adb else WARN,
                "found" if has_adb else "not found (OSD screenshots + port forwarding need it)",
                "" if has_adb else "Install Android platform-tools and add adb to PATH.",
            )
        )

    # Geofence
    gf = Path(settings.outdoor_geofence_file)
    try:
        poly = json.loads(gf.read_text(encoding="utf-8")).get("local_polygon", [])
        if len(poly) < 3:
            checks.append(
                Check("Geofence", FAIL, f"{gf}: needs >= 3 points", "Add local_polygon points.")
            )
        elif (
            not _point_in_polygon(0.0, 0.0, poly)
            or _edge_distance(0.0, 0.0, poly) < TAKEOFF_MARGIN_M
        ):
            checks.append(
                Check(
                    "Geofence",
                    WARN,
                    f"{gf.name}: takeoff point (0,0) is on, near (<{TAKEOFF_MARGIN_M:g} m) "
                    "or outside the fence",
                    "Centre local_polygon on the takeoff point, e.g. config/geofence_default.json.",
                )
            )
        else:
            checks.append(Check("Geofence", OK, f"{gf.name} ({len(poly)} points)"))
    except (OSError, ValueError) as exc:
        checks.append(
            Check(
                "Geofence",
                WARN,
                f"{gf} unreadable ({exc.__class__.__name__}); falling back to indoor box",
                "Set DJI_GEOFENCE_FILE to a valid JSON file with local_polygon.",
            )
        )

    # Venice
    checks.append(
        Check(
            "Venice API key",
            OK if settings.venice_configured else WARN,
            f"set (vision model: {settings.venice_vision_model})"
            if settings.venice_configured
            else "not set: scene captions use the offline stub",
            "" if settings.venice_configured else "Set VENICE_API_KEY in .env.",
        )
    )

    # Telegram
    if settings.telegram_bot_token:
        has_users = bool(settings.allowed_telegram_ids)
        bad = FAIL if telegram else WARN
        checks.append(
            Check(
                "Telegram allowlist",
                OK if has_users else bad,
                f"{len(settings.allowed_telegram_ids)} operator id(s)"
                if has_users
                else "TELEGRAM_ALLOWED_USERS is empty: the bot will refuse every command",
                "" if has_users else "Get your id from @userinfobot and set TELEGRAM_ALLOWED_USERS.",
            )
        )
    else:
        checks.append(
            Check(
                "Telegram bot",
                FAIL if telegram else WARN,
                "TELEGRAM_BOT_TOKEN not set (bot disabled)",
                "Create a bot with @BotFather and set TELEGRAM_BOT_TOKEN.",
            )
        )

    # Web UI
    has_ui = (WEB_DIST_DIR / "index.html").exists()
    checks.append(
        Check(
            "Web UI bundle",
            OK if has_ui else WARN,
            str(WEB_DIST_DIR) if has_ui else "web/dist/index.html missing",
            "" if has_ui else "cd web && npm install && npm run build",
        )
    )

    # 3D export dir
    export_dir = Path(settings.model_3d_export_dir)
    try:
        export_dir.mkdir(parents=True, exist_ok=True)
        writable = os.access(export_dir, os.W_OK)
    except OSError:
        writable = False
    checks.append(
        Check(
            "3D export directory",
            OK if writable else FAIL,
            f"{export_dir} ({'3D on' if settings.enable_3d_modeling else '3D off'})",
            "" if writable else "Set DJI_MODEL_3D_EXPORT_DIR to a writable folder.",
        )
    )

    # YOLO
    if settings.enable_yolo:
        has_yolo = importlib.util.find_spec("ultralytics") is not None
        checks.append(
            Check(
                "YOLO detector",
                OK if has_yolo else FAIL,
                "ultralytics installed" if has_yolo else "DJI_ENABLE_YOLO=true but ultralytics missing",
                "" if has_yolo else 'uv pip install -e ".[vision]"',
            )
        )

    # Gateway port
    free = _port_free(settings.gateway_host, port)
    checks.append(
        Check(
            f"Port {port}",
            OK if free else FAIL,
            "free" if free else "already in use (another dji-station running?)",
            "" if free else f"Stop the other process or run: dji-station --port {port + 1}",
        )
    )
    return checks


def render(checks: list[Check]) -> str:
    """ASCII-only table (safe on legacy Windows consoles)."""
    width = max(len(c.name) for c in checks)
    lines = []
    for c in checks:
        lines.append(f"  [{c.status:<4}] {c.name.ljust(width)}  {c.detail}")
        if c.fix and c.status != OK:
            lines.append(f"  {'':6} {'':{width}}  -> {c.fix}")
    return "\n".join(lines)


def has_failures(checks: list[Check]) -> bool:
    return any(c.status == FAIL for c in checks)
