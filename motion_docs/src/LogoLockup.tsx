import React from 'react';
import { AbsoluteFill } from 'remotion';
import { Logo } from './components';
import { C, F } from './theme';

// Logotipo estático para o README (fundo transparente, variantes clara e escura).
export const LogoLockup: React.FC<{ dark: boolean }> = ({ dark }) => (
  <AbsoluteFill style={{ alignItems: 'center', justifyContent: 'center' }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 36 }}>
      <div style={{ filter: 'drop-shadow(0 18px 26px rgba(31,94,255,0.35))' }}>
        <Logo size={190} />
      </div>
      <div style={{ fontFamily: F.sans, fontWeight: 800, fontSize: 160, letterSpacing: -5, color: dark ? C.white : C.ink }}>
        Pain<span style={{ color: dark ? C.sky : C.blue }}>killer</span>
      </div>
    </div>
  </AbsoluteFill>
);
