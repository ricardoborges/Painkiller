import { Easing, interpolate, spring } from 'remotion';

export const EASE_OUT = Easing.bezier(0.16, 1, 0.3, 1);
export const EASE_IN_OUT = Easing.bezier(0.65, 0, 0.35, 1);

const clamp = { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' } as const;

// 0 → 1 a partir do frame `at`, com desaceleração suave.
export const ease = (frame: number, at: number, dur = 18, easing = EASE_OUT) =>
  interpolate(frame, [at, at + dur], [0, 1], { ...clamp, easing });

// Mola com leve overshoot, para elementos que "entram".
export const pop = (frame: number, fps: number, at: number, damping = 14) =>
  spring({ frame: frame - at, fps, config: { damping, mass: 0.8 } });

export const lerp = (t: number, a: number, b: number) => a + (b - a) * t;

// Valor entre keyframes [frame, valor] com easing in-out.
export const keys = (frame: number, kf: [number, number][]) =>
  interpolate(frame, kf.map((k) => k[0]), kf.map((k) => k[1]), { ...clamp, easing: EASE_IN_OUT });
