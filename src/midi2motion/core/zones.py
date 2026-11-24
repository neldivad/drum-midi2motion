# LIBRARY COPY of drum-benchmark/tools/zones.py (nelvids lab, 2026-11-2x), packaged in midi2motion (vendored from the nelvids drums library): analysis-only functions and the lab's CLI dropped, lab paths -> rigenv.
#!/usr/bin/env python3
"""zones.py: R-575's per-hand, per-side stick zones and the straight-arm flag (round 6), measured on solved motion; fixes nothing.

    import zones; zones.frames(D, Z) -> per-frame flags for one 120 Hz dataset (30 fps sampling)

CELL = (hand, where its stick tip is, from above): "snare" (the left hand's tip within 0.15 m of the snare's centre: its own close-to-the-body zone, R-575), "left side"
  (tip x > +0.25 m), "right side" (x < -0.25 m), "centre" (the rest). YAW = the stick's heading from straight forward, + toward the player's left (tools/splay.py).
ZONE of a cell = the 2.5-97.5 % range of the yaw over the CLEANEST frames we have: solved windows with 0 missed, 0 wrong, 0 hard frames and 0 R-557 splay frames
  (v009 and v013 datasets). These are OUR zones, fitted on this rig's own motion, not measured on human drummers. R-575 also forbids pointing back across the body, so on a
  far side the zone is cut at 15 deg inward (R-557's line): left side, left hand: yaw >= -15; right side, right hand: yaw <= +15.
ZONE ERROR = a frame whose yaw is outside its cell's zone (a cell with < 60 clean frames has no zone and is not judged).
STRAIGHT ARM (R-575): upper arm and forearm nearly straight (elbow angle >= 165 deg) AND the arm out to the side (the shoulder -> wrist line, from above, >= 70 deg from
  straight forward): an arm held out at ~90 deg from the head line.
"""
import collections, glob, json, pathlib, sys
sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent; LAB = HERE.parent; sys.path.insert(0, str(HERE))
import numpy as np
import splay as SPL
SIDE, SNARE_R, MINF = 0.25, 0.15, 60


def cells(SL, SR, kit):
    sn = np.array(next(p["c"] for p in kit["pieces"] if p["id"] == "snare")[:2]); out = {}
    for h, S in (("L", SL), ("R", SR)):
        tip = S[:, 1, :2]; x = tip[:, 0]; c = np.where(x > SIDE, "left side", np.where(x < -SIDE, "right side", "centre")).astype(object)
        if h == "L": c[np.linalg.norm(tip - sn, axis=1) <= SNARE_R] = "snare"
        out[h] = c
    return out


def arm_straight(D, every=4):
    out = {}
    for h in "LR":
        P = D["arms"][h]["pts"]; S, E, W = (np.asarray(P[k], float)[::every] for k in ("S", "E", "W")); a, b = S - E, W - E
        el = np.degrees(np.arccos(np.clip((a * b).sum(1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1) + 1e-9), -1, 1)))
        sw = W - S; side = np.degrees(np.arctan2(np.abs(sw[:, 0]), -sw[:, 1])); out[h] = (el >= 165) & (side >= 70)
    return out






def frames(D, Z):
    SL, SR = SPL.from_dataset(D); C = cells(SL, SR, D["kit"]); st = arm_straight(D); out = {}
    for h, S in (("L", SL), ("R", SR)):
        y = SPL.yaw(S); n = min(len(y), len(st[h])); bad = np.zeros(n, bool)
        for k in range(n):
            z = Z.get(f"{h} {C[h][k]}")
            if z and not np.isnan(y[k]) and not (z["lo"] <= y[k] <= z["hi"]): bad[k] = True
        out[h] = dict(zone=bad, straight=st[h][:n], cell=C[h][:n])
    return out
