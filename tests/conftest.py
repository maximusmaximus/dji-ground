"""Pytest configuration and shared test fixtures."""

import pytest

from dji_ground.authority import Authority
from dji_ground.bridge.fake import FakeBridge
from dji_ground.config import Settings
from dji_ground.db import SessionDB
from dji_ground.scene import FakeDetector, FakeVLMClient, ScenePipeline
from dji_ground.triggers import TriggerEngine


@pytest.fixture
def test_settings(tmp_path):
    """Return test settings with temporary database and geofence."""
    db_file = str(tmp_path / "test_session.sqlite")
    geofence_file = "fixtures/geofence_sample.json"
    return Settings(
        bridge_mode="fake",
        sqlite_db_path=db_file,
        outdoor_geofence_file=geofence_file,
        indoor_max_speed=1.0,
        outdoor_max_speed=3.0,
        watchdog_timeout_ms=500,
        video_stale_threshold_ms=1000,
        stick_loop_freq_hz=20,
        token_ttl_seconds=10,
    )


@pytest.fixture
def fake_bridge():
    """Return an unstarted fake bridge."""
    return FakeBridge()


@pytest.fixture
def session_db(test_settings):
    """Return temporary SQLite session DB."""
    return SessionDB(test_settings.sqlite_db_path)


@pytest.fixture
def scene_pipeline():
    """Return scene pipeline with deterministic fake detector and VLM."""
    return ScenePipeline(detector=FakeDetector(), vlm_client=FakeVLMClient())


@pytest.fixture
def trigger_engine(session_db):
    """Return trigger engine connected to session DB."""
    return TriggerEngine(session_db)


@pytest.fixture
async def running_authority(fake_bridge, test_settings):
    """Return started authority and fake bridge with cleanup."""
    await fake_bridge.connect()
    authority = Authority(fake_bridge, test_settings)
    await authority.start()
    yield authority
    await authority.stop()
    await fake_bridge.disconnect()
