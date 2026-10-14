import React from 'react';
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig, Easing } from 'remotion';
import { C, F, shadow } from './theme';

// ---------- tempo ----------

export const useSpring = (delay = 0, damping = 14, mass = 0.8) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame: frame - delay, fps, config: { damping, mass } });
};

export const ramp = (frame: number, from: number, to: number, ease = Easing.inOut(Easing.cubic)) =>
  interpolate(frame, [from, to], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease });

// ---------- fundo ----------

export const Background: React.FC = () => {
  const frame = useCurrentFrame();
  const drift = (s: number, a: number) => Math.sin(frame / s) * a;
  return (
    <AbsoluteFill style={{ background: C.paper, overflow: 'hidden' }}>
      <div
        style={{
          position: 'absolute', width: 900, height: 900, borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(95,162,255,0.32), rgba(95,162,255,0) 70%)',
          left: -260 + drift(90, 40), top: -320 + drift(70, 30),
        }}
      />
      <div
        style={{
          position: 'absolute', width: 1000, height: 1000, borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(31,94,255,0.18), rgba(31,94,255,0) 70%)',
          right: -360 + drift(80, 50), bottom: -420 + drift(110, 30),
        }}
      />
      <svg width="100%" height="100%" style={{ position: 'absolute', inset: 0, opacity: 0.55 }}>
        <defs>
          <pattern id="dots" width="36" height="36" patternUnits="userSpaceOnUse"
            patternTransform={`translate(${(frame * 0.25) % 36} ${(frame * 0.15) % 36})`}>
            <circle cx="2" cy="2" r="1.6" fill="#C6D6F5" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#dots)" />
      </svg>
    </AbsoluteFill>
  );
};

// Envolve a cena com fade de entrada e saída.
export const SceneFrame: React.FC<{ duration: number; children: React.ReactNode }> = ({ duration, children }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, 12, duration - 12, duration], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  const scale = interpolate(frame, [0, duration], [1.0, 1.025]);
  return <AbsoluteFill style={{ opacity, transform: `scale(${scale})` }}>{children}</AbsoluteFill>;
};

export const Heading: React.FC<{ step?: string; title: string; sub?: string; delay?: number }> = ({ step, title, sub, delay = 0 }) => {
  const s = useSpring(delay, 18);
  return (
    <div style={{ position: 'absolute', left: 120, top: 84, opacity: s, transform: `translateY(${(1 - s) * 24}px)` }}>
      {step && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14 }}>
          <div style={{ width: 36, height: 3, background: C.blue, borderRadius: 2 }} />
          <span style={{ fontFamily: F.mono, fontSize: 22, letterSpacing: 4, color: C.blue, textTransform: 'uppercase' }}>{step}</span>
        </div>
      )}
      <div style={{ fontFamily: F.sans, fontWeight: 800, fontSize: 64, color: C.ink, letterSpacing: -1.5, lineHeight: 1.05 }}>{title}</div>
      {sub && <div style={{ fontFamily: F.sans, fontSize: 28, color: C.inkSoft, marginTop: 14, fontWeight: 500 }}>{sub}</div>}
    </div>
  );
};

// ---------- blocos ----------

export const Pop: React.FC<{ delay?: number; style?: React.CSSProperties; children: React.ReactNode; from?: number }> = ({
  delay = 0, style, children, from = 0.6,
}) => {
  const s = useSpring(delay);
  return (
    <div style={{ ...style, opacity: Math.min(1, s * 1.4), transform: `${style?.transform ?? ''} scale(${from + (1 - from) * s})` }}>
      {children}
    </div>
  );
};

export const Card: React.FC<{ style?: React.CSSProperties; children: React.ReactNode }> = ({ style, children }) => (
  <div style={{ background: C.white, borderRadius: 22, boxShadow: shadow, border: `1px solid ${C.line}`, ...style }}>{children}</div>
);

export const Chip: React.FC<{ children: React.ReactNode; active?: boolean; style?: React.CSSProperties }> = ({ children, active, style }) => (
  <div
    style={{
      display: 'inline-flex', alignItems: 'center', gap: 10, padding: '10px 20px', borderRadius: 999,
      fontFamily: F.sans, fontWeight: 600, fontSize: 22,
      background: active ? C.blue : C.white, color: active ? C.white : C.ink,
      border: `1.5px solid ${active ? C.blue : C.line}`,
      boxShadow: active ? '0 12px 30px -10px rgba(31,94,255,0.6)' : 'none',
      ...style,
    }}
  >
    {children}
  </div>
);

// Caixa de contentor Docker com cabeçalho e um agente dentro.
export const ContainerBox: React.FC<{
  label: string; sublabel?: string; width?: number; height?: number; children?: React.ReactNode; glow?: number; style?: React.CSSProperties;
}> = ({ label, sublabel, width = 360, height = 240, children, glow = 0, style }) => (
  <div
    style={{
      width, height, borderRadius: 22, background: C.white, border: `2px solid ${glow > 0 ? C.blue : C.line}`,
      boxShadow: `${shadow}, 0 0 0 ${glow * 10}px rgba(31,94,255,${0.12 * glow})`, overflow: 'hidden',
      display: 'flex', flexDirection: 'column', ...style,
    }}
  >
    <div style={{ height: 52, background: `linear-gradient(90deg, ${C.blue}, ${C.sky})`, display: 'flex', alignItems: 'center', padding: '0 18px', gap: 12 }}>
      <Icon name="container" size={26} color={C.white} />
      <span style={{ fontFamily: F.mono, fontSize: 19, color: C.white, fontWeight: 600 }}>{label}</span>
      {sublabel && <span style={{ fontFamily: F.mono, fontSize: 16, color: 'rgba(255,255,255,0.8)', marginLeft: 'auto' }}>{sublabel}</span>}
    </div>
    <div style={{ flex: 1, position: 'relative' }}>{children}</div>
  </div>
);

export const AgentBot: React.FC<{ size?: number; blink?: boolean }> = ({ size = 90 }) => {
  const frame = useCurrentFrame();
  const bob = Math.sin(frame / 9) * 3;
  const eye = frame % 90 < 4 ? 0.2 : 1;
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" style={{ transform: `translateY(${bob}px)` }}>
      <line x1="50" y1="8" x2="50" y2="22" stroke={C.blue} strokeWidth="4" strokeLinecap="round" />
      <circle cx="50" cy="8" r="6" fill={C.sky} />
      <rect x="14" y="22" width="72" height="60" rx="20" fill={C.blue} />
      <rect x="24" y="34" width="52" height="30" rx="12" fill={C.white} />
      <ellipse cx="40" cy="49" rx="5" ry={6 * eye} fill={C.blue} />
      <ellipse cx="60" cy="49" rx="5" ry={6 * eye} fill={C.blue} />
      <rect x="34" y="86" width="32" height="8" rx="4" fill={C.sky} />
    </svg>
  );
};

export const Person: React.FC<{ size?: number; label?: string }> = ({ size = 120, label }) => (
  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
    <svg width={size} height={size} viewBox="0 0 100 100">
      <circle cx="50" cy="50" r="48" fill={C.ice} />
      <circle cx="50" cy="40" r="17" fill={C.blue} />
      <path d="M18 86 C22 64 36 58 50 58 C64 58 78 64 82 86" fill={C.blue} />
    </svg>
    {label && <span style={{ fontFamily: F.sans, fontWeight: 700, fontSize: 24, color: C.ink }}>{label}</span>}
  </div>
);

// Seta desenhada progressivamente.
export const DrawPath: React.FC<{ d: string; progress: number; color?: string; width?: number; dashed?: boolean; head?: boolean }> = ({
  d, progress, color = C.blue, width = 4, dashed, head = true,
}) => {
  const id = React.useId().replace(/:/g, '');
  return (
    <>
      <defs>
        <marker id={`h${id}`} viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
          <path d="M0 0 L10 5 L0 10 z" fill={color} />
        </marker>
        <mask id={`m${id}`} maskUnits="userSpaceOnUse" x="0" y="0" width="1920" height="1080">
          <path d={d} stroke="white" strokeWidth={width + 30} fill="none" pathLength={1} strokeDasharray="1 1" strokeDashoffset={1 - progress} />
        </mask>
      </defs>
      <path
        d={d} stroke={color} strokeWidth={width} fill="none" strokeLinecap="round"
        strokeDasharray={dashed ? '10 12' : undefined}
        mask={`url(#m${id})`}
        markerEnd={head && progress > 0.97 ? `url(#h${id})` : undefined}
      />
    </>
  );
};

export const Typewriter: React.FC<{ text: string; start: number; cps?: number; style?: React.CSSProperties; caret?: boolean }> = ({
  text, start, cps = 40, style, caret = true,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const n = Math.max(0, Math.floor(((frame - start) / fps) * cps));
  const done = n >= text.length;
  return (
    <span style={style}>
      {text.slice(0, n)}
      {caret && !done && frame >= start && <span style={{ opacity: frame % 16 < 8 ? 1 : 0 }}>▍</span>}
    </span>
  );
};

// ---------- ícones (SVG inline) ----------

type IconName =
  | 'container' | 'bulb' | 'doc' | 'list' | 'code' | 'rocket' | 'check' | 'branch' | 'git'
  | 'globe' | 'chat' | 'spark' | 'shield' | 'pause' | 'play' | 'wrench' | 'coin' | 'bolt' | 'cloud';

export const Icon: React.FC<{ name: IconName; size?: number; color?: string; stroke?: number }> = ({ name, size = 32, color = C.blue, stroke = 2 }) => {
  const p = { fill: 'none', stroke: color, strokeWidth: stroke, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  const paths: Record<IconName, React.ReactNode> = {
    container: (<><rect x="3" y="8" width="18" height="12" rx="2" {...p} /><path d="M7 8v12M11 8v12M15 8v12M5 8l2-4h10l2 4" {...p} /></>),
    bulb: (<><path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.8.8 1 1.5 1 2.5h6c0-1 .2-1.7 1-2.5A6 6 0 0 0 12 3z" {...p} /></>),
    doc: (<><path d="M6 3h8l4 4v14H6z" {...p} /><path d="M14 3v4h4M9 12h6M9 16h6" {...p} /></>),
    list: (<><path d="M9 6h11M9 12h11M9 18h11" {...p} /><circle cx="5" cy="6" r="1.2" fill={color} /><circle cx="5" cy="12" r="1.2" fill={color} /><circle cx="5" cy="18" r="1.2" fill={color} /></>),
    code: (<><path d="M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16" {...p} /></>),
    rocket: (<><path d="M12 15l-3-3c1.5-4.5 5-8 10-8 0 5-3.5 8.5-8 10z" {...p} /><path d="M9 12l-4 1-2 3 4 1M12 15l-1 4 3 2 1-4" {...p} /><circle cx="15" cy="9" r="1.5" {...p} /></>),
    check: (<path d="M5 12.5l4.5 4.5L19 7.5" {...p} />),
    branch: (<><circle cx="6" cy="5" r="2" {...p} /><circle cx="6" cy="19" r="2" {...p} /><circle cx="18" cy="8" r="2" {...p} /><path d="M6 7v10M18 10c0 4-6 3-11.5 7.5" {...p} /></>),
    git: (<><circle cx="12" cy="12" r="3" {...p} /><path d="M3 12h6M15 12h6" {...p} /></>),
    globe: (<><circle cx="12" cy="12" r="9" {...p} /><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18" {...p} /></>),
    chat: (<path d="M4 5h16v11H9l-5 4z" {...p} />),
    spark: (<path d="M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z" {...p} />),
    shield: (<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" {...p} />),
    pause: (<><path d="M9 6v12M15 6v12" {...p} /></>),
    play: (<path d="M7 5l12 7-12 7z" {...p} />),
    wrench: (<path d="M14.5 6.5a4 4 0 0 0 5 5L13 18a2.1 2.1 0 0 1-3-3l6.5-6.5a4 4 0 0 0-2-2zM4 20l5-5" {...p} />),
    coin: (<><ellipse cx="12" cy="7" rx="7" ry="3" {...p} /><path d="M5 7v10c0 1.7 3 3 7 3s7-1.3 7-3V7M5 12c0 1.7 3 3 7 3s7-1.3 7-3" {...p} /></>),
    bolt: (<path d="M13 3L5 14h6l-1 7 8-11h-6z" {...p} />),
    cloud: (<path d="M7 18h10a4 4 0 0 0 .5-8A6 6 0 0 0 6 9.5 4.3 4.3 0 0 0 7 18z" {...p} />),
  };
  return (
    <svg width={size} height={size} viewBox="0 0 24 24">
      {paths[name]}
    </svg>
  );
};

// Logotipo: cápsula azul/branca.
export const Logo: React.FC<{ size?: number; spin?: number }> = ({ size = 160, spin = 0 }) => (
  <svg width={size} height={size} viewBox="0 0 100 100" style={{ transform: `rotate(${spin}deg)` }}>
    <defs>
      <linearGradient id="capA" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor={C.sky} />
        <stop offset="1" stopColor={C.blueDeep} />
      </linearGradient>
      <clipPath id="capClip">
        <rect x="32" y="6" width="36" height="88" rx="18" transform="rotate(45 50 50)" />
      </clipPath>
    </defs>
    <g clipPath="url(#capClip)">
      <rect x="0" y="0" width="100" height="100" fill={C.white} />
      <polygon points="0,0 100,100 0,100" fill="url(#capA)" />
    </g>
    <rect x="32" y="6" width="36" height="88" rx="18" transform="rotate(45 50 50)" fill="none" stroke={C.blueDeep} strokeWidth="3" />
    <ellipse cx="34" cy="58" rx="4" ry="11" transform="rotate(45 34 58)" fill={C.white} opacity="0.45" />
  </svg>
);
