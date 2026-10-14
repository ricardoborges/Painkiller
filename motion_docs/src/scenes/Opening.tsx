import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion';
import { C, F } from '../theme';
import { AgentBot, Card, ContainerBox, DrawPath, Heading, Icon, Logo, Person, Pop, ramp, useSpring } from '../components';

const s = (sec: number) => Math.round(sec * 30);

// 1. Intro: logotipo e contentores orbitando.
export const Intro: React.FC = () => {
  const frame = useCurrentFrame();
  const logo = useSpring(4, 12);
  const title = useSpring(s(1.0), 16);
  const sub = useSpring(s(2.0), 18);
  const orbit = useSpring(s(5.0), 20);
  const lift = interpolate(orbit, [0, 1], [0, -90]);
  const n = 6;
  return (
    <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
      {Array.from({ length: n }).map((_, i) => {
        const a = (i / n) * Math.PI * 2 + frame / 140;
        const r = 600 * orbit;
        const x = Math.cos(a) * r;
        const y = Math.sin(a) * r * 0.42 + 40;
        const pop = useSpring(s(5.0) + i * 4, 14);
        return (
          <div key={i} style={{ position: 'absolute', transform: `translate(${x}px, ${y}px) scale(${0.55 * pop})`, opacity: pop }}>
            <ContainerBox label={`agent-${i + 1}`} width={230} height={170}>
              <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 14 }}>
                <AgentBot size={84} />
              </div>
            </ContainerBox>
          </div>
        );
      })}
      <div style={{ transform: `translateY(${lift}px)`, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <div style={{ transform: `scale(${logo})`, filter: 'drop-shadow(0 30px 40px rgba(31,94,255,0.35))' }}>
          <Logo size={220} spin={(1 - logo) * -120} />
        </div>
        <div style={{ fontFamily: F.sans, fontWeight: 800, fontSize: 150, letterSpacing: -5, color: C.ink, opacity: title, transform: `translateY(${(1 - title) * 30}px)`, marginTop: 10 }}>
          Pain<span style={{ color: C.blue }}>killer</span>
        </div>
        <div style={{ fontFamily: F.sans, fontWeight: 500, fontSize: 40, color: C.inkSoft, opacity: sub, transform: `translateY(${(1 - sub) * 20}px)` }}>
          Turn a conversation into running software.
        </div>
      </div>
    </AbsoluteFill>
  );
};

// 2. Objetivo: o caminho ideia -> produção, com perdas nas passagens e depois automatizado.
const STAGES: { icon: Parameters<typeof Icon>[0]['name']; label: string }[] = [
  { icon: 'bulb', label: 'Idea' },
  { icon: 'doc', label: 'Spec' },
  { icon: 'list', label: 'Tasks' },
  { icon: 'code', label: 'Code' },
  { icon: 'rocket', label: 'Production' },
];

export const Goal: React.FC = () => {
  const frame = useCurrentFrame();
  const x0 = 260;
  const gap = 350;
  const y = 600;
  const loss = ramp(frame, s(4.6), s(6.2));
  const sweep = ramp(frame, s(7.0), s(9.6));
  const human = useSpring(s(10.0), 16);
  return (
    <AbsoluteFill>
      <Heading step="The goal" title="Automate the whole path" sub="from an idea to software in production" />
      <svg width={1920} height={1080} style={{ position: 'absolute' }}>
        {STAGES.slice(0, -1).map((_, i) => {
          const a = x0 + i * gap + 110;
          const b = x0 + (i + 1) * gap - 110;
          const p = ramp(frame, s(0.6) + i * s(0.9), s(1.2) + i * s(0.9));
          return <DrawPath key={i} d={`M ${a} ${y} L ${b} ${y}`} progress={p} color={C.muted} dashed width={3} />;
        })}
        <path d={`M ${x0} ${y} L ${x0 + 4 * gap} ${y}`} stroke={C.blue} strokeWidth={10} strokeLinecap="round"
          pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - sweep} fill="none" opacity={0.9} />
        {/* analista acima, ligado ao fluxo */}
        {human > 0.01 && STAGES.map((_, i) => (
          <line key={i} x1={960} y1={330} x2={x0 + i * gap} y2={y - 100} stroke={C.sky} strokeWidth={2}
            strokeDasharray="4 8" opacity={human * 0.8} />
        ))}
      </svg>
      {/* pedaços de contexto caindo nas passagens */}
      {STAGES.slice(0, -1).map((_, i) =>
        [0, 1, 2].map((k) => {
          const cx = x0 + i * gap + gap / 2 + (k - 1) * 26;
          const fall = loss * (120 + k * 50);
          return (
            <div key={`${i}-${k}`} style={{
              position: 'absolute', left: cx - 9, top: y - 9 + fall, width: 18, height: 18, borderRadius: 5,
              background: C.muted, opacity: loss > 0 ? (1 - loss) * 0.9 + 0.1 - sweep : 0, transform: `rotate(${fall * 2}deg)`,
            }} />
          );
        }),
      )}
      {STAGES.map((st, i) => {
        const pop = useSpring(s(0.3) + i * s(0.9), 13);
        const lit = sweep >= i / 4 - 0.01;
        return (
          <div key={st.label} style={{ position: 'absolute', left: x0 + i * gap - 100, top: y - 100, width: 200, opacity: pop, transform: `scale(${pop})` }}>
            <Card style={{ width: 200, height: 200, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 16,
              background: lit && sweep > 0 ? C.blue : C.white, border: `1px solid ${lit && sweep > 0 ? C.blue : C.line}` }}>
              <Icon name={st.icon} size={70} color={lit && sweep > 0 ? C.white : C.blue} />
              <span style={{ fontFamily: F.sans, fontWeight: 700, fontSize: 28, color: lit && sweep > 0 ? C.white : C.ink }}>{st.label}</span>
            </Card>
          </div>
        );
      })}
      <div style={{ position: 'absolute', left: 0, right: 0, top: 830, textAlign: 'center', fontFamily: F.mono, fontSize: 26, color: C.inkSoft, opacity: loss * (1 - sweep) }}>
        every handoff loses context
      </div>
      <div style={{ position: 'absolute', left: 0, right: 0, top: 830, textAlign: 'center', fontFamily: F.sans, fontWeight: 700, fontSize: 34, color: C.blue, opacity: sweep }}>
        One automated pipeline
      </div>
      <div style={{ position: 'absolute', left: 960 - 110, top: 220, width: 220, opacity: human, transform: `scale(${0.7 + 0.3 * human})` }}>
        <Card style={{ padding: '18px 0 14px', display: 'flex', justifyContent: 'center' }}>
          <Person size={80} label="Analyst in control" />
        </Card>
      </div>
    </AbsoluteFill>
  );
};

// 3. Entrevista: analista conversando com o agente de brainstorming.
const Bubble: React.FC<{ from: 'agent' | 'analyst'; delay: number; children: React.ReactNode }> = ({ from, delay, children }) => {
  const sp = useSpring(delay, 15);
  const agent = from === 'agent';
  return (
    <div style={{
      alignSelf: agent ? 'flex-start' : 'flex-end', maxWidth: 560, opacity: sp, transform: `translateY(${(1 - sp) * 20}px)`,
      background: agent ? C.frost : C.blue, color: agent ? C.ink : C.white, border: agent ? `1px solid ${C.line}` : 'none',
      borderRadius: agent ? '22px 22px 22px 6px' : '22px 22px 6px 22px', padding: '16px 22px',
      fontFamily: F.sans, fontSize: 25, fontWeight: 500, lineHeight: 1.35,
    }}>
      {children}
    </div>
  );
};

export const Interview: React.FC = () => {
  const frame = useCurrentFrame();
  const pick = frame > s(8.8);
  const options = ['Web app', 'Mobile app', 'REST API'];
  const clarity = ramp(frame, s(9.8), s(11.6));
  return (
    <AbsoluteFill>
      <Heading step="Step 1 · Initial analysis" title="An interview, not a form" sub="Superpowers brainstorming skill, one question at a time" />
      <Pop delay={s(0.4)} style={{ position: 'absolute', left: 150, top: 470 }}>
        <Person size={190} label="Analyst" />
      </Pop>
      <Pop delay={s(2.2)} style={{ position: 'absolute', right: 120, top: 360 }}>
        <ContainerBox label="painkiller-agent" sublabel="docker" width={420} height={420}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: 34, gap: 20 }}>
            <AgentBot size={150} />
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 18px', borderRadius: 14, background: C.ice }}>
              <Icon name="spark" size={26} />
              <span style={{ fontFamily: F.mono, fontSize: 21, color: C.blueDeep, fontWeight: 600 }}>superpowers:brainstorming</span>
            </div>
          </div>
        </ContainerBox>
      </Pop>
      <Pop delay={s(1.0)} from={0.9} style={{ position: 'absolute', left: 470, top: 300 }}>
        <Card style={{ width: 860, height: 640, padding: 30, display: 'flex', flexDirection: 'column', gap: 18 }}>
          <Bubble from="analyst" delay={s(1.2)}>I need a booking system for my clinic.</Bubble>
          <Bubble from="agent" delay={s(3.6)}>Great. Who will book the appointments?</Bubble>
          <Bubble from="analyst" delay={s(5.0)}>Patients, online.</Bubble>
          <Bubble from="agent" delay={s(6.4)}>
            Where should patients book?
            <div style={{ display: 'flex', gap: 12, marginTop: 14 }}>
              {options.map((o, i) => {
                const on = pick && i === 0;
                return (
                  <div key={o} style={{
                    padding: '10px 18px', borderRadius: 12, fontSize: 22, fontWeight: 600,
                    background: on ? C.blue : C.white, color: on ? C.white : C.ink, border: `1.5px solid ${on ? C.blue : C.line}`,
                    transform: on ? `scale(${1 + 0.06 * Math.max(0, 1 - (frame - s(8.8)) / 10)})` : undefined,
                  }}>{o}</div>
                );
              })}
            </div>
          </Bubble>
          <div style={{ marginTop: 'auto', display: 'flex', alignItems: 'center', gap: 16, opacity: clarity }}>
            <div style={{ flex: 1, height: 12, borderRadius: 6, background: C.ice, overflow: 'hidden' }}>
              <div style={{ width: `${clarity * 100}%`, height: '100%', background: `linear-gradient(90deg, ${C.sky}, ${C.blue})` }} />
            </div>
            <span style={{ fontFamily: F.mono, fontSize: 22, color: C.blue, fontWeight: 600 }}>idea clarity {Math.round(clarity * 100)}%</span>
          </div>
        </Card>
      </Pop>
    </AbsoluteFill>
  );
};
