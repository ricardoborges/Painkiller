# Painkiller — explainer video

An animated explainer (~1:54, 1920×1080, 30 fps) built with [Remotion](https://remotion.dev). It has an ElevenLabs voice over, captions synced word by word, sound effects, and an ambient music bed.

## Structure

```
src/
  Root.tsx           compositions: Painkiller (full video), Scenes/* (each scene on its own), Stills/* (logos)
  Painkiller.tsx     TransitionSeries with the 11 scenes, step indicator, music, and whooshes
  voiceover.ts       loads public/voiceover/*.json, scene durations, makeCue()
  theme.ts           colors and fonts
  ui/                visual kit (kit.tsx), Stage (narration, captions, camera), StepRail, Sfx, anim
  scenes/            one file per scene, each an Interactive.withSchema(...) connected composition
scripts/
  narration.json     narration text per scene
  voiceover.mjs      ElevenLabs TTS with word-level timestamps → public/voiceover/<id>.{mp3,json}
  music.sh           synthesizes the ambient bed (public/music/pad.mp3) with ffmpeg
```

**Narration-synced animations.** Each scene calls `cue('word')` to get the frame where that word starts in the narration. Animations are timed to those cues, so if you rewrite the text and regenerate the voice over, the scenes stay in sync. Duration is not hardcoded anywhere: `calculateMetadata` reads the JSON files and sizes every scene and the full video.

## Usage

```bash
npm install
# voice over: put ELEVENLABS_API_KEY=... in motion_docs/.env (git ignores it)
npm run voiceover            # regenerates only the scenes whose text changed (--force regenerates all)
bash scripts/music.sh        # optional: resynthesizes the music bed
npm run studio               # preview; each scene also has its own composition under "Scenes"
npm run render               # out/painkiller-explainer.mp4
```

The `Painkiller` composition takes `showCaptions` and `music` props, both editable in Studio. The voice is set by `ELEVENLABS_VOICE_ID` (default: George).

The README and landing page logos come from the stills:

```bash
npx remotion still src/index.ts LogoLight ../docs/assets/painkiller-logo-light.png --image-format=png
npx remotion still src/index.ts LogoDark ../docs/assets/painkiller-logo-dark.png --image-format=png
```

Sound effects in `public/sfx/` come from remotion.media.
