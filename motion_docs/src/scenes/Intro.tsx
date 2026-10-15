import React from 'react';
import { Interactive } from 'remotion';
import { C } from '../theme';
import { ease, pop } from '../ui/anim';
import { AgentBot, Arrow, Card, Chip, ContainerBox, Icon, Logo, Pop, Wires, Wordmark } from '../ui/kit';
import { Sfx } from '../ui/Sfx';
import { Stage, sceneSchema, useScene, type SceneProps } from '../ui/Stage';

const CONTAINERS = [0, 1, 2, 3, 4];

// 2. Apresentação: o que o Painkiller é.
const IntroInner: React.FC<SceneProps> = ({ title, subtitle, voiceover, showCaptions, withBackground }) => {
  const { frame, fps, cue } = useScene(voiceover);
  const brand = cue('painkiller');
  const logo = pop(frame, fps, brand, 12);
  const conv = cue('conversation');
  const soft = cue('running');
  const orch = cue('orchestrating');
  return (
    <Stage id="intro" voiceover={voiceover} showCaptions={showCaptions} withBackground={withBackground}>
      <Sfx name="whoosh" at={brand - 4} volume={0.3} />
      <div style={{ position: 'absolute', left: 0, right: 0, top: 150, display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 34, opacity: Math.min(1, logo * 1.4), scale: String(0.75 + 0.25 * logo) }}>
        <div style={{ filter: 'drop-shadow(0 26px 34px rgba(31,94,255,0.35))' }}>
          <Logo size={170} spin={(1 - logo) * -140} />
        </div>
        <Wordmark size={150} />
      </div>
      <div style={{ position: 'absolute', left: 0, right: 0, top: 360, display: 'flex', justifyContent: 'center', gap: 14, opacity: ease(frame, cue('self-hosted'), 16) }}>
        <Chip>{title}</Chip>
        <Chip active>{subtitle}</Chip>
      </div>
      <Wires>
        <Arrow d="M 740 560 L 1170 560" progress={ease(frame, conv + 10, soft - conv)} width={5} />
        {CONTAINERS.map((i) => (
          <Arrow key={i} d={`M 960 610 C 960 680, ${300 + i * 330} 660, ${300 + i * 330} 735`} progress={ease(frame, orch + i * 4, 16)} color={C.sky} width={3} head={false} />
        ))}
      </Wires>
      <Pop at={conv} style={{ left: 300, top: 480 }}>
        <Card style={{ width: 430, padding: 24, display: 'flex', alignItems: 'center', gap: 18 }}>
          <div style={{ width: 70, height: 70, borderRadius: 18, background: C.ice, display: 'grid', placeItems: 'center' }}>
            <Icon name="chat" size={40} />
          </div>
          <div style={{ fontWeight: 800, fontSize: 32, color: C.ink }}>A conversation</div>
        </Card>
      </Pop>
      <Pop at={soft} style={{ left: 1190, top: 480 }}>
        <Card style={{ width: 430, padding: 24, display: 'flex', alignItems: 'center', gap: 18 }}>
          <div style={{ width: 70, height: 70, borderRadius: 18, background: C.blue, display: 'grid', placeItems: 'center' }}>
            <Icon name="rocket" size={40} color={C.white} />
          </div>
          <div style={{ fontWeight: 800, fontSize: 32, color: C.ink }}>Running software</div>
        </Card>
      </Pop>
      {CONTAINERS.map((i) => (
        <Pop key={i} at={orch + i * 4} from={0.4} style={{ left: 185 + i * 330, top: 735 }}>
          <ContainerBox label={`agent-${i + 1}`} width={230} height={160} active={frame > cue('isolated') && frame < cue('isolated') + 30 + i * 6}>
            <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 12 }}>
              <AgentBot size={78} busy />
            </div>
          </ContainerBox>
        </Pop>
      ))}
    </Stage>
  );
};

export const Intro = Interactive.withSchema({
  Component: IntroInner,
  componentName: 'Intro',
  schema: sceneSchema('Self-hosted', 'Docker sandboxes'),
  wrapInSequence: true,
  layout: 'absolute-fill',
});
