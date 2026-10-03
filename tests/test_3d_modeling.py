"""Tests for live 3D reconstruction, point cloud accumulation, and timeline scrubbing."""

import os

from PIL import Image

from dji_ground.db import SessionDB
from dji_ground.modeling_3d import ReconstructionEngine3D


def test_3d_reconstruction_session_and_export(tmp_path):
    """Test full 3D scan lifecycle: start, feed frames, timeline recording, and PLY export."""
    db_path = str(tmp_path / "test_3d.sqlite")
    export_dir = str(tmp_path / "models_3d")
    db = SessionDB(db_path)
    engine = ReconstructionEngine3D(db=db, export_dir=export_dir, resolution="medium")

    # Start session
    session_id = engine.start_session(target_label="red_cone")
    assert engine.is_active() is True

    # Process sample frames with poses
    img = Image.open("fixtures/sample_frame.jpg")
    telem = {
        "vx": 0.5,
        "vy": 0.2,
        "altitude_agl": 2.5,
        "yaw": 45.0,
        "pitch": 0.0,
        "gimbal_pitch": -25.0,
    }

    # Process frame 1
    slice1 = engine.process_frame(img, telem, min_interval_ms=0.0)
    assert slice1 is not None
    assert len(slice1) > 0
    assert len(engine.points) > 0

    # Stop session & export
    res = engine.stop_session()
    assert res["session_id"] == session_id
    assert res["point_count"] > 0
    assert os.path.exists(res["file_path"])

    # Verify PLY format header
    with open(res["file_path"], "r", encoding="utf-8") as f:
        header = f.readline().strip()
        assert header == "ply"


def test_3d_timeline_scrubbing(tmp_path):
    """Test scrubbing timeline to specific time returns matching point slice and pose."""
    db_path = str(tmp_path / "test_scrub.sqlite")
    export_dir = str(tmp_path / "models_scrub")
    db = SessionDB(db_path)
    engine = ReconstructionEngine3D(db=db, export_dir=export_dir)

    session_id = engine.start_session()
    img = Image.open("fixtures/sample_frame.jpg")

    engine.process_frame(img, {"altitude_agl": 1.0, "vx": 0.1, "vy": 0.0}, min_interval_ms=0.0)
    t1 = engine.last_keyframe_time * 1000.0

    # Query timeline scrub
    scrub_res = engine.get_timeline_scrub(session_id, t1 + 10.0)
    assert scrub_res["session_id"] == session_id
    assert len(scrub_res["points"]) > 0
    assert scrub_res["pose"]["z"] == 1.0
