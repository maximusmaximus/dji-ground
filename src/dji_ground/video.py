"""Video decoding using PyAV for H.264 stream and MJPEG streaming."""

import asyncio
import io
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import av
import numpy as np
from PIL import Image


@dataclass
class DecodedFrame:
    """Decoded video frame with timing metadata."""

    frame_id: int
    timestamp_ms: float
    image: Image.Image
    rgb_array: np.ndarray

    @property
    def age_ms(self) -> float:
        """Calculate age of frame in milliseconds relative to now."""
        return max(0.0, (time.time() * 1000.0) - self.timestamp_ms)


class VideoPipeline:
    """Consumes H.264 chunks from bridge, decodes frames via PyAV, and yields MJPEG."""

    def __init__(self, bridge) -> None:
        self.bridge = bridge
        self.latest_frame: DecodedFrame | None = None
        self._frame_counter: int = 0
        self._running: bool = False
        self._decode_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start background H.264 decoding task."""
        if self._running:
            return
        self._running = True
        self._decode_task = asyncio.create_task(self._decode_loop())

    async def stop(self) -> None:
        """Stop background decoding task."""
        self._running = False
        if self._decode_task:
            self._decode_task.cancel()
            try:
                await self._decode_task
            except asyncio.CancelledError:
                pass

    async def _decode_loop(self) -> None:
        """Decode H.264 packets using PyAV parser/codec."""
        codec = av.CodecContext.create("h264", "r")
        try:
            codec.flags |= av.codec.context.Flags.low_delay
        except Exception:
            pass

        while self._running:
            try:
                chunk = await self.bridge.get_video_chunk()
                if not chunk:
                    await asyncio.sleep(0.02)
                    continue

                packets = codec.parse(chunk)
                for packet in packets:
                    frames = codec.decode(packet)
                    for frame in frames:
                        now_ms = time.time() * 1000.0
                        img = frame.to_image()
                        arr = np.array(img)
                        self._frame_counter += 1
                        async with self._lock:
                            self.latest_frame = DecodedFrame(
                                frame_id=self._frame_counter,
                                timestamp_ms=now_ms,
                                image=img,
                                rgb_array=arr,
                            )
                await asyncio.sleep(0.01)
            except Exception:
                await asyncio.sleep(0.02)

    async def get_latest_frame(self) -> DecodedFrame | None:
        """Return the most recently decoded video frame."""
        async with self._lock:
            return self.latest_frame

    async def get_latest_jpeg(self) -> bytes | None:
        """Return the most recent frame encoded as JPEG bytes."""
        frame = await self.get_latest_frame()
        if not frame:
            return None
        buf = io.BytesIO()
        frame.image.save(buf, format="JPEG", quality=85)
        return buf.getvalue()

    async def generate_mjpeg_stream(self) -> AsyncGenerator[bytes, None]:
        """Async generator yielding multipart/x-mixed-replace MJPEG stream."""
        boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
        while self._running:
            frame = await self.get_latest_frame()
            if frame:
                buf = io.BytesIO()
                frame.image.save(buf, format="JPEG", quality=75)
                jpeg_bytes = buf.getvalue()
                yield boundary + jpeg_bytes + b"\r\n"
            await asyncio.sleep(0.066)  # ~15 FPS
