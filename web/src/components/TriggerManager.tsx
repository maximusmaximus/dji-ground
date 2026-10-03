import React, { useState } from 'react';
import { TriggerItem } from '../types.ts';

interface Props {
  triggers: TriggerItem[];
  onAddTrigger: (t: TriggerItem) => Promise<void>;
  onDeleteTrigger: (id: string) => Promise<void>;
}

const ALLOWED_ACTIONS = ['notify', 'photo', 'hover', 'yaw_toward', 'start_mode', 'rth', 'land'] as const;

export const TriggerManager: React.FC<Props> = ({ triggers, onAddTrigger, onDeleteTrigger }) => {
  const [name, setName] = useState('');
  const [action, setAction] = useState<TriggerItem['action']>('hover');
  const [conditionType, setConditionType] = useState('object_detected');
  const [conditionValue, setConditionValue] = useState('red_cone');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name) return;
    const item: TriggerItem = {
      trigger_id: `trig_${Date.now()}`,
      name,
      action,
      condition_type: conditionType,
      condition_value: conditionValue,
    };
    await onAddTrigger(item);
    setName('');
  };

  return (
    <div style={{ backgroundColor: '#161b22', padding: '16px', borderRadius: '8px', border: '1px solid #30363d' }}>
      <h3 style={{ fontSize: '14px', marginBottom: '12px', color: '#8b949e', textTransform: 'uppercase' }}>
        Safety Triggers (Closed Action Enum)
      </h3>

      <form onSubmit={handleSubmit} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '8px', marginBottom: '16px' }}>
        <input
          type="text"
          placeholder="Rule Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          style={{ padding: '6px 10px', backgroundColor: '#0d1117', border: '1px solid #30363d', borderRadius: '4px', color: '#fff' }}
        />
        <select
          value={conditionType}
          onChange={(e) => setConditionType(e.target.value)}
          style={{ padding: '6px 10px', backgroundColor: '#0d1117', border: '1px solid #30363d', borderRadius: '4px', color: '#fff' }}
        >
          <option value="object_detected">Object Detected</option>
          <option value="osd_text">OSD Warning</option>
          <option value="diff_detected">Scene Diff</option>
          <option value="telemetry">Telemetry Check</option>
        </select>
        <input
          type="text"
          placeholder="Value (e.g. red_cone)"
          value={conditionValue}
          onChange={(e) => setConditionValue(e.target.value)}
          style={{ padding: '6px 10px', backgroundColor: '#0d1117', border: '1px solid #30363d', borderRadius: '4px', color: '#fff' }}
        />
        <select
          value={action}
          onChange={(e) => setAction(e.target.value as any)}
          style={{ padding: '6px 10px', backgroundColor: '#0d1117', border: '1px solid #30363d', borderRadius: '4px', color: '#fff' }}
        >
          {ALLOWED_ACTIONS.map((a) => (
            <option key={a} value={a}>{a.toUpperCase()}</option>
          ))}
        </select>
        <button
          type="submit"
          style={{ padding: '6px 12px', backgroundColor: '#238636', border: 'none', borderRadius: '4px', color: '#fff', fontWeight: 'bold', cursor: 'pointer' }}
        >
          + Add Trigger
        </button>
      </form>

      {/* Triggers List */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        {triggers.length === 0 && <div style={{ fontSize: '12px', color: '#8b949e' }}>No active triggers configured.</div>}
        {triggers.map((t) => (
          <div key={t.trigger_id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', backgroundColor: '#21262d', padding: '6px 10px', borderRadius: '4px', fontSize: '12px' }}>
            <div>
              <strong>{t.name}</strong>: IF <code>{t.condition_type}</code> = "{t.condition_value}" THEN <code>{t.action}</code>
            </div>
            <button
              onClick={() => onDeleteTrigger(t.trigger_id)}
              style={{ backgroundColor: 'transparent', border: 'none', color: '#f85149', cursor: 'pointer', fontWeight: 'bold' }}
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </div>
  );
};
