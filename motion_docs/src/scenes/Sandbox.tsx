import React from 'react';
import { Interactive } from 'remotion';
import { C, F } from '../theme';
import { ease, keys, pop } from '../ui/anim';
import { AgentBot, Card, ContainerBox, Heading, Icon, Pop, Tag } from '../ui/kit';
import { Stage, sceneSchema, useScene, type SceneProps } from '../ui/Stage';

const SLOTS = [
  { id: 'T1', x: 120, y: 380 },
  { id: 'T2', x: 560, y: 380 },
  { id: 'T3', x: 120, y: 650 },
  { id: 'T4', x: 560, y: 650 },
];
const FEED = [
  'Read docs/superpowers/plans/booking.md',
  'Skill: test-driven-development',
  'Write tests/test_bookings.py',
  'Run pytest -q  (1 failed)',
  'Edit api/bookings.py',
  'Run pytest -q  (6 passed)',
  'git commit -m "booking API"',
];

// 5. Uma sandbox por tarefa, cada uma no seu branch, com atividade ao vivo.
const SandboxInner: React.FC<SceneProps> = ({ title, subtitle, voiceover, showCaptions, withBackground }) => {
  const { frame, fps, cue } = useScene(voiceover);
  const fly = cue('sandboxed');
  const branch = cue('branch');
  const parallel = cue('parallel');
  const live = cue('watch');
  return (
    <Stage id="sandbox" voiceover={voiceover} showCaptions={showCaptions} withBackground={withBackground}>
      <Heading eyebrow="Step 3 · Orchestration" title={title} subtitle={subtitle} />
      {SLOTS.map((s, i) => {
        const p = pop(frame, fps, fly + i * 4, 14);
        const work = ease(frame, parallel + i * 5, 60 + i * 25, (v) => v);
        return (
          <div key={s.id} style={{ position: 'absolute', left: s.x, top: s.y, opacity: Math.min(1, p * 1.4), scale: String(0.6 + 0.4 * p) }}>
            <ContainerBox label={s.id} sublabel="sandbox" width={410} height={240} active={i === 1 && frame > live}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 22, padding: '22px 24px 0' }}>
                <AgentBot size={92} busy={frame > parallel} />
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: F.mono, fontSize: 22, color: C.blueDeep, opacity: ease(frame, branch + i * 4, 12) }}>
                    <Icon name="branch" size={24} />
                    feature/{s.id}
                  </div>
                  <div style={{ marginTop: 18, height: 12, borderRadius: 6, background: C.ice, overflow: 'hidden' }}>
                    <div style={{ width: `${work * (70 + i * 7)}%`, height: '100%', background: `linear-gradient(90deg, ${C.sky}, ${C.blue})` }} />
                  </div>
                  <div style={{ marginTop: 10, fontSize: 20, fontWeight: 600, color: C.inkSoft }}>
                    {frame > parallel ? 'working…' : 'ready'}
                  </div>
                </div>
              </div>
            </ContainerBox>
          </div>
        );
      })}
      {/* tarefas do backlog voam para dentro dos contentores */}
      {SLOTS.map((s, i) => {
        const t = keys(frame, [[fly - 24 + i * 4, 0], [fly + i * 4, 1]]);
        const gone = ease(frame, fly + i * 4, 6);
        return (
          <div key={s.id} style={{
            position: 'absolute', left: 1180 + (s.x + 30 - 1180) * t, top: 420 + i * 100 + (s.y + 10 - 420 - i * 100) * t,
            opacity: ease(frame, 0, 10) * (1 - gone), scale: String(1 - 0.3 * t),
          }}>
            <Card style={{ width: 380, padding: '18px 22px', display: 'flex', alignItems: 'center', gap: 12 }}>
              <Tag>{s.id}</Tag>
              <span style={{ fontWeight: 700, fontSize: 24, color: C.ink }}>backlog task</span>
            </Card>
          </div>
        );
      })}
      <Pop at={live} from={0.85} style={{ left: 1060, top: 380 }}>
        <Card style={{ width: 740, height: 510, padding: 30 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 18 }}>
            <div style={{ width: 16, height: 16, borderRadius: 8, background: C.blue, opacity: frame % 30 < 18 ? 1 : 0.3 }} />
            <span style={{ fontWeight: 800, fontSize: 30, color: C.ink }}>Live activity</span>
            <span style={{ marginLeft: 'auto', fontFamily: F.mono, fontSize: 20, color: C.inkSoft }}>T2 · feature/T2</span>
          </div>
          {FEED.map((line, i) => {
            const t = ease(frame, live + 6 + i * 6, 10);
            return (
              <div key={line} style={{
                display: 'flex', alignItems: 'center', gap: 12, padding: '9px 0', borderTop: `1px solid ${C.line}`,
                fontFamily: F.mono, fontSize: 22, color: i === FEED.length - 1 ? C.blue : C.ink, opacity: t, translate: `${(1 - t) * 20}px 0`,
              }}>
                <span style={{ color: C.sky }}>›</span>
                {line}
              </div>
            );
          })}
        </Card>
      </Pop>
    </Stage>
  );
};

export const Sandbox = Interactive.withSchema({
  Component: SandboxInner,
  componentName: 'Sandbox',
  schema: sceneSchema('One sandbox per task', 'isolated containers, one branch each'),
  wrapInSequence: true,
  layout: 'absolute-fill',
});
