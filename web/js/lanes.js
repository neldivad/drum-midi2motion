// lanes.js: piece colours and the two note canvases: the transport's timeline (bar ticks + one lane per piece, hit/miss
// from the judgement, a scrubbable playhead) and the upload's note chart (bars of the whole MIDI, a bar-range selection).

export const ORDER = ['crash', 'crash2', 'china', 'splash', 'ride', 'hat', 'tom1', 'tom2', 'tom3', 'floor', 'floor2', 'snare', 'kick', 'kick2', 'hatped'];
export const LABEL = { crash: 'Crash', crash2: 'Crash 2', china: 'China', splash: 'Splash', ride: 'Ride', hat: 'Hi-hat', tom1: 'Tom 1', tom2: 'Tom 2', tom3: 'Tom 3', floor: 'Floor tom', floor2: 'Floor 2', snare: 'Snare', kick: 'Kick', kick2: 'Kick 2', hatped: 'Hat pedal' };
export const SHORT = { crash: 'CR', crash2: 'C2', china: 'CH', splash: 'SP', ride: 'RD', hat: 'HH', tom1: 'T1', tom2: 'T2', tom3: 'T3', floor: 'FT', floor2: 'F2', snare: 'SN', kick: 'K', kick2: 'K2', hatped: 'PD' };
export const PCOL = { crash: '#f2c94c', crash2: '#e0b13d', china: '#d9963a', splash: '#f5dd7a', ride: '#f29a4a', hat: '#6fdc9c', tom1: '#6aa8ff', tom2: '#8f8cf5', tom3: '#a98bf0', floor: '#c77ee6', floor2: '#b56fd8', snare: '#eef0f6', kick: '#ff8fb1', kick2: '#f07aa0', hatped: '#58b98a' };
export const VCOL = { missed: '#ff4f4f', wrong: '#c08bff', none: '#5d5f72' };
const BG = '#14151d', ROWA = '#191a24', ROWB = '#16171f', TICK = '#2c2e3d', BAR = '#4a4d64', DIM = '#8b8ea6';

export const sortRows = (ids) => [...new Set(ids)].sort((a, b) => (ORDER.indexOf(a) + 1 || 99) - (ORDER.indexOf(b) + 1 || 99));

function fit(cv) { const dpr = Math.min(2, devicePixelRatio || 1), w = cv.clientWidth, h = cv.clientHeight; if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); } const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); return { g, w, h }; }

// ---- the transport timeline ----
export class Timeline {
  constructor(cv, onSeek) {
    this.cv = cv; this.clip = null; this.base = null; this.onSeek = onSeek; this.LX = 26;
    let drag = false;
    const at = (e) => { const r = cv.getBoundingClientRect(), x = e.clientX - r.left; return this.clip ? Math.max(0, Math.min(1, (x - this.LX) / (r.width - this.LX - 4))) * this.clip.dur : 0; };
    cv.addEventListener('pointerdown', (e) => { if (!this.clip) return; drag = true; cv.setPointerCapture(e.pointerId); this.onSeek(at(e), 'start'); });
    cv.addEventListener('pointermove', (e) => { if (drag) this.onSeek(at(e), 'move'); });
    const up = (e) => { if (!drag) return; drag = false; this.onSeek(at(e), 'end'); }; cv.addEventListener('pointerup', up); cv.addEventListener('pointercancel', up);
  }
  // clip: {dur, rows: [ids], marks: [{t,row,cls}], bars: [{t, n}]}
  set(clip) { this.clip = clip; this.base = null; this.cv.style.height = clip ? `${18 + Math.max(3, clip.rows.length) * 6 + 4}px` : '22px'; }
  X(t) { return this.LX + (t / this.clip.dur) * (this.w - this.LX - 4); }
  paintBase() {
    const { g, w, h } = fit(this.cv); this.w = w; this.h = h; g.fillStyle = BG; g.fillRect(0, 0, w, h); const c = this.clip; if (!c) return;
    const top = 16, rh = (h - top - 3) / Math.max(1, c.rows.length);
    c.rows.forEach((id, i) => { g.fillStyle = i % 2 ? ROWB : ROWA; g.fillRect(this.LX, top + i * rh, w - this.LX - 4, rh); g.fillStyle = PCOL[id] || DIM; g.fillRect(this.LX - 5, top + i * rh + 0.5, 3, Math.max(1, rh - 1)); });
    g.font = '10px system-ui, sans-serif'; g.textBaseline = 'middle';
    let lastLab = -1e9; for (const b of c.bars) { const x = this.X(b.t); if (x < this.LX - 1 || x > w) continue; g.fillStyle = b.beat ? TICK : BAR; g.fillRect(Math.round(x), b.beat ? top : 10, 1, h - (b.beat ? top : 10) - 3);
      if (!b.beat && x - lastLab > 26) { g.fillStyle = DIM; g.fillText(String(b.n), x + 3, 6); lastLab = x; } }
    g.fillStyle = DIM; g.fillText('bar', 0, 6);
    const ri = Object.fromEntries(c.rows.map((id, i) => [id, i]));
    for (const m of c.marks) { const i = ri[m.row]; if (i == null) continue; const x = this.X(m.t), y = top + i * rh + 0.5, hh = Math.max(1, rh - 1);
      if (m.cls === 'missed') { g.fillStyle = VCOL.missed; g.fillRect(x - 1.5, y - 1, 3, hh + 2); }
      else if (m.cls === 'wrong') { g.strokeStyle = VCOL.wrong; g.lineWidth = 1; g.strokeRect(x - 1.5, y, 3, hh); }
      else { g.fillStyle = m.cls === 'none' ? VCOL.none : PCOL[m.row] || DIM; g.fillRect(x - 1, y, 2, hh); } }
    this.base = g.getImageData(0, 0, this.cv.width, this.cv.height);
  }
  draw(t) {
    if (!this.base || this.cv.width !== Math.round(this.cv.clientWidth * Math.min(2, devicePixelRatio || 1))) this.paintBase();
    if (!this.clip) return; const g = this.cv.getContext('2d'); g.putImageData(this.base, 0, 0);
    const dpr = Math.min(2, devicePixelRatio || 1); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const x = this.X(t); g.fillStyle = 'rgba(255,255,255,0.08)'; g.fillRect(this.LX, 0, x - this.LX, this.h); g.fillStyle = '#ffffff'; g.fillRect(Math.round(x) - 1, 0, 2, this.h);
  }
}

// ---- the upload's note chart: the whole MIDI by bar; drag to pick bars ----
export class Chart {
  constructor(cv, onPick) {
    this.cv = cv; this.a = null; this.sel = [1, 1]; this.onPick = onPick; this.PX = 22; this.LX = 70; this.head = null;
    let drag = null;
    const bar = (e) => { const r = this.cv.getBoundingClientRect(); return Math.max(1, Math.min(this.a.nbars, Math.floor((e.clientX - r.left - this.LX) / this.PX) + 1)); };
    cv.addEventListener('pointerdown', (e) => { if (!this.a) return; drag = bar(e); cv.setPointerCapture(e.pointerId); this.onPick(drag, drag, false); });
    cv.addEventListener('pointermove', (e) => { if (drag == null) return; const b = bar(e); this.onPick(Math.min(drag, b), Math.max(drag, b), false); });
    const up = () => { if (drag == null) return; drag = null; this.onPick(this.sel[0], this.sel[1], true); }; cv.addEventListener('pointerup', up); cv.addEventListener('pointercancel', up);
  }
  set(a) {
    this.a = a; this.rows = sortRows(a.notes.map((n) => n.row));
    const avail = this.cv.parentElement.clientWidth || 600; this.PX = Math.max(14, Math.min(44, (avail - this.LX - 8) / a.nbars));
    this.cv.style.width = `${Math.ceil(this.LX + a.nbars * this.PX + 8)}px`; this.cv.style.height = `${22 + Math.max(4, this.rows.length) * 14 + 6}px`;
  }
  draw() {
    const { g, w, h } = fit(this.cv), a = this.a; g.fillStyle = BG; g.fillRect(0, 0, w, h); if (!a) return;
    const top = 22, rh = 14, X = (bar) => this.LX + (bar - 1) * this.PX; g.font = '11px system-ui, sans-serif'; g.textBaseline = 'middle';
    this.rows.forEach((id, i) => { g.fillStyle = i % 2 ? ROWB : ROWA; g.fillRect(this.LX, top + i * rh, w - this.LX, rh); g.fillStyle = PCOL[id] || DIM; g.fillText(LABEL[id] || id, 6, top + i * rh + rh / 2); });
    const [s0, s1] = this.sel; g.fillStyle = 'rgba(122,162,255,0.16)'; g.fillRect(X(s0), 0, (s1 - s0 + 1) * this.PX, h); g.fillStyle = '#7aa2ff'; g.fillRect(X(s0), 0, (s1 - s0 + 1) * this.PX, 2);
    const every = this.PX < 18 ? 4 : this.PX < 26 ? 2 : 1;
    for (let b = 1; b <= a.nbars + 1; b++) { const x = Math.round(X(b)); g.fillStyle = (b - 1) % 4 === 0 ? BAR : TICK; g.fillRect(x, top - 4, 1, h - top + 4); if (b <= a.nbars && (b - 1) % every === 0) { g.fillStyle = b >= s0 && b <= s1 ? '#c9d6ff' : DIM; g.fillText(String(b), x + 3, 11); } }
    const ri = Object.fromEntries(this.rows.map((id, i) => [id, i]));
    for (const n of a.notes) { const i = ri[n.row], x = X(n.bar); g.globalAlpha = 0.35 + 0.65 * (n.vel / 127); g.fillStyle = PCOL[n.row] || DIM; g.fillRect(x - 1, top + i * rh + 2, Math.max(2, this.PX * 0.08), rh - 4); }
    g.globalAlpha = 1;
    if (this.head != null) { const x = X(this.head); g.fillStyle = '#fff'; g.fillRect(x - 1, 0, 2, h); }
  }
}
