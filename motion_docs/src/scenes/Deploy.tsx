import React from 'react';
import { Interactive } from 'remotion';
import { C, F } from '../theme';
import { ease, pop } from '../ui/anim';
import { Arrow, Card, Chip, Cursor, Heading, Icon, Logo, Pop, Wires, type IconName } from '../ui/kit';
import { Sfx } from '../ui/Sfx';
import { Stage, sceneSchema, useScene, type SceneProps } from '../ui/Stage';

const Node: React.FC<{ at: number; x: number; icon?: IconName; title: string; sub: string; logo?: boolean }> = ({ at, x, icon, title, sub, logo }) => (
  <Pop at={at} style={{ left: x, top: 420 }}>
    <Card style={{ width: 290, height: 220, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 10 }}>
      {logo ? <Logo size={80} /> : <Icon name={icon ?? 'git'} size={70} />}
      <span style={{ fontWeight: 800, fontSize: 32, color: C.ink }}>{title}</span>
      <span style={{ fontFamily: F.mono, fontSize: 19, color: C.inkSoft }}>{sub}</span>
    </Card>
  </Pop>
);

export const Browser: React.FC<{ url: string; label: string; live: boolean; strong?: boolean }> = ({ url, label, live, strong }) => (
  <Card style={{ width: 480, overflow: 'hidden', border: `2px solid ${strong && live ? C.blue : C.line}` }}>
    <div style={{ height: 44, background: C.frost, display: 'flex', alignItems: 'center', gap: 8, padding: '0 16px', borderBottom: `1px solid ${C.line}` }}>
      {[0, 1, 2].map((k) => <div key={k} style={{ width: 12, height: 12, borderRadius: 6, background: C.line }} />)}
      <div style={{ marginLeft: 10, flex: 1, height: 28, borderRadius: 8, background: C.white, fontFamily: F.mono, fontSize: 17, color: C.inkSoft, display: 'flex', alignItems: 'center', padding: '0 12px' }}>{url}</div>
    </div>
    <div style={{ padding: 22, display: 'flex', alignItems: 'center', gap: 16 }}>
      <div style={{ width: 62, height: 62, borderRadius: 16, background: strong && live ? C.blue : C.ice, display: 'grid', placeItems: 'center' }}>
        <Icon name={strong ? 'rocket' : 'globe'} size={36} color={strong && live ? C.white : C.blue} />
      </div>
      <div>
        <div style={{ fontWeight: 800, fontSize: 28, color: C.ink }}>{label}</div>
        <div style={{ fontFamily: F.mono, fontSize: 19, color: live ? C.blue : C.muted }}>{live ? '● healthy' : '○ not deployed'}</div>
      </div>
    </div>
  </Card>
);

// 9. Deploy: Gitea -> Coolify -> preview por tarefa e produção num clique.
const DeployInner: React.FC<SceneProps> = ({ title, subtitle, voiceover, showCaptions, withBackground }) => {
  const { frame, fps, cue } = useScene(voiceover);
  const click = cue('click') + 4;
  const prod = pop(frame, fps, cue('production') - 4, 14);
  return (
    <Stage id="deploy" voiceover={voiceover} showCaptions={showCaptions} withBackground={withBackground}>
      <Heading eyebrow="Step 5 · Deploy" title={title} subtitle={subtitle} />
      <Node at={0} x={120} title="Painkiller" sub="merge · push" logo />
      <Node at={cue('gitea') - 4} x={500} icon="git" title="Gitea" sub="built-in repos" />
      <Node at={cue('coolify') - 4} x={880} icon="cloud" title="Coolify" sub="build · deploy" />
      <Wires>
        <Arrow d="M 420 530 L 490 530" progress={ease(frame, cue('pushes'), 14)} width={5} />
        <Arrow d="M 800 530 L 870 530" progress={ease(frame, cue('hands'), 14)} width={5} />
        <Arrow d="M 1180 490 C 1240 490, 1240 440, 1300 440" progress={ease(frame, cue('preview') - 6, 14)} width={5} />
        <Arrow d="M 1180 570 C 1240 570, 1240 690, 1300 690" progress={ease(frame, click, 14)} width={5} />
      </Wires>
      <Pop at={cue('preview') - 2} style={{ left: 1320, top: 360 }}>
        <Browser url="t4.preview.clinic.app" label="Preview · T4" live />
      </Pop>
      <div style={{ position: 'absolute', left: 1320, top: 610, opacity: Math.min(1, prod * 1.4), translate: `${(1 - prod) * 40}px 0` }}>
        <Browser url="clinic.app" label="Production" live={frame >= click + 14} strong />
      </div>
      <div style={{ position: 'absolute', left: 920, top: 690, opacity: ease(frame, cue('production'), 12) }}>
        <Chip active={frame >= click && frame < click + 10} style={{ scale: frame >= click && frame < click + 6 ? '0.94' : '1' }}>
          <Icon name="rocket" size={26} color={frame >= click && frame < click + 10 ? C.white : C.blue} />
          Deploy to production
        </Chip>
      </div>
      <Cursor path={[[cue('production') + 4, 1150, 900], [click - 2, 1010, 712]]} clicks={[click]} />
      <Sfx name="mouse-click" at={click} volume={0.5} />
      <Sfx name="ding" at={click + 14} volume={0.25} />
    </Stage>
  );
};

export const Deploy = Interactive.withSchema({
  Component: DeployInner,
  componentName: 'Deploy',
  schema: sceneSchema('Shipped with Coolify', 'a preview per task, production in one click'),
  wrapInSequence: true,
  layout: 'absolute-fill',
});
