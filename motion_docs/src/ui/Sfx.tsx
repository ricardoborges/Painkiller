import React from 'react';
import { Audio } from '@remotion/media';
import { staticFile, useVideoConfig } from 'remotion';

export type SfxName = 'whoosh' | 'mouse-click' | 'ding' | 'switch' | 'page-turn';

// Efeito sonoro curto no frame `at` (local à cena).
export const Sfx: React.FC<{ name: SfxName; at: number; volume?: number }> = ({ name, at, volume = 0.35 }) => {
  const { fps } = useVideoConfig();
  return <Audio name={`SFX ${name}`} src={staticFile(`sfx/${name}.wav`)} from={Math.max(0, at)} volume={volume} premountFor={fps} />;
};
