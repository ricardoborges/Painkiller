import React from 'react';
import { Interactive } from 'remotion';
import { C, F } from '../theme';
import { ease, pop } from '../ui/anim';
import { AgentBot, Arrow, Card, Chip, ContainerBox, Heading, Icon, Wires } from '../ui/kit';
import { Sfx } from '../ui/Sfx';
import { Stage, sceneSchema, useScene, type SceneProps } from '../ui/Stage';

const HARNESSES = [
  { word: 'antigravity', cmd: 'agy', name: 'Antigravity', model: 'Gemini' },
  { word: 'dsh', cmd: 'dsh', name: 'DeepSeek Harness', model: 'DeepSeek' },
  { word: 'maki', cmd: 'maki', name: 'Maki', model: 'DeepSeek' },
  { word: 'unreal', cmd: 'unreal', name: 'Unreal Agent', model: 'DeepSeek' },
];
const SKILLS = [
  { word: 'planning', name: 'writing-plans' },
  { word: 'test-driven', name: 'test-driven-development' },
  { word: 'debugging', name: 'systematic-debugging' },
];

// 6. Harness por projeto; as mesmas skills Superpowers em todos.
const HarnessInner: React.FC<SceneProps> = ({ title, subtitle, voiceover, showCaptions, withBackground }) => {
  const { frame, fps, cue } = useScene(voiceover);
  const starts = HARNESSES.map((h) => cue(h.word));
  const active = starts.reduce((acc, s, i) => (frame >= s ? i : acc), -1);
  const h = HARNESSES[Math.max(0, active)];
  const swap = active >= 0 ? pop(frame, fps, starts[active], 12) : 0;
  const sp = cue('superpowers');
  return (
    <Stage id="harness" voiceover={voiceover} showCaptions={showCaptions} withBackground={withBackground}>
      <Heading eyebrow="Harness-agnostic" title={title} subtitle={subtitle} />
      {HARNESSES.map((x, i) => {
        const on = active === i;
        const t = ease(frame, 4 + i * 4, 16);
        return (
          <div key={x.cmd} style={{ position: 'absolute', left: 120, top: 370 + i * 128, opacity: t, translate: `${(1 - t) * -30 + (on ? 24 : 0)}px 0` }}>
            <Card style={{
              width: 460, height: 108, padding: '0 26px', display: 'flex', alignItems: 'center', gap: 18,
              background: on ? C.blue : C.white, border: `1px solid ${on ? C.blue : C.line}`,
            }}>
              <span style={{ fontFamily: F.mono, fontSize: 22, fontWeight: 600, color: on ? C.white : C.blue, width: 92 }}>{x.cmd}</span>
              <div>
                <div style={{ fontWeight: 800, fontSize: 28, color: on ? C.white : C.ink }}>{x.name}</div>
                <div style={{ fontSize: 21, fontWeight: 600, color: on ? 'rgba(255,255,255,0.8)' : C.inkSoft }}>{x.model}</div>
              </div>
            </Card>
          </div>
        );
      })}
      <Wires>
        <Arrow d="M 610 620 L 690 620" progress={ease(frame, starts[0] - 6, 10)} width={5} />
        {SKILLS.map((s, i) => (
          <Arrow key={s.word} d={`M 1330 ${505 + i * 120} C 1260 ${505 + i * 120}, 1270 620, 1215 620`} progress={ease(frame, cue(s.word), 14)} color={C.sky} width={4} />
        ))}
      </Wires>
      <div style={{ position: 'absolute', left: 700, top: 380, opacity: ease(frame, 2, 16) }}>
        <ContainerBox label="project sandbox" width={500} height={480} active={active >= 0}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: 34, gap: 18 }}>
            <AgentBot size={140} busy={active >= 0} />
            <div style={{ height: 96, display: 'flex', flexDirection: 'column', alignItems: 'center', opacity: active >= 0 ? Math.min(1, swap * 1.4) : 0, scale: String(0.8 + 0.2 * swap) }}>
              <div style={{ fontWeight: 800, fontSize: 38, color: C.ink }}>{h.name}</div>
              <div style={{ fontFamily: F.mono, fontSize: 22, color: C.blue }}>model · {h.model}</div>
            </div>
            <div style={{ display: 'flex', gap: 8, opacity: ease(frame, sp, 12) }}>
              {SKILLS.map((s) => (
                <div key={s.word} style={{ width: 40, height: 10, borderRadius: 5, background: frame >= cue(s.word) + 12 ? C.blue : C.ice }} />
              ))}
            </div>
          </div>
        </ContainerBox>
      </div>
      <div style={{ position: 'absolute', left: 1330, top: 380, display: 'flex', alignItems: 'center', gap: 12, opacity: ease(frame, sp, 14) }}>
        <Icon name="spark" size={38} />
        <span style={{ fontWeight: 800, fontSize: 34, color: C.blue }}>Superpowers skills</span>
      </div>
      {SKILLS.map((s, i) => {
        const p = pop(frame, fps, cue(s.word) - 4, 13);
        return (
          <div key={s.word} style={{ position: 'absolute', left: 1330, top: 470 + i * 120, opacity: Math.min(1, p * 1.4), scale: String(0.7 + 0.3 * p) }}>
            <Chip active={frame >= cue(s.word) && frame < cue(s.word) + 24} style={{ fontFamily: F.mono, fontSize: 22, fontWeight: 600 }}>
              <Icon name="check" size={24} stroke={3} color={frame >= cue(s.word) && frame < cue(s.word) + 24 ? C.white : C.blue} />
              {s.name}
            </Chip>
          </div>
        );
      })}
      {starts.map((s, i) => <Sfx key={i} name="switch" at={s} volume={0.3} />)}
    </Stage>
  );
};

export const Harness = Interactive.withSchema({
  Component: HarnessInner,
  componentName: 'Harness',
  schema: sceneSchema('Bring the agent you prefer', 'one harness per project, the same skills'),
  wrapInSequence: true,
  layout: 'absolute-fill',
});
