// audio.ts: the drum sound. A sample kit (kits/<id>/kit.json, pieces keyed by the motion's piece ids, velocity layers per piece)
// played through WebAudio; a small synth stands in for any piece the kit lacks (or when no kit loads).
// No AudioContext exists until the first play (to save compute, and the autoplay rules): until then the page is silent.
// Each hit is a source: 'midi' (what should sound) or 'hits' (the measured contacts, what the drummer played). In stack mode MIDI pans
// left and the performance right, and a performance hit carries a short bright tick, so a late hit reads as a flam (the review page's sound).

const FALLBACK: Record<string, string[]> = { crash2: ['crash'], china: ['crash'], splash: ['crash'], tom3: ['tom2', 'floor'], floor: ['tom3'], floor2: ['floor', 'tom3'], kick2: ['kick'], tom1: ['tom2'], tom2: ['tom1', 'tom3'] };
const CHOKES: Record<string, string[]> =  { hat: ['hat'], hatped: ['hat'] };       // a closed hat or the pedal stops the ringing open hat

export class Drums {
  [k: string]: any;
  constructor() { this.ac = null; this.out = null; this.kit = null; this.dir = ''; this.bufs = new Map(); this.rr = new Map(); this.ring = new Map(); this.vol = 0.8; this.muted = false; this.noiseBuf = null; this.status = 'no kit';
    this.engine = 'samples'; this.pending = []; this.log = null; this.vsrc = { midi: 1, hits: 1 }; this.count = { midi: 0, hits: 0, tick: 0, samples: 0, synth: 0 }; }

  // call from a user gesture
  unlock() {
    if (!this.ac) { const AC = window.AudioContext || (window as any).webkitAudioContext; if (!AC) return false; this.ac = new AC(); this.out = this.ac.createGain(); this.out.connect(this.ac.destination); this.applyGain(); if (this.kit) this.preload(this._want || []); }
    if (this.ac.state === 'suspended') this.ac.resume().catch(() => {});
    return true;
  }
  get live() { return !!this.ac && this.ac.state === 'running' && !this.muted; }
  setVolume(v: number) { this.vol = Math.max(0, Math.min(1, v)); this.applyGain(); }
  setMuted(m: boolean) { this.muted = !!m; this.applyGain(); }
  applyGain() { if (this.out) this.out.gain.setTargetAtTime(this.muted ? 0 : this.vol * this.vol, this.ac.currentTime, 0.015); }

  async loadKit(dir: string) {
    this.dir = dir.replace(/\/?$/, '/');
    const r = await fetch(this.dir + 'kit.json'); if (!r.ok) throw new Error('kit.json ' + r.status);
    const k = await r.json(); if (!k || !k.pieces || typeof k.pieces !== 'object') throw new Error('kit.json has no pieces');
    this.kit = k; this.bufs.clear(); this.status = `${k.name || k.id || 'kit'}`;
    if (this.ac) this.preload(this._want || []);
    return k;
  }
  layersFor(row: string, zone?: string): any {
    if (!this.kit) return null; const P = this.kit.pieces;
    for (const id of [zone ? `${row}:${zone}` : null, zone ? `${row}_${zone}` : null, row, ...(FALLBACK[row] || [])]) if (id && Array.isArray(P[id]) && P[id].length) return { id, layers: P[id] };
    return null;
  }
  // fetch + decode only the pieces a clip uses; buffers are cached across clips
  preload(rows: any[]): Promise<any> {
    this._want = rows; if (!this.kit || !this.ac) return Promise.resolve();
    const files = new Set<string>(); for (const [row, zone] of rows) { const L = this.layersFor(row, zone); if (L) for (const l of L.layers) if (l.file) files.add(l.file); }
    return Promise.all([...files].map((f) => {
      if (this.bufs.has(f)) return this.bufs.get(f);
      const p = fetch(this.dir + f).then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(f)))).then((a: ArrayBuffer) => new Promise((res, rej) => this.ac.decodeAudioData(a, res, rej))).catch(() => null).then((buf: any) => { this.bufs.set(f, buf); return buf; });
      this.bufs.set(f, p); return p;
    }));
  }
  pick(row: string, zone: string, vel: number) {
    const L = this.layersFor(row, zone); if (!L) return null;
    let c = L.layers.filter((l: any) => l.vel && vel >= l.vel[0] && vel <= l.vel[1]);
    if (!c.length) { let best = Infinity; for (const l of L.layers) { const v = l.vel || [0, 127], d = vel < v[0] ? v[0] - vel : vel - v[1]; if (d < best) { best = d; c = [l]; } else if (d === best) c.push(l); } }
    const key = L.id + ':' + c.map((l: any) => l.file).join('|'), i = (this.rr.get(key) || 0) % c.length; this.rr.set(key, i + 1);      // round robin among the layer's takes
    return { layer: c[i], id: L.id };
  }
  noise() { if (this.noiseBuf) return this.noiseBuf; const a = this.ac, b = a.createBuffer(1, a.sampleRate, a.sampleRate), d = b.getChannelData(0); let s = 7; for (let i = 0; i < d.length; i++) { s = (s * 16807) % 2147483647; d[i] = (s / 2147483647) * 2 - 1; } return (this.noiseBuf = b); }

  // play one hit `when` seconds from now (AudioContext time offset). o = {src: 'midi' | 'hits', stack: bool}
  // o.at = the exact AudioContext time to sound at (the look-ahead scheduler's); otherwise `when` seconds from now
  hit(row: string, vel = 90, zone = '', when = 0, o: any = {}) {
    if (!this.live) return;
    const src = o.src || 'midi', a = this.ac, now = a.currentTime, t0 = o.at != null ? Math.max(o.at, now) : now + 0.01 + Math.max(0, when), v = Math.max(1, Math.min(127, Math.round(vel)));
    const lvl = this.vsrc[src] ?? 1; if (lvl <= 0) return;
    this.count[src] = (this.count[src] || 0) + 1;
    if (this.log && o.at != null) this.log.push({ src, row, at: o.at, start: t0, now, t: o.t, u: o.u });
    const bus = a.createGain(); bus.gain.value = lvl; const rec: any = { t0, nodes: [], bus }; this._rec = rec;
    if (t0 > now + 0.004) { this.pending.push(rec); if (this.pending.length > 512) this.pending = this.pending.filter((p: any) => p.t0 > now); }
    if (o.stack && a.createStereoPanner) { const pn = a.createStereoPanner(); pn.pan.value = src === 'midi' ? -0.85 : 0.85; bus.connect(pn); pn.connect(this.out); } else bus.connect(this.out);
    if (o.stack && src === 'hits') { this.count.tick++; const os = a.createOscillator(), og = a.createGain(); os.type = 'square'; os.frequency.value = 3200; og.gain.setValueAtTime(0.18, t0); og.gain.exponentialRampToValueAtTime(0.001, t0 + 0.012); os.connect(og); og.connect(bus); os.start(t0); os.stop(t0 + 0.015); rec.nodes.push(os); }
    const chokeKey = src + ':hat';
    for (const id of CHOKES[row] || []) if (!(row === 'hat' && /^open/.test(zone || ''))) { for (const g of this.ring.get(src + ':' + id) || []) g.gain.setTargetAtTime(0, t0, 0.012); this.ring.set(src + ':' + id, []); }
    if (this.engine === 'samples') {
      const p = this.pick(row, zone, v);
      if (p && p.layer.file) {
        const pr = this.bufs.get(p.layer.file);
        if (pr && typeof pr.then !== 'function') { this.count.samples++; return this._play(pr, p, v, t0, row, zone, bus, chokeKey); }
        if (pr === undefined) this.preload([...(this._want || []), [row, zone]]);        // not asked for yet: fetch it, the synth covers this hit
      }
    }
    this.count.synth++; this.synth(row, v, zone, t0, bus);
  }
  _play(buf: AudioBuffer, p: any, v: number, t0: number, row: string, zone: string, bus: GainNode, chokeKey: string) {
    const a = this.ac, g = a.createGain(), lo = p.layer.vel ? p.layer.vel[0] : 0, hi = p.layer.vel ? p.layer.vel[1] : 127;
    g.gain.value = 0.55 * (p.layer.gain || 1) * (0.7 + 0.3 * Math.min(1, (v - lo + 1) / (hi - lo + 1))); g.connect(bus);
    const s = a.createBufferSource(); s.buffer = buf; s.connect(g); s.start(t0); this._rec.nodes.push(s);
    if (row === 'hat' && /^open/.test(zone || '')) { const l = this.ring.get(chokeKey) || []; l.push(g); this.ring.set(chokeKey, l); }
  }
  // drop every voice queued for the future (a seek, a re-anchor, a pause)
  flush() { if (!this.ac) return; const now = this.ac.currentTime; for (const p of this.pending) if (p.t0 > now) { for (const n of p.nodes) { try { n.stop(0); } catch { /* not started */ } } try { p.bus.disconnect(); } catch { /* gone */ } } this.pending = []; }
  synth(row: string, v: number, zone: string, t0: number, bus?: GainNode) {
    const a = this.ac, g = a.createGain(), amp = Math.max(0.08, v / 127) * 0.5; g.connect(bus || this.out);
    const fam = row.startsWith('kick') ? 'kick' : row === 'snare' ? 'snare' : row === 'hat' ? 'hat' : row === 'hatped' ? 'ped' : /crash|ride|china|splash/.test(row) ? 'cym' : /tom|floor/.test(row) ? 'tom' : 'other';
    const nz = (dur: number, type: BiquadFilterType, f: number, q = 0.8) => { const s = a.createBufferSource(); s.buffer = this.noise(); const fl = a.createBiquadFilter(); fl.type = type; fl.frequency.value = f; fl.Q.value = q; s.connect(fl); fl.connect(g); s.start(t0); s.stop(t0 + dur); this._rec.nodes.push(s); };
    const tone = (f0: number, f1: number, dur: number) => { const o = a.createOscillator(); o.frequency.setValueAtTime(f0, t0); o.frequency.exponentialRampToValueAtTime(f1, t0 + dur); o.connect(g); o.start(t0); o.stop(t0 + dur); this._rec.nodes.push(o); };
    let dur = 0.1;
    if (fam === 'kick') { dur = 0.18; tone(130, 45, dur); } else if (fam === 'snare') { dur = 0.14; nz(dur, 'bandpass', 1900, 0.6); tone(230, 170, 0.06); }
    else if (fam === 'tom') { dur = 0.22; const f = ({ tom1: 210, tom2: 170, tom3: 140, floor: 110, floor2: 95 } as Record<string, number>)[row] || 150; tone(f, f * 0.7, dur); }
    else if (fam === 'hat') { dur = /^open/.test(zone || '') ? 0.25 : 0.045; nz(dur, 'highpass', 7500); } else if (fam === 'ped') { dur = 0.03; nz(dur, 'highpass', 5000); }
    else if (fam === 'cym') { dur = row === 'ride' ? 0.35 : 0.8; nz(dur, 'highpass', row === 'ride' ? 6000 : 4500); if (zone === 'bell') tone(1250, 1200, 0.25); } else nz(dur, 'highpass', 3000);
    g.gain.setValueAtTime(amp, t0); g.gain.exponentialRampToValueAtTime(0.001, t0 + dur);
  }
}
