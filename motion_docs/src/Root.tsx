import React from 'react';
import { Composition } from 'remotion';
import { TOTAL_FRAMES, Video } from './Video';
import { LogoLockup } from './LogoLockup';
import { FPS } from './theme';

export const Root: React.FC = () => (
  <>
    <Composition id="Painkiller" component={Video} durationInFrames={TOTAL_FRAMES} fps={FPS} width={1920} height={1080} />
    <Composition id="LogoLight" component={LogoLockup} defaultProps={{ dark: false }} durationInFrames={1} fps={FPS} width={1200} height={300} />
    <Composition id="LogoDark" component={LogoLockup} defaultProps={{ dark: true }} durationInFrames={1} fps={FPS} width={1200} height={300} />
  </>
);
