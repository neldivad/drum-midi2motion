// state.js: the page's UI state in ONE object (S). Loading a clip never touches it except S.clip.
// Mirrors: localStorage holds all of it; the URL hash holds the shareable part (everything but volume and list scroll).
// Every storage call is wrapped: the page works with storage blocked (private windows, previews).

const KEY = 'midi2motion.ui.v1';

export const DEFAULTS = {
  clip: '',                                                   // the preset id on stage ('' = none, or a dropped file)
  f: { kind: '', style: '', meter: '', source: '', q: '' },   // the list filters
  cam: 'perf', camPos: null, camTgt: null,                   // a named camera, or 'custom' with its position + target
  speed: 1, loop: true, orbit: false,
  ov: { xray: false, flash: true, hud: true },               // overlays
  sound: { muted: false, vol: 0.8 },
  panels: { filters: true, midi: false, info: true },
  scroll: 0,                                                  // the preset list's scroll (local only)
};

const clone = (o) => JSON.parse(JSON.stringify(o));
export const S = clone(DEFAULTS);

function merge(dst, src) {
  if (!src || typeof src !== 'object') return;
  for (const k of Object.keys(dst)) {
    if (!(k in src)) continue;
    const d = dst[k], s = src[k];
    if (d && typeof d === 'object' && !Array.isArray(d)) merge(d, s);
    else if (d === null || typeof s === typeof d || (Array.isArray(s) && s.length === 3)) dst[k] = s;
  }
}

// ---- the hash: short flat keys ----
const num = (v, d) => (Number.isFinite(+v) && v !== '' ? +v : d);
const bit = (b) => (b ? '1' : '0');
function toHash() {
  const p = new URLSearchParams();
  if (S.clip) p.set('p', S.clip);
  for (const [k, v] of Object.entries(S.f)) if (v) p.set(k, v);
  p.set('cam', S.cam);
  if (S.cam === 'custom' && S.camPos && S.camTgt) p.set('cp', [...S.camPos, ...S.camTgt].map((x) => +x.toFixed(3)).join(','));
  p.set('speed', String(S.speed)); p.set('loop', bit(S.loop));
  if (S.orbit) p.set('orbit', '1');
  p.set('ov', bit(S.ov.xray) + bit(S.ov.flash) + bit(S.ov.hud));
  if (S.sound.muted) p.set('mute', '1');
  p.set('pn', bit(S.panels.filters) + bit(S.panels.midi) + bit(S.panels.info));
  return p.toString();
}
function fromHash(h) {
  const p = new URLSearchParams(h.replace(/^#/, ''));
  if (![...p.keys()].length) return false;
  S.clip = p.get('p') || '';
  for (const k of Object.keys(S.f)) S.f[k] = p.get(k) || '';
  if (p.has('cam')) S.cam = p.get('cam');
  const cp = (p.get('cp') || '').split(',').map(Number);
  if (S.cam === 'custom' && cp.length === 6 && cp.every(Number.isFinite)) { S.camPos = cp.slice(0, 3); S.camTgt = cp.slice(3); }
  else if (S.cam === 'custom') S.cam = 'perf';
  S.speed = [0.25, 0.5, 1].includes(num(p.get('speed'), 1)) ? num(p.get('speed'), 1) : 1;
  if (p.has('loop')) S.loop = p.get('loop') !== '0';
  S.orbit = p.get('orbit') === '1';
  const ov = p.get('ov'); if (ov && ov.length === 3) { S.ov.xray = ov[0] === '1'; S.ov.flash = ov[1] === '1'; S.ov.hud = ov[2] === '1'; }
  S.sound.muted = p.get('mute') === '1';
  const pn = p.get('pn'); if (pn && pn.length === 3) { S.panels.filters = pn[0] === '1'; S.panels.midi = pn[1] === '1'; S.panels.info = pn[2] === '1'; }
  return true;
}

let lastHash = '';
export function loadState() {
  try { const raw = localStorage.getItem(KEY); if (raw) merge(S, JSON.parse(raw)); } catch { /* storage blocked: defaults */ }
  try { if (fromHash(location.hash)) lastHash = location.hash.replace(/^#/, ''); } catch { /* a bad hash: ignore */ }
}

let timer = 0;
export function save(now = false) {
  clearTimeout(timer);
  const run = () => {
    try { localStorage.setItem(KEY, JSON.stringify(S)); } catch { /* fine without storage */ }
    try { const h = toHash(); if (h !== lastHash) { lastHash = h; history.replaceState(null, '', '#' + h); } } catch { /* sandboxed history */ }
  };
  if (now) run(); else timer = setTimeout(run, 250);
}

// the user edited the hash by hand (or pasted a shared link into this tab)
export function onHashChange(cb) {
  window.addEventListener('hashchange', () => {
    const h = location.hash.replace(/^#/, '');
    if (h === lastHash) return;
    lastHash = h; fromHash(h); cb();
  });
}
