import React from 'react';
import { Interactive } from 'remotion';
import { C, F } from '../theme';
import { ease, pop } from '../ui/anim';
import { Arrow, Card, Icon, Typewriter, Wires, type IconName } from '../ui/kit';
import { Stage, sceneSchema, useScene, type SceneProps } from '../ui/Stage';

const OBSTACLES: { word: string; label: string; icon: IconName; x: number; y: number; tilt: number }[] = [
  { word: 'specs', label: 'Specs', icon: 'doc', x: 190, y: 600, tilt: -6 },
  { word: 'tickets', label: 'Tickets', icon: 'ticket', x: 520, y: 760, tilt: 4 },
  { word: 'handoffs', label: 'Handoffs', icon: 'chat', x: 830, y: 640, tilt: -3 },
  { word: 'reviews', label: 'Reviews', icon: 'eye', x: 1160, y: 770, tilt: 5 },
  { word: 'deploys', label: 'Deploys', icon: 'rocket', x: 1450, y: 610, tilt: -5 },
];

// 1. Gancho: descrever é fácil, entregar é difícil.
const HookInner: React.FC<SceneProps> = ({ title, subtitle, voiceover, showCaptions, withBackground }) => {
  const { frame, fps, cue } = useScene(voiceover);
  const describe = cue('describing');
  const shipping = cue('shipping');
  const a = ease(frame, describe, 20);
  const b = ease(frame, shipping, 20);
  return (
    <Stage id="hook" voiceover={voiceover} showCaptions={showCaptions} withBackground={withBackground}>
      <div style={{ position: 'absolute', left: 0, right: 0, top: 150, textAlign: 'center' }}>
        <div style={{ fontWeight: 800, fontSize: 84, letterSpacing: -2.5, color: C.ink, opacity: a * (1 - b * 0.65), translate: `0 ${(1 - a) * 30 - b * 20}px`, scale: String(1 - b * 0.18) }}>
          {title}
        </div>
        <div style={{ fontWeight: 800, fontSize: 92, letterSpacing: -2.5, color: C.blue, opacity: b, translate: `0 ${(1 - b) * 30 - 18}px` }}>
          {subtitle}
        </div>
      </div>
      <Wires>
        {OBSTACLES.map((o, i) => (
          <Arrow key={o.word} d={`M 960 530 C ${960 + (i - 2) * 60} 600, ${o.x + 140} ${o.y - 80}, ${o.x + 140} ${o.y}`}
            progress={ease(frame, cue(o.word) - 4, 14)} color={C.muted} width={3} dashed head={false} />
        ))}
      </Wires>
      <div style={{ position: 'absolute', left: 600, top: 400, opacity: a, scale: String(0.9 + 0.1 * a) }}>
        <Card style={{ width: 720, padding: '26px 30px', display: 'flex', alignItems: 'center', gap: 18 }}>
          <Icon name="chat" size={40} />
          <Typewriter text="Build me a booking app for my clinic." at={describe + 6} cps={32}
            style={{ fontFamily: F.sans, fontSize: 32, fontWeight: 600, color: C.ink }} />
        </Card>
      </div>
      {OBSTACLES.map((o) => {
        const p = pop(frame, fps, cue(o.word), 11);
        const wobble = Math.sin((frame + o.x) / 7) * 2 * Math.min(1, p);
        return (
          <div key={o.word} style={{ position: 'absolute', left: o.x, top: o.y, opacity: Math.min(1, p * 1.5), scale: String(0.5 + 0.5 * p), rotate: `${o.tilt + wobble}deg` }}>
            <Card style={{ width: 280, padding: '20px 24px', display: 'flex', alignItems: 'center', gap: 16 }}>
              <div style={{ width: 52, height: 52, borderRadius: 14, background: C.ice, display: 'grid', placeItems: 'center' }}>
                <Icon name={o.icon} size={30} />
              </div>
              <span style={{ fontWeight: 800, fontSize: 30, color: C.ink }}>{o.label}</span>
            </Card>
          </div>
        );
      })}
    </Stage>
  );
};

export const Hook = Interactive.withSchema({
  Component: HookInner,
  componentName: 'Hook',
  schema: sceneSchema('Describing an app is easy.', 'Shipping it is the hard part.'),
  wrapInSequence: true,
  layout: 'absolute-fill',
});
