// review.js: the checking tools of the benchmark's review page (nelvids lab 2026-11-20-drum-benchmark/verify), fed only by a clip's
// judgement + motion JSON: the mistakes list, the tally to the playhead, a cumulative errors chart, and the zoomed note lane with its overlays
// (freezes, crossed hands, habit boxes, splay + zone bands, collision runs, ornament clusters when the judgement carries them).
import { LABEL, PCOL, sortRows } from './lanes.js';

export const COL = { perfect: '#78eba0', good: '#ebdc5a', early: '#ffa03c', late: '#ffa03c', wrong: '#be78ff', missed: '#ff5c5c', extra: '#ff3cc8', brush: '#ff3cc8', softer: '#ffc878', simplified: '#6ecde1',
  layer: '#5a566e', collision: '#ff2828', freeze: '#ffffff', crossed: '#ffd65a', splay: '#ff8c28', habit: '#78dcff', zone: '#c878ff' };
export const CATS = ['perfect', 'good', 'early', 'late', 'softer', 'simplified', 'wrong', 'missed', 'extra', 'brush'];
const HABIT = ['swap', 'steal', 'role flip', 'split bounce'];
// the cumulative chart's lines: an error type each (good is not an error)
export const TYPES = [['missed', 'missed', COL.missed], ['wrong', 'wrong drum', COL.wrong], ['timing', 'early / late', COL.early], ['soft', 'softer / simplified', COL.softer], ['extra', 'extra / brush', COL.extra],
  ['collision', 'collision runs', COL.collision], ['freeze', 'freezes', COL.freeze], ['crossed', 'crossed hands', COL.crossed], ['habit', 'habits', COL.habit], ['splay', 'splay runs', COL.splay], ['zone', 'zone runs', COL.zone]];
const TYPE_OF = { missed: 'missed', wrong: 'wrong', early: 'timing', late: 'timing', softer: 'soft', simplified: 'soft', extra: 'extra', brush: 'extra', collision: 'collision', freeze: 'freeze', crossed: 'crossed', splay: 'splay', zone: 'zone', swap: 'habit', steal: 'habit', 'role flip': 'habit', 'split bounce': 'habit' };
// R-575 stick zones (src/midi2motion/data/zones_v001.json): fitted on this rig's own cleanest frames, not measured on human drummers
const ZONES = { 'L snare': { lo: -64.6, hi: -48.5 }, 'R centre': { lo: 47.6, hi: 69.6 }, 'R left side': { lo: 77.7, hi: 87.4 } };
const dec16 = (s) => { const b = atob(s || ''), u = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return new Int16Array(u.buffer); };
const rgbArr = (c) => (Array.isArray(c) ? `rgb(${c[0]},${c[1]},${c[2]})` : c);
const lab = (r) => LABEL[r] || r;

// ───────── build: every mistake of a clip, with the overlay data ─────────
export function buildReview(M, J) {
  const FPS = M.fps, R = { mist: [], ev: [], src: [], contacts: [], rows: [], limbs: {}, lshort: {}, freezes: [], crossed: [], crossedIds: new Set(), habits: [], splay: [], zones: [], clusters: [], collisions: M.collisions || [], orn: null, J };
  for (const l of (J && J.limbs) || []) { R.limbs[l.id] = rgbArr(l.color); R.lshort[l.id] = l.short; }
  if (!J) { R.src = (M.notes || []).map(([t, row, vel, zone], i) => ({ id: 'n' + i, t, row, vel, zone, judged: true, verdict: { cls: 'hit', timing: 'perfect', t_hit: t }, _res: t, _col: COL.perfect })); R.rows = sortRows(R.src.map((s) => s.row)); return R; }
  const Wm = ((J.windows && J.windows.match_ms) || 100) / 1000; R.ev = J.events || []; R.contacts = J.contacts || []; R.src = J.source || [];
  for (const s of R.src) { const v = s.verdict || { cls: 'layer' };
    s._res = ['hit', 'wrong', 'in_gesture'].includes(v.cls) ? v.t_hit ?? s.t : v.cls === 'missed' ? s.t + Wm : 1e9;
    s._col = v.cls === 'wrong' ? COL.wrong : (v.cls === 'missed' || (v.cls === 'in_gesture' && v.head_missed)) ? COL.missed : v.simplified ? COL.simplified : ['hit', 'in_gesture'].includes(v.cls) ? (COL[v.timing] || COL.perfect) : COL.layer; }
  const used = new Set([...R.src.map((s) => s.row), ...R.contacts.map((c) => c.row)]);
  R.rows = (J.rows || []).map((r) => r.id).filter((id) => used.has(id)); if (!R.rows.length) R.rows = sortRows([...used]);
  const ORN = J.ornament || null; R.orn = ORN; R.clusters = (ORN && ORN.clusters) || [];      // ornament clusters (R-527): only when the judgement carries them
  const srcBy = Object.fromEntries(R.src.map((s) => [s.id, s])), M_ = R.mist;
  for (const e of R.ev) {
    const cat = e.cat; if (cat === 'perfect' && !e.softer && !e.simplified) continue;
    const s = e.src ? srcBy[e.src] : null, c = e.contact != null ? R.contacts[e.contact] : null, v = s ? s.verdict : null;
    const row = s ? s.row : c ? c.row : null; let verdict = cat === 'perfect' ? (e.simplified ? 'simplified' : 'softer') : cat, reason = '';
    if (cat === 'missed') reason = (e.limit || (v && v.limit) || '') + (v && v.plan_disagrees ? ` (the plan says ${s.plan.fate})` : '');
    else if (cat === 'wrong' && v) reason = `struck ${lab(v.row_hit)} instead` + (s.plan && s.plan.how ? ` · ${s.plan.how}` : '');
    else if ((cat === 'extra' || cat === 'brush') && c) reason = c.cause || c.kind || '';
    else if (['good', 'early', 'late'].includes(cat) && v) reason = `${v.offset_ms > 0 ? '+' : ''}${v.offset_ms} ms`;
    else if (verdict === 'softer' && v) reason = `velocity read ${v.vel_est} for ${s.vel}`;
    else if (verdict === 'simplified' && v) reason = `${v.gesture_notes} notes played as one stroke`;
    const rows = new Set([row].filter(Boolean)); if (cat === 'wrong' && v && v.row_hit) rows.add(v.row_hit);
    const on = e.src && ORN && ORN.notes ? ORN.notes[e.src] : null;
    if (on && !on.transient) reason += ` · ornament ${R.clusters[on.cluster]?.kind || ''}, k ${on.k}, costs ${on.cost}`;
    M_.push({ orn: on && !on.transient ? on.cost : null, t: e.t, end: e.t, cat: verdict, piece: row ? lab(row) : '', rows: [...rows], limbs: [e.limb].filter(Boolean), limb: e.limb || '', reason });
  }
  for (const r of R.collisions) M_.push({ t: r.f0 / FPS, end: r.f1 / FPS, cat: 'collision', piece: (r.pairs || []).join(', '), rows: [], limbs: [], limb: '', reason: `penetration up to ${r.max_mm} mm for ${r.f1 - r.f0 + 1} frames (a hard limit)` });
  const rem = J.remedy || {}; R.freezes = rem.freezes || []; R.crossed = rem.crossed || []; R.crossedIds = new Set(R.crossed.map((x) => x.id));
  for (const z of R.freezes) M_.push({ t: z.t0, end: z.t1, cat: 'freeze', piece: (z.rows || []).map(lab).join(', '), rows: z.rows || [], limbs: [z.limb], limb: z.limb, reason: `FREEZE: ${R.lshort[z.limb] || z.limb} ${(+z.span_s).toFixed(2)} s, ${z.notes} notes, mostly ${z.mostly}` });
  const lead = (M.kit && M.kit.lead_hand) || 'R', weak = lead === 'L' ? 'R' : 'L';
  for (const x of R.crossed) M_.push({ t: x.t, end: x.t, cat: 'crossed', piece: x.zone === 'bell' ? 'Ride bell' : 'Ride', rows: ['ride'], limbs: [weak], limb: weak, reason: `crossed hand: the plan gave this ride note to the weak hand (${x.fate})` });
  const H = J.habits || {};
  for (const x of H.swaps || []) { R.habits.push(x); M_.push({ t: x.t, end: x.t, cat: 'swap', piece: lab(x.piece), rows: [x.piece], limbs: [x.hand], limb: x.hand, reason: `same-piece swap: ${x.hand} plays ${x.role}'s ${x.piece} for ${x.notes} note(s) and swaps back` }); }
  for (const x of H.steals || []) { R.habits.push(x); M_.push({ t: x.t, end: x.t, cat: 'steal', piece: lab(x.piece), rows: [x.piece], limbs: [x.hand], limb: x.hand, reason: `reserved-limb steal: ${x.hand} has its own note in ${x.own_next} s; ${x.free} was free` }); }
  for (const x of H.role_flips || []) { R.habits.push(x); M_.push({ t: x.t, end: x.t, cat: 'role flip', piece: lab(x.piece), rows: [x.piece], limbs: [x.hand], limb: x.hand, reason: `role flip after a fill: ${x.piece} mostly by ${x.hand}; its role is ${x.role}` }); }
  for (const x of H.bounce_splits || []) { R.habits.push(x); M_.push({ t: x.t, end: x.t, cat: 'split bounce', piece: lab(x.piece), rows: [x.piece], limbs: [], limb: '', reason: `a bounce (${x.notes} quiet fast notes on one piece) split between ${x.hands}` }); }
  R.splay = ((J.splay && J.splay.runs) || []).map((r) => ({ f0: r.f0, f1: r.f1, kind: r.kind }));
  for (const r of R.splay) M_.push({ t: r.f0 / FPS, end: r.f1 / FPS, cat: 'splay', piece: 'Stick splay', rows: [], limbs: /L/.test(r.kind) ? ['L'] : /R/.test(r.kind) ? ['R'] : [], limb: '', reason: `stick splay: ${r.kind}, ${r.f1 - r.f0 + 1} frames` });
  R.zones = zoneRuns(M);
  for (const r of R.zones) M_.push({ t: r.f0 / FPS, end: r.f1 / FPS, cat: 'zone', piece: 'Stick zone', rows: [], limbs: [...new Set([...r.cells].map((c) => c[0]))], limb: '', reason: `stick outside its zone: ${[...r.cells].join(', ')}, ${r.f1 - r.f0 + 1} frames` });
  M_.sort((a, b) => a.t - b.t); M_.forEach((m, i) => { m.i = i; m.col = COL[m.cat] || (HABIT.includes(m.cat) ? COL.habit : COL.missed); });
  return R;
}
// R-575 zone runs from the motion's stick tracks: the stick's yaw (seen from above) outside its (hand, side) zone; cells without a zone are not judged
function zoneRuns(M) {
  const ST = dec16(M.sticks), NF = M.frames, runs = []; if (!ST.length) return runs; let cur = null;
  const sn = ((M.kit && M.kit.pieces) || []).find((p) => p.id === 'snare')?.c || [0, -0.5];
  const raw = (f, h, k) => { const o = (f * 2 + (h === 'L' ? 0 : 1)) * 6 + k * 3; return [ST[o] / 1e4, ST[o + 1] / 1e4]; };
  for (let f = 0; f < NF; f++) { const bad = [];
    for (const h of ['L', 'R']) { const b = raw(f, h, 0), t = raw(f, h, 1), dx = t[0] - b[0], dy = t[1] - b[1]; if (Math.hypot(dx, dy) < 0.04) continue; const yw = Math.atan2(dx, -dy) * 180 / Math.PI;
      let cell = t[0] > 0.25 ? 'left side' : t[0] < -0.25 ? 'right side' : 'centre'; if (h === 'L' && Math.hypot(t[0] - sn[0], t[1] - sn[1]) <= 0.15) cell = 'snare';
      const z = ZONES[`${h} ${cell}`]; if (z && (yw < z.lo || yw > z.hi)) bad.push(`${h} ${cell}`); }
    if (bad.length) { if (cur && cur.f1 === f - 1) { cur.f1 = f; bad.forEach((x) => cur.cells.add(x)); } else { cur = { f0: f, f1: f, cells: new Set(bad) }; runs.push(cur); } } }
  return runs;
}

// the mistakes the filters show (the review page's checkboxes)
export function filterMist(R, mf) {
  return R.mist.filter((m) => (mf.col || m.cat !== 'collision') && (mf.soft || !['softer', 'simplified'].includes(m.cat)) && (mf.good || m.cat !== 'good') && !(mf.orn && m.orn != null && m.orn < 0.5) &&
    (mf.frz || !['freeze', 'crossed', 'splay', 'zone', ...HABIT].includes(m.cat)));
}

// ───────── the tally to the playhead ─────────
export function count(R, t) {
  const c = Object.fromEntries(CATS.map((k) => [k, 0])), by = {}, lb = {}, ext = { collision: 0, freeze: 0, crossed: 0, habit: 0, splay: 0, zone: 0 };
  for (const e of R.ev) { if (e.t > t + 1e-9) continue; if (c[e.cat] != null) c[e.cat]++; if (e.softer) c.softer++; if (e.simplified) c.simplified++; if (e.cat === 'missed') by[e.limit || '?'] = (by[e.limit || '?'] || 0) + 1;
    const L = (lb[e.limb ?? '—'] ||= [0, 0, 0, 0]); L[['perfect', 'good', 'early', 'late'].includes(e.cat) ? 0 : ['extra', 'brush'].includes(e.cat) ? 2 : e.cat === 'wrong' ? 3 : 1]++; }
  for (const m of R.mist) { if (m.t > t + 1e-9) continue; const ty = TYPE_OF[m.cat]; if (ty in ext) ext[ty]++; }
  const hits = c.perfect + c.good + c.early + c.late, notes = hits + c.wrong + c.missed;
  let orn = null; if (R.orn && R.orn.units) { const ou = R.orn.units.filter((u) => u.t <= t + 1e-9), w = ou.reduce((a, u) => a + u.w, 0), a = ou.reduce((s, u) => s + u.a, 0); orn = w ? (100 * a) / w : 0; }
  return { c, by, lb, ext, hits, notes, acc: notes ? (100 * hits) / notes : 0, orn };
}

// ───────── the cumulative errors chart: one line per error type, the playhead on it ─────────
export function series(R) { const s = {}; for (const m of R.mist) { const ty = TYPE_OF[m.cat]; if (!ty) continue; (s[ty] ||= []).push(m.t); } for (const k in s) s[k].sort((a, b) => a - b); return s; }
export function cumAt(times, t) { let lo = 0, hi = times.length; while (lo < hi) { const m = (lo + hi) >> 1; if (times[m] <= t) lo = m + 1; else hi = m; } return lo; }
export class CumChart {      // a base canvas (axes + the full lines, dim) and a top canvas (the lines up to the playhead, bright, + the playhead)
  constructor(base, top) { this.cv = base; this.top = top; this.R = null; this.dur = 1; this.s = {}; this.dirty = true; this.lastX = -1; this.bright = document.createElement('canvas'); }
  set(R, dur) { this.R = R; this.dur = dur; this.s = series(R); this.dirty = true; }
  resized() { this.dirty = true; }
  geom() { const w = this.cv.clientWidth, h = this.cv.clientHeight, L = 26, B = h - 14, T = 6; const keys = TYPES.filter(([k]) => this.s[k] && this.s[k].length), max = Math.max(1, ...keys.map(([k]) => this.s[k].length));
    return { w, h, L, B, T, keys, max, X: (tt) => L + (tt / this.dur) * (w - L - 6), Y: (n) => B - (n / max) * (B - T) }; }
  lines(g, G, alpha, width) { for (const [k, , col] of G.keys) { const ts = this.s[k]; g.beginPath(); let n = 0; g.moveTo(G.X(0), G.Y(0)); for (const tt of ts) { const x = G.X(tt); g.lineTo(x, G.Y(n)); n++; g.lineTo(x, G.Y(n)); } g.lineTo(G.X(this.dur), G.Y(n)); g.strokeStyle = col; g.globalAlpha = alpha; g.lineWidth = width; g.stroke(); } g.globalAlpha = 1; }
  paintBase() {
    const dpr = Math.min(2, devicePixelRatio || 1), G = this.geom(); this.dirty = false; this.lastX = -1; if (!G.w || !G.h) return;
    for (const c of [this.cv, this.bright]) { c.width = Math.round(G.w * dpr); c.height = Math.round(G.h * dpr); }
    const g = this.cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.fillStyle = '#14151d'; g.fillRect(0, 0, G.w, G.h);
    g.font = '10px system-ui, sans-serif'; g.fillStyle = '#8b8ea6'; g.textBaseline = 'middle'; g.fillText(String(G.max), 4, G.T + 2); g.fillText('0', 4, G.B); g.fillStyle = '#2c2e3d'; g.fillRect(G.L, G.B, G.w - G.L - 6, 1); g.fillRect(G.L, G.T, 1, G.B - G.T);
    if (!G.keys.length) { g.fillStyle = '#8b8ea6'; g.fillText(this.R && this.R.J ? 'no errors in this clip' : 'no judgement file', G.L + 8, (G.T + G.B) / 2); }
    g.textAlign = 'right'; g.fillStyle = '#8b8ea6'; g.fillText(`${this.dur.toFixed(1)} s`, G.w - 6, G.h - 6); g.textAlign = 'left';
    this.lines(g, G, 0.25, 1);
    const b = this.bright.getContext('2d'); b.setTransform(dpr, 0, 0, dpr, 0, 0); b.clearRect(0, 0, G.w, G.h); this.lines(b, G, 1, 1.6); this.G = G;
  }
  draw(t) {
    if (this.dirty || this.cv.width !== Math.round(this.cv.clientWidth * Math.min(2, devicePixelRatio || 1))) this.paintBase();
    const G = this.G; if (!G || !G.w) return; const xp = Math.round(G.X(Math.min(Math.max(0, t), this.dur)) * 2) / 2; if (xp === this.lastX) return; this.lastX = xp;
    const dpr = Math.min(2, devicePixelRatio || 1), top = this.top; if (top.width !== this.cv.width || top.height !== this.cv.height) { top.width = this.cv.width; top.height = this.cv.height; }
    const g = top.getContext('2d'); g.setTransform(1, 0, 0, 1, 0, 0); g.clearRect(0, 0, top.width, top.height);
    const sw = Math.max(1, Math.round(xp * dpr)); g.drawImage(this.bright, 0, 0, sw, top.height, 0, 0, sw, top.height);
    g.setTransform(dpr, 0, 0, dpr, 0, 0); g.fillStyle = '#fff'; g.fillRect(xp - 0.5, G.T - 2, 1.5, G.B - G.T + 4);
  }
}

// ───────── the zoomed note lane (the review page's highway): rows = pieces, time runs right to left under NOW ─────────
const BG = '#101118', LANE = '#181922', LANE2 = '#14151d', GRID = '#2a2c3a', BARL = '#4a4d64', DIM = '#8b8ea6', GHOST = '#9690ba';
export class Lane {      // the clip is painted once into tiles (a 'past' look: verdict colours and contacts; a 'future' look: grey ghosts), then each frame blits them
  constructor(cv, onSeek) {
    this.cv = cv; this.R = null; this.G = null; this.onSeek = onSeek; this.XL = 70; this.TW = 512; this.tiles = new Map(); this.key = '';
    cv.addEventListener('pointerdown', (e) => { if (!this.R) return; const r = cv.getBoundingClientRect(); this.onSeek(this.t + ((e.clientX - r.left) - this.XN()) / this.PPS()); });
  }
  set(R, G, FPS) { this.R = R; this.G = G; this.FPS = FPS; this.tiles.clear(); this.key = ''; }
  resized() { this.key = ''; }
  XN() { return this.XL + (this.w - this.XL) * 0.32; }
  PPS() { return (this.w - this.XL) / this.zoom; }
  // one tile of the strip: strip x = (t + zoom) * pps
  tile(kind, i) {
    const k = kind + i; let c = this.tiles.get(k); if (c) return c;
    if (this.tiles.size > 80) this.tiles.clear();
    const R = this.R, dpr = this.dpr, TW = this.TW, h = this.h, pps = this.pps, PAD = this.zoom, TOP = 22, BOT = 4, past = kind === 'p';
    c = document.createElement('canvas'); c.width = Math.ceil(TW * dpr); c.height = Math.ceil(h * dpr); const g = c.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const x0 = i * TW, X = (tt) => (tt + PAD) * pps - x0, ta = x0 / pps - PAD - 0.3, tb = (x0 + TW) / pps - PAD + 0.3;
    const rowh = (h - TOP - BOT) / Math.max(1, R.rows.length), RI = this.RI, RY = (id) => TOP + RI[id] * rowh;
    g.font = '11px system-ui, sans-serif'; g.textBaseline = 'middle';
    R.rows.forEach((r, j) => { g.fillStyle = j % 2 ? LANE2 : LANE; g.fillRect(0, TOP + j * rowh, TW, rowh); });
    const G = this.G; if (G) { for (let b = Math.floor((ta - G.lead) / G.beat); b <= Math.ceil((tb - G.lead) / G.beat); b++) { const x = X(G.lead + b * G.beat), q = b / G.bpb, bar = Math.abs(q - Math.round(q)) < 1e-6; g.fillStyle = bar ? BARL : GRID; g.fillRect(x, TOP, 1, h - TOP - BOT); if (bar) { g.fillStyle = DIM; g.fillText(String(G.bar0 + Math.round(q)), x + 3, 8); } } }
    for (const s of R.src) { if (s.t < ta || s.t > tb || RI[s.row] == null) continue; const x = X(s.t), y = RY(s.row) + 2, hh = Math.max(2, rowh - 4), ww = Math.max(6, 0.035 * pps);
      const col = !s.judged ? COL.layer : past ? s._col : GHOST; g.strokeStyle = col; g.lineWidth = past ? 2 : 1.2; g.strokeRect(x - ww / 2, y, ww, hh);
      if (past && s.verdict && s.verdict.cls === 'missed') { g.beginPath(); g.moveTo(x - ww / 2, y); g.lineTo(x + ww / 2, y + hh); g.moveTo(x + ww / 2, y); g.lineTo(x - ww / 2, y + hh); g.stroke(); if (rowh > 13) { g.fillStyle = COL.missed; g.fillText((s.verdict.limit || '').slice(0, 22), x + ww / 2 + 3, y + hh / 2); } }
      if (past && s.verdict && s.verdict.cls === 'wrong' && RI[s.verdict.row_hit] != null) { g.strokeStyle = COL.wrong; g.beginPath(); g.moveTo(x, y + hh / 2); g.lineTo(X(s.verdict.t_hit), RY(s.verdict.row_hit) + rowh / 2); g.stroke(); } }
    if (past) for (const ct of R.contacts) { if (ct.t < ta || ct.t > tb || ct.role === 'articulation' || RI[ct.row] == null) continue; const x = X(ct.t), y = RY(ct.row) + 4, hh = Math.max(2, rowh - 8), x2 = ct.kind === 'drag' ? X(ct.t_off) : x + Math.max(4, 0.025 * pps);
      if (ct.role === 'extra' || ct.role === 'brush') { g.fillStyle = g.strokeStyle = COL.extra; if (ct.role === 'extra') g.fillRect(x, y, Math.max(5, x2 - x), hh); else { g.beginPath(); g.moveTo(x, y + hh / 2); g.lineTo(x + 5, y); g.lineTo(x + 10, y + hh / 2); g.lineTo(x + 5, y + hh); g.closePath(); g.stroke(); } continue; }
      g.globalAlpha = ct.sounding ? 0.9 : 0.35; g.fillStyle = R.limbs[ct.limb] || COL.extra; g.fillRect(x, y, Math.max(3, x2 - x), hh); g.globalAlpha = 1; }
    if (this.overlays) {
      for (const z of R.freezes) { if (z.t1 < ta || z.t0 > tb) continue; const xa = X(z.t0) - 6, xb = X(z.t1) + 6, col = R.limbs[z.limb] || '#fff';
        for (const r of z.rows || []) { if (RI[r] == null) continue; const y = RY(r); g.save(); g.beginPath(); g.rect(xa, y + 1, xb - xa, rowh - 2); g.clip(); g.strokeStyle = col; g.globalAlpha = 0.55; g.lineWidth = 1.5; for (let q = xa - rowh; q < xb + rowh; q += 7) { g.beginPath(); g.moveTo(q, y + rowh); g.lineTo(q + rowh, y); g.stroke(); } g.restore(); }
        g.fillStyle = col; g.font = 'bold 10px system-ui, sans-serif'; g.fillText(`FREEZE ${R.lshort[z.limb] || z.limb} ${(+z.span_s).toFixed(2)} s`, xa + 2, TOP - 4); g.font = '11px system-ui, sans-serif'; }
      const band = (runs, y, col) => { for (const r of runs) { const xa = X(r.f0 / this.FPS), xb = X((r.f1 + 1) / this.FPS); if (xb > 0 && xa < TW) { g.fillStyle = col; g.fillRect(xa, y, xb - xa, 3); } } };
      band(R.zones, TOP - 12, COL.zone); band(R.splay, TOP - 8, COL.splay);
      for (const x of R.habits) { if (x.t < ta || x.t > tb || RI[x.piece] == null) continue; const X0 = X(x.t); g.strokeStyle = COL.habit; g.lineWidth = 2; g.strokeRect(X0 - 6, RY(x.piece) + 2, 12, rowh - 4); g.lineWidth = 1; }
      for (const s of R.src) { if (!R.crossedIds.has(s.id) || s.t < ta || s.t > tb || RI[s.row] == null) continue; const x = X(s.t), y = RY(s.row); g.fillStyle = COL.crossed; g.beginPath(); g.moveTo(x - 5, y + 1); g.lineTo(x + 5, y + 1); g.lineTo(x, y + 7); g.closePath(); g.fill(); }
      for (const cl of R.clusters) { if (cl.span[1] < ta || cl.span[0] > tb) continue; const xa = X(cl.span[0]) - 4, xb = X(cl.span[1]) + 4, rs = (cl.rows || []).map((r) => RI[r]).filter((x) => x != null); if (!rs.length) continue;
        const y = TOP + Math.min(...rs) * rowh + 1, y2 = TOP + (Math.max(...rs) + 1) * rowh - 1; g.strokeStyle = 'rgba(233,228,247,0.55)'; g.beginPath(); g.moveTo(xa, y + 5); g.lineTo(xa, y); g.lineTo(xb, y); g.lineTo(xb, y + 5); g.moveTo(xa, y2 - 5); g.lineTo(xa, y2); g.lineTo(xb, y2); g.lineTo(xb, y2 - 5); g.stroke();
        g.fillStyle = 'rgba(233,228,247,0.85)'; g.font = '10px system-ui, sans-serif'; g.fillText(cl.kind, xa + 2, y - 5); g.font = '11px system-ui, sans-serif'; }
      for (const r of R.collisions) { const xa = X(r.f0 / this.FPS), xb = X((r.f1 + 1) / this.FPS); if (xb < 0 || xa > TW) continue; g.fillStyle = COL.collision; g.fillRect(xa, TOP - 4, Math.max(2, xb - xa), 3); }
    }
    this.tiles.set(k, c); return c;
  }
  blit(g, kind, sa, sb, xn, sNow) {
    for (let i = Math.floor(sa / this.TW); i * this.TW < sb; i++) { const a = Math.max(sa, i * this.TW), b = Math.min(sb, (i + 1) * this.TW); if (b <= a) continue;
      g.drawImage(this.tile(kind, i), (a - i * this.TW) * this.dpr, 0, (b - a) * this.dpr, this.h * this.dpr, xn + (a - sNow), 0, b - a, this.h); }
  }
  draw(t, o) {      // o = {zoom, overlays, loop: [a,b] | null, hl: mistake | null}
    const cv = this.cv, dpr = Math.min(2, devicePixelRatio || 1), w = cv.clientWidth, h = cv.clientHeight; if (!w || !h) return;
    const key = `${w}x${h}@${dpr}|${o.zoom}|${o.overlays}`;
    if (key !== this.key) { this.key = key; this.tiles.clear(); cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); this.w = w; this.h = h; this.dpr = dpr; this.zoom = o.zoom; this.overlays = o.overlays; this.pps = (w - this.XL) / o.zoom; this.labels = null; this.drawn = null;
      if (this.R) this.RI = Object.fromEntries(this.R.rows.map((r, i) => [r, i])); }
    if (this.drawn && t === this.lt && o.loop === this.ll && o.hl === this.lh) return; this.drawn = true; this.lt = t; this.ll = o.loop; this.lh = o.hl;
    this.t = t; const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.fillStyle = BG; g.fillRect(0, 0, w, h); const R = this.R; if (!R) return;
    const TOP = 22, BOT = 4, XL = this.XL, xn = this.XN(), pps = this.pps, sNow = (t + this.zoom) * pps, X = (tt) => xn + (tt - t) * pps;
    this.blit(g, 'p', Math.max(0, sNow - (xn - XL)), sNow, xn, sNow); this.blit(g, 'f', sNow, sNow + (w - xn), xn, sNow);
    if (!this.labels) { const L = (this.labels = document.createElement('canvas')); L.width = Math.ceil(XL * dpr); L.height = Math.ceil(h * dpr); const lg = L.getContext('2d'); lg.setTransform(dpr, 0, 0, dpr, 0, 0); lg.fillStyle = BG; lg.fillRect(0, 0, XL, h); lg.font = '11px system-ui, sans-serif'; lg.textBaseline = 'middle';
      const rowh = (h - TOP - BOT) / Math.max(1, R.rows.length); R.rows.forEach((r, i) => { lg.fillStyle = PCOL[r] || DIM; lg.fillRect(XL - 4, TOP + i * rowh + 1, 2, rowh - 2); lg.fillStyle = DIM; if (rowh >= 9) lg.fillText(lab(r).slice(0, 10), 6, TOP + i * rowh + rowh / 2); }); }
    g.drawImage(this.labels, 0, 0, this.labels.width, this.labels.height, 0, 0, XL, h);
    if (o.loop) { const xa = Math.max(XL, X(o.loop[0])), xb = Math.min(w, X(o.loop[1])); if (xb > xa) { g.fillStyle = 'rgba(110,205,225,0.08)'; g.fillRect(xa, TOP, xb - xa, h - TOP - BOT); g.fillStyle = '#6ecde1'; g.fillRect(xa, TOP - 2, xb - xa, 2); } }
    if (o.hl) { const xa = X(o.hl.t), xb = X(o.hl.end); g.strokeStyle = '#fff'; g.setLineDash([3, 3]); g.strokeRect(Math.max(XL, xa - 8), TOP, Math.max(16, xb - xa + 16), h - TOP - BOT); g.setLineDash([]); }
    g.fillStyle = '#fff'; g.fillRect(xn, TOP - 4, 2, h - TOP);
  }
}
