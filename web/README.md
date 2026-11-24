# midi2motion web page

A React + TypeScript + Vite + Tailwind + shadcn/ui (Radix) page: watch solved presets, chart an uploaded MIDI and copy the local solve command, drop a `.motion.json` back to play it. Nothing plays on load; the 3D stage draws one frame and then only while you play or move the view.

- `src/engine/`: plain TS modules React drives (stage = three.js, audio = WebAudio, lanes + review = the canvases and the check data, smf = the MIDI reader, state = the one UI state object `S`, player = the clock, scheduler and the on-demand frame loop). Playback time never enters React state; readouts are written through refs at <= 15 Hz.
- `src/components/`: the page (`ui/` holds the shadcn components).
- `public/`: the static data, served as is: `presets/manifest.json` + one folder per preset, `kits/index.json` + `kits/<id>/kit.json`, `assets/android_base.glb` (written by the solver side). Vite copies it into a build.
- `dist/`: the built page, **checked in** so `midi2motion serve` works on a fresh clone without Node. Its copies of `public/` are git-ignored: the server maps `/presets/`, `/kits/` and `/assets/` to `public/`.

**Develop:** `npm ci`, then `npm run dev` (127.0.0.1:8814). **Build:** `npm run build` (type-check + `dist/`); commit `dist/` with the source. `npm run preview` serves the build on 127.0.0.1:8814. Every package is pinned to an exact version; every path is relative (`base: './'`), so the page runs under any sub-path.

**Deploy:** Vercel project with **Root Directory = `web/`**; `vercel.json` sets framework Vite, build `npm run build`, output `dist`, and the cache headers.

- Query: `?kit=<folder with kit.json>` (your own drums) · `?manifest=<url>` · `?glb=<url>` · `?perf` (the perf HUD; or press P). UI state lives in the URL hash (shareable) and localStorage.
- `dev-fixtures/` (git- and vercel-ignored) points at the nelvids demo clip for local testing from a server rooted at the nelworks folder.
