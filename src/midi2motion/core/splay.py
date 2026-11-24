# LIBRARY COPY of drum-benchmark/tools/splay.py (nelvids lab, 2026-11-2x), packaged in midi2motion (vendored from the nelvids drums library): analysis-only functions and the lab's CLI dropped, lab paths -> rigenv.
#!/usr/bin/env python3
"""splay.py: R-557's stick-splay check. Seen from above, each stick should point away from the body's midline on its own side (left stick forward-left, right stick
forward-right: a V opening forward). Counted per frame at 30 fps, from the page's motion files or the 120 Hz inspector datasets; changes nothing.

    import splay; R = splay.check(sticks_L, sticks_R, kit)     sticks_*: (N, 2, 3) butt, tip per frame (character space: x = the player's left, -y = forward, z = up)

YAW = the stick's heading from above (butt -> tip), degrees from straight forward, + toward the player's left. A frame is a SPLAY ERROR for a hand when:
  INWARD   the stick is at its own far side of the kit (its TIP more than 0.25 m from the midline: the hi-hat and crash on the left, the floor tom, tom 3 and ride on the
           right; the snare and tom 1 are central) and it points in toward the
           midline by more than 15 deg (left yaw < -15, right yaw > +15): his screenshot's left hand at the left crash pointing in;
  PARALLEL both sticks are at opposite ends (left tip x > +0.25 and right tip x < -0.25) and both sticks point the same way by more than 15 deg (both yaws > +15 or both < -15).
Frames where the stick points nearly straight up or down (less than 4 cm of horizontal length) are skipped (no heading). The PIECE of a flagged frame is the kit piece whose
centre is nearest the stick's tip, from above.
"""
import base64, collections, glob, json, pathlib, sys
sys.dont_write_bytecode = True
import numpy as np
HERE = pathlib.Path(__file__).resolve().parent; LAB = HERE.parent
FAR, DEG, MINLEN, FULCRUM = 0.25, 15.0, 0.04, 0.3333


def yaw(st):
    d = st[:, 1, :2] - st[:, 0, :2]; ln = np.linalg.norm(d, axis=1); y = np.degrees(np.arctan2(d[:, 0], -d[:, 1])); y[ln < MINLEN] = np.nan; return y


def check(SL, SR, kit=None):
    yl, yr = yaw(SL), yaw(SR); xl, xr = SL[:, 1, 0], SR[:, 1, 0]; n = min(len(yl), len(yr))   # v002: where the stick IS on the kit = its tip (v001 used the fulcrum: the snare itself counted as the far side)
    yl, yr, xl, xr = yl[:n], yr[:n], xl[:n], xr[:n]
    with np.errstate(invalid="ignore"):
        inL = (xl > FAR) & (yl < -DEG); inR = (xr < -FAR) & (yr > DEG); par = (xl > FAR) & (xr < -FAR) & (((yl > DEG) & (yr > DEG)) | ((yl < -DEG) & (yr < -DEG)))
    err = inL | inR | par; pieces = collections.Counter()
    if kit:
        P = [(p["id"], np.array(p["c"][:2])) for p in kit["pieces"]]
        for f in np.nonzero(inL)[0]: pieces["L " + min(P, key=lambda q: np.linalg.norm(q[1] - SL[f, 1, :2]))[0]] += 1
        for f in np.nonzero(inR)[0]: pieces["R " + min(P, key=lambda q: np.linalg.norm(q[1] - SR[f, 1, :2]))[0]] += 1
    runs = []; f = 0
    while f < n:
        if err[f]:
            g = f
            while g + 1 < n and err[g + 1]: g += 1
            runs.append(dict(f0=int(f), f1=int(g), kind="inward L" if inL[f:g + 1].any() and not inR[f:g + 1].any() else "inward R" if inR[f:g + 1].any() and not inL[f:g + 1].any() else "parallel" if par[f:g + 1].any() and not (inL | inR)[f:g + 1].any() else "mixed"))
            f = g + 1
        else: f += 1
    return dict(frames=int(err.sum()), frames_total=int(n), inward_L=int(inL.sum()), inward_R=int(inR.sum()), parallel=int(par.sum()), pieces=dict(pieces), runs=runs,
                yaw_L_median=None if np.all(np.isnan(yl)) else round(float(np.nanmedian(yl)), 1), yaw_R_median=None if np.all(np.isnan(yr)) else round(float(np.nanmedian(yr)), 1))


def from_motion(M):
    """the page's motion file: sticks = int16 / 10000, (frames, hand L/R, butt + tip = 6)"""
    a = np.frombuffer(base64.b64decode(M["sticks"]), dtype="<i2").astype(float) / 10000.0; a = a.reshape(M["frames"], 2, 6)
    return a[:, 0].reshape(-1, 2, 3), a[:, 1].reshape(-1, 2, 3)


def from_dataset(D):
    ev = 4; S = {h: np.stack([np.asarray(D["arms"][h]["stick"]["butt"], float)[::ev], np.asarray(D["arms"][h]["stick"]["tip"], float)[::ev]], 1) for h in "LR"}; return S["L"], S["R"]
