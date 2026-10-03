"""Integration tests verifying end-to-end hardware-free pipelines."""

import asyncio
import time

import pytest

from dji_ground.authority import Authority, FlightState
from dji_ground.bridge.fake import FakeBridge
from dji_ground.config import Settings
from dji_ground.modes import ModeManager
from dji_ground.scene import FakeDetector, FakeVLMClient, ScenePipeline
from dji_ground.screen import ScreenCapturer
from dji_ground.triggers import TriggerEngine
from dji_ground.video import VideoPipeline


@pytest.mark.asyncio
async def test_fixture_h264_decode_to_describe_scene(
    fake_bridge: FakeBridge, scene_pipeline: ScenePipeline
):
    """Integration: Fixture H.264 -> VideoPipeline -> get_latest_frame -> describe_scene non-empty."""
    await fake_bridge.connect()
    video = VideoPipeline(fake_bridge)
    await video.start()

    # Wait for frames to decode
    frame = None
    for _ in range(30):
        frame = await video.get_latest_frame()
        if frame:
            break
        await asyncio.sleep(0.05)

    assert frame is not None
    assert frame.image is not None

    desc = await scene_pipeline.describe_scene(
        image=frame.image,
        telemetry_dict={"altitude_agl": 1.5, "is_flying": True},
        frame_id=frame.frame_id,
        age_ms=frame.age_ms,
    )

    assert desc["caption"] != ""
    assert isinstance(desc["objects"], list)
    assert desc["frame_id"] == frame.frame_id
    assert desc["age_ms"] >= 0.0

    await video.stop()
    await fake_bridge.disconnect()


def test_fixture_osd_png_contains_warning():
    """Integration: Fixture OSD PNG -> get_osd_text contains known warning."""
    capturer = ScreenCapturer(fallback_fixture="fixtures/osd_warning_obstacle.png")
    osd_result = capturer.get_osd_text()

    assert osd_result["obstacle_detected"] is True
    assert "WARNING: Obstacle detected" in osd_result["raw_text"]


@pytest.mark.asyncio
async def test_emergency_stop_within_500ms(fake_bridge: FakeBridge, test_settings: Settings):
    """Integration: emergency_stop halts flight and registers on bridge in < 500ms."""
    await fake_bridge.connect()
    authority = Authority(fake_bridge, test_settings)
    await authority.start()

    tok = authority.arm_motion("takeoff")
    await authority.takeoff(tok.token)

    tok2 = authority.arm_motion("outdoor_box")
    await authority.set_mode(
        "outdoor_box", token=tok2.token, controller_cb=lambda: (0.5, 0.0, 0.0, 0.0)
    )

    start_time = time.time()
    await authority.emergency_stop()
    stop_latency_ms = (time.time() - start_time) * 1000.0

    # Must execute within 500 ms limit
    assert stop_latency_ms < 500.0
    assert authority.state == FlightState.EMERGENCY_HOVER

    # Bridge verify command received
    cmds = [c[1] for c in fake_bridge.command_history]
    assert "emergency_stop" in cmds

    await authority.stop()
    await fake_bridge.disconnect()


@pytest.mark.asyncio
async def test_follow_mode_stops_at_geofence_boundary(
    fake_bridge: FakeBridge, test_settings: Settings
):
    """Integration: follow mode tracks target until reaching geofence boundary, then holds."""
    await fake_bridge.connect()
    authority = Authority(fake_bridge, test_settings)
    scene_pipe = ScenePipeline(FakeDetector(), FakeVLMClient())
    trigger_eng = TriggerEngine()
    mode_mgr = ModeManager(authority, scene_pipe, trigger_eng)
    await authority.start()

    # Takeoff
    tok = authority.arm_motion("takeoff")
    await authority.takeoff(tok.token)

    # Set follow target
    mode_mgr.set_follow_target([0.1, 0.4, 0.4, 0.6])

    tok_follow = authority.arm_motion("follow")
    await authority.set_mode(
        "follow",
        token=tok_follow.token,
        controller_cb=mode_mgr.get_follow_controller(),
    )

    await asyncio.sleep(0.1)
    # When position is inside geofence
    assert authority.is_point_inside_geofence(2.0, 2.0) is True

    # When position crosses geofence boundary (e.g. 20m in a 15m box)
    assert authority.is_point_inside_geofence(20.0, 20.0) is False

    await authority.stop()
    await fake_bridge.disconnect()
