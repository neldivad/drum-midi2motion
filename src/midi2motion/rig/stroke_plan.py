#!/usr/bin/env python3
# midi2motion: vendored from nelvids/lab/wrapped/3d/2026-11-16-rig-foundations/tools/stroke_plan.py (a wrapped lab, read-only source). Solver behaviour unchanged; only data paths and the lab command line were changed.
"""stroke_plan.py: the drum planner for one hand (STANDARD.md §6, R-405): from the chart's strokes to SMOOTH targets for the arm solver plus
the stick's own motion in the grip. The solver (arm_rig.py) never moves these targets afterwards.

What comes from the sibling drum lab, by import (read-only): the tip envelope (`envelope`, `lift_h`, `down_t`: velocity -> preparation
height and downstroke time, R-402), the stroke list (`Hand`: strike points, sweeps) and the kit numbers. What is new here:

- THE GRIP (S-GRIP-1/2). The stick is its own rigid body: it crosses the palm diagonally and pivots on a fulcrum under the index finger with
  the thumb on top. Two DoF in the hand: pitch alpha about the fulcrum axis (normal to the stroke plane), yaw beta (the cone). The back
  fingers follow alpha: each one's curl is solved so it stays on the stick (a table over alpha), never a constant fist.
- THE STROKE IS DISTAL (S-GRIP-4). The tip's height envelope is split into four smooth parts: an arm lift (elbow and shoulder: small, more
  for loud slow strokes), a forearm rotation, a wrist swing (both whole-clip minimum-jerk curves, pinned low at every contact) and alpha,
  which is then solved in closed form per frame so the tip is exactly on the envelope. So the snap of the downstroke and the rebound live in
  the stick (alpha reverses at the contact, S-GRIP-5), the wrist leads, and the arm stays quiet.
- THE WRIST PATH is a minimum-jerk curve through the contact poses (arm_rig.minjerk_fit, pinned on the hit frames), its smoothing weight
  raised until the wrist target's acceleration is under C-TGT-1's bound. At each contact the wrist is where it must be for the tip to be on the
  strike point, in closed form (no closed-loop correction of the arm around a pinned tip: that was the "spasm").
- WAITING (R-406): in a rest the stick bobs on the beat (a 2 cm dip of the tip peaking on each beat), carried by the wrist and fingers.
- Where the wrist sits for each drum (the stick's heading) is a per-piece choice of the planner: the heading whose static pose is most
  comfortable (reach, wrist near neutral-ulnar, shoulder), probed with the rig at the prior's swivel. Not a per-frame search.
"""
import math, pathlib, sys
import numpy as np
from scipy.spatial.transform import Rotation as Rot, Slerp
HERE = pathlib.Path(__file__).resolve().parent; SIB = HERE / "sibling"         # midi2motion: the sibling modules (kit, rig, drum_perf) are packaged beside the rig
sys.path.insert(0, str(HERE))
import arm_rig as AR
from arm_rig import CFG, unit, rv, cols, HZ

G = CFG["grip"]; ST = CFG["stick"]; Z = np.array([0, 0, 1.0])
R_TIP = ST["length"] * (1 - ST["fulcrum_from_butt"]); R_BUTT = ST["length"] * ST["fulcrum_from_butt"]
ZONE_PITCH = {"edge": 4, "closed": -8, "open": -8, "bow": -10, "bell": -16, "head": -12, "rimshot": -8, "cross": -3}
def mj(u): u = np.clip(u, 0, 1); return np.clip(u * u * u * (10 - 15 * u + 6 * u * u), 0.0, 1.0)      # 2026-11-20: the output clipped too; float rounding put u = 1 - eps at 1.0000000000000004 and Slerp refused it (Groove benchmark crash)


class Grip:
    """the stick in the hand, in the hand's own frame (x = y x z, y forward, z = back of the hand)"""
    def __init__(self, rig, preset=None, zeta=None, fulcrum=None, quick=False):
        self.quick = quick; self.rig = rig; sg = rig.sg; self.P = G["presets"][preset or G["preset"]]; z = math.radians(G["stick_in_hand_deg"] if zeta is None else zeta); fh = G["fulcrum_hand"] if fulcrum is None else fulcrum
        self.s0 = np.array([sg * math.sin(z), math.cos(z), 0.0]); self.f = np.array([sg * fh[0], fh[1], fh[2]])        # the thumb side is sg * x
        ro = math.radians(self.P["roll"]); d0 = np.array([0, -1.0, 0]); self.Rref = self.hand_frame(d0)                    # a level stick pointing forward
        self.ag = unit(self.Rref.T @ np.cross(d0, Z)); self.e2 = np.cross(self.ag, self.s0)                                # + alpha about ag lifts the tip
        yh = np.array([0, 1.0, 0]); aw = self.ag - yh * (self.ag @ yh); self.aw = unit(aw); self.e_w = float(self.aw @ self.ag); self.e_r = float(yh @ self.ag)   # the wrist's swing axis (no forearm twist in it) and how much of each lifts the tip
        self.thumb_abd = 0.0; self.als = np.array([0.0]); self.curl_fixed, self.back, self.report = (dict(thumb=0, index=0), {}, {}) if quick == "probe" else self.fit_fingers()

    def hand_frame(self, d0):
        """the hand's rotation (character space) that holds a stick pointing along d0 with the preset's roll"""
        sg = self.rig.sg; ro = math.radians(self.P["roll"]); d0 = unit(np.asarray(d0, float)); upp = unit(Z - d0 * (d0 @ Z)); lat = sg * np.cross(upp, d0); zw = math.cos(ro) * upp + math.sin(ro) * lat
        ez = np.array([0, 0, 1.0]); return cols(d0, np.cross(zw, d0), zw) @ cols(self.s0, np.cross(ez, self.s0), ez).T

    def sdir(self, al, be):
        al, be = np.asarray(al), np.asarray(be); return np.cos(be)[..., None] * (np.cos(al)[..., None] * self.s0 + np.sin(al)[..., None] * self.e2) + np.sin(be)[..., None] * self.ag

    # ---- the fingers on the stick
    def clearance(self, finger, c, al, abd=0.0):
        """signed gap (m) between one finger's capsules (curl c) and the stick's surface at pitch al, hand frame; and the tip's gap"""
        curl = [0.0] * 5; i = AR.FINGERS.index(finger); curl[i] = c; P, tips = self.rig.hand_bones(np.eye(3), np.zeros(3), curl, thumb_abd=abd); s = self.rig.s
        pts = [P[f"{finger}.{k:02d}.{s}"][:3, 3] for k in (1, 2, 3)] + [tips[finger]]; d = self.sdir(al, 0.0); a, b = self.f - R_BUTT * d, self.f + R_TIP * d; rr = CFG["capsules"]["finger_r"] + ST["radius"]
        ds = [AR.seg_seg(pts[k], pts[k + 1], a, b) for k in range(3)]; j = int(np.argmin([x[0] for x in ds]))
        return float(ds[j][0]) - rr, float(AR.seg_seg(pts[3], pts[3], a, b)[0]) - rr, ds[j][2]

    def contact_curl(self, finger, al, cmax=1.0, abd=0.0):
        """the smallest curl at which the finger touches the stick (it closes onto it and stops); if it never reaches, the curl of closest approach"""
        cs = np.arange(-0.3 if finger == "thumb" else 0.0, cmax + 1e-9, 0.02); g = np.array([self.clearance(finger, c, al, abd)[0] for c in cs]); hit = np.nonzero(g <= 0)[0]   # the thumb may also lift (extend) off a rising stick
        if len(hit) and hit[0] == 0: return float(cs[0]), float(g[0])              # already on the stick fully open: it cannot give way further (the overlap is reported)
        if len(hit) and hit[0] > 0:
            lo, hi = cs[hit[0] - 1], cs[hit[0]]
            for _ in range(12):
                m = 0.5 * (lo + hi); lo, hi = (lo, m) if self.clearance(finger, m, al, abd)[0] <= 0 else (m, hi)
            return hi, 0.0
        k = int(np.argmin(g)); return float(cs[k]), float(g[k])

    def fit_fingers(self):
        lo, hi = CFG["limits"]["stick_alpha"]["hard"]; als = np.array([float(lo), 0.0, 15.0, float(hi)]) if self.quick else np.arange(lo - 2, hi + 2.01, 1.0); back = {}; rep = {}
        ci, gi = self.contact_curl("index", 0.0); best = None
        for ab in np.radians(np.arange(-40, 41, 8.0)):                               # the thumb opposes the index: curl + CMC opposition (within +-40 deg), its pad on the stick as near the fulcrum as it reaches
            for c in np.arange(0.0, 1.11, 0.1):
                g_, gt_, pt_ = self.clearance("thumb", c, 0.0, ab); sc = (abs(g_) if g_ > 0 else 6 * abs(g_)) + 0.25 * float(np.linalg.norm(pt_ - self.f))
                if best is None or sc < best[0]: best = (sc, c, ab, g_)
        _, ct, self.thumb_abd, gt = best
        _, _, pi = self.clearance("index", ci, 0.0); _, _, pt = self.clearance("thumb", ct, 0.0, self.thumb_abd)
        rep["index"] = dict(curl=round(ci, 3), gap_mm=round(gi * 1000, 1), contact_from_fulcrum_mm=round(float(np.linalg.norm(pi - self.f)) * 1000, 1))
        rep["thumb"] = dict(curl=round(ct, 3), cmc_opposition_deg=round(math.degrees(self.thumb_abd), 1), gap_mm=round(gt * 1000, 1), contact_from_fulcrum_mm=round(float(np.linalg.norm(pt - self.f)) * 1000, 1))
        for fn in ("thumb", "index", "middle", "ring", "pinky"):
            cg = [self.contact_curl(fn, math.radians(a), abd=self.thumb_abd if fn == "thumb" else 0.0) for a in als]; c = np.array([x[0] for x in cg]); c = c if self.quick else np.convolve(np.pad(c, 2, mode="edge"), np.ones(5) / 5, mode="valid")   # a smooth table
            back[fn] = c; rep[fn] = dict(curl_at_alpha={int(a): round(float(c[list(als).index(a)]), 3) for a in (lo, 0, 15, hi)}, gap_mm_at_0=round(cg[list(als).index(0)][1] * 1000, 1))
        self.als = als; return dict(thumb=ct, index=ci), back, rep

    def curls(self, al_deg):
        """alpha (deg, array) -> curl[N,5] (thumb, index, middle, ring, pinky): the back fingers open as the tip rises"""
        al = np.asarray(al_deg, float); out = np.zeros(al.shape + (5,))
        for i, fn in enumerate(AR.FINGERS): out[..., i] = np.interp(al, self.als, self.back[fn])
        return out


def tip_plan(S, N, lead, beat_s, DP, kit):
    """the tip's target at 120 Hz from the stroke list (drum_perf.Hand.S): strike point A(t), surface normal n(t), height h(t), per-frame mode, the travel parameter"""
    t = np.arange(N) / HZ; A = np.zeros((N, 3)); nn = np.zeros((N, 3)); h = np.zeros(N); mode = np.empty(N, dtype=object); ia = np.zeros(N, int); ib = np.zeros(N, int); uu = np.zeros(N); sweep = np.zeros(N, bool)
    PU = G["pulse"]; beats = lead + beat_s * np.arange(-8, int(N / HZ / beat_s) + 8); pulse = np.zeros(N)
    for f in range(N):
        tt = t[f]; j = next((k for k, s in enumerate(S) if s["t"] > tt + 1e-9), None); i = (j - 1) if j is not None else len(S) - 1
        a = S[i] if i >= 0 else None; b = S[j] if j is not None else None; ia[f] = max(i, 0); ib[f] = j if j is not None else len(S) - 1
        if a is not None and a["kind"] == "sweep" and tt <= a["t_end"] + 1e-9:
            q = float(np.interp(tt, a["tk"], a["pk"])); A[f] = a["path"](q); nn[f] = kit.P[a["piece"]]["n"]; mode[f] = "sweep"; sweep[f] = True; ib[f] = i; uu[f] = 0; continue
        if a is None: a = dict(b, t=b["t"] - 2.0, t_end=b["t"] - 2.0, vel=40, kind="hit")
        if b is None: b = dict(a, t=a["t_end"] + 3.0, vel=40, kind="hit", A=a.get("A_end", a["A"]))
        Aa = a["A_end"] if a["kind"] == "sweep" else a["A"]; ta = a["t_end"]; g = b["t"] - ta; tau = tt - ta; Td = DP.down_t(b["vel"]); H = DP.lift_h(b["vel"]) * b.get("lift", 1.0)             # lift < 1: a stroke the chart marks as low (the cross-stick, played here as a low tap)
        hh = DP.envelope(tau, g, H, Td, 0.35 * DP.lift_h(a["vel"]), 0.05, hold_up=b.get("cres", False))
        dist = float(np.linalg.norm(b["A"] - Aa)); Tm = min(0.45, max(0.16, dist / 1.3)); ts = max(ta + 0.02, b["t"] - Td - 0.03 - Tm) if g > 0.34 else ta; te = b["t"] - min(Td, 0.5 * g) * (1.0 if g > 0.34 else 0.6)
        if te - ts < 0.03: ts, te = ta, b["t"] - 0.25 * min(Td, g)
        u = float(mj((tt - ts) / (te - ts))); hump = 4 * u * (1 - u) * min(0.07, 0.18 * dist) if dist > 0.05 else 0.0
        A[f] = Aa + (b["A"] - Aa) * u; nn[f] = unit(kit.P[a["piece"]]["n"] * (1 - u) + kit.P[b["piece"]]["n"] * u); h[f] = hh + hump; uu[f] = u
        # the phases the checks need: a stroke = the lift, the downstroke and the rebound; the rest is travel or waiting
        tl = g - Td - 0.035 - 0.17
        mode[f] = "stroke" if (g <= 0.34 or tau < 0.07 + 0.36 or tau > tl - 0.02) else ("travel" if 0.02 < u < 0.98 else "wait")
        if g >= PU["min_gap_beats"] * beat_s:                                     # R-406: keep time while waiting (only where the stick is settled at its ready height)
            for tb in beats:
                if ta + 0.30 < tb < b["t"] - (Td + 0.035 + 0.17 + 0.16): pulse[f] -= PU["height"] * math.exp(-0.5 * ((tt - tb) / PU["sigma_s"]) ** 2)
    kc = np.array([int(round(s["t"] * HZ)) for s in S]); kc = kc[(kc >= 0) & (kc < N)]; w = np.ones(N); w[kc] = 2000.0; w[sweep] = 2000.0
    h = AR.minjerk_fit(h, 0.25, w)                                                # the sibling's envelope has acceleration steps in the air; this keeps its shape and its contact kinks (pinned), nothing else
    return dict(t=t, A=A, n=nn, h=h + pulse, mode=mode, ia=ia, ib=ib, u=uu, sweep=sweep, pulse=pulse)


def homes(rig, grip, S):
    """per stroke: the stick's heading at contact -> the hand's contact attitude. A per-piece planner choice (cached), probed with a static pose"""
    cache = {}
    for s in S:
        key = (s["piece"], s["zone"], tuple(np.round(s["A"], 3)))
        if key not in cache:
            best = None; Sh = rig.to_char(rig.sh0); az0 = math.atan2(*(s["A"] - Sh)[[1, 0]]); pr = None
            for al in np.radians(ZONE_PITCH.get(s["zone"], -12) + np.array([-8.0, 0.0, 8.0, 16.0])):
                for daz in np.radians(np.arange(-70, 71, 5.0)):
                    az = az0 + daz; d0 = np.array([math.cos(az) * math.cos(al), math.sin(az) * math.cos(al), math.sin(al)]); R = grip.hand_frame(d0)
                    W = s["A"] - R @ (grip.f + R_TIP * grip.sdir(math.radians(G["contact_alpha"]), 0.0)); p0 = math.degrees(float(rig.prior(rig.shoulder(np.zeros(1), np.zeros(1))[0], rig.to_chest(W)[None])[0]))
                    for dphi in (0.0, 20.0, 40.0):                               # the elbow may lift for a high or far piece: the probe tries the prior's swivel and two raised ones (the clip's plan then decides)
                        q = rig.solve_one(W, R, math.radians(p0 + dphi))
                        cost = 60 * max(0, q["ratio"] - 0.86) ** 2 * 100 + 30 * max(0, 0.50 - q["ratio"]) ** 2 * 100 + ((q["flex"] - 8) / 25) ** 2 + ((q["dev"] - 18) / 12) ** 2 + 40 * max(0, math.sqrt(q["ellipse"]) - 0.7) ** 2
                        cost += AR.band_pen(q["pron"], CFG["limits"]["pron"], 2, 40) + sum(AR.band_pen(q[k], CFG["limits"][k], 2, 40) for k in ("sh_flex", "sh_abd", "sh_twist")) + 0.3 * (daz / 0.6) ** 2 + 0.2 * (dphi / 40) ** 2
                        if best is None or cost < best[0]: best = (cost, R, d0, q)
            cache[key] = best
        s["R"], s["d0"], s["probe"] = cache[key][1], cache[key][2], cache[key][3]
        if s["kind"] == "sweep": s["R_end"] = s["R"]
    return S


def plan(rig, S, N, lead, beat_s, DP, kit, accel_max=None, grip=None, wscale=None, Rb=None, homes_done=False):
    """-> everything the solver and the bake need for one hand, all at 120 Hz. homes_done: the full-body planner (body_plan.py) has already chosen each stroke's contact attitude with the trunk"""
    grip = grip or Grip(rig); S = S if homes_done else homes(rig, grip, S); T = tip_plan(S, N, lead, beat_s, DP, kit); out = None; scale = np.ones(N); hi_deg = CFG["limits"]["stick_alpha"]["hard"][1]
    for it in range(4):                                                             # planner feedback (S-GRIP-2): where the envelope asks the grip for more than its cone, that stroke's lift is lowered, and the plan redone
        out = _plan(rig, grip, S, dict(T, h=T["h"] * scale), N, accel_max, wscale, Rb); kc = sorted(set([0, N - 1] + [int(c) for c in out["kc"] if 0 <= c < N])); worst = 0.0
        for a_, b_ in zip(kc[:-1], kc[1:]):
            m = float(out["alpha_free"][a_:b_ + 1].max()); worst = max(worst, m)
            if m > hi_deg - 1.0: scale[a_:b_ + 1] *= max(0.45, 0.93 * (hi_deg - 1.0) / m)
        out["lift_scale_min"] = float(scale.min()); out["plan_passes"] = it + 1
        if worst <= hi_deg - 1.0: break
    return out


def _plan(rig, grip, S, T, N, accel_max=None, wscale=None, Rb_in=None):
    t = T["t"]; A, nn, h = T["A"], T["n"], T["h"]; P = grip.P
    accel_max = accel_max or 0.92 * CFG["target"]["accel_m_s2"]
    kc = np.array([int(round(s["t"] * HZ)) for s in S]); ok = (kc >= 0) & (kc < N)
    # the hand's base attitude: the contact attitudes, slerped along the same travel curve as the strike point
    Rb = np.zeros((N, 3, 3))
    for f in range(N):
        a, b = S[T["ia"][f]], S[T["ib"][f]]
        Rb[f] = a["R"] if (T["sweep"][f] or T["ia"][f] == T["ib"][f]) else Slerp([0, 1], Rot.from_matrix(np.stack([a["R"], b["R"]])))(T["u"][f]).as_matrix()
    if Rb_in is not None: Rb = Rb_in
    # shares (S-GRIP-4): the next stroke's loudness and the time there is decide how much the arm carries
    vel = np.array([S[j]["vel"] for j in T["ib"]], float); gap = np.array([S[j]["t"] - (S[i]["t_end"] if i != j else S[j]["t"] - 1.0) for i, j in zip(T["ia"], T["ib"])])
    loud = np.clip((vel - 60) / 50, 0, 1); slow = np.clip((gap - 0.20) / 0.30, 0, 1); s_arm = G["arm_share"]["base"] + G["arm_share"]["loud_slow"] * loud * slow
    k = np.exp(-0.5 * (np.arange(-36, 37) / 12.0) ** 2); k /= k.sum(); sm = lambda x: np.convolve(np.pad(x, 36, mode="edge"), k, mode="valid")
    hs = np.maximum(h, 0.0); h_arm = sm(sm(s_arm) * hs)                                                    # the arm's lift: a slow, zero-phase share of the envelope
    lever = float(np.linalg.norm(grip.f + R_TIP * grip.s0)); Th = np.arcsin(np.clip((h - h_arm) / lever, -0.3, 0.95))
    pin = np.ones(N); pin[kc[ok]] = 400.0; tgt_w = P["wrist"] * Th / grip.e_w; tgt_r = (P["forearm_rot"] * Th / grip.e_r) if abs(grip.e_r) > 0.2 else np.zeros(N)
    if wscale is not None: tgt_w, tgt_r = tgt_w * wscale, tgt_r * wscale                                   # planner feedback (S-IK-5): where the wrist ran onto its ellipse, the fingers take more of the stroke
    tgt_w[kc[ok]] = math.radians(1.5); tgt_r[kc[ok]] = 0.0
    psi = AR.minjerk_fit(tgt_w, 40.0, pin); rho = AR.minjerk_fit(tgt_r, 40.0, pin)                         # wrist swing and forearm rotation: smooth, low at every contact
    Rrp = rv(np.array([0, 1.0, 0]) * rho[:, None]) @ rv(grip.aw * psi[:, None]); Rh = Rb @ Rrp
    # contacts: alpha so the stick meets the head at its contact attitude; the wrist exactly where that puts the tip on the strike point
    al_c = np.clip(math.radians(G["contact_alpha"]) - grip.e_w * psi - grip.e_r * rho, math.radians(-9.5), math.radians(10))
    Wc = A - np.einsum("nij,nj->ni", Rh, grip.f + R_TIP * grip.sdir(al_c, np.zeros(N)))                    # the wrist that would put the tip on A(t) with the contact alpha
    W_raw = Wc + nn * h_arm[:, None]; pinw = np.ones(N); pinw[kc[ok]] = 3000.0; pinw[T["sweep"]] = 60.0
    for s in S:                                                                                            # exact at the hit frames (the arm's lift is not zero there: fold it into the pin)
        f = int(round(s["t"] * HZ))
        if 0 <= f < N: W_raw[f] = Wc[f]
    W_raw[T["sweep"]] = Wc[T["sweep"]]
    lam = 5.0; W = W_raw
    for _ in range(40):                                                                                    # S-TGT-1: raise the smoothing until the wrist target's acceleration is inside the bound
        W = AR.minjerk_fit(W_raw, lam, pinw); acc = np.linalg.norm(np.diff(W, 2, axis=0), axis=1) * HZ * HZ
        if acc.max() <= accel_max: break
        lam *= 1.6
    # the stick in the grip: alpha in closed form so the tip is on the height envelope; beta aims along a sweep
    F = W + np.einsum("nij,j->ni", Rh, grip.f); e1 = np.einsum("nij,j->ni", Rh, grip.s0); e2 = np.einsum("nij,j->ni", Rh, grip.e2); c1, c2 = AR.dot(nn, e1), AR.dot(nn, e2)
    q = (h - AR.dot(nn, F - A)) / R_TIP; r0 = np.hypot(c1, c2); al = np.arcsin(np.clip(q / r0, -1, 1)) - np.arctan2(c1, c2); be = np.zeros(N)
    if T["sweep"].any():
        v = unit(np.einsum("nji,nj->ni", Rh, A - F)); sw = T["sweep"]; al[sw] = np.arctan2(v[sw] @ grip.e2, v[sw] @ grip.s0); be[sw] = np.arcsin(np.clip(v[sw] @ grip.ag, -1, 1))
        edge = np.convolve(sw.astype(float), np.ones(13) / 13, mode="same"); bl = AR.minjerk_fit(be, 3.0); be = np.where(sw, be, bl * (edge > 0))   # the yaw eases in and out of the sweep
    lo, hi = np.radians(CFG["limits"]["stick_alpha"]["hard"]); bl_, bh_ = np.radians(CFG["limits"]["stick_beta"]["hard"]); al_free = al.copy(); al = np.clip(al, lo, hi); be = np.clip(be, bl_, bh_)
    sd = np.einsum("nij,nj->ni", Rh, grip.sdir(al, be)); tip = F + R_TIP * sd; butt = F - R_BUTT * sd
    return dict(grip=grip, S=S, T=T, W=W, W_raw=W_raw, Hm=Rh, Rb=Rb, alpha=np.degrees(al), alpha_free=np.degrees(al_free), beta=np.degrees(be), psi=np.degrees(psi), rho=np.degrees(rho), h_arm=h_arm, s_arm=s_arm,
                tip=tip, butt=butt, F=F, tip_target=A + nn * h[:, None], curls=grip.curls(np.degrees(al)), lam=lam, kc=kc, lever=lever, lever_tip=R_TIP, Rrp=Rrp)


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "design":
    # the grip's geometry search: where the stick sits so the index seats the fulcrum, the thumb reaches it and the back fingers can close on it
    rig = AR.ArmRig(); rows = []
    for zeta in (45, 50, 55, 60, 65):
        for fy in (0.080, 0.088, 0.096, 0.104):
            for fz in (-0.020, -0.026, -0.032):
                for fx in (0.022, 0.030, 0.038):
                    g = Grip(rig, zeta=zeta, fulcrum=[fx, fy, fz], quick=True); r = g.report
                    sc = abs(r["index"]["gap_mm"]) + r["index"]["contact_from_fulcrum_mm"] * 0.5 + abs(r["thumb"]["gap_mm"]) + r["thumb"]["contact_from_fulcrum_mm"] * 0.5 + sum(abs(r[f]["gap_mm_at_0"]) for f in ("middle", "ring", "pinky"))
                    rows.append((sc, zeta, fx, fy, fz, r["index"], r["thumb"], [r[f]["gap_mm_at_0"] for f in ("middle", "ring", "pinky")]))
    for r in sorted(rows, key=lambda r: r[0])[:8]: print(r)
