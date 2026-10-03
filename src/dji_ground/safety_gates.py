"""Guards so MCP clients cannot self-arm and placeholders cannot look live.

Wire these into mcp_server.scan_target_object and the frame fallbacks.
"""

from __future__ import annotations

from typing import Any

PLACEHOLDER_AGE_MS = 10_000.0


def placeholder_frame(image_b64: str) -> dict[str, Any]:
    """A missing stream is stale. Never report age_ms 0 or 15."""
    return {
        "frame_id": 0,
        "age_ms": PLACEHOLDER_AGE_MS,
        "source": "placeholder",
        "image_b64": image_b64,
    }


def scan_without_confirm(target_label: str, matched: dict[str, Any] | None) -> dict[str, Any]:
    """Proposal only. Caller must pass a token already minted for orbit."""
    if not matched:
        return {
            "status": "target_not_found",
            "searched_label": target_label,
            "action": "hover",
        }
    return {
        "status": "requires_arm",
        "target_label": target_label,
        "matched_bbox": matched.get("bbox"),
        "message": "Pass confirm_token from operator arm_motion('orbit'). This tool will not mint one.",
    }
