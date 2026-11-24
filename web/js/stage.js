// stage.js: the three.js stage. The android GLB loads once; setClip() swaps the motion and rebuilds the kit it carries.
// The camera is never touched by a clip change. Pose, kit and stick code from the library player (library/performers/drums/player).
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const dec16 = (s) => { const b = atob(s || ''), u = new Uint8Array(b.length); for (let i = 0; i < b.length; i++) u[i] = b.charCodeAt(i); return new Int16Array(u.buffer); };
const LIMBCOL = { L: '#ff7ac4', R: '#5cc8ff' };
// [eye, target, vfov] in the solver's (Blender) metres: x right, y forward (negative = toward the camera), z up
export const CAMS = {
  perf: [[0.6, -2.9, 2.75], [-0.05, -0.45, 0.8], 34], grip: [[-0.62, -1.5, 1.18], [0.02, -0.55, 0.84], 30], side: [[-1.3, -0.72, 1.42], [0.0, -0.55, 0.84], 30],
  feet: [[1.25, -1.35, 0.42], [0.05, -0.5, 0.14], 34], top: [[0, -0.5, 4.6], [0, -0.45, 0.7], 34],
};
const B = (x, y, z) => new THREE.Vector3(x, z, -y), Bv = (a) => B(a[0], a[1], a[2]);
const Cm = new THREE.Matrix4().set(1, 0, 0, 0, 0, 0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1), Ci = Cm.clone().invert(), UP = new THREE.Vector3(0, 1, 0);
const STICK_PROFILE = [[0, 0], [0.0068, 0], [0.00725, 0.004], [0.00725, 0.62], [0.0052, 0.86], [0.0034, 0.955], [0.0042, 0.975], [0.0036, 0.995], [0, 1]].map(([r, y]) => new THREE.Vector2(r, y));

export async function createStage(el, glbUrl, onProgress) {
  const renderer = new THREE.WebGLRenderer({ antialias: true }); renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1)); el.appendChild(renderer.domElement);
  const scene = new THREE.Scene(); scene.background = new THREE.Color('#101118');
  const camera = new THREE.PerspectiveCamera(34, 16 / 9, 0.03, 200);
  const controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = false;
  scene.add(new THREE.HemisphereLight('#ffffff', '#383a4c', 1.5)); const sun = new THREE.DirectionalLight('#ffffff', 1.6); sun.position.set(1.5, 4, 3); scene.add(sun);
  scene.add(new THREE.GridHelper(8, 32, '#33364a', '#1d1f2b'));

  const gltf = await new GLTFLoader().loadAsync(glbUrl, (e) => { if (onProgress && e.total) onProgress(e.loaded / e.total); });
  const root = gltf.scene; scene.add(root); root.updateMatrixWorld(true);
  const bones = {}, rest = new Map(); let mesh = null;
  root.traverse((o) => { if (o.isBone) bones[o.name] = o; if (o.isSkinnedMesh) mesh = o; });
  for (const b of Object.values(bones)) { rest.set(b, b.matrixWorld.clone()); b.matrixAutoUpdate = false; b.matrixWorldAutoUpdate = false; }
  if (!mesh) throw new Error('no skinned mesh in the android GLB');
  const skin = new THREE.MeshStandardMaterial({ color: '#d9e4ea', roughness: 0.55, metalness: 0.05 }); mesh.material = skin; mesh.frustumCulled = false;

  const stickM = {}; for (const h of ['L', 'R']) { const m = new THREE.Mesh(new THREE.LatheGeometry(STICK_PROFILE, 14), new THREE.MeshStandardMaterial({ color: '#e3b87a', roughness: 0.6, emissive: LIMBCOL[h], emissiveIntensity: 0.25 })); m.visible = false; scene.add(m); stickM[h] = m; }
  const placeStick = (m, a, b) => { m.position.copy(a); m.scale.set(1, a.distanceTo(b), 1); m.quaternion.setFromUnitVectors(UP, b.clone().sub(a).normalize()); };
  const tmp = new THREE.Matrix4(), Dm = new THREE.Matrix4();
  let C = null;        // the clip on stage

  function disposeKit() { if (!C) return; scene.remove(C.sets); C.sets.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); }); }

  function setClip(M) {
    const names = M.names || [], NB = names.length;
    const list = names.map((n) => { const b = bones[n.replace(/\./g, '')] || bones[n]; if (!b) throw new Error('this motion names a bone the android does not have: ' + n); return { b, rest: rest.get(b) }; });
    disposeKit();
    for (const [b, r] of rest) b.matrixWorld.copy(r);          // bones the new clip does not drive go back to rest
    const K = M.kit, PIECE = {}, sets = new THREE.Group(); scene.add(sets); let hatTop = null;
    const cyl = (r1, r2, h, color, parent, y = 0, o = {}) => { const g = new THREE.CylinderGeometry(r1, r2, h, o.segs || 32); g.translate(0, y - h / 2, 0); const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color, roughness: o.rough ?? 0.5, metalness: o.metal ?? 0.1, side: THREE.DoubleSide, transparent: true, opacity: 0.85, emissive: '#000000' })); parent.add(m); return m; };
    for (const p of K.pieces) {
      const g = new THREE.Group(); g.position.copy(Bv(p.c)); g.quaternion.setFromUnitVectors(UP, Bv(p.n).normalize()); sets.add(g); const ms = [];
      if (p.kind === 'cymbal') {
        ms.push(cyl(p.id === 'ride' ? K.bell.r : 0.035, p.r, 0.022, '#d4a94a', g, p.id === 'hat' ? 0.012 : 0, { metal: 0.8, rough: 0.3, segs: 48 }));
        if (p.id === 'hat') { hatTop = g; g.userData.base = g.position.clone(); const bot = cyl(p.r, 0.035, 0.02, '#b8923c', sets, 0, { metal: 0.8, rough: 0.3, segs: 48 }); bot.position.copy(Bv(p.c)).add(new THREE.Vector3(0, -0.012, 0)); ms.push(bot); }
        if (p.id === 'ride') ms.push(cyl(0.014, K.bell.r, K.bell.h, '#e8c060', g, K.bell.h, { metal: 0.8, rough: 0.3 }));
        const pole = cyl(0.008, 0.008, p.c[2], '#8a8c96', sets, 0, { segs: 8 }); pole.position.set(p.c[0], p.c[2], -p.c[1]);
      } else { ms.push(cyl(p.r, p.r, p.depth, p.kind === 'kick' ? '#1d2050' : '#2a3080', g, -0.004)); ms.push(cyl(p.r * 0.965, p.r * 0.965, 0.004, '#deded6', g, 0)); ms.push(cyl(p.r + 0.007, p.r + 0.007, 0.02, '#b9bcc6', g, 0.004, { metal: 0.7 })); }
      PIECE[p.id] = ms;
    }
    cyl(0.17, 0.165, 0.08, '#15151c', sets, K.seat_z).position.set(0, 0, -K.seat_y);
    const board = (a, dx, len) => { const piv = new THREE.Group(); piv.position.copy(B(a[0] + dx, a[1] + 0.05, 0.012)); sets.add(piv); const g = new THREE.BoxGeometry(0.085, 0.010, len); g.translate(0, 0, len / 2); piv.add(new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: '#b9bcc6', metalness: 0.6, roughness: 0.4 }))); return piv; };
    const kf = (M.kick_foot || 'RF')[0], hf = (M.hat_foot || 'LF')[0], kickBoard = board(K.ankle[kf], 0, 0.29), hatBoard = board(K.ankle[hf], 0.02, 0.27);
    PIECE.hatped = [hatBoard.children[0]]; PIECE.kick = (PIECE.kick || []).concat([kickBoard.children[0]]);
    C = { M, K, NB, list, sets, PIECE, hatTop, kickBoard, hatBoard, FPS: M.fps, NF: M.frames, DQ: dec16(M.delta), ST: dec16(M.sticks), HAT: dec16(M.hat30), KP: dec16(M.kick_plate), HP: dec16(M.hat_plate) };
    for (const h of ['L', 'R']) stickM[h].visible = C.ST.length > 0;
  }

  function pose(f) { const { DQ, NB, list } = C, base = f * NB * 12; for (let i = 0; i < NB; i++) { const o = base + i * 12, r = (k) => DQ[o + k] / 32000, t = (k) => DQ[o + k] / 10000; Dm.set(r(0), r(1), r(2), t(3), r(4), r(5), r(6), t(7), r(8), r(9), r(10), t(11), 0, 0, 0, 1); tmp.copy(Cm).multiply(Dm).multiply(Ci); list[i].b.matrixWorld.multiplyMatrices(tmp, list[i].rest); } }
  const stickPt = (f, h, k) => { const o = (f * 2 + (h === 'L' ? 0 : 1)) * 6 + k * 3, S = C.ST; return B(S[o] / 1e4, S[o + 1] / 1e4, S[o + 2] / 1e4); };

  function resize() {
    const w = el.clientWidth, h = el.clientHeight, pr = renderer.getPixelRatio();
    if (w && h && (renderer.domElement.width !== Math.floor(w * pr) || renderer.domElement.height !== Math.floor(h * pr))) { renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
  }
  // t in seconds; flash = {pieceId: 0..1}
  function draw(t, flash) {
    resize();
    if (C) {
      const f = Math.max(0, Math.min(C.NF - 1, Math.round(t * C.FPS))); pose(f);
      if (C.ST.length) for (const h of ['L', 'R']) placeStick(stickM[h], stickPt(f, h, 0), stickPt(f, h, 1));
      const K = C.K; if (C.hatTop && C.HAT.length) C.hatTop.position.copy(C.hatTop.userData.base).add(new THREE.Vector3(0, K.hat_gap[0] + (K.hat_gap[1] - K.hat_gap[0]) * C.HAT[f] / 1e4, 0));
      if (C.KP.length) C.kickBoard.rotation.x = -THREE.MathUtils.degToRad(C.KP[f] / 100);
      if (C.HP.length) C.hatBoard.rotation.x = -THREE.MathUtils.degToRad(C.HP[f] / 100);
      for (const [id, ms] of Object.entries(C.PIECE)) { const a = (flash && flash[id]) || 0; for (const m of ms) { m.material.emissive.setRGB(1, 0.72, 0.35); m.material.emissiveIntensity = a; } }
    }
    renderer.render(scene, camera);
  }

  function setCam(name) { const [e, t, fov] = CAMS[name] || CAMS.perf; camera.fov = fov; camera.updateProjectionMatrix(); camera.position.copy(Bv(e)); controls.target.copy(Bv(t)); controls.update(); }
  function setCamRaw(pos, tgt) { camera.fov = 34; camera.updateProjectionMatrix(); camera.position.fromArray(pos); controls.target.fromArray(tgt); controls.update(); }
  const getCam = () => ({ pos: camera.position.toArray().map((x) => +x.toFixed(3)), tgt: controls.target.toArray().map((x) => +x.toFixed(3)) });
  function orbit(dt) { const t = controls.target, p = camera.position.clone().sub(t); p.applyAxisAngle(UP, dt * 0.35); camera.position.copy(t).add(p); controls.update(); }
  function setXray(on) { skin.transparent = on; skin.opacity = on ? 0.5 : 1; skin.depthWrite = !on; skin.needsUpdate = true; }
  return { setClip, draw, setCam, setCamRaw, getCam, orbit, setXray, controls, renderer, get clip() { return C; } };
}
