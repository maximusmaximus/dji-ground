"""Real-time 3D reconstruction, point cloud generation, and timeline recording."""

import json
import math
import os
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

from .db import SessionDB


@dataclass
class Point3D:
    x: float
    y: float
    z: float
    r: int = 255
    g: int = 255
    b: int = 255


class ReconstructionEngine3D:
    """Synchronizes camera video frames with 6-DOF telemetry to build and record 3D point clouds."""

    def __init__(
        self,
        db: SessionDB | None = None,
        export_dir: str = "./data/models_3d",
        resolution: str = "high",
        max_points: int = 500_000,
    ) -> None:
        self.db = db or SessionDB()
        self.export_dir = export_dir
        self.resolution = resolution
        self.max_points = max_points
        self.active_session_id: str | None = None
        self.session_start_time: float = 0.0

        # Accumulated world points: list of Point3D
        self.points: list[Point3D] = []
        self.keyframe_count: int = 0
        self.last_keyframe_time: float = 0.0

        # Camera intrinsics (DJI standard FOV ~84 deg, 640x480 normalized)
        self.fx = 480.0
        self.fy = 480.0
        self.cx = 320.0
        self.cy = 240.0

        os.makedirs(self.export_dir, exist_ok=True)

    def is_active(self) -> bool:
        return self.active_session_id is not None

    def start_session(self, target_label: str | None = None, resolution: str | None = None) -> str:
        """Initialize a new 3D scanning session."""
        self.session_id = f"scan_{int(time.time())}"
        self.active_session_id = self.session_id
        self.session_start_time = time.time()
        self.points.clear()
        self.keyframe_count = 0
        self.last_keyframe_time = 0.0
        if resolution:
            self.resolution = resolution

        meta = {"target_label": target_label, "resolution": self.resolution}
        self.db.save_3d_session(
            session_id=self.session_id,
            start_time=self.session_start_time,
            end_time=None,
            point_count=0,
            file_path=None,
            resolution=self.resolution,
            metadata=meta,
        )
        return self.session_id

    def process_frame(
        self,
        image: Image.Image,
        telemetry: dict[str, Any],
        min_interval_ms: float = 200.0,
    ) -> list[dict[str, Any]] | None:
        """Process video frame with current drone pose and project 3D points."""
        if not self.is_active():
            return None

        now = time.time()
        if (now - self.last_keyframe_time) * 1000.0 < min_interval_ms:
            return None
        self.last_keyframe_time = now
        self.keyframe_count += 1

        # Extract aircraft 6-DOF pose
        # Drone position in local ENU (East-North-Up): vx/vy integration or lat/lon
        x = float(telemetry.get("vx", 0.0)) * (now - self.session_start_time)
        y = float(telemetry.get("vy", 0.0)) * (now - self.session_start_time)
        z = float(telemetry.get("altitude_agl", 1.5))
        yaw = math.radians(float(telemetry.get("yaw", 0.0)))
        pitch = math.radians(float(telemetry.get("pitch", 0.0)))
        gimbal_pitch = math.radians(float(telemetry.get("gimbal_pitch", -20.0)))

        # Downsample image for rapid 3D feature reprojection
        thumb = image.resize((80, 60))
        arr = np.array(thumb)
        h, w = arr.shape[:2]

        new_points: list[Point3D] = []
        slice_dicts: list[dict[str, Any]] = []

        # Step size based on resolution
        step = 4 if self.resolution == "high" else (8 if self.resolution == "medium" else 12)

        # Approximate depth from camera height and ray angle
        # Ground plane is at z=0, camera is at z
        for v in range(0, h, step):
            for u in range(0, w, step):
                r_val, g_val, b_val = int(arr[v, u, 0]), int(arr[v, u, 1]), int(arr[v, u, 2])

                # Normalized camera ray
                ray_x = (u * (640 / w) - self.cx) / self.fx
                ray_y = (v * (480 / h) - self.cy) / self.fy
                ray_z = 1.0
                ray_len = math.sqrt(ray_x**2 + ray_y**2 + ray_z**2)
                ray_x /= ray_len
                ray_y /= ray_len
                ray_z /= ray_len

                # Downward tilt angle (absolute value of negative gimbal pitch)
                alpha = math.radians(abs(float(telemetry.get("gimbal_pitch", -20.0))))
                if alpha < 0.05:
                    alpha = math.radians(20.0)

                # Horizontal and vertical ray components in ENU
                r_h = ray_z * math.cos(alpha) - ray_y * math.sin(alpha)
                w_z = -(ray_z * math.sin(alpha) + ray_y * math.cos(alpha))

                if w_z < -0.01:
                    d = min(z / (-w_z), 25.0)
                    w_x = ray_x * math.cos(yaw) + r_h * math.sin(yaw)
                    w_y = -ray_x * math.sin(yaw) + r_h * math.cos(yaw)
                    pt_x = round(x + w_x * d, 3)
                    pt_y = round(y + w_y * d, 3)
                    pt_z = round(max(0.0, z + w_z * d), 3)
                else:
                    d = 5.0
                    w_x = ray_x * math.cos(yaw) + ray_z * math.sin(yaw)
                    w_y = -ray_x * math.sin(yaw) + ray_z * math.cos(yaw)
                    pt_x = round(x + w_x * d, 3)
                    pt_y = round(y + w_y * d, 3)
                    pt_z = round(max(0.0, z - ray_y * d), 3)

                pt = Point3D(pt_x, pt_y, pt_z, r_val, g_val, b_val)
                new_points.append(pt)
                slice_dicts.append(
                    {"x": pt_x, "y": pt_y, "z": pt_z, "r": r_val, "g": g_val, "b": b_val}
                )

        # Append while honoring max_points cap
        if len(self.points) + len(new_points) <= self.max_points:
            self.points.extend(new_points)

        # Record timeline frame in SQLite
        pose_info = {
            "x": round(x, 3),
            "y": round(y, 3),
            "z": round(z, 3),
            "yaw_deg": round(math.degrees(yaw), 1),
            "pitch_deg": round(math.degrees(pitch), 1),
            "gimbal_pitch_deg": round(math.degrees(gimbal_pitch), 1),
        }
        self.db.add_timeline_frame(
            session_id=self.active_session_id,
            timestamp_ms=now * 1000.0,
            frame_idx=self.keyframe_count,
            pose=pose_info,
            telemetry=telemetry,
            point_slice=slice_dicts,
        )

        return slice_dicts

    def stop_session(self) -> dict[str, Any]:
        """Finalize session, export point cloud PLY, and return summary."""
        if not self.is_active():
            return {"status": "no_active_session"}

        session_id = self.active_session_id
        end_time = time.time()
        ply_path = os.path.join(self.export_dir, f"{session_id}.ply")
        obj_path = os.path.join(self.export_dir, f"{session_id}.obj")
        gltf_path = os.path.join(self.export_dir, f"{session_id}.gltf")

        self.export_ply(ply_path)
        self.export_obj(obj_path)
        self.export_gltf(gltf_path)

        meta = {
            "duration_s": round(end_time - self.session_start_time, 2),
            "keyframe_count": self.keyframe_count,
            "bounds": self.get_bounds(),
            "export_files": {
                "ply": ply_path,
                "obj": obj_path,
                "gltf": gltf_path,
            },
        }
        self.db.save_3d_session(
            session_id=session_id,
            start_time=self.session_start_time,
            end_time=end_time,
            point_count=len(self.points),
            file_path=ply_path,
            resolution=self.resolution,
            metadata=meta,
        )

        self.active_session_id = None
        return {
            "session_id": session_id,
            "point_count": len(self.points),
            "keyframe_count": self.keyframe_count,
            "file_path": ply_path,
            "obj_path": obj_path,
            "gltf_path": gltf_path,
            "bounds": meta["bounds"],
        }

    def export_ply(self, output_path: str) -> None:
        """Write current accumulated point cloud to standard ASCII PLY file."""
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("ply\n")
            f.write("format ascii 1.0\n")
            f.write(f"element vertex {len(self.points)}\n")
            f.write("property float x\n")
            f.write("property float y\n")
            f.write("property float z\n")
            f.write("property uchar red\n")
            f.write("property uchar green\n")
            f.write("property uchar blue\n")
            f.write("end_header\n")
            f.writelines(f"{p.x:.3f} {p.y:.3f} {p.z:.3f} {p.r} {p.g} {p.b}\n" for p in self.points)

    def export_obj(self, output_path: str) -> None:
        """Export point cloud and reconstructed vertices to Wavefront OBJ format."""
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("# dji-ground 3D Reconstruction Model\n")
            f.write(f"# Vertices: {len(self.points)}\n")
            for p in self.points:
                # OBJ format with vertex color extension: v x y z r g b (0.0-1.0)
                r_norm = round(p.r / 255.0, 3)
                g_norm = round(p.g / 255.0, 3)
                b_norm = round(p.b / 255.0, 3)
                f.write(f"v {p.x:.3f} {p.y:.3f} {p.z:.3f} {r_norm} {g_norm} {b_norm}\n")

    def export_gltf(self, output_path: str) -> None:
        """Export point cloud metadata and scene description to standard GLTF JSON."""
        bounds = self.get_bounds()
        pts_data = [{"pos": [p.x, p.y, p.z], "color": [p.r / 255.0, p.g / 255.0, p.b / 255.0]} for p in self.points[:5000]]
        gltf_doc = {
            "asset": {"version": "2.0", "generator": "dji-ground-3d-engine"},
            "scene": 0,
            "scenes": [{"name": "DefaultScene", "nodes": [0]}],
            "nodes": [{"name": "ReconstructedPointCloud", "mesh": 0}],
            "meshes": [
                {
                    "name": "DroneScanMesh",
                    "primitives": [{"mode": 0, "attributes": {"POSITION": 0}}],
                    "extras": {
                        "point_count": len(self.points),
                        "bounds": bounds,
                        "sample_points": pts_data,
                    },
                }
            ],
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(gltf_doc, f, indent=2)

    def get_bounds(self) -> dict[str, float]:
        """Compute bounding box of accumulated points."""
        if not self.points:
            return {
                "min_x": 0.0,
                "max_x": 0.0,
                "min_y": 0.0,
                "max_y": 0.0,
                "min_z": 0.0,
                "max_z": 0.0,
            }
        xs = [p.x for p in self.points]
        ys = [p.y for p in self.points]
        zs = [p.z for p in self.points]
        return {
            "min_x": round(min(xs), 2),
            "max_x": round(max(xs), 2),
            "min_y": round(min(ys), 2),
            "max_y": round(max(ys), 2),
            "min_z": round(min(zs), 2),
            "max_z": round(max(zs), 2),
        }

    def get_timeline_scrub(self, session_id: str, target_time_ms: float) -> dict[str, Any]:
        """Return reconstructed 3D points and drone pose up to target_time_ms."""
        frames = self.db.get_timeline_frames(session_id)
        if not frames:
            return {"points": [], "pose": {}, "telemetry": {}}

        accumulated_points = []
        matching_frame = frames[0]

        for f in frames:
            if f["timestamp_ms"] <= target_time_ms:
                accumulated_points.extend(f.get("point_slice", []))
                matching_frame = f
            else:
                break

        return {
            "session_id": session_id,
            "target_time_ms": target_time_ms,
            "points": accumulated_points,
            "pose": matching_frame.get("pose"),
            "telemetry": matching_frame.get("telemetry"),
            "frame_idx": matching_frame.get("frame_idx"),
        }
