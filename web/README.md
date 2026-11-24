# midi2motion web page

A static page (no build step): watch solved presets, chart an uploaded MIDI and copy the local solve command, drop a `.motion.json` back to play it.

**Deploy:** Vercel project with **Root Directory = `web/`**, framework preset "Other", no build command (`vercel.json` only sets cache headers). Every path is relative, so any static server works: `python3 -m http.server -d web 8814 --bind 127.0.0.1`.

- Data: `presets/manifest.json`, `kits/index.json` + `kits/<id>/kit.json`, `assets/android_base.glb` (written by the solver side).
- Query: `?kit=<folder with kit.json>` (your own drums) · `?manifest=<url>` · `?glb=<url>`. UI state lives in the URL hash (shareable) and localStorage.
- `dev-fixtures/` (git- and vercel-ignored) points at the nelvids demo clip for local testing from a server rooted at the nelworks folder.
