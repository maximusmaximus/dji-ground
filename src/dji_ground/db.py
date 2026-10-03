"""SQLite persistence for triggers, snapshots, 3D modeling timelines, and audit logs."""

import json
import sqlite3
import time
from typing import Any


class SessionDB:
    """Session database handling persistent state and telemetry logs."""

    def __init__(self, db_path: str = "dji_ground_session.sqlite") -> None:
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS triggers (
                    trigger_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    condition_type TEXT NOT NULL,
                    condition_value TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    timestamp_ms REAL NOT NULL,
                    caption TEXT,
                    frame_path TEXT,
                    telemetry_json TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS models_3d (
                    session_id TEXT PRIMARY KEY,
                    start_time REAL NOT NULL,
                    end_time REAL,
                    point_count INTEGER NOT NULL DEFAULT 0,
                    file_path TEXT,
                    resolution TEXT NOT NULL,
                    metadata_json TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS timeline_frames (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    timestamp_ms REAL NOT NULL,
                    frame_idx INTEGER NOT NULL,
                    pose_json TEXT NOT NULL,
                    telemetry_json TEXT NOT NULL,
                    point_slice_json TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    source TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    details_json TEXT
                )
                """
            )
            conn.commit()

    def add_trigger(
        self,
        trigger_id: str,
        name: str,
        action: str,
        condition_type: str,
        condition_value: str,
    ) -> None:
        with self._get_conn() as conn:
            conn.cursor().execute(
                """
                INSERT OR REPLACE INTO triggers
                (trigger_id, name, action, condition_type, condition_value, active, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (trigger_id, name, action, condition_type, condition_value, time.time()),
            )
            conn.commit()

    def get_triggers(self, active_only: bool = True) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            query = "SELECT * FROM triggers"
            if active_only:
                query += " WHERE active = 1"
            rows = conn.cursor().execute(query).fetchall()
            return [dict(r) for r in rows]

    def delete_trigger(self, trigger_id: str) -> bool:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM triggers WHERE trigger_id = ?", (trigger_id,))
            conn.commit()
            return cursor.rowcount > 0

    def add_snapshot(
        self,
        snapshot_id: str,
        timestamp_ms: float,
        caption: str,
        frame_path: str | None,
        telemetry: dict[str, Any],
    ) -> None:
        with self._get_conn() as conn:
            conn.cursor().execute(
                """
                INSERT INTO snapshots (snapshot_id, timestamp_ms, caption, frame_path, telemetry_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (snapshot_id, timestamp_ms, caption, frame_path, json.dumps(telemetry)),
            )
            conn.commit()

    def save_3d_session(
        self,
        session_id: str,
        start_time: float,
        end_time: float | None,
        point_count: int,
        file_path: str | None,
        resolution: str,
        metadata: dict[str, Any],
    ) -> None:
        with self._get_conn() as conn:
            conn.cursor().execute(
                """
                INSERT OR REPLACE INTO models_3d
                (session_id, start_time, end_time, point_count, file_path, resolution, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    start_time,
                    end_time,
                    point_count,
                    file_path,
                    resolution,
                    json.dumps(metadata),
                ),
            )
            conn.commit()

    def get_3d_session(self, session_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            row = (
                conn.cursor()
                .execute("SELECT * FROM models_3d WHERE session_id = ?", (session_id,))
                .fetchone()
            )
            if not row:
                return None
            res = dict(row)
            if res.get("metadata_json"):
                res["metadata"] = json.loads(res["metadata_json"])
            return res

    def add_timeline_frame(
        self,
        session_id: str,
        timestamp_ms: float,
        frame_idx: int,
        pose: dict[str, Any],
        telemetry: dict[str, Any],
        point_slice: list[dict[str, Any]] | None = None,
    ) -> None:
        with self._get_conn() as conn:
            conn.cursor().execute(
                """
                INSERT INTO timeline_frames
                (session_id, timestamp_ms, frame_idx, pose_json, telemetry_json, point_slice_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    timestamp_ms,
                    frame_idx,
                    json.dumps(pose),
                    json.dumps(telemetry),
                    json.dumps(point_slice or []),
                ),
            )
            conn.commit()

    def get_timeline_frames(self, session_id: str) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            rows = (
                conn.cursor()
                .execute(
                    "SELECT * FROM timeline_frames WHERE session_id = ? ORDER BY timestamp_ms ASC",
                    (session_id,),
                )
                .fetchall()
            )
            result = []
            for r in rows:
                item = dict(r)
                item["pose"] = json.loads(item["pose_json"])
                item["telemetry"] = json.loads(item["telemetry_json"])
                item["point_slice"] = json.loads(item["point_slice_json"])
                result.append(item)
            return result

    def log_audit(self, source: str, event_type: str, details: dict[str, Any]) -> None:
        with self._get_conn() as conn:
            conn.cursor().execute(
                """
                INSERT INTO audit_log (timestamp, source, event_type, details_json)
                VALUES (?, ?, ?, ?)
                """,
                (time.time(), source, event_type, json.dumps(details)),
            )
            conn.commit()
