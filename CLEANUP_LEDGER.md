# Cleanup ledger

| date | what | why |
|---|---|---|
| 2026-11-24 | src/midi2motion/rig/body_targets.py (trashed) | copied by mistake during vendoring; it only read the wrapped labs closure and piano charts and no packaged code path uses it |
| 2026-11-24 | web/blank_probe.html (trashed) | a one-line probe page made for a GPU frame-rate test that was dropped; never part of the page |
| 2026-11-24 | web/app.css (trashed) | the plain-HTML page's stylesheet, replaced by the Tailwind + shadcn rebuild (web/src/index.css); the old index.html was rewritten as the Vite entry and js/*.js moved (git mv) to web/src/engine/*.ts |
