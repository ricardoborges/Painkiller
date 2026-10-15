import React from 'react';
import { interpolate, Interactive } from 'remotion';
import { C, F } from '../theme';
import { ease, pop } from '../ui/anim';
import { Arrow, Card, Chip, Heading, Icon, Pop, Wires } from '../ui/kit';
import { Sfx } from '../ui/Sfx';
import { Stage, sceneSchema, useScene, type SceneProps } from '../ui/Stage';

const TESTS = ['test_create_booking', 'test_double_booking', 'test_confirmation_email', 'test_admin_calendar'];

// 8. Testes num worker novo, merge e custo por token.
const VerifyInner: React.FC<SceneProps> = ({ title, subtitle, voiceover, showCaptions, withBackground }) => {
  const { frame, fps, cue } = useScene(voiceover);
  const tests = cue('tests');
  const green = cue('green');
  const merge = cue('merge');
  const done = pop(frame, fps, merge + 12, 11);
  const token = cue('token');
  const budget = cue('budget');
  const tokens = Math.round(interpolate(frame, [token, budget + 24], [18240, 412880], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }));
  const used = ease(frame, token + 6, budget + 24 - token);
  return (
    <Stage id="verify" voiceover={voiceover} showCaptions={showCaptions} withBackground={withBackground}>
      <Heading eyebrow="Step 4 · Verify" title={title} subtitle={subtitle} />
      <Pop at={tests - 6} from={0.9} style={{ left: 120, top: 380 }}>
        <Card style={{ width: 620, padding: 30 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
            <span style={{ fontFamily: F.mono, fontSize: 23, color: C.inkSoft }}>$ pytest backend/tests</span>
            <span style={{ marginLeft: 'auto', opacity: ease(frame, cue('fresh'), 12) }}>
              <Chip style={{ fontSize: 19, padding: '6px 14px' }}><Icon name="container" size={22} />fresh worker</Chip>
            </span>
          </div>
          {TESTS.map((t, i) => {
            const ok = frame >= tests + 10 + i * 8;
            return (
              <div key={t} style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '12px 0', borderTop: `1px solid ${C.line}` }}>
                <div style={{ width: 36, height: 36, borderRadius: 10, background: ok ? C.blue : C.ice, display: 'grid', placeItems: 'center', scale: ok ? '1' : '0.85' }}>
                  {ok && <Icon name="check" size={24} color={C.white} stroke={3} />}
                </div>
                <span style={{ fontFamily: F.mono, fontSize: 23, color: ok ? C.ink : C.muted }}>{t}</span>
              </div>
            );
          })}
          <div style={{ marginTop: 12, fontWeight: 800, fontSize: 30, color: C.blue, opacity: ease(frame, green, 10) }}>4 passed</div>
        </Card>
      </Pop>
      <Wires>
        <g opacity={ease(frame, tests, 14)}>
          <line x1={800} y1={720} x2={1260} y2={720} stroke={C.blueDeep} strokeWidth={6} strokeLinecap="round" />
          <path d="M 850 720 C 900 720, 900 560, 960 560 L 1090 560" stroke={C.sky} strokeWidth={6} fill="none" strokeLinecap="round" />
          <circle cx={850} cy={720} r={14} fill={C.white} stroke={C.blueDeep} strokeWidth={5} />
          {[960, 1025, 1090].map((x) => <circle key={x} cx={x} cy={560} r={12} fill={C.white} stroke={C.sky} strokeWidth={5} />)}
          <text x={800} y={770} fontFamily={F.mono} fontSize={24} fill={C.inkSoft}>main</text>
          <text x={950} y={522} fontFamily={F.mono} fontSize={24} fill={C.inkSoft}>feature/T4</text>
        </g>
        <Arrow d="M 1090 560 C 1150 560, 1150 720, 1196 720" progress={ease(frame, merge - 4, 16)} width={6} head={false} />
        <circle cx={1200} cy={720} r={14 + 6 * done} fill={C.blue} opacity={Math.min(1, done)} />
      </Wires>
      <div style={{ position: 'absolute', left: 1050, top: 790, opacity: Math.min(1, done * 1.4), scale: String(0.6 + 0.4 * done) }}>
        <Chip active><Icon name="merge" size={26} color={C.white} />Merged · COMPLETED</Chip>
      </div>
      <Pop at={token - 4} style={{ left: 1330, top: 380 }}>
        <Card style={{ width: 470, padding: 30 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
            <Icon name="coin" size={34} />
            <span style={{ fontWeight: 800, fontSize: 28, color: C.ink }}>Usage</span>
          </div>
          <div style={{ fontFamily: F.mono, fontSize: 40, fontWeight: 600, color: C.ink }}>{tokens.toLocaleString('en-US')}</div>
          <div style={{ fontSize: 22, color: C.inkSoft, marginBottom: 18 }}>tokens on this task</div>
          <div style={{ height: 16, borderRadius: 8, background: C.ice, overflow: 'hidden' }}>
            <div style={{ width: `${used * 38}%`, height: '100%', background: `linear-gradient(90deg, ${C.sky}, ${C.blue})` }} />
          </div>
          <div style={{ marginTop: 10, fontFamily: F.mono, fontSize: 21, color: C.inkSoft }}>project budget · {Math.round(used * 38)}% used</div>
        </Card>
      </Pop>
      <Sfx name="ding" at={merge + 12} volume={0.3} />
    </Stage>
  );
};

export const Verify = Interactive.withSchema({
  Component: VerifyInner,
  componentName: 'Verify',
  schema: sceneSchema('Green means merge', 'tests run in a fresh worker container'),
  wrapInSequence: true,
  layout: 'absolute-fill',
});
