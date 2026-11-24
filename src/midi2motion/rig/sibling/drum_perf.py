#!/usr/bin/env python3
# midi2motion: vendored from nelvids/lab/wrapped/3d/2026-11-16-android-drums/tools/drum_perf.py (a wrapped lab, read-only source). Solver behaviour unchanged; only data paths and the lab command line were changed.
"""drum_perf.py: a drum chart (drum_chart.py) -> the android's baked drum performance + its audit.

    <venv>/python tools/drum_perf.py out/closure_drum_chart.json out/drums_perf_v001.json [--report out/drums_report_v001.json]

Solver: the sibling lab's tools/rig.py (round 2: collision-aware arms, capsule body), used by path. This file adds what a drummer needs:
a seated lower body with feet on two pedals, sticks rigid in the fists, and the stroke model.

Stroke model (R-389 on the beat, R-402 velocity-aware). Each hand is a list of strokes; between two of them:
- the hand travels (minimum jerk) to hover over the next piece BEFORE its downstroke starts: the next hand is already moving;
- the stick tip's height above the strike point is an envelope: rebound off the last hit (it leaves the head at speed), settle at a low ready
  height, LIFT (the anticipation) to a height set by the NEXT note's velocity, a short hold, then an accelerating downstroke that is at
  height 0 on the note's frame. Close notes (< 0.34 s) are one hump: rebound straight into the next lift, capped by the time there is (0.03 + 1.5 x gap m).
- lift height = 0.025 + 0.30 (v/127)^1.6 m (ghost v20: 4 cm; v85: 18 cm; v127: 33 cm), downstroke time 0.11 - 0.04 v/127 s, so loud = higher
  AND faster; the wrist/forearm carries 35 % of any height over 6 cm (a Moeller-ish arm stroke for accents), the wrist hinge the rest.
Articulations are gestures (R-401): a sweep keeps the tip ON the cymbal and drags it along a curved path, its progress weighted by the run's
velocities (a crescendo run accelerates the drag); a crescendo keeps the stick up between its notes (no settle), heights growing with the ramp;
a cross-stick plants the tip on the head and drops the wrist. Feet: the kick beater and the hat pedal use the same envelope in degrees.
Kit reactions are closed-form sums of damped oscillators per hit (cymbals swing, drums dip on their stands).
"""
import argparse, json, math, pathlib, sys
import numpy as np
HERE = pathlib.Path(__file__).resolve().parent; LAB = HERE.parent; SIB = LAB.parent / "2026-11-15-android-mocap-midi"
sys.path.insert(0, str(SIB / "tools")); sys.path.insert(0, str(HERE))
import rig as RG, kit

DEBUG = set(int(x) for x in __import__("os").environ.get("DRUM_DEBUG", "").split(",") if x)
Z = np.array([0, 0, 1.0]); nrm = RG.nrm; rot = RG.rot
def mj(u): u = min(1.0, max(0.0, u)); return u * u * u * (10 - 15 * u + 6 * u * u)
def lift_h(v): return 0.025 + 0.30 * (v / 127.0) ** 1.6
def down_t(v): return 0.11 - 0.04 * v / 127.0
def minrot(a, b):
    a, b = nrm(a), nrm(b); ax = np.cross(a, b); s = np.linalg.norm(ax); c = float(a @ b)
    return np.eye(3) if s < 1e-9 else rot(ax / s, math.atan2(s, c))


def envelope(tau, g, H, Td, Rb, ready, hold_up=False, unit=1.0):
    """height at time tau after the last hit, the next hit at tau = g. H: the next stroke's lift, Rb: the last hit's rebound"""
    Hc = min(H, unit * (0.03 + 1.5 * g))                                          # unit: metres for a stick tip; the pedals run the same envelope in degrees (unit = degrees per metre)
    if g <= 0.34 or hold_up:
        Td = min(Td, 0.5 * g); tu = g - Td
        if tau < tu: return Hc * math.sin(math.pi / 2 * tau / tu) if not hold_up else Hc * math.sin(math.pi / 2 * min(1.0, tau / min(tu, 0.12)))
        v = (tau - tu) / Td; return Hc * (1 - v * v)
    Tl = 0.17; hold = 0.035; tl = g - Td - hold - Tl; Rb = min(Rb, 0.12 * unit); ready = min(ready, max(Rb, 0.02 * unit))
    if tau < 0.07: return Rb * math.sin(math.pi / 2 * tau / 0.07)
    if tau < tl: return ready + (Rb - ready) * (1 - mj((tau - 0.07) / max(1e-3, min(0.25, tl - 0.07))))
    if tau < tl + Tl: return ready + (Hc - ready) * mj((tau - tl) / Tl)
    if tau < g - Td: return Hc
    v = (tau - (g - Td)) / Td; return Hc * (1 - v * v)


def wrist_home(hand, A, zone):
    """where the wrist sits when the tip is on A. The stick's heading and pitch are searched so that the forearm can continue the stick:
    the elbow implied by 'forearm along the stick' must be an upper-arm length from the shoulder, low, outside the ribs, near a hanging elbow"""
    sg = 1 if hand == "L" else -1; Sh = kit.SHOULDER[hand]; E0 = Sh + np.array([sg * 0.08, 0.03, -0.255])
    a0 = {"edge": 4, "closed": -8, "open": -8, "bow": -10, "bell": -16, "cross": -3}.get(zone, -12); best = None
    for al in np.radians([a0] if zone == "cross" else [a0 - 8, a0, a0 + 8]):
        for ph in np.radians(np.arange(0, 360, 4.0)):
            dh = np.array([math.cos(ph), math.sin(ph), 0]); d0 = dh * math.cos(al) + Z * math.sin(al); hu = nrm(Z - d0 * d0[2]); W = A - kit.STICK_L * d0 + kit.GRIP_DROP * hu
            E = W - 0.255 * nrm(d0 * np.array([1, 1, 0.5])); to = A - Sh; to[2] = 0
            cost = 4.0 * (np.linalg.norm(E - Sh) - 0.275) ** 2 + 0.30 * float((E - E0) @ (E - E0)) + 6 * max(0.0, np.linalg.norm(W - Sh) - 0.47) ** 2 + 6 * max(0.0, 0.24 - np.linalg.norm(W - Sh)) ** 2
            cost += 3.0 * max(0.0, 0.15 - E[0] * sg) ** 2 + 2.0 * max(0.0, E[2] - (Sh[2] - 0.10)) ** 2 + 0.02 * abs(al - math.radians(a0))
            if abs(W[0]) < 0.26 and W[1] > -0.19: cost += 10 + (W[1] + 0.19)
            if W[0] * sg < -0.22: cost += 5
            cost += 0.05 * (1 - float(dh @ nrm(to)))
            if best is None or cost < best[0]: best = (cost, W, d0)
    return best[1], best[2]


def sweep_path(piece, A0, A1):
    p = kit.P[piece]; a, b = kit.plane_basis(p); c = p["c"]
    def polar(A): v = A - c; return math.hypot(v @ a, v @ b), math.atan2(v @ b, v @ a)
    r0, a0 = polar(A0); r1, a1 = polar(A1)
    if r0 < 0.02: a0 = a1
    if r1 < 0.02: a1 = a0
    def f(q):
        r = r0 + (r1 - r0) * q + math.sin(math.pi * q) * max(0.0, 0.80 * p["r"] - max(r0, r1) * 0.5); ang = a0 + (a1 - a0) * q + math.radians(110) * math.sin(math.pi * q) * 0.5 + math.radians(70) * q * (1 - q)
        return c + r * (math.cos(ang) * a + math.sin(ang) * b) + p["n"] * (kit.BELL_H * max(0.0, 1 - r / kit.BELL_R) + 0.002)
    return f


class Hand:
    def __init__(self, hand, notes, gap_at):
        self.hand = hand; self.S = []; seen = set()
        for n in notes:
            art = n.get("art")
            if art and art["kind"] == "sweep":
                if art["id"] in seen: continue
                seen.add(art["id"]); run = [m for m in notes if m.get("art", {}).get("id") == art["id"]]
                A0 = kit.strike_point(n["piece"], n["zone"], hand); A1 = kit.strike_point(run[-1]["piece"], run[-1]["zone"], hand); W, d0 = wrist_home(hand, A0, "bow")
                cv = np.cumsum([m["vel"] for m in run[1:]]); pk = [0.0] + list(cv / cv[-1])
                self.S.append(dict(t=n["tc"], t_end=run[-1]["tc"], vel=n["vel"], piece=n["piece"], zone=n["zone"], kind="sweep", A=A0, W=W, d0=d0, path=sweep_path(n["piece"], A0, A1), tk=list(np.maximum.accumulate([run[0]["tc"]] + [max(m["tc_raw"], run[0]["tc"] + 0.004 * (k + 1)) for k, m in enumerate(run[1:-1])] + [run[-1]["tc"]])), pk=pk, vels=[m["vel"] for m in run], art=art["id"], A_end=A1))
                continue
            A = kit.strike_point(n["piece"], n["zone"], hand, gap_at(n["tc"]) if n["piece"] == "hat" else 0.0); W, d0 = wrist_home(hand, A, n["zone"])
            self.S.append(dict(t=n["tc"], t_end=n["tc"], vel=n["vel"], piece=n["piece"], zone=n["zone"], kind="cross" if n["zone"] == "cross" else "hit", A=A, W=W, d0=d0, art=art["id"] if art else None, cres=bool(art and art["kind"] == "crescendo" and art["i"] > 0)))
        self.S.sort(key=lambda s: s["t"])

    def at(self, t):
        """-> wrist W, stick dir d, back-of-hand up hu, info"""
        S = self.S; j = next((k for k, s in enumerate(S) if s["t"] > t + 1e-9), None); i = (j - 1) if j is not None else len(S) - 1
        a = S[i] if i >= 0 else None; b = S[j] if j is not None else None
        if a is not None and a["kind"] == "sweep" and t <= a["t_end"] + 1e-9:                    # dragging: tip on the cymbal
            q = float(np.interp(t, a["tk"], a["pk"])); A = a["path"](q); W = a["W"] + (A - a["A"]); d = nrm(A - (W - kit.GRIP_DROP * Z)); hu = nrm(Z - d * d[2])
            return W, d, hu, dict(h=0.0, mode="sweep", piece=a["piece"])
        if a is None: a = dict(b, t=b["t"] - 2.0, t_end=b["t"] - 2.0, vel=40)
        if b is None: b = dict(a, t=a["t_end"] + 3.0, vel=40, kind="hit")
        Aa, Wa = (a["A_end"], a["W"] + (a["A_end"] - a["A"])) if a["kind"] == "sweep" else (a["A"], a["W"])
        ta = a["t_end"]; g = b["t"] - ta; tau = t - ta; Td = down_t(b["vel"]); H = lift_h(b["vel"]) * (0.45 if b["kind"] == "cross" else 1.0)
        h = envelope(tau, g, H, Td, 0.35 * lift_h(a["vel"]), 0.05, hold_up=b.get("cres", False))
        dist = float(np.linalg.norm(b["A"] - Aa)); Tm = min(0.45, max(0.16, dist / 1.3)); ts = max(ta + 0.02, b["t"] - Td - 0.03 - Tm) if g > 0.34 else ta; te = b["t"] - min(Td, 0.5 * g) * (1.0 if g > 0.34 else 0.6)
        if te - ts < 0.03: ts, te = ta, b["t"] - 0.25 * min(Td, g)
        u = mj((t - ts) / (te - ts)); A = Aa + (b["A"] - Aa) * u; W = Wa + (b["W"] - Wa) * u
        hump = 4 * u * (1 - u) * min(0.07, 0.18 * dist) if dist > 0.05 else 0.0
        planted = a["kind"] == "cross" and b["kind"] == "cross" and g < 1.0 and dist < 0.02
        if planted:                                                                             # cross-stick: the tip stays on the head, the wrist drops the shaft onto the rim
            W = W + Z * h * 0.9; hu0 = nrm(Z - b["d0"] * b["d0"][2]); d = nrm(A - (W - kit.GRIP_DROP * hu0)); hu = nrm(Z - d * d[2])
            return W, d, hu, dict(h=h, mode="cross", piece=b["piece"])
        hh = h + hump; wl = 0.35 * max(0.0, hh - 0.06); d0 = nrm(A - (W - kit.GRIP_DROP * Z)); side = nrm(np.cross(d0, Z))
        th = math.asin(min(0.97, max(-0.3, (hh - wl) / kit.STICK_L))); d = rot(side, th) @ d0; hu = nrm(Z - d * d[2]); W = W + Z * wl
        return W, d, hu, dict(h=hh, mode="hit", piece=b["piece"] if u > 0.5 else a["piece"])


def hat_track(notes, T):
    """the hi-hat's openness 0..1 over time as keys (t, value, ease); closed for 42, open for 46, stomped shut on 44"""
    keys = [(-9.0, 0.0, "s")]; cur = 0.0; last = -9.0
    for n in notes:
        t = n["tc"]
        if n["note"] == 42:
            if cur > 0: keys += [(max(last + 0.02, t - 0.10), cur, "s"), (max(last + 0.04, t - 0.03), 0.0, "s")]; cur = 0.0
        elif n["note"] == 46:
            if cur < 1: keys += [(max(last + 0.02, t - 0.11), cur, "s"), (max(last + 0.04, t - 0.015), 1.0, "s")]; cur = 1.0
        elif n["note"] == 44:
            if cur < 0.3:
                a = 0.35 + 0.65 * n["vel"] / 127.0; keys += [(max(last + 0.02, t - 0.21), cur, "s"), (max(last + 0.05, t - 0.075), a, "s")]; cur = a
            else: keys.append((max(last + 0.02, t - 0.075), cur, "s"))
            keys.append((t, 0.0, "a")); cur = 0.0
        else: continue
        last = t
    keys.sort(key=lambda k: k[0]); kt = [k[0] for k in keys]
    def f(t):
        i = int(np.searchsorted(kt, t, side="right")) - 1
        if i >= len(keys) - 1: return keys[-1][1]
        (t0, v0, _), (t1, v1, e) = keys[i], keys[i + 1]; u = (t - t0) / max(1e-6, t1 - t0); return v0 + (v1 - v0) * (u * u if e == "a" else mj(u))
    return f


def osc(hits, t, amp, freq, decay, phase="sin"):
    v = 0.0
    for th, w in hits:
        x = t - th
        if 0 <= x < 6 * decay: v += amp * w * math.exp(-x / decay) * (math.sin(2 * math.pi * freq * x) if phase == "sin" else math.cos(2 * math.pi * freq * x))
    return v


def solid_pen(pt, rad, solid):
    _, c, n, r, depth = solid; x = pt - c; ax = -float(x @ n); radial = float(np.linalg.norm(x + n * ax))
    if -rad < ax < depth + rad and radial < r + rad: return min(ax + rad, r + rad - radial, depth + rad - ax)
    return 0.0


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("chart"); ap.add_argument("out"); ap.add_argument("--report"); A = ap.parse_args()
    C = json.load(open(A.chart)); fps = C["fps"]; N = C["frames"]; notes = C["notes"]
    for n in notes: n["tc_raw"] = n["tc"]; n["tc"] = n["frame"] / fps if abs(n["tc"] * fps - n["frame"]) < 0.51 else n["tc"]            # every note lands on its frame
    rg = RG.Rig(); H0 = rg.HEAD
    hatf = hat_track([n for n in notes if n["note"] in (42, 44, 46)], N / fps); gap = lambda t: kit.HAT_GAP_CLOSED + (kit.HAT_GAP_OPEN - kit.HAT_GAP_CLOSED) * hatf(t)
    hands = {h: Hand(h, [n for n in notes if n["limb"] == h and not n.get("merged")], gap) for h in "LR"}
    kicks = [n for n in notes if n["limb"] == "RF"]
    def beater(t):                                                                  # degrees back from the head; 0 on the note
        j = next((k for k, s in enumerate(kicks) if s["tc"] > t + 1e-9), None); i = (j - 1) if j is not None else len(kicks) - 1
        ta, va = (kicks[i]["tc"], kicks[i]["vel"]) if i >= 0 else (t - 2.0, 60); tb, vb = (kicks[j]["tc"], kicks[j]["vel"]) if j is not None else (t + 3.0, 60)
        return envelope(t - ta, tb - ta, 22 + 34 * vb / 127.0, 0.085, 12 + 14 * va / 127.0, 20.0, unit=170.0)
    # beats (from the MIDI tempo) and their weight (the loudest kick / snare / crash on them)
    beat_s = C["bar_s"] / 4; beats = []
    for k in range(-4, int(N / fps / beat_s) + 6):
        tb = C["lead"] + k * beat_s; w = max([n["vel"] for n in notes if abs(n["tc"] - tb) < 0.02 and n["note"] in (36, 38, 49)] or [45]) / 127.0; beats.append((tb, w))
    def pulse(t): return sum(w * (-math.exp(-((t - tb - 0.035) / 0.06) ** 2) + 0.45 * math.exp(-((t - tb + 0.13) / 0.085) ** 2)) for tb, w in beats if abs(t - tb) < 0.5)
    # kit hits for the reactions: piece -> [(t, weight)]
    kh = {p["id"]: [] for p in kit.PIECES}
    for n in notes:
        if n["piece"] and n["limb"]: kh[n["piece"]].append((n["tc"], n["vel"] / 127.0 * (0.35 if n.get("art", {}).get("kind") == "sweep" and 0 < n["art"]["i"] < n["art"]["n"] - 1 else 1.0)))
    surfaces = kit.surfaces(); solids = kit.solids(); st = {}
    raw = [{h: hands[h].at(f / fps) for h in "LR"} for f in range(N)]
    xm = np.array([np.mean([r[h][0][0] + r[h][1][0] * 0.4 for h in "LR"]) for r in raw]); ym = np.array([np.mean([r[h][0][1] + r[h][1][1] * 0.4 for h in "LR"]) for r in raw])
    ker = np.exp(-0.5 * (np.arange(-15, 16) / 5.0) ** 2); ker /= ker.sum(); sm = lambda x: np.convolve(np.pad(x, 15, mode="edge"), ker, mode="valid")
    yaw = sm(np.clip(xm / 0.5, -1, 1) * 14.0); lean = sm(np.clip((-ym - 0.45) / 0.3, 0, 1) * 7.0)
    out = dict(fps=fps, frames=N, bone_names=rg.names, delta=[], sticks=[], kit_state=[], caps=[], hat=[], beater=[], height={"L": [], "R": []}, tip_dist={"L": [], "R": []}, mode={"L": [], "R": []},
               pens=[], angles=[], limits=[]); col_rows = []; tips = {"L": [], "R": []}
    for f in range(N):
        t = f / fps; pu = pulse(t); be = beater(t); ho = hatf(t)
        pose = dict(root=[kit.ROOT[0], kit.ROOT[1], kit.ROOT[2] + 0.006 * pu], hips=[4, 0, 0], spine=[5 + lean[f] * 0.5 - 1.6 * pu, 0, yaw[f] * 0.35], chest=[4 + lean[f] * 0.5 - 1.2 * pu, 0, yaw[f] * 0.65],
                    neck=[2 - 2.5 * pu, 0, yaw[f] * 0.2], head=[3 - 4.0 * pu, 0, yaw[f] * 0.3], shrug=[0, 0])
        for h in "LR":
            W, d, hu, inf = raw[f][h]; pose[f"hand_{h}"] = dict(pos=list(W), dir=list(d), up=list(hu), curl=[0.55, 0.92, 0.95, 0.95, 0.95], spread=0.0)
        # feet: right = kick (heel up, the ball of the foot on the board), left = hat pedal (heel down, the toe lifts with the board)
        psi = math.radians(0.36 * be); hinge = np.array([kit.ANKLE["R"][0], kit.ANKLE["R"][1] + 0.05, 0.012]); ball = hinge + 0.16 * np.array([0, -math.cos(psi), math.sin(psi)]) + Z * 0.02
        ankR = ball + np.array([0, 0.115, 0.062 + 0.022 * be / 40.0]); dirR = ball - ankR
        psl = math.radians(11.0 * ho); ankL = kit.ANKLE["L"]; dirL = rot((1, 0, 0), psl) @ np.array([0.03, -0.122, -0.06])           # x rotation: the toe rises (checked below)
        if dirL[2] < -0.06 - 1e-6 and ho > 0: dirL = rot((1, 0, 0), -psl) @ np.array([0.03, -0.122, -0.06])
        feet = {"R": (ankR, dirR), "L": (ankL, dirL)}
        rg.HEAD = dict(H0); rg.HEAD["foot.R"] = ankR; rg.HEAD["foot.L"] = ankL
        want = {h: np.asarray(pose[f"hand_{h}"]["pos"]) - kit.GRIP_DROP * np.asarray(pose[f"hand_{h}"]["up"]) + kit.STICK_L * np.asarray(pose[f"hand_{h}"]["dir"]) for h in "LR"}
        base = {h: np.asarray(pose[f"hand_{h}"]["pos"], float) for h in "LR"}; corr = {h: np.zeros(3) for h in "LR"}; best = None
        for it in range(6):                                                        # closed loop on the TIP: where the solver bends the wrist to its limit or pushes the arm, the wrist target moves so the tip still lands
            for h in "LR": pose[f"hand_{h}"]["pos"] = list(base[h] + corr[h])
            s_try = dict(st); P, info = rg.solve(pose, s_try, collide=True, surfaces=surfaces); worst = 0.0
            for h in "LR":
                M = P[f"hand.{h}"]; e = want[h] - (M[:3, 3] - kit.GRIP_DROP * M[:3, 2] + kit.STICK_L * M[:3, 1]); worst = max(worst, float(np.linalg.norm(e))); corr[h] = corr[h] + 0.8 * e
            if best is None or worst < best[0]: best = (worst, P, info, s_try)
            if worst < 0.0015: break
        _, P, info, s_try = best
        if f in DEBUG: print("DBG", f, {h: (np.round(base[h], 3), np.round(pose[f"hand_{h}"]["dir"], 2), "corr", np.round(corr[h], 3), "solvedW", np.round(P[f"hand.{h}"][:3, 3], 3), "hd", np.round(P[f"hand.{h}"][:3, 1], 2), "E", np.round(P[f"forearm.{h}"][:3, 3], 3), "S", np.round(P[f"upper_arm.{h}"][:3, 3], 3)) for h in "LR"}, "worst", round(best[0], 3), file=sys.stderr)
        st = s_try; rg.HEAD = H0
        capd = {c[0]: c for c in info["caps"]}
        for s in "LR":                                                             # the seated legs: frames by minimal rotation from rest (rig.py's fixed z-reference twists a horizontal thigh)
            Hp = capd[f"thigh.{s}"][1]; An, fd = feet[s]; K, _ = rg.two_bone(Hp, An, rg.thigh_l, rg.shin_l, Hp + np.array([(An[0] - Hp[0]) * 1.3, -1.0, 0.25]))       # the knee splays out over its foot
            info["caps"] = [(n_, Hp, K, r_) if n_ == f"thigh.{s}" else (n_, a_, b_, r_) for n_, a_, b_, r_ in info["caps"]]
            ry = lambda b: rg.REST[b][:3, 1]
            Rt = minrot(ry(f"thigh.{s}"), K - Hp); Rs = minrot(Rt @ ry(f"shin.{s}"), An - K) @ Rt; Rf = minrot(Rs @ ry(f"foot.{s}"), fd) @ Rs
            yawfix = minrot(np.array([(Rf @ rg.REST[f"foot.{s}"][:3, 0])[0], (Rf @ rg.REST[f"foot.{s}"][:3, 0])[1], 0.0]), rg.REST[f"foot.{s}"][:3, 0]) if False else np.eye(3)
            for b, R, pos in ((f"thigh.{s}", Rt, Hp), (f"shin.{s}", Rs, K), (f"foot.{s}", Rf, An), (f"toe.{s}", Rf, An + Rf @ (H0[f"toe.{s}"] - H0[f"foot.{s}"]))):
                M = np.eye(4); M[:3, :3] = R @ rg.REST[b][:3, :3]; M[:3, 3] = pos; P[b] = M
            info["caps"].append((f"shin.{s}", K, An, 0.055))
        out["delta"].append(rg.delta(P)); stk = {}
        for h in "LR":
            M = P[f"hand.{h}"]; W, hd, hu = M[:3, 3], M[:3, 1], M[:3, 2]; O = W - kit.GRIP_DROP * hu; tip = O + kit.STICK_L * hd; stk[h] = (O, tip); tips[h].append(tip)
            out["mode"][h].append(raw[f][h][3]["mode"])
        out["sticks"].append([[round(float(v), 4) for v in np.concatenate(stk[h])] for h in "LR"])
        out["caps"].append([[n, *[round(float(v), 4) for v in a], *[round(float(v), 4) for v in b], r] for n, a, b, r in info["caps"]])
        out["hat"].append(round(ho, 4)); out["beater"].append(round(be, 3)); out.setdefault("kick_plate", []).append(round(0.36 * be, 3)); out.setdefault("hat_plate", []).append(round(11.0 * ho, 3)); out["angles"].append(info["angles"]); out["limits"].append(info["limits"])
        ks = {}
        for p in kit.PIECES:
            hits = kh[p["id"]]; pid = p["id"]
            if p["kind"] == "cymbal":
                amp, fr, dc = {"crash": (0.26, 1.7, 0.75), "ride": (0.07, 1.3, 0.9), "hat": (0.045, 4.5, 0.12)}[pid]
                u = kit.toward(p, kit.SHOULDER["R"]); axis = np.cross(p["n"], u); ang = -osc(hits, t, amp, fr, dc); wob = osc(hits, t, amp * 0.3, fr * 2.3, dc * 0.6)
                rv = axis * ang + u * wob; ks[pid] = [round(float(v), 4) for v in rv] + [0.0]
            elif p["kind"] == "drum": ks[pid] = [0, 0, 0, round(-osc(hits, t, 0.007 if pid != "floor" else 0.004, 9.0, 0.06, "cos"), 5)]
            else: ks[pid] = [0, 0, 0, round(-osc(hits, t, 0.006, 7.0, 0.07, "cos"), 5)]
        out["kit_state"].append(ks)
        # ---- collisions, measured on what was solved
        rows = []
        for a, b, dep, pt, _n in info["pens"]:
            if dep > 0.002: rows.append(("body", a, b, dep))
        struck = {h: {s["piece"] for s in hands[h].S if abs(s["t"] - t) <= 1.01 / fps or (s["kind"] == "sweep" and s["t"] - 1e-6 <= t <= s["t_end"] + 1.01 / fps)} for h in "LR"}
        if any(s["kind"] == "cross" and abs(s["t"] - t) < 1.0 for s in hands["L"].S + hands["R"].S):
            for h in "LR":
                if raw[f][h][3]["mode"] == "cross": struck[h].add("snare")           # a cross-stick lies on the snare
        for h in "LR":
            O, tip = stk[h]; pts = [O + (tip - O) * u for u in np.linspace(0.12, 1.0, 30)]
            for so in solids:
                dep = max(solid_pen(p_, kit.STICK_R, so) for p_ in pts); lim = 0.022 if so[0] in struck[h] else 0.004
                if dep > lim: rows.append(("stick-kit", f"stick.{h}", so[0], dep))
            for n_, a_, b_, r_ in info["caps"]:
                if n_.endswith("." + h) and not n_.startswith(("thigh", "shin")): continue
                d_, _, _ = RG.seg_seg(O + (tip - O) * 0.1, tip, np.asarray(a_), np.asarray(b_))
                if d_ < r_ + kit.STICK_R - 0.004: rows.append(("stick-body", f"stick.{h}", n_, r_ + kit.STICK_R - d_))
        d_, _, _ = RG.seg_seg(stk["L"][0], stk["L"][1], stk["R"][0], stk["R"][1])
        if d_ < 2 * kit.STICK_R - 0.002: rows.append(("stick-stick", "stick.L", "stick.R", 2 * kit.STICK_R - d_))
        for n_, a_, b_, r_ in info["caps"]:
            if n_.startswith(("forearm", "hand", "thigh", "shin")):
                a_, b_ = np.asarray(a_), np.asarray(b_)
                for so in solids:
                    if n_.startswith("shin") and so[0] == "kick": continue
                    dep = max(solid_pen(a_ + (b_ - a_) * u, r_ * 0.8, so) for u in np.linspace(0, 1, 6))
                    if dep > 0.006: rows.append(("limb-kit", n_, so[0], dep))
        out["pens"].append([[k, a, b, round(float(d), 4)] for k, a, b, d in rows]); col_rows += [(f, *r) for r in rows]
    # ---- sync, measured on the baked sticks and pedals
    hits = []; per = {}
    for n in notes:
        f = n["frame"]
        if not (0 <= f < N) or not n["limb"] or n.get("merged"): continue
        row = dict(frame=f, note=n["note"], vel=n["vel"], limb=n["limb"], piece=n["piece"], zone=n["zone"], art=n.get("art", {}).get("kind"), bar=n["bar"])
        if n["limb"] in "LR":
            p = kit.P[n["piece"]]; A_ = kit.strike_point(n["piece"], n["zone"], n["limb"], gap(n["tc"]) if n["piece"] == "hat" else 0.0)
            hgt = lambda ff: float((tips[n["limb"]][ff] - A_) @ p["n"])
            if n.get("art", {}).get("kind") == "sweep" and n["art"]["i"] > 0:
                rr = float(np.linalg.norm((tips[n["limb"]][f] - p["c"]) - p["n"] * float((tips[n["limb"]][f] - p["c"]) @ p["n"]))); surf = kit.BELL_H * max(0.0, 1 - rr / kit.BELL_R)
                row.update(err=0, miss_mm=round(abs(float((tips[n["limb"]][f] - p["c"]) @ p["n"]) - surf) * 1000, 1), lift_mm=0.0, sweep=True)       # in contact through the gesture: judged by how far the tip is off the surface
            else:
                w = [ff for ff in range(max(0, f - 3), min(N, f + 4))]; dist = lambda ff: float(np.linalg.norm(tips[n["limb"]][ff] - A_))
                on = [ff for ff in w if dist(ff) < 0.015]; fm = min(on, key=lambda ff: abs(ff - f)) if on else min(w, key=dist)       # the hit frame = the frame the tip is on the strike point; prev = [s for s in hands[n["limb"]].S if s["t_end"] < n["tc"] - 1e-6]
                prev = [s for s in hands[n["limb"]].S if s["t_end"] < n["tc"] - 1e-6]; f0 = max(0, f - 7, int(round(prev[-1]["t_end"] * fps)) if prev else 0); over = lambda ff: float(np.linalg.norm((tips[n["limb"]][ff] - A_) - p["n"] * hgt(ff))) < 0.10        # only while the tip hovers over its target: travel from a higher piece is not lift
                pk = max([hgt(ff) for ff in range(f0, f + 1) if over(ff)] or [0.0])
                row.update(err=fm - f, miss_mm=round(float(np.linalg.norm(tips[n["limb"]][f] - A_)) * 1000, 1), lift_mm=round(pk * 1000, 1), speed_ms=round((hgt(f - 1) - hgt(f)) * fps, 2) if f > 0 else None)
        elif n["limb"] == "RF":
            w = range(max(0, f - 3), min(N, f + 4)); fm = min(w, key=lambda ff: (out["beater"][ff], abs(ff - f))); row.update(err=fm - f, miss_mm=round(out["beater"][f], 2), lift_mm=round(max(out["beater"][max(0, f - 8):f + 1]), 1))
        else:
            fm = next((ff for ff in range(max(1, f - 3), min(N, f + 4)) if out["hat"][ff] <= 1e-4 and out["hat"][ff - 1] > 1e-4), None)
            row.update(err=(fm - f) if fm is not None else None, miss_mm=round(out["hat"][f], 3), lift_mm=round(max(out["hat"][max(0, f - 8):f + 1]), 2))
        hits.append(row); per.setdefault(n["limb"], []).append(row)
    out["hits"] = hits; out["notes_unplayed"] = [dict(frame=n["frame"], note=n["note"], vel=n["vel"], why=n.get("why")) for n in notes if 0 <= n["frame"] < N and not n["limb"]]
    for h in "LR":
        for f in range(N):
            r = raw[f][h][3]; p = kit.P[r["piece"]]; out["height"][h].append(round(float(tips[h][f][2]), 4))
    out["kit"] = kit.export(); out["chart"] = dict(bars=C["bars"], t0=C["t0"], dur=C["dur"], lead=C["lead"], bar_s=C["bar_s"], names=C["names"], song=C["song"])
    out["rest"] = dict(names=rg.names, parent=[rg.parent[n] for n in rg.names], head=[[float(x) for x in rg.HEAD[n]] for n in rg.names], tail=[[float(x) for x in rg.TAIL[n]] for n in rg.names])
    # ---- report
    rep = dict(frames=N, fps=fps, sync={}, velocity_lift={}, collisions={}, limits={})
    for limb, rows in per.items():
        e = [r["err"] for r in rows if r["err"] is not None]; ms = [r["miss_mm"] for r in rows]
        rep["sync"][limb] = dict(notes=len(rows), on_frame=sum(1 for x in e if x == 0), within_1=sum(1 for x in e if abs(x) <= 1), mean_abs_err_frames=round(float(np.mean(np.abs(e))), 3) if e else None,
                                 no_event=sum(1 for r in rows if r["err"] is None), worst=[(r["frame"], r["note"], r["err"], r["miss_mm"]) for r in sorted(rows, key=lambda r: -(abs(r["err"]) if r["err"] is not None else 9) - (r["miss_mm"] / 1000 if limb in "LR" else 0))[:4]],
                                 tip_miss_mm_mean=round(float(np.mean(ms)), 1) if limb in ("L", "R") else None, tip_miss_mm_max=max(ms) if limb in ("L", "R") else None)
    hv = [(r["vel"], r["lift_mm"]) for r in hits if r["limb"] in "LR" and not r.get("sweep") and r["zone"] != "cross"]
    if hv:
        v, l = np.array(hv).T; bins = [(1, 40), (40, 70), (70, 90), (90, 105), (105, 128)]
        rep["velocity_lift"] = dict(formula="lift = 0.025 + 0.30 (v/127)^1.6 m, capped by 0.03 + 1.5 x gap s; downstroke 0.11 - 0.04 v/127 s", pearson_r=round(float(np.corrcoef(v, l)[0, 1]), 3),
                                    bins=[dict(vel=f"{a}-{b - 1}", n=int(((v >= a) & (v < b)).sum()), lift_mm_mean=round(float(l[(v >= a) & (v < b)].mean()), 1) if ((v >= a) & (v < b)).any() else None,
                                               intended_mm=round(lift_h((a + b) / 2) * 1000)) for a, b in bins])
    kinds = {}
    for f, k, a, b, d in col_rows:
        e = kinds.setdefault(k, dict(frames=set(), pairs={})); e["frames"].add(f); pr = e["pairs"].setdefault(f"{a} x {b}", [0, 0.0]); pr[0] += 1; pr[1] = max(pr[1], d)
    rep["collisions"] = {k: dict(frames=len(e["frames"]), pairs={p: dict(frames=c, max_mm=round(m * 1000, 1)) for p, (c, m) in sorted(e["pairs"].items(), key=lambda kv: -kv[1][0])}) for k, e in kinds.items()}
    rep["collisions"]["frames_with_any"] = len({r[0] for r in col_rows})
    rep["limits"] = {k: int(sum(k in l for l in out["limits"])) for k in sorted({x for l in out["limits"] for x in l})}
    rep["elbow_deg_range"] = {s: [min(a[s]["elbow"] for a in out["angles"]), max(a[s]["elbow"] for a in out["angles"])] for s in "LR"}
    rep["unplayed"] = out["notes_unplayed"]; out["report"] = rep
    json.dump(out, open(A.out, "w"), separators=(",", ":"))
    if A.report: json.dump(rep, open(A.report, "w"), indent=1)
    print(json.dumps(rep, indent=1))


if __name__ == "__main__": main()
