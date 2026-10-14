import React from 'react';
import { AbsoluteFill, interpolate, useCurrentFrame } from 'remotion';
import { C, F } from '../theme';
import { AgentBot, Card, Chip, ContainerBox, DrawPath, Heading, Icon, Person, Pop, ramp, Typewriter, useSpring } from '../components';

const s = (sec: number) => Math.round(sec * 30);

// 4. Spec-driven: a spec é escrita, versionada e decomposta em tarefas atômicas.
const TASKS = [
  { id: 'T1', title: 'Data model: appointments', deps: [] as number[] },
  { id: 'T2', title: 'Booking REST API', deps: [0] },
  { id: 'T3', title: 'Patient booking page', deps: [1] },
  { id: 'T4', title: 'Email confirmations', deps: [1] },
  { id: 'T5', title: 'Admin calendar view', deps: [0] },
  { id: 'T6', title: 'End-to-end tests', deps: [2, 3] },
];
const TASK_POS = [
  { x: 1040, y: 330 }, { x: 1040, y: 520 }, { x: 1040, y: 710 },
  { x: 1440, y: 520 }, { x: 1440, y: 330 }, { x: 1440, y: 710 },
];

export const Spec: React.FC = () => {
  const frame = useCurrentFrame();
  const lines = [0.9, 0.7, 0.85, 0.5, 0.95, 0.75, 0.6, 0.88];
  const commit = useSpring(s(3.0), 15);
  const split = ramp(frame, s(7.4), s(9.6));
  const depP = ramp(frame, s(11.0), s(13.0));
  const docX = interpolate(split, [0, 1], [700, 160]);
  return (
    <AbsoluteFill>
      <Heading step="Step 2 · Spec-driven" title="The spec drives everything" sub="written, versioned, then decomposed into atomic tasks" />
      <Pop delay={s(0.2)} from={0.85} style={{ position: 'absolute', left: docX, top: 300 }}>
        <Card style={{ width: 520, height: 640, padding: 36, position: 'relative' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 26 }}>
            <Icon name="doc" size={40} />
            <span style={{ fontFamily: F.mono, fontSize: 19, color: C.inkSoft }}>docs/superpowers/specs/booking.md</span>
          </div>
          <div style={{ fontFamily: F.sans, fontWeight: 800, fontSize: 34, color: C.ink, marginBottom: 22 }}>
            <Typewriter text="Clinic booking — design" start={s(0.4)} cps={30} />
          </div>
          {lines.map((w, i) => {
            const p = ramp(frame, s(1.0) + i * 6, s(1.0) + i * 6 + 14);
            return <div key={i} style={{ height: 14, borderRadius: 7, background: i % 4 === 0 ? C.sky : C.ice, width: `${w * 100 * p}%`, marginBottom: 20 }} />;
          })}
          <div style={{
            position: 'absolute', left: 36, bottom: 30, display: 'flex', alignItems: 'center', gap: 12, opacity: commit,
            transform: `translateY(${(1 - commit) * 16}px)`, padding: '10px 18px', borderRadius: 12, background: C.blue,
          }}>
            <Icon name="branch" size={26} color={C.white} />
            <span style={{ fontFamily: F.mono, fontSize: 20, color: C.white }}>committed to main · a3f9c1e</span>
          </div>
        </Card>
      </Pop>
      <svg width={1920} height={1080} style={{ position: 'absolute' }}>
        {split > 0 && TASK_POS.map((p, i) => (
          <DrawPath key={i} d={`M 690 ${620} C 820 ${620}, 860 ${p.y + 60}, ${p.x - 10} ${p.y + 60}`}
            progress={ramp(frame, s(7.6) + i * 3, s(8.8) + i * 3)} color={C.sky} width={3} head={false} />
        ))}
        {TASKS.map((t, i) => t.deps.map((d) => {
          const a = TASK_POS[d];
          const b = TASK_POS[i];
          const sameCol = a.x === b.x;
          const path = sameCol
            ? `M ${a.x + 170} ${a.y + 120} L ${b.x + 170} ${b.y}`
            : `M ${a.x + 340} ${a.y + 60} L ${b.x} ${b.y + 60}`;
          return <DrawPath key={`${i}-${d}`} d={path} progress={depP} width={3} />;
        }))}
      </svg>
      {TASKS.map((t, i) => {
        const sp = useSpring(s(8.0) + i * 4, 14);
        const p = TASK_POS[i];
        return (
          <div key={t.id} style={{ position: 'absolute', left: p.x, top: p.y, opacity: sp, transform: `scale(${0.6 + 0.4 * sp})` }}>
            <Card style={{ width: 340, height: 120, padding: '18px 22px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ fontFamily: F.mono, fontSize: 18, fontWeight: 600, color: C.white, background: C.blue, borderRadius: 8, padding: '3px 10px' }}>{t.id}</span>
                <span style={{ fontFamily: F.sans, fontWeight: 700, fontSize: 22, color: C.ink }}>{t.title}</span>
              </div>
              <div style={{ display: 'flex', gap: 8, opacity: ramp(frame, s(10.4) + i * 3, s(11.2) + i * 3) }}>
                {[0, 1, 2].map((k) => (
                  <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <div style={{ width: 18, height: 18, borderRadius: 5, background: C.ice, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <Icon name="check" size={14} stroke={3} />
                    </div>
                    <div style={{ width: 50, height: 8, borderRadius: 4, background: C.line }} />
                  </div>
                ))}
              </div>
            </Card>
          </div>
        );
      })}
      <div style={{ position: 'absolute', left: 1040, top: 880, fontFamily: F.mono, fontSize: 22, color: C.inkSoft, opacity: depP }}>
        acceptance criteria · dependencies
      </div>
    </AbsoluteFill>
  );
};

// 5. Harness: cada tarefa num contentor, num feature branch; harness escolhido por projeto.
const HARNESSES = [
  { name: 'Antigravity', model: 'Gemini' },
  { name: 'dsh', model: 'DeepSeek' },
  { name: 'Maki', model: 'DeepSeek' },
  { name: 'Unreal Agent', model: 'DeepSeek' },
];
const SKILLS = ['brainstorming', 'writing-plans', 'test-driven-development', 'systematic-debugging'];

export const Harness: React.FC = () => {
  const frame = useCurrentFrame();
  const hubPop = useSpring(s(0.2), 14);
  const harnessT = ramp(frame, s(5.2), s(12.6), (x) => x);
  const active = frame < s(5.2) ? -1 : Math.min(3, Math.floor(harnessT * 4));
  const skillsIn = s(13.4);
  const cols = [170, 590, 1010, 1430];
  return (
    <AbsoluteFill>
      <Heading step="Step 3 · Orchestration" title="One sandbox per task" sub="any harness, the same Superpowers skills" />
      {/* hub */}
      <div style={{ position: 'absolute', left: 1320, top: 110, opacity: hubPop, transform: `scale(${hubPop})` }}>
        <Card style={{ padding: '20px 28px', display: 'flex', alignItems: 'center', gap: 18 }}>
          <div style={{ width: 56, height: 56, borderRadius: 16, background: C.blue, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Icon name="bolt" size={34} color={C.white} />
          </div>
          <div>
            <div style={{ fontFamily: F.sans, fontWeight: 800, fontSize: 28, color: C.ink }}>Orchestrator</div>
            <div style={{ fontFamily: F.mono, fontSize: 18, color: C.inkSoft }}>dispatch_task()</div>
          </div>
        </Card>
      </div>
      <svg width={1920} height={1080} style={{ position: 'absolute' }}>
        {cols.map((x, i) => (
          <DrawPath key={i} d={`M 1480 210 C 1480 300, ${x + 160} 260, ${x + 160} 350`}
            progress={ramp(frame, s(0.8) + i * 5, s(1.8) + i * 5)} width={3} />
        ))}
      </svg>
      {cols.map((x, i) => {
        const sp = useSpring(s(1.2) + i * 5, 14);
        const h = HARNESSES[Math.max(0, active)];
        const working = (frame / 6 + i * 3) % 12;
        return (
          <div key={i} style={{ position: 'absolute', left: x, top: 360, opacity: sp, transform: `translateY(${(1 - sp) * 40}px)` }}>
            <ContainerBox label={`T${i + 1}`} sublabel="sandbox" width={320} height={330} glow={active >= 0 ? 1 : 0}>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: 16, gap: 12 }}>
                <AgentBot size={96} />
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: F.mono, fontSize: 18, color: C.blueDeep }}>
                  <Icon name="branch" size={22} />
                  feature/T{i + 1}
                </div>
                <div style={{ display: 'flex', gap: 5 }}>
                  {Array.from({ length: 12 }).map((_, k) => (
                    <div key={k} style={{ width: 12, height: 6, borderRadius: 3, background: k <= working ? C.sky : C.ice }} />
                  ))}
                </div>
                <div style={{ fontFamily: F.sans, fontSize: 19, fontWeight: 700, color: C.blue, opacity: active >= 0 ? 1 : 0 }}>
                  {h.name} · {h.model}
                </div>
              </div>
            </ContainerBox>
          </div>
        );
      })}
      {/* seletor de harness */}
      <div style={{ position: 'absolute', left: 0, right: 0, top: 735, display: 'flex', justifyContent: 'center', gap: 16, opacity: ramp(frame, s(5.0), s(5.6)) }}>
        <span style={{ fontFamily: F.mono, fontSize: 22, color: C.inkSoft, alignSelf: 'center', marginRight: 6 }}>harness:</span>
        {HARNESSES.map((h, i) => (
          <Chip key={h.name} active={active === i}>
            {h.name}
            <span style={{ fontWeight: 500, opacity: 0.75, fontSize: 18 }}>{h.model}</span>
          </Chip>
        ))}
      </div>
      {/* skills */}
      <div style={{ position: 'absolute', left: 0, right: 0, top: 840, display: 'flex', justifyContent: 'center', gap: 18 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, opacity: ramp(frame, skillsIn - 10, skillsIn) }}>
          <Icon name="spark" size={34} />
          <span style={{ fontFamily: F.sans, fontWeight: 800, fontSize: 28, color: C.blue }}>Superpowers</span>
        </div>
        {SKILLS.map((sk, i) => {
          const sp = useSpring(skillsIn + i * s(1.2), 14);
          return (
            <div key={sk} style={{ opacity: sp, transform: `translateY(${(1 - sp) * 30}px)` }}>
              <Chip active={frame > skillsIn + i * s(1.2) && frame < skillsIn + (i + 1) * s(1.2) + 10}
                style={{ fontFamily: F.mono, fontSize: 20 }}>{sk}</Chip>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// 6. Interrupção limpa: painkiller ask -> exit 42 -> analista responde -> retoma.
export const Ask: React.FC = () => {
  const frame = useCurrentFrame();
  const exit = useSpring(s(5.2), 10);
  const pause = frame > s(7.0);
  const answer = useSpring(s(8.4), 15);
  const back = ramp(frame, s(9.4), s(10.6));
  const resumed = frame > s(10.8);
  const pulse = 1 + 0.04 * Math.sin(frame / 4);
  return (
    <AbsoluteFill>
      <Heading step="Clean interruption" title="Ask, don't guess" sub="the agent pauses with exit code 42" />
      <Pop delay={s(0.2)} from={0.9} style={{ position: 'absolute', left: 120, top: 330 }}>
        <ContainerBox label="painkiller-worker" sublabel="feature/T4" width={860} height={560}>
          <div style={{ position: 'absolute', inset: 0, background: '#0B1A3A', padding: 30, fontFamily: F.mono, fontSize: 24, lineHeight: 1.7, color: '#C9D8FF' }}>
            <div style={{ opacity: ramp(frame, 4, 14) }}><span style={{ color: C.sky }}>agent</span> reading spec and plan…</div>
            <div style={{ opacity: ramp(frame, s(1.2), s(1.6)) }}><span style={{ color: C.sky }}>agent</span> unclear: which email provider?</div>
            <div style={{ marginTop: 10 }}>
              {frame > s(3.0) && <span style={{ color: '#7FB0FF' }}>$ </span>}
              <Typewriter text={'painkiller ask "SendGrid or SMTP?"'} start={s(3.0)} cps={28} style={{ color: C.white }} />
            </div>
            <div style={{ opacity: ramp(frame, s(4.4), s(4.8)) }}>✓ WIP committed · clarification.json written</div>
            {resumed && (
              <div style={{ marginTop: 10, color: C.white, opacity: ramp(frame, s(10.8), s(11.2)) }}>
                <span style={{ color: C.sky }}>agent</span> resuming on feature/T4 with “SMTP”…
              </div>
            )}
          </div>
          <div style={{
            position: 'absolute', right: 30, bottom: 30, opacity: exit * (resumed ? 0 : 1), transform: `scale(${0.5 + exit * 0.5}) rotate(${(1 - exit) * -12}deg)`,
            background: C.white, borderRadius: 18, padding: '14px 26px', display: 'flex', alignItems: 'baseline', gap: 12,
            boxShadow: '0 0 0 6px rgba(95,162,255,0.4)',
          }}>
            <span style={{ fontFamily: F.mono, fontSize: 24, color: C.inkSoft }}>exit</span>
            <span style={{ fontFamily: F.sans, fontWeight: 800, fontSize: 72, color: C.blue, lineHeight: 1 }}>42</span>
          </div>
        </ContainerBox>
      </Pop>
      {/* cartão da tarefa */}
      <Pop delay={s(6.6)} style={{ position: 'absolute', left: 1120, top: 330 }}>
        <Card style={{ width: 640, padding: 28, transform: pause && !resumed ? `scale(${pulse})` : undefined, border: `2px solid ${pause && !resumed ? C.blue : C.line}` }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <span style={{ fontFamily: F.mono, fontSize: 18, fontWeight: 600, color: C.white, background: C.blue, borderRadius: 8, padding: '3px 10px' }}>T4</span>
            <span style={{ fontFamily: F.sans, fontWeight: 700, fontSize: 26, color: C.ink }}>Email confirmations</span>
          </div>
          <div style={{ marginTop: 18, display: 'flex', alignItems: 'center', gap: 10 }}>
            <Icon name={resumed ? 'play' : 'pause'} size={28} stroke={3} />
            <span style={{ fontFamily: F.mono, fontSize: 22, color: C.blue, fontWeight: 600 }}>{resumed ? 'RUNNING' : 'AWAITING ANALYST'}</span>
          </div>
          <div style={{ marginTop: 16, fontFamily: F.sans, fontSize: 24, color: C.inkSoft }}>“SendGrid or SMTP?”</div>
        </Card>
      </Pop>
      <div style={{ position: 'absolute', left: 1140, top: 640, display: 'flex', alignItems: 'center', gap: 24, opacity: answer, transform: `translateY(${(1 - answer) * 20}px)` }}>
        <Person size={110} />
        <div style={{ background: C.blue, color: C.white, borderRadius: '22px 22px 22px 6px', padding: '16px 24px', fontFamily: F.sans, fontWeight: 600, fontSize: 26 }}>
          SMTP — we already have a server.
        </div>
      </div>
      <svg width={1920} height={1080} style={{ position: 'absolute', pointerEvents: 'none' }}>
        <DrawPath d="M 1130 800 C 1060 860, 1040 880, 990 860" progress={back} width={4} />
      </svg>
    </AbsoluteFill>
  );
};
