"""Pluggable object detection and VLM scene captioning pipeline."""

import base64
import io
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx
import numpy as np
from PIL import Image


class BaseDetector(ABC):
    """Abstract interface for object detection."""

    @abstractmethod
    def detect(
        self, image: Image.Image, filter_labels: list[str] | None = None
    ) -> list[dict[str, Any]]:
        pass


class FakeDetector(BaseDetector):
    """Deterministic object detector for automated tests and baseline operation."""

    def detect(
        self, image: Image.Image, filter_labels: list[str] | None = None
    ) -> list[dict[str, Any]]:
        # Inspect image to see if red object exists
        arr = np.array(image)
        r = arr[:, :, 0]
        g = arr[:, :, 1]
        b = arr[:, :, 2]
        # Red cone detection rule: strong red, low green and blue
        red_mask = (r > 160) & (g < 100) & (b < 80)
        y_indices, x_indices = np.where(red_mask)

        detected = []
        if len(y_indices) > 50:
            h, w = arr.shape[:2]
            ymin = float(np.min(y_indices)) / h
            ymax = float(np.max(y_indices)) / h
            xmin = float(np.min(x_indices)) / w
            xmax = float(np.max(x_indices)) / w

            cone_obj = {
                "label": "red_cone",
                "conf": 0.96,
                "bbox": [round(ymin, 3), round(xmin, 3), round(ymax, 3), round(xmax, 3)],
                "source": "fake_detector",
            }
            if not filter_labels or "red_cone" in filter_labels or "cone" in filter_labels:
                detected.append(cone_obj)

        # Default object if none found to ensure deterministic testing
        if not detected and (not filter_labels or "landing_pad" in filter_labels):
            detected.append(
                {
                    "label": "landing_pad",
                    "conf": 0.88,
                    "bbox": [0.65, 0.35, 0.90, 0.65],
                    "source": "fake_detector",
                }
            )
        return detected


class YoloDetector(BaseDetector):
    """Real-time object detector using Ultralytics YOLO with automatic fallback."""

    def __init__(self, model_name: str = "yolov8n.pt", conf_threshold: float = 0.25) -> None:
        self.model_name = model_name
        self.conf_threshold = conf_threshold
        self.model = None
        try:
            from ultralytics import YOLO

            self.model = YOLO(self.model_name)
        except Exception:
            self.model = None

    def detect(
        self, image: Image.Image, filter_labels: list[str] | None = None
    ) -> list[dict[str, Any]]:
        if not self.model:
            return FakeDetector().detect(image, filter_labels)

        try:
            results = self.model(image, conf=self.conf_threshold, verbose=False)
            detected = []
            for r in results:
                for box in r.boxes:
                    cls_id = int(box.cls[0])
                    label = self.model.names[cls_id]
                    if filter_labels and label not in filter_labels:
                        continue
                    xyxyn = box.xyxyn[0].tolist()
                    detected.append(
                        {
                            "label": label,
                            "conf": round(float(box.conf[0]), 3),
                            "bbox": [
                                round(xyxyn[1], 3),
                                round(xyxyn[0], 3),
                                round(xyxyn[3], 3),
                                round(xyxyn[2], 3),
                            ],
                            "source": "yolo_detector",
                        }
                    )
            return detected or FakeDetector().detect(image, filter_labels)
        except Exception:
            return FakeDetector().detect(image, filter_labels)


class BaseVLMClient(ABC):
    """Abstract interface for Vision Language Model captioning."""

    @abstractmethod
    async def caption_scene(self, image: Image.Image, prompt: str | None = None) -> str:
        pass


class FakeVLMClient(BaseVLMClient):
    """Deterministic VLM for tests returning structured fixture captions."""

    async def caption_scene(self, image: Image.Image, prompt: str | None = None) -> str:
        # Check image colors
        arr = np.array(image)
        has_red = np.any((arr[:, :, 0] > 180) & (arr[:, :, 1] < 100))
        if has_red:
            return "Clear outdoor corridor with a bright red safety cone positioned in the center path."
        return "Open indoor flight staging area with clean floor markings and clear line of sight."


class VeniceVLMClient(BaseVLMClient):
    """Production VLM client powered by Venice AI API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.venice.ai/api/v1",
        model: str = "qwen-2.5-vl-72b",
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    async def caption_scene(self, image: Image.Image, prompt: str | None = None) -> str:
        buffered = io.BytesIO()
        image.save(buffered, format="JPEG", quality=80)
        img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

        user_prompt = (
            prompt
            or "Describe the scene visible from the drone's primary camera in 2 concise sentences."
        )
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
                        },
                    ],
                }
            ],
            "max_tokens": 150,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=headers
                )
                if res.status_code == 200:
                    data = res.json()
                    return data["choices"][0]["message"]["content"].strip()
        except Exception:
            pass
        return "Scene visible with primary camera; VLM API fallback."


class ScenePipeline:
    """Orchestrates detection, VLM captioning, diffing, and baseline storage."""

    def __init__(
        self,
        detector: BaseDetector | None = None,
        vlm_client: BaseVLMClient | None = None,
    ) -> None:
        self.detector = detector or FakeDetector()
        self.vlm = vlm_client or FakeVLMClient()
        self.baseline_image: Image.Image | None = None
        self.baseline_caption: str | None = None
        self.baseline_objects: list[dict[str, Any]] = []

    def set_baseline(
        self, image: Image.Image, caption: str, objects: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Record the current scene state as reference baseline."""
        self.baseline_image = image
        self.baseline_caption = caption
        self.baseline_objects = objects
        return {
            "status": "baseline_set",
            "caption": caption,
            "object_count": len(objects),
            "timestamp": time.time(),
        }

    async def describe_scene(
        self,
        image: Image.Image,
        telemetry_dict: dict[str, Any],
        frame_id: int,
        age_ms: float,
        prompt: str | None = None,
    ) -> dict[str, Any]:
        """Produce standardized scene description matching MCP contract."""
        objects = self.detector.detect(image)
        caption = await self.vlm.caption_scene(image, prompt)

        overlays = []
        if telemetry_dict.get("is_flying"):
            overlays.append("IN_FLIGHT")
        if age_ms > 1000.0:
            overlays.append("STALE_VIDEO_WARNING")
        if telemetry_dict.get("obstacle_detected"):
            overlays.append("OBSTACLE_WARNING")

        return {
            "caption": caption,
            "objects": objects,
            "overlays": overlays,
            "telemetry_stamp": telemetry_dict,
            "frame_id": frame_id,
            "age_ms": round(age_ms, 2),
        }

    def diff_scene(
        self, current_objects: list[dict[str, Any]], current_caption: str
    ) -> dict[str, Any]:
        """Compute difference between current scene and stored baseline."""
        if not self.baseline_caption:
            return {"has_diff": False, "reason": "No baseline set", "diff_score": 0.0}

        base_labels = {o["label"] for o in self.baseline_objects}
        curr_labels = {o["label"] for o in current_objects}

        new_labels = list(curr_labels - base_labels)
        missing_labels = list(base_labels - curr_labels)

        has_diff = len(new_labels) > 0 or len(missing_labels) > 0
        diff_score = 0.8 if has_diff else 0.0

        return {
            "has_diff": has_diff,
            "new_objects": new_labels,
            "missing_objects": missing_labels,
            "diff_score": diff_score,
            "baseline_caption": self.baseline_caption,
            "current_caption": current_caption,
        }
