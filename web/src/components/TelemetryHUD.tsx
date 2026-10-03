import React from 'react';
import { AuthorityStatus, TelemetryData } from '../types.ts';

interface Props {
  telemetry?: TelemetryData;
  status?: AuthorityStatus;
}

export const TelemetryHUD: React.FC<Props> = ({ telemetry, status }) => {
  const alt = telemetry?.altitude_agl ?? status?.altitude_agl ?? 0.0;
  const batt = telemetry?.battery_percent ?? status?.battery_percent ?? 0;
  const sats = telemetry?.gps_satellite_count ?? 0;
  const state = status?.state ?? 'DISCONNECTED';
  const mode = status?.mode ?? 'disarmed';

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))',
      gap: '10px',
      padding: '12px',
      backgroundColor: '#161b22',
      borderRadius: '8px',
      border: '1px solid #30363d'
    }}>
      <div>
        <div style={{ fontSize: '11px', color: '#8b949e', textTransform: 'uppercase' }}>State</div>
        <div style={{ fontSize: '14px', fontWeight: 'bold', color: state.includes('EMERGENCY') ? '#f85149' : '#58a6ff' }}>
          {state}
        </div>
      </div>
      <div>
        <div style={{ fontSize: '11px', color: '#8b949e', textTransform: 'uppercase' }}>Active Mode</div>
        <div style={{ fontSize: '14px', fontWeight: 'bold', color: '#7ee787' }}>{mode}</div>
      </div>
      <div>
        <div style={{ fontSize: '11px', color: '#8b949e', textTransform: 'uppercase' }}>Altitude AGL</div>
        <div style={{ fontSize: '14px', fontWeight: 'bold', color: '#c9d1d9' }}>{alt.toFixed(1)} m</div>
      </div>
      <div>
        <div style={{ fontSize: '11px', color: '#8b949e', textTransform: 'uppercase' }}>Battery</div>
        <div style={{ fontSize: '14px', fontWeight: 'bold', color: batt < 25 ? '#f85149' : '#3fb950' }}>{batt}%</div>
      </div>
      <div>
        <div style={{ fontSize: '11px', color: '#8b949e', textTransform: 'uppercase' }}>GPS Sats</div>
        <div style={{ fontSize: '14px', fontWeight: 'bold', color: sats >= 10 ? '#3fb950' : '#d29922' }}>{sats}</div>
      </div>
      <div>
        <div style={{ fontSize: '11px', color: '#8b949e', textTransform: 'uppercase' }}>Watchdog</div>
        <div style={{ fontSize: '14px', fontWeight: 'bold', color: status?.watchdog_ok ? '#3fb950' : '#f85149' }}>
          {status?.watchdog_ok ? 'PASS (500ms)' : 'TIMEOUT'}
        </div>
      </div>
    </div>
  );
};
