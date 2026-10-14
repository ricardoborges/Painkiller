// Gera o voice over de cada cena com a API da ElevenLabs e grava as durações
// em src/durations.json, que a composição usa para dimensionar as cenas.
// Uso: node scripts/voiceover.mjs [--force]
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const env = existsSync(join(root, '.env')) ? readFileSync(join(root, '.env'), 'utf8') : '';
const apiKey = process.env.ELEVENLABS_API_KEY ?? env.match(/^ELEVENLABS_API_KEY=(.+)$/m)?.[1]?.trim();
if (!apiKey) throw new Error('ELEVENLABS_API_KEY missing (env or motion_docs/.env)');

const voiceId = process.env.ELEVENLABS_VOICE_ID ?? 'JBFqnCBsd6RMkjVDRZzb'; // George
const force = process.argv.includes('--force');
const scenes = JSON.parse(readFileSync(join(root, 'scripts/narration.json'), 'utf8'));
const durations = {};

for (const scene of scenes) {
  const out = join(root, 'public/audio', `${scene.id}.mp3`);
  if (force || !existsSync(out)) {
    const res = await fetch(
      `https://api.elevenlabs.io/v1/text-to-speech/${voiceId}?output_format=mp3_44100_128`,
      {
        method: 'POST',
        headers: { 'xi-api-key': apiKey, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: scene.text,
          model_id: 'eleven_multilingual_v2',
          voice_settings: { stability: 0.5, similarity_boost: 0.75, style: 0.15, use_speaker_boost: true },
        }),
      },
    );
    if (!res.ok) throw new Error(`${scene.id}: ${res.status} ${await res.text()}`);
    writeFileSync(out, Buffer.from(await res.arrayBuffer()));
    console.log(`generated ${scene.id}`);
  }
  const seconds = execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', out])
    .toString()
    .trim();
  durations[scene.id] = Number(seconds);
}

writeFileSync(join(root, 'src/durations.json'), JSON.stringify(durations, null, 2) + '\n');
console.log(durations);
