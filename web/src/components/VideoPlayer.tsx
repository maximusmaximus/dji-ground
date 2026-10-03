import React from 'react';

interface Props {
  streamUrl?: string;
  isFlying: boolean;
  videoFresh: boolean;
  ageMs: number;
}

export const VideoPlayer: React.FC<Props> = ({
  streamUrl = '/video/mjpeg',
  isFlying,
  videoFresh,
  ageMs,
}) => {
  return (
    <div style={{ position: 'relative', width: '100%', height: '360px', backgroundColor: '#000', borderRadius: '8px', overflow: 'hidden' }}>
      <img
        src={streamUrl}
        alt="Live FPV Camera Feed"
        style={{ width: '100%', height: '100%', objectFit: 'contain' }}
        onError={(e) => {
          // Fallback if mjpeg not streaming yet
          (e.target as HTMLImageElement).src = 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360"><rect width="100%" height="100%" fill="%23161b22"/><text x="50%" y="50%" fill="%238b949e" font-family="sans-serif" font-size="16" text-anchor="middle">Awaiting H.264 Video Stream...</text></svg>';
        }}
      />
      {/* HUD Overlays */}
      <div style={{ position: 'absolute', top: 12, left: 12, display: 'flex', gap: '8px' }}>
        <span style={{
          backgroundColor: videoFresh ? 'rgba(46, 160, 67, 0.85)' : 'rgba(218, 54, 51, 0.85)',
          padding: '4px 8px', borderRadius: '4px', fontSize: '12px', fontWeight: 'bold', color: '#fff'
        }}>
          {videoFresh ? `LIVE (${ageMs}ms)` : `VIDEO LOST (${ageMs}ms)`}
        </span>
        {isFlying && (
          <span style={{ backgroundColor: 'rgba(56, 139, 253, 0.85)', padding: '4px 8px', borderRadius: '4px', fontSize: '12px', fontWeight: 'bold', color: '#fff' }}>
            AIRBORNE
          </span>
        )}
      </div>
    </div>
  );
};
