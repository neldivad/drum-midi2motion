#!/usr/bin/env python3
# midi2motion: vendored from nelvids/lab/wrapped/3d/2026-11-16-rig-foundations/tools/drums2/endpoints.py (a wrapped lab, read-only source). Solver behaviour unchanged; only data paths and the lab command line were changed.
"""endpoints.py: C-END-1, the world-space END-POINT check (R-441): stick tips, wrists, the hands' far ends (knuckles) and the feet, speed and acceleration per 120 Hz frame
against rig.yaml `endpoints` (hard caps; where each number comes from is written there). Also the shift rule the chart uses before any solve.

    R = endpoints.check(points, contacts)     points: {name: (N,3)} named tip.L, wrist.R, hand.L, ankle.R, toe.L ...; contacts: {name: [frames]} (a tip's or a foot's own hits)
    endpoints.shift_time(D)                    the shortest window a minimum-jerk hand shift of D metres fits in
"""
import math, pathlib, sys
import numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from arm_rig import CFG, HZ
EP = CFG["endpoints"]; KIND = dict(tip="tip", wrist="wrist", hand="hand", elbow="elbow", shoulder="shoulder", ankle="foot", toe="foot", heel="foot")
MJ_V, MJ_A = 1.875, 10 / math.sqrt(3)          # minimum jerk x = D (10 u^3 - 15 u^4 + 6 u^5): peak speed 1.875 D/T at u = 0.5, peak acceleration 5.7735 D/T^2 at u = 0.211, 0.789 (derived)


def kin(p, win=None):
    """-> smoothed path, speed (N-1,), acceleration (N-2,) in m/s, m/s2: the calibration's own measure (a `win`-frame mean, edges held)"""
    win = win or EP["smooth_frames"]; k = np.ones(win) / win; q = np.stack([np.convolve(np.pad(p[:, i], win // 2, mode="edge"), k, mode="valid") for i in range(3)], 1)
    return q, np.linalg.norm(np.diff(q, axis=0), axis=1) * HZ, np.linalg.norm(np.diff(q, 2, axis=0), axis=1) * HZ * HZ


def shift_time(D, caps=None):
    c = caps or EP["shift"]; return max(MJ_V * D / c["speed_m_s"], math.sqrt(MJ_A * D / c["accel_m_s2"]))


def check(points, contacts=None, every=4):
    """-> dict(ok, frames (any end point over a cap), by: {name: {...}}, over: {name: bool (N,)} per point for the R-417 loop)"""
    contacts = contacts or {}; rows = {}; over = {}; N = len(next(iter(points.values()))); anyo = np.zeros(N, bool)
    for name, p in points.items():
        c = EP[KIND[name.split(".")[0]]]; q, v, a = kin(np.asarray(p, float)); ex = np.zeros(N, bool); w = c.get("contact_exempt_frames", 0)
        for f in contacts.get(name, []):
            if 0 <= f < N: ex[max(0, f - w - 2):f + w + 3] = True                  # the smoothing window spreads a contact's reversal over +-2 more frames
        ov = np.zeros(N, bool); sv = v > c["speed_m_s"]; sa = (a > c["accel_m_s2"]) & ~ex[1:-1]; ov[:-1] |= sv; ov[1:-1] |= sa; over[name] = ov; anyo |= ov
        raw = np.linalg.norm(np.diff(np.asarray(p, float)[::every], axis=0), axis=1)
        rows[name] = dict(speed_max_m_s=round(float(v.max()), 2), speed_cap=c["speed_m_s"], speed_x_cap=round(float(v.max() / c["speed_m_s"]), 2), accel_max_m_s2=round(float(np.where(ex[1:-1], 0, a).max()), 1), accel_cap=c["accel_m_s2"],
                          accel_x_cap=round(float(np.where(ex[1:-1], 0, a).max() / c["accel_m_s2"]), 2), frames_over_speed=int(sv.sum()), frames_over_accel=int(sa.sum()), frames_over=int(ov.sum()), mm_per_30fps_frame_max=round(float(raw.max()) * 1000, 1),
                          accel_at_contact_max_m_s2=round(float(np.where(ex[1:-1], a, 0).max()), 1))
    fr = np.nonzero(anyo)[0]
    return dict(ok=not anyo.any(), note="C-END-1 (R-441): world-space speed and acceleration of every end point (stick tips, knuckles, wrists, elbows, shoulders, ankles, toes) against rig.yaml endpoints, 120 Hz on a 5-frame mean; a tip or a foot is exempt from the acceleration cap at its own contact",
                frames=[int(x) for x in fr][:400], n_frames=int(len(fr)), by=rows, worst=max(rows, key=lambda k: max(rows[k]["speed_x_cap"], rows[k]["accel_x_cap"])), over=over)


def summary(R):
    return {k: f"{v['speed_max_m_s']} m/s (x{v['speed_x_cap']}), {v['accel_max_m_s2']} m/s2 (x{v['accel_x_cap']}), {v['frames_over']} fr" for k, v in R["by"].items()}
