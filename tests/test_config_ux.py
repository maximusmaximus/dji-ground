"""Config UX: documented env names work, placeholders mean 'unset', paths are CWD-independent."""

import json
from pathlib import Path

from dji_ground.config import PROJECT_ROOT, Settings, resolve_path


def _clear(monkeypatch, *names):
    for n in names:
        monkeypatch.delenv(n, raising=False)


def test_unprefixed_venice_and_telegram_names_are_read(monkeypatch):
    monkeypatch.setenv("VENICE_API_KEY", "vk-123")
    monkeypatch.setenv("VENICE_VISION_MODEL", "some-vl-model")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1:abc")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", " 111, 222 ,")
    monkeypatch.setenv("INDOOR_ARM", "1")
    s = Settings(_env_file=None)
    assert s.venice_api_key == "vk-123"
    assert s.venice_configured
    assert s.venice_vision_model == "some-vl-model"
    assert s.telegram_bot_token == "1:abc"
    assert s.allowed_telegram_ids == {"111", "222"}
    assert s.indoor_arm == 1


def test_template_placeholders_mean_not_configured(monkeypatch):
    monkeypatch.setenv("VENICE_API_KEY", "your_venice_api_key_here")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "  ")
    s = Settings(_env_file=None)
    assert s.venice_api_key is None
    assert not s.venice_configured
    assert s.telegram_bot_token is None


def test_empty_allowlist_is_empty_set(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "")
    assert Settings(_env_file=None).allowed_telegram_ids == set()


def test_documented_geofence_env_name(monkeypatch):
    monkeypatch.setenv("DJI_GEOFENCE_FILE", "fixtures/geofence_sample.json")
    s = Settings(_env_file=None)
    assert Path(s.outdoor_geofence_file) == PROJECT_ROOT / "fixtures" / "geofence_sample.json"


def test_relative_paths_resolve_against_project_root(monkeypatch, tmp_path):
    _clear(monkeypatch, "DJI_SQLITE_DB_PATH", "DJI_MODEL_3D_EXPORT_DIR", "DJI_GEOFENCE_FILE")
    monkeypatch.chdir(tmp_path)  # simulate Hermes launching us from another directory
    s = Settings(_env_file=None)
    assert Path(s.sqlite_db_path).is_absolute()
    assert Path(s.sqlite_db_path).parent == PROJECT_ROOT / "data"
    assert Path(s.model_3d_export_dir) == PROJECT_ROOT / "data" / "models_3d"
    assert Path(s.outdoor_geofence_file).exists()


def test_absolute_paths_untouched(tmp_path):
    p = tmp_path / "x.sqlite"
    assert resolve_path(p) == str(p)
    assert Settings(_env_file=None, sqlite_db_path=str(p)).sqlite_db_path == str(p)


def test_default_vision_model_is_a_real_venice_vision_model(monkeypatch):
    _clear(monkeypatch, "VENICE_VISION_MODEL", "DJI_VENICE_VISION_MODEL")
    # Verified against https://api.venice.ai/api/v1/models (supportsVision=true).
    assert Settings(_env_file=None).venice_vision_model == "qwen3-vl-235b-a22b"


def test_default_geofence_contains_takeoff_point():
    from dji_ground.doctor import _point_in_polygon

    s = Settings(_env_file=None, outdoor_geofence_file="config/geofence_default.json")
    poly = json.loads(Path(s.outdoor_geofence_file).read_text())["local_polygon"]
    assert _point_in_polygon(0.0, 0.0, poly)
