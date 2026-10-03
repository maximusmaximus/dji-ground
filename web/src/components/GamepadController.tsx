import React, { useEffect, useState } from 'react';

interface Props {
  isManualMode: boolean;
  onEmergencyStop: () => Promise<void>;
}

export const GamepadController: React.FC<Props> = ({ isManualMode, onEmergencyStop }) => {
  const [connected, setConnected] = useState(false);
  const [padName, setPadName] = useState('');
  const [sticks, setSticks] = useState({ pitch: 0, roll: 0, yaw: 0, throttle: 0 });

  useEffect(() => {
    let ws: WebSocket;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host || 'localhost:8000';

    if (isManualMode) {
      ws = new WebSocket(`${protocol}//${host}/ws/manual_stick`);
    }

    let animId: number;

    const scanGamepad = () => {
      const pads = navigator.getGamepads ? navigator.getGamepads() : [];
      let activePad: Gamepad | null = null;
      for (const p of pads) {
        if (p) {
          activePad = p;
          break;
        }
      }

      if (activePad) {
        setConnected(true);
        setPadName(activePad.id.slice(0, 30));

        // Read axes: invert Y axis so pushing forward is positive pitch
        const roll = Math.abs(activePad.axes[0]) > 0.08 ? activePad.axes[0] : 0.0;
        const pitch = Math.abs(activePad.axes[1]) > 0.08 ? -activePad.axes[1] : 0.0;
        const yaw = Math.abs(activePad.axes[2]) > 0.08 ? activePad.axes[2] : 0.0;
        const throttle = Math.abs(activePad.axes[3]) > 0.08 ? -activePad.axes[3] : 0.0;

        const currentSticks = {
          pitch: round(pitch, 2),
          roll: round(roll, 2),
          yaw: round(yaw, 2),
          throttle: round(throttle, 2),
        };
        setSticks(currentSticks);

        // Emergency stop on button 1 (B / Circle)
        if (activePad.buttons[1]?.pressed) {
          onEmergencyStop();
        }

        // Send sticks to gateway websocket if in manual_sidecar mode
        if (ws && ws.readyState === WebSocket.OPEN && isManualMode) {
          ws.send(JSON.stringify(currentSticks));
        }
      } else {
        setConnected(false);
      }

      animId = requestAnimationFrame(scanGamepad);
    };

    animId = requestAnimationFrame(scanGamepad);

    return () => {
      cancelAnimationFrame(animId);
      if (ws) ws.close();
    };
  }, [isManualMode, onEmergencyStop]);

  function round(val: number, decimals: number) {
    const factor = Math.pow(10, decimals);
    return Math.round(val * factor) / factor;
  }

  return (
    <div style={{ backgroundColor: '#161b22', padding: '12px 16px', borderRadius: '8px', border: '1px solid #30363d', marginTop: '12px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
        <div style={{ fontSize: '12px', fontWeight: 'bold', color: '#8b949e', textTransform: 'uppercase' }}>
          Hardware Gamepad / RC Sticks
        </div>
        <div style={{ fontSize: '12px', color: connected ? '#3fb950' : '#8b949e' }}>
          {connected ? `🎮 ${padName}` : 'No controller detected (Connect USB/Bluetooth)'}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px', textAlign: 'center' }}>
        <div style={{ background: '#0d1117', padding: '6px', borderRadius: '4px' }}>
          <div style={{ fontSize: '10px', color: '#8b949e' }}>PITCH</div>
          <div style={{ fontSize: '13px', fontWeight: 'bold', fontFamily: 'monospace' }}>{sticks.pitch}</div>
        </div>
        <div style={{ background: '#0d1117', padding: '6px', borderRadius: '4px' }}>
          <div style={{ fontSize: '10px', color: '#8b949e' }}>ROLL</div>
          <div style={{ fontSize: '13px', fontWeight: 'bold', fontFamily: 'monospace' }}>{sticks.roll}</div>
        </div>
        <div style={{ background: '#0d1117', padding: '6px', borderRadius: '4px' }}>
          <div style={{ fontSize: '10px', color: '#8b949e' }}>YAW</div>
          <div style={{ fontSize: '13px', fontWeight: 'bold', fontFamily: 'monospace' }}>{sticks.yaw}</div>
        </div>
        <div style={{ background: '#0d1117', padding: '6px', borderRadius: '4px' }}>
          <div style={{ fontSize: '10px', color: '#8b949e' }}>THROTTLE</div>
          <div style={{ fontSize: '13px', fontWeight: 'bold', fontFamily: 'monospace' }}>{sticks.throttle}</div>
        </div>
      </div>
    </div>
  );
};
