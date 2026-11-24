#!/usr/bin/env python3
# midi2motion: vendored from nelvids/lab/wrapped/3d/2026-11-16-rig-foundations/tools/body_checks.py (a wrapped lab, read-only source). Solver behaviour unchanged; only data paths and the lab command line were changed.
"""body_checks.py: the whole-body C-checks of STANDARD.md at 120 Hz (R-412: the body is judged as a whole; components stay inspector numbers).

The two arms are checked by the proof's own checks.run / checks.grip_checks (unchanged thresholds), each on the moving chest. This file adds what a full body adds:
  C-JT-1/2      trunk, head and leg channels against rig.yaml body.limits (hard: fail; comfort: a % of frames, warn above 20 %)
  C-CONT-1/2/3  speed ceilings (pelvis, spine bones, neck + head, hip, knee, ankle, toes), second differences <= 3 deg, the knee never faster than 1.5 x the ankle + 0.3 m/s
  C-IK-2 legs   hip-ankle distance beyond 0.97 x the leg is reported; the miss measured
  C-FOOT-1      a planted contact slides <= 5 mm (the ball on its board or the floor; the heel while it is down)
  C-FOOT-2      ankle hinge and roll, the MTP, inside their ranges (dorsiflexion + 10 deg while the knee is bent > 60 deg)
  S-BODY-1      seated: the pelvis stays on the throne (<= 2 cm); standing: the pelvis stays between the feet
  C-IDLE-1/2/3  no motion above max(4 Hz, 2 x beat) over 0.5 deg in the trunk and head (legs: away from their own events); no dead limb in any 2-bar window
                (six limbs: both arms, both legs, trunk, head); the keep-time pulse bottoms within one solved frame of the beat grid
  C-COL-1 body  everything the one-arm proof could not collide with: arm against arm, stick against stick, sticks and limbs against the kit and the body, legs against the kit
  sync          both hands on their strike points on frame; the kick's beater and the hat's pedal on their notes
"""
import math, pathlib, sys
import numpy as np
from scipy.signal import butter, filtfilt
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import arm_rig as AR, body_rig as BR, checks
from arm_rig import CFG, HZ
from checks import res, runs, r1, r2

BC = CFG["body"]; LM = BC["limits"]; CE = BC["ceilings"]; MARGIN = CFG["margin_deg"]; EV = CFG["render_every"]
LEG = ("hip_flex", "hip_abd", "hip_twist", "knee", "ankle", "ankle_roll", "foot_yaw", "toes")
def lim_of(k):
    k = k[:-2] if k.endswith(("_L", "_R")) else k; return LM[k.replace("chest_", "spine_")]
def ang_speed(R): M = np.swapaxes(R[:-1], 1, 2) @ R[1:]; return np.degrees(np.arccos(np.clip((np.trace(M, axis1=1, axis2=2) - 1) / 2, -1, 1))) * HZ


def body_channels(P):
    ch = dict(P["K"]["ch"])
    for s in "LR":
        for k in LEG + ("knee_swivel",): ch[f"{k}_{s}"] = P["legs"][s]["ch"][k]
    return ch


def body_speeds(P):
    T = P["T"]; R = {b: T[b][:, :3, :3] for b in T}; rel = lambda a, b: np.swapaxes(R[a], 1, 2) @ R[b]; sp = dict(pelvis=ang_speed(R["hips"]), spine=ang_speed(rel("hips", "spine")), chest=ang_speed(rel("spine", "chest")), head=ang_speed(rel("chest", "head")))
    for s in "LR":
        L = P["legs"][s]; sp[f"hip_{s}"] = ang_speed(np.swapaxes(R["hips"], 1, 2) @ L["R"]["thigh"]); sp[f"knee_{s}"] = np.abs(np.diff(L["ch"]["knee"])) * HZ; sp[f"ankle_{s}"] = ang_speed(np.swapaxes(L["R"]["shin"], 1, 2) @ L["R"]["foot"])
        sp[f"toes_{s}"] = np.abs(np.diff(L["ch"]["toes"])) * HZ
    return sp


def solid_pen(pts, rad, solid):
    """penetration depth (m) of spheres (pts (...,3), rad) in a kit solid (the sibling's drum_perf.solid_pen, vectorised)"""
    _, c, n, r, depth = solid; x = pts - c; ax = -(x @ n); radial = np.linalg.norm(x + n * ax[..., None], axis=-1); inside = (ax > -rad) & (ax < depth + rad) & (radial < r + rad)
    return np.where(inside, np.minimum(np.minimum(ax + rad, r + rad - radial), depth + rad - ax), 0.0)


def collisions(P, perfs, kind):
    """world-space penetration (m) per 120 Hz frame for the pairs the per-arm check does not see -> depth (N,), pairs {name: (frames, max)} , rows for the fails"""
    N = P["N"]; dep = np.zeros(N); pairs = {}; pm = CFG["penetration_mm"] / 1000
    def add(name, d, lim=0.0):
        d = np.maximum(d - lim, 0.0); np.maximum(dep, d, out=dep)
        if (d > pm).any(): pairs[name] = dict(frames=int((d > pm).sum()), max_mm=r1(d.max() * 1000), first=int(np.argmax(d > pm)))
    caps = {h: checks.capsules(perfs[h]) for h in "LR"}
    for na, a0, a1, ra in caps["L"][1:]:
        for nb, b0, b1, rb in caps["R"][1:]: d, _, _ = AR.seg_seg(a0, a1, b0, b1); add(f"{na}.L x {nb}.R", ra + rb - d)
    if kind == "drums":
        kit = P["d"]["kit"]; st = {h: perfs[h]["stick"] for h in "LR"}; sr = CFG["stick"]["radius"]; solids = kit.solids(); u = np.linspace(0.34, 1.0, 24)[None, :, None]
        d, _, _ = AR.seg_seg(st["L"]["F"], st["L"]["tip"], st["R"]["F"], st["R"]["tip"]); add("stick.L x stick.R", 2 * sr - d)
        for h, o in (("L", "R"), ("R", "L")):
            pts = st[h]["butt"][:, None, :] + (st[h]["tip"] - st[h]["butt"])[:, None, :] * u; struck = {p["id"]: np.zeros(N, bool) for p in kit.PIECES}
            for s in P["arms"][h]["S"]:
                a_, b_ = max(0, int(round(s["t"] * HZ)) - 5), min(N, int(round(s["t_end"] * HZ)) + 6)
                if b_ > a_: struck[s["piece"]][a_:b_] = True      # 2026-11-20: a stroke before the clip (t_end < -5 frames) gave a NEGATIVE end, which Python read from the end of the array: its piece was exempt for nearly the whole clip
            for so in solids: add(f"stick.{h} x {so[0]}", solid_pen(pts, sr, so).max(1), np.where(struck[so[0]], 0.022, 0.0))         # a struck piece allows the stick 22 mm (round 1's measure, as the proof)
            for n_, a, b, r in P["caps"]:
                d, _, _ = AR.seg_seg(st[h]["F"], st[h]["tip"], a, b); add(f"stick.{h} x {n_}", r + sr - d)
            for n_, a, b, r in caps[o][1:]:
                d, _, _ = AR.seg_seg(st[h]["F"], st[h]["tip"], a, b); add(f"stick.{h} x {n_}.{o}", r + sr - d)
            for n_, a, b, r in caps[h][1:]:
                q = a[:, None, :] + (b - a)[:, None, :] * np.linspace(0, 1, 6)[None, :, None]
                for so in solids: add(f"{n_}.{h} x {so[0]}", solid_pen(q, r * 0.8, so).max(1))
        for n_, a, b, r in P["caps"]:
            if not n_.startswith(("thigh", "shin")): continue
            q = a[:, None, :] + (b - a)[:, None, :] * np.linspace(0, 1, 6)[None, :, None]
            for so in solids:
                if n_.startswith("shin") and so[0] == "kick": continue                    # the kick's pedal stands in front of the batter head: the shin is meant to be there (as round 1)
                add(f"{n_} x {so[0]}", solid_pen(q, r * 0.8, so).max(1))
    return dep, pairs


def drum_sync(P, perfs):
    """round 1's measure on both stick tips at 30 fps: on the strike point (<= 15 mm) on the note's frame +-1; then the pedals"""
    d = P["d"]; kit = d["kit"]; rows = []
    for h in "LR":
        ch_ = {(x["t"], x["piece"]): x["change"] for x in d.get("resticked", []) if x["hand"] == h}; other = "L" if h == "R" else "R"; tips = {x: perfs[x]["stick"]["tip"][::EV] for x in "LR"}; M = len(tips[h])
        for n in d["notes"][h]:
            f = n["frame"]; p = kit.P[n["piece"]]; c_ = ch_.get((round(n["tc"], 3), n["piece"])); hh = h; tip = tips[h]
            if c_ and c_.startswith("left"): rows.append(dict(frame=f, limb=h, note=n["note"], vel=n["vel"], piece=n["piece"], left_to_other_hand=True, err=0, miss_mm=0.0, ok=True)); continue
            if c_: hh = other; tip = tips[other]                                             # re-dealt to the other hand: judged on the stick that plays it
            A_ = n["A_strike"] if (n.get("A_strike") is not None and hh == h) else kit.strike_point(n["piece"], n["zone"], hh, d["gap"](n["tc"]) if n["piece"] == "hat" else 0.0)      # 2026-11-20: a scattered stroke is judged where it was aimed
            if n.get("art", {}).get("kind") == "sweep" and n["art"]["i"] > 0:
                rr = float(np.linalg.norm((tip[f] - p["c"]) - p["n"] * float((tip[f] - p["c"]) @ p["n"]))); surf = kit.BELL_H * max(0.0, 1 - rr / kit.BELL_R); m = abs(float((tip[f] - p["c"]) @ p["n"]) - surf) * 1000
                rows.append(dict(frame=f, limb=h, note=n["note"], vel=n["vel"], piece=n["piece"], err=0, miss_mm=r1(m), sweep=True, ok=m <= 15)); continue
            w = list(range(max(0, f - 3), min(M, f + 4))); dist = lambda ff: float(np.linalg.norm(tip[ff] - A_)); on = [ff for ff in w if dist(ff) < 0.015]; fm = min(on, key=lambda ff: abs(ff - f)) if on else min(w, key=dist)
            rows.append(dict(frame=f, limb=hh, note=n["note"], vel=n["vel"], piece=n["piece"], zone=n["zone"], err=fm - f, miss_mm=r1(dist(f) * 1000), ok=abs(fm - f) <= 1 and dist(f) <= 0.015, dealt_from=h if hh != h else None))
    be = P["ped"]["beater"]; ho = P["ped"]["hat"]; N = P["N"]
    for n in d["all_notes"]:
        f = int(round(n["tc"] * HZ))
        if n.get("zone") == "beater" and n["limb"] and 0 <= f < N: rows.append(dict(frame=n["frame"], limb=n["limb"], note=36, vel=n["vel"], piece="kick", err=0, miss_mm=r2(be[f]), ok=be[f] < 0.5, lift_deg=r1(be[max(0, f - 40):f + 1].max())))
        if n.get("zone") == "pedal" and n["limb"] and 0 <= f < N: rows.append(dict(frame=n["frame"], limb=n["limb"], note=44, vel=n["vel"], piece="hat pedal", err=0, miss_mm=r2(ho[f]), ok=ho[f] < 1e-3))
    hands = [r for r in rows if r["limb"] in "LR"]; bad = [r for r in rows if not r["ok"]]
    return res(len([r for r in hands if r["ok"]]) >= math.ceil(0.98 * len(hands)) and all(r["ok"] for r in rows if r["limb"] in ("RF", "LF")), "both stick tips on their strike point (<= 15 mm) on the note's 30 fps frame +-1 for >= 98 % of the notes; the beater on the head and the hat shut on every pedal note",
               [4 * r["frame"] for r in bad], notes={l: sum(r["limb"] == l for r in rows) for l in ("L", "R", "RF", "LF")}, ok_by_limb={l: sum(r["limb"] == l and r["ok"] for r in rows) for l in ("L", "R", "RF", "LF")},
               tip_miss_mm_mean=r1(np.mean([r["miss_mm"] for r in hands])), tip_miss_mm_max=r1(max(r["miss_mm"] for r in hands)), left_to_other_hand=sum(bool(r.get("left_to_other_hand")) for r in rows), failing=bad[:12]), rows


def run(P, perfs, kind, quat=None, foot_events=None, bpm=None):
    N = P["N"]; ch = body_channels(P); sp = body_speeds(P); R = {}; body = P["body"]; legs = P["legs"]; feet = P["feet"]; foot_events = foot_events or {"L": [], "R": []}
    # ---- joints
    bad = np.zeros(N, bool); worst = {}; comf = {}
    for k, v in ch.items():
        if k.startswith("knee_swivel"): continue
        L_ = lim_of(k); lo, hi = L_["hard"]; hi_f = hi + (L_["bent_knee_extra"] * np.clip(ch["knee_" + k[-1]] / L_["bent_knee_deg"], 0, 1) if k.startswith("ankle_") and not k.startswith("ankle_roll") else 0.0)
        o = np.maximum(lo - v, v - hi_f); bad |= o > MARGIN; worst[k] = r1(o.max()); cl, chh = L_["comfort"]; comf[k] = r1(100 * ((v < cl) | (v > chh)).mean())
    R["C-JT-1"] = res(not bad.any(), "trunk, head and leg channels inside their hard limits (+0.5 deg); the knee is a hinge by construction", np.nonzero(bad)[0], worst_over_limit_deg={k: v for k, v in worst.items() if v > -3},
                      ranges_deg={k: [r1(v.min()), r1(v.max())] for k, v in ch.items()})
    R["C-JT-2"] = res(max(comf.values()) <= 20, "% of frames outside comfort, per channel (a cost, not an error; warn above 20 %)", pct_outside_comfort={k: v for k, v in comf.items() if v > 0})
    # ---- continuity
    over = np.zeros(N - 1, bool); peaks = {}
    for k, v in sp.items():
        c = CE["spine" if k in ("spine", "chest") else k.split("_")[0]]; peaks[k] = [r1(v.max()), c]; over |= v > c
    R["C-CONT-1"] = res(not over.any(), "speed ceilings, deg/s [peak, ceiling]: pelvis, each spine bone, neck + head, hips, knees, ankles, toes", np.nonzero(over)[0], peak_vs_ceiling=peaks)
    b = np.zeros(N - 2, bool); pk = {}
    for k, v in ch.items():
        d2 = np.abs(np.diff(v, 2))
        if k[-2:] in ("_L", "_R") and len(foot_events[k[-1]]):                           # a foot's own contact (the beater on the head, the heel on the board) reverses its velocity: exempt +-1 frame, as the stick's alpha
            near = np.zeros(N, bool)
            for c in foot_events[k[-1]]: near[max(0, c - 1):c + 2] = True
            d2 = np.where(near[1:-1], 0, d2)
        pk[k] = r2(d2.max()); b |= d2 > CFG["steps"]["limb"]
    R["C-CONT-2"] = res(not b.any(), "second difference per frame at 120 Hz <= 3 deg on every trunk, head and leg channel (a leg is exempt +-1 frame at its own foot contact)", np.nonzero(b)[0] + 1, worst_deg={k: v for k, v in sorted(pk.items(), key=lambda kv: -kv[1])[:6]})
    lp = CFG["lipschitz"]; b = np.zeros(N - 1, bool); ex = 0.0
    for s in "LR":
        vK = np.linalg.norm(np.diff(legs[s]["knee"], axis=0), axis=1) * HZ; vA = np.linalg.norm(np.diff(legs[s]["ankle"], axis=0), axis=1) * HZ; vH = np.linalg.norm(np.diff(legs[s]["hip"], axis=0), axis=1) * HZ
        e = vK - lp["gain"] * np.maximum(vA, vH) - lp["floor_m_s"]; b |= e > 0; ex = max(ex, float(e.max()))
    R["C-CONT-3"] = res(not b.any(), "a knee never moves faster than 1.5 x its ankle (or its hip, when the pelvis moves over a planted foot) + 0.3 m/s", np.nonzero(b)[0], worst_excess_m_s=r2(ex))
    if quat is not None:
        qd = min(float((q[1:] * q[:-1]).sum(1).min()) for q in quat.values()); R["C-CONT-4"] = res(qd >= 0, "every stored quaternion of the driving skeleton stays in one hemisphere frame to frame", min_quat_dot=round(qd, 4), bones=len(quat))
    # ---- legs and feet
    ov = legs["L"]["reach_over"] | legs["R"]["reach_over"]; un = np.maximum(legs["L"]["unattained_m"], legs["R"]["unattained_m"])
    R["C-IK-2 legs"] = res(not (un > 0.002).any(), "hip-ankle distance beyond 0.97 x the leg is reported, never clamped onto a straight leg; the miss is measured", np.nonzero(ov | (un > 0.002))[0], frames_over_0_97=int(ov.sum()),
                           reach_ratio_max=r2(max(legs[s]["reach_ratio"].max() for s in "LR")), unattained_max_mm=r1(un.max() * 1000), knee_min_deg=r1(min(legs[s]["ch"]["knee"].min() for s in "LR")))
    sl = {}; slide = np.zeros(N)
    for s in "LR":
        f = feet[s]; ball = np.linalg.norm(legs[s]["ball"] - f["ball"], axis=1); slide = np.maximum(slide, ball); row = dict(ball_on_its_contact_mm=r2(ball.max() * 1000), ball_world_travel_mm=r1(np.linalg.norm(f["ball"] - f["ball"].mean(0), axis=1).max() * 1000))
        hh = f.get("heel_h"); down = (hh < 0.001) if hh is not None else np.ones(N, bool)
        if down.any():
            hp = f["heel"] + (legs[s]["ball"] - f["ball"]); hd = np.linalg.norm((hp - np.median(hp[down], 0))[:, :2], axis=1) * down; slide = np.maximum(slide, hd); row.update(heel_down_frames=int(down.sum()), heel_slide_mm=r2(hd.max() * 1000))
        else: row.update(heel_down_frames=0, note="heel-up throughout: the ball is the only contact")
        if hh is not None: row["heel_lift_max_mm"] = r1(hh.max() * 1000)
        sl[s] = row
    R["C-FOOT-1"] = res(slide.max() * 1000 <= BC["slide_mm"], "a planted contact slides <= 5 mm: the ball of the foot on its contact (the pedal board it rides, or the floor), the heel while it is down", np.nonzero(slide * 1000 > BC["slide_mm"])[0], slide_max_mm=r2(slide.max() * 1000), feet=sl)
    bad = np.zeros(N, bool); rg = {}
    for s in "LR":
        c = legs[s]["ch"]; A_ = LM["ankle"]; hi = A_["hard"][1] + A_["bent_knee_extra"] * np.clip(c["knee"] / A_["bent_knee_deg"], 0, 1)
        bad |= (c["ankle"] < A_["hard"][0] - MARGIN) | (c["ankle"] > hi + MARGIN) | (c["ankle_roll"] < LM["ankle_roll"]["hard"][0] - MARGIN) | (c["ankle_roll"] > LM["ankle_roll"]["hard"][1] + MARGIN) | (c["toes"] < LM["toes"]["hard"][0] - MARGIN) | (c["toes"] > LM["toes"]["hard"][1] + MARGIN)
        rg[s] = dict(ankle=[r1(c["ankle"].min()), r1(c["ankle"].max())], roll=[r1(c["ankle_roll"].min()), r1(c["ankle_roll"].max())], toes_mtp=[r1(c["toes"].min()), r1(c["toes"].max())], shank_yaw=[r1(c["foot_yaw"].min()), r1(c["foot_yaw"].max())])
    R["C-FOOT-2"] = res(not bad.any(), "ankle hinge in [-54, +12] (up to +10 more as the knee bends to 60 deg), roll in [-15, +35], MTP in [-40, +70]: a raised heel is MTP extension + plantarflexion, never an ankle past its range", np.nonzero(bad)[0], ranges_deg=rg)
    hp = BR.pt(P["T"]["hips"], AR.HEAD["hips"]); seat = BR.pt(P["T"]["hips"], body.pivot); drift = np.linalg.norm(seat - seat.mean(0), axis=1)
    if body.seated: R["S-BODY-1"] = res(drift.max() <= BC["pelvis_drift_m"], "seated: the pelvis stays on the throne: its seat contact (the sit bones it rocks on) moves <= 2 cm from its mean place", np.nonzero(drift > BC["pelvis_drift_m"])[0], seat_contact_drift_max_mm=r1(drift.max() * 1000),
                                        hips_bone_travel_max_mm=r1(np.linalg.norm(hp - hp.mean(0), axis=1).max() * 1000))
    else:
        fx = [feet[s]["ball"][0, 0] for s in "LR"]; inside = (hp[:, 0] >= min(fx) - 0.02) & (hp[:, 0] <= max(fx) + 0.02)
        R["S-BODY-2"] = res(inside.all(), "standing: the pelvis stays between the planted feet (a stand-in for the centre of mass over the support polygon)", np.nonzero(~inside)[0], pelvis_shift_mm=[r1(1000 * (hp[:, 0] - hp[0, 0]).min()), r1(1000 * (hp[:, 0] - hp[0, 0]).max())],
                            pelvis_drop_mm=[r1(1000 * (hp[:, 2].min() - AR.HEAD["hips"][2])), r1(1000 * (hp[:, 2].max() - AR.HEAD["hips"][2]))])
    # ---- idle: jitter, dead limbs, the pulse on the grid
    fc = max(4.0, 2 * bpm / 60.0) if bpm else 4.0; bb, aa = butter(4, fc / (HZ / 2), "high"); amp = {}; fr = np.arange(N)
    for k, v in ch.items():
        hpv = np.abs(filtfilt(bb, aa, v)); m = np.ones(N, bool)
        if k[-2:] in ("_L", "_R"):
            for c in foot_events[k[-1]]: m &= np.abs(fr - c) > 0.25 * HZ
        amp[k] = r2(hpv[m].max()) if m.any() else 0.0
    R["C-IDLE-1"] = res(max(amp.values()) <= 0.5, f"no jitter: trunk and head motion above {fc:.1f} Hz stays <= 0.5 deg on every frame; a leg's, on the frames more than 0.25 s from its own foot events", high_pass_amp_deg={k: v for k, v in sorted(amp.items(), key=lambda kv: -kv[1])[:8]})
    limbs = limb_speed(P, perfs, ch)
    if bpm:
        win = int(8 * 60 / bpm * HZ); low = {}
        for k, v in limbs.items(): low[k] = r1(min(float(np.sqrt((v[s0:s0 + win] ** 2).mean())) for s0 in range(0, max(1, N - 1 - win + 1), win // 2)))
        R["C-IDLE-2"] = res(min(low.values()) >= 5, "no dead limb: in every 2-bar window each of the six limbs (both arms, both legs, trunk, head) has an RMS joint speed >= 5 deg/s", rms_deg_s_min_per_limb=low)
    pu = P["lay"]["curves"]["pulse"]; offs = []
    for tb in P["beats"]:
        f = int(round(tb * HZ))
        if 12 <= f < N - 12: j = f - 10 + int(np.argmax(pu[f - 10:f + 11])); offs.append((j - tb * HZ) / HZ * 1000)
    R["C-IDLE-3"] = res(max(abs(x) for x in offs) <= 1000.0 / HZ + 1e-6, "the keep-time pulse (trunk dip, pelvis drop, head nod) bottoms within one solved frame (8.3 ms) of every beat (R-389)", beats=len(offs), offset_ms_max=r1(max(abs(x) for x in offs)), offset_ms_mean=r1(np.mean(offs)))
    # ---- collisions the per-arm check cannot see
    dep, pairs = collisions(P, perfs, kind); pm = CFG["penetration_mm"] / 1000
    R["C-COL-1 body"] = res(dep.max() <= pm, "penetration between the parts a one-arm proof never had together: arm x arm, stick x stick, sticks x kit and body, limbs and legs x kit (a struck piece allows the stick 22 mm)", np.nonzero(dep > pm)[0], max_mm=r1(dep.max() * 1000), frames_over_3mm=int((dep > pm).sum()), pairs=pairs)
    return R, dict(ch=ch, speeds=sp, limbs=limbs, pen=dep, slide=slide)


def limb_speed(P, perfs, ch):
    """one activity curve per limb: the fastest of its joints, deg/s (N-1,)"""
    d = lambda v: np.abs(np.diff(v)) * HZ; out = {}
    for h in "LR":
        a = perfs[h]["ch"]; out[f"arm_{h}"] = np.max([d(a[k]) for k in ("elbow", "sh_flex", "wrist_flex", "wrist_dev", "pron") + (("stick_alpha",) if "stick_alpha" in a else ())], 0)
        out[f"leg_{h}"] = np.max([d(ch[f"{k}_{h}"]) for k in ("hip_flex", "knee", "ankle", "toes")], 0)
    out["trunk"] = np.max([d(ch[k]) for k in ch if k.startswith(("pelvis", "spine", "chest"))], 0) * 3.0          # three bones share the trunk's motion: the limb's speed is their sum
    out["head"] = np.max([d(ch[k]) for k in ("head_flex", "head_side", "head_twist")], 0)
    return out
