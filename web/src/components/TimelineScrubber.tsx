import React, { useState } from 'react';

interface Props {
  sessionId?: string;
  maxTimeMs: number;
  currentTimeMs: number;
  onScrub: (timeMs: number) => void;
}

export const TimelineScrubber: React.FC<Props> = ({
  sessionId,
  maxTimeMs,
  currentTimeMs,
  onScrub,
}) => {
  const [isPlaying, setIsPlaying] = useState(false);

  const durationSec = Math.max(1, Math.round(maxTimeMs / 1000));
  const currentSec = Math.round(currentTimeMs / 1000);

  const handleSliderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const sec = parseFloat(e.target.value);
    onScrub(sec * 1000);
  };

  return (
    <div style={{ backgroundColor: '#161b22', padding: '12px 16px', borderRadius: '8px', border: '1px solid #30363d', marginTop: '12px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
        <div style={{ fontSize: '12px', fontWeight: 'bold', color: '#8b949e', textTransform: 'uppercase' }}>
          3D Mission Timeline Scrubber
        </div>
        <div style={{ fontSize: '12px', color: '#58a6ff', fontFamily: 'monospace' }}>
          {currentSec}s / {durationSec}s {sessionId ? `[Session: ${sessionId}]` : ''}
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <button
          onClick={() => setIsPlaying(!isPlaying)}
          style={{ padding: '4px 10px', backgroundColor: '#21262d', border: '1px solid #30363d', borderRadius: '4px', color: '#c9d1d9', cursor: 'pointer', fontSize: '12px' }}
        >
          {isPlaying ? '⏸ Pause' : '▶ Play'}
        </button>
        <input
          type="range"
          min="0"
          max={durationSec}
          step="0.25"
          value={currentSec}
          onChange={handleSliderChange}
          style={{ flex: 1, cursor: 'pointer' }}
        />
      </div>
    </div>
  );
};
