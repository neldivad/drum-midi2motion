// audio.js: the drum sound. A sample kit (kits/<id>/kit.json, pieces keyed by the motion's piece ids, velocity layers per piece)
// played through WebAudio; a small synth stands in for any piece the kit lacks (or when no kit loads).
// No AudioContext exists until the first user gesture (autoplay rules): until then the page is silent.

const FALLBACK = { crash2: ['crash'], china: ['crash'], splash: ['crash'], tom3: ['tom2', 'floor'], floor: ['tom3'], floor2: ['floor', 'tom3'], kick2: ['kick'], tom1: ['tom2'], tom2: ['tom1', 'tom3'] };
const CHOKES = { hat: ['hat'], hatped: ['hat'] };       // a closed hat or the pedal stops the ringing open hat

export class Drums {
  constructor() { this.ac = null; this.out = null; this.kit = null; this.dir = ''; this.bufs = new Map(); this.rr = new Map(); this.ring = new Map(); this.vol = 0.8; this.muted = false; this.noiseBuf = null; this.status = 'no kit'; }

  // call from a user gesture
  unlock() {
    if (!this.ac) { const AC = window.AudioContext || window.webkitAudioContext; if (!AC) return false; this.ac = new AC(); this.out = this.ac.createGain(); this.out.connect(this.ac.destination); this.applyGain(); if (this.kit) this.preload(this._want || []); }
    if (this.ac.state === 'suspended') this.ac.resume().catch(() => {});
    return true;
  }
  get live() { return !!this.ac && this.ac.state === 'running' && !this.muted; }
  setVolume(v) { this.vol = Math.max(0, Math.min(1, v)); this.applyGain(); }
  setMuted(m) { this.muted = !!m; this.applyGain(); }
  applyGain() { if (this.out) this.out.gain.setTargetAtTime(this.muted ? 0 : this.vol * this.vol, this.ac.currentTime, 0.015); }

  async loadKit(dir) {
    this.dir = dir.replace(/\/?$/, '/');
    const r = await fetch(this.dir + 'kit.json'); if (!r.ok) throw new Error('kit.json ' + r.status);
    const k = await r.json(); if (!k || !k.pieces || typeof k.pieces !== 'object') throw new Error('kit.json has no pieces');
    this.kit = k; this.bufs.clear(); this.status = `${k.name || k.id || 'kit'}`;
    if (this.ac) this.preload(this._want || []);
    return k;
  }
  layersFor(row, zone) {
    if (!this.kit) return null; const P = this.kit.pieces;
    for (const id of [zone ? `${row}:${zone}` : null, zone ? `${row}_${zone}` : null, row, ...(FALLBACK[row] || [])]) if (id && Array.isArray(P[id]) && P[id].length) return { id, layers: P[id] };
    return null;
  }
  // fetch + decode only the pieces a clip uses; buffers are cached across clips
  preload(rows) {
    this._want = rows; if (!this.kit || !this.ac) return Promise.resolve();
    const files = new Set(); for (const [row, zone] of rows) { const L = this.layersFor(row, zone); if (L) for (const l of L.layers) if (l.file) files.add(l.file); }
    return Promise.all([...files].map((f) => {
      if (this.bufs.has(f)) return this.bufs.get(f);
      const p = fetch(this.dir + f).then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(f)))).then((a) => new Promise((res, rej) => this.ac.decodeAudioData(a, res, rej))).catch(() => null).then((buf) => { this.bufs.set(f, buf); return buf; });
      this.bufs.set(f, p); return p;
    }));
  }
  pick(row, zone, vel) {
    const L = this.layersFor(row, zone); if (!L) return null;
    let c = L.layers.filter((l) => l.vel && vel >= l.vel[0] && vel <= l.vel[1]);
    if (!c.length) { let best = Infinity; for (const l of L.layers) { const v = l.vel || [0, 127], d = vel < v[0] ? v[0] - vel : vel - v[1]; if (d < best) { best = d; c = [l]; } else if (d === best) c.push(l); } }
    const key = L.id + ':' + c.map((l) => l.file).join('|'), i = (this.rr.get(key) || 0) % c.length; this.rr.set(key, i + 1);      // round robin among the layer's takes
    return { layer: c[i], id: L.id };
  }
  noise() { if (this.noiseBuf) return this.noiseBuf; const a = this.ac, b = a.createBuffer(1, a.sampleRate, a.sampleRate), d = b.getChannelData(0); let s = 7; for (let i = 0; i < d.length; i++) { s = (s * 16807) % 2147483647; d[i] = (s / 2147483647) * 2 - 1; } return (this.noiseBuf = b); }

  // play one hit `when` seconds from now (AudioContext time offset)
  hit(row, vel = 90, zone = '', when = 0) {
    if (!this.live) return;
    const a = this.ac, t0 = a.currentTime + 0.01 + Math.max(0, when), v = Math.max(1, Math.min(127, Math.round(vel)));
    for (const id of CHOKES[row] || []) if (!(row === 'hat' && /^open/.test(zone || ''))) { for (const g of this.ring.get(id) || []) g.gain.setTargetAtTime(0, t0, 0.012); this.ring.set(id, []); }
    const p = this.pick(row, zone, v);
    if (p && p.layer.file) {
      const pr = this.bufs.get(p.layer.file);
      if (pr && typeof pr.then !== 'function') return this._play(pr, p, v, t0, row, zone);
      if (pr === undefined) this.preload([...(this._want || []), [row, zone]]);        // not asked for yet: fetch it, the synth covers this hit
    }
    this.synth(row, v, zone, t0);
  }
  _play(buf, p, v, t0, row, zone) {
    const a = this.ac, g = a.createGain(), lo = p.layer.vel ? p.layer.vel[0] : 0, hi = p.layer.vel ? p.layer.vel[1] : 127;
    g.gain.value = 0.55 * (p.layer.gain || 1) * (0.7 + 0.3 * Math.min(1, (v - lo + 1) / (hi - lo + 1))); g.connect(this.out);
    const s = a.createBufferSource(); s.buffer = buf; s.connect(g); s.start(t0);
    if (row === 'hat' && /^open/.test(zone || '')) { const l = this.ring.get('hat') || []; l.push(g); this.ring.set('hat', l); }
  }
  synth(row, v, zone, t0) {
    const a = this.ac, g = a.createGain(), amp = Math.max(0.08, v / 127) * 0.5; g.connect(this.out);
    const fam = row.startsWith('kick') ? 'kick' : row === 'snare' ? 'snare' : row === 'hat' ? 'hat' : row === 'hatped' ? 'ped' : /crash|ride|china|splash/.test(row) ? 'cym' : /tom|floor/.test(row) ? 'tom' : 'other';
    const nz = (dur, type, f, q = 0.8) => { const s = a.createBufferSource(); s.buffer = this.noise(); const fl = a.createBiquadFilter(); fl.type = type; fl.frequency.value = f; fl.Q.value = q; s.connect(fl); fl.connect(g); s.start(t0); s.stop(t0 + dur); };
    const tone = (f0, f1, dur) => { const o = a.createOscillator(); o.frequency.setValueAtTime(f0, t0); o.frequency.exponentialRampToValueAtTime(f1, t0 + dur); o.connect(g); o.start(t0); o.stop(t0 + dur); };
    let dur = 0.1;
    if (fam === 'kick') { dur = 0.18; tone(130, 45, dur); } else if (fam === 'snare') { dur = 0.14; nz(dur, 'bandpass', 1900, 0.6); tone(230, 170, 0.06); }
    else if (fam === 'tom') { dur = 0.22; const f = { tom1: 210, tom2: 170, tom3: 140, floor: 110, floor2: 95 }[row] || 150; tone(f, f * 0.7, dur); }
    else if (fam === 'hat') { dur = /^open/.test(zone || '') ? 0.25 : 0.045; nz(dur, 'highpass', 7500); } else if (fam === 'ped') { dur = 0.03; nz(dur, 'highpass', 5000); }
    else if (fam === 'cym') { dur = row === 'ride' ? 0.35 : 0.8; nz(dur, 'highpass', row === 'ride' ? 6000 : 4500); } else nz(dur, 'highpass', 3000);
    g.gain.setValueAtTime(amp, t0); g.gain.exponentialRampToValueAtTime(0.001, t0 + dur);
  }
}
