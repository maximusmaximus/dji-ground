import React from 'react';
import { SceneDescription } from '../types.ts';

interface Props {
  scene?: SceneDescription;
  onRefreshScene: () => Promise<void>;
}

export const SceneTranscript: React.FC<Props> = ({ scene, onRefreshScene }) => {
  return (
    <div style={{ backgroundColor: '#161b22', padding: '16px', borderRadius: '8px', border: '1px solid #30363d' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <h3 style={{ fontSize: '14px', color: '#8b949e', textTransform: 'uppercase' }}>
          Visual Scene Description
        </h3>
        <button
          onClick={onRefreshScene}
          style={{ padding: '4px 10px', backgroundColor: '#30363d', border: 'none', borderRadius: '4px', color: '#c9d1d9', fontSize: '12px', cursor: 'pointer' }}
        >
          Describe Now
        </button>
      </div>

      <div style={{ backgroundColor: '#0d1117', padding: '12px', borderRadius: '6px', minHeight: '60px', marginBottom: '12px' }}>
        <p style={{ fontSize: '13px', lineHeight: '1.5', color: '#e6edf3' }}>
          {scene?.caption || 'Awaiting scene description...'}
        </p>
      </div>

      {scene?.objects && scene.objects.length > 0 && (
        <div>
          <div style={{ fontSize: '11px', color: '#8b949e', textTransform: 'uppercase', marginBottom: '6px' }}>Detected Objects</div>
          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
            {scene.objects.map((obj, i) => (
              <span key={i} style={{ backgroundColor: '#21262d', border: '1px solid #388bfd', padding: '2px 8px', borderRadius: '12px', fontSize: '11px', color: '#58a6ff' }}>
                {obj.label} ({Math.round(obj.conf * 100)}%)
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
