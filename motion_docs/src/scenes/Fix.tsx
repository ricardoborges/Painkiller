import React from 'react';
import { Interactive } from 'remotion';
import { C, F } from '../theme';
import { ease, pop } from '../ui/anim';
import { AgentBot, Arrow, Card, Chip, Cursor, Heading, Icon, Pop, Tag, Wires } from '../ui/kit';
import { Sfx } from '../ui/Sfx';
import { Stage, sceneSchema, useScene, type SceneProps } from '../ui/Stage';
import { Browser } from './Deploy';

const LOG = ['#12 RUN pip install -r requirements.txt', '#13 RUN python -m app', "ModuleNotFoundError: No module named 'jinja2'", 'Deployment failed'];

// 10. Um deploy que falha vira tarefa, e o agente corrige.
const FixInner: React.FC<SceneProps> = ({ title, subtitle, voiceover, showCaptions, withBackground }) => {
  const { frame, fps, cue } = useScene(voiceover);
  const fails = cue('fails');
  const shake = frame >= fails && frame < fails + 14 ? Math.sin(frame * 2.2) * 8 * (1 - (frame - fails) / 14) : 0;
  const click = cue('becomes');
  const task = pop(frame, fps, cue('task'), 13);
  const fixed = frame >= cue('fixes') + 8;
  return (
    <Stage id="fix" voiceover={voiceover} showCaptions={showCaptions} withBackground={withBackground}>
      <Heading eyebrow="Self-healing" title={title} subtitle={subtitle} />
      <Pop at={fails - 8} from={0.9} style={{ left: 120, top: 380 }}>
        <div style={{ translate: `${shake}px 0` }}>
          <Card style={{ width: 780, padding: 30, position: 'relative', overflow: 'hidden' }}>
            <div style={{ position: 'absolute', inset: 0, opacity: 0.6, background: `repeating-linear-gradient(135deg, ${C.ice} 0 10px, transparent 10px 22px)` }} />
            <div style={{ position: 'relative' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                <Icon name="alert" size={36} color={C.ink} />
                <span style={{ fontWeight: 800, fontSize: 32, color: C.ink }}>Deploy failed</span>
                <span style={{ marginLeft: 'auto', fontFamily: F.mono, fontSize: 19, color: C.inkSoft }}>build log</span>
              </div>
              <div style={{ marginTop: 16, background: C.night, borderRadius: 14, padding: '16px 20px', fontFamily: F.mono, fontSize: 21, lineHeight: 1.7 }}>
                {LOG.map((l, i) => (
                  <div key={l} style={{ color: i >= 2 ? C.white : '#9FB3DA', opacity: ease(frame, fails + i * 5, 8) }}>{l}</div>
                ))}
              </div>
              <div style={{ marginTop: 18 }}>
                <Chip active={frame >= click} style={{ fontSize: 24 }}>
                  <Icon name="wrench" size={26} color={frame >= click ? C.white : C.blue} />
                  Fix with the agent
                </Chip>
              </div>
            </div>
          </Card>
        </div>
      </Pop>
      <Wires>
        <Arrow d="M 910 560 L 1020 560" progress={ease(frame, cue('task') - 6, 12)} width={5} />
        <Arrow d="M 1400 612 L 1400 756" progress={ease(frame, cue('fixes') + 6, 10)} width={5} />
      </Wires>
      <div style={{ position: 'absolute', left: 1040, top: 430, opacity: Math.min(1, task * 1.4), scale: String(0.6 + 0.4 * task) }}>
        <Card style={{ width: 720, padding: 28, display: 'flex', alignItems: 'center', gap: 22, border: `2px solid ${fixed ? C.blue : C.line}` }}>
          <AgentBot size={110} busy={!fixed} />
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <Tag>T7</Tag>
              <span style={{ fontFamily: F.mono, fontSize: 20, color: C.inkSoft }}>deploy-fix</span>
            </div>
            <div style={{ fontWeight: 800, fontSize: 32, color: C.ink, marginTop: 8 }}>Add the missing dependency</div>
            <div style={{ fontFamily: F.mono, fontSize: 22, color: C.blue, marginTop: 6, fontWeight: 600 }}>{fixed ? '✓ COMPLETED' : 'RUNNING…'}</div>
          </div>
        </Card>
      </div>
      <div style={{ position: 'absolute', left: 1160, top: 770, opacity: ease(frame, cue('fixes') + 10, 12) }}>
        <Browser url="clinic.app" label="Production" live strong />
      </div>
      <Cursor path={[[fails + 10, 700, 900], [click - 2, 330, 845]]} clicks={[click]} />
      <Sfx name="mouse-click" at={click} volume={0.5} />
      <Sfx name="ding" at={cue('fixes') + 8} volume={0.3} />
    </Stage>
  );
};

export const Fix = Interactive.withSchema({
  Component: FixInner,
  componentName: 'Fix',
  schema: sceneSchema('Failures become tasks', 'the build log goes straight to the agent'),
  wrapInSequence: true,
  layout: 'absolute-fill',
});
