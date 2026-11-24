#!/usr/bin/env python3
# midi2motion: vendored from nelvids/lab/wrapped/3d/2026-11-16-rig-foundations/tools/bake.py (a wrapped lab, read-only source). Solver behaviour unchanged; only data paths and the lab command line were changed.
"""bake.py: one solved arm (arm_rig.ArmRig.solve) -> a `perf`: every channel at 120 Hz, the points, the driving skeleton's local quaternions
(VRM names + twist bones), the stick, the fingers, and the android's bone deltas on every 4th frame (what Blender and the inspector apply).

Also old_channels(): the SAME joint decomposition run on an old bake's arm (its shoulder, elbow, wrist and hand matrix per frame), so the
inspector can draw old and new on one graph. In the old rig the forearm has no roll, so the twist it reports sits at the wrist joint.
"""
import json, math, pathlib, sys
import numpy as np
from scipy.spatial.transform import Rotation as Rot
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import arm_rig as AR
from arm_rig import CFG, HZ, rx, ry, rv

EVERY = CFG["render_every"]


def _quat(M):
    """rotation matrices (N,3,3) -> quaternions (N,4) x,y,z,w kept in one hemisphere frame to frame (C-CONT-4)"""
    q = Rot.from_matrix(M).as_quat()
    for i in range(1, len(q)):
        if q[i] @ q[i - 1] < 0: q[i] = -q[i]
    return q


def assemble(rig, out, W_plan, Hm, curls, spread, static, kind, ident, W_raw=None, stick=None, thumb_abd=0.0, events=(), contacts=(), mode=None, extra=None):
    N = len(W_plan); s = rig.s; sg = rig.sg; ch = dict(out["ch"]); K = out["K"]; Hw = out["Hw"]; pts = out["pts"]; r = np.radians
    fd = np.array([AR.ArmRig.finger_deg(c) for c in curls])                                    # (N, 5, 3)
    for i, fn in enumerate(AR.FINGERS):
        for j, jn in enumerate(("mcp", "pip", "dip")): ch[f"{fn}_{jn}"] = fd[:, i, j]
    tips = {fn: np.zeros((N, 3)) for fn in AR.FINGERS}; knuck = np.zeros((N, 3)); delta = []; Ks = [{k: K[k][f] for k in ("S", "U", "F0", "Rcl")} for f in range(N)]
    for f in range(N):
        Pf, tp = rig.hand_bones(Hw[f], pts["W"][f], curls[f], spread, thumb_abd)
        for fn in AR.FINGERS: tips[fn][f] = tp[fn]
        knuck[f] = Pf[f"middle.01.{s}"][:3, 3]
        if f % EVERY == 0:
            P, _ = rig.android_pose(Ks[f], Hw[f], (pts["S"][f], pts["E"][f], pts["W"][f]), K["tau"][f], curls[f], spread, static or {}, thumb_abd, f=f); delta.append(AR.delta_rows(P) if static is not None else P)   # static None (full body): this arm's bone matrices only; body_bake merges them
    # the driving skeleton: local rotations per bone
    tw = sg * r(ch["sh_twist"]); tau = K["tau"]; sw = np.stack([-r(ch["wrist_dev"]), np.zeros(N), -sg * r(ch["wrist_flex"])], 1)
    sd = "right" if s == "R" else "left"
    L = {f"{sd}Shoulder": K["Rcl"], f"{sd}UpperArm": np.swapaxes(K["Rcl"], 1, 2) @ K["U"] @ rig.U0.T, f"{sd}UpperArm.twist.01": ry(-0.5 * tw), f"{sd}UpperArm.twist.02": ry(0 * tw),
         f"{sd}LowerArm": rx(r(ch["elbow"])), f"{sd}LowerArm.twist.01": ry(tau / 3), f"{sd}LowerArm.twist.02": ry(2 * tau / 3), f"{sd}Hand": ry(tau) @ rv(sw) @ ry(sg * r(ch["wrist_twist"]))}
    for i, fn in enumerate(AR.FINGERS):
        for j, jn in enumerate(("Proximal", "Intermediate", "Distal") if fn != "thumb" else ("Metacarpal", "Proximal", "Distal")): L[f"{sd}{fn.capitalize()}{jn}"] = rx(r(fd[:, i, j]))
    perf = dict(id=ident, kind=kind, hz=HZ, N=N, ch=ch, pts=dict(pts), tips=tips, knuckle=knuck, W_plan=W_plan, W_raw=W_raw, Hm=Hm, Hw=Hw, flags=out["flags"], prior=out["prior"], plan=out["plan"], events=list(events),
                contacts=np.array(sorted(contacts), int), mode=mode, delta=delta, static=static, rig=rig, curls=curls, spread=spread, thumb_abd=thumb_abd, K=K, S_off=out.get("S_off"))
    if stick is not None:
        g = stick["grip"]; al, be = r(stick["alpha"]), r(stick["beta"]); sd = np.einsum("nij,nj->ni", Hw, g.sdir(al, be)); F = pts["W"] + np.einsum("nij,j->ni", Hw, g.f)
        import stroke_plan as SP
        perf.update(stick=dict(F=F, tip=F + SP.R_TIP * sd, butt=F - SP.R_BUTT * sd, dir=sd), grip=g); ch["stick_alpha"] = stick["alpha"]; ch["stick_beta"] = stick["beta"]
        L[f"stick.{s}"] = rv(g.ag * al[:, None]) @ rv(np.cross(g.s0, g.ag) * -be[:, None])
    perf["quat"] = {k: _quat(np.broadcast_to(v, (N, 3, 3)).copy()) for k, v in L.items()}
    if extra: perf.update(extra)
    return perf


def old_channels(rig0, perf, char, side="R"):
    """an old bake's arm, decomposed with the new rig's joint definitions (per frame, in that frame's own chest). -> channels (deg) + S, E, W (character space)"""
    C = next(c for c in perf["chars"] if c["name"] == char) if char else perf; names = perf["bone_names"]; ix = {n: i for i, n in enumerate(names)}; N = len(C["delta"]); out = {}; rows = []
    S, E, W = np.zeros((N, 3)), np.zeros((N, 3)), np.zeros((N, 3))
    for f in range(N):
        P = {}
        for n in ("chest", f"upper_arm.{side}", f"forearm.{side}", f"hand.{side}"):
            M = np.eye(4); M[:3] = np.array(C["delta"][f][ix[n]]).reshape(3, 4); P[n] = M @ AR.REST[n] if n != "chest" else M
        T = P["chest"]; U_, _, Vt = np.linalg.svd(T[:3, :3]); T[:3, :3] = U_ @ Vt; rg = AR.ArmRig(T, ()); S[f], E[f], W[f] = P[f"upper_arm.{side}"][:3, 3], P[f"forearm.{side}"][:3, 3], P[f"hand.{side}"][:3, 3]
        a = rg.analyze(rg.to_chest(S[f])[None], rg.to_chest(E[f])[None], rg.to_chest(W[f])[None], (T[:3, :3].T @ P[f"hand.{side}"][:3, :3])[None])
        sw = a["sw_raw"][0]; rows.append([np.degrees(a[k][0]) for k in ("sh_flex", "sh_abd", "sh_twist", "elbow")] + [rg.sg * np.degrees(a["tau_raw"][0]), -rg.sg * np.degrees(sw[2]), -np.degrees(sw[0]),
                                                                                                               np.degrees(rg.swivel_of(rg.to_chest(S[f])[None], rg.to_chest(E[f])[None], rg.to_chest(W[f])[None])[0])])
    rows = np.array(rows); rows[:, 4] = np.degrees(np.unwrap(np.radians(rows[:, 4]))); rows[:, 7] = np.degrees(np.unwrap(np.radians(rows[:, 7])))
    for i, k in enumerate(("sh_flex", "sh_abd", "sh_twist", "elbow", "hand_twist_at_wrist", "wrist_flex", "wrist_dev", "swivel")): out[k] = rows[:, i]
    return out, dict(S=S, E=E, W=W)


def render_perf_piano(perf, old, path, cam=None):
    """the new arm as an android_scene --perf JSON: 1P only, the old bake's set, keys and note blocks"""
    C = dict(next(c for c in old["chars"] if c["name"] == "1P")); C = dict(name="1P", mark=C["mark"], yaw=C["yaw"], accent=C["accent"], delta=perf["delta"])
    P = {k: old[k] for k in ("fps", "bone_names", "keys", "keys_sink", "key_quads", "key_z", "lanes", "blocks", "note_speed", "set") if k in old}; P["frames"] = len(perf["delta"]); P["chars"] = [C]
    P["lanes"] = [l for l in P["lanes"] if l["player"] == 1]; P["blocks"] = [b for b in P["blocks"] if "_a" in b["mat"] or b["mat"] in ("note_w", "note_sweep", "note_flick")]
    if cam: P["set"] = dict(P.get("set", {}), camera=cam)
    json.dump(P, open(path, "w"), separators=(",", ":"))


def render_perf_drums(perf, old, path):
    """the new arm as a drum_scene --perf JSON: the old kit, pedals and kit reactions; the left stick frozen in the frozen left hand"""
    f0 = perf["ref_frame"]; st = perf["stick"]; n = len(perf["delta"]); M = perf.get("posture_M", np.eye(4)); L = old["sticks"][f0][0]; L = [round(float(v), 4) for v in np.concatenate([M[:3, :3] @ np.array(L[:3]) + M[:3, 3], M[:3, :3] @ np.array(L[3:]) + M[:3, 3]])]
    P = {k: old[k] for k in ("fps", "bone_names", "kit", "chart", "hat", "beater", "kick_plate", "hat_plate", "kit_state")}; P["frames"] = n; P["delta"] = perf["delta"]; P["left_stick"] = L
    P["beater"] = [old["beater"][f0]] * n; P["kick_plate"] = [old["kick_plate"][f0]] * n                        # the legs are frozen: so are the kick pedal and its beater
    P["sticks"] = [[L, [round(float(v), 4) for v in np.concatenate([st["tip"][f] - 0.40 * st["dir"][f], st["tip"][f]])]] for f in range(0, perf["N"], EVERY)]
    json.dump(P, open(path, "w"), separators=(",", ":"))
