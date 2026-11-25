// player.ts: the page's engine, driven by React but never re-rendering it per frame. One UI state object (state.ts: S) that clip
// changes never reset; a clip is {motion, judgement, meta} and loading one swaps only that.
// Query (not state): ?manifest=<url> · ?glb=<url> · ?kit=<kit folder with kit.json> · ?perf (the perf HUD).
// Time: while sound plays, the AudioContext clock is the master (picture = the time being heard); voices are queued ahead by a
// look-ahead scheduler at exact context times. Muted or silent: performance.now() is the clock. Nothing accumulates frame deltas.
// Compute: nothing plays on load or on a selection. A change draws ONE frame; the rAF loop runs only while playing (or listening, or an
// orbit the user started), never in a hidden tab. The AudioContext is created on the first play. Readouts are written through element
// refs at <= 15 Hz; React only hears about coarse changes (a clip, play/pause, a selected mistake, the tally when its counts change).
import { toast } from 'sonner';
import { S, DEFAULTS, loadState, save, notify, onHashChange } from './state';
import { createStage, CAMS, type Stage } from './stage';
import { Drums } from './audio';
import { parseSMF, analyse, type MidiInfo } from './smf';
import { Timeline, Chart, LABEL, sortRows, measure } from './lanes';
import { buildReview, filterMist, count, CumChart, Lane, series, cumAt } from './review';

const Q = new URLSearchParams(location.search);
const url = (p: string) => new URL(p, document.baseURI).href;                 // manifest paths are relative to the page
const MANIFEST = Q.get('manifest') || 'presets/manifest.json', GLB = Q.get('glb') || 'assets/android_base.glb';
export const SRC_LABEL: Record<string, string> = { groove: 'Groove MIDI', author: "The author's songs" };
export const SRC_CREDIT: Record<string, string> = { groove: 'Groove MIDI Dataset (Magenta), CC BY 4.0', author: '© the author' };
export const fmtMeter = (m: any): string => (m == null || m === '' ? '' : typeof m === 'string' ? m : Number.isInteger(m) ? `${m}/4` : Number.isInteger(m * 2) ? `${m * 2}/8` : String(m));
const meterQ = (m: any) => { if (typeof m === 'number') return m; const x = /^(\d+)\s*\/\s*(\d+)$/.exec(m || ''); return x ? (+x[1] * 4) / +x[2] : null; };
async function getJSON(u: string) { const r = await fetch(u); if (!r.ok) throw new Error(`${r.status} ${u}`); return r.json(); }
export const played = (x: any): number | null => (x == null || !Number.isFinite(+x) ? null : +x);
const setText = (el: HTMLElement | null | undefined, s: string) => { if (el && el.textContent !== s) el.textContent = s; };

export type Preset = { id: string; title?: string; kind?: string; style?: string; bpm?: number; meter?: any; bpb?: number; bars?: number[]; source?: string; credit?: string; kit?: string; midi?: string; motion: string; judgement?: string; played_pct?: number; ornament_pct?: number; notes?: string };
export function matches(p: Preset) {
  const f = S.f; if (f.kind && p.kind !== f.kind) return false; if (f.style && p.style !== f.style) return false;
  if (f.meter && fmtMeter(p.meter) !== f.meter) return false; if (f.source && p.source !== f.source) return false;
  if (f.q) { const hay = [p.title, p.style, p.kind, p.source, p.credit, p.id, SRC_LABEL[p.source || '']].join(' ').toLowerCase(); for (const w of f.q.toLowerCase().split(/\s+/).filter(Boolean)) if (!hay.includes(w)) return false; }
  return true;
}
export const SORTS: Record<string, (p: Preset) => any> = { worst: (p) => played(p.played_pct) ?? 101, best: (p) => -(played(p.played_pct) ?? -1), worst_orn: (p) => played(p.ornament_pct) ?? played(p.played_pct) ?? 101, style: (p) => `${p.style || ''} ${p.title || p.id}`, bpm: (p) => +(p.bpm || 0), name: (p) => (p.title || p.id).toLowerCase() };
export function visiblePresets(list: Preset[]) { const key = SORTS[S.sort] || SORTS.worst; return list.filter(matches).sort((a, b) => { const p = key(a), q = key(b); return p < q ? -1 : p > q ? 1 : 0; }); }

// ───────── the coarse view React renders (immutable, replaced on change) ─────────
export type Clip = any;
export type View = {
  presets: Preset[]; man: any; clip: Clip | null; clipSeq: number; playing: boolean; hl: number | null; loadingTitle: string;
  stage: { status: 'loading' | 'ready' | 'error'; progress: number }; kit: { name: string; title: string }; audio: boolean;
  tally: ReturnType<typeof count> | null; listen: boolean; midi: MidiInfo | null; midiError: string; range: [number, number];
};
let view: View = { presets: [], man: null, clip: null, clipSeq: 0, playing: false, hl: null, loadingTitle: '', stage: { status: 'loading', progress: 0 }, kit: { name: '', title: '' }, audio: false, tally: null, listen: false, midi: null, midiError: '', range: [1, 1] };
const vsubs = new Set<() => void>();
function setView(p: Partial<View>) { view = { ...view, ...p }; for (const f of vsubs) f(); }
export const viewStore = { get: () => view, subscribe: (f: () => void) => { vsubs.add(f); return () => { vsubs.delete(f); }; } };

// ───────── state ─────────
loadState();
if (Q.has('perf')) S.ov.perf = true;
let PRESETS: Preset[] = [], MAN: any = null, stage: Stage | null = null, CL: Clip | null = null, Tn = 0, playing = false, listen: any = null, HL: any = null, orbitLive = false;
export const drums = new Drums(); drums.setVolume(S.sound.vol); drums.setMuted(S.sound.muted); drums.engine = S.sound.engine; drums.vsrc = { midi: S.sound.vm, hits: S.sound.vp };

// one change to S: React hears it (notify), the engine applies it, the URL + storage follow (debounced)
export function setS(fn: () => void, { now = false, anchor = false } = {}) {
  fn(); notify(); applyEngine(); if (anchor) reanchor(); save(now); markDirty();
}
function applyEngine() {
  if (stage) stage.setXray(S.ov.xray);
  drums.engine = S.sound.engine; drums.vsrc.midi = S.sound.vm; drums.vsrc.hits = S.sound.vp; drums.setMuted(S.sound.muted);
  if (!S.ov.hud) setText(R.hud, ''), (hudKey = '');
  if (R.perf) R.perf.hidden = !S.ov.perf;
  tallyKey = '';
}

// ───────── element refs (React mounts them; the engine writes into them) ─────────
const R: { bb?: HTMLElement | null; tt?: HTMLElement | null; hud?: HTMLElement | null; perf?: HTMLElement | null; mlist?: HTMLElement | null } = {};
export function bindReadout(k: keyof typeof R, el: HTMLElement | null) { R[k] = el; if (el) { if (k === 'perf') el.hidden = !S.ov.perf; markDirty(); } if (k === 'mlist') mistPastKey = -1; }

let stageBox: HTMLElement | null = null;
// ?capture=1 (README preview only): the canvas fills the window and window.__capture.at(t) seeks and draws that frame at once, so frames can be grabbed off-line
const capBox: HTMLElement | null = Q.has('capture') ? Object.assign(document.body.appendChild(document.createElement('div')), { style: 'position:fixed;inset:0;z-index:9999;background:#101118' }) : null;
export function attachStage(el: HTMLElement | null) { if (capBox) el = capBox; stageBox = el; if (el && stage) { stage.attach(el); markDirty(); } }

// the canvases: their boxes are measured on a debounced resize (never per frame), then redrawn once
let timeline: Timeline | null = null, lane: Lane | null = null, cum: CumChart | null = null, chart: Chart | null = null, scrubWasPlaying = false;
const canvases = new Set<HTMLCanvasElement>(); let roT: any = 0;
const ro = new ResizeObserver(() => { clearTimeout(roT); roT = setTimeout(resized, 100); });
function watch(...cv: HTMLCanvasElement[]) { for (const c of cv) { canvases.add(c); measure(c); ro.observe(c); } }
function unwatch(...cv: (HTMLCanvasElement | undefined)[]) { for (const c of cv) if (c) { canvases.delete(c); ro.unobserve(c); } }
function resized() { for (const c of canvases) measure(c); timeline?.resized(); cum?.resized(); lane?.resized(); markDirty(); }
export function attachTimeline(base: HTMLCanvasElement | null, top: HTMLCanvasElement | null) {
  unwatch(timeline?.cv, timeline?.top); timeline = null; if (!base || !top) return;
  timeline = new Timeline(base, top, (t, phase) => { if (phase === 'start') { scrubWasPlaying = playing; if (playing) setPlay(false); } seek(t); if (phase === 'end' && scrubWasPlaying) setPlay(true); });
  watch(base, top); if (CL) { timeline.set(CL.tl); measure(base); measure(top); } markDirty();
}
export function attachLane(cv: HTMLCanvasElement | null) { unwatch(lane?.cv); lane = null; if (!cv) return; lane = new Lane(cv, (t) => seek(t)); watch(cv); if (CL) lane.set(CL.R, CL.G, CL.M.fps); markDirty(); }
export function attachCum(base: HTMLCanvasElement | null, top: HTMLCanvasElement | null) { unwatch(cum?.cv, cum?.top); cum = null; if (!base || !top) return; cum = new CumChart(base, top); watch(base, top); if (CL) cum.set(CL.R, CL.dur); markDirty(); }
export function attachChart(cv: HTMLCanvasElement | null) {
  chart = null; if (!cv) return; chart = new Chart(cv, (b0, b1, done) => { setRange(b0, b1); if (done) stopListen(); });
  if (A) { chart.set(A); chart.sel = view.range; chart.draw(); }
}

// ───────── clips (motion fetched only when selected; decoded once per clip) ─────────
const cache = new Map<string, any[]>(); let loadSeq = 0;
export async function loadPreset(p: Preset) {
  const seq = ++loadSeq; setS(() => { S.clip = p.id; }, { now: true });      // the hash names the clip at once (a quick reload keeps it)
  try {
    let pair = cache.get(p.id);
    if (!pair) { setView({ loadingTitle: `Loading ${p.title || p.id}…` });
      pair = await Promise.all([getJSON(url(p.motion)), p.judgement ? getJSON(url(p.judgement)).catch(() => null) : null]);
      cache.set(p.id, pair); if (cache.size > 6) cache.delete(cache.keys().next().value!); }
    if (seq !== loadSeq) return;
    showClip({ M: pair[0], J: pair[1], meta: p, kind: 'preset' });
  } catch (e: any) { if (seq === loadSeq) { setView({ loadingTitle: '' }); toast.error(`Could not load “${p.title || p.id}”: ${e.message}`); } }
}
function gridOf(M: any, J: any, meta: any) {
  if (J && J.grid && J.grid.beat_s) return { lead: J.grid.lead || 0, beat: J.grid.beat_s, bar0: J.grid.bar0 ?? 1, bpb: J.grid.bpb || 4 };
  const c = M.chart, bpb = (meta && +meta.bpb) || meterQ(meta && meta.meter) || (J && J.library && +J.library.meter) || 4;
  if (c && c.bar_s) return { lead: c.lead || 0, beat: c.bar_s / bpb, bar0: (c.bars || [1])[0], bpb };
  return null;
}
let pendingClip: any = null;
function wantRows() { return CL ? [...new Set([...CL.sMidi, ...CL.sHits].map((n: any) => n.row + '\u0000' + (n.zone || '')))].map((k) => k.split('\u0000')) : []; }
// a clip on stage: the first frame drawn once, paused at 0 (nothing autoplays)
function showClip(c: any) {
  if (!stage) { pendingClip = c; return; }
  try { stage.setClip(c.M); } catch (e: any) { toast.error('This motion file does not fit the drummer: ' + e.message); return; }
  stopListen(); if (playing) setPlay(false); HL = null;
  const M = c.M, J = c.J && Array.isArray(c.J.source) ? c.J : null, dur = Math.max(0.001, Math.min(J && J.duration ? J.duration : Infinity, (M.frames - 1) / M.fps)), G = gridOf(M, J, c.meta);
  const notes = (M.notes || []).map(([t, row, vel, zone]: any[]) => ({ t, row, vel, zone }));
  const RV = buildReview(M, J);
  const marks = J ? J.source.map((s: any) => ({ t: s.t, row: s.row, cls: !s.judged ? 'none' : s.verdict && s.verdict.cls === 'missed' ? 'missed' : s.verdict && s.verdict.cls === 'wrong' ? 'wrong' : 'hit' })) : notes.map((n: any) => ({ t: n.t, row: n.row, cls: 'hit' }));
  // the two sound sources: MIDI = the judged source notes (what should sound); hits = the measured stick contacts (what was played)
  const sMidi = (J ? J.source.filter((s: any) => s.judged).map((s: any) => ({ t: s.t, row: s.row, vel: s.vel, zone: s.zone })) : notes.slice()).sort((a: any, b: any) => a.t - b.t);
  const sHits = (J ? (J.contacts || []).filter((x: any) => x.sounding && x.role !== 'articulation' && !x.under_stick).map((x: any) => ({ t: x.t, row: x.row, vel: x.vel_est || 90, zone: x.zone, limb: x.limb })) : notes.slice()).sort((a: any, b: any) => a.t - b.t);
  const bars: any[] = [];
  if (G) for (let k = Math.floor((0 - G.lead) / G.beat) - 1; k <= Math.ceil((dur - G.lead) / G.beat) + 1; k++) { const t = G.lead + k * G.beat; if (t < 0 || t > dur) continue; const q = k / G.bpb; bars.push({ t, beat: Math.abs(q - Math.round(q)) > 1e-6, n: G.bar0 + Math.round(q) }); }
  const rows = sortRows(J && J.rows ? J.rows.map((r: any) => r.id).filter((id: string) => marks.some((m: any) => m.row === id)) : marks.map((m: any) => m.row));
  const evT = RV.ev.map((e: any) => e.t).sort((a: number, b: number) => a - b), mistT = RV.mist.map((m: any) => m.t);
  CL = { ...c, J, dur, G, marks, sMidi, sHits, rows, notes, R: RV, evT, mistT, tl: { dur, rows, marks, bars } };
  stage.setContacts(sHits.map((n: any) => n.t));
  if (timeline) { timeline.set(CL.tl); measure(timeline.cv); measure(timeline.top); }
  lane?.set(RV, G, M.fps); cum?.set(RV, dur);
  drums.preload(wantRows());
  tallyKey = ''; mistPastKey = -1; Tn = 0; reanchor();
  setView({ clip: CL, clipSeq: view.clipSeq + 1, hl: null, loadingTitle: '', playing: false });
  markDirty();
}

// ───────── the tally to the playhead (React renders it; recomputed only when its counts change, <= 15 Hz) ─────────
let tallyKey = '';
function updateTally(t: number) {
  if (!CL) return; const tt = t >= CL.dur - 1e-6 ? 1e9 : t;       // at the end, misses judged after the last frame (onset + 100 ms) count too
  const key = `${cumAt(CL.evT, tt)}|${cumAt(CL.mistT, tt)}|${view.clipSeq}`; if (key === tallyKey) return; tallyKey = key;
  setView({ tally: count(CL.R, tt) });
}
export function barbeat(t: number) { const G = CL && CL.G; if (!G) return '–'; const b = (t - G.lead) / G.beat, bar = G.bar0 + Math.floor(b / G.bpb), beat = Math.floor(((b % G.bpb) + G.bpb) % G.bpb) + 1; return `${bar}.${beat}`; }
export const mistShown = () => (CL ? filterMist(CL.R, S.mf) : []);
let mistPastKey = -1;
function markPast(t: number) {      // the mistakes list's past rows: a data attribute on the (memoised) rows, no React render
  const el = R.mlist; if (!el || !CL) return; const k = cumAt(CL.mistT, t - 0.05); if (k === mistPastKey) return; mistPastKey = k;
  for (const row of el.querySelectorAll<HTMLElement>('[data-i]')) { const m = CL.R.mist[+row.dataset.i!]; if (m) row.toggleAttribute('data-past', m.t < t - 0.05); }
}
export function remarkPast() { mistPastKey = -1; markPast(Tn); }
export function jumpTo(i: number) {
  if (!CL) return; const m = CL.R.mist[i]; if (!m) return; HL = m;
  setView({ hl: i }); S.speed = 0.25; setPlay(false); seek(m.t - 0.4); setS(() => {});
}
export const selected = () => HL;

// ───────── transport: the clock, loops, the look-ahead scheduler ─────────
const LOOKAHEAD = 0.2, TICK_MS = 25, LEAD = 0.03;      // a 25 ms timer queues the next 200 ms while playing (the frame loop tops it up too)
const clock: any = { src: 'perf', u0: 0, ac0: 0, pf0: 0, sched: 0 };       // song time u = u0 + (clock - anchor) * speed; the clip time is u wrapped into the loop
let LR: number[] | null = null, LRkey = '';
export function loopRange() { const k = CL ? `${S.loop}|${S.ab}|${CL.dur}` : ''; if (k !== LRkey) { LRkey = k; LR = null; if (CL && S.loop) { LR = [0, CL.dur]; if (S.ab) { const a = Math.max(0, Math.min(S.ab[0], CL.dur)), b = Math.min(CL.dur, S.ab[1]); if (b - a >= 0.1) LR = [a, b]; } } } return LR; }
function wrap(u: number) { const L = loopRange(); if (!L) return Math.min(u, CL.dur); const [a, b] = L; return u < b ? u : a + ((u - a) % (b - a)); }
const audioMaster = () => !!drums.ac && drums.ac.state === 'running' && !S.sound.muted && S.sound.mode !== 'off';
function heardAc() {      // the context time being heard right now (output latency taken off)
  const a = drums.ac; if (a.getOutputTimestamp) { const ts = a.getOutputTimestamp(); if (ts && ts.contextTime > 0 && ts.performanceTime > 0) return ts.contextTime + (performance.now() - ts.performanceTime) / 1000; }
  return a.currentTime - (a.outputLatency || a.baseLatency || 0);
}
function songNow() {
  if (clock.src === 'ac') return clock.u0 + Math.max(0, heardAc() - clock.ac0) * S.speed;
  return clock.u0 + (Math.max(0, performance.now() - clock.pf0) / 1000) * S.speed;
}
// a new anchor at the current picture time: seeks, speed, loop and sound changes; queued voices are dropped and re-queued
function reanchor() {
  drums.flush(); clock.u0 = Tn; clock.pf0 = performance.now(); clock.src = playing && audioMaster() ? 'ac' : 'perf';
  if (drums.ac) clock.ac0 = drums.ac.currentTime + LEAD; clock.sched = Tn; clock.start = { u0: clock.u0, ac0: clock.ac0, speed: S.speed };
  if (playing && clock.src === 'ac') schedule();
}
const acAt = (u: number) => clock.ac0 + (u - clock.u0) / S.speed;
function lowerT(a: any[], t: number) { let lo = 0, hi = a.length; while (lo < hi) { const m = (lo + hi) >> 1; if (a[m].t < t) lo = m + 1; else hi = m; } return lo; }
function lowerSnd(a: any[], t: number) { let lo = 0, hi = a.length; while (lo < hi) { const m = (lo + hi) >> 1; if (a[m].t <= t) lo = m + 1; else hi = m; } return lo; }      // first note after t
function schedule() {
  if (listen) listenTick();
  if (!playing || clock.src !== 'ac' || !CL) return;
  const uEnd = clock.u0 + Math.max(0, drums.ac.currentTime + LOOKAHEAD - clock.ac0) * S.speed; let s = clock.sched; if (uEnd <= s) return;
  const L = loopRange(), mode = S.sound.mode, stack = mode === 'stack', lists: [string, any[]][] = mode === 'midi' ? [['midi', CL.sMidi]] : mode === 'hits' ? [['hits', CL.sHits]] : mode === 'stack' ? [['midi', CL.sMidi], ['hits', CL.sHits]] : [];
  let guard = 0;
  while (s < uEnd && guard++ < 64) {
    const c = wrap(s); let rem = L ? L[1] - c : CL.dur - c; if (rem <= 1e-9) { if (!L) break; rem = L[1] - L[0]; }
    const seg = Math.min(uEnd - s, rem), c1 = c + seg;
    for (const [src, arr] of lists) for (let i = lowerT(arr, c); i < arr.length && arr[i].t < c1; i++) { const n = arr[i], u = s + (n.t - c); drums.hit(n.row, n.vel, n.zone, 0, { src, stack, at: acAt(u), t: n.t, u }); }
    s += seg; if (!L && c1 >= CL.dur) break;
  }
  clock.sched = uEnd;
}
let schedTimer: any = 0;      // runs only while something sounds: no idle timer wake-ups
function schedOn(on: boolean) { if (on && !schedTimer) schedTimer = setInterval(schedule, TICK_MS); else if (!on && schedTimer) { clearInterval(schedTimer); schedTimer = 0; } }
export function setPlay(p: boolean) {
  const was = playing; playing = !!p && !!CL;
  if (playing && !was) { const L = loopRange(); if (L && S.ab && (Tn < L[0] || Tn >= L[1])) Tn = L[0]; if (!S.loop && Tn >= CL.dur - 1e-3) Tn = 0; }
  if (playing) stopListen(); reanchor(); schedOn(playing || !!listen);
  if (was !== playing) setView({ playing });
  markDirty();
}
// the play button: the first play creates the AudioContext and waits (up to 0.5 s) for the clip's samples, so the first hits are not synth
let starting = false;
export async function togglePlay() {
  if (!CL || starting) return; if (playing) { setPlay(false); return; }
  if (!drums.ac) { starting = true; try { if (drums.unlock()) { setView({ audio: true });
    await Promise.race([Promise.all([drums.preload(wantRows()), new Promise<void>((res) => { const w = () => (drums.ac.state === 'running' ? res() : setTimeout(w, 20)); w(); })]), new Promise((r) => setTimeout(r, 500))]); } } finally { starting = false; } }
  else drums.unlock();
  setPlay(true);
}
export function seek(t: number) { if (!CL) return; Tn = Math.max(0, Math.min(CL.dur, t)); reanchor(); markDirty(); }
export function step(d: number) { if (!CL) return; setPlay(false); seek(Math.round(Tn * CL.M.fps + d) / CL.M.fps); }
export const now = () => Tn;
export function setA() { if (!CL) return; setS(() => { S.abA = +Tn.toFixed(3); }); }
export function setB() { if (!CL) return; const a = S.abA ?? 0, b = +Tn.toFixed(3); setS(() => { if (Math.abs(b - a) >= 0.1) { S.ab = [Math.min(a, b), Math.max(a, b)]; S.loop = true; } S.abA = null; }, { anchor: true }); }
export function clearAB() { setS(() => { S.ab = null; S.abA = null; }, { anchor: true }); }
export function loopMistake() { if (!HL || !CL) return; setS(() => { S.ab = [Math.max(0, +(HL.t - 1).toFixed(3)), Math.min(CL.dur, +(HL.end + 1).toFixed(3))]; S.abA = null; S.loop = true; }); seek(S.ab![0]); togglePlayOn(); }
function togglePlayOn() { if (!playing) togglePlay(); }
export function setCam(name: string) { setS(() => { S.cam = name; S.orbit = false; orbitLive = false; if (stage) stage.setCam(name); }); }
export function setOrbit(on: boolean) { orbitLive = on; setS(() => { S.orbit = on; if (!on && stage) { const c = stage.getCam(); S.cam = 'custom'; S.camPos = c.pos; S.camTgt = c.tgt; } }); }

// ───────── the frame loop: on demand only ─────────
let raf = 0, dirty = true, lastFrame = 0, lastText = 0, ticks = 0;
const PF: any = { iv: new Float32Array(240), work: new Float32Array(240), n: 0, dropped: 0, drift: 0, lastHud: 0 };
const animating = () => playing || !!listen || (S.orbit && orbitLive);
export function markDirty() { dirty = true; if (!raf && !document.hidden) raf = requestAnimationFrame(loop); }
function loop(nowMs: number) {
  raf = 0; ticks++; const iv = lastFrame ? nowMs - lastFrame : 16.7; lastFrame = nowMs;
  const w0 = performance.now();
  if (playing && CL) {
    schedule(); const u = songNow(), L = loopRange();
    PF.lastU = u; PF.lastNow = performance.now();
    if (!L && u >= CL.dur) { Tn = CL.dur; setPlay(false); } else Tn = wrap(u);
    if (clock.src === 'ac') { const d = ((clock.u0 + Math.max(0, heardAc() - clock.ac0) * S.speed - u) * 1000) / S.speed; PF.drift = d; PF.driftMax = Math.max(PF.driftMax || 0, Math.abs(d)); }
  }
  if (stage && S.orbit && orbitLive) { stage.orbit(Math.min(0.1, iv / 1000)); dirty = true; }
  if (listen) listenTick();
  if (dirty || playing) { dirty = false; frame(nowMs, iv); }
  const work = performance.now() - w0;
  if (playing || (S.orbit && orbitLive)) { const i = PF.n++ % 240; PF.iv[i] = iv; PF.work[i] = work; if (PF.n > 2 && iv > 1.6 * (PF.ivMed || 16.7)) PF.dropped++; }
  if (nowMs - PF.lastHud > 500) { PF.lastHud = nowMs; perfStats(); if (S.ov.perf) perfHud(); }
  if (animating() && !document.hidden) raf = requestAnimationFrame(loop);
  else lastFrame = 0;
}
const flash: Record<string, number> = {}, LO: any = { zoom: 5, overlays: true, loop: null, hl: null }; let hudKey = '';
function frame(nowMs: number, iv: number) {
  if (!stage) return;
  let fl: Record<string, number> | null = null;
  if (CL) {
    for (const k in flash) flash[k] = 0;
    const A = CL.sHits;
    if (S.ov.flash) for (let i = lowerSnd(A, Tn) - 1; i >= 0 && Tn - A[i].t < 0.18; i--) { const n = A[i], a = 0.5 * (1 - (Tn - n.t) / 0.18); if (a > (flash[n.row] || 0)) flash[n.row] = a; }
    if (HL) for (const r of HL.rows) flash[r] = Math.max(flash[r] || 0, 0.6);
    fl = flash;
  }
  const snap = playing ? Math.max(1 / 240, ((PF.ivMed || iv || 16.7) / 2000) * S.speed) : 0;     // half a display frame, in clip seconds
  stage.draw(Tn, fl, snap);
  const L = loopRange(), ab = L && S.ab ? L : null; timeline?.draw(Tn, ab);
  LO.zoom = S.zoom; LO.overlays = S.ov.lane; LO.loop = ab; LO.hl = HL; lane?.draw(Tn, LO);
  cum?.draw(Tn);
  if (!playing || nowMs - lastText > 66) { lastText = nowMs;      // text at <= 15 Hz while playing, and only when it changed
    if (CL) { setText(R.bb, barbeat(Tn)); setText(R.tt, `${Tn.toFixed(2)} / ${CL.dur.toFixed(2)} s`); updateTally(Tn); markPast(Tn);
      let hud = ''; if (S.ov.hud) { const A = CL.sHits; for (let i = lowerSnd(A, Tn) - 1; i >= 0 && Tn - A[i].t < 0.25; i--) { const l = LABEL[A[i].row] || A[i].row; if (!hud.includes(l)) hud = hud ? hud + '  ·  ' + l : l; } }
      if (hud !== hudKey) { hudKey = hud; setText(R.hud, hud); } } }
}
const qn = (a: number[], p: number) => a[Math.min(a.length - 1, Math.floor(p * (a.length - 1)))];
function perfStats() { const n = Math.min(PF.n, 240); if (n < 8) return; const iv = Array.from(PF.iv.subarray(0, n) as Float32Array).sort((a, b) => a - b), wk = Array.from(PF.work.subarray(0, n) as Float32Array).sort((a, b) => a - b);
  PF.ivMed = qn(iv, 0.5); PF.ivP95 = qn(iv, 0.95); PF.wkMed = qn(wk, 0.5); PF.wkP95 = qn(wk, 0.95); }
function perfHud() {
  if (!R.perf) return; if (!PF.ivMed) { setText(R.perf, 'perf: play to measure'); return; }
  const f1 = (x: number) => x.toFixed(1);
  setText(R.perf, `fps ${(1000 / PF.ivMed).toFixed(0)}  frame p50 ${f1(PF.ivMed)} p95 ${f1(PF.ivP95)} ms\nwork p50 ${f1(PF.wkMed)} p95 ${f1(PF.wkP95)} ms  render ${stage ? f1(stage.renderMs) : '-'} ms\n` +
    `dropped ${PF.dropped}  px ratio ${stage ? stage.renderer.getPixelRatio() : '-'}\nclock ${clock.src}  audio-picture drift ${clock.src === 'ac' ? f1(PF.drift) + ' ms' : 'n/a (silent clock)'}`);
}
// a hidden tab draws nothing (the sound, already queued ahead, keeps going); back in view, one frame, then the loop if playing
document.addEventListener('visibilitychange', () => { if (document.hidden) { if (raf) cancelAnimationFrame(raf); raf = 0; lastFrame = 0; } else markDirty(); });

// ───────── keys ─────────
const skipKeys = (el: any) => !!el && el.closest && !!el.closest('input, textarea, select, [contenteditable=true], [role=slider], [role=radio], [role=tab], [role=option], [role=combobox], [role=listbox], [role=dialog], [role=checkbox]');
window.addEventListener('keydown', (e) => {
  if (skipKeys(e.target) || e.ctrlKey || e.metaKey || e.altKey || document.querySelector('[role=dialog]')) return;
  if (e.code === 'Space') { e.preventDefault(); if (!e.repeat) togglePlay(); }
  else if (e.code === 'ArrowLeft') { e.preventDefault(); step(-1); }
  else if (e.code === 'ArrowRight') { e.preventDefault(); step(1); }
  else if (e.code === 'KeyL') setS(() => { S.loop = !S.loop; }, { anchor: true });
  else if (e.code === 'KeyP') setS(() => { S.ov.perf = !S.ov.perf; });
});
window.addEventListener('keyup', (e) => { if (e.code === 'Space' && !skipKeys(e.target) && !document.querySelector('[role=dialog]')) e.preventDefault(); });      // a focused button must not also click on Space

// ───────── files: MIDI uploads and dropped motion / judgement JSON ─────────
const isMotion = (o: any) => o && typeof o === 'object' && (String(o.schema || '').startsWith('verify.motion') || (o.delta && o.names && o.kit));
const isJudgement = (o: any) => o && typeof o === 'object' && (String(o.schema || '').includes('judgement') || (Array.isArray(o.source) && o.tally));
export async function handleFiles(files: File[]) {
  const mids = files.filter((f) => /\.midi?$/i.test(f.name)), jsons = files.filter((f) => /\.json$/i.test(f.name));
  if (!mids.length && !jsons.length) { if (files.length) toast('Drop a .mid file, or a .motion.json (and its .judgement.json).'); return; }
  if (mids.length) openMidi(mids[0]);
  let M: any = null, J: any = null, name = '';
  for (const f of jsons) { let o; try { o = JSON.parse(await f.text()); } catch { toast.error(`${f.name} is not valid JSON.`); continue; }
    if (isMotion(o)) { M = o; name = f.name; } else if (isJudgement(o)) J = o; else toast.error(`${f.name} is neither a motion nor a judgement file.`); }
  if (M) { setS(() => { S.clip = ''; }); showClip({ M, J, meta: { title: M.title || name.replace(/\.json$/i, ''), file: name }, kind: 'file' }); toast.success(`${name}${J ? ' and its judgement' : ''} on stage: press play.`); }
  else if (J) {
    if (CL && CL.kind === 'file' && (!J.frames || J.frames === CL.M.frames)) { showClip({ M: CL.M, J, meta: CL.meta, kind: 'file' }); toast.success('Judgement added: the lanes show hits and misses.'); }
    else toast('Drop the judgement together with its motion file.');
  }
}

// ---- the upload dialog's MIDI ----
let A: MidiInfo | null = null;
export async function openMidi(file: File) {
  setS(() => { S.panels.midi = true; });
  try { A = analyse(parseSMF(await file.arrayBuffer()), file.name); }
  catch (e: any) { A = null; setView({ midi: null, midiError: `Could not read ${file.name}: ${e.message}` }); toast.error(`Could not read ${file.name}: ${e.message}`); return; }
  stopListen(); setView({ midi: A, midiError: '' });
  if (chart) chart.set(A);
  setRange(A.firstBar, Math.min(A.nbars, A.firstBar + 3));
}
export function setRange(b0: number, b1: number) {
  if (!A) return; b0 = Math.max(1, Math.min(A.nbars, Math.round(b0) || 1)); b1 = Math.max(b0, Math.min(A.nbars, Math.round(b1) || b0));
  if (chart) { chart.sel = [b0, b1]; chart.draw(); }
  if (view.range[0] !== b0 || view.range[1] !== b1) setView({ range: [b0, b1] });
}
export function solveCommand(a: MidiInfo, [b0, b1]: number[]) {
  const q = (s: string) => (/^[\w.\-/]+$/.test(s) ? s : `'${s.replace(/'/g, "'\\''")}'`), stem = a.name.replace(/\.midi?$/i, '');
  return `midi2motion solve ${q(a.name)} --bars ${b0}-${b1}${a.meter !== 4 ? ` --meter ${a.meter}` : ''} --out ${q(stem + '.motion.json')}`;
}
export function solveEstimate(a: MidiInfo, [b0, b1]: number[]) {
  const n = b1 - b0 + 1, inR = a.notes.filter((x: any) => x.bar >= b0 && x.bar < b1 + 1).length;
  const lo = n <= 4 ? Math.max(1, Math.round(n * 0.5)) : Math.round(2 + (n - 4) * 1.75), hi = n <= 4 ? Math.ceil(n * 0.75) : Math.round(3 + (n - 4) * 6);
  return `${n} bar${n > 1 ? 's' : ''} · ${inR} notes · solves in about ${lo === hi ? lo : `${lo}–${hi}`} min${n > 8 ? ' (long: try 8 bars or fewer)' : ''}`;
}
export function closeMidi() { stopListen(); setS(() => { S.panels.midi = false; }); }
// listen to the picked bars with the kit (no motion: a check that the range is the part you want)
export function toggleListen() {
  if (listen) { stopListen(); return; } if (!A || !A.notes.length) return;
  if (!drums.unlock()) { toast.error('This browser has no WebAudio.'); return; } setView({ audio: true });
  if (S.sound.muted) setS(() => { S.sound.muted = false; });
  setPlay(false);
  const [b0, b1] = view.range, t0 = A.barStart(b0), t1 = A.barStart(b1 + 1), list = A.notes.filter((n: any) => n.bar >= b0 && n.bar < b1 + 1);
  drums.preload([...new Set(list.map((n: any) => n.row + '\u0000' + n.zone))].map((k) => k.split('\u0000')));
  listen = { c0: drums.ac.currentTime + 0.15, t0, t1, list, i: 0, b0, b1 }; schedOn(true); setView({ listen: true }); markDirty();
}
function listenTick() {
  const L = listen, t = drums.ac.currentTime - L.c0 + L.t0;
  while (L.i < L.list.length && L.list[L.i].t < t + LOOKAHEAD) { const n = L.list[L.i++]; drums.hit(n.row, n.vel, n.zone, 0, { src: 'midi', at: L.c0 + (n.t - L.t0) }); }
  if (chart) { chart.head = L.b0 + Math.max(0, Math.min(1, (t - L.t0) / (L.t1 - L.t0))) * (L.b1 - L.b0 + 1); chart.draw(); }
  if (t > L.t1 + 0.2) stopListen();
}
function stopListen() { if (!listen) return; listen = null; drums.flush(); schedOn(playing); if (chart) { chart.head = null; chart.draw(); } setView({ listen: false }); }

// ───────── boot ─────────
window.addEventListener('pagehide', () => save(true));      // a pending debounced save is not lost on a reload or close
onHashChange(() => {
  applyEngine();
  if (stage) { if (S.cam === 'custom' && S.camPos && S.camTgt) stage.setCamRaw(S.camPos, S.camTgt); else stage.setCam(S.cam); }
  const p = PRESETS.find((x) => x.id === S.clip); if (p && (!CL || CL.meta !== p)) loadPreset(p); else reanchor();
  save(true); markDirty();
});

const manifestReady = (async () => {
  try { MAN = await getJSON(url(MANIFEST)); PRESETS = (MAN.presets || []).filter((p: any) => p && p.id && p.motion); }
  catch { MAN = false; PRESETS = []; }
  setView({ presets: PRESETS, man: MAN });
})();

(async () => {      // the kit: ?kit= (a local install points at its own drums) → the first of kits/index.json → the manifest's kit → the synth
  let dir = Q.get('kit');
  if (!dir) { try { const ix = await getJSON(url('kits/index.json')); const L = Array.isArray(ix) ? ix : ix.kits || []; const k = L[0]; if (k) dir = typeof k === 'string' ? `kits/${k}/` : k.path || `kits/${k.id}/`; } catch { /* no index */ } }
  if (!dir) { await manifestReady; if (MAN && MAN.kit) dir = typeof MAN.kit === 'string' ? `kits/${MAN.kit}/` : MAN.kit.path || `kits/${MAN.kit.id}/`; }
  if (!dir) { setView({ kit: { name: 'synth', title: 'No sample kit found: a simple synth plays' } }); return; }
  try { const k = await drums.loadKit(url(dir)); setView({ kit: { name: k.name || k.id || 'kit', title: [k.name, k.license, k.credit].filter(Boolean).join(' · ') } }); if (CL) drums.preload(wantRows()); }
  catch { setView({ kit: { name: 'synth', title: `Could not load the kit at ${dir}: a simple synth plays` } }); }
})();

(async () => {
  try {
    stage = await createStage(url(GLB), (f) => setView({ stage: { status: 'loading', progress: f } }), () => markDirty());
  } catch (e: any) { setView({ stage: { status: 'error', progress: 0 } }); toast.error('The 3D model did not load: ' + e.message); return; }
  if (stageBox) stage.attach(stageBox);
  stage.setXray(S.ov.xray);
  if (S.cam === 'custom' && S.camPos && S.camTgt) stage.setCamRaw(S.camPos, S.camTgt); else stage.setCam(CAMS[S.cam] ? S.cam : 'perf');
  stage.controls.addEventListener('start', () => { if (S.orbit) { orbitLive = false; setS(() => { S.orbit = false; }); } });
  stage.controls.addEventListener('change', () => markDirty());
  stage.controls.addEventListener('end', () => { const c = stage!.getCam(); setS(() => { S.cam = 'custom'; S.camPos = c.pos; S.camTgt = c.tgt; }); });
  setView({ stage: { status: 'ready', progress: 1 } });
  await manifestReady;
  if (pendingClip) { showClip(pendingClip); pendingClip = null; }
  else { const p = PRESETS.find((x) => x.id === S.clip) || visiblePresets(PRESETS)[0] || PRESETS[0]; if (p) await loadPreset(p); }
  app.ready = true; markDirty();
})();

// the test / debug handle
const app: any = { ready: false, S, get clip() { return CL; }, get t() { return Tn; }, get playing() { return playing; }, get ticks() { return ticks; }, get raf() { return raf; }, seek, setPlay, togglePlay, jumpTo,
  get presets() { return PRESETS; }, get midi() { return A; }, cmd: () => (A ? solveCommand(A, view.range) : ''), cam: () => stage && stage.getCam(), drums,
  clock: () => ({ ...clock, start: clock.start }), tip: () => (stage ? Array.from(stage.tip) : null), perf: () => ({ ...PF, iv: Array.from(PF.iv.subarray(0, Math.min(PF.n, 240))), work: Array.from(PF.work.subarray(0, Math.min(PF.n, 240))) }),
  tally: (t: number) => (CL ? count(CL.R, t) : null), series: () => (CL ? series(CL.R) : null), mistShown: () => mistShown().map((m: any) => ({ i: m.i, t: m.t, cat: m.cat })), loopRange: () => (CL ? loopRange() : null), HL: () => HL && HL.i };
(window as any).__app = app;
if (capBox) (window as any).__capture = { at: (t: number) => { if (!stage || !CL) return false; seek(t); frame(performance.now(), 16.7); return true; }, cam: (n: string) => { setCam(n); frame(performance.now(), 16.7); }, raw: (pos: number[], tgt: number[]) => { if (stage) { stage.setCamRaw(pos, tgt); frame(performance.now(), 16.7); } } };
export { S, DEFAULTS };
