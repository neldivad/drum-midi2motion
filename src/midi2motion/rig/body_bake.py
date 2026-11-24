#!/usr/bin/env python3
# midi2motion: vendored from nelvids/lab/wrapped/3d/2026-11-16-rig-foundations/tools/body_bake.py (a wrapped lab, read-only source). Solver behaviour unchanged; only data paths and the lab command line were changed.
"""body_bake.py: a planned full body (fullbody.plan_*) -> what Blender, the inspector and a driving-skeleton consumer take.

- arm_perf(): one arm through the proof's own bake.assemble (channels, points, the stick, fingers, the driving quaternions) on the moving chest;
- deltas(): the android's 51 bone deltas per render frame (every 4th solved frame): trunk and head from body_rig, legs from the leg IK, arms from each arm's bake;
- drive(): the whole driving skeleton: VRM 1.0 humanoid names + twist bones, local rotations (quaternions x,y,z,w, one hemisphere) at 120 Hz, the hips' position;
- render_drums() / render_piano(): the perf JSONs the sibling scenes render (their kit, keys, note blocks and kit reactions reused by path, never edited).
"""
import json, pathlib, sys
import numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import arm_rig as AR, bake, body_rig as BR
from arm_rig import CFG, HZ

EV = CFG["render_every"]; VRM = dict(hips="hips", spine="spine", chest="chest", neck="neck", head="head")
def rl(a, n=3): return np.round(np.asarray(a, float), n).tolist()


def deltas(P, perfs):
    N = P["N"]; T = P["T"]; rows = []
    for i, f in enumerate(range(0, N, EV)):
        D = {b: T[b][f] for b in BR.TRUNK + BR.HEADB}
        for s in "LR": D.update(BR.Body.leg_delta(P["legs"][s], f))
        for h in "LR":
            for b, M in perfs[h]["delta"][i].items(): D[b] = M @ AR.RINV[b]
        rows.append([[round(float(v), 5) for v in D[n][:3].reshape(-1)] for n in AR.NAMES])
    return rows


def drive(P, perfs, path, note):
    N = P["N"]; T = P["T"]; q = {}; Rw = {b: T[b][:, :3, :3] for b in BR.TRUNK + BR.HEADB}; par = dict(hips=None, spine="hips", chest="spine", neck="chest", head="neck")
    for b, p in par.items(): q[VRM[b]] = bake._quat(Rw[b] if p is None else np.swapaxes(Rw[p], 1, 2) @ Rw[b])
    for s, sd in (("L", "left"), ("R", "right")):
        L = P["legs"][s]["R"]; q[f"{sd}UpperLeg"] = bake._quat(np.swapaxes(Rw["hips"], 1, 2) @ L["thigh"]); q[f"{sd}LowerLeg"] = bake._quat(np.swapaxes(L["thigh"], 1, 2) @ L["shin"])
        q[f"{sd}Foot"] = bake._quat(np.swapaxes(L["shin"], 1, 2) @ L["foot"]); q[f"{sd}Toes"] = bake._quat(np.swapaxes(L["foot"], 1, 2) @ L["toe"])
    for h in "LR": q.update(perfs[h]["quat"])
    json.dump(dict(note=note, hz=HZ, frames=N, rest="rotations are deltas from the android's rest pose (2026-11-15-android-mocap-midi/out/android_rest.json), each in its parent's frame; character space x = left, y = back, z = up",
                   hips_position=rl(BR.pt(T["hips"], AR.HEAD["hips"]), 4), quat={k: np.round(v, 5).tolist() for k, v in q.items()}), open(path, "w"), separators=(",", ":"))
    return q


def sticks_30(perfs):
    out = []
    for f in range(0, perfs["R"]["N"], EV): out.append([[round(float(v), 4) for v in np.concatenate([perfs[h]["stick"]["tip"][f] - 0.40 * perfs[h]["stick"]["dir"][f], perfs[h]["stick"]["tip"][f]])] for h in "LR"])
    return out


def render_drums(P, perfs, delta, path):
    old = P["d"]["old"]; n = len(delta); R = {k: old[k] for k in ("fps", "bone_names", "kit", "chart", "hat", "beater", "kick_plate", "hat_plate", "kit_state")}; R["frames"] = n; R["delta"] = delta; R["sticks"] = sticks_30(perfs)
    json.dump(R, open(path, "w"), separators=(",", ":"))


def render_piano(P, delta, path, cam=None):
    old = P["d"]["old"]; C1 = next(c for c in old["chars"] if c["name"] == "1P"); C = dict(name="1P", mark=C1["mark"], yaw=C1["yaw"], accent=C1["accent"], delta=delta)
    R = {k: old[k] for k in ("fps", "bone_names", "keys", "keys_sink", "key_quads", "key_z", "lanes", "blocks", "note_speed", "set") if k in old}; R["frames"] = len(delta); R["chars"] = [C]
    R["lanes"] = [l for l in R["lanes"] if l["player"] == 1]; R["blocks"] = [b for b in R["blocks"] if "_a" in b["mat"] or b["mat"] in ("note_w", "note_sweep", "note_flick")]
    if P.get("keys_sink") is not None: R["keys_sink"] = P["keys_sink"]                 # the keys sink where THESE fingertips are (the chart still lights them)
    R["keys"] = [row[:30] + [0.0] * (len(row) - 30) for row in R["keys"]]                # 2P is not in this clip: its half of the console stays dark
    if cam: R["set"] = dict(R.get("set", {}), camera=cam)
    json.dump(R, open(path, "w"), separators=(",", ":"))
