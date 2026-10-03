"""Closed action enum trigger rules engine."""

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .db import SessionDB


class AllowedAction(str, Enum):
    """Closed action enum enforced for all trigger executions."""

    NOTIFY = "notify"
    PHOTO = "photo"
    HOVER = "hover"
    YAW_TOWARD = "yaw_toward"
    START_MODE = "start_mode"
    RTH = "rth"
    LAND = "land"


class TriggerDefinition(BaseModel):
    """Schema for a trigger rule."""

    trigger_id: str = Field(description="Unique identifier for the trigger")
    name: str = Field(description="Human readable rule name")
    action: AllowedAction = Field(description="One of the closed action enum members")
    condition_type: str = Field(
        description="'object_detected', 'osd_text', 'diff_detected', or 'telemetry'"
    )
    condition_value: str = Field(
        description="Target label, keyword, threshold, or telemetry expression"
    )

    @field_validator("action", mode="before")
    @classmethod
    def validate_action(cls, v: Any) -> AllowedAction:
        if isinstance(v, AllowedAction):
            return v
        if isinstance(v, str):
            v_clean = v.strip().lower()
            for member in AllowedAction:
                if member.value == v_clean:
                    return member
        raise ValueError(
            f"Action '{v}' is not permitted. Action must be one of: {[a.value for a in AllowedAction]}"
        )


class TriggerEngine:
    """Evaluates incoming scene snapshots and telemetry against active trigger rules."""

    def __init__(self, db: SessionDB | None = None) -> None:
        self.db = db or SessionDB()
        self.triggers: dict[str, TriggerDefinition] = {}
        self._load_from_db()

    def _load_from_db(self) -> None:
        rows = self.db.get_triggers(active_only=True)
        for r in rows:
            try:
                defn = TriggerDefinition(
                    trigger_id=r["trigger_id"],
                    name=r["name"],
                    action=r["action"],
                    condition_type=r["condition_type"],
                    condition_value=r["condition_value"],
                )
                self.triggers[defn.trigger_id] = defn
            except Exception:
                pass

    def add_trigger(self, trigger_data: dict[str, Any]) -> TriggerDefinition:
        """Register and persist a new trigger rule with strict action enum validation."""
        defn = TriggerDefinition(**trigger_data)
        self.triggers[defn.trigger_id] = defn
        self.db.add_trigger(
            trigger_id=defn.trigger_id,
            name=defn.name,
            action=defn.action.value,
            condition_type=defn.condition_type,
            condition_value=defn.condition_value,
        )
        return defn

    def remove_trigger(self, trigger_id: str) -> bool:
        """Remove trigger by ID."""
        if trigger_id in self.triggers:
            del self.triggers[trigger_id]
        return self.db.delete_trigger(trigger_id)

    def list_triggers(self) -> list[dict[str, Any]]:
        """List all active triggers."""
        return [t.model_dump() for t in self.triggers.values()]

    def evaluate(
        self,
        scene_desc: dict[str, Any],
        osd_data: dict[str, Any],
        telemetry: dict[str, Any],
        diff_data: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Evaluate all triggers and return triggered actions."""
        fired_actions = []

        for trigger in self.triggers.values():
            triggered = False
            details = {}

            # 1. Object detection condition
            if trigger.condition_type == "object_detected":
                target_label = trigger.condition_value.strip().lower()
                for obj in scene_desc.get("objects", []):
                    if obj.get("label", "").lower() == target_label:
                        triggered = True
                        details = {"matched_object": obj}
                        break

            # 2. OSD text condition
            elif trigger.condition_type == "osd_text":
                keyword = trigger.condition_value.strip().lower()
                osd_raw = osd_data.get("raw_text", "").lower()
                if keyword in osd_raw or (
                    keyword == "obstacle" and osd_data.get("obstacle_detected")
                ):
                    triggered = True
                    details = {"matched_osd": osd_data.get("raw_text")}

            # 3. Scene diff condition
            elif trigger.condition_type == "diff_detected":
                if diff_data and diff_data.get("has_diff"):
                    triggered = True
                    details = {"diff": diff_data}

            # 4. Telemetry condition (e.g. "battery < 20")
            elif trigger.condition_type == "telemetry":
                expr = trigger.condition_value.strip()
                # Parse simple pattern like "battery < 20" or "altitude > 5.0"
                match = re.match(r"(battery|altitude|speed)\s*([<>]=?)\s*([0-9.]+)", expr)
                if match:
                    param, op, val_str = match.groups()
                    target_val = float(val_str)
                    actual_val = 0.0
                    if param == "battery":
                        actual_val = float(telemetry.get("battery_percent", 100))
                    elif param == "altitude":
                        actual_val = float(telemetry.get("altitude_agl", 0.0))

                    if (
                        op == "<"
                        and actual_val < target_val
                        or op == "<="
                        and actual_val <= target_val
                        or op == ">"
                        and actual_val > target_val
                        or op == ">="
                        and actual_val >= target_val
                    ):
                        triggered = True
                    details = {"param": param, "actual": actual_val, "target": target_val}

            if triggered:
                fired_actions.append(
                    {
                        "trigger_id": trigger.trigger_id,
                        "name": trigger.name,
                        "action": trigger.action.value,
                        "details": details,
                    }
                )

        return fired_actions
