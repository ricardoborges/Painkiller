import React from 'react';
import { Interactive } from 'remotion';
import { C, F } from '../theme';
import { ease, pop } from '../ui/anim';
import { Chip, Logo, Wordmark } from '../ui/kit';
import { Stage, sceneSchema, useScene, type SceneProps } from '../ui/Stage';

const STEPS = [
  { word: 'conversation', label: 'Conversation' },
  { word: 'spec', label: 'Spec' },
  { word: 'production', label: 'Production' },
];

// 11. Encerramento.
const OutroInner: React.FC<SceneProps> = ({ title, subtitle, voiceover, showCaptions, withBackground }) => {
  const { frame, fps, cue } = useScene(voiceover);
  const logo = pop(frame, fps, cue('painkiller') - 6, 12);
  const last = cue('production');
  return (
    <Stage id="outro" voiceover={voiceover} showCaptions={showCaptions} withBackground={withBackground}>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', paddingBottom: 80 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 36, opacity: Math.min(1, logo * 1.4), scale: String(0.8 + 0.2 * logo) }}>
          <div style={{ filter: 'drop-shadow(0 26px 34px rgba(31,94,255,0.35))' }}>
            <Logo size={180} spin={(1 - logo) * 120} />
          </div>
          <Wordmark size={150} />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 24, marginTop: 56 }}>
          {STEPS.map((s, i) => {
            const p = pop(frame, fps, cue(s.word) - 4, 14);
            return (
              <React.Fragment key={s.word}>
                {i > 0 && <div style={{ width: 70 * ease(frame, cue(s.word) - 8, 10), height: 4, borderRadius: 2, background: C.sky }} />}
                <div style={{ opacity: Math.min(1, p * 1.4), translate: `0 ${(1 - p) * 20}px` }}>
                  <Chip active={i === 2 && frame >= last} style={{ fontSize: 34, padding: '16px 32px' }}>{s.label}</Chip>
                </div>
              </React.Fragment>
            );
          })}
        </div>
        <div style={{ marginTop: 56, textAlign: 'center', opacity: ease(frame, last + 20, 16) }}>
          <div style={{ fontWeight: 700, fontSize: 34, color: C.ink }}>{title}</div>
          <div style={{ fontFamily: F.mono, fontSize: 28, color: C.blue, marginTop: 8 }}>{subtitle}</div>
        </div>
      </div>
    </Stage>
  );
};

export const Outro = Interactive.withSchema({
  Component: OutroInner,
  componentName: 'Outro',
  schema: sceneSchema('Self-hosted. Your code, your keys, your servers.', 'github.com/ricardoborges/Painkiller'),
  wrapInSequence: true,
  layout: 'absolute-fill',
});
