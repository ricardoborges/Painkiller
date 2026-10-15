import React from 'react';
import { Interactive } from 'remotion';
import { C } from '../theme';
import { ease } from '../ui/anim';
import { AgentBot, Card, ContainerBox, Cursor, Heading, Icon, Person, Pop } from '../ui/kit';
import { Sfx } from '../ui/Sfx';
import { Stage, sceneSchema, useScene, type SceneProps } from '../ui/Stage';

const Bubble: React.FC<{ from: 'agent' | 'analyst'; at: number; frame: number; children: React.ReactNode }> = ({ from, at, frame, children }) => {
  const t = ease(frame, at, 16);
  const agent = from === 'agent';
  return (
    <div
      style={{
        alignSelf: agent ? 'flex-start' : 'flex-end', maxWidth: 620, opacity: t, translate: `0 ${(1 - t) * 22}px`,
        background: agent ? C.frost : C.blue, color: agent ? C.ink : C.white, border: agent ? `1px solid ${C.line}` : 'none',
        borderRadius: agent ? '24px 24px 24px 6px' : '24px 24px 6px 24px', padding: '16px 24px',
        fontSize: 28, fontWeight: 600, lineHeight: 1.35,
      }}
    >
      {children}
    </div>
  );
};

// 3. Análise inicial: entrevista com o agente de brainstorming.
const InterviewInner: React.FC<SceneProps> = ({ title, subtitle, voiceover, showCaptions, withBackground }) => {
  const { frame, cue } = useScene(voiceover);
  const click = cue('choices') + 14;
  const picked = frame >= click;
  const clarity = ease(frame, cue('until'), cue('clear') + 12 - cue('until'));
  const skill = frame >= cue('superpowers');
  return (
    <Stage id="interview" voiceover={voiceover} showCaptions={showCaptions} withBackground={withBackground}>
      <Heading eyebrow="Step 1 · Initial analysis" title={title} subtitle={subtitle} />
      <Pop at={cue('interview') - 6} style={{ left: 120, top: 520 }}>
        <Person size={170} label="Analyst" />
      </Pop>
      <Pop at={cue('containerized')} style={{ left: 1360, top: 380 }}>
        <ContainerBox label="painkiller-agent" sublabel="docker" width={440} height={440} active={skill && frame < cue('skill') + 30}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: 40, gap: 26 }}>
            <AgentBot size={150} busy />
            <div style={{
              display: 'flex', alignItems: 'center', gap: 10, padding: '12px 20px', borderRadius: 16,
              background: skill ? C.blue : C.ice, color: skill ? C.white : C.blueDeep, scale: String(skill ? 1 + 0.06 * Math.max(0, 1 - (frame - cue('superpowers')) / 12) : 1),
            }}>
              <Icon name="spark" size={28} color={skill ? C.white : C.blue} />
              <span style={{ fontFamily: 'inherit', fontSize: 24, fontWeight: 700 }}>brainstorming</span>
            </div>
          </div>
        </ContainerBox>
      </Pop>
      <Pop at={cue('interview')} from={0.92} style={{ left: 380, top: 380 }}>
        <Card style={{ width: 920, height: 520, padding: 30, display: 'flex', flexDirection: 'column', gap: 18 }}>
          <Bubble from="analyst" at={cue('interview') + 4} frame={frame}>I need a booking app for my clinic.</Bubble>
          <Bubble from="agent" at={cue('one')} frame={frame}>Who will book the appointments?</Bubble>
          <Bubble from="analyst" at={cue('time')} frame={frame}>Patients, online.</Bubble>
          <Bubble from="agent" at={cue('clickable') - 4} frame={frame}>
            Where should patients book?
            <div style={{ display: 'flex', gap: 12, marginTop: 14 }}>
              <div style={{ padding: '10px 20px', borderRadius: 12, fontSize: 24, background: picked ? C.blue : C.white, color: picked ? C.white : C.ink, border: `1.5px solid ${picked ? C.blue : C.line}` }}>Web app</div>
              <div style={{ padding: '10px 20px', borderRadius: 12, fontSize: 24, background: C.white, color: C.ink, border: `1.5px solid ${C.line}` }}>Mobile app</div>
              <div style={{ padding: '10px 20px', borderRadius: 12, fontSize: 24, background: C.white, color: C.ink, border: `1.5px solid ${C.line}` }}>Both</div>
            </div>
          </Bubble>
          <div style={{ marginTop: 'auto', display: 'flex', alignItems: 'center', gap: 16, opacity: ease(frame, cue('until') - 6, 10) }}>
            <div style={{ flex: 1, height: 14, borderRadius: 7, background: C.ice, overflow: 'hidden' }}>
              <div style={{ width: `${clarity * 100}%`, height: '100%', background: `linear-gradient(90deg, ${C.sky}, ${C.blue})` }} />
            </div>
            <span style={{ fontSize: 24, color: C.blue, fontWeight: 700, width: 230 }}>
              {clarity >= 1 ? 'Ready for the spec' : `Clarity ${Math.round(clarity * 100)}%`}
            </span>
          </div>
        </Card>
      </Pop>
      <Cursor path={[[cue('clickable') + 2, 1200, 820], [click - 2, 470, 765]]} clicks={[click]} />
      <Sfx name="mouse-click" at={click} volume={0.5} />
      <Sfx name="ding" at={cue('clear') + 12} volume={0.25} />
    </Stage>
  );
};

export const Interview = Interactive.withSchema({
  Component: InterviewInner,
  componentName: 'Interview',
  schema: sceneSchema('An interview, not a form', 'Superpowers brainstorming, one question at a time'),
  wrapInSequence: true,
  layout: 'absolute-fill',
});
