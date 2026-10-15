import { loadFont as loadSans } from '@remotion/google-fonts/PlusJakartaSans';
import { loadFont as loadMono } from '@remotion/google-fonts/JetBrainsMono';

const sans = loadSans('normal', { weights: ['400', '500', '600', '700', '800'], subsets: ['latin'] });
const mono = loadMono('normal', { weights: ['400', '600'], subsets: ['latin'] });

export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;

export const C = {
  paper: '#F6F9FF',
  white: '#FFFFFF',
  ink: '#0A1B3D',
  inkSoft: '#4A5B7D',
  muted: '#8A9BBC',
  line: '#D8E3F7',
  blue: '#1F5EFF',
  blueDeep: '#0B3BC2',
  sky: '#5FA2FF',
  ice: '#E6EEFF',
  frost: '#F0F5FF',
  night: '#0B1A3A',
};

export const F = {
  sans: sans.fontFamily,
  mono: mono.fontFamily,
};

export const shadow = '0 28px 70px -28px rgba(16, 52, 140, 0.38), 0 2px 8px rgba(16, 52, 140, 0.08)';
export const glow = '0 18px 40px -12px rgba(31, 94, 255, 0.55)';
