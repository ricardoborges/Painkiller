import React from 'react';
import { AbsoluteFill } from 'remotion';
import { Logo, Wordmark } from './ui/kit';

// Logotipo estático para o README e a landing page (fundo transparente).
export const LogoLockup: React.FC<{ dark: boolean }> = ({ dark }) => (
  <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 36 }}>
      <div style={{ filter: 'drop-shadow(0 18px 26px rgba(31,94,255,0.35))' }}>
        <Logo size={190} />
      </div>
      <Wordmark size={160} dark={dark} />
    </div>
  </AbsoluteFill>
);
