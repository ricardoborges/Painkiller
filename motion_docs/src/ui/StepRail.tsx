import React from 'react';
import { useCurrentFrame } from 'remotion';
import { C, F } from '../theme';
import { ease } from './anim';

export const RAIL_STEPS = ['Interview', 'Spec', 'Sandbox', 'Ask', 'Verify', 'Deploy'];

// Indicador persistente do passo atual, no topo do vídeo. `active` é o passo
// por janela de frames: [início, passo].
export const StepRail: React.FC<{ show: [number, number]; marks: [number, number][] }> = ({ show, marks }) => {
  const frame = useCurrentFrame();
  const visible = ease(frame, show[0], 14) * (1 - ease(frame, show[1] - 10, 12));
  if (visible <= 0) return null;
  const active = marks.reduce((acc, [at, step]) => (frame >= at ? step : acc), 0);
  return (
    <div style={{ position: 'absolute', top: 44, right: 120, display: 'flex', alignItems: 'center', gap: 10, opacity: visible, translate: `0 ${(1 - visible) * -16}px` }}>
      {RAIL_STEPS.map((s, i) => {
        const on = i === active;
        const past = i < active;
        return (
          <React.Fragment key={s}>
            {i > 0 && <div style={{ width: 22, height: 2, background: past || on ? C.blue : C.line }} />}
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8, padding: on ? '8px 16px' : '8px 10px', borderRadius: 999,
              background: on ? C.blue : 'rgba(255,255,255,0.85)', border: `1.5px solid ${on ? C.blue : past ? C.sky : C.line}`,
              fontFamily: F.sans, fontWeight: 700, fontSize: 19, color: on ? C.white : past ? C.blue : C.muted,
            }}>
              <span style={{ fontFamily: F.mono, fontSize: 17 }}>{i + 1}</span>
              {on && <span>{s}</span>}
            </div>
          </React.Fragment>
        );
      })}
    </div>
  );
};
