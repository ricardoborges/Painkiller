import React from 'react';
import { Interactive } from 'remotion';
import { C, F } from '../theme';
import { ease, lerp, pop } from '../ui/anim';
import { Arrow, Card, Heading, Icon, Tag, Typewriter, Wires } from '../ui/kit';
import { Sfx } from '../ui/Sfx';
import { Stage, sceneSchema, useScene, type SceneProps } from '../ui/Stage';

const TASKS = [
  { id: 'T1', title: 'Data model', x: 1000, y: 380 },
  { id: 'T2', title: 'Booking API', x: 1000, y: 565 },
  { id: 'T3', title: 'Booking page', x: 1000, y: 750 },
  { id: 'T5', title: 'Admin calendar', x: 1430, y: 380 },
  { id: 'T4', title: 'Email confirmation', x: 1430, y: 565 },
  { id: 'T6', title: 'End-to-end tests', x: 1430, y: 750 },
];
// Dependências como caminhos entre cartões (de -> para).
const DEPS = [
  'M 1180 510 L 1180 560', // T1 -> T2
  'M 1180 695 L 1180 745', // T2 -> T3
  'M 1360 445 L 1425 445', // T1 -> T5
  'M 1360 630 L 1425 630', // T2 -> T4
  'M 1610 695 L 1610 745', // T4 -> T6
  'M 1360 815 L 1425 815', // T3 -> T6
];
const LINES = [0.92, 0.7, 0.86, 0.52, 0.95, 0.74, 0.6];

// 4. Spec-driven: a spec é escrita, versionada e decomposta em tarefas atômicas.
const SpecInner: React.FC<SceneProps> = ({ title, subtitle, voiceover, showCaptions, withBackground }) => {
  const { frame, fps, cue } = useScene(voiceover);
  const write = cue('written');
  const split = ease(frame, cue('broken'), 26);
  const stamp = pop(frame, fps, cue('spec-driven'), 10);
  const commit = pop(frame, fps, cue('committed'), 14);
  const accept = cue('acceptance');
  const deps = cue('dependencies');
  return (
    <Stage id="spec" voiceover={voiceover} showCaptions={showCaptions} withBackground={withBackground}>
      <Heading eyebrow="Step 2 · Spec-driven" title={title} subtitle={subtitle} />
      <div style={{ position: 'absolute', left: lerp(split, 700, 120), top: 370, opacity: ease(frame, write - 8, 14), scale: String(0.92 + 0.08 * ease(frame, write - 8, 20)) }}>
        <Card style={{ width: 540, height: 520, padding: 34, position: 'relative' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 22 }}>
            <Icon name="doc" size={36} />
            <span style={{ fontFamily: F.mono, fontSize: 20, color: C.inkSoft }}>docs/superpowers/specs/booking.md</span>
          </div>
          <div style={{ fontWeight: 800, fontSize: 36, color: C.ink, marginBottom: 24 }}>
            <Typewriter text="Clinic booking: design" at={write} cps={30} />
          </div>
          {LINES.map((w, i) => (
            <div key={i} style={{ height: 14, borderRadius: 7, marginBottom: 20, background: i % 3 === 0 ? C.sky : C.ice, width: `${w * 100 * ease(frame, write + 8 + i * 4, 14)}%` }} />
          ))}
          <div style={{
            position: 'absolute', left: 34, bottom: 30, display: 'flex', alignItems: 'center', gap: 12, padding: '10px 18px', borderRadius: 14,
            background: C.blue, opacity: commit, translate: `0 ${(1 - commit) * 16}px`,
          }}>
            <Icon name="branch" size={26} color={C.white} />
            <span style={{ fontFamily: F.mono, fontSize: 21, color: C.white }}>committed to main · a3f9c1e</span>
          </div>
          <div style={{
            position: 'absolute', right: -36, top: -26, padding: '10px 20px', borderRadius: 12, border: `3px solid ${C.blue}`, background: C.white,
            color: C.blue, fontFamily: F.mono, fontWeight: 600, fontSize: 24, letterSpacing: 2,
            opacity: Math.min(1, stamp * 1.5), scale: String(2 - stamp), rotate: `${-8 + (1 - stamp) * -20}deg`,
          }}>
            SPEC-DRIVEN
          </div>
        </Card>
      </div>
      <Wires>
        {TASKS.map((t, i) => (
          <Arrow key={t.id} d={`M 670 630 C 820 630, 860 ${t.y + 65}, ${t.x - 6} ${t.y + 65}`} progress={ease(frame, cue('small') + i * 3, 16)} color={C.sky} width={3} head={false} />
        ))}
        {DEPS.map((d, i) => <Arrow key={d} d={d} progress={ease(frame, deps + i * 3, 12)} width={4} />)}
      </Wires>
      {TASKS.map((t, i) => {
        const p = pop(frame, fps, cue('small') + 6 + i * 3, 13);
        return (
          <div key={t.id} style={{ position: 'absolute', left: t.x, top: t.y, opacity: Math.min(1, p * 1.4), scale: String(0.6 + 0.4 * p) }}>
            <Card style={{ width: 360, height: 130, padding: '20px 24px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <Tag>{t.id}</Tag>
                <span style={{ fontWeight: 800, fontSize: 25, color: C.ink }}>{t.title}</span>
              </div>
              <div style={{ display: 'flex', gap: 10 }}>
                {[0, 1, 2].map((k) => {
                  const on = ease(frame, accept + i * 2 + k * 4, 8);
                  return (
                    <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <div style={{ width: 22, height: 22, borderRadius: 6, background: on > 0.5 ? C.blue : C.ice, display: 'grid', placeItems: 'center' }}>
                        {on > 0.5 && <Icon name="check" size={16} color={C.white} stroke={3} />}
                      </div>
                      <div style={{ width: 54, height: 8, borderRadius: 4, background: C.line }} />
                    </div>
                  );
                })}
              </div>
            </Card>
          </div>
        );
      })}
      <Sfx name="page-turn" at={cue('broken')} volume={0.35} />
    </Stage>
  );
};

export const Spec = Interactive.withSchema({
  Component: SpecInner,
  componentName: 'Spec',
  schema: sceneSchema('The spec drives everything', 'written, versioned, then split into atomic tasks'),
  wrapInSequence: true,
  layout: 'absolute-fill',
});
