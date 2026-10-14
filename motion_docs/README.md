# Painkiller — explainer video

An animated explainer (~2 min, 1920×1080, 30 fps) built with [Remotion](https://remotion.dev), plus a voice over from ElevenLabs.

## Scenes

| # | Scene | What it shows |
|---|-------|---------------|
| 1 | `intro` | The logo and agents in containers |
| 2 | `goal` | Idea → Spec → Tasks → Code → Production, with the analyst in control |
| 3 | `interview` | Initial analysis: the Superpowers `brainstorming` skill with clickable choices |
| 4 | `spec` | Spec-driven: a versioned spec split into atomic tasks with dependencies |
| 5 | `harness` | One sandbox per task on `feature/*`, the harnesses (agy, dsh, Maki, Unreal), and the Superpowers skills |
| 6 | `ask` | Clean interruption: `painkiller ask` → exit 42 → the analyst answers → the agent resumes |
| 7 | `tests` | Tests in a fresh worker, merge, live activity, and token budget |
| 8 | `deploy` | Gitea → Coolify → preview and production, plus "Fix with the agent" |
| 9 | `outro` | Conversation → Spec → Production |

## Usage

```bash
npm install
# voice over: put ELEVENLABS_API_KEY=... in motion_docs/.env (git ignores it)
npm run voiceover            # generates public/audio/*.mp3 and src/durations.json (--force regenerates them)
npm run studio               # live preview
npm run render               # out/painkiller-explainer.mp4
```

The narration text is in `scripts/narration.json`. Each scene runs as long as its audio, so to change a scene's text, edit the JSON and run `npm run voiceover -- --force`. Within a scene, animations are timed in seconds (the `s(...)` calls in `src/scenes/*`) to match the narration. The voice is set by `ELEVENLABS_VOICE_ID` (default: George).

The repo README logo (`docs/assets/painkiller-logo-{light,dark}.png`) comes from the `LogoLight`/`LogoDark` compositions:

```bash
npx remotion still src/index.ts LogoLight ../docs/assets/painkiller-logo-light.png --image-format=png
npx remotion still src/index.ts LogoDark ../docs/assets/painkiller-logo-dark.png --image-format=png
```
