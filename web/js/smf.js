// smf.js: a small Standard MIDI File reader for uploads (format 0/1, ticks-per-quarter division, running status),
// and the solver's note map: the Groove/TD-11 rims and edges fold onto heads and bows, then drumkit.yaml's note_map
// gives the piece. Pitches the solver drops are counted, not charted.

// pitch -> [piece, zone]  (TD-11 fold, then the kit's note_map; rig-foundations drumkit.yaml + core/rigenv.py)
export const NOTE_MAP = {
  36: ['kick', 'beater'], 44: ['hatped', 'pedal'], 38: ['snare', 'head'], 40: ['snare', 'rimshot'], 37: ['snare', 'cross'],
  42: ['hat', 'closed'], 22: ['hat', 'closed'], 46: ['hat', 'open'], 26: ['hat', 'open'],
  48: ['tom1', 'head'], 50: ['tom1', 'head'], 45: ['tom2', 'head'], 47: ['tom2', 'head'], 43: ['floor', 'head'], 58: ['floor', 'head'], 41: ['floor', 'head'],
  49: ['crash', 'edge'], 55: ['crash', 'edge'], 57: ['crash', 'edge'], 52: ['crash', 'edge'], 51: ['ride', 'bow'], 59: ['ride', 'bow'], 53: ['ride', 'bell'],
};

export function parseSMF(buf) {
  const d = new DataView(buf); let p = 0;
  const str = (n) => { let s = ''; for (let i = 0; i < n; i++) s += String.fromCharCode(d.getUint8(p + i)); p += n; return s; };
  const u32 = () => { const v = d.getUint32(p); p += 4; return v; }, u16 = () => { const v = d.getUint16(p); p += 2; return v; };
  if (buf.byteLength < 14 || str(4) !== 'MThd') throw new Error('not a MIDI file (no MThd header)');
  const hl = u32(), format = u16(), ntr = u16(), div = u16(); p = 8 + hl;
  if (div & 0x8000) throw new Error('SMPTE-timed MIDI files are not supported');
  const notes = [], tempos = [], sigs = [], names = [];
  for (let t = 0; t < ntr && p + 8 <= buf.byteLength; t++) {
    const id = str(4), len = u32(), end = Math.min(buf.byteLength, p + len);
    if (id !== 'MTrk') { p = end; continue; }
    let tick = 0, run = 0; const open = new Map();
    const vlq = () => { let v = 0, b; do { b = d.getUint8(p++); v = (v << 7) | (b & 0x7f); } while (b & 0x80 && p < end); return v; };
    while (p < end) {
      tick += vlq(); let st = d.getUint8(p);
      if (st < 0x80) st = run; else { p++; if (st < 0xf0) run = st; }
      if (st === 0xff) { const type = d.getUint8(p++), n = vlq(), s = p; p += n;
        if (type === 0x51 && n === 3) tempos.push({ tick, uspq: (d.getUint8(s) << 16) | (d.getUint8(s + 1) << 8) | d.getUint8(s + 2) });
        else if (type === 0x58 && n >= 2) sigs.push({ tick, num: d.getUint8(s), den: 2 ** d.getUint8(s + 1) });
        else if (type === 0x03 && n) { let x = ''; for (let i = 0; i < n; i++) x += String.fromCharCode(d.getUint8(s + i)); names.push(x); }
        else if (type === 0x2f) { p = end; }
        continue; }
      if (st === 0xf0 || st === 0xf7) { p += vlq(); continue; }
      const hi = st & 0xf0, ch = st & 0x0f;
      if (hi === 0xc0 || hi === 0xd0) { p += 1; continue; }
      const a = d.getUint8(p++), b = d.getUint8(p++);
      if (hi === 0x90 && b > 0) { const n = { tick, ch, pitch: a, vel: b, dur: 0 }; notes.push(n); open.set(ch * 128 + a, n); }
      else if (hi === 0x80 || (hi === 0x90 && b === 0)) { const n = open.get(ch * 128 + a); if (n) { n.dur = tick - n.tick; open.delete(ch * 128 + a); } }
    }
    p = end;
  }
  notes.sort((x, y) => x.tick - y.tick); tempos.sort((x, y) => x.tick - y.tick); sigs.sort((x, y) => x.tick - y.tick);
  return { format, tpq: div, notes, tempos, sigs, names };
}

// seconds at a tick, from the tempo map
function timer(tpq, tempos) {
  const segs = []; let t = 0, lastTick = 0, us = 500000;
  for (const x of tempos) { t += ((x.tick - lastTick) * us) / tpq / 1e6; segs.push({ tick: x.tick, t, us: x.uspq }); lastTick = x.tick; us = x.uspq; }
  return (tick) => { let s = { tick: 0, t: 0, us: 500000 }; for (const x of segs) { if (x.tick <= tick) s = x; else break; } return s.t + ((tick - s.tick) * s.us) / tpq / 1e6; };
}

// what the page shows for an upload: drum notes by piece, bars as the solver counts them (ticks per bar = tpq x meter)
export function analyse(smf, fileName) {
  const ch9 = smf.notes.filter((n) => n.ch === 9), src = ch9.length ? ch9 : smf.notes;
  const sig = smf.sigs[0] || { num: 4, den: 4 }, meter = (sig.num * 4) / sig.den;      // quarter notes per bar (3/4, 6/8 -> 3; 5/8 -> 2.5)
  const tpbar = smf.tpq * meter, sec = timer(smf.tpq, smf.tempos);
  const bpm = smf.tempos.length ? 60e6 / smf.tempos[0].uspq : 120;
  const drums = [], dropped = new Map();
  for (const n of src) { const m = NOTE_MAP[n.pitch]; if (!m) { dropped.set(n.pitch, (dropped.get(n.pitch) || 0) + 1); continue; } drums.push({ ...n, row: m[0], zone: m[1], bar: n.tick / tpbar + 1, t: sec(n.tick) }); }
  let lastTick = 0; for (const n of src) lastTick = Math.max(lastTick, n.tick);          // the last note-on, as the solver's bar_info counts
  const nbars = Math.floor(lastTick / tpbar) + 1;
  const firstBar = drums.length ? Math.floor(drums[0].bar) : 1;
  const tempoChanges = new Set(smf.tempos.map((x) => x.uspq)).size > 1, sigChanges = new Set(smf.sigs.map((x) => `${x.num}/${x.den}`)).size > 1;
  return {
    name: fileName, bpm, sig: `${sig.num}/${sig.den}`, meter, tpq: smf.tpq, tpbar, nbars, firstBar, notes: drums, dropped,
    channel: ch9.length ? 'channel 10' : 'all channels (no channel 10 found)', tempoChanges, sigChanges, sec, barStart: (b) => sec(Math.round((b - 1) * tpbar)),
  };
}
