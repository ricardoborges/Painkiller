import React, { useMemo } from 'react';
import { Audio } from '@remotion/media';
import { createTikTokStyleCaptions, type Caption } from '@remotion/captions';
import { AbsoluteFill, interpolate, staticFile, useCurrentFrame, useVideoConfig, type InteractivitySchema } from 'remotion';
import { C, F } from '../theme';
import { LEAD, makeCue, type SceneId, type Voiceover } from '../voiceover';
import { Background } from './kit';
import { ease } from './anim';

// Props comuns a todas as cenas. `voiceover` é preenchido pelo calculateMetadata.
export type SceneProps = {
  readonly title: string;
  readonly subtitle: string;
  readonly voiceover: Voiceover | null;
  readonly showCaptions: boolean;
  readonly withBackground: boolean;
};

export const sceneSchema = (title: string, subtitle: string) =>
  ({
    title: { type: 'string', default: title, description: 'Title' },
    subtitle: { type: 'string', default: subtitle, description: 'Subtitle' },
    showCaptions: { type: 'boolean', default: true, description: 'Show captions' },
    withBackground: { type: 'boolean', default: true, description: 'Own background' },
  }) as const satisfies InteractivitySchema;

export const useScene = (voiceover: Voiceover | null) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const cue = useMemo(() => makeCue(voiceover, fps), [voiceover, fps]);
  return { frame, fps, durationInFrames, cue };
};

// Moldura da cena: fundo (quando isolada), leve aproximação de câmera, narração e legendas.
export const Stage: React.FC<{
  id: SceneId;
  voiceover: Voiceover | null;
  showCaptions: boolean;
  withBackground: boolean;
  children: React.ReactNode;
}> = ({ id, voiceover, showCaptions, withBackground, children }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  return (
    <>
      {withBackground && <Background />}
      <AbsoluteFill
        style={{
          fontFamily: F.sans,
          scale: String(interpolate(frame, [0, durationInFrames], [1, 1.03])),
        }}
      >
        {children}
      </AbsoluteFill>
      <Audio name="Voiceover" src={staticFile(`voiceover/${id}.mp3`)} from={LEAD} premountFor={fps} />
      {showCaptions && voiceover && <Subtitles captions={voiceover.captions} />}
    </>
  );
};

// Legenda em página com a palavra falada destacada.
const Subtitles: React.FC<{ captions: Caption[] }> = ({ captions }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { pages } = useMemo(() => createTikTokStyleCaptions({ captions, combineTokensWithinMilliseconds: 1500 }), [captions]);
  const ms = ((frame - LEAD) / fps) * 1000;
  const idx = pages.findIndex((p, i) => ms >= p.startMs && ms < (pages[i + 1]?.startMs ?? p.startMs + p.durationMs + 600));
  if (idx < 0) return null;
  const page = pages[idx];
  const t = ease(frame, LEAD + Math.round((page.startMs / 1000) * fps), 6);
  return (
    <AbsoluteFill style={{ justifyContent: 'flex-end', alignItems: 'center', paddingBottom: 46, pointerEvents: 'none' }}>
      <div
        style={{
          maxWidth: 1500, padding: '14px 30px', borderRadius: 18, background: 'rgba(11, 26, 58, 0.9)',
          fontFamily: F.sans, fontWeight: 700, fontSize: 36, lineHeight: 1.3, textAlign: 'center',
          opacity: t, translate: `0 ${(1 - t) * 10}px`, boxShadow: '0 20px 40px -20px rgba(11,26,58,0.6)',
        }}
      >
        {page.tokens.map((tok, i) => {
          const active = ms >= tok.fromMs && ms < tok.toMs;
          const said = ms >= tok.fromMs;
          return (
            <span key={i} style={{ color: active ? C.sky : said ? C.white : 'rgba(255,255,255,0.5)', whiteSpace: 'pre' }}>
              {tok.text}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
