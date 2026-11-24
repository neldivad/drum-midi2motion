// stage.ts: the three.js stage. The android GLB loads once; setClip() swaps the motion and rebuilds the kit it carries.
// The camera is never touched by a clip change. Pose, kit and stick code from the library player (library/performers/drums/player).
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
// Drawing is on demand (the player calls draw() only when something changed). The canvas fills its box by CSS; its drawing buffer follows
// the box through a ResizeObserver, debounced, so dragging a panel handle never reallocates the buffer on every pointer move.

const dec16 = (s: string) => { const b = atob(s || ''), u = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return new Int16Array(u.buffer); };
const LIMBCOL = { L: '#ff7ac4', R: '#5cc8ff' };
// [eye, target, vfov] in the solver's (Blender) metres: x right, y forward (negative = toward the camera), z up
export const CAMS: Record<string, [number[], number[], number]> = {
  perf: [[0.6, -2.9, 2.75], [-0.05, -0.45, 0.8], 34], grip: [[-0.62, -1.5, 1.18], [0.02, -0.55, 0.84], 30], side: [[-1.3, -0.72, 1.42], [0.0, -0.55, 0.84], 30],
  feet: [[1.25, -1.35, 0.42], [0.05, -0.5, 0.14], 34], top: [[0, -0.5, 4.6], [0, -0.45, 0.7], 34],
};
const B = (x: number, y: number, z: number) => new THREE.Vector3(x, z, -y), Bv = (a: number[]) => B(a[0], a[1], a[2]);
const Cm = new THREE.Matrix4().set(1, 0, 0, 0, 0, 0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1), Ci = Cm.clone().invert(), UP = new THREE.Vector3(0, 1, 0);
const STICK_PROFILE = [[0, 0], [0.0068, 0], [0.00725, 0.004], [0.00725, 0.62], [0.0052, 0.86], [0.0034, 0.955], [0.0042, 0.975], [0.0036, 0.995], [0, 1]].map(([r, y]) => new THREE.Vector2(r, y));

export type Stage = Awaited<ReturnType<typeof createStage>>;
export async function createStage(glbUrl: string, onProgress?: (f: number) => void, onResized?: () => void) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' }); const prCap = Math.min(1.5, devicePixelRatio || 1); renderer.setPixelRatio(prCap);
  const cvs = renderer.domElement; cvs.style.width = '100%'; cvs.style.height = '100%'; cvs.style.display = 'block'; cvs.style.touchAction = 'none';
  let el: HTMLElement | null = null, ro: ResizeObserver | null = null, rT: any = 0, sized = false;
  const scene = new THREE.Scene(); scene.background = new THREE.Color('#101118');
  const camera = new THREE.PerspectiveCamera(34, 16 / 9, 0.03, 200);
  const controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = false;
  scene.add(new THREE.HemisphereLight('#ffffff', '#383a4c', 1.5)); const sun = new THREE.DirectionalLight('#ffffff', 1.6); sun.position.set(1.5, 4, 3); scene.add(sun);
  scene.add(new THREE.GridHelper(8, 32, '#33364a', '#1d1f2b'));

  const gltf = await new GLTFLoader().loadAsync(glbUrl, (e) => { if (onProgress && e.total) onProgress(e.loaded / e.total); });
  const root = gltf.scene; scene.add(root); root.updateMatrixWorld(true);
  const bones: Record<string, any> = {}, rest = new Map<any, THREE.Matrix4>(); let mesh: any = null;
  root.traverse((o: any) => { if (o.isBone) bones[o.name] = o; if (o.isSkinnedMesh) mesh = o; });
  for (const b of Object.values(bones)) { rest.set(b, b.matrixWorld.clone()); b.matrixAutoUpdate = false; b.matrixWorldAutoUpdate = false; }
  if (!mesh) throw new Error('no skinned mesh in the android GLB');
  const skin = new THREE.MeshStandardMaterial({ color: '#d9e4ea', roughness: 0.55, metalness: 0.05 }); mesh.material = skin; mesh.frustumCulled = false;

  const stickM: Record<string, THREE.Mesh> = {}; for (const h of ['L', 'R']) { const m = new THREE.Mesh(new THREE.LatheGeometry(STICK_PROFILE, 14), new THREE.MeshStandardMaterial({ color: '#e3b87a', roughness: 0.6, emissive: LIMBCOL[h], emissiveIntensity: 0.25 })); m.visible = false; scene.add(m); stickM[h] = m; }
  const placeStick = (m: THREE.Mesh, a: THREE.Vector3, b: THREE.Vector3) => { m.position.copy(a); m.scale.set(1, a.distanceTo(b), 1); m.quaternion.setFromUnitVectors(UP, vD.subVectors(b, a).normalize()); };
  const tmp = new THREE.Matrix4(), Dm = new THREE.Matrix4(), vA = new THREE.Vector3(), vB = new THREE.Vector3(), vD = new THREE.Vector3(), vP = new THREE.Vector3(), qQ = new THREE.Quaternion(), ONE = new THREE.Vector3(1, 1, 1), qOut = new Float32Array(4), hatOff = new THREE.Vector3(), orbV = new THREE.Vector3(), HANDS = ['L', 'R'] as const;
  let C: any = null;        // the clip on stage

  function disposeKit() { if (!C) return; scene.remove(C.sets); C.sets.traverse((o: any) => { if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); }); }

  function setClip(M: any) {
    const names = M.names || [], NB = names.length;
    const list = names.map((n: string) => { const b = bones[n.replace(/\./g, '')] || bones[n]; if (!b) throw new Error('this motion names a bone the android does not have: ' + n); return { b, rest: rest.get(b) }; });
    disposeKit();
    for (const [b, r] of rest) b.matrixWorld.copy(r);          // bones the new clip does not drive go back to rest
    const K = M.kit, PIECE: Record<string, any[]> = {}, sets = new THREE.Group(); scene.add(sets); let hatTop: any = null;
    const cyl = (r1: number, r2: number, h: number, color: string, parent: THREE.Object3D, y = 0, o: any = {}) => { const g = new THREE.CylinderGeometry(r1, r2, h, o.segs || 32); g.translate(0, y - h / 2, 0); const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color, roughness: o.rough ?? 0.5, metalness: o.metal ?? 0.1, side: THREE.DoubleSide, transparent: true, opacity: 0.85, emissive: '#000000' })); parent.add(m); return m; };
    for (const p of K.pieces) {
      const g = new THREE.Group(); g.position.copy(Bv(p.c)); g.quaternion.setFromUnitVectors(UP, Bv(p.n).normalize()); sets.add(g); const ms: THREE.Mesh[] = [];
      if (p.kind === 'cymbal') {
        ms.push(cyl(p.id === 'ride' ? K.bell.r : 0.035, p.r, 0.022, '#d4a94a', g, p.id === 'hat' ? 0.012 : 0, { metal: 0.8, rough: 0.3, segs: 48 }));
        if (p.id === 'hat') { hatTop = g; g.userData.base = g.position.clone(); const bot = cyl(p.r, 0.035, 0.02, '#b8923c', sets, 0, { metal: 0.8, rough: 0.3, segs: 48 }); bot.position.copy(Bv(p.c)).add(new THREE.Vector3(0, -0.012, 0)); ms.push(bot); }
        if (p.id === 'ride') ms.push(cyl(0.014, K.bell.r, K.bell.h, '#e8c060', g, K.bell.h, { metal: 0.8, rough: 0.3 }));
        const pole = cyl(0.008, 0.008, p.c[2], '#8a8c96', sets, 0, { segs: 8 }); pole.position.set(p.c[0], p.c[2], -p.c[1]);
      } else { ms.push(cyl(p.r, p.r, p.depth, p.kind === 'kick' ? '#1d2050' : '#2a3080', g, -0.004)); ms.push(cyl(p.r * 0.965, p.r * 0.965, 0.004, '#deded6', g, 0)); ms.push(cyl(p.r + 0.007, p.r + 0.007, 0.02, '#b9bcc6', g, 0.004, { metal: 0.7 })); }
      PIECE[p.id] = ms;
    }
    cyl(0.17, 0.165, 0.08, '#15151c', sets, K.seat_z).position.set(0, 0, -K.seat_y);
    const board = (a: number[], dx: number, len: number) => { const piv = new THREE.Group(); piv.position.copy(B(a[0] + dx, a[1] + 0.05, 0.012)); sets.add(piv); const g = new THREE.BoxGeometry(0.085, 0.010, len); g.translate(0, 0, len / 2); piv.add(new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: '#b9bcc6', metalness: 0.6, roughness: 0.4 }))); return piv; };
    const kf = (M.kick_foot || 'RF')[0], hf = (M.hat_foot || 'LF')[0], kickBoard = board(K.ankle[kf], 0, 0.29), hatBoard = board(K.ankle[hf], 0.02, 0.27);
    PIECE.hatped = [hatBoard.children[0]]; PIECE.kick = (PIECE.kick || []).concat([kickBoard.children[0]]);
    // decoded once per clip: per frame and bone the delta as position + quaternion (three.js space), sticks as float points, the pedal tracks as floats
    const NF = M.frames, DQ = dec16(M.delta), QP = new Float32Array(NF * NB * 7), pos = new THREE.Vector3(), quat = new THREE.Quaternion(), scl = new THREE.Vector3();
    for (let f = 0; f < NF; f++) for (let i = 0; i < NB; i++) { const o = (f * NB + i) * 12, r = (k: number) => DQ[o + k] / 32000, t = (k: number) => DQ[o + k] / 10000;
      Dm.set(r(0), r(1), r(2), t(3), r(4), r(5), r(6), t(7), r(8), r(9), r(10), t(11), 0, 0, 0, 1); tmp.copy(Cm).multiply(Dm).multiply(Ci); tmp.decompose(pos, quat, scl);
      const q = (f * NB + i) * 7; QP[q] = quat.x; QP[q + 1] = quat.y; QP[q + 2] = quat.z; QP[q + 3] = quat.w; QP[q + 4] = pos.x; QP[q + 5] = pos.y; QP[q + 6] = pos.z; }
    const S16 = dec16(M.sticks), ST = new Float32Array(S16.length); for (let j = 0; j < S16.length; j += 3) { ST[j] = S16[j] / 1e4; ST[j + 1] = S16[j + 2] / 1e4; ST[j + 2] = -S16[j + 1] / 1e4; }      // Blender (x, y, z) -> three (x, z, -y)
    const f32 = (s16: string, k: number) => Float32Array.from(dec16(s16), (v) => v / k);
    C = { M, K, NB, list, sets, PIECE, hatTop, kickBoard, hatBoard, FPS: M.fps, NF, QP, ST, HAT: f32(M.hat30, 1e4), KP: f32(M.kick_plate, 100), HP: f32(M.hat_plate, 100), contact: new Uint8Array(NF) };
    for (const h of HANDS) stickM[h].visible = C.ST.length > 0;
  }
  // the frames where something is struck: the blend snaps to them so a hit is never blended away
  function setContacts(times: number[]) { if (!C) return; C.contact.fill(0); for (const t of times) { const f = Math.round(t * C.FPS); if (f >= 0 && f < C.NF) C.contact[f] = 1; } }

  // the pose between frames f0 and f0 + 1: slerp the rotations, lerp the positions (no allocation)
  function pose(f0: number, f1: number, a: number) { const { QP, NB, list } = C, b0 = f0 * NB * 7, b1 = f1 * NB * 7;
    for (let i = 0; i < NB; i++) { const o0 = b0 + i * 7, o1 = b1 + i * 7; THREE.Quaternion.slerpFlat(qOut as any, 0, QP as any, o0, QP as any, o1, a); qQ.set(qOut[0], qOut[1], qOut[2], qOut[3]);
      vP.set(QP[o0 + 4] + (QP[o1 + 4] - QP[o0 + 4]) * a, QP[o0 + 5] + (QP[o1 + 5] - QP[o0 + 5]) * a, QP[o0 + 6] + (QP[o1 + 6] - QP[o0 + 6]) * a);
      tmp.compose(vP, qQ, ONE); list[i].b.matrixWorld.multiplyMatrices(tmp, list[i].rest); } }
  const stickPt = (out: THREE.Vector3, f0: number, f1: number, a: number, h: string, k: number) => { const S = C.ST, o0 = (f0 * 2 + (h === 'L' ? 0 : 1)) * 6 + k * 3, o1 = (f1 * 2 + (h === 'L' ? 0 : 1)) * 6 + k * 3; return out.set(S[o0] + (S[o1] - S[o0]) * a, S[o0 + 1] + (S[o1 + 1] - S[o0 + 1]) * a, S[o0 + 2] + (S[o1 + 2] - S[o0 + 2]) * a); };
  const lerpT = (arr: Float32Array, f0: number, f1: number, a: number) => arr[f0] + (arr[f1] - arr[f0]) * a;
  const tip = new Float32Array(6);      // the last drawn tips (L xyz, R xyz): a debug read for the continuity check

  // the buffer follows the box: the first size at once, later ones 120 ms after the last change (the CSS stretches the old buffer meanwhile)
  function applySize() { if (!el) return; const w = el.clientWidth, h = el.clientHeight; if (!w || !h) return; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); sized = true; onResized && onResized(); }
  function attach(box: HTMLElement) {
    if (el === box) return; if (ro) ro.disconnect(); el = box; box.appendChild(cvs); sized = false;
    ro = new ResizeObserver(() => { clearTimeout(rT); if (!sized) applySize(); else rT = setTimeout(applySize, 120); }); ro.observe(box);
  }
  // t in seconds; flash = {pieceId: 0..1}; snap = half a display frame in clip seconds (0 = no snapping, e.g. paused: show t exactly)
  let renderMs = 0, slowN = 0, fastN = 0;
  function draw(t: number, flash: Record<string, number> | null, snap = 0) {
    if (!sized) applySize();
    if (C) {
      const x = Math.max(0, Math.min(C.NF - 1, t * C.FPS)); let f0 = Math.floor(x), a = x - f0;
      if (snap > 0) { const h = snap * C.FPS; if (C.contact[f0] && x - f0 <= h && C.lastSnap !== f0) { a = 0; C.lastSnap = f0; } else if (f0 + 1 < C.NF && C.contact[f0 + 1] && f0 + 1 - x <= h && C.lastSnap !== f0 + 1) { f0 += 1; a = 0; C.lastSnap = f0; } } else C.lastSnap = -1;      // each contact is snapped to once      // the display frame nearest a contact shows it exactly
      const f1 = Math.min(C.NF - 1, f0 + 1); if (f1 === f0) a = 0;
      pose(f0, f1, a);
      if (C.ST.length) for (const h of HANDS) { stickPt(vA, f0, f1, a, h, 0); stickPt(vB, f0, f1, a, h, 1); placeStick(stickM[h], vA, vB); const j = h === 'L' ? 0 : 3; tip[j] = vB.x; tip[j + 1] = vB.y; tip[j + 2] = vB.z; }
      const K = C.K; if (C.hatTop && C.HAT.length) C.hatTop.position.copy(C.hatTop.userData.base).add(hatOff.set(0, K.hat_gap[0] + (K.hat_gap[1] - K.hat_gap[0]) * lerpT(C.HAT, f0, f1, a), 0));
      if (C.KP.length) C.kickBoard.rotation.x = -THREE.MathUtils.degToRad(lerpT(C.KP, f0, f1, a));
      if (C.HP.length) C.hatBoard.rotation.x = -THREE.MathUtils.degToRad(lerpT(C.HP, f0, f1, a));
      for (const id in C.PIECE) { const v = (flash && flash[id]) || 0, ms = C.PIECE[id]; for (let k = 0; k < ms.length; k++) { const m = ms[k].material; if (m.emissiveIntensity !== v) { m.emissive.setRGB(1, 0.72, 0.35); m.emissiveIntensity = v; } } }
    }
    const t0 = performance.now(); renderer.render(scene, camera); const ms = performance.now() - t0; renderMs = renderMs * 0.9 + ms * 0.1;
    // adaptive pixel ratio: down to 1 (then 0.75 on very slow GPUs) when renders run long, back up to the cap when they are cheap
    if (renderMs > 14) { if (++slowN > 30) { const pr = renderer.getPixelRatio(), next = pr > 1 ? 1 : pr > 0.75 ? 0.75 : pr; if (next !== pr) renderer.setPixelRatio(next); slowN = 0; renderMs = 8; } } else slowN = 0;
    if (renderMs < 5) { if (++fastN > 120) { const pr = renderer.getPixelRatio(); if (pr < prCap) renderer.setPixelRatio(Math.min(prCap, pr + 0.25)); fastN = 0; } } else fastN = 0;
  }

  function setCam(name: string) { const [e, t, fov] = CAMS[name] || CAMS.perf; camera.fov = fov; camera.updateProjectionMatrix(); camera.position.copy(Bv(e)); controls.target.copy(Bv(t)); controls.update(); }
  function setCamRaw(pos: number[], tgt: number[]) { camera.fov = 34; camera.updateProjectionMatrix(); camera.position.fromArray(pos); controls.target.fromArray(tgt); controls.update(); }
  const getCam = () => ({ pos: camera.position.toArray().map((x) => +x.toFixed(3)), tgt: controls.target.toArray().map((x) => +x.toFixed(3)) });
  function orbit(dt: number) { const t = controls.target, p = orbV.copy(camera.position).sub(t); p.applyAxisAngle(UP, dt * 0.35); camera.position.copy(t).add(p); controls.update(); }
  function setXray(on: boolean) { skin.transparent = on; skin.opacity = on ? 0.5 : 1; skin.depthWrite = !on; skin.needsUpdate = true; }
  return { attach, canvas: cvs, setClip, setContacts, draw, setCam, setCamRaw, getCam, orbit, setXray, controls, renderer, tip, get renderMs() { return renderMs; }, get clip() { return C; } };
}
