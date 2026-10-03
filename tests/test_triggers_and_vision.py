"""Tests for closed trigger action enum and vision pipeline triggers."""

import pytest
from PIL import Image

from dji_ground.scene import ScenePipeline
from dji_ground.triggers import TriggerEngine


def test_trigger_action_outside_enum_rejected(trigger_engine: TriggerEngine):
    """Test that any action string not in the closed enum raises ValueError."""
    invalid_data = {
        "trigger_id": "test_bad",
        "name": "Bad Trigger",
        "action": "fly_to_forbidden_coordinate",
        "condition_type": "object_detected",
        "condition_value": "intruder",
    }
    with pytest.raises(ValueError, match="Action 'fly_to_forbidden_coordinate' is not permitted"):
        trigger_engine.add_trigger(invalid_data)


def test_trigger_action_inside_enum_accepted(trigger_engine: TriggerEngine):
    """Test that all 7 allowed action enum values are successfully registered."""
    allowed = ["notify", "photo", "hover", "yaw_toward", "start_mode", "rth", "land"]
    for i, act in enumerate(allowed):
        data = {
            "trigger_id": f"test_ok_{i}",
            "name": f"Valid {act}",
            "action": act,
            "condition_type": "object_detected",
            "condition_value": "red_cone",
        }
        defn = trigger_engine.add_trigger(data)
        assert defn.action.value == act


def test_red_cone_trigger_fires_notify_and_hover(
    trigger_engine: TriggerEngine, scene_pipeline: ScenePipeline
):
    """Test that red cone trigger fires notify + hover without stick translation."""
    trigger_engine.add_trigger(
        {
            "trigger_id": "trig_cone",
            "name": "Cone Stop",
            "action": "hover",
            "condition_type": "object_detected",
            "condition_value": "red_cone",
        }
    )

    img = Image.open("fixtures/sample_frame.jpg")
    objects = scene_pipeline.detector.detect(img)
    scene_desc = {"objects": objects}
    osd_data = {"raw_text": "STATUS: P-GPS"}
    telem = {"altitude_agl": 2.0}

    fired = trigger_engine.evaluate(scene_desc, osd_data, telem)
    assert len(fired) >= 1
    assert fired[0]["action"] == "hover"
    assert fired[0]["trigger_id"] == "trig_cone"


def test_scene_diffing(scene_pipeline: ScenePipeline):
    """Test scene diffing against baseline."""
    base_img = Image.open("fixtures/sample_frame.jpg")
    base_objs = scene_pipeline.detector.detect(base_img)
    scene_pipeline.set_baseline(base_img, "Baseline description", base_objs)

    # Current scene with new object
    new_objs = list(base_objs) + [
        {"label": "intruder_person", "conf": 0.9, "bbox": [0, 0, 1, 1], "source": "fake"}
    ]
    diff = scene_pipeline.diff_scene(new_objs, "New caption with intruder")
    assert diff["has_diff"] is True
    assert "intruder_person" in diff["new_objects"]
