import React from 'react';
import { Interactive } from 'remotion';
import { C, F } from '../theme';
import { ease, pop } from '../ui/anim';
import { Arrow, Card, ContainerBox, Heading, Icon, Person, Tag, Typewriter, Wires } from '../ui/kit';
import { Sfx } from '../ui/Sfx';
import { Stage, sceneSchema, useScene, type SceneProps } from '../ui/Stage';

const Line: React.FC<{ at: number; frame: number; children: React.ReactNode; color?: string }> = ({ at, frame, children, color = '#C9D8FF' }) => {
  const t = ease(frame, at, 10);
  return <div style={{ opacity: t, translate: `${(1 - t) * 14}px 0`, color }}>{children}</div>;
};

// 7. Interrupção limpa: painkiller ask -> exit 42 -> analista responde -> retoma.
const AskInner: React.FC<SceneProps> = ({ title, subtitle, voiceover, showCaptions, withBackground }) => {
  const { frame, fps, cue } = useScene(voiceover);
  const guess = cue('guess');
  const strike = ease(frame, guess + 8, 10);
  const exitAt = cue('forty-two');
  const exit = pop(frame, fps, exitAt, 9);
  const waiting = frame >= cue('exits');
  const answered = cue('answers');
  const resumed = frame >= cue('resumes');
  const pulse = waiting && !resumed ? 1 + 0.025 * Math.sin(frame / 4) : 1;
  return (
    <Stage id="ask" voiceover={voiceover} showCaptions={showCaptions} withBackground={withBackground}>
      <Heading eyebrow="Clean interruption" title={title} subtitle={subtitle} />
      <div style={{ position: 'absolute', left: 120, top: 380, opacity: ease(frame, 0, 14) }}>
        <ContainerBox label="painkiller-worker" sublabel="feature/T4" width={880} height={500}>
          <div style={{ position: 'absolute', inset: 0, background: C.night, padding: '26px 30px', fontFamily: F.mono, fontSize: 25, lineHeight: 1.75 }}>
            <Line at={4} frame={frame}><span style={{ color: C.sky }}>agent</span> implementing email confirmations…</Line>
            <Line at={cue('ambiguity')} frame={frame}><span style={{ color: C.sky }}>agent</span> unclear: which email provider?</Line>
            <Line at={guess} frame={frame} color="#7F93BF">
              <span style={{ position: 'relative' }}>
                guess: “SendGrid, probably”
                <span style={{ position: 'absolute', left: 0, top: '52%', height: 3, width: `${strike * 100}%`, background: C.sky }} />
              </span>
              <span style={{ marginLeft: 16, color: C.sky, opacity: strike }}>✕ never</span>
            </Line>
            <div style={{ color: C.white }}>
              {frame >= cue('asks') && <span style={{ color: C.sky }}>$ </span>}
              <Typewriter text={'painkiller ask "SendGrid or SMTP?"'} at={cue('asks')} cps={34} />
            </div>
            <Line at={cue('commits')} frame={frame}>✓ WIP committed · clarification.json</Line>
            <Line at={cue('resumes')} frame={frame} color={C.white}>
              <span style={{ color: C.sky }}>agent</span> resuming with “SMTP”…
            </Line>
          </div>
          <div style={{
            position: 'absolute', right: 30, bottom: 28, display: 'flex', alignItems: 'baseline', gap: 12, padding: '12px 26px', borderRadius: 18,
            background: C.white, boxShadow: '0 0 0 6px rgba(95,162,255,0.45)',
            opacity: Math.min(1, exit * 1.5) * (1 - ease(frame, cue('resumes'), 10)), scale: String(2.2 - 1.2 * exit), rotate: `${(1 - exit) * -14}deg`,
          }}>
            <span style={{ fontFamily: F.mono, fontSize: 26, color: C.inkSoft }}>exit</span>
            <span style={{ fontWeight: 800, fontSize: 80, color: C.blue, lineHeight: 1 }}>42</span>
          </div>
        </ContainerBox>
      </div>
      <div style={{ position: 'absolute', left: 1110, top: 380, opacity: ease(frame, cue('exits') - 4, 14), scale: String(pulse) }}>
        <Card style={{ width: 690, padding: 30, border: `2px solid ${waiting && !resumed ? C.blue : C.line}` }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <Tag>T4</Tag>
            <span style={{ fontWeight: 800, fontSize: 30, color: C.ink }}>Email confirmations</span>
          </div>
          <div style={{ marginTop: 18, display: 'flex', alignItems: 'center', gap: 12 }}>
            <Icon name={resumed ? 'play' : 'pause'} size={30} stroke={3} />
            <span style={{ fontFamily: F.mono, fontSize: 25, color: C.blue, fontWeight: 600 }}>{resumed ? 'RUNNING' : 'AWAITING ANALYST'}</span>
          </div>
          <div style={{ marginTop: 14, fontSize: 28, color: C.inkSoft, fontWeight: 600 }}>“SendGrid or SMTP?”</div>
        </Card>
      </div>
      <div style={{ position: 'absolute', left: 1130, top: 670, display: 'flex', alignItems: 'center', gap: 22, opacity: ease(frame, answered - 6, 14), translate: `0 ${(1 - ease(frame, answered - 6, 14)) * 20}px` }}>
        <Person size={110} />
        <div style={{ background: C.blue, color: C.white, borderRadius: '24px 24px 24px 6px', padding: '18px 26px', fontWeight: 700, fontSize: 30 }}>
          SMTP. We already run a server.
        </div>
      </div>
      <Wires>
        <Arrow d="M 1120 760 C 1060 790, 1040 800, 1012 780" progress={ease(frame, cue('resumes') - 10, 12)} width={5} />
      </Wires>
      <Sfx name="ding" at={exitAt} volume={0.3} />
      <Sfx name="mouse-click" at={answered + 6} volume={0.35} />
    </Stage>
  );
};

export const Ask = Interactive.withSchema({
  Component: AskInner,
  componentName: 'Ask',
  schema: sceneSchema("Ask, don't guess", 'exit code 42 pauses the task for the analyst'),
  wrapInSequence: true,
  layout: 'absolute-fill',
});
