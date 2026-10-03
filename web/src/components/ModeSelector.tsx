import React, { useState } from 'react';

interface Props {
  activeMode: string;
  onSetMode: (mode: string, token?: string) => Promise<void>;
  onTakeoff: (token: string) => Promise<void>;
  onLand: () => Promise<void>;
  onRth: () => Promise<void>;
  onReleaseToRc: () => Promise<void>;
  onArmMotion: (mode: string) => Promise<string>;
}

const MODES = [
  { id: 'narrate', name: 'Narrate', description: 'Zero sticks, periodic scene descriptions' },
  { id: 'sentinel', name: 'Sentinel', description: 'Hover, evaluate triggers & scene diffs' },
  { id: 'follow', name: 'Follow', description: 'Visual tracking with speed/geofence cap' },
  { id: 'orbit', name: 'Orbit', description: 'POI circle inspection & sector notes' },
  { id: 'indoor_grid', name: 'Indoor Grid', description: 'Lawnmower search inside room polygon' },
  { id: 'outdoor_box', name: 'Outdoor Box', description: 'Perimeter box survey in geofence' },
  { id: 'manual_sidecar', name: 'Manual Sidecar', description: 'Gamepad flight with AI vision guardian' },
];

export const ModeSelector: React.FC<Props> = ({
  activeMode,
  onSetMode,
  onTakeoff,
  onLand,
  onRth,
  onReleaseToRc,
  onArmMotion,
}) => {
  const [loading, setLoading] = useState(false);
  const [armingMode, setArmingMode] = useState<string | null>(null);

  const handleSelectMode = async (modeId: string) => {
    setLoading(true);
    try {
      if (['follow', 'orbit', 'indoor_grid', 'outdoor_box', 'manual_sidecar'].includes(modeId)) {
        // Requires token
        const token = await onArmMotion(modeId);
        await onSetMode(modeId, token);
      } else {
        await onSetMode(modeId);
      }
    } catch (e: any) {
      alert(`Mode switch failed: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleTakeoff = async () => {
    setLoading(true);
    try {
      const token = await onArmMotion('takeoff');
      await onTakeoff(token);
    } catch (e: any) {
      alert(`Takeoff failed: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ backgroundColor: '#161b22', padding: '16px', borderRadius: '8px', border: '1px solid #30363d' }}>
      <h3 style={{ fontSize: '14px', marginBottom: '12px', color: '#8b949e', textTransform: 'uppercase' }}>
        Flight Modes & Actions
      </h3>

      {/* Flight Action Commands */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '16px', flexWrap: 'wrap' }}>
        <button
          onClick={handleTakeoff}
          disabled={loading}
          style={{ padding: '8px 16px', backgroundColor: '#238636', border: 'none', borderRadius: '6px', color: '#fff', fontWeight: 'bold', cursor: 'pointer' }}
        >
          Takeoff (Arm Token)
        </button>
        <button
          onClick={onLand}
          disabled={loading}
          style={{ padding: '8px 16px', backgroundColor: '#30363d', border: 'none', borderRadius: '6px', color: '#c9d1d9', fontWeight: 'bold', cursor: 'pointer' }}
        >
          Land
        </button>
        <button
          onClick={onRth}
          disabled={loading}
          style={{ padding: '8px 16px', backgroundColor: '#1f6feb', border: 'none', borderRadius: '6px', color: '#fff', fontWeight: 'bold', cursor: 'pointer' }}
        >
          Return-to-Home
        </button>
        <button
          onClick={onReleaseToRc}
          disabled={loading}
          style={{ padding: '8px 16px', backgroundColor: '#6e7681', border: 'none', borderRadius: '6px', color: '#fff', fontWeight: 'bold', cursor: 'pointer' }}
        >
          Release to RC
        </button>
      </div>

      {/* Mode Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: '8px' }}>
        {MODES.map((m) => {
          const isActive = activeMode === m.id;
          return (
            <button
              key={m.id}
              onClick={() => handleSelectMode(m.id)}
              disabled={loading}
              title={m.description}
              style={{
                padding: '10px',
                textAlign: 'left',
                backgroundColor: isActive ? '#1f6feb' : '#21262d',
                border: `1px solid ${isActive ? '#388bfd' : '#30363d'}`,
                borderRadius: '6px',
                color: '#fff',
                cursor: 'pointer',
              }}
            >
              <div style={{ fontWeight: 'bold', fontSize: '13px' }}>{m.name}</div>
              <div style={{ fontSize: '11px', color: isActive ? '#e6edf3' : '#8b949e', marginTop: '4px' }}>
                {m.description.slice(0, 28)}...
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
};
