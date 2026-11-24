#!/usr/bin/env python3
# midi2motion: vendored from nelvids/lab/wrapped/3d/2026-11-16-rig-foundations/tools/body_plan.py (a wrapped lab, read-only source). Solver behaviour unchanged; only data paths and the lab command line were changed.
"""body_plan.py: what the body does while the hands play (STANDARD.md §9, S-IK-4, S-BODY-1, S-FOOT-*; R-389, R-402, R-406, R-412). Everything here is a
whole-clip plan at 120 Hz, made BEFORE the arms are solved, so the arm IK runs after the layers and no layer can break a contact.

L0 reach      reach_plan(): for every hit (stick tip or fingertip, either hand) the trunk posture (lean, side bend, turn, and when standing a pelvis shift) from which
              that hand reaches it comfortably. One choice per hit on a small grid (a planner-level choice, S-IK-8), aware of the other hand's hits near it in
              time; then ONE smooth curve through the choices (a non-causal minimum-jerk fit, pinned at the hit frames in proportion to need): the trunk arrives
              WITH the hand, it does not chase it.
L1 pulse      a dip that bottoms on each beat with a small rise before it; its size follows the loudest note on that beat (R-402); trunk lean, pelvis drop, head nod.
L2 breath     the chest opens and closes 15 times a minute.
L3 phrase     one weight shift per phrase (2 bars), at rest on the phrase boundaries: side bend, a little turn, the pelvis moving over the loaded side.
accents       a loud hit off the beat goes through the trunk as its own dip.
head          nod = the pulse; gaze = a turn toward the piece (or lane) the next travelling hand is going to, lead_s before the hit, with the trunk's own turn taken out.
feet (drums)  right: heel-up on the kick board, the ball planted on the board, the heel lifting with the beater's pull-back; left: heel-down on the hi-hat board,
              following the hat's openness from the MIDI; whenever the board is at rest (shut, or held open), a heel tap on 2 and 4 (the ball keeps the board where
              it is: no sound that is not in the audio). Planted contacts ride their board and never slide (S-FOOT-2).
"""
import math
import numpy as np
import arm_rig as AR, body_rig as BR
from arm_rig import CFG, HZ, unit, dot

BC = CFG["body"]; LY = BC["layers"]
def mj(u): u = np.clip(u, 0, 1); return np.clip(u * u * u * (10 - 15 * u + 6 * u * u), 0.0, 1.0)      # 2026-11-20: output clipped (as stroke_plan.mj)
def bump(t, t0, sigma): return np.exp(-0.5 * ((t - t0) / sigma) ** 2)


# ---------------------------------------------------------------- L1 / L2 / L3 / accents
def beat_weights(beats, notes, base=LY["pulse"]["base"], which=None):
    """the loudest note on each beat -> weight base..1"""
    w = []
    for tb in beats:
        v = [n["vel"] for n in notes if abs(n["tc"] - tb) < 0.03 and (which is None or which(n))]; w.append(base + (1 - base) * (max(v) / 127.0 if v else 0.0))
    return np.array(w)


def pulse(t, beats, w):
    """the keep-time dip (1 = full): bottoms ON the beat (C-IDLE-3), a small rise before it"""
    P = LY["pulse"]; out = np.zeros_like(t)
    for tb, wi in zip(beats, w): out += wi * (bump(t, tb, P["sigma_s"]) - P["lead_gain"] * bump(t, tb - P["lead_s"], 1.5 * P["sigma_s"]))
    return out


def layers(N, beats, bw, bar0, bar_s, accents=()):
    """-> additive channels (deg / m) and the per-layer curves the inspector draws"""
    t = np.arange(N) / HZ; P, B_, F, A_ = LY["pulse"], LY["breath"], LY["phrase"], LY["accent"]; pu = pulse(t, beats, bw)
    ac = np.zeros(N)
    for ta, va in accents: ac += (va - A_["vel_min"] + 20) / 47.0 * (bump(t, ta + 0.02, 0.06) - 0.4 * bump(t, ta - 0.14, 0.08))
    br = B_["chest_deg"] * np.sin(2 * np.pi * t / B_["period_s"])
    Tp = F["bars"] * bar_s; k = np.floor((t - bar0) / Tp); u = (t - bar0) / Tp - k; sway = np.where(k % 2 == 0, 1.0, -1.0) * (1 - 2 * mj(u))       # +1 at even phrase boundaries, -1 at odd ones, at rest on each
    sway = np.where(t < bar0, mj((t - (bar0 - Tp / 2)) / (Tp / 2)), sway) if bar0 > 0 else sway                                                      # eases in from neutral before the first bar
    shift = np.zeros((N, 3)); shift[:, 0] = F["shift_m"] * sway; shift[:, 2] = -P["drop_m"] * pu
    return dict(lean=P["lean_deg"] * pu + A_["lean_deg"] * ac, side=F["side_deg"] * sway, turn=F["turn_deg"] * sway, shift=shift, nod=P["nod_deg"] * pu + 0.6 * P["nod_deg"] * ac, breath=br,
                curves=dict(pulse=pu, accent=ac, breath=br, sway=sway))


# ---------------------------------------------------------------- L0: the trunk reaches with the hands
def reach_plan(body, A, kind, N, tool_max=None, boost=None, ahead=None):
    """A: {hand: (N,3)} where each hand's tool (stick tip, fingertips) is headed at every frame: the planners' own smooth travel curves, which arrive BEFORE the hit.
    ahead: {hand: [(t, point)]} that hand's coming hits: a hit less than ahead_s away already pulls the trunk (rising as it nears), so the trunk has left for a far
    piece while the hand is still finishing the stroke before it (the hand travels in 0.1-0.4 s; a trunk needs longer).
    -> the trunk's L0 channels (totals, neutral included): the least posture from which both hands are in comfortable reach, as a continuous function of time.
    Per frame the posture is a SOFT minimum over a small grid of postures (a weighted mean, weights exp(-cost / tau)): continuous in the targets, so there is no
    per-frame arg-min and no branch to flip (S-IK-8); then a zero-phase Gaussian (the standard's critically damped follow, S-BODY-1, without its lag) and a
    whole-clip minimum-jerk polish."""
    RP = BC["reach_plan"]; K = RP[kind]; ne = body.neutral; ax = [np.arange(*K[k]) for k in ("lean", "side", "turn", "shift")]; G = np.stack(np.meshgrid(*ax, indexing="ij"), -1).reshape(-1, 4); M = len(G)
    sh = np.zeros((M, 3)); sh[:, 0] = G[:, 3]; z = np.zeros(M); tmax = tool_max or K["tool_max"]
    T = body.trunk(dict(lean=ne["lean"] + G[:, 0], side=ne["side"] + G[:, 1], turn=ne["turn"] + G[:, 2], shift=sh, nod=z, tilt=z, look=z))["T"]["chest"]
    scale = np.array([RP["trunk_cost"][k] for k in ("lean", "side", "turn", "shift")]); tc = ((G / scale) ** 2).sum(1); g0 = int(np.argmin(tc)); fs = np.arange(0, N, 4); ts = fs / HZ; C = np.tile(tc, (len(fs), 1)); d0 = {}
    def hand_cost(h, pts, short=0.0):
        """pts (K,3) -> cost (K, M): too far, too near, too far across the body, too far out to the side"""
        sg = 1.0 if h == "L" else -1.0; S = BR.pt(T, AR.HEAD[f"upper_arm.{h}"]); v = pts[:, None, :] - S[None]; d = np.linalg.norm(v, axis=2); cross = -sg * (v * T[None, :, :3, 0]).sum(2)
        return (RP["w_over"] * (np.maximum(0, d - (tmax - short)) / 0.1) ** 2 + 0.33 * RP["w_over"] * (np.maximum(0, K["tool_min"] - d) / 0.1) ** 2 + RP["w_cross"] * (np.maximum(0, cross - RP["cross_free"]) / 0.1) ** 2
                + RP["w_out"] * (np.maximum(0, -cross - RP["out_free"]) / 0.1) ** 2), d
    for h, Ah in A.items():
        c, d = hand_cost(h, Ah[fs], boost[h][fs][:, None] if boost else 0.0); C += c; d0[h] = d[:, g0]       # boost: a hand dragging a sweep is planned as if its reach were shorter
        for t_s, A_s in (ahead or {}).get(h, []):
            w = 1 - (t_s - ts) / RP["ahead_s"]; w = np.where((w > 0) & (w < 1), w, 0.0)
            if w.any(): C += RP["ahead_gain"] * w[:, None] * hand_cost(h, np.asarray(A_s, float)[None])[0]
    W = np.exp(-(C - C.min(1, keepdims=True)) / RP["tau"]); W /= W.sum(1, keepdims=True); Y = W @ G; fr = np.arange(N); Y = np.stack([np.interp(fr, fs, Y[:, j]) for j in range(4)], 1)
    k = np.exp(-0.5 * (np.arange(-60, 61) / (RP["follow_s"] * HZ)) ** 2); k /= k.sum(); Y = np.stack([np.convolve(np.pad(Y[:, j], 60, mode="edge"), k, mode="valid") for j in range(4)], 1); raw = Y.copy()
    Y = AR.minjerk_fit(Y / scale, RP["smooth"]) * scale
    return dict(lean=ne["lean"] + Y[:, 0], side=ne["side"] + Y[:, 1], turn=ne["turn"] + Y[:, 2], shift_x=Y[:, 3], raw=raw, dist_neutral={h: np.interp(fr, fs, v) for h, v in d0.items()}, tool_max=tmax)


# ---------------------------------------------------------------- head: gaze leads to the next target
def gaze(body, events, trunk_turn, head_pos, N):
    """events: [dict(t, A, travel (m, how far that hand comes from), vel)] -> look (deg, the head's own turn on the chest), nod offset (deg, + down)"""
    Gz = BC["gaze"]; fr = np.arange(N); keys = []
    for e in sorted(events, key=lambda e: e["t"]):
        if e.get("travel", 1.0) < 0.12 and e.get("vel", 0) < 105: continue                                # a repeat on the same piece is not looked at again
        f = int(np.clip(round((e["t"] - Gz["lead_s"]) * HZ), 0, N - 1)); v = e["A"] - head_pos[f]; yaw = math.degrees(math.atan2(v[0], -v[1])); pit = math.degrees(math.atan2(-v[2], math.hypot(v[0], v[1])))
        if keys and f - keys[-1][0] < Gz["min_gap_s"] * HZ: continue                                                 # the eyes cannot dart faster than the hands in a fill: the first target of a run holds
        keys.append((f, yaw, pit))
    if not keys: return dict(look=np.zeros(N), nod=np.zeros(N), keys=[])
    kf = np.array([k[0] for k in keys]); yaw = np.interp(fr, kf, [k[1] for k in keys]); pit = np.interp(fr, kf, [k[2] for k in keys]); w = np.full(N, 0.05); w[kf] = 1.0
    look = np.clip(Gz["yaw_share"] * (AR.minjerk_fit(yaw, Gz["smooth"], w) - trunk_turn), -Gz["yaw_max"], Gz["yaw_max"]); nod = np.clip(Gz["pitch_share"] * AR.minjerk_fit(pit, Gz["smooth"], w), -Gz["pitch_max"], Gz["pitch_max"])
    return dict(look=AR.minjerk_fit(look, Gz["polish"]), nod=AR.minjerk_fit(nod, Gz["polish"]), keys=[dict(f=int(k[0]), yaw=round(k[1], 1), pitch=round(k[2], 1)) for k in keys], target_yaw=yaw)


# ---------------------------------------------------------------- drums: the pedals and the feet on them
def drum_pedals(DP, kit, notes, N, lead, beat_s):
    """-> beater (deg back from the head), hat openness 0..1, at 120 Hz; the same envelopes the sibling bake drives its kit with"""
    t = np.arange(N) / HZ; kicks = sorted([n for n in notes if n.get("zone") == "beater" and n["limb"]], key=lambda n: n["tc"]); be = np.zeros(N)
    for f, tt in enumerate(t):
        j = next((k for k, s in enumerate(kicks) if s["tc"] > tt + 1e-9), None); i = (j - 1) if j is not None else len(kicks) - 1
        ta, va = (kicks[i]["tc"], kicks[i]["vel"]) if i >= 0 else (tt - 2.0, 60); tb, vb = (kicks[j]["tc"], kicks[j]["vel"]) if j is not None else (tt + 3.0, 60)
        be[f] = DP.envelope(tt - ta, tb - ta, 22 + 34 * vb / 127.0, 0.085, 12 + 14 * va / 127.0, 20.0, unit=170.0)
    hatf = DP.hat_track([n for n in notes if n["note"] in (42, 44, 46)], N / HZ); ho = np.array([hatf(x) for x in t])
    return dict(beater=be, hat=ho, hatf=hatf, kicks=kicks, pedal=[n for n in notes if n.get("zone") == "pedal" and n["limb"]])


def drum_feet(body, kit, ped, N, lead, beat_s):
    """the two feet on their boards -> foot dicts (body_rig.Body.foot_on_board), heel angles, contact notes"""
    t = np.arange(N) / HZ; Kk, Hh = BC["kick"], BC["hat"]; be, ho = ped["beater"], ped["hat"]; kt = np.array([n["tc"] for n in ped["kicks"]]); beats = lead + beat_s * np.arange(-8, int(N / HZ / beat_s) + 8)
    # right foot: heel-up. The heel rides the beater's pull-back (louder = higher, R-402); in a long gap it keeps time with a small bounce on the beat
    heel = Kk["heel_base_deg"] + Kk["heel_per_beater_deg"] * AR.minjerk_fit(be, 0.5, 1 + 400.0 * ((np.abs(t[:, None] - kt[None, :]).min(1) < 0.6 / HZ) if len(kt) else np.zeros(N, bool))); idle = []      # 2026-11-20: a clip with no kick (a fill) has nothing to pin
    for tb in beats:
        if len(kt) == 0 or np.abs(kt - tb).min() > 0.45: heel = heel + Kk["idle_pulse_deg"] * bump(t, tb - 0.13, 0.06); idle.append(float(tb))      # up before the beat, back down on it
    fo = getattr(kit, "FOOT_OF", {"kick": "R", "hat": "L"}); ks = fo.get("kick", "R"); hs = "L" if ks == "R" else "R"; to = getattr(kit, "TURNOUT", {})       # drum round 2: which foot plays which pedal comes from the layout (a mirrored kit: the left foot kicks)
    hk = np.array([kit.ANKLE[ks][0], kit.ANKLE[ks][1] + 0.05, 0.012]); FR = body.foot_on_board(ks, hk, 0.36 * be, heel, to.get("kick", Kk["turnout_deg"]))
    # left foot: heel-down on the hat board; closed and free -> a heel tap that lands on 2 and 4
    busy = [n["tc"] for n in ped["pedal"]]; chick = np.zeros(N); taps = []
    for k, tb in enumerate(beats):
        b_in_bar = int(round((tb - lead) / beat_s)) % 4
        if b_in_bar not in (1, 3) or tb < 0.3 or tb > N / HZ - 0.05: continue
        f0, f1 = int(max(0, (tb - Hh["chick_rise_s"] - 0.05) * HZ)), int(min(N - 1, (tb + 0.12) * HZ))
        if np.ptp(ho[f0:f1 + 1]) > 0.02 or any(abs(x - tb) < 0.45 for x in busy): continue                # the board is moving (the hat opening or shutting, a pedal chick): the foot is at work, no tap. A hat HELD open still gets its tap: the ball holds the board where it is
        u = (t - (tb - Hh["chick_rise_s"])) / Hh["chick_rise_s"]; chick += np.where((u > 0) & (u < 1), Hh["chick_deg"] * np.where(u < 0.6, mj(u / 0.6), 1 - ((u - 0.6) / 0.4) ** 2), 0.0); taps.append(float(tb))
    hh = np.array([kit.ANKLE[hs][0] + (0.02 if hs == "L" else -0.02), kit.ANKLE[hs][1] + 0.05, 0.012]); FL = body.foot_on_board(hs, hh, Hh["plate_deg"] * ho, chick, to.get("hat", Hh["turnout_deg"]))
    return {ks: FR, hs: FL, "heel_deg": {ks: heel, hs: chick}, "taps": taps, "kick_idle_beats": idle, "plate_deg": {ks: 0.36 * be, hs: Hh["plate_deg"] * ho}, "kick_side": ks, "hat_side": hs}
