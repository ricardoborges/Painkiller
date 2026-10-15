import React from 'react';
import { Audio } from '@remotion/media';
import { linearTiming, TransitionSeries } from '@remotion/transitions';
import { fade } from '@remotion/transitions/fade';
import { slide } from '@remotion/transitions/slide';
import { interpolate, staticFile, useVideoConfig, type CalculateMetadataFunction } from 'remotion';
import { Background } from './ui/kit';
import { Sfx } from './ui/Sfx';
import { StepRail } from './ui/StepRail';
import { loadVoiceover, SCENE_IDS, sceneFrames, type SceneId, type Voiceover } from './voiceover';
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

type Voiceovers = Record<SceneId, Voiceover>;

export type PainkillerProps = {
  readonly voiceovers: Voiceovers | null;
  readonly showCaptions: boolean;
  readonly music: boolean;
};

// Duração das transições entre cenas (frames); elas sobrepõem as cenas vizinhas.
const T = 15;
const transition = linearTiming({ durationInFrames: T });

// Passo do indicador do topo para cada cena (as demais não mostram o indicador).
const RAIL: Partial<Record<SceneId, number>> = { interview: 0, spec: 1, sandbox: 2, harness: 2, ask: 3, verify: 4, deploy: 5, fix: 5 };

const durations = (vo: Voiceovers | null) =>
  SCENE_IDS.map((id) => (vo ? sceneFrames(id, vo[id]) : 150));

const starts = (d: number[]) => d.map((_, i) => d.slice(0, i).reduce((acc, x) => acc + x - T, 0));

export const calculatePainkillerMetadata: CalculateMetadataFunction<PainkillerProps> = async ({ props, abortSignal }) => {
  const list = await Promise.all(SCENE_IDS.map((id) => loadVoiceover(id, abortSignal)));
  const voiceovers = Object.fromEntries(SCENE_IDS.map((id, i) => [id, list[i]])) as Voiceovers;
  const d = durations(voiceovers);
  return {
    durationInFrames: d.reduce((a, b) => a + b, 0) - T * (d.length - 1),
    props: { ...props, voiceovers },
  };
};

export const Painkiller: React.FC<PainkillerProps> = ({ voiceovers, showCaptions, music }) => {
  const { fps, durationInFrames } = useVideoConfig();
  const vo = (id: SceneId) => voiceovers?.[id] ?? null;
  const d = durations(voiceovers);
  const at = starts(d);
  const dur = (id: SceneId) => d[SCENE_IDS.indexOf(id)];
  const start = (id: SceneId) => at[SCENE_IDS.indexOf(id)];
  const marks = SCENE_IDS.filter((id) => RAIL[id] !== undefined).map((id): [number, number] => [start(id), RAIL[id] ?? 0]);

  return (
    <>
      <Background />
      <TransitionSeries name="Scenes">
        <TransitionSeries.Sequence name="Hook" durationInFrames={dur('hook')} premountFor={fps}>
          <Hook title="Describing an app is easy." subtitle="Shipping it is the hard part." voiceover={vo('hook')} showCaptions={showCaptions} withBackground={false} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={fade()} timing={transition} />
        <TransitionSeries.Sequence name="Intro" durationInFrames={dur('intro')} premountFor={fps}>
          <Intro title="Self-hosted" subtitle="Docker sandboxes" voiceover={vo('intro')} showCaptions={showCaptions} withBackground={false} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={slide({ direction: 'from-right' })} timing={transition} />
        <TransitionSeries.Sequence name="Interview" durationInFrames={dur('interview')} premountFor={fps}>
          <Interview title="An interview, not a form" subtitle="Superpowers brainstorming, one question at a time" voiceover={vo('interview')} showCaptions={showCaptions} withBackground={false} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={slide({ direction: 'from-right' })} timing={transition} />
        <TransitionSeries.Sequence name="Spec" durationInFrames={dur('spec')} premountFor={fps}>
          <Spec title="The spec drives everything" subtitle="written, versioned, then split into atomic tasks" voiceover={vo('spec')} showCaptions={showCaptions} withBackground={false} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={slide({ direction: 'from-right' })} timing={transition} />
        <TransitionSeries.Sequence name="Sandbox" durationInFrames={dur('sandbox')} premountFor={fps}>
          <Sandbox title="One sandbox per task" subtitle="isolated containers, one branch each" voiceover={vo('sandbox')} showCaptions={showCaptions} withBackground={false} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={fade()} timing={transition} />
        <TransitionSeries.Sequence name="Harness" durationInFrames={dur('harness')} premountFor={fps}>
          <Harness title="Bring the agent you prefer" subtitle="one harness per project, the same skills" voiceover={vo('harness')} showCaptions={showCaptions} withBackground={false} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={slide({ direction: 'from-right' })} timing={transition} />
        <TransitionSeries.Sequence name="Ask" durationInFrames={dur('ask')} premountFor={fps}>
          <Ask title="Ask, don't guess" subtitle="exit code 42 pauses the task for the analyst" voiceover={vo('ask')} showCaptions={showCaptions} withBackground={false} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={slide({ direction: 'from-right' })} timing={transition} />
        <TransitionSeries.Sequence name="Verify" durationInFrames={dur('verify')} premountFor={fps}>
          <Verify title="Green means merge" subtitle="tests run in a fresh worker container" voiceover={vo('verify')} showCaptions={showCaptions} withBackground={false} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={slide({ direction: 'from-right' })} timing={transition} />
        <TransitionSeries.Sequence name="Deploy" durationInFrames={dur('deploy')} premountFor={fps}>
          <Deploy title="Shipped with Coolify" subtitle="a preview per task, production in one click" voiceover={vo('deploy')} showCaptions={showCaptions} withBackground={false} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={fade()} timing={transition} />
        <TransitionSeries.Sequence name="Fix" durationInFrames={dur('fix')} premountFor={fps}>
          <Fix title="Failures become tasks" subtitle="the build log goes straight to the agent" voiceover={vo('fix')} showCaptions={showCaptions} withBackground={false} />
        </TransitionSeries.Sequence>
        <TransitionSeries.Transition presentation={fade()} timing={transition} />
        <TransitionSeries.Sequence name="Outro" durationInFrames={dur('outro')} premountFor={fps}>
          <Outro title="Self-hosted. Your code, your keys, your servers." subtitle="github.com/ricardoborges/Painkiller" voiceover={vo('outro')} showCaptions={showCaptions} withBackground={false} />
        </TransitionSeries.Sequence>
      </TransitionSeries>

      <StepRail show={[start('interview'), start('outro')]} marks={marks} />

      {/* whoosh em cada troca de cena (a apresentação já tem o seu) */}
      {at.slice(2).map((f) => <Sfx key={f} name="whoosh" at={f - Math.round(T / 2)} volume={0.18} />)}

      {music && (
        <Audio
          name="Music"
          src={staticFile('music/pad.mp3')}
          loop
          premountFor={fps}
          volume={(f) => interpolate(f, [0, fps, durationInFrames - 3 * fps, durationInFrames], [0, 0.22, 0.22, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })}
        />
      )}
    </>
  );
};
