import React from 'react';
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from 'remotion';
import { C, F, glow, shadow } from '../theme';
import { ease, pop } from './anim';

// ---------- fundo ----------

export const Background: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ background: C.paper, overflow: 'hidden' }}>
      <div
        style={{
          position: 'absolute', width: 1000, height: 1000, borderRadius: '50%', left: -320, top: -380,
          background: 'radial-gradient(circle, rgba(95,162,255,0.30), rgba(95,162,255,0) 70%)',
          translate: `${Math.sin(frame / 90) * 40}px ${Math.sin(frame / 70) * 30}px`,
        }}
      />
      <div
        style={{
          position: 'absolute', width: 1100, height: 1100, borderRadius: '50%', right: -420, bottom: -480,
          background: 'radial-gradient(circle, rgba(31,94,255,0.16), rgba(31,94,255,0) 70%)',
          translate: `${Math.sin(frame / 80) * 50}px ${Math.sin(frame / 110) * 30}px`,
        }}
      />
      <svg width="100%" height="100%" style={{ position: 'absolute', inset: 0, opacity: 0.5 }}>
        <defs>
          <pattern id="bg-dots" width="36" height="36" patternUnits="userSpaceOnUse"
            patternTransform={`translate(${(frame * 0.25) % 36} ${(frame * 0.15) % 36})`}>
            <circle cx="2" cy="2" r="1.6" fill="#C6D6F5" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#bg-dots)" />
      </svg>
    </AbsoluteFill>
  );
};

// ---------- tipografia ----------

export const Heading: React.FC<{ eyebrow: string; title: string; subtitle?: string; at?: number }> = ({ eyebrow, title, subtitle, at = 0 }) => {
  const frame = useCurrentFrame();
  const t = ease(frame, at, 22);
  const s = ease(frame, at + 6, 22);
  return (
    <div style={{ position: 'absolute', left: 120, top: 140 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 14, opacity: t }}>
        <div style={{ width: 40 * t, height: 3, background: C.blue, borderRadius: 2 }} />
        <span style={{ fontFamily: F.mono, fontSize: 22, letterSpacing: 4, color: C.blue, textTransform: 'uppercase' }}>{eyebrow}</span>
      </div>
      <div style={{ fontFamily: F.sans, fontWeight: 800, fontSize: 76, color: C.ink, letterSpacing: -2, lineHeight: 1.04, opacity: t, translate: `0 ${(1 - t) * 26}px` }}>
        {title}
      </div>
      {subtitle && (
        <div style={{ fontFamily: F.sans, fontSize: 32, color: C.inkSoft, marginTop: 14, fontWeight: 500, opacity: s, translate: `0 ${(1 - s) * 18}px` }}>
          {subtitle}
        </div>
      )}
    </div>
  );
};

// ---------- blocos ----------

// Entra com mola a partir do frame `at`.
export const Pop: React.FC<{ at: number; from?: number; style?: React.CSSProperties; children: React.ReactNode; damping?: number }> = ({
  at, from = 0.6, style, children, damping,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = pop(frame, fps, at, damping);
  return (
    <div style={{ position: 'absolute', ...style, opacity: Math.min(1, p * 1.5), scale: String(from + (1 - from) * p) }}>
      {children}
    </div>
  );
};

// Sobe e aparece a partir do frame `at`.
export const Rise: React.FC<{ at: number; dist?: number; style?: React.CSSProperties; children: React.ReactNode }> = ({ at, dist = 30, style, children }) => {
  const frame = useCurrentFrame();
  const t = ease(frame, at, 20);
  return <div style={{ ...style, opacity: t, translate: `0 ${(1 - t) * dist}px` }}>{children}</div>;
};

export const Card: React.FC<{ style?: React.CSSProperties; children: React.ReactNode }> = ({ style, children }) => (
  <div style={{ background: C.white, borderRadius: 24, boxShadow: shadow, border: `1px solid ${C.line}`, ...style }}>{children}</div>
);

export const Chip: React.FC<{ children: React.ReactNode; active?: boolean; style?: React.CSSProperties }> = ({ children, active, style }) => (
  <div
    style={{
      display: 'inline-flex', alignItems: 'center', gap: 10, padding: '12px 24px', borderRadius: 999,
      fontFamily: F.sans, fontWeight: 700, fontSize: 26, whiteSpace: 'nowrap',
      background: active ? C.blue : C.white, color: active ? C.white : C.ink,
      border: `1.5px solid ${active ? C.blue : C.line}`, boxShadow: active ? glow : 'none',
      ...style,
    }}
  >
    {children}
  </div>
);

export const Tag: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <span style={{ fontFamily: F.mono, fontSize: 20, fontWeight: 600, color: C.white, background: C.blue, borderRadius: 8, padding: '4px 12px' }}>
    {children}
  </span>
);

// Contentor Docker: cabeçalho em gradiente, corpo branco.
export const ContainerBox: React.FC<{
  label: string; sublabel?: string; width: number; height: number; active?: boolean; children?: React.ReactNode; style?: React.CSSProperties;
}> = ({ label, sublabel, width, height, active, children, style }) => (
  <div
    style={{
      width, height, borderRadius: 24, background: C.white, overflow: 'hidden', display: 'flex', flexDirection: 'column',
      border: `2px solid ${active ? C.blue : C.line}`,
      boxShadow: active ? `${shadow}, 0 0 0 8px rgba(31,94,255,0.12)` : shadow,
      ...style,
    }}
  >
    <div style={{ height: 56, flex: 'none', background: `linear-gradient(90deg, ${C.blue}, ${C.sky})`, display: 'flex', alignItems: 'center', padding: '0 20px', gap: 12 }}>
      <Icon name="container" size={28} color={C.white} />
      <span style={{ fontFamily: F.mono, fontSize: 21, color: C.white, fontWeight: 600 }}>{label}</span>
      {sublabel && <span style={{ fontFamily: F.mono, fontSize: 18, color: 'rgba(255,255,255,0.85)', marginLeft: 'auto' }}>{sublabel}</span>}
    </div>
    <div style={{ flex: 1, position: 'relative' }}>{children}</div>
  </div>
);

export const AgentBot: React.FC<{ size?: number; busy?: boolean }> = ({ size = 90, busy }) => {
  const frame = useCurrentFrame();
  const blink = frame % 96 < 4 ? 0.15 : 1;
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" style={{ translate: `0 ${Math.sin(frame / 9) * 3}px`, overflow: 'visible' }}>
      <line x1="50" y1="8" x2="50" y2="22" stroke={C.blue} strokeWidth="4" strokeLinecap="round" />
      <circle cx="50" cy="8" r="6" fill={busy && frame % 20 < 10 ? C.blue : C.sky} />
      <rect x="14" y="22" width="72" height="60" rx="20" fill={C.blue} />
      <rect x="24" y="34" width="52" height="30" rx="12" fill={C.white} />
      <ellipse cx="40" cy="49" rx="5" ry={6 * blink} fill={C.blue} />
      <ellipse cx="60" cy="49" rx="5" ry={6 * blink} fill={C.blue} />
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
    {label && <span style={{ fontFamily: F.sans, fontWeight: 700, fontSize: 26, color: C.ink }}>{label}</span>}
  </div>
);

// Caminho SVG desenhado progressivamente (progress 0..1), com ponta de seta no fim.
export const Arrow: React.FC<{ d: string; progress: number; color?: string; width?: number; dashed?: boolean; head?: boolean }> = ({
  d, progress, color = C.blue, width = 4, dashed, head = true,
}) => {
  const id = React.useId().replace(/:/g, '');
  if (progress <= 0) return null;
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
      <path d={d} stroke={color} strokeWidth={width} fill="none" strokeLinecap="round" strokeDasharray={dashed ? '10 12' : undefined}
        mask={`url(#m${id})`} markerEnd={head && progress > 0.97 ? `url(#h${id})` : undefined} />
    </>
  );
};

// Camada SVG do tamanho do quadro, para setas e ligações.
export const Wires: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <svg width={1920} height={1080} style={{ position: 'absolute', inset: 0, pointerEvents: 'none', overflow: 'visible' }}>{children}</svg>
);

export const Typewriter: React.FC<{ text: string; at: number; cps?: number; style?: React.CSSProperties }> = ({ text, at, cps = 34, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const n = Math.max(0, Math.floor(((frame - at) / fps) * cps));
  return (
    <span style={style}>
      {text.slice(0, n)}
      {frame >= at && n < text.length && <span style={{ opacity: frame % 16 < 8 ? 1 : 0 }}>▍</span>}
    </span>
  );
};

// Ponteiro do mouse: segue keyframes [frame, x, y] e "clica" nos frames de `clicks`.
export const Cursor: React.FC<{ path: [number, number, number][]; clicks?: number[] }> = ({ path, clicks = [] }) => {
  const frame = useCurrentFrame();
  if (frame < path[0][0] - 8) return null;
  let x = path[0][1];
  let y = path[0][2];
  for (let i = 1; i < path.length; i++) {
    const [f0, x0, y0] = path[i - 1];
    const [f1, x1, y1] = path[i];
    if (frame >= f0) {
      const t = ease(frame, f0, f1 - f0, (v) => 1 - Math.pow(1 - v, 3));
      x = x0 + (x1 - x0) * t;
      y = y0 + (y1 - y0) * t;
    }
  }
  const press = clicks.reduce((m, c) => Math.max(m, frame >= c && frame < c + 8 ? 1 - (frame - c) / 8 : 0), 0);
  const ripple = clicks.map((c) => (frame >= c && frame < c + 22 ? (frame - c) / 22 : -1)).find((r) => r >= 0) ?? -1;
  // some depois do último clique (ou do último keyframe)
  const end = Math.max(path[path.length - 1][0], ...clicks);
  const appear = ease(frame, path[0][0] - 8, 8) * (1 - ease(frame, end + 18, 10));
  return (
    <div style={{ position: 'absolute', left: x, top: y, opacity: appear, zIndex: 50, pointerEvents: 'none' }}>
      {ripple >= 0 && (
        <div style={{
          position: 'absolute', left: -40 * ripple - 6, top: -40 * ripple - 6, width: 80 * ripple + 12, height: 80 * ripple + 12,
          borderRadius: '50%', border: `3px solid ${C.blue}`, opacity: 1 - ripple,
        }} />
      )}
      <svg width="44" height="44" viewBox="0 0 24 24" style={{ scale: String(1 - press * 0.18), transformOrigin: '0 0', filter: 'drop-shadow(0 6px 10px rgba(10,27,61,0.35))' }}>
        <path d="M4 2 L4 19 L8.5 15 L11.5 22 L14.5 20.7 L11.6 14 L18 14 Z" fill={C.ink} stroke={C.white} strokeWidth="1.4" strokeLinejoin="round" />
      </svg>
    </div>
  );
};

// ---------- ícones (SVG inline) ----------

export type IconName =
  | 'container' | 'bulb' | 'doc' | 'list' | 'code' | 'rocket' | 'check' | 'branch' | 'git' | 'globe' | 'chat'
  | 'spark' | 'shield' | 'pause' | 'play' | 'wrench' | 'coin' | 'bolt' | 'cloud' | 'ticket' | 'eye' | 'cross' | 'alert' | 'merge';

export const Icon: React.FC<{ name: IconName; size?: number; color?: string; stroke?: number }> = ({ name, size = 32, color = C.blue, stroke = 2 }) => {
  const p = { fill: 'none', stroke: color, strokeWidth: stroke, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  const paths: Record<IconName, React.ReactNode> = {
    container: (<><rect x="3" y="8" width="18" height="12" rx="2" {...p} /><path d="M7 8v12M11 8v12M15 8v12M5 8l2-4h10l2 4" {...p} /></>),
    bulb: (<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.8.8 1 1.5 1 2.5h6c0-1 .2-1.7 1-2.5A6 6 0 0 0 12 3z" {...p} />),
    doc: (<><path d="M6 3h8l4 4v14H6z" {...p} /><path d="M14 3v4h4M9 12h6M9 16h6" {...p} /></>),
    list: (<><path d="M9 6h11M9 12h11M9 18h11" {...p} /><circle cx="5" cy="6" r="1.2" fill={color} /><circle cx="5" cy="12" r="1.2" fill={color} /><circle cx="5" cy="18" r="1.2" fill={color} /></>),
    code: (<path d="M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16" {...p} />),
    rocket: (<><path d="M12 15l-3-3c1.5-4.5 5-8 10-8 0 5-3.5 8.5-8 10z" {...p} /><path d="M9 12l-4 1-2 3 4 1M12 15l-1 4 3 2 1-4" {...p} /><circle cx="15" cy="9" r="1.5" {...p} /></>),
    check: (<path d="M5 12.5l4.5 4.5L19 7.5" {...p} />),
    branch: (<><circle cx="6" cy="5" r="2" {...p} /><circle cx="6" cy="19" r="2" {...p} /><circle cx="18" cy="8" r="2" {...p} /><path d="M6 7v10M18 10c0 4-6 3-11.5 7.5" {...p} /></>),
    git: (<><circle cx="12" cy="12" r="3" {...p} /><path d="M3 12h6M15 12h6" {...p} /></>),
    globe: (<><circle cx="12" cy="12" r="9" {...p} /><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18" {...p} /></>),
    chat: (<path d="M4 5h16v11H9l-5 4z" {...p} />),
    spark: (<path d="M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z" {...p} />),
    shield: (<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z" {...p} />),
    pause: (<path d="M9 6v12M15 6v12" {...p} />),
    play: (<path d="M7 5l12 7-12 7z" {...p} />),
    wrench: (<path d="M14.5 6.5a4 4 0 0 0 5 5L13 18a2.1 2.1 0 0 1-3-3l6.5-6.5a4 4 0 0 0-2-2zM4 20l5-5" {...p} />),
    coin: (<><ellipse cx="12" cy="7" rx="7" ry="3" {...p} /><path d="M5 7v10c0 1.7 3 3 7 3s7-1.3 7-3V7M5 12c0 1.7 3 3 7 3s7-1.3 7-3" {...p} /></>),
    bolt: (<path d="M13 3L5 14h6l-1 7 8-11h-6z" {...p} />),
    cloud: (<path d="M7 18h10a4 4 0 0 0 .5-8A6 6 0 0 0 6 9.5 4.3 4.3 0 0 0 7 18z" {...p} />),
    ticket: (<path d="M3 7h18v3a2 2 0 0 0 0 4v3H3v-3a2 2 0 0 0 0-4zM14 7v10" {...p} />),
    eye: (<><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" {...p} /><circle cx="12" cy="12" r="3" {...p} /></>),
    cross: (<path d="M6 6l12 12M18 6L6 18" {...p} />),
    alert: (<><path d="M12 3l10 18H2z" {...p} /><path d="M12 10v5M12 18v.01" {...p} /></>),
    merge: (<><circle cx="6" cy="5" r="2" {...p} /><circle cx="6" cy="19" r="2" {...p} /><circle cx="18" cy="19" r="2" {...p} /><path d="M6 7v10M6 9c0 6 12 4 12 8" {...p} /></>),
  };
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" style={{ flex: 'none' }}>
      {paths[name]}
    </svg>
  );
};

// Logotipo: cápsula azul/branca.
export const Logo: React.FC<{ size?: number; spin?: number }> = ({ size = 160, spin = 0 }) => {
  const id = React.useId().replace(/:/g, '');
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" style={{ rotate: `${spin}deg` }}>
      <defs>
        <linearGradient id={`g${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor={C.sky} />
          <stop offset="1" stopColor={C.blueDeep} />
        </linearGradient>
        <clipPath id={`c${id}`}>
          <rect x="32" y="6" width="36" height="88" rx="18" transform="rotate(45 50 50)" />
        </clipPath>
      </defs>
      <g clipPath={`url(#c${id})`}>
        <rect x="0" y="0" width="100" height="100" fill={C.white} />
        <polygon points="0,0 100,100 0,100" fill={`url(#g${id})`} />
      </g>
      <rect x="32" y="6" width="36" height="88" rx="18" transform="rotate(45 50 50)" fill="none" stroke={C.blueDeep} strokeWidth="3" />
      <ellipse cx="34" cy="58" rx="4" ry="11" transform="rotate(45 34 58)" fill={C.white} opacity="0.45" />
    </svg>
  );
};

export const Wordmark: React.FC<{ size: number; dark?: boolean }> = ({ size, dark }) => (
  <span style={{ fontFamily: F.sans, fontWeight: 800, fontSize: size, letterSpacing: -size * 0.035, color: dark ? C.white : C.ink, lineHeight: 1 }}>
    Pain<span style={{ color: dark ? C.sky : C.blue }}>killer</span>
  </span>
);
