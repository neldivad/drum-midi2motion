#!/usr/bin/env python3
# midi2motion: vendored from nelvids/lab/wrapped/3d/2026-11-16-rig-foundations/tools/keys_plan.py (a wrapped lab, read-only source). Solver behaviour unchanged; only data paths and the lab command line were changed.
"""keys_plan.py: the planning pass for a keyboard hand (D1): from the chart's raw per-frame targets (chart_play.py's wrist, direction, up, curl,
captured by targets.piano) to targets the solver can take as they are (S-TGT-1), with the strike led by the wrist and fingers.

The raw targets stop the WRIST dead on every key (accelerations of 200-340 m/s^2) and ask the hand for orientations the wrist cannot take.
This pass keeps what the chart decided (which key, when, how hard) and re-plans how the arm gets there:

1. the FINGERTIP keeps the chart's strike: its path is the chart's, pinned on every hit frame and while a key is held (a light whole-clip
   minimum-jerk fit, so it is only rounded inside a frame or two);
2. the WRIST is a smooth whole-clip minimum-jerk curve near the chart's wrist, its smoothing raised until its acceleration is inside
   C-TGT-1's bound: the arm arrives over the key early and does not stop dead;
3. the HAND pitches about the wrist (its own side axis) so the fingertips are exactly at the fingertip path's HEIGHT (closed form, as the
   stick's alpha). The fingertip may slide a little ALONG its key while the hand pitches; across the keys it is checked by the sync
   audit (lane offset). So the fast part of a strike is the wrist joint's, not the forearm's: the same distal rule as the drum stroke;
4. FEEDBACK (S-IK-5): where the solver reports that the wrist cannot take the hand's orientation (the ellipse, the twist budget), the planner
   replaces the hand target by the nearest orientation the arm CAN take (the solved one, smoothed over the whole clip) and plans again.
   The fingertips stay on their keys; the hand gives up the roll or the bend it never had.
"""
import numpy as np
import arm_rig as AR
from arm_rig import CFG, HZ


def pitch_to(Hb, tl, W, pad_z):
    """turn the hand about its own side axis, through the wrist, until the fingertip point is at height pad_z (closed form) -> H, the angle (rad), frames it could not reach"""
    v = np.einsum("nij,nj->ni", Hb, tl); sx = Hb[:, :, 0]; a = v[:, 2]; b = np.cross(sx, v)[:, 2]; c = sx[:, 2] * AR.dot(sx, v); q = pad_z - W[:, 2]; rho = np.hypot(a - c, b); x = (q - c) / rho
    th = np.arcsin(np.clip(x, -1, 1)) - np.arctan2(a - c, b); return AR.rv(sx * th[:, None]) @ Hb, th, np.abs(x) > 1


def smooth_rot(H, lam, w=None):
    M = AR.minjerk_fit(H.reshape(len(H), 9), lam, w).reshape(-1, 3, 3); return AR.hand_matrix(M[:, :, 1], M[:, :, 2])


def interior(rig, out, shrink=0.86, twist_guard=5.0):
    """the solved hand, pulled a little INSIDE the wrist's limits (so a smoothed copy of it does not graze them again): -> hand matrices, character space"""
    ch = {k: np.radians(v) for k, v in out["ch"].items() if k != "swivel"}; e = np.sqrt(np.maximum(out["flags"]["wrist_ellipse"], 1e-9)); k = np.minimum(1.0, shrink / np.maximum(e, 1e-6))
    lo, hi = CFG["limits"]["pron"]["hard"]; ch["wrist_flex"] = ch["wrist_flex"] * k; ch["wrist_dev"] = ch["wrist_dev"] * k; ch["wrist_twist"] = np.clip(ch["wrist_twist"], -np.radians(4), np.radians(4))
    ch["pron"] = np.clip(ch["pron"], np.radians(lo + twist_guard), np.radians(hi - twist_guard)); return rig.rot_char(rig.fk(ch)["H"])


def plan(rig, tg, tl_of, max_iter=6, lam_pad=0.4, Hb=None):
    N = tg["N"]; hitf = np.array([int(round((n["t"] - tg["half"]) * HZ)) for n in tg["notes"]]); hitf = hitf[(hitf >= 0) & (hitf < N)]
    w = np.ones(N) + 30.0 * (tg["pad"][:, 2] <= tg["pad_z"] + 0.001); w[hitf] = 600.0
    ws = np.ones(N); ws[hitf] = 25.0                                            # the wrist is only held NEAR the chart's wrist on a hit (the hand's pitch does the rest)
    pad = AR.minjerk_fit(tg["pad"], lam_pad, w); curl = AR.minjerk_fit(tg["curl"], 4.0); tl = tl_of(curl); Hb = AR.hand_matrix(AR.minjerk_fit(tg["dir"], 8.0), AR.minjerk_fit(tg["up"], 8.0)) if Hb is None else Hb; hist = []
    for it in range(max_iter):
        Wb = pad - np.einsum("nij,nj->ni", Hb, tl); lam = 2.0
        if tg.get("w_floor") is not None: Wb = tg["w_floor"](Wb)                 # R-417: the wrist rides over the console's rim, never through it (the hand's pitch, below, keeps the fingertips on their keys)
        for _ in range(40):
            W = AR.minjerk_fit(Wb, lam, ws)
            if tg.get("w_floor") is not None: W = tg["w_floor"](W, hard=True)       # the smoothing may not undo the floor
            H, th, miss = pitch_to(Hb, tl, W, pad[:, 2]); acc = np.linalg.norm(np.diff(W, 2, axis=0), axis=1) * HZ * HZ
            if acc.max() <= 0.9 * CFG["target"]["accel_m_s2"]: break
            lam *= 1.5
        out = rig.solve(W, H); fl = out["flags"]; cl = fl["swing_clamp"] | fl["twist_clamp"]; hist.append(dict(pass_=it + 1, lam=round(lam, 1), clamp_frames=int(cl.sum()), ori_err_max_deg=round(float(fl["ori_err_deg"].max()), 1), wrist_accel_max=round(float(acc.max()), 1), pitch_deg=[round(float(np.degrees(th).min()), 1), round(float(np.degrees(th).max()), 1)], pitch_unreachable=int(miss.sum())))
        if cl.mean() <= 0.002 or it == max_iter - 1: break
        Hb = smooth_rot(interior(rig, out), 6.0)                                # what the arm could do (a little inside its limits) becomes what is asked of it
    return dict(W=W, Hm=H, out=out, pad=pad, curl=curl, lam=lam, passes=hist, hitf=hitf, lam_pad=lam_pad, Hb=Hb, pitch=np.degrees(th))
