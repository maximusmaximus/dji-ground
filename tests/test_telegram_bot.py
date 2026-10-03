"""Telegram bot: fail-closed auth, stop always works, /scan never arms, polling advances offset."""

import json

import httpx
import pytest

from dji_ground import gateway, mcp_server
from dji_ground.config import Settings
from dji_ground.telegram_bot import TelegramBot


class Recorder:
    """MockTransport handler that records requests and returns canned responses."""

    def __init__(self, routes=None):
        self.calls: list[httpx.Request] = []
        self.routes = routes or {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        for key, resp in self.routes.items():
            method, path = key
            if request.method == method and request.url.path.endswith(path):
                return resp(request) if callable(resp) else resp
        return httpx.Response(200, json={"ok": True, "result": []})

    def paths(self):
        return [r.url.path for r in self.calls]

    def texts(self):
        out = []
        for r in self.calls:
            if r.url.path.endswith("/sendMessage"):
                out.append(json.loads(r.content)["text"])
        return out


def _bot(tg: Recorder, gw: Recorder, allowed="42", venice: Recorder | None = None, **kw):
    settings = Settings(
        _env_file=None,
        telegram_bot_token="123:abc",
        telegram_allowed_users=allowed,
        **kw,
    )
    return TelegramBot(
        settings=settings,
        gateway_url="http://gw",
        telegram_client=httpx.AsyncClient(transport=httpx.MockTransport(tg)),
        gateway_client=httpx.AsyncClient(transport=httpx.MockTransport(gw)),
        venice_client=httpx.AsyncClient(transport=httpx.MockTransport(venice or Recorder())),
    )


async def test_empty_allowlist_refuses_everyone():
    tg, gw = Recorder(), Recorder()
    bot = _bot(tg, gw, allowed="")
    await bot.handle_command(1, 42, "/stop")
    assert gw.calls == []  # nothing reached the flight authority
    assert "Unauthorized" in tg.texts()[0] and "TELEGRAM_ALLOWED_USERS" in tg.texts()[0]


async def test_unknown_user_refused():
    tg, gw = Recorder(), Recorder()
    bot = _bot(tg, gw, allowed="42")
    await bot.handle_command(1, 99, "/status")
    assert gw.calls == []
    assert "your id: 99" in tg.texts()[0]


@pytest.mark.parametrize("text", ["/stop", "stop", "ABORT", "halt", "/stop@MyDroneBot"])
async def test_stop_variants_hit_emergency_stop(text):
    tg = Recorder()
    gw = Recorder({("POST", "/api/emergency_stop"): httpx.Response(200, json={"state": "EMERGENCY_HOVER"})})
    bot = _bot(tg, gw)
    await bot.handle_command(1, 42, text)
    assert gw.paths() == ["/api/emergency_stop"]
    assert "EMERGENCY_HOVER" in tg.texts()[0]


async def test_scan_only_proposes_and_never_mints_a_token():
    tg = Recorder()
    gw = Recorder({
        ("POST", "/api/scan_target"): httpx.Response(
            200, json={"status": "requires_arm", "matched_bbox": [0.1, 0.1, 0.3, 0.3]}
        )
    })
    bot = _bot(tg, gw)
    await bot.handle_command(1, 42, "/scan red chair")
    assert "/api/arm_motion" not in gw.paths()
    body = json.loads(gw.calls[0].content)
    assert body == {"target_label": "red chair"}
    assert "/confirm_scan red chair" in tg.texts()[0]


async def test_confirm_scan_mints_orbit_token_then_scans():
    tg = Recorder()
    gw = Recorder({
        ("POST", "/api/arm_motion"): httpx.Response(200, json={"token": "tok-1", "mode": "orbit"}),
        ("POST", "/api/scan_target"): httpx.Response(
            200, json={"status": "scanning_target_initiated", "session_id": "s1", "radius_m": 3.0}
        ),
    })
    bot = _bot(tg, gw)
    await bot.handle_command(1, 42, "/confirm_scan chair")
    assert gw.paths() == ["/api/arm_motion", "/api/scan_target"]
    assert json.loads(gw.calls[0].content) == {"mode": "orbit"}
    assert json.loads(gw.calls[1].content)["confirm_token"] == "tok-1"
    assert "s1" in tg.texts()[0]


async def test_confirm_scan_refusal_is_explained():
    tg = Recorder()
    gw = Recorder({
        ("POST", "/api/arm_motion"): httpx.Response(200, json={"token": "t"}),
        ("POST", "/api/scan_target"): httpx.Response(
            409, json={"detail": "Aircraft must be ARMED."}
        ),
    })
    bot = _bot(tg, gw)
    await bot.handle_command(1, 42, "/confirm_scan chair")
    assert "Scan refused" in tg.texts()[0] and "ARMED" in tg.texts()[0]


async def test_free_text_goes_to_venice_and_cannot_fly():
    tg, gw = Recorder(), Recorder()
    venice = Recorder({
        ("POST", "/chat/completions"): httpx.Response(
            200, json={"choices": [{"message": {"content": "Use /scan chair"}}]}
        )
    })
    bot = _bot(tg, gw, venice=venice, venice_api_key="vk")
    await bot.handle_command(1, 42, "take off and fly to the tree")
    assert gw.calls == []  # chat never touches the gateway
    assert tg.texts() == ["Use /scan chair"]
    assert venice.calls[0].headers["authorization"] == "Bearer vk"


async def test_markdown_failure_falls_back_to_plain_text():
    calls = []

    def tg_handler(request):
        calls.append(json.loads(request.content))
        if "parse_mode" in calls[-1]:
            return httpx.Response(400, json={"ok": False})
        return httpx.Response(200, json={"ok": True})

    bot = _bot(Recorder(), Recorder())
    bot.tg = httpx.AsyncClient(transport=httpx.MockTransport(tg_handler))
    await bot.send_message(1, "bad_markdown_*")
    assert len(calls) == 2 and "parse_mode" not in calls[1]


async def test_download_rejects_path_traversal(tmp_path):
    tg, gw = Recorder(), Recorder()
    (tmp_path / "models").mkdir()
    bot = _bot(tg, gw, model_3d_export_dir=str(tmp_path / "models"))
    (tmp_path / "secret.obj").write_text("x")
    await bot.handle_command(1, 42, "/download ../secret")
    assert not any(p.endswith("/sendDocument") for p in tg.paths())
    assert "Invalid" in tg.texts()[0]


async def test_download_sends_existing_model(tmp_path):
    tg, gw = Recorder(), Recorder()
    d = tmp_path / "models"
    d.mkdir()
    (d / "abc.ply").write_bytes(b"ply\n")
    bot = _bot(tg, gw, model_3d_export_dir=str(d))
    await bot.handle_command(1, 42, "/download abc")
    assert any(p.endswith("/sendDocument") for p in tg.paths())


async def test_poll_once_advances_offset_and_dispatches():
    updates = {
        "ok": True,
        "result": [
            {"update_id": 10, "message": {"chat": {"id": 1}, "from": {"id": 42}, "text": "/help"}},
            {"update_id": 11, "message": {"chat": {"id": 1}, "from": {"id": 42}, "text": "/start"}},
        ],
    }
    tg = Recorder({("GET", "/getUpdates"): httpx.Response(200, json=updates)})
    bot = _bot(tg, Recorder())
    assert await bot.poll_once() == 2
    assert bot.offset == 12
    assert len(tg.texts()) == 2


async def test_poll_once_bad_token_is_a_clear_error():
    tg = Recorder({("GET", "/getUpdates"): httpx.Response(401, json={"ok": False})})
    bot = _bot(tg, Recorder())
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        await bot.poll_once()


async def test_gateway_down_is_reported_not_crashing():
    def down(request):
        raise httpx.ConnectError("refused")

    tg = Recorder()
    bot = _bot(tg, Recorder())
    bot.gw = httpx.AsyncClient(transport=httpx.MockTransport(down))
    await bot.handle_update({"message": {"chat": {"id": 1}, "from": {"id": 42}, "text": "/status"}})
    assert "Gateway unreachable" in tg.texts()[0]


async def test_status_against_real_gateway():
    """End-to-end through the real FastAPI gateway (in-process ASGI)."""
    mcp_server.init_subsystems()
    tg = Recorder()
    bot = _bot(tg, Recorder())
    bot.gw = httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app))
    bot.gateway_url = "http://gw"
    await bot.handle_command(1, 42, "/status")
    text = tg.texts()[0]
    assert "State:" in text and "Battery:" in text
