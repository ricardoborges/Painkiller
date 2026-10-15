import type { Caption } from '@remotion/captions';
import { staticFile } from 'remotion';
import { FPS } from './theme';

// Frames de silêncio antes da narração começar e depois dela acabar, em cada cena.
export const LEAD = 12;
export const TAIL = 18;

export type Voiceover = {
  readonly durationMs: number;
  readonly captions: Caption[];
};

export const SCENE_IDS = [
  'hook', 'intro', 'interview', 'spec', 'sandbox', 'harness', 'ask', 'verify', 'deploy', 'fix', 'outro',
] as const;
export type SceneId = (typeof SCENE_IDS)[number];

// Folga extra no fim de cenas que precisam respirar (o encerramento segura o logo).
export const EXTRA_FRAMES: Partial<Record<SceneId, number>> = { outro: 60 };

export const loadVoiceover = async (id: SceneId, signal?: AbortSignal): Promise<Voiceover> => {
  const res = await fetch(staticFile(`voiceover/${id}.json`), { signal });
  if (!res.ok) throw new Error(`voiceover/${id}.json missing; run npm run voiceover`);
  return res.json();
};

export const sceneFrames = (id: SceneId, vo: Voiceover) =>
  Math.ceil((vo.durationMs / 1000) * FPS) + LEAD + TAIL + (EXTRA_FRAMES[id] ?? 0);

// calculateMetadata das composições de cena: duração = narração + folgas.
export const sceneMetadata =
  (id: SceneId) =>
  async <P extends { voiceover: Voiceover | null }>({ props, abortSignal }: { props: P; abortSignal: AbortSignal }) => {
    const voiceover = await loadVoiceover(id, abortSignal);
    return { durationInFrames: sceneFrames(id, voiceover), props: { ...props, voiceover } };
  };

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9-]/g, '');

// Frame (local à cena) em que a n-ésima ocorrência de `word` começa a ser falada.
export const makeCue = (voiceover: Voiceover | null, fps: number) => (word: string, nth = 0) => {
  if (!voiceover) return LEAD;
  const target = norm(word);
  const hits = voiceover.captions.filter((c) => norm(c.text) === target);
  const pool = hits.length ? hits : voiceover.captions.filter((c) => norm(c.text).startsWith(target));
  const hit = pool[nth];
  if (!hit) throw new Error(`cue "${word}" (#${nth}) is not in the narration`);
  return LEAD + Math.round((hit.startMs / 1000) * fps);
};
