export interface TelemetryData {
  timestamp_ms: number;
  latitude: number;
  longitude: number;
  altitude_agl: number;
  roll: number;
  pitch: number;
  yaw: number;
  vx: number;
  vy: number;
  vz: number;
  battery_percent: number;
  gps_satellite_count: number;
  signal_quality: number;
  flight_mode: string;
  is_flying: boolean;
  gimbal_pitch: number;
  obstacle_detected: boolean;
}

export interface AuthorityStatus {
  state: string;
  mode: string;
  is_flying: boolean;
  battery_percent: number;
  altitude_agl: number;
  latitude: number;
  longitude: number;
  heading_deg: number;
  velocities: { vx: number; vy: number; vz: number };
  sticks: { pitch: number; roll: number; yaw: number; throttle: number };
  watchdog_ok: boolean;
  video_age_ms: number;
  video_fresh: boolean;
  obstacle_detected: boolean;
  bridge_connected: boolean;
}

export interface Point3D {
  x: number;
  y: number;
  z: number;
  r: number;
  g: number;
  b: number;
}

export interface TriggerItem {
  trigger_id: string;
  name: string;
  action: 'notify' | 'photo' | 'hover' | 'yaw_toward' | 'start_mode' | 'rth' | 'land';
  condition_type: string;
  condition_value: string;
  active?: boolean;
}

export interface SceneDescription {
  caption: string;
  objects: Array<{
    label: string;
    conf: number;
    bbox: [number, number, number, number];
    source: string;
  }>;
  overlays: string[];
  telemetry_stamp: Record<string, any>;
  frame_id: number;
  age_ms: number;
}
