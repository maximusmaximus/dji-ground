from dji_ground.safety_gates import PLACEHOLDER_AGE_MS, placeholder_frame, scan_without_confirm


def test_placeholder_is_stale():
    frame = placeholder_frame("abc")
    assert frame["age_ms"] == PLACEHOLDER_AGE_MS
    assert frame["age_ms"] > 1000
    assert frame["source"] == "placeholder"


def test_scan_does_not_self_arm():
    result = scan_without_confirm("cone", {"bbox": [0.1, 0.1, 0.2, 0.2]})
    assert result["status"] == "requires_arm"
    assert "token" not in result
