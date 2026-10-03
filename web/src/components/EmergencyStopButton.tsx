import React from 'react';

interface Props {
  onEmergencyStop: () => Promise<void>;
}

export const EmergencyStopButton: React.FC<Props> = ({ onEmergencyStop }) => {
  return (
    <button
      onClick={onEmergencyStop}
      title="Immediate Emergency Motor Disarm & Stick Zero"
      style={{
        width: '100%',
        padding: '16px',
        backgroundColor: '#da3633',
        color: '#ffffff',
        border: '2px solid #f85149',
        borderRadius: '8px',
        fontSize: '16px',
        fontWeight: '900',
        letterSpacing: '1px',
        cursor: 'pointer',
        boxShadow: '0 4px 12px rgba(218, 54, 51, 0.4)',
        transition: 'background-color 0.15s ease',
      }}
      onMouseEnter={(e) => ((e.target as HTMLButtonElement).style.backgroundColor = '#b62324')}
      onMouseLeave={(e) => ((e.target as HTMLButtonElement).style.backgroundColor = '#da3633')}
    >
      🛑 EMERGENCY STOP
    </button>
  );
};
