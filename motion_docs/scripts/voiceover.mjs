// Gera o voice over de cada cena com a API da ElevenLabs, com timestamps por
// palavra. Para cada cena grava public/voiceover/<id>.mp3 e <id>.json (texto,
// duração e legendas no formato Caption do @remotion/captions); as cenas usam
// as palavras para sincronizar as animações com a fala.
// Uso: node scripts/voiceover.mjs [--force]
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const env = existsSync(join(root, '.env')) ? readFileSync(join(root, '.env'), 'utf8') : '';
const apiKey = process.env.ELEVENLABS_API_KEY ?? env.match(/^ELEVENLABS_API_KEY=(.+)$/m)?.[1]?.trim();
if (!apiKey) throw new Error('ELEVENLABS_API_KEY missing (env or motion_docs/.env)');

const voiceId = process.env.ELEVENLABS_VOICE_ID ?? 'JBFqnCBsd6RMkjVDRZzb'; // George
const force = process.argv.includes('--force');
const scenes = JSON.parse(readFileSync(join(root, 'scripts/narration.json'), 'utf8'));
const outDir = join(root, 'public/voiceover');
mkdirSync(outDir, { recursive: true });

// Agrupa o alinhamento por caractere em palavras (Caption[]).
const toCaptions = ({ characters, character_start_times_seconds: starts, character_end_times_seconds: ends }) => {
  const captions = [];
  let word = null;
  characters.forEach((ch, i) => {
    if (/\s/.test(ch)) {
      if (word) captions.push(word);
      word = null;
      return;
    }
    if (!word) {
      word = {
        text: (captions.length ? ' ' : '') + ch,
        startMs: Math.round(starts[i] * 1000),
        endMs: Math.round(ends[i] * 1000),
        timestampMs: null,
        confidence: null,
      };
    } else {
      word.text += ch;
      word.endMs = Math.round(ends[i] * 1000);
    }
  });
  if (word) captions.push(word);
  return captions.map((c) => ({ ...c, timestampMs: Math.round((c.startMs + c.endMs) / 2) }));
};

for (const [i, scene] of scenes.entries()) {
  const jsonPath = join(outDir, `${scene.id}.json`);
  const cached = existsSync(jsonPath) ? JSON.parse(readFileSync(jsonPath, 'utf8')) : null;
  if (!force && cached?.text === scene.text && existsSync(join(outDir, `${scene.id}.mp3`))) {
    console.log(`cached ${scene.id}`);
    continue;
  }
  const res = await fetch(
    `https://api.elevenlabs.io/v1/text-to-speech/${voiceId}/with-timestamps?output_format=mp3_44100_128`,
    {
      method: 'POST',
      headers: { 'xi-api-key': apiKey, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: scene.text,
        model_id: 'eleven_multilingual_v2',
        // contexto vizinho deixa a entonação contínua entre as cenas
        previous_text: scenes[i - 1]?.text,
        next_text: scenes[i + 1]?.text,
        voice_settings: { stability: 0.5, similarity_boost: 0.75, style: 0.2, use_speaker_boost: true },
      }),
    },
  );
  if (!res.ok) throw new Error(`${scene.id}: ${res.status} ${await res.text()}`);
  const body = await res.json();
  writeFileSync(join(outDir, `${scene.id}.mp3`), Buffer.from(body.audio_base64, 'base64'));
  const captions = toCaptions(body.alignment);
  const durationMs = Math.max(...body.alignment.character_end_times_seconds) * 1000;
  writeFileSync(jsonPath, JSON.stringify({ id: scene.id, text: scene.text, durationMs: Math.round(durationMs), captions }, null, 1) + '\n');
  console.log(`generated ${scene.id} (${(durationMs / 1000).toFixed(1)}s, ${captions.length} words)`);
}
