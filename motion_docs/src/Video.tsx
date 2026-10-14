import React from 'react';
import { AbsoluteFill, Audio, Sequence, interpolate, staticFile, useCurrentFrame } from 'remotion';
import durations from './durations.json';
import { FPS } from './theme';
import { Background, SceneFrame } from './components';
import { Goal, Interview, Intro } from './scenes/Opening';
import { Ask, Harness, Spec } from './scenes/Build';
import { Deploy, Outro, Tests } from './scenes/Ship';

// Atraso da narração dentro da cena e folga depois dela (em frames).
const LEAD = 10;
const TAIL = 20;

const SCENES: { id: keyof typeof durations; C: React.FC; extra?: number }[] = [
  { id: 'intro', C: Intro },
  { id: 'goal', C: Goal },
  { id: 'interview', C: Interview },
  { id: 'spec', C: Spec },
  { id: 'harness', C: Harness },
  { id: 'ask', C: Ask },
  { id: 'tests', C: Tests },
  { id: 'deploy', C: Deploy },
  { id: 'outro', C: Outro, extra: 45 },
];

export const sceneFrames = (id: keyof typeof durations, extra = 0) => Math.ceil(durations[id] * FPS) + LEAD + TAIL + extra;

export const TOTAL_FRAMES = SCENES.reduce((acc, sc) => acc + sceneFrames(sc.id, sc.extra), 0);


export const Video: React.FC = () => {
  const frame = useCurrentFrame();
  let from = 0;
  return (
    <AbsoluteFill>
      <Background />
      {SCENES.map(({ id, C, extra }) => {
        const d = sceneFrames(id, extra);
        const start = from;
        from += d;
        return (
          <Sequence key={id} from={start} durationInFrames={d} name={id}>
            <SceneFrame duration={d}>
              <C />
            </SceneFrame>
            <Sequence from={LEAD}>
              <Audio src={staticFile(`audio/${id}.mp3`)} />
            </Sequence>
          </Sequence>
        );
      })}
      {/* barra de progresso discreta */}
      <div style={{ position: 'absolute', left: 0, bottom: 0, height: 6, background: '#1F5EFF', opacity: 0.85,
        width: `${interpolate(frame, [0, TOTAL_FRAMES], [0, 100])}%` }} />
    </AbsoluteFill>
  );
};
