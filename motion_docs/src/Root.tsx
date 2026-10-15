import React from 'react';
import { Composition, Folder, Still } from 'remotion';
import { calculatePainkillerMetadata, Painkiller } from './Painkiller';
import { LogoLockup } from './LogoLockup';
import { sceneMetadata } from './voiceover';
import { Hook } from './scenes/Hook';
import { Intro } from './scenes/Intro';
import { Interview } from './scenes/Interview';
import { Spec } from './scenes/Spec';
import { Sandbox } from './scenes/Sandbox';
import { Harness } from './scenes/Harness';
import { Ask } from './scenes/Ask';
import { Verify } from './scenes/Verify';
import { Deploy } from './scenes/Deploy';
import { Fix } from './scenes/Fix';
import { Outro } from './scenes/Outro';

export const Root: React.FC = () => (
  <>
    <Composition
      id="Painkiller"
      component={Painkiller}
      width={1920}
      height={1080}
      fps={30}
      durationInFrames={3300}
      defaultProps={{ voiceovers: null, showCaptions: true, music: true }}
      calculateMetadata={calculatePainkillerMetadata}
    />
    <Folder name="Scenes">
      <Composition id="Hook" component={Hook} width={1920} height={1080} fps={30} durationInFrames={270}
        defaultProps={{ title: 'Describing an app is easy.', subtitle: 'Shipping it is the hard part.', voiceover: null, showCaptions: true, withBackground: true }}
        calculateMetadata={sceneMetadata('hook')} />
      <Composition id="Intro" component={Intro} width={1920} height={1080} fps={30} durationInFrames={340}
        defaultProps={{ title: 'Self-hosted', subtitle: 'Docker sandboxes', voiceover: null, showCaptions: true, withBackground: true }}
        calculateMetadata={sceneMetadata('intro')} />
      <Composition id="Interview" component={Interview} width={1920} height={1080} fps={30} durationInFrames={370}
        defaultProps={{ title: 'An interview, not a form', subtitle: 'Superpowers brainstorming, one question at a time', voiceover: null, showCaptions: true, withBackground: true }}
        calculateMetadata={sceneMetadata('interview')} />
      <Composition id="Spec" component={Spec} width={1920} height={1080} fps={30} durationInFrames={380}
        defaultProps={{ title: 'The spec drives everything', subtitle: 'written, versioned, then split into atomic tasks', voiceover: null, showCaptions: true, withBackground: true }}
        calculateMetadata={sceneMetadata('spec')} />
      <Composition id="Sandbox" component={Sandbox} width={1920} height={1080} fps={30} durationInFrames={300}
        defaultProps={{ title: 'One sandbox per task', subtitle: 'isolated containers, one branch each', voiceover: null, showCaptions: true, withBackground: true }}
        calculateMetadata={sceneMetadata('sandbox')} />
      <Composition id="Harness" component={Harness} width={1920} height={1080} fps={30} durationInFrames={520}
        defaultProps={{ title: 'Bring the agent you prefer', subtitle: 'one harness per project, the same skills', voiceover: null, showCaptions: true, withBackground: true }}
        calculateMetadata={sceneMetadata('harness')} />
      <Composition id="Ask" component={Ask} width={1920} height={1080} fps={30} durationInFrames={380}
        defaultProps={{ title: "Ask, don't guess", subtitle: 'exit code 42 pauses the task for the analyst', voiceover: null, showCaptions: true, withBackground: true }}
        calculateMetadata={sceneMetadata('ask')} />
      <Composition id="Verify" component={Verify} width={1920} height={1080} fps={30} durationInFrames={290}
        defaultProps={{ title: 'Green means merge', subtitle: 'tests run in a fresh worker container', voiceover: null, showCaptions: true, withBackground: true }}
        calculateMetadata={sceneMetadata('verify')} />
      <Composition id="Deploy" component={Deploy} width={1920} height={1080} fps={30} durationInFrames={330}
        defaultProps={{ title: 'Shipped with Coolify', subtitle: 'a preview per task, production in one click', voiceover: null, showCaptions: true, withBackground: true }}
        calculateMetadata={sceneMetadata('deploy')} />
      <Composition id="Fix" component={Fix} width={1920} height={1080} fps={30} durationInFrames={210}
        defaultProps={{ title: 'Failures become tasks', subtitle: 'the build log goes straight to the agent', voiceover: null, showCaptions: true, withBackground: true }}
        calculateMetadata={sceneMetadata('fix')} />
      <Composition id="Outro" component={Outro} width={1920} height={1080} fps={30} durationInFrames={200}
        defaultProps={{ title: 'Self-hosted. Your code, your keys, your servers.', subtitle: 'github.com/ricardoborges/Painkiller', voiceover: null, showCaptions: true, withBackground: true }}
        calculateMetadata={sceneMetadata('outro')} />
    </Folder>
    <Folder name="Stills">
      <Still id="LogoLight" component={LogoLockup} width={1200} height={300} defaultProps={{ dark: false }} />
      <Still id="LogoDark" component={LogoLockup} width={1200} height={300} defaultProps={{ dark: true }} />
    </Folder>
  </>
);
