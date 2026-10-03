import React, { useEffect, useState } from 'react';
import { AuthorityStatus, Point3D, SceneDescription, TelemetryData, TriggerItem } from './types.ts';
import { VideoPlayer } from './components/VideoPlayer.tsx';
import { TelemetryHUD } from './components/TelemetryHUD.tsx';
import { ModeSelector } from './components/ModeSelector.tsx';
import { TriggerManager } from './components/TriggerManager.tsx';
import { SceneTranscript } from './components/SceneTranscript.tsx';
import { ThreeDViewer } from './components/ThreeDViewer.tsx';
import { TimelineScrubber } from './components/TimelineScrubber.tsx';
import { EmergencyStopButton } from './components/EmergencyStopButton.tsx';
import { GamepadController } from './components/GamepadController.tsx';

export const App: React.FC = () => {
  const [telemetry, setTelemetry] = useState<TelemetryData | undefined>();
  const [status, setStatus] = useState<AuthorityStatus | undefined>();
  const [scene, setScene] = useState<SceneDescription | undefined>();
  const [triggers, setTriggers] = useState<TriggerItem[]>([]);
  const [points, setPoints] = useState<Point3D[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [timelineMaxMs, setTimelineMaxMs] = useState(10000);
  const [currentTimeMs, setCurrentTimeMs] = useState(0);

  // Connect telemetry WebSocket
  useEffect(() => {
    let ws: WebSocket;
    const connect = () => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const host = window.location.host || 'localhost:8000';
      ws = new WebSocket(`${protocol}//${host}/ws/telemetry`);

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.telemetry) setTelemetry(data.telemetry);
          if (data.status) setStatus(data.status);
        } catch (e) {
          console.error(e);
        }
      };

      ws.onclose = () => {
        setTimeout(connect, 1500);
      };
    };

    connect();
    return () => ws?.close();
  }, []);

  // Initial data load
  const loadTriggers = async () => {
    try {
      const res = await fetch('/api/triggers');
      if (res.ok) setTriggers(await res.json());
    } catch (e) {
      console.error(e);
    }
  };

  const refreshScene = async () => {
    try {
      const res = await fetch('/api/describe_scene');
      if (res.ok) setScene(await res.json());
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    loadTriggers();
    refreshScene();
  }, []);

  // API Handlers
  const handleEmergencyStop = async () => {
    await fetch('/api/emergency_stop', { method: 'POST' });
  };

  const handleArmMotion = async (mode: string) => {
    const res = await fetch('/api/arm_motion', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    });
    const data = await res.json();
    return data.token;
  };

  const handleTakeoff = async (token: string) => {
    await fetch('/api/takeoff', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    });
  };

  const handleLand = async () => {
    await fetch('/api/land', { method: 'POST' });
  };

  const handleRth = async () => {
    await fetch('/api/rth', { method: 'POST' });
  };

  const handleReleaseToRc = async () => {
    await fetch('/api/release_to_rc', { method: 'POST' });
  };

  const handleSetMode = async (mode: string, token?: string) => {
    await fetch('/api/set_mode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode, token }),
    });
  };

  const handleAddTrigger = async (t: TriggerItem) => {
    await fetch('/api/triggers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(t),
    });
    await loadTriggers();
  };

  const handleDeleteTrigger = async (id: string) => {
    await fetch(`/api/triggers/${id}`, { method: 'DELETE' });
    await loadTriggers();
  };

  // 3D Scan Handlers
  const handleStartScan = async () => {
    const res = await fetch('/api/3d_scan/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resolution: 'high' }),
    });
    const data = await res.json();
    setActiveSessionId(data.session_id);
  };

  const handleStopScan = async () => {
    await fetch('/api/3d_scan/stop', { method: 'POST' });
    setActiveSessionId(null);
  };

  const handleScrub = async (timeMs: number) => {
    setCurrentTimeMs(timeMs);
    if (!activeSessionId) return;
    try {
      const res = await fetch(`/api/3d_timeline/${activeSessionId}?time_ms=${timeMs}`);
      if (res.ok) {
        const data = await res.json();
        setPoints(data.points || []);
      }
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div style={{ maxWidth: '1440px', margin: '0 auto', padding: '16px' }}>
      {/* Header */}
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', borderBottom: '1px solid #30363d', paddingBottom: '12px' }}>
        <div>
          <h1 style={{ fontSize: '20px', fontWeight: 'bold', color: '#f0f6fc' }}>
            DJI Ground Station <span style={{ fontSize: '13px', color: '#58a6ff', fontWeight: 'normal' }}>v0.1.0</span>
          </h1>
          <div style={{ fontSize: '12px', color: '#8b949e' }}>
            Single Flight Authority | Hermes FastMCP | Venice AI | Human Pilot in Command
          </div>
        </div>
        <div style={{ width: '220px' }}>
          <EmergencyStopButton onEmergencyStop={handleEmergencyStop} />
        </div>
      </header>

      {/* Top HUD */}
      <div style={{ marginBottom: '16px' }}>
        <TelemetryHUD telemetry={telemetry} status={status} />
        <GamepadController
          isManualMode={status?.mode === 'manual_sidecar'}
          onEmergencyStop={handleEmergencyStop}
        />
      </div>

      {/* Main Grid: Left Video & AI, Right 3D Viewport */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
        {/* Left Column: FPV Video + Scene Transcript */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <VideoPlayer
            isFlying={status?.is_flying ?? false}
            videoFresh={status?.video_fresh ?? true}
            ageMs={status?.video_age_ms ?? 0}
          />
          <SceneTranscript scene={scene} onRefreshScene={refreshScene} />
        </div>

        {/* Right Column: 3D Point Cloud Viewport + Timeline Scrubber */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <ThreeDViewer
            points={points}
            dronePose={telemetry ? { x: telemetry.vx * 2, y: telemetry.vy * 2, z: telemetry.altitude_agl, yaw_deg: telemetry.yaw, pitch_deg: telemetry.pitch } : undefined}
            activeSessionId={activeSessionId}
            onStartScan={handleStartScan}
            onStopScan={handleStopScan}
          />
          <TimelineScrubber
            sessionId={activeSessionId ?? undefined}
            maxTimeMs={timelineMaxMs}
            currentTimeMs={currentTimeMs}
            onScrub={handleScrub}
          />
        </div>
      </div>

      {/* Bottom Grid: Mode Controls & Safety Triggers */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
        <ModeSelector
          activeMode={status?.mode ?? 'disarmed'}
          onSetMode={handleSetMode}
          onTakeoff={handleTakeoff}
          onLand={handleLand}
          onRth={handleRth}
          onReleaseToRc={handleReleaseToRc}
          onArmMotion={handleArmMotion}
        />
        <TriggerManager
          triggers={triggers}
          onAddTrigger={handleAddTrigger}
          onDeleteTrigger={handleDeleteTrigger}
        />
      </div>
    </div>
  );
};
export default App;
