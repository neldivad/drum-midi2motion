// state.ts: the page's UI state in ONE object (S). Loading a clip never touches it except S.clip.
// Mirrors: localStorage holds all of it; the URL hash holds the shareable part (everything but volumes, panel sizes and list scroll).
// Every storage call is wrapped: the page works with storage blocked (private windows, previews).
// React reads S through useS() (a selector over an immutable snapshot that changes only on setS / a hash edit); the engine reads S directly.
import { useSyncExternalStore } from 'react';

const KEY = 'midi2motion.ui.v1';

export type UIState = typeof DEFAULTS_;
const DEFAULTS_ = {
  clip: '',                                                   // the preset id on stage ('' = none, or a dropped file)
  f: { kind: '', style: '', meter: '', source: '', q: '' },   // the list filters
  cam: 'perf', camPos: null as number[] | null, camTgt: null as number[] | null,                   // a named camera, or 'custom' with its position + target
  speed: 1, loop: true, orbit: false,
  ab: null as number[] | null, abA: null as number | null,                                        // the A-B loop [a, b] in seconds (inside loop-on; null = loop all) and a pending A
  zoom: 5,                                                    // the note lane's width in seconds: 5 / 2.5 / 1.25
  sort: 'worst',                                              // the list order: worst / best / worst_orn / style / bpm / name
  tview: 'cat',                                               // the tally: by category or per limb
  mf: { col: true, soft: true, good: false, frz: true, orn: true },   // mistakes filters (the review page's checkboxes)
  ov: { xray: false, flash: true, hud: true, lane: true },    // overlays (lane = the judgement's bands, boxes and marks on the note lane)
  sound: { muted: false, vol: 0.8, mode: 'hits', engine: 'samples', vm: 1, vp: 1 },   // mode: off / midi / hits (performance) / stack
  panels: { filters: true, midi: false, info: true, review: true },
  sizes: { side: 22, review: 28, stage: 55 },                 // panel sizes in % of their group (local only)
  scroll: 0,                                                  // the preset list's scroll (local only)
};

export const DEFAULTS: UIState = DEFAULTS_;
const clone = <T,>(o: T): T => JSON.parse(JSON.stringify(o));
export const S: UIState & { ov: UIState['ov'] & { perf?: boolean } } = clone(DEFAULTS);

function merge(dst: any, src: any) {
  if (!src || typeof src !== 'object') return;
  for (const k of Object.keys(dst)) {
    if (!(k in src)) continue;
    const d = dst[k], s = src[k];
    if (d && typeof d === 'object' && !Array.isArray(d)) merge(d, s);
    else if (d === null || typeof s === typeof d || (Array.isArray(s) && s.length === 3)) dst[k] = s;
  }
}

// ---- the hash: short flat keys ----
const num = (v: any, d: number) => (Number.isFinite(+v) && v !== '' ? +v : d);
const bit = (b: any) => (b ? '1' : '0');
function toHash() {
  const p = new URLSearchParams();
  if (S.clip) p.set('p', S.clip);
  for (const [k, v] of Object.entries(S.f)) if (v) p.set(k, v as string);
  p.set('cam', S.cam);
  if (S.cam === 'custom' && S.camPos && S.camTgt) p.set('cp', [...S.camPos, ...S.camTgt].map((x) => +x.toFixed(3)).join(','));
  p.set('speed', String(S.speed)); p.set('loop', bit(S.loop));
  if (S.orbit) p.set('orbit', '1');
  if (S.ab) p.set('ab', S.ab.map((x) => +x.toFixed(3)).join(','));
  if (S.abA != null) p.set('abA', String(+S.abA.toFixed(3)));
  p.set('zoom', String(S.zoom)); p.set('sort', S.sort); p.set('tv', S.tview);
  p.set('mf', bit(S.mf.col) + bit(S.mf.soft) + bit(S.mf.good) + bit(S.mf.frz) + bit(S.mf.orn));
  p.set('ov', bit(S.ov.xray) + bit(S.ov.flash) + bit(S.ov.hud) + bit(S.ov.lane));
  p.set('snd', S.sound.mode); p.set('eng', S.sound.engine);
  if (S.sound.muted) p.set('mute', '1');
  p.set('pn', bit(S.panels.filters) + bit(S.panels.midi) + bit(S.panels.info) + bit(S.panels.review));
  return p.toString();
}
function fromHash(h: string) {
  const p = new URLSearchParams(h.replace(/^#/, ''));
  if (![...p.keys()].length) return false;
  S.clip = p.get('p') || '';
  for (const k of Object.keys(S.f)) (S.f as any)[k] = p.get(k) || '';
  if (p.has('cam')) S.cam = p.get('cam')!;
  const cp = (p.get('cp') || '').split(',').map(Number);
  if (S.cam === 'custom' && cp.length === 6 && cp.every(Number.isFinite)) { S.camPos = cp.slice(0, 3); S.camTgt = cp.slice(3); }
  else if (S.cam === 'custom') S.cam = 'perf';
  S.speed = [0.25, 0.5, 1].includes(num(p.get('speed'), 1)) ? num(p.get('speed'), 1) : 1;
  if (p.has('loop')) S.loop = p.get('loop') !== '0';
  S.orbit = p.get('orbit') === '1';
  const ab = (p.get('ab') || '').split(',').map(Number); S.ab = ab.length === 2 && ab.every(Number.isFinite) && ab[1] > ab[0] ? ab : null;
  S.abA = p.has('abA') && Number.isFinite(+p.get('abA')!) ? +p.get('abA')! : null;
  if ([5, 2.5, 1.25].includes(+p.get('zoom')!)) S.zoom = +p.get('zoom')!;
  if (['worst', 'best', 'worst_orn', 'style', 'bpm', 'name'].includes(p.get('sort') || '')) S.sort = p.get('sort')!;
  if (['cat', 'limb'].includes(p.get('tv') || '')) S.tview = p.get('tv')!;
  const mf = p.get('mf'); if (mf && mf.length === 5) ['col', 'soft', 'good', 'frz', 'orn'].forEach((k, i) => { (S.mf as any)[k] = mf[i] === '1'; });
  const ov = p.get('ov'); if (ov && ov.length >= 3) { S.ov.xray = ov[0] === '1'; S.ov.flash = ov[1] === '1'; S.ov.hud = ov[2] === '1'; if (ov.length > 3) S.ov.lane = ov[3] === '1'; }
  if (['off', 'midi', 'hits', 'stack'].includes(p.get('snd') || '')) S.sound.mode = p.get('snd')!;
  if (['samples', 'synth'].includes(p.get('eng') || '')) S.sound.engine = p.get('eng')!;
  S.sound.muted = p.get('mute') === '1';
  const pn = p.get('pn'); if (pn && pn.length >= 3) { S.panels.filters = pn[0] === '1'; S.panels.midi = pn[1] === '1'; S.panels.info = pn[2] === '1'; if (pn.length > 3) S.panels.review = pn[3] === '1'; }
  return true;
}

let lastHash = '';
export function loadState() {
  try { const raw = localStorage.getItem(KEY); if (raw) merge(S, JSON.parse(raw)); } catch { /* storage blocked: defaults */ }
  try { if (fromHash(location.hash)) lastHash = location.hash.replace(/^#/, ''); } catch { /* a bad hash: ignore */ }
  snap = clone(S);
}

// ---- the React side: an immutable snapshot, replaced on every change ----
let snap: typeof S = clone(S);
const subs = new Set<() => void>();
export function notify() { snap = clone(S); for (const f of subs) f(); }
const subscribe = (f: () => void) => { subs.add(f); return () => { subs.delete(f); }; };
export function useS<T>(sel: (s: typeof S) => T): T { return useSyncExternalStore(subscribe, () => sel(snap)); }

let timer: any = 0;
export function save(now = false) {
  clearTimeout(timer);
  const run = () => {
    try { localStorage.setItem(KEY, JSON.stringify(S)); } catch { /* fine without storage */ }
    try { const h = toHash(); if (h !== lastHash) { lastHash = h; history.replaceState(null, '', '#' + h); } } catch { /* sandboxed history */ }
  };
  if (now) run(); else timer = setTimeout(run, 250);
}

// the user edited the hash by hand (or pasted a shared link into this tab)
export function onHashChange(cb: () => void) {
  window.addEventListener('hashchange', () => {
    const h = location.hash.replace(/^#/, '');
    if (h === lastHash) return;
    lastHash = h; fromHash(h); notify(); cb();
  });
}
