"""`dji-station --check` and the doctor checks give actionable, correct verdicts."""

import json
import socket

from dji_ground import station
from dji_ground.config import Settings
from dji_ground.doctor import FAIL, OK, WARN, has_failures, render, run_checks


def _settings(tmp_path, **kw):
    base = dict(
        _env_file=None,
        sqlite_db_path=str(tmp_path / "s.sqlite"),
        model_3d_export_dir=str(tmp_path / "models"),
        outdoor_geofence_file="config/geofence_default.json",
    )
    base.update(kw)
    return Settings(**base)


def _by_name(checks, prefix):
    return next(c for c in checks if c.name.startswith(prefix))


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_default_setup_has_no_failures(tmp_path):
    checks = run_checks(_settings(tmp_path), port=_free_port())
    assert not has_failures(checks), render(checks)
    assert _by_name(checks, "Geofence").status == OK
    assert _by_name(checks, "Bridge").status == OK


def test_geofence_with_takeoff_on_corner_warns(tmp_path):
    checks = run_checks(
        _settings(tmp_path, outdoor_geofence_file="fixtures/geofence_sample.json"),
        port=_free_port(),
    )
    gf = _by_name(checks, "Geofence")
    assert gf.status == WARN and "takeoff" in gf.detail


def test_geofence_too_few_points_fails(tmp_path):
    bad = tmp_path / "fence.json"
    bad.write_text(json.dumps({"local_polygon": [[0, 0], [1, 1]]}))
    checks = run_checks(_settings(tmp_path, outdoor_geofence_file=str(bad)), port=_free_port())
    assert _by_name(checks, "Geofence").status == FAIL


def test_telegram_requested_without_allowlist_fails_closed(tmp_path):
    s = _settings(tmp_path, telegram_bot_token="1:abc", telegram_allowed_users="")
    assert _by_name(run_checks(s, port=_free_port()), "Telegram").status == WARN
    tg = _by_name(run_checks(s, port=_free_port(), telegram=True), "Telegram")
    assert tg.status == FAIL and "@userinfobot" in tg.fix


def test_telegram_requested_without_token_fails(tmp_path):
    s = _settings(tmp_path, telegram_bot_token=None)
    assert _by_name(run_checks(s, port=_free_port(), telegram=True), "Telegram").status == FAIL


def test_opendji_without_bridge_fails_with_adb_hint(tmp_path):
    s = _settings(tmp_path, bridge_mode="opendji", telemetry_port=_free_port(),
                  video_port=_free_port(), command_port=_free_port())
    check = _by_name(run_checks(s, port=_free_port()), "OpenDJI")
    assert check.status == FAIL and "adb forward" in check.fix


def test_busy_port_is_detected(tmp_path):
    with socket.socket() as srv:
        srv.bind(("0.0.0.0", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        check = _by_name(run_checks(_settings(tmp_path), port=port), f"Port {port}")
        assert check.status == FAIL and f"--port {port + 1}" in check.fix


def test_render_is_ascii(tmp_path):
    out = render(run_checks(_settings(tmp_path), port=_free_port()))
    out.encode("ascii")  # must not raise on legacy Windows consoles


def test_station_check_exit_codes(tmp_path, capsys):
    port = _free_port()
    assert station.main(["--check", "--port", str(port)]) == 0
    assert "READY" in capsys.readouterr().out
    with socket.socket() as srv:
        srv.bind(("0.0.0.0", 0))
        srv.listen(1)
        busy = srv.getsockname()[1]
        assert station.main(["--check", "--port", str(busy)]) == 1
    assert "NOT READY" in capsys.readouterr().out


def test_station_refuses_to_start_on_busy_port(capsys):
    with socket.socket() as srv:
        srv.bind(("0.0.0.0", 0))
        srv.listen(1)
        busy = srv.getsockname()[1]
        assert station.main(["--no-browser", "--port", str(busy)]) == 1
    assert "cannot start" in capsys.readouterr().err


def test_banner_shows_mcp_url(tmp_path):
    args = station.build_parser().parse_args(["--port", "8123"])
    text = station.banner(args, [])
    assert "http://localhost:8123/mcp" in text
    text.encode("ascii")
