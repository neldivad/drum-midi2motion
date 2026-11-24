// main.js: the page. One UI state object (state.js: S) that clip changes never reset; a clip is {motion, judgement, meta}
// and loading one swaps only that. Query (not state): ?manifest=<url> · ?glb=<url> · ?kit=<kit folder with kit.json>.
import { S, loadState, save, onHashChange } from './state.js';
import { createStage, CAMS } from './stage.js';
import { Drums } from './audio.js';
import { parseSMF, analyse } from './smf.js';
import { Timeline, Chart, PCOL, VCOL, LABEL, SHORT, sortRows } from './lanes.js';

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const Q = new URLSearchParams(location.search);
const url = (p) => new URL(p, document.baseURI).href;                 // manifest paths are relative to web/
const MANIFEST = Q.get('manifest') || 'presets/manifest.json', GLB = Q.get('glb') || 'assets/android_base.glb';
const SRC_LABEL = { groove: 'Groove MIDI', author: "The author's songs" };
const SRC_CREDIT = { groove: 'Groove MIDI Dataset (Magenta), CC BY 4.0', author: '© the author' };
const fmtMeter = (m) => (m == null || m === '' ? '' : typeof m === 'string' ? m : Number.isInteger(m) ? `${m}/4` : Number.isInteger(m * 2) ? `${m * 2}/8` : String(m));
const meterQ = (m) => { if (typeof m === 'number') return m; const x = /^(\d+)\s*\/\s*(\d+)$/.exec(m || ''); return x ? (+x[1] * 4) / +x[2] : null; };
async function getJSON(u) { const r = await fetch(u); if (!r.ok) throw new Error(`${r.status} ${u}`); return r.json(); }

let toastT = 0;
function toast(msg, ms = 3200) { const t = $('toast'); t.textContent = msg; t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => { t.hidden = true; }, ms); }

// ───────── state → controls ─────────
loadState();
let PRESETS = [], MAN = null, stage = null, CL = null, Tn = 0, playing = false, dirty = true, listen = null;
const drums = new Drums(); drums.setVolume(S.sound.vol); drums.setMuted(S.sound.muted);

const pressed = (el, on) => { el.setAttribute('aria-pressed', on ? 'true' : 'false'); };
function applyUI() {
  $('fq').value = S.f.q; for (const k of ['kind', 'style', 'meter', 'source']) ensureOpt($('f' + k), S.f[k]);
  $('filters').hidden = !S.panels.filters; $('tgFilters').setAttribute('aria-expanded', String(S.panels.filters));
  $('fclear').hidden = !Object.values(S.f).some(Boolean);
  for (const b of $('speed').children) b.classList.toggle('on', +b.dataset.v === S.speed);
  pressed($('loop'), S.loop); pressed($('orbit'), S.orbit); pressed($('xray'), S.ov.xray); pressed($('flash'), S.ov.flash); pressed($('hudbtn'), S.ov.hud);
  for (const b of $('cams').children) b.classList.toggle('on', b.dataset.cam === S.cam);
  $('vol').value = S.sound.vol; soundUI();
  $('ibody').hidden = !S.panels.info; $('tgInfo').textContent = S.panels.info ? 'Hide' : 'Show'; $('tgInfo').setAttribute('aria-expanded', String(S.panels.info));
  $('midi').hidden = !S.panels.midi;
  if (stage) stage.setXray(S.ov.xray);
  dirty = true;
}
function ensureOpt(sel, v) { if (v && ![...sel.options].some((o) => o.value === v)) sel.add(new Option(v, v)); sel.value = v; }
function soundUI() {
  const off = S.sound.muted || !drums.ac, b = $('mute');
  b.classList.toggle('off', off); b.setAttribute('aria-label', off ? 'Sound on' : 'Mute');
  b.title = !drums.ac ? 'Sound starts after your first click or key press' : S.sound.muted ? 'Sound is muted: click to unmute' : 'Mute';
  $('muteIcon').setAttribute('d', off ? 'M3 9v6h4l5 5V4L7 9zm13.6 3 2.7-2.7-1.4-1.4-2.7 2.7-2.7-2.7-1.4 1.4 2.7 2.7-2.7 2.7 1.4 1.4 2.7-2.7 2.7 2.7 1.4-1.4z' : 'M3 9v6h4l5 5V4L7 9zm11.5 3A4.5 4.5 0 0 0 12 8v8a4.5 4.5 0 0 0 2.5-4zM12 3.2v2.1a7 7 0 0 1 0 13.4v2.1a9 9 0 0 0 0-17.6z');
}
function setS(fn, { list = false, now = false } = {}) { fn(); applyUI(); if (list) renderList(); save(now); }

// ───────── the preset list ─────────
function matches(p) {
  const f = S.f; if (f.kind && p.kind !== f.kind) return false; if (f.style && p.style !== f.style) return false;
  if (f.meter && fmtMeter(p.meter) !== f.meter) return false; if (f.source && p.source !== f.source) return false;
  if (f.q) { const hay = [p.title, p.style, p.kind, p.source, p.credit, p.id, SRC_LABEL[p.source]].join(' ').toLowerCase(); for (const w of f.q.toLowerCase().split(/\s+/).filter(Boolean)) if (!hay.includes(w)) return false; }
  return true;
}
function fillFilterOptions() {
  const opts = (sel, vals, label) => { const cur = S.f[sel.id.slice(1)]; sel.innerHTML = `<option value="">${label}</option>` + vals.map((v) => `<option value="${esc(v[0])}">${esc(v[1])}</option>`).join(''); ensureOpt(sel, cur); };
  const uniq = (a) => [...new Set(a.filter((x) => x != null && x !== ''))].sort();
  opts($('fstyle'), uniq(PRESETS.map((p) => p.style)).map((s) => [s, s]), 'Any style');
  opts($('fmeter'), uniq(PRESETS.map((p) => fmtMeter(p.meter))).map((s) => [s, s]), 'Any meter');
  opts($('fsource'), uniq(PRESETS.map((p) => p.source)).map((s) => [s, SRC_LABEL[s] || s]), 'Any source');
}
function renderList() {
  const L = $('list'), vis = PRESETS.filter(matches); const top = L.scrollTop;
  $('count').textContent = PRESETS.length ? (vis.length === PRESETS.length ? `${PRESETS.length}` : `${vis.length} of ${PRESETS.length}`) : '';
  if (!PRESETS.length) { L.innerHTML = `<li class="none">${MAN === false ? 'No presets are published yet. Drop a motion file to play one.' : 'Loading presets…'}</li>`; return; }
  if (!vis.length) { L.innerHTML = '<li class="none">No preset matches these filters.</li>'; return; }
  L.innerHTML = vis.map((p) => { const pct = played(p.played_pct), bars = Array.isArray(p.bars) ? `bars ${p.bars[0]}–${p.bars[1]}` : '';
    return `<li role="option" tabindex="0" data-id="${esc(p.id)}" class="${p.id === S.clip ? 'on' : ''}" aria-selected="${p.id === S.clip}"><span class="t">${esc(p.title || p.id)}</span>` +
      `<span class="pct${pct === 100 ? ' full' : ''}" title="notes played">${pct != null ? pct.toFixed(pct === 100 ? 0 : 1) + ' %' : ''}</span>` +
      `<span class="m"><span class="badge ${esc(p.kind)}">${esc(p.kind || '')}</span>${esc([p.style, p.bpm ? Math.round(p.bpm) + ' bpm' : '', fmtMeter(p.meter), bars].filter(Boolean).join(' · '))}</span></li>`; }).join('');
  L.scrollTop = top;
}
const played = (x) => (x == null || !Number.isFinite(+x) ? null : +x);
function markSelected() { for (const li of $('list').querySelectorAll('li[data-id]')) { const on = li.dataset.id === S.clip; li.classList.toggle('on', on); li.setAttribute('aria-selected', String(on)); } }

// ───────── clips ─────────
const cache = new Map(); let loadSeq = 0;
async function loadPreset(p, { autoplay = true } = {}) {
  const seq = ++loadSeq; S.clip = p.id; markSelected(); save();
  try {
    let pair = cache.get(p.id);
    if (!pair) { $('ititle').textContent = `Loading ${p.title || p.id}…`;
      pair = await Promise.all([getJSON(url(p.motion)), p.judgement ? getJSON(url(p.judgement)).catch(() => null) : null]);
      cache.set(p.id, pair); if (cache.size > 8) cache.delete(cache.keys().next().value); }
    if (seq !== loadSeq) return;
    showClip({ M: pair[0], J: pair[1], meta: p, kind: 'preset' }, autoplay);
  } catch (e) { if (seq === loadSeq) { toast(`Could not load “${p.title || p.id}”: ${e.message}`); renderInfo(); } }
}
function gridOf(M, J, meta) {
  if (J && J.grid && J.grid.beat_s) return { lead: J.grid.lead || 0, beat: J.grid.beat_s, bar0: J.grid.bar0 ?? 1, bpb: J.grid.bpb || 4 };
  const c = M.chart, bpb = meterQ(meta && meta.meter) || (J && J.library && +J.library.meter) || 4;
  if (c && c.bar_s) return { lead: c.lead || 0, beat: c.bar_s / bpb, bar0: (c.bars || [1])[0], bpb };
  return null;
}
function showClip(c, autoplay) {
  if (!stage) { pendingClip = [c, autoplay]; return; }
  try { stage.setClip(c.M); } catch (e) { toast('This motion file does not fit the drummer: ' + e.message, 5000); return; }
  stopListen();
  const M = c.M, J = c.J && Array.isArray(c.J.source) ? c.J : null, dur = Math.max(0.001, (M.frames - 1) / M.fps), G = gridOf(M, J, c.meta);
  const notes = (M.notes || []).map(([t, row, vel, zone]) => ({ t, row, vel, zone }));
  let marks, snd;
  if (J) {
    marks = J.source.map((s) => ({ t: s.t, row: s.row, cls: !s.judged ? 'none' : s.verdict && s.verdict.cls === 'missed' ? 'missed' : s.verdict && s.verdict.cls === 'wrong' ? 'wrong' : 'hit' }));
    snd = J.source.filter((s) => s.judged && s.verdict && s.verdict.cls !== 'missed').map((s) => (s.verdict.cls === 'wrong' && s.verdict.row_hit ? { t: s.verdict.t_hit ?? s.t, row: s.verdict.row_hit, vel: s.vel, zone: s.verdict.zone_hit || s.zone } : { t: s.t, row: s.row, vel: s.vel, zone: s.zone }));
  } else { marks = notes.map((n) => ({ t: n.t, row: n.row, cls: 'hit' })); snd = notes; }
  snd.sort((a, b) => a.t - b.t);
  const bars = [];
  if (G) { for (let k = Math.floor((0 - G.lead) / G.beat) - 1; k <= Math.ceil((dur - G.lead) / G.beat) + 1; k++) { const t = G.lead + k * G.beat; if (t < 0 || t > dur) continue; const q = k / G.bpb; bars.push({ t, beat: Math.abs(q - Math.round(q)) > 1e-6, n: G.bar0 + Math.round(q) }); } }
  const rows = sortRows(J && J.rows ? J.rows.map((r) => r.id).filter((id) => marks.some((m) => m.row === id)) : marks.map((m) => m.row));
  CL = { ...c, J, dur, G, marks, snd, rows, notes };
  timeline.set({ dur, rows, marks, bars });
  drums.preload([...new Set(snd.map((n) => n.row + '\u0000' + (n.zone || '')))].map((k) => k.split('\u0000')));
  Tn = 0; $('empty').hidden = true; renderInfo();
  if (autoplay) setPlay(true); dirty = true;
}
let pendingClip = null;

function renderInfo() {
  if (!CL) { $('ititle').textContent = PRESETS.length ? 'Pick a preset' : 'No clip yet'; $('icredit').textContent = ''; $('ichips').innerHTML = ''; $('ilegend').innerHTML = ''; return; }
  const { M, J, meta, G } = CL, m = meta || {};
  $('ititle').textContent = m.title || M.title || M.key || 'Motion';
  const credit = m.credit || SRC_CREDIT[m.source] || (CL.kind === 'file' ? `Your file: ${m.file}` : '');
  const kitc = drums.kit ? `Drum sounds: ${drums.kit.name || drums.kit.id}${drums.kit.license ? ` (${drums.kit.license})` : ''}${drums.kit.credit ? `, ${drums.kit.credit}` : ''}` : '';
  $('icredit').innerHTML = [credit, kitc].filter(Boolean).map((x) => `<div>${esc(x)}</div>`).join('');
  const A = J && J.tally && J.tally.all, pct = played(A ? A.accuracy_pct : m.played_pct ?? (M.remedy && M.remedy.played_pct));
  const bpm = m.bpm || (G ? 60 / G.beat : null), meter = fmtMeter(m.meter) || (G ? fmtMeter(G.bpb) : ''), bars = Array.isArray(m.bars) ? m.bars : M.chart && M.chart.bars;
  const nMiss = CL.marks.filter((x) => x.cls === 'missed').length, nWrong = CL.marks.filter((x) => x.cls === 'wrong').length, nJ = CL.marks.filter((x) => x.cls !== 'none').length;
  const chip = (k, v, cls = '') => (v == null || v === '' ? '' : `<span class="chip ${cls}">${esc(k)} <b>${esc(v)}</b></span>`);
  $('ichips').innerHTML = chip('played', pct != null ? `${pct.toFixed(pct === 100 ? 0 : 1)} %` : null, pct === 100 ? 'ok' : pct != null && pct < 90 ? 'warn' : '') + chip('tempo', bpm ? `${Math.round(bpm)} bpm` : null) + chip('meter', meter) +
    chip('bars', bars ? `${bars[0]}–${bars[1]}` : null) + chip('length', `${CL.dur.toFixed(1)} s`) + chip('notes', J ? nJ : CL.notes.length) + (J ? chip('missed', nMiss, nMiss ? 'bad' : '') + chip('wrong drum', nWrong || null, 'warn') : '') +
    (M.collisions && M.collisions.length ? chip('collision runs', M.collisions.length, 'bad') : '');
  $('ilegend').innerHTML = CL.rows.map((id) => `<span><i style="background:${PCOL[id] || '#888'}"></i>${esc(LABEL[id] || id)}</span>`).join('') +
    (J ? `<span><i style="background:${VCOL.missed}"></i>missed</span><span><i style="border:1px solid ${VCOL.wrong}"></i>wrong drum</span>` : '<span>(no judgement file: every note shown as played)</span>');
}

// ───────── transport ─────────
function setPlay(p) { playing = !!p && !!CL; $('play').setAttribute('aria-label', playing ? 'Pause' : 'Play'); $('playIcon').setAttribute('d', playing ? 'M6 5h4v14H6zm8 0h4v14h-4z' : 'M7 5v14l12-7z'); if (playing) stopListen(); }
function seek(t) { if (!CL) return; Tn = Math.max(0, Math.min(CL.dur, t)); dirty = true; }
function step(d) { if (!CL) return; setPlay(false); seek(Math.round(Tn * CL.M.fps + d) / CL.M.fps); }
function lower(t) { const a = CL.snd; let lo = 0, hi = a.length; while (lo < hi) { const m = (lo + hi) >> 1; if (a[m].t <= t) lo = m + 1; else hi = m; } return lo; }      // first note after t
function soundBetween(t0, t1) { if (!drums.live || !CL) return; for (let i = lower(t0); i < CL.snd.length && CL.snd[i].t <= t1; i++) { const n = CL.snd[i]; drums.hit(n.row, n.vel, n.zone, 0); } }
function barbeat(t) { const G = CL && CL.G; if (!G) return '–'; const b = (t - G.lead) / G.beat, bar = G.bar0 + Math.floor(b / G.bpb), beat = Math.floor(((b % G.bpb) + G.bpb) % G.bpb) + 1; return `${bar}.${beat}`; }
const timeline = new Timeline($('timeline'), (t, phase) => { if (phase === 'start') { scrubWasPlaying = playing; setPlay(false); } seek(t); if (phase === 'end' && scrubWasPlaying) setPlay(true); });
let scrubWasPlaying = false;

function frame() {
  if (!stage) return;
  let flash = null, hud = [];
  if (CL) {
    const recent = []; for (let i = lower(Tn) - 1; i >= 0 && Tn - CL.snd[i].t < 0.25; i--) recent.push(CL.snd[i]);
    if (S.ov.flash) { flash = {}; for (const n of recent) { const a = 0.5 * (1 - (Tn - n.t) / 0.18); if (a > 0) flash[n.row] = Math.max(flash[n.row] || 0, a); } }
    if (S.ov.hud) hud = [...new Set(recent.map((n) => LABEL[n.row] || n.row))];
    $('bb').textContent = barbeat(Tn); $('tt').textContent = `${Tn.toFixed(2)} / ${CL.dur.toFixed(2)} s`;
  }
  $('hud').textContent = hud.join('  ·  ');
  stage.draw(Tn, flash); timeline.draw(Tn);
}
let last = performance.now();
function tick(now) {
  const dt = Math.min(0.1, (now - last) / 1000); last = now;
  if (stage && S.orbit) { stage.orbit(dt); dirty = true; }
  if (playing && CL) {
    const t0 = Tn; Tn += dt * S.speed;
    if (Tn >= CL.dur) { if (S.loop) { soundBetween(t0, CL.dur); Tn = Tn % CL.dur; soundBetween(-1, Tn); } else { soundBetween(t0, CL.dur); Tn = CL.dur; setPlay(false); } }
    else soundBetween(t0, Tn);
    dirty = true;
  }
  if (listen) listenTick();
  if (dirty) { dirty = false; frame(); }
  requestAnimationFrame(tick);
}

// ───────── controls ─────────
$('play').onclick = () => { if (!CL) return; if (!playing && !S.loop && Tn >= CL.dur - 1e-3) Tn = 0; setPlay(!playing); };
$('prev').onclick = () => step(-1); $('next').onclick = () => step(1);
for (const b of $('speed').children) b.onclick = () => setS(() => { S.speed = +b.dataset.v; });
$('loop').onclick = () => setS(() => { S.loop = !S.loop; });
$('orbit').onclick = () => setS(() => { S.orbit = !S.orbit; if (!S.orbit && stage) { const c = stage.getCam(); S.cam = 'custom'; S.camPos = c.pos; S.camTgt = c.tgt; } });
$('xray').onclick = () => setS(() => { S.ov.xray = !S.ov.xray; });
$('flash').onclick = () => setS(() => { S.ov.flash = !S.ov.flash; });
$('hudbtn').onclick = () => setS(() => { S.ov.hud = !S.ov.hud; });
for (const b of $('cams').children) b.onclick = () => setS(() => { S.cam = b.dataset.cam; S.orbit = false; if (stage) stage.setCam(S.cam); });
$('vol').oninput = () => { S.sound.vol = +$('vol').value; drums.setVolume(S.sound.vol); if (S.sound.muted && S.sound.vol > 0) { S.sound.muted = false; drums.setMuted(false); } soundUI(); save(); };
let unlockedAt = -1e9;
$('mute').onclick = () => { drums.unlock(); if (performance.now() - unlockedAt < 600 && !S.sound.muted) { soundUI(); return; } setS(() => { S.sound.muted = !S.sound.muted; drums.setMuted(S.sound.muted); }); };
const unlock = () => { if (drums.ac) return; if (drums.unlock()) { unlockedAt = performance.now(); soundUI(); window.removeEventListener('pointerdown', unlock, true); window.removeEventListener('keydown', unlock, true); } };
window.addEventListener('pointerdown', unlock, true); window.addEventListener('keydown', unlock, true);

for (const k of ['kind', 'style', 'meter', 'source']) $('f' + k).onchange = () => setS(() => { S.f[k] = $('f' + k).value; }, { list: true });
$('fq').oninput = () => setS(() => { S.f.q = $('fq').value.trim(); }, { list: true });
$('fclear').onclick = () => setS(() => { for (const k of Object.keys(S.f)) S.f[k] = ''; }, { list: true });
$('tgFilters').onclick = () => setS(() => { S.panels.filters = !S.panels.filters; });
$('tgInfo').onclick = () => setS(() => { S.panels.info = !S.panels.info; });
$('tgMidi').onclick = () => { stopListen(); setS(() => { S.panels.midi = false; }); };
const pick = (li) => { const p = PRESETS.find((x) => x.id === li.dataset.id); if (p) loadPreset(p); };
$('list').addEventListener('click', (e) => { const li = e.target.closest('li[data-id]'); if (li) pick(li); });
$('list').addEventListener('keydown', (e) => { const li = e.target.closest('li[data-id]'); if (!li) return;
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); pick(li); }
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); e.stopPropagation(); const n = e.key === 'ArrowDown' ? li.nextElementSibling : li.previousElementSibling; if (n && n.dataset.id) { n.focus(); pick(n); } } });
$('list').addEventListener('scroll', () => { S.scroll = Math.round($('list').scrollTop); save(); }, { passive: true });

const typing = (el) => el && (el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.tagName === 'TEXTAREA' || el.isContentEditable);
window.addEventListener('keydown', (e) => {
  if (typing(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.code === 'Space') { e.preventDefault(); if (!e.repeat) $('play').click(); }
  else if (e.code === 'ArrowLeft') { e.preventDefault(); step(-1); }
  else if (e.code === 'ArrowRight') { e.preventDefault(); step(1); }
  else if (e.code === 'KeyL') $('loop').click();
});
window.addEventListener('keyup', (e) => { if (e.code === 'Space' && !typing(e.target)) e.preventDefault(); });      // a focused button must not also click on Space
window.addEventListener('resize', () => { dirty = true; if (A) { chart.set(A); chart.draw(); } });

// ───────── files: MIDI uploads and dropped motion / judgement JSON ─────────
$('btnMidi').onclick = $('btnMidi2').onclick = () => $('fileMidi').click();
$('btnMotion').onclick = () => $('fileMotion').click();
$('fileMidi').onchange = () => { const f = $('fileMidi').files[0]; if (f) openMidi(f); $('fileMidi').value = ''; };
$('fileMotion').onchange = () => { handleFiles([...$('fileMotion').files]); $('fileMotion').value = ''; };
let dragDepth = 0;
window.addEventListener('dragenter', (e) => { if (![...(e.dataTransfer?.types || [])].includes('Files')) return; dragDepth++; $('dropveil').hidden = false; });
window.addEventListener('dragleave', () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $('dropveil').hidden = true; });
window.addEventListener('dragover', (e) => { e.preventDefault(); });
window.addEventListener('drop', (e) => { e.preventDefault(); dragDepth = 0; $('dropveil').hidden = true; handleFiles([...(e.dataTransfer?.files || [])]); });

const isMotion = (o) => o && typeof o === 'object' && (String(o.schema || '').startsWith('verify.motion') || (o.delta && o.names && o.kit));
const isJudgement = (o) => o && typeof o === 'object' && (String(o.schema || '').includes('judgement') || (Array.isArray(o.source) && o.tally));
async function handleFiles(files) {
  const mids = files.filter((f) => /\.midi?$/i.test(f.name)), jsons = files.filter((f) => /\.json$/i.test(f.name));
  if (!mids.length && !jsons.length) { if (files.length) toast('Drop a .mid file, or a .motion.json (and its .judgement.json).'); return; }
  if (mids.length) openMidi(mids[0]);
  let M = null, J = null, name = '';
  for (const f of jsons) { let o; try { o = JSON.parse(await f.text()); } catch { toast(`${f.name} is not valid JSON.`); continue; }
    if (isMotion(o)) { M = o; name = f.name; } else if (isJudgement(o)) J = o; else toast(`${f.name} is neither a motion nor a judgement file.`); }
  if (M) { S.clip = ''; markSelected(); save(); showClip({ M, J, meta: { title: M.title || name.replace(/\.json$/i, ''), file: name }, kind: 'file' }, true); toast(`Playing ${name}${J ? ' with its judgement' : ''}.`); }
  else if (J) {
    if (CL && CL.kind === 'file' && (!J.frames || J.frames === CL.M.frames)) { showClip({ ...CL, J }, false); toast('Judgement added: the lanes show hits and misses.'); }
    else toast('Drop the judgement together with its motion file.');
  }
}

// ---- the upload panel ----
let A = null;
const chart = new Chart($('chart'), (b0, b1, done) => { setRange(b0, b1); if (done) stopListen(); });
async function openMidi(file) {
  setS(() => { S.panels.midi = true; });
  try { A = analyse(parseSMF(await file.arrayBuffer()), file.name); }
  catch (e) { A = null; $('mbody').hidden = true; $('mempty').hidden = false; toast(`Could not read ${file.name}: ${e.message}`, 5000); return; }
  stopListen(); $('mempty').hidden = true; $('mbody').hidden = false; $('mtitle').textContent = `Your MIDI: ${file.name}`;
  const dropped = [...A.dropped.values()].reduce((a, b) => a + b, 0);
  $('mchips').innerHTML = [['tempo', `${Math.round(A.bpm)} bpm${A.tempoChanges ? ' (changes)' : ''}`], ['meter', A.sig + (A.sigChanges ? ' (changes)' : '')], ['bars', A.nbars], ['drum notes', A.notes.length], ['read from', A.channel]]
    .map(([k, v]) => `<span class="chip">${esc(k)} <b>${esc(v)}</b></span>`).join('') + (dropped ? `<span class="chip warn" title="pitches: ${esc([...A.dropped.keys()].join(', '))}">left out <b>${dropped}</b></span>` : '');
  $('mnote').textContent = (dropped ? `${dropped} notes are on pitches the solver leaves out (${[...A.dropped.keys()].slice(0, 8).join(', ')}): claps, extra percussion or non-drum parts. ` : '') +
    (A.sigChanges ? 'The meter changes in this file: the solver counts bars in the first meter. ' : '') + (A.notes.length ? '' : 'No drum notes found.');
  $('b0').max = $('b1').max = A.nbars; $('bof').textContent = `of ${A.nbars}`;
  chart.set(A); setRange(A.firstBar, Math.min(A.nbars, A.firstBar + 3));
  $('midi').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
function setRange(b0, b1) {
  if (!A) return; b0 = Math.max(1, Math.min(A.nbars, Math.round(b0) || 1)); b1 = Math.max(b0, Math.min(A.nbars, Math.round(b1) || b0));
  chart.sel = [b0, b1]; $('b0').value = b0; $('b1').value = b1; chart.draw();
  const q = (s) => (/^[\w.\-/]+$/.test(s) ? s : `'${s.replace(/'/g, "'\\''")}'`), stem = A.name.replace(/\.midi?$/i, '');
  $('cmd').textContent = `midi2motion solve ${q(A.name)} --bars ${b0}-${b1}${A.meter !== 4 ? ` --meter ${A.meter}` : ''} --out ${q(stem + '.motion.json')}`;
  const n = b1 - b0 + 1, inR = A.notes.filter((x) => x.bar >= b0 && x.bar < b1 + 1).length;
  const lo = n <= 4 ? Math.max(1, Math.round(n * 0.5)) : Math.round(2 + (n - 4) * 1.75), hi = n <= 4 ? Math.ceil(n * 0.75) : Math.round(3 + (n - 4) * 6);
  $('est').textContent = `${n} bar${n > 1 ? 's' : ''} · ${inR} notes · solves in about ${lo === hi ? lo : `${lo}–${hi}`} min${n > 8 ? ' (long: try 8 bars or fewer)' : ''}`;
}
$('b0').onchange = () => setRange(+$('b0').value, Math.max(+$('b0').value, +$('b1').value));
$('b1').onchange = () => setRange(Math.min(+$('b0').value, +$('b1').value), +$('b1').value);
$('copy').onclick = async () => {
  const s = $('cmd').textContent; let ok = false;
  try { await navigator.clipboard.writeText(s); ok = true; } catch { try { const r = document.createRange(); r.selectNodeContents($('cmd')); const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r); ok = document.execCommand('copy'); } catch { /* select it for a manual copy */ } }
  $('copy').textContent = ok ? 'Copied' : 'Select + copy'; setTimeout(() => { $('copy').textContent = 'Copy'; }, 1600);
};
// listen to the picked bars with the kit (no motion: a check that the range is the part you want)
$('listen').onclick = () => {
  if (listen) { stopListen(); return; } if (!A || !A.notes.length) return;
  if (!drums.unlock()) { toast('This browser has no WebAudio.'); return; } if (S.sound.muted) setS(() => { S.sound.muted = false; drums.setMuted(false); });
  setPlay(false); dirty = true;
  const [b0, b1] = chart.sel, t0 = A.barStart(b0), t1 = A.barStart(b1 + 1), list = A.notes.filter((n) => n.bar >= b0 && n.bar < b1 + 1);
  drums.preload([...new Set(list.map((n) => n.row + '\u0000' + n.zone))].map((k) => k.split('\u0000')));
  listen = { c0: drums.ac.currentTime + 0.15, t0, t1, list, i: 0, b0, b1 }; $('listen').textContent = 'Stop';
};
function listenTick() {
  const L = listen, now = drums.ac.currentTime - L.c0 + L.t0;
  while (L.i < L.list.length && L.list[L.i].t < now + 0.12) { const n = L.list[L.i++]; drums.hit(n.row, n.vel, n.zone, Math.max(0, n.t - now)); }
  const span = L.t1 - L.t0; chart.head = L.b0 + Math.max(0, Math.min(1, (now - L.t0) / span)) * (L.b1 - L.b0 + 1); chart.draw();
  if (now > L.t1 + 0.2) stopListen();
}
function stopListen() { if (!listen) return; listen = null; chart.head = null; $('listen').textContent = 'Listen'; chart.draw(); }

// ───────── boot ─────────
applyUI();
renderInfo();
onHashChange(() => {
  applyUI(); renderList();
  if (stage) { if (S.cam === 'custom' && S.camPos && S.camTgt) stage.setCamRaw(S.camPos, S.camTgt); else stage.setCam(S.cam); }
  const p = PRESETS.find((x) => x.id === S.clip); if (p && (!CL || CL.meta !== p)) loadPreset(p);
  save(true);
});

const manifestReady = (async () => {
  try { MAN = await getJSON(url(MANIFEST)); PRESETS = (MAN.presets || []).filter((p) => p && p.id && p.motion); }
  catch { MAN = false; PRESETS = []; }
  fillFilterOptions(); applyUI(); renderList(); $('list').scrollTop = S.scroll || 0;
})();

(async () => {      // the kit: ?kit= (a local install points at its own drums) → the first of kits/index.json → the manifest's kit → the synth
  let dir = Q.get('kit');
  if (!dir) { try { const ix = await getJSON(url('kits/index.json')); const L = Array.isArray(ix) ? ix : ix.kits || []; const k = L[0]; if (k) dir = typeof k === 'string' ? `kits/${k}/` : k.path || `kits/${k.id}/`; } catch { /* no index */ } }
  if (!dir) { await manifestReady; if (MAN && MAN.kit) dir = typeof MAN.kit === 'string' ? `kits/${MAN.kit}/` : MAN.kit.path || `kits/${MAN.kit.id}/`; }
  if (!dir) { $('kitname').textContent = 'synth'; $('kitname').title = 'No sample kit found: a simple synth plays'; return; }
  try { const k = await drums.loadKit(url(dir)); $('kitname').textContent = k.name || k.id || 'kit'; $('kitname').title = [k.name, k.license, k.credit].filter(Boolean).join(' · '); if (CL) { drums.preload(CL.snd.map((n) => [n.row, n.zone])); renderInfo(); } }
  catch { $('kitname').textContent = 'synth'; $('kitname').title = `Could not load the kit at ${dir}: a simple synth plays`; }
})();


(async () => {
  try {
    stage = await createStage($('stage'), url(GLB), (f) => { $('loadmsg').textContent = `Loading the drummer… ${Math.round(f * 100)} %`; });
  } catch (e) { $('loadmsg').textContent = 'Could not load the drummer model. Reload to try again.'; $('loading').querySelector('.spin').hidden = true; toast('The 3D model did not load: ' + e.message, 6000); return; }
  $('loading').hidden = true; stage.setXray(S.ov.xray);
  if (S.cam === 'custom' && S.camPos && S.camTgt) stage.setCamRaw(S.camPos, S.camTgt); else stage.setCam(CAMS[S.cam] ? S.cam : 'perf');
  stage.controls.addEventListener('start', () => { if (S.orbit) setS(() => { S.orbit = false; }); });
  stage.controls.addEventListener('change', () => { dirty = true; });
  stage.controls.addEventListener('end', () => { const c = stage.getCam(); setS(() => { S.cam = 'custom'; S.camPos = c.pos; S.camTgt = c.tgt; }); });
  new ResizeObserver(() => { dirty = true; }).observe($('stagewrap'));
  await manifestReady;
  if (pendingClip) { showClip(...pendingClip); pendingClip = null; }
  else { const p = PRESETS.find((x) => x.id === S.clip) || PRESETS.filter(matches)[0] || PRESETS[0]; if (p) await loadPreset(p); else { $('empty').hidden = false; renderInfo(); } }
  window.__app.ready = true;
})();
requestAnimationFrame(tick);

window.__app = { ready: false, S, get clip() { return CL; }, get t() { return Tn; }, get playing() { return playing; }, seek, setPlay, get presets() { return PRESETS; }, get midi() { return A; }, cmd: () => $('cmd').textContent, cam: () => stage && stage.getCam(), drums };
