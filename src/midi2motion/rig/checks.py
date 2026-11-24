#!/usr/bin/env python3
# midi2motion: vendored from nelvids/lab/wrapped/3d/2026-11-16-rig-foundations/tools/checks.py (a wrapped lab, read-only source). Solver behaviour unchanged; only data paths and the lab command line were changed.
"""checks.py: the C-checks of STANDARD.md on a baked arm (bake.assemble's perf), at 120 Hz (C-0.2). Every check returns
{ok, value(s), frames (the failing 120 Hz frames), note}; run() also returns the failing moments as inspector events.

Scope of this proof (the driving-skeleton subset): C-JT-1/2/3, C-TW-1, C-IK-2/3, C-CONT-1/2/3/4, C-TGT-1, C-COL-1, C-GRIP-1..6, sync, C-IDLE-1/2/3.
Not run here: C-SKIN-*, C-FOOT-*, C-FACE-1, C-SK-1 (one arm), C-0.1 (no new GLB).

Where a check needed a decision the standard does not spell out, it is stated in the check's `note` and in the README.
"""
import math, pathlib, sys
import numpy as np
from scipy.signal import butter, filtfilt
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import arm_rig as AR
from arm_rig import CFG, HZ

LM = CFG["limits"]; MARGIN = CFG["margin_deg"]
ARM = ("clav_elev", "clav_prot", "sh_flex", "sh_abd", "sh_twist", "elbow", "pron", "wrist_twist")
FING = [f"{f}_{j}" for f in AR.FINGERS for j in ("mcp", "pip", "dip")]
def runs(mask):
    f = np.nonzero(mask)[0]; return [] if not len(f) else [[int(a[0]), int(a[-1])] for a in np.split(f, np.nonzero(np.diff(f) > 1)[0] + 1)]
def res(ok, note="", frames=(), **v): return dict(ok=bool(ok), note=note, frames=[int(x) for x in np.atleast_1d(frames)][:400], n_frames=int(len(np.atleast_1d(frames))), **v)
def r1(x): return round(float(x), 1)
def r2(x): return round(float(x), 2)


def swing_speed(perf):
    a, b = np.radians(perf["ch"]["sh_flex"]), np.radians(perf["ch"]["sh_abd"]); d = np.stack([np.sin(b), np.cos(b) * np.sin(a), np.cos(b) * np.cos(a)], 1)
    return np.degrees(np.arccos(np.clip((d[1:] * d[:-1]).sum(1), -1, 1))) * HZ


def speeds(perf):
    """deg/s per channel group, each (N-1,)"""
    ch = perf["ch"]; d = lambda k: np.abs(np.diff(ch[k])) * HZ
    out = dict(clav_elev=d("clav_elev"), clav_prot=d("clav_prot"), sh_swing=swing_speed(perf), sh_twist=d("sh_twist"), swivel=d("swivel"), elbow=d("elbow"), pron=d("pron"),
               wrist_swing=np.hypot(np.diff(ch["wrist_flex"]), np.diff(ch["wrist_dev"])) * HZ, finger=np.max([d(k) for k in FING], 0))
    if "stick_alpha" in ch: out.update(stick_alpha=d("stick_alpha"), stick_beta=d("stick_beta"))
    return out


def capsules(perf):
    """the arm's capsules per frame: (name, a (N,3), b (N,3), r)"""
    c = CFG["capsules"]; S, E, W = (perf["pts"][k] for k in "SEW"); y = perf["Hw"][:, :, 1]
    return [("upper_arm", S + (E - S) * c["upper_arm"]["from"], E, c["upper_arm"]["r"]), ("forearm", E, W, c["forearm"]["r"]), ("hand", W, W + y * c["hand"]["len"], c["hand"]["r"])]


def collisions(perf):
    """penetration depth (m) per frame against the frozen torso, the set's surfaces (keys) and the kit (drums) -> depth (N,), rows [(frame, a, b, depth)]"""
    N = perf["N"]; rig = perf["rig"]; dep = np.zeros(N); rows = []; caps = capsules(perf); off = 0 if perf.get("S_off") is None else perf["S_off"]
    def add(f, a, b, d):
        rows.append((int(f), a, b, float(d))); dep[f] = max(dep[f], d)
    for n, a, b, r in caps:
        for bn, ba, bb, br in rig.body:
            if n == "upper_arm" and bn in ("chest", "neck"): continue                          # the shoulder joint lives inside the chest's end
            d, _, _ = AR.seg_seg(a, b, np.broadcast_to(rig.to_char(ba) + off, a.shape), np.broadcast_to(rig.to_char(bb) + off, a.shape)); p = r + br - d
            for f in np.nonzero(p > 0.0005)[0]: add(f, n, bn, p[f])
    env = perf.get("env", {})
    if env.get("surfaces"):                                                                    # keys: the hand (wrist .. knuckles, 18 mm) and the forearm over the keybed, as the old audit measured it
        to_w = env["to_world"]
        for n, a, b, r in caps[1:]:
            for u in ((0.0, 0.33, 0.66, 1.0) if n == "forearm" else (0.0, 0.7)):
                p = to_w(a + (b - a) * u); rr = 0.018 if n == "hand" else r
                for f in range(0, N):
                    z = max([s(p[f, 0], p[f, 1]) or -9 for s in env["surfaces"]])
                    if p[f, 2] - rr < z and p[f, 2] > z - 0.25: add(f, n, "set", z + rr - p[f, 2])
    if env.get("kit"):
        kit, DP = env["kit"], env["DP"]; st = perf["stick"]; solids = kit.solids(); struck = env["struck"]
        for f in range(N):
            pts = [st["butt"][f] + (st["tip"][f] - st["butt"][f]) * u for u in np.linspace(0.34, 1.0, 24)]
            for so in solids:
                d = max(DP.solid_pen(p_, CFG["stick"]["radius"], so) for p_ in pts); lim = 0.022 if so[0] in struck[f] else 0.0
                if d > lim + 0.0005: add(f, "stick", so[0], d - lim)
            for n, a, b, r in caps[1:]:
                for so in solids:
                    d = max(DP.solid_pen(a[f] + (b[f] - a[f]) * u, r * 0.8, so) for u in np.linspace(0, 1, 6))
                    if d > 0.0005: add(f, n, so[0], d)
            for bn, ba, bb, br in rig.body:
                d, _, _ = AR.seg_seg(st["F"][f], st["tip"][f], rig.to_char(ba), rig.to_char(bb))
                if d < br + CFG["stick"]["radius"]: add(f, "stick", bn, br + CFG["stick"]["radius"] - d)
    return dep, rows


def run(perf):
    ch = perf["ch"]; N = perf["N"]; fl = perf["flags"]; R = {}; keys = perf["kind"] == "keys"; drums = "stick" in perf; cont = perf["contacts"]
    near = np.zeros(N, bool)
    for c in cont: near[max(0, c - 1):c + 2] = True
    R["C-0.2"] = res(perf["hz"] == 120, f"solve_hz {perf['hz']}")
    # ---- joints
    bad = np.zeros(N, bool); worst = {}
    for k in ARM + tuple(k for k in ("stick_alpha", "stick_beta") if k in ch):
        lo, hi = LM[k]["hard"]; o = np.maximum(lo - ch[k], ch[k] - hi); bad |= o > MARGIN; worst[k] = r1(o.max())
    for k in FING:
        lo, hi = LM["finger_" + k.split("_")[1]]["hard"]; o = np.maximum(lo - ch[k], ch[k] - hi); bad |= o > MARGIN; worst[k] = r1(o.max())
    el = AR.wrist_ellipse(ch["wrist_flex"], ch["wrist_dev"], "hard"); bad |= el > 1.02; worst["wrist_ellipse"] = r2(np.sqrt(el.max()))
    K = perf["K"]; hinge = AR.Rot.from_matrix(np.swapaxes(K["U"], 1, 2) @ K["F0"]).as_rotvec(); off = np.degrees(np.abs(hinge[:, 1:]).max()); bad |= np.degrees(np.abs(hinge[:, 1:]).max(1)) > MARGIN
    R["C-JT-1"] = res(not bad.any(), "every channel inside its hard limit (+0.5 deg); the elbow's off-axis rotation", np.nonzero(bad)[0], worst_over_limit_deg={k: v for k, v in worst.items() if v > -3}, elbow_off_axis_deg=r2(off))
    comf = {}
    for k in ("sh_flex", "sh_abd", "sh_twist", "elbow", "pron", "wrist_twist"):
        lo, hi = LM[k]["comfort"]; comf[k] = r1(100 * ((ch[k] < lo) | (ch[k] > hi)).mean())
    comf["wrist"] = r1(100 * (AR.wrist_ellipse(ch["wrist_flex"], ch["wrist_dev"], "comfort") > 1).mean())
    R["C-JT-2"] = res(max(comf.values()) <= 20, "% of frames outside comfort, per joint (a cost, not an error; warn above 20 %)", pct_outside_comfort=comf)
    rt = [ch[f"{f}_dip"][ch[f"{f}_pip"] > 20] / ch[f"{f}_pip"][ch[f"{f}_pip"] > 20] for f in AR.FINGERS[1:]]; rt = np.concatenate(rt) if any(len(x) for x in rt) else np.array([2 / 3])
    R["C-JT-3"] = res(rt.min() >= LM["dip_over_pip"][0] and rt.max() <= LM["dip_over_pip"][1], "DIP/PIP whenever PIP > 20 deg", ratio=[r2(rt.min()), r2(rt.max())])
    # ---- twist
    wt = ch["wrist_twist"]; b = (np.abs(wt) > 10 + MARGIN) | (ch["pron"] < LM["pron"]["hard"][0] - MARGIN) | (ch["pron"] > LM["pron"]["hard"][1] + MARGIN)
    R["C-TW-1"] = res(not b.any(), "twist of the hand about the forearm axis left AT THE WRIST (the rest is pronation, in the forearm's twist bones)", np.nonzero(b)[0], wrist_twist_abs_max_deg=r1(np.abs(wt).max()),
                      wrist_twist_range_deg=r1(wt.max() - wt.min()), pronation_range_deg=[r1(ch["pron"].min()), r1(ch["pron"].max())], frames_with_spill=int(fl["twist_spill"].sum()))
    # ---- IK
    un = fl["unattained_m"]; b = un > 0.002
    R["C-IK-2"] = res(not b.any(), "targets beyond 0.97 x reach are reported and never clamped onto a straight arm; the miss is measured", np.nonzero(b | fl["reach_over"])[0], frames_over_0_97=int(fl["reach_over"].sum()), reach_ratio_max=r2(fl["reach_ratio"].max()),
                      unattained_max_mm=r1(un.max() * 1000), frames_unattained_over_2mm=int(b.sum()), elbow_min_deg=r1(ch["elbow"].min()), runs=runs(fl["reach_over"])[:20])
    oc = fl["swing_clamp"] | fl["twist_clamp"]; lc = np.any(list(fl["limit_clamp"].values()), 0)
    R["C-IK-3"] = res(oc.mean() <= 0.02 and not lc.any(), "orientation clamps (the wrist ellipse or the twist budget hit) <= 2 % of frames, each reported; shoulder/elbow limit clamps: 0", np.nonzero(oc | lc)[0], clamp_frames=int(oc.sum()), pct=r1(100 * oc.mean()),
                      shoulder_elbow_limit_clamps=int(lc.sum()), limit_clamps_by_channel={k: int(v.sum()) for k, v in fl["limit_clamp"].items()}, orientation_error_max_deg=r1(fl["ori_err_deg"].max()), wrist_on_boundary_frames=int((np.sqrt(el) > 0.985).sum()))
    # ---- continuity
    sp = speeds(perf); ce = CFG["ceilings"]; sc = CFG["keys_ceiling_scale"] if keys else 1.0; hc = CFG.get("hard_ceilings", ce); over = np.zeros(N - 1, bool); strain = np.zeros(N - 1, bool); peaks = {}; style = {}
    for k, v in sp.items():                                                                       # R-417: the hard cap (human-calibrated) decides pass or fail; the style band (the keys' 60 %) is reported as strain
        lim = ce[k] * (sc if k not in ("finger", "stick_alpha", "stick_beta") else 1.0); peaks[k] = [r1(v.max()), r1(hc[k])]; style[k] = [r1(v.max()), r1(lim)]; over |= v > hc[k]; strain |= v > lim
    R["C-CONT-1"] = res(not over.any(), "speed against the HARD caps (R-417: human-calibrated, rig.yaml hard_ceilings), deg/s [peak, cap]; frames over the style band (" + ("keys: 60 % of the arm ceilings" if keys else "the standard's ceilings") + ") are strain, counted beside it",
                        np.nonzero(over)[0], peak_vs_ceiling=peaks, strain_frames=int(strain.sum()), peak_vs_style_band=style)
    st = CFG["steps"]; b = np.zeros(N - 2, bool); pk = {}
    fx = near[1:-1]
    for k in ARM + ("wrist_flex", "wrist_dev", "swivel"):
        d2 = np.abs(np.diff(ch[k], 2)); d2 = np.where(fx & keys & k.startswith("wrist_f"), 0, d2); pk[k] = r2(d2.max()); b |= d2 > st["limb"]         # keys: the fingertip stops on the key; the wrist's flexion carries that contact (as alpha does for a stick)
    fx = near[1:-1]                                                                               # the stick's own pitch reverses at a contact (S-GRIP-5): alpha and the fingers riding it are exempt for +-1 frame
    fcon = perf.get("fcon")                                                                       # keys with a finger rig (the fingers round): a key's bottom stops its finger as a drum head stops a stick: that digit is exempt for +-1 frame there
    for k in FING: d2 = np.abs(np.diff(ch[k], 2)); d2 = np.where(fx & drums, 0, d2); d2 = np.where(fcon[k.split("_")[0]][1:-1], 0, d2) if fcon is not None else d2; pk[k] = r2(d2.max()); b |= d2 > st["finger"]
    for k in ("stick_alpha", "stick_beta"):
        if k in ch: d2 = np.where(fx, 0, np.abs(np.diff(ch[k], 2))); pk[k] = r2(d2.max()); b |= d2 > st["finger"]
    R["C-CONT-2"] = res(not b.any(), "second difference per frame at 120 Hz: <= 3 deg limbs, <= 5 deg fingers and the stick (exempt +-1 frame at a contact: the stick and the fingers on it; on keys the wrist's flexion)", np.nonzero(b)[0] + 1, worst_deg={k: v for k, v in sorted(pk.items(), key=lambda kv: -kv[1])[:6]})
    vE = np.linalg.norm(np.diff(perf["pts"]["E"], axis=0), axis=1) * HZ; vW = np.linalg.norm(np.diff(perf["pts"]["W"], axis=0), axis=1) * HZ; lp = CFG["lipschitz"]
    vS = np.linalg.norm(np.diff(perf["pts"]["S"], axis=0), axis=1) * HZ; b = vE > lp["gain"] * np.maximum(vW, vS) + lp["floor_m_s"]                # full body: the elbow may also go with the SHOULDER when the trunk moves over a planted hand (as torture case 7); it may still never outrun both ends
    R["C-CONT-3"] = res(not b.any(), "the elbow point never moves faster than 1.5 x the faster of its two ends (wrist, shoulder) + 0.3 m/s (a null-space jump)", np.nonzero(b)[0], elbow_speed_max_m_s=r2(vE.max()), wrist_speed_max_m_s=r2(vW.max()), worst_excess_m_s=r2((vE - lp["gain"] * np.maximum(vW, vS)).max()))
    qd = min(float((q[1:] * q[:-1]).sum(1).min()) for q in perf["quat"].values()); wrap = max(float(np.abs(np.diff(ch[k])).max()) for k in ("swivel", "pron", "sh_twist", "wrist_twist"))
    R["C-CONT-4"] = res(qd >= 0 and wrap < 90, "stored quaternions stay in one hemisphere; phi and the twists are unwrapped", min_quat_dot=round(qd, 4), max_channel_jump_deg=r1(wrap))
    # ---- targets
    def tgt(W):
        a = np.linalg.norm(np.diff(W, 2, axis=0), axis=1) * HZ * HZ; v = np.linalg.norm(np.diff(W, axis=0), axis=1) * HZ; dv = np.abs(np.diff(v)); return a, dv
    a, dv = tgt(perf["W_plan"]); T = CFG["target"]; b = (a > T["accel_m_s2"]) | (dv > T["dspeed_m_s"])
    R["C-TGT-1"] = res(not b.any(), "the wrist target the solver was given: acceleration and speed change per frame", np.nonzero(b)[0] + 1, accel_max_m_s2=r1(a.max()), dspeed_max_m_s=r2(dv.max()))
    if perf.get("W_raw") is not None:
        a0, dv0 = tgt(perf["W_raw"]); b0 = (a0 > T["accel_m_s2"]) | (dv0 > T["dspeed_m_s"])
        R["C-TGT-1"].update(input_before_planning=dict(accel_max_m_s2=r1(a0.max()), frames_over=int(b0.sum())), moved_by_planning_max_mm=r1(np.linalg.norm(perf["W_plan"] - perf["W_raw"], axis=1).max() * 1000)); R["C-TGT-1"]["raw_frames"] = [int(x) for x in np.nonzero(b0)[0][:200] + 1]
    # ---- collisions
    dep, rows = collisions(perf); pm = CFG["penetration_mm"] / 1000; pairs = {}
    for f, a_, b_, d in rows:
        if d > pm: e = pairs.setdefault(f"{a_} x {b_}", [0, 0.0]); e[0] += 1; e[1] = max(e[1], d)
    R["C-COL-1"] = res(dep.max() <= pm, "penetration depth against the frozen torso" + (", the keybed" if keys else ", the kit (a struck piece allows the stick 22 mm, as round 1 measured)" if drums else ""), np.nonzero(dep > pm)[0], max_mm=r1(dep.max() * 1000),
                       frames_over_3mm=int((dep > pm).sum()), pairs={k: dict(frames=v[0], max_mm=r1(v[1] * 1000)) for k, v in pairs.items()})
    perf["pen_depth"] = dep
    # ---- idle
    ev_t = perf["events"]; far = np.ones(N, bool); fr = np.arange(N)
    for e in ev_t: far &= (fr < e.get("f0", e["f"]) - 0.25 * HZ) | (fr > (e["f_end"] if e.get("f_end") is not None else e["f"]) + 0.25 * HZ)     # a gesture's own span (wind-up .. settle) is not waiting
    wait = far & ((perf["mode"] == "wait") if perf.get("mode") is not None else True); bpm = perf.get("bpm"); fc = max(4.0, 2 * bpm / 60.0) if bpm else 4.0
    bb, aa = butter(4, fc / (HZ / 2), "high"); amp = {}
    for k in ARM + ("wrist_flex", "wrist_dev", "swivel") + (("stick_alpha",) if drums else ()):
        if N > 40: hp = np.abs(filtfilt(bb, aa, ch[k])); amp[k] = r2(hp[wait].max()) if wait.any() else 0.0
    b = max(amp.values() or [0]) > 0.5
    if len(ev_t): R["C-IDLE-1"] = res(not b, f"waiting frames (no event within 0.25 s" + (", the planner's 'wait' phase" if perf.get("mode") is not None else "") + f"): motion above {fc:.1f} Hz stays <= 0.5 deg", waiting_frames=int(wait.sum()), high_pass_amp_deg=amp)
    if bpm and N > 2 * int(8 * 60 / bpm * HZ) // 2:
        win = int(8 * 60 / bpm * HZ); rms = []
        for s0 in range(0, N - win + 1, win // 2): rms.append(max(float(np.sqrt((np.diff(ch[k][s0:s0 + win]) ** 2).mean()) * HZ) for k in ("elbow", "sh_flex", "wrist_flex", "wrist_dev", "pron") + (("stick_alpha",) if drums else ())))
        R["C-IDLE-2"] = res(min(rms) >= 5, "no dead limb: every 2-bar window's RMS joint speed >= 5 deg/s", rms_deg_s_min=r1(min(rms)))
    perf["speeds"] = sp; perf["wait"] = wait
    return R


def grip_checks(perf, plan, R):
    """C-GRIP-1..6 and the stroke table (drums / torture 6)"""
    ch = perf["ch"]; N = perf["N"]; g = perf["grip"]; st = perf["stick"]; al = ch["stick_alpha"]; S = plan["S"]; T = plan["T"]
    grid = np.arange(-10, 35.01, 2.5); fg = []; tg = {f: [] for f in ("middle", "ring", "pinky")}; pen = []
    for a in grid:
        cu = g.curls(np.array([a]))[0]; gi, _, pi = g.clearance("index", cu[1], math.radians(a)); gt, _, pt = g.clearance("thumb", cu[0], math.radians(a), g.thumb_abd)
        fg.append(max(float(np.linalg.norm(0.5 * (pi + pt) - g.f)), max(gi, 0.0), max(gt, 0.0))); pen.append(min(gi, gt))        # the thumb-index contact point = the midpoint of where each touches the stick
        for i, f in ((2, "middle"), (3, "ring"), (4, "pinky")):
            gc, gtip, _ = g.clearance(f, cu[i], math.radians(a)); tg[f].append(gtip); pen[-1] = min(pen[-1], gc)
    fd = np.interp(al, grid, fg); R["C-GRIP-1"] = res(fd.max() <= 0.005, "the fulcrum on the stick stays within 5 mm of the thumb-index contact point, and neither floats off the stick by more than 5 mm", np.nonzero(fd > 0.005)[0], max_mm=r1(fd.max() * 1000))
    lo, hi = LM["stick_alpha"]["hard"]; bl = LM["stick_beta"]["hard"]; cl = np.abs(plan["alpha_free"] - plan["alpha"]) > 0.01
    R["C-GRIP-2"] = res(al.min() >= lo - 0.01 and al.max() <= hi + 0.01 and np.abs(ch["stick_beta"]).max() <= bl[1] + 0.01, "alpha and beta inside the grip's cone; frames where the envelope asked for more than the grip allows are listed (the tip is then off the envelope, never off a hit)", np.nonzero(cl)[0],
                        alpha_range_deg=[r1(al.min()), r1(al.max())], beta_range_deg=[r1(ch["stick_beta"].min()), r1(ch["stick_beta"].max())], frames_alpha_at_limit=int(cl.sum()))
    tipgap = np.max([np.interp(al, grid, tg[f]) for f in tg], 0); low = al <= 0; pn = np.interp(al, grid, pen)
    R["C-GRIP-3"] = res((tipgap[low].max() if low.any() else 0) <= 0.010 and pn.min() >= -0.0015, "back-finger tips within 10 mm of the stick while alpha <= 0; no finger inside the stick (1.5 mm tolerance)", np.nonzero((low & (tipgap > 0.010)) | (pn < -0.0015))[0],
                        tip_gap_max_mm_alpha_le_0=r1((tipgap[low].max() if low.any() else 0) * 1000), tip_gap_max_mm_any=r1(tipgap.max() * 1000), deepest_finger_in_stick_mm=r1(-pn.min() * 1000))
    rows = []; kit = perf["env"]["kit"]
    for i, s in enumerate(S):
        c = int(round(s["t"] * AR.HZ))
        if not (1 <= c < N): continue
        prev = int(round(S[i - 1]["t_end"] * AR.HZ)) if i else 0; lo_f = max(prev, c - int(0.5 * AR.HZ), 0); n = kit.P[s["piece"]]["n"]; hgt = (st["tip"][lo_f:c + 1] - s["A"]) @ n; p = lo_f + int(np.argmax(hgt)); Hn = lambda W, Rh, a: float((W + Rh @ (g.f + plan["lever_tip"] * g.sdir(math.radians(a), 0.0)) - s["A"]) @ n)
        Rb = plan["Rb"]; rot = lambda f, ps, rh: Rb[f] @ AR.rv(np.array([0, 1.0, 0]) * math.radians(rh)) @ AR.rv(g.aw * math.radians(ps)); W = perf["pts"]["W"]
        h0 = Hn(W[p], rot(p, plan["psi"][p], plan["rho"][p]), al[p]); h1 = Hn(W[p], rot(p, plan["psi"][p], plan["rho"][p]), al[c]); h2 = Hn(W[p], rot(p, plan["psi"][c], plan["rho"][p]), al[c]); h3 = Hn(W[p], rot(p, plan["psi"][c], plan["rho"][c]), al[c])
        tot = max(h0 - Hn(W[c], rot(c, plan["psi"][c], plan["rho"][c]), al[c]), 1e-4); sh = dict(alpha=(h0 - h1) / tot, wrist=(h1 - h2) / tot, forearm_rot=(h2 - h3) / tot); sh["arm"] = 1 - sum(sh.values())
        vt = float(-(st["tip"][c] - st["tip"][c - 1]) @ n * AR.HZ); rows.append(dict(f=c, t=round(s["t"], 4), vel=s["vel"], piece=s["piece"], kind=s["kind"], lift_mm=r1(hgt.max() * 1000), d_alpha_deg=r1(al[p] - al[c]), alpha_contact_deg=r1(al[c]),
                                                                              tip_speed_m_s=r2(vt), tip_speed_abs_m_s=r2(np.linalg.norm(st["tip"][c] - st["tip"][c - 1]) * AR.HZ), share={k: r2(v) for k, v in sh.items()}, gap_s=round(s["t"] - S[i - 1]["t_end"], 3) if i else None))
    hits = [r for r in rows if r["kind"] != "sweep"]; loud = [r for r in hits if r["vel"] >= 60]; bad = [r for r in loud if abs(r["d_alpha_deg"]) < 8]
    R["C-GRIP-4"] = res(not bad, "not welded: alpha changes >= 8 deg between the preparation's peak and the contact on every stroke >= v60; shares = the tip's travel split by joint", [r["f"] for r in bad], strokes_v60=len(loud), failing=len(bad), d_alpha_min_deg=r1(min(abs(r["d_alpha_deg"]) for r in loud)) if loud else None,
                        d_alpha_median_deg=r1(np.median([abs(r["d_alpha_deg"]) for r in loud])) if loud else None, share_mean={k: r2(np.mean([r["share"][k] for r in hits])) for k in ("arm", "forearm_rot", "wrist", "alpha")},
                        distal_share_soft_or_fast=r2(np.mean([r["share"]["alpha"] + r["share"]["wrist"] + r["share"]["forearm_rot"] for r in hits if r["vel"] < 70 or (r["gap_s"] or 1) < 0.25] or [0])))
    v = np.array([r["vel"] for r in hits]); spd = np.array([r["tip_speed_m_s"] for r in hits]); cr = float(np.corrcoef(v, spd)[0, 1]) if len(hits) > 3 and v.std() > 0 else 1.0
    tmax = max([r["tip_speed_abs_m_s"] for r in rows] or [0.0])      # 2026-11-20: a hand with no stroke in the clip (a fill) has nothing to measure: pass, and say so
    R["C-GRIP-5"] = res(tmax <= 10 and cr >= 0.8, "tip speed into the contact <= 10 m/s, and it tracks velocity (R-402)" + ("" if rows else " (no stroke in the clip)"), tip_speed_max_m_s=r2(tmax), r_velocity_speed=r2(cr))
    io = [r["gap_s"] for r in rows if r["gap_s"] is not None]; R["C-GRIP-6"] = res(min(io or [1.0]) >= 0.0995, "same-hand inter-onset >= 100 ms (hard); gaps < 140 ms flagged" + ("" if io else " (fewer than two strokes in the clip)"), min_gap_ms=r1(min(io) * 1000) if io else None, gaps_under_140ms=int(sum(x < 0.1395 for x in io)))      # 2026-11-20: <= 1 stroke: no gap to check
    perf["strokes"] = rows; return R


def events(R):
    """failing moments for the inspector: one row per run of failing frames per check"""
    ev = []
    for k, r in R.items():
        if r["ok"] or not r.get("frames"): continue
        f = np.array(r["frames"]);
        for a in np.split(f, np.nonzero(np.diff(f) > 2)[0] + 1)[:25]: ev.append(dict(f=int(a[0]), f1=int(a[-1]), check=k, text=r["note"][:90]))
    return sorted(ev, key=lambda e: e["f"])
