import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion';
import { C, F } from '../theme';
import { AgentBot, Card, Chip, DrawPath, Heading, Icon, Logo, Pop, ramp, useSpring } from '../components';

const s = (sec: number) => Math.round(sec * 30);

// 7. Testes em worker novo, merge e conclusão; atividade ao vivo e custo.
const TESTS = ['test_create_booking', 'test_double_booking_rejected', 'test_confirmation_email_sent', 'test_admin_calendar'];

export const Tests: React.FC = () => {
  const frame = useCurrentFrame();
  const merge = ramp(frame, s(4.2), s(5.6));
  const done = useSpring(s(5.8), 12);
  const tokens = Math.round(interpolate(frame, [s(6.8), s(10.6)], [18240, 412880], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }));
  const budget = ramp(frame, s(7.6), s(10.6));
  return (
    <AbsoluteFill>
      <Heading step="Step 4 · Verify" title="Green means merge" sub="tests run in a fresh worker container" />
      {/* testes */}
      <Pop delay={s(0.2)} from={0.9} style={{ position: 'absolute', left: 120, top: 330 }}>
        <Card style={{ width: 600, padding: 30 }}>
          <div style={{ fontFamily: F.mono, fontSize: 22, color: C.inkSoft, marginBottom: 18 }}>$ pytest backend/tests</div>
          {TESTS.map((t, i) => {
            const at = s(0.9) + i * s(0.6);
            const ok = frame > at;
            return (
              <div key={t} style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '12px 0', borderTop: `1px solid ${C.line}` }}>
                <div style={{
                  width: 34, height: 34, borderRadius: 10, background: ok ? C.blue : C.ice,
                  display: 'flex', alignItems: 'center', justifyContent: 'center', transform: `scale(${ok ? 1 : 0.85})`,
                }}>
                  {ok && <Icon name="check" size={24} color={C.white} stroke={3} />}
                </div>
                <span style={{ fontFamily: F.mono, fontSize: 21, color: ok ? C.ink : C.muted }}>{t}</span>
              </div>
            );
          })}
          <div style={{ marginTop: 14, fontFamily: F.sans, fontWeight: 700, fontSize: 26, color: C.blue, opacity: ramp(frame, s(3.3), s(3.7)) }}>4 passed</div>
        </Card>
      </Pop>
      {/* grafo git */}
      <svg width={1920} height={1080} style={{ position: 'absolute' }}>
        <g opacity={ramp(frame, s(0.6), s(1.2))}>
          <line x1={800} y1={720} x2={1240} y2={720} stroke={C.blueDeep} strokeWidth={6} strokeLinecap="round" />
          <path d="M 860 720 C 900 720, 900 560, 960 560 L 1080 560" stroke={C.sky} strokeWidth={6} fill="none" strokeLinecap="round" />
          {[860, 1180].map((x) => <circle key={x} cx={x} cy={720} r={14} fill={C.white} stroke={C.blueDeep} strokeWidth={5} />)}
          {[960, 1020, 1080].map((x) => <circle key={x} cx={x} cy={560} r={12} fill={C.white} stroke={C.sky} strokeWidth={5} />)}
        </g>
        <DrawPath d="M 1080 560 C 1140 560, 1140 720, 1172 720" progress={merge} color={C.blue} width={6} head={false} />
        <circle cx={1180} cy={720} r={14 + 6 * done} fill={C.blue} opacity={done} />
        <text x={800} y={770} fontFamily={F.mono} fontSize={22} fill={C.inkSoft}>main</text>
        <text x={960} y={525} fontFamily={F.mono} fontSize={22} fill={C.inkSoft}>feature/T4</text>
      </svg>
      <div style={{ position: 'absolute', left: 1040, top: 790, opacity: done, transform: `scale(${0.6 + 0.4 * done})` }}>
        <Chip active><Icon name="check" size={24} color={C.white} stroke={3} />COMPLETED</Chip>
      </div>
      {/* ao vivo + custo */}
      <Pop delay={s(6.6)} style={{ position: 'absolute', left: 1330, top: 330 }}>
        <Card style={{ width: 470, padding: 28 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
            <div style={{ width: 14, height: 14, borderRadius: 7, background: C.blue, opacity: frame % 30 < 18 ? 1 : 0.3 }} />
            <span style={{ fontFamily: F.sans, fontWeight: 700, fontSize: 24, color: C.ink }}>Live activity</span>
          </div>
          {['Edit booking/service.py', 'Run pytest -q', 'Write tests/test_email.py'].map((l, i) => (
            <div key={l} style={{ fontFamily: F.mono, fontSize: 19, color: C.inkSoft, padding: '6px 0', opacity: ramp(frame, s(6.9) + i * 8, s(7.2) + i * 8) }}>› {l}</div>
          ))}
          <div style={{ marginTop: 22, display: 'flex', alignItems: 'center', gap: 10 }}>
            <Icon name="coin" size={30} />
            <span style={{ fontFamily: F.mono, fontSize: 24, color: C.ink, fontWeight: 600 }}>{tokens.toLocaleString('en-US')} tokens</span>
          </div>
          <div style={{ marginTop: 14, height: 14, borderRadius: 7, background: C.ice, overflow: 'hidden' }}>
            <div style={{ width: `${budget * 38}%`, height: '100%', background: `linear-gradient(90deg, ${C.sky}, ${C.blue})` }} />
          </div>
          <div style={{ marginTop: 8, fontFamily: F.mono, fontSize: 18, color: C.inkSoft }}>project budget · {Math.round(budget * 38)}% used</div>
        </Card>
      </Pop>
    </AbsoluteFill>
  );
};

// 8. Deploy: Gitea -> Coolify -> preview por tarefa e produção; falha vira tarefa de correção.
const FlowNode: React.FC<{ x: number; y: number; delay: number; icon: Parameters<typeof Icon>[0]['name']; title: string; sub: string; logo?: boolean }> = ({
  x, y, delay, icon, title, sub, logo,
}) => (
  <Pop delay={delay} style={{ position: 'absolute', left: x, top: y }}>
    <Card style={{ width: 260, height: 190, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 10 }}>
      {logo ? <Logo size={74} /> : <Icon name={icon} size={64} />}
      <span style={{ fontFamily: F.sans, fontWeight: 800, fontSize: 28, color: C.ink }}>{title}</span>
      <span style={{ fontFamily: F.mono, fontSize: 17, color: C.inkSoft }}>{sub}</span>
    </Card>
  </Pop>
);

const Browser: React.FC<{ url: string; label: string; strong?: boolean }> = ({ url, label, strong }) => (
  <Card style={{ width: 420, overflow: 'hidden', border: `2px solid ${strong ? C.blue : C.line}` }}>
    <div style={{ height: 40, background: C.frost, display: 'flex', alignItems: 'center', gap: 8, padding: '0 14px', borderBottom: `1px solid ${C.line}` }}>
      {[0, 1, 2].map((k) => <div key={k} style={{ width: 11, height: 11, borderRadius: 6, background: C.line }} />)}
      <div style={{ marginLeft: 10, flex: 1, height: 24, borderRadius: 8, background: C.white, fontFamily: F.mono, fontSize: 15, color: C.inkSoft, display: 'flex', alignItems: 'center', padding: '0 10px' }}>{url}</div>
    </div>
    <div style={{ padding: 20, display: 'flex', alignItems: 'center', gap: 14 }}>
      <div style={{ width: 56, height: 56, borderRadius: 14, background: strong ? C.blue : C.ice, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Icon name={strong ? 'rocket' : 'globe'} size={34} color={strong ? C.white : C.blue} />
      </div>
      <div>
        <div style={{ fontFamily: F.sans, fontWeight: 800, fontSize: 24, color: C.ink }}>{label}</div>
        <div style={{ fontFamily: F.mono, fontSize: 16, color: C.blue }}>● healthy</div>
      </div>
    </div>
  </Card>
);

export const Deploy: React.FC = () => {
  const frame = useCurrentFrame();
  const y = 300;
  const flow = (i: number) => ramp(frame, s(1.4) + i * s(1.4), s(2.2) + i * s(1.4));
  const preview = useSpring(s(5.8), 14);
  const prod = useSpring(s(8.4), 14);
  const click = frame > s(8.0) && frame < s(8.6);
  const fail = useSpring(s(10.6), 14);
  const fixClick = frame > s(12.8);
  const loop = ramp(frame, s(13.2), s(14.4));
  const fixCard = useSpring(s(14.0), 14);
  return (
    <AbsoluteFill>
      <Heading step="Step 5 · Deploy" title="Shipped with Coolify" />
      <FlowNode x={120} y={y} delay={s(0.2)} icon="bolt" title="Painkiller" sub="merge · push" logo />
      <FlowNode x={500} y={y} delay={s(1.6)} icon="git" title="Gitea" sub="built-in repos" />
      <FlowNode x={880} y={y} delay={s(3.0)} icon="cloud" title="Coolify" sub="build · deploy" />
      <svg width={1920} height={1080} style={{ position: 'absolute', pointerEvents: 'none' }}>
        <DrawPath d={`M 390 ${y + 95} L 490 ${y + 95}`} progress={flow(0)} />
        <DrawPath d={`M 770 ${y + 95} L 870 ${y + 95}`} progress={flow(1)} />
        <DrawPath d={`M 1150 ${y + 70} C 1220 ${y + 70}, 1220 ${y + 0}, 1300 ${y + 0}`} progress={ramp(frame, s(5.4), s(6.0))} />
        <DrawPath d={`M 1150 ${y + 120} C 1220 ${y + 120}, 1220 ${y + 200}, 1300 ${y + 200}`} progress={ramp(frame, s(8.0), s(8.6))} />
        {/* laço de correção */}
        <DrawPath d="M 760 810 C 960 810, 1000 810, 1100 810" progress={loop} />
        <DrawPath d="M 1560 720 C 1640 600, 1100 600, 1010 500" progress={ramp(frame, s(14.6), s(15.6))} dashed />
      </svg>
      <div style={{ position: 'absolute', left: 1310, top: y - 70, opacity: preview, transform: `translateX(${(1 - preview) * 40}px)` }}>
        <Browser url="t4.preview.clinic.app" label="Test · T4 preview" />
      </div>
      <div style={{ position: 'absolute', left: 1310, top: y + 140, opacity: prod, transform: `translateX(${(1 - prod) * 40}px)` }}>
        <Browser url="clinic.app" label="Production" strong />
      </div>
      <div style={{ position: 'absolute', left: 900, top: y + 220, opacity: ramp(frame, s(7.2), s(7.6)) * (frame < s(10) ? 1 : 0.4) }}>
        <Chip active={click} style={{ transform: click ? 'scale(0.94)' : undefined }}><Icon name="rocket" size={24} color={click ? C.white : C.blue} />Deploy</Chip>
      </div>
      {/* falha -> tarefa de correção */}
      <div style={{ position: 'absolute', left: 120, top: 690, opacity: fail, transform: `translateY(${(1 - fail) * 30}px)` }}>
        <Card style={{ width: 640, padding: 24, position: 'relative', overflow: 'hidden' }}>
          <div style={{ position: 'absolute', inset: 0, opacity: 0.5, background: `repeating-linear-gradient(135deg, ${C.ice} 0 10px, transparent 10px 22px)` }} />
          <div style={{ position: 'relative' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <Icon name="shield" size={30} color={C.ink} />
              <span style={{ fontFamily: F.sans, fontWeight: 800, fontSize: 26, color: C.ink }}>Deploy failed</span>
              <span style={{ marginLeft: 'auto', fontFamily: F.mono, fontSize: 17, color: C.inkSoft }}>build log</span>
            </div>
            <div style={{ fontFamily: F.mono, fontSize: 18, color: C.inkSoft, marginTop: 10 }}>ModuleNotFoundError: No module named 'jinja2'</div>
            <div style={{ marginTop: 14 }}>
              <Chip active={fixClick} style={{ fontSize: 20, padding: '8px 16px' }}><Icon name="wrench" size={22} color={fixClick ? C.white : C.blue} />Fix with the agent</Chip>
            </div>
          </div>
        </Card>
      </div>
      <div style={{ position: 'absolute', left: 1110, top: 720, opacity: fixCard, transform: `scale(${0.6 + 0.4 * fixCard})` }}>
        <Card style={{ width: 440, padding: 20, display: 'flex', alignItems: 'center', gap: 16 }}>
          <AgentBot size={80} />
          <div>
            <div style={{ fontFamily: F.mono, fontSize: 17, color: C.inkSoft }}>new task · deploy-fix</div>
            <div style={{ fontFamily: F.sans, fontWeight: 800, fontSize: 24, color: C.ink }}>Add missing dependency</div>
          </div>
        </Card>
      </div>
    </AbsoluteFill>
  );
};

// 9. Encerramento.
export const Outro: React.FC = () => {
  const frame = useCurrentFrame();
  const logo = useSpring(2, 12);
  const words = ['Conversation', 'Spec', 'Production'];
  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 30, transform: `scale(${0.8 + 0.2 * logo})`, opacity: logo }}>
        <Logo size={150} spin={(1 - logo) * 90} />
        <div style={{ fontFamily: F.sans, fontWeight: 800, fontSize: 130, letterSpacing: -4, color: C.ink }}>
          Pain<span style={{ color: C.blue }}>killer</span>
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 26, marginTop: 50 }}>
        {words.map((w, i) => {
          const sp = useSpring(s(0.9) + i * s(0.55), 15);
          return (
            <React.Fragment key={w}>
              {i > 0 && <div style={{ width: 60 * sp, height: 4, borderRadius: 2, background: C.sky }} />}
              <div style={{ opacity: sp, transform: `translateY(${(1 - sp) * 20}px)` }}>
                <Chip active={i === 2 && frame > s(2.4)} style={{ fontSize: 32, padding: '14px 30px' }}>{w}</Chip>
              </div>
            </React.Fragment>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
