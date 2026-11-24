#!/usr/bin/env python3
# midi2motion: vendored from nelvids/lab/wrapped/3d/2026-11-16-rig-foundations/tools/fullbody.py (a wrapped lab, read-only source). Solver behaviour unchanged; only data paths and the lab command line were changed.
"""fullbody.py: the full-body round (R-412): both arms to the standard on a moving trunk, legs and feet with locked contacts, head, layers.


D2 drums: closure bars 85-92, both hands and both feet (the sibling drum chart). D1 piano: the chart, 1P both hands, closure bars 65-72.
Order of work per clip (STANDARD §9: IK after layering):
  1. the hands' tools' travel curves (stroke_plan.tip_plan / the chart's fingertip pads): where each hand is headed, per frame;
  2. body_plan: L0 reach (the trunk goes with the hands) + L1 pulse + L2 breath + L3 phrase sway + accents, the head's nod and gaze, the feet on their boards;
  3. body_rig: pelvis..head and the legs, per frame -> the chest transform and the body capsules each arm is solved against;
  4. per hand: the contact attitudes probed from the trunk's posture at that piece (stroke_plan.homes), the planner (stroke_plan / keys_plan) and arm_rig.solve
     on the MOVING chest, with the proof's planner feedback;
  5. body_bake + body_checks: the android's bones, the driving skeleton, every check at 120 Hz, the inspector data, the render perfs.
Writes out/fullbody_report_v001.json, out/drive_fullbody_<set>_v001.json, work/fullbody/render_fullbody_<set>_v001.json, inspector/data/body_<set>.json.
"""
import json, math, pathlib, sys, time
sys.dont_write_bytecode = True
import numpy as np
HERE = pathlib.Path(__file__).resolve().parent; LAB = HERE.parent; sys.path.insert(0, str(HERE))
import arm_rig as AR, bake, checks, stroke_plan as SP, keys_plan, body_rig as BR, body_plan as BP
from arm_rig import CFG, HZ
BC = CFG["body"]; V = "v001"; EV = CFG["render_every"]


def body_channels(body, L0, lay, gz, N):
    """the layers summed into the trunk's and head's channels (deg, m): L0 + L1 + L2 + L3 + accents; the head keeps level against the trunk"""
    ne = body.neutral; lean = L0["lean"] + lay["lean"]; side = L0["side"] + lay["side"]; turn = L0["turn"] + lay["turn"]; shift = lay["shift"].copy(); shift[:, 0] += L0["shift_x"]
    if body.seated: shift[:, 0] += 0.0008 * (side - ne["side"])                              # weight shift on the throne: the pelvis slides a little toward the side it leans to (<= 2 cm, S-BODY-1)
    else: shift[:, 2] -= ne["drop"] + 0.9 * np.abs(shift[:, 0]) ** 2 / 0.84; shift[:, 1] += ne["back"]      # standing: soft knees, the hips a little back over the heels, and a shifted pelvis drops as much as the far leg needs
    nod = lay["nod"] + (gz["nod"] if gz else 0) - 0.35 * (lean - ne["lean"]); tilt = -0.5 * (side - ne["side"]); look = gz["look"] if gz else np.zeros(N)
    return dict(lean=lean, side=side, turn=turn, shift=shift, nod=nod, tilt=tilt, look=look, breath=lay["breath"])


def static_rig(T, caps, f, side): return AR.ArmRig(T[f], [(n, a[f], b[f], r) for n, a, b, r in caps], side)


def restick(S, kit, gap_at, window=0.45, v_free=3.0, cross_free=0.5, cross_hat=0.5):
    """the sticking, revisited where it hurts (a planner-level choice per phrase, S-IK-8; never per frame). The sibling chart gives every note a hand; with a body in
    the picture two things in it are not playable: a hand that must cross the kit faster than a hand travels, and arms crossed far past each other. Around each such
    moment the notes inside +-window s are re-dealt by exhaustive search (a few dozen deals): each plain hit may go to either hand, and of two hands landing on the SAME
    piece at the same instant one may leave the unison to the other (the note still sounds; one stick plays it). Cost of a deal: per hand, (mean travel speed - v_free)^2
    between consecutive strokes (m/s); arms crossed more than cross_free m at nearly the same time (cross_hat m when one hand is on the hi-hat); a small price per change. Sweeps and cross-sticks stay as dealt.
    Tried and not kept (README, Full body): cross_free = 0.15 m un-crosses the 100 ms fill at bar 91 too (no stick through a forearm), but hands the left hand tom 2 at 1.0 m from
    its shoulder 100 ms after a snare: a reach miss of 19 mm and twice the frames over the speed ceilings. The looser rule keeps the chart's deal there and the collision is reported.
    Also tried: a price on pieces far from the dealt hand's shoulder (30 x (distance - 0.8 m)^2): it re-dealt bar 88's tom 2 + floor tom into crossed arms and raised the right arm's speed failures from 2 frames to 9."""
    import itertools
    X = lambda s: float(s["A"][0]); allS = sorted([dict(s, hand=h, orig=h) for h in "LR" for s in S[h]], key=lambda s: (s["t"], s["hand"]))
    def seq_cost(seq):
        c = 0.0
        for a, b in zip(seq[:-1], seq[1:]):
            g = b["t"] - a["t_end"]
            if g < 0.095: c += 100.0; continue
            c += max(0.0, float(np.linalg.norm(b["A"] - a.get("A_end", a["A"]))) / g - v_free) ** 2
        return c
    def cost(ev):
        L = [e for e in ev if e["hand"] == "L"]; R = [e for e in ev if e["hand"] == "R"]; c = seq_cost(L) + seq_cost(R)
        for l in L:
            for r in R:
                dt = abs(l["t"] - r["t"])
                if dt < 0.3: c += 100.0 * max(0.0, X(r) - X(l) - (cross_hat if "hat" in (l["piece"], r["piece"]) else cross_free)) ** 2 * (1 - dt / 0.3)       # crossed arms; the right hand over the left on the hi-hat is the one crossing drummers do play
        return c
    def moved(e, h):
        if h == e["hand"]: return e
        e = dict(e, hand=h); e["A"] = kit.strike_point(e["piece"], e["zone"], h, gap_at(e["t"]) if e["piece"] == "hat" else 0.0); return e
    changes = []; guard = 0
    while guard < 12:
        guard += 1; base = cost(allS); worst = None
        for i, e in enumerate(allS):                                               # the stroke whose removal from the cost helps most = where it hurts
            c = base - cost(allS[:i] + allS[i + 1:])
            if c > 0.3 and (worst is None or c > worst[0]) and not e.get("tried"): worst = (c, i)
        if worst is None: break
        t0 = allS[worst[1]]["t"]; allS[worst[1]]["tried"] = True; idx = [i for i, e in enumerate(allS) if abs(e["t"] - t0) <= window and e["kind"] == "hit"][:9]
        if not idx: continue
        lo = max(0, min(idx) - 4); hi = min(len(allS), max(idx) + 5); ctx = allS[lo:hi]; best = (cost(ctx), None)
        uni = [(i, j) for i in idx for j in idx if i < j and abs(allS[i]["t"] - allS[j]["t"]) < 0.03 and allS[i]["piece"] == allS[j]["piece"]]
        for deal in itertools.product("LR", repeat=len(idx)):
            for drop in [None] + [x for pr in uni for x in pr]:
                ev = []; n_ch = 0.0
                for k, e in enumerate(ctx):
                    i = lo + k
                    if i == drop: n_ch += 0.5; continue
                    if i in idx: h = deal[idx.index(i)]; n_ch += 0.05 * (h != e["hand"]); e = moved(e, h)
                    ev.append(e)
                if any(abs(a["t"] - b["t"]) < 0.03 and a["hand"] == b["hand"] for a in ev for b in ev if a is not b): continue      # one hand, one stroke at a time
                c = cost(ev) + n_ch
                if c < best[0] - 1e-9: best = (c, (deal, drop))
        if best[1] is None: continue
        deal, drop = best[1]; new = []
        for i, e in enumerate(allS):
            if i == drop: changes.append(dict(t=round(e["t"], 3), piece=e["piece"], vel=e["vel"], hand=e["hand"], change="left to the other hand (a unison on one piece)")); continue
            if i in idx and deal[idx.index(i)] != e["hand"]: changes.append(dict(t=round(e["t"], 3), piece=e["piece"], vel=e["vel"], hand=e["hand"], change="moved to " + deal[idx.index(i)])); e = moved(e, deal[idx.index(i)])
            new.append(e)
        allS = new
    for h in "LR": S[h] = [{k: v for k, v in e.items() if k not in ("hand", "orig", "tried")} for e in allS if e["hand"] == h]
    return changes


# ---------------------------------------------------------------- D2: drums
def plan_drums(preset="german", tool_max=None, verbose=True, do_restick=True, d=None):
    """d (drum round 2): the targets of ANY kit and chart (tools/drums2/run2.targets); none = the sibling chart on the sibling kit. preset: one grip, or {hand: grip}"""
    assert d is not None, "midi2motion: plan_drums needs its targets (drums2/run2.targets)"; kit, DP = d["kit"], d["DP"]; presets = preset if isinstance(preset, dict) else {h: preset for h in "LR"}; N = d["N"]; lead, beat_s = d["lead"], d["bar_s"] / 4; body = BR.Body(True, kit.ROOT); t0 = time.time()
    d["resticked"] = restick(d["S"], kit, d["gap"]) if do_restick else []
    if verbose: print("  sticking changes:", d["resticked"], flush=True)
    TP = {h: SP.tip_plan(d["S"][h], N, lead, beat_s, DP, kit) for h in "LR"}; boost = {}
    if not any(d["S"].values()): raise ValueError("no hand strokes left in this chart")
    for h in "LR":                                                                       # a sweep drags the tip across the whole cymbal: that hand's comfortable distance is shorter while it does
        k = np.exp(-0.5 * (np.arange(-60, 61) / 25.0) ** 2); boost[h] = np.minimum(np.convolve(np.pad(TP[h]["sweep"].astype(float), 60, mode="edge"), k, mode="valid"), 1.0) * BC["reach_plan"]["sweep_margin"]
    L0 = BP.reach_plan(body, {h: TP[h]["A"] for h in "LR"}, "drums", N, tool_max, boost, ahead={h: [(s["t"], s["A"]) for s in d["S"][h]] for h in "LR"})
    beats = lead + beat_s * np.arange(-2, int((N / HZ - lead) / beat_s) + 2); on = lambda n: n["note"] in (36, 38, 40, 49, 57); bw = BP.beat_weights(beats, d["all_notes"], which=on)
    acc = [(n["tc"], n["vel"]) for n in d["all_notes"] if n["vel"] >= BC["layers"]["accent"]["vel_min"] and n["limb"] in ("L", "R") and np.abs(beats - n["tc"]).min() > 0.05 and 0 <= n["tc"] < N / HZ]
    lay = BP.layers(N, beats, bw, lead, d["bar_s"], acc); z = np.zeros(N)
    pre = body.trunk(body_channels(body, L0, lay, None, N)); head_pos = BR.pt(pre["T"]["head"], AR.HEAD["head"] + np.array([0, -0.05, 0.10])); gev = []
    for h in "LR":
        prev = None
        for s in d["S"][h]:
            gev.append(dict(t=s["t"], A=s["A"], travel=1.0 if prev is None else float(np.linalg.norm(s["A"] - prev)), vel=s["vel"], tag=s["piece"])); prev = s.get("A_end", s["A"])
    gz = BP.gaze(body, gev, L0["turn"] + lay["turn"], head_pos, N); ch = body_channels(body, L0, lay, gz, N); K = body.trunk(ch); T = K["T"]
    ped = BP.drum_pedals(DP, kit, d["all_notes"], N, lead, beat_s); feet = BP.drum_feet(body, kit, ped, N, lead, beat_s)
    legs = {s: body.leg(s, T["hips"], feet[s]["ankle"], feet[s]["foot_dir"], feet[s]["toe_dir"], foot_x=feet[s]["foot_x"]) for s in "LR"}; caps = body.caps(T, legs)
    arms = {}
    for h in "LR":
        preset = presets[h]; rig = AR.ArmRig(T["chest"], caps, h); S = d["S"][h]; grip = None; groups = {}
        fr_of = lambda s: int(np.clip(round(s["t"] * HZ), 0, N - 1))
        for s in S: f = fr_of(s); groups.setdefault((s["piece"], s["zone"], tuple(np.round(s["A"], 3)), round(ch["lean"][f] / 6), round(ch["side"][f] / 6), round(ch["turn"][f] / 8)), []).append(s)
        for key, grp in groups.items():                                                 # each stroke's contact attitude: probed from the trunk's own posture when it is hit (one probe per piece and posture: the same piece from a leaned trunk is held differently)
            fs = [fr_of(s) for s in grp]; P_ = np.stack([ch[k][fs] for k in ("lean", "side", "turn")], 1); f = fs[int(np.argmin(((P_ - P_.mean(0)) ** 2).sum(1)))]
            rs = static_rig(T["chest"], caps, f, h); grip = grip or SP.Grip(rs, preset); SP.homes(rs, SP.Grip(rs, preset, quick="probe"), grp)
        Rb = None; fb = []; best = None
        for it in range(4):                                                             # the proof's planner feedback (S-IK-5): a hand attitude the wrist cannot take is replaced by the nearest one it can
            pl = SP.plan(rig, S, N, lead, beat_s, DP, kit, grip=grip, Rb=Rb, homes_done=True); out = rig.solve(pl["W"], pl["Hm"]); fl = out["flags"]; cl = fl["swing_clamp"] | fl["twist_clamp"] | np.any(list(fl["limit_clamp"].values()), 0) | fl["reach_over"]; fb.append(int(cl.sum()))
            if best is None or fb[-1] < best[0]: best = (fb[-1], pl, out)
            if cl.mean() <= 0.005 or it == 3 or fb[-1] > best[0]: break                 # on a moving trunk the feedback can run away: the pass with the fewest clamped frames is kept
            Rb = keys_plan.smooth_rot(keys_plan.interior(rig, out) @ np.swapaxes(pl["Rrp"], 1, 2), 6.0)
        _, pl, out = best; pl["feedback_clamp_frames"] = fb; arms[h] = dict(rig=rig, pl=pl, out=out, S=S, grip=grip)
        if verbose:
            fl = out["flags"]; print(f"  arm {h} [{preset}]: clamp passes {fb}, reach max {fl['reach_ratio'].max():.3f} ({int(fl['reach_over'].sum())} frames > 0.97), unattained {fl['unattained_m'].max() * 1000:.1f} mm, limit clamps "
                                     f"{ {k: int(v.sum()) for k, v in fl['limit_clamp'].items() if v.any()} }, lift scale min {pl['lift_scale_min']:.2f}, {time.time() - t0:.0f}s", flush=True)
    return dict(d=d, body=body, N=N, ch=ch, K=K, T=T, L0=L0, lay=lay, gz=gz, ped=ped, feet=feet, legs=legs, caps=caps, arms=arms, beats=beats, bw=bw, lead=lead, beat_s=beat_s, preset=presets["R"] if presets["L"] == presets["R"] else f"left {presets['L']}, right {presets['R']}", presets=presets, TP=TP, accents=acc)


def r1(x): return round(float(x), 1)
def rl(a, n=3): return np.round(np.asarray(a, float), n).tolist()
ARM_SHOW = ("sh_flex", "sh_abd", "sh_twist", "elbow", "pron", "wrist_twist", "wrist_flex", "wrist_dev", "swivel", "clav_elev", "clav_prot", "stick_alpha", "stick_beta", "index_pip")


def finish(P, kind, ident, perfs, R_arm, R_sync, sync_rows, foot_events, extra, ds=None, paths=None):
    """bake, check the whole body, write the drive skeleton, the inspector data and the report rows -> (checks, info)"""
    import body_bake as BB, body_checks as BK
    N = P["N"]; bpm = P["bpm"]; delta = BB.deltas(P, perfs)
    ds = ds or kind; paths = paths or {}                    # paths (the fingers round): dict(drive=, inspector=) so a machine-written series lands in its own subfolder (None = not kept: /dev/null)
    quat = BB.drive(P, perfs, paths["drive"] if "drive" in paths else LAB / (f"out/drive_fullbody_{kind}_{V}.json" if ds == kind else f"out/ladder/drive_{ds}_{V}.json"), f"full-body driving skeleton, {ident}: VRM 1.0 humanoid names + arm twist bones + stick.L/R, local rotations (quaternions x,y,z,w) at 120 Hz")
    Rb, aux = BK.run(P, perfs, kind, quat, foot_events, bpm); R = {}
    for h in "LR": R.update({f"{k} arm {h}": v for k, v in R_arm[h].items()})
    R.update({f"{k} body" if not k.endswith(("body", "legs")) else k: v for k, v in Rb.items()}); R["sync"] = R_sync
    fails = []
    for k, r in R.items():
        if r["ok"] or not r.get("frames"): continue
        f = np.array(r["frames"])
        for a_ in np.split(f, np.nonzero(np.diff(f) > 2)[0] + 1)[:3 if k.startswith("C-GRIP-1") else 25]: fails.append(dict(f=int(a_[0]), f1=int(a_[-1]), check=k, text=r["note"][:110]))      # the thumb's drift (C-GRIP-1) recurs on every lift: its first three runs stand for the rest
    fails.sort(key=lambda e: e["f"]); ch = aux["ch"]; lim = {}
    for k in ch:
        if not k.startswith("knee_swivel"): lim[k] = BK.lim_of(k)
    D = dict(id=ident, kind=kind, hz=HZ, N=N, every=EV, names=AR.NAMES, delta=delta, bpm=bpm, beats=rl(P["beats"], 4), bw=rl(P["bw"], 2), preset=P.get("preset"),
             body=dict(ch={k: rl(v, 2) for k, v in ch.items()}, speed={k: rl(v, 0) for k, v in aux["speeds"].items()}, limits=lim, ceilings=BC["ceilings"]),
             arms={h: dict(ch={k: rl(perfs[h]["ch"][k], 2) for k in ARM_SHOW if k in perfs[h]["ch"]}, speed={k: rl(v, 0) for k, v in perfs[h]["speeds"].items()}, pts={k: rl(perfs[h]["pts"][k]) for k in "SEW"}, tgt=rl(perfs[h]["W_plan"]),
                           reach=rl(perfs[h]["flags"]["reach_ratio"]), ellipse=rl(np.sqrt(perfs[h]["flags"]["wrist_ellipse"]), 2), prior=rl(perfs[h]["prior"], 1), pen_mm=rl(perfs[h]["pen_depth"] * 1000, 1),
                           stick=dict(tip=rl(perfs[h]["stick"]["tip"]), butt=rl(perfs[h]["stick"]["butt"]), F=rl(perfs[h]["stick"]["F"])) if "stick" in perfs[h] else None, strokes=perfs[h].get("strokes", [])) for h in "LR"},
             arm_limits=CFG["limits"], arm_ceilings=CFG.get("hard_ceilings", CFG["ceilings"]), ceiling_scale=1.0, steps=CFG["steps"],
             feet={s: dict(ball=rl(P["legs"][s]["ball"]), heel=rl(P["feet"][s]["heel"]), ankle=rl(P["legs"][s]["ankle"]), knee=rl(P["legs"][s]["knee"]), hip=rl(P["legs"][s]["hip"]), toe=rl(P["legs"][s]["toe_tip"]),
                           heel_mm=rl(P["feet"][s].get("heel_h", np.zeros(N)) * 1000, 1), reach=rl(P["legs"][s]["reach_ratio"])) for s in "LR"},
             slide_mm=rl(aux["slide"] * 1000, 2), pen_mm=rl(aux["pen"] * 1000, 1), limbs={k: rl(v, 0) for k, v in aux["limbs"].items()},
             layers=dict(L0={k: rl(P["L0"][k], 2) for k in ("lean", "side", "turn")}, pulse=rl(P["lay"]["curves"]["pulse"], 3), accent=rl(P["lay"]["curves"]["accent"], 3), breath=rl(P["lay"]["curves"]["breath"], 2), sway=rl(P["lay"]["curves"]["sway"], 3),
                         total={k: rl(P["ch"][k], 2) for k in ("lean", "side", "turn", "nod", "look", "tilt")}, shift_mm=rl(P["ch"]["shift"] * 1000, 1)),
             gaze=dict(keys=P["gz"]["keys"], head=rl(BR.pt(P["T"]["head"], AR.HEAD["head"] + np.array([0, 0, 0.10]))), fwd=rl(np.einsum("nij,j->ni", P["T"]["head"][:, :3, :3], np.array([0, -1.0, 0])))),
             checks=R, fails=fails, sync_rows=sync_rows)
    D.update(extra); pathlib.Path(paths["inspector"]).parent.mkdir(parents=True, exist_ok=True) if "inspector" in paths else None      # midi2motion: was a mkdir inside the lab folder
    json.dump(D, open(paths["inspector"] if "inspector" in paths else LAB / f"inspector/data/body_{ds}.json", "w"), separators=(",", ":"), default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o))
    return R, delta, aux


def strip(R):
    return {k: {a: b for a, b in v.items() if a not in ("frames", "raw_frames", "rows")} | dict(first_frames=v.get("frames", [])[:12]) for k, v in R.items()}


def run_drums(preset="german", write=True):
    import body_bake as BB, body_checks as BK
    P = plan_drums(preset); d = P["d"]; kit, DP = d["kit"], d["DP"]; N = P["N"]; P["bpm"] = 60.0 / P["beat_s"]; perfs = {}; R_arm = {}
    for h in "LR":
        a = P["arms"][h]; pl, out, rig, S = a["pl"], a["out"], a["rig"], a["S"]
        ev = [dict(f=int(round(s["t"] * HZ)), f_end=int(round(s["t_end"] * HZ)) if s["kind"] == "sweep" else None, t=round(s["t"], 4), vel=s["vel"], piece=s["piece"], zone=s["zone"], type=s["kind"]) for s in S if 0 <= s["t"] * HZ < N]
        cont = [e["f"] for e in ev] + [int(round(n["tc"] * HZ)) for n in d["notes"][h] if 0 <= n["tc"] * HZ < N]
        perf = bake.assemble(rig, out, pl["W"], pl["Hm"], pl["curls"], 0.0, None, "drums", f"drums_b85-92_{h}", W_raw=pl["W_raw"], stick=dict(grip=pl["grip"], alpha=pl["alpha"], beta=pl["beta"]), thumb_abd=pl["grip"].thumb_abd, events=ev,
                             contacts=cont, mode=pl["T"]["mode"].copy(), extra=dict(env={}, bpm=P["bpm"], lam=pl["lam"]))
        R = checks.run(perf); perf["env"] = dict(kit=kit, DP=DP); R = checks.grip_checks(perf, pl, R); perfs[h] = perf; R_arm[h] = R
    R_sync, rows = BK.drum_sync(P, perfs); ped = P["ped"]
    fe = dict(R=[int(round(n["tc"] * HZ)) for n in ped["kicks"] if 0 <= n["tc"] * HZ < N] + [int(round(t * HZ)) for t in P["feet"]["kick_idle_beats"] if 0 <= t * HZ < N], L=[int(round(t * HZ)) for t in P["feet"]["taps"]] + [int(round(n["tc"] * HZ)) for n in d["all_notes"] if n["note"] in (42, 44, 46) and 0 <= n["tc"] * HZ < N])       # the hat foot's events: its taps, its pedal notes, and every hat note it opens or shuts the cymbals for
    old = d["old"]; hat_diff = float(np.abs(np.array(old["hat"]) - ped["hat"][::EV]).max()); be_diff = float(np.abs(np.array(old["beater"]) - ped["beater"][::EV]).max())
    hits = [dict(t=round(n["tc"], 4), limb=n["limb"], piece=n["piece"], note=n["note"], vel=n["vel"]) for n in d["all_notes"] if 0 <= n["tc"] < N / HZ]
    for x in d["resticked"]:
        for hrow in hits:
            if abs(hrow["t"] - x["t"]) < 1e-3 and hrow["piece"] == x["piece"] and hrow["limb"] == x["hand"]: hrow["limb"] = ("L" if x["hand"] == "R" else "R") if x["change"].startswith("moved") else None; hrow["note_change"] = x["change"]; break
    extra = dict(title="D2 drums, full body: both hands, both feet, closure bars 85-92", kit=old["kit"], chart=dict(bars=d["bars"], lead=d["lead"], bar_s=d["bar_s"]), audio="../../2026-11-16-android-drums/inspector/audio/closure_b85-92.opus", hits=hits,
                 pedals=dict(beater=rl(ped["beater"], 2), hat=rl(ped["hat"], 3), kick_plate=rl(P["feet"]["plate_deg"]["R"], 2), hat_plate=rl(P["feet"]["plate_deg"]["L"], 2), taps=P["feet"]["taps"], kick_idle=P["feet"]["kick_idle_beats"]),
                 kit_state=old["kit_state"], hat30=old["hat"], resticked=d["resticked"], grip={h: P["arms"][h]["grip"].report for h in "LR"})
    R, delta, aux = finish(P, "drums", "drums_b85-92_fullbody", perfs, R_arm, R_sync, rows, fe, extra)
    if write: BB.render_drums(P, perfs, delta, LAB / f"work/fullbody/render_fullbody_drums_{V}.json")
    info = dict(preset=preset, resticked=d["resticked"], trunk_range={k: [r1(P["ch"][k].min()), r1(P["ch"][k].max())] for k in ("lean", "side", "turn")}, pedal_envelopes_vs_old_bake=dict(hat_max_diff=round(hat_diff, 4), beater_max_diff_deg=round(be_diff, 3)),
                feedback={h: P["arms"][h]["pl"]["feedback_clamp_frames"] for h in "LR"}, lift_scale_min={h: round(P["arms"][h]["pl"]["lift_scale_min"], 2) for h in "LR"}, heel_taps=P["feet"]["taps"], kick_idle_beats=P["feet"]["kick_idle_beats"],
                gaze_keys=len(P["gz"]["keys"]), grip={h: P["arms"][h]["grip"].report for h in "LR"})
    return R, info, P, perfs


def rim_floor(d, clear=None):
    """R-417, the cause of the forearm-in-rim frames (README, Full body, item 4): the chart's wrist target sits lower than the console's rim wherever the hand is flat on a key
    (a slam's -16 deg pitch puts the forearm's wrist end 13-17 mm inside it). The wrist target gets a FLOOR while it is over or inside the rim band: rim height + the forearm
    capsule's radius + 6 mm, blended in over 6 cm of approach so the path has no corner. -> f(W (N,3), hard=False) -> W"""
    RG = d["RG"]; clear = clear if clear is not None else CFG["capsules"]["forearm"]["r"] + 0.006; floor = RG.RIM_Z + clear
    cache = {}
    def f(W, hard=False):
        if not hard or "w" not in cache:                                              # the hard pass (inside the smoothing loop) reuses the blend of the pass before it: the wrist's path over the console barely moves with the smoothing
            Ww = W @ d["Rz"].T + d["mark"]; dd = np.array([RG.console_d(p[0], p[1])[1] for p in Ww]); w = np.clip((0.09 - dd) / 0.06, 0.0, 1.0); cache["w"] = w * w * (3 - 2 * w)      # 1 over the rim band (d <= 0.03), 0 from 9 cm out on the keys
        w = cache["w"]; zf = np.where(w >= 0.999, floor, -9.0) if hard else np.where(w > 0, floor - 0.10 * (1 - w), -9.0); W = W.copy(); W[:, 2] = np.maximum(W[:, 2], zf); return W
    return f


# ---------------------------------------------------------------- D1: the piano chart, 1P, both hands, standing at the console
def plan_piano(verbose=True, bt=None):
    raise NotImplementedError("midi2motion packages the drums only"); N = d["N"]; body = BR.Body(False); spb = d["spb"]; t0 = time.time(); bar0 = d["lead_beats"] * spb; bar_s = d["bpb"] * spb; hands = d["hands"]
    L0 = BP.reach_plan(body, {h: hands[h]["pad"] for h in "LR"}, "keys", N, ahead={h: [(n["t"], hands[h]["pad"][int(np.clip(round(n["t"] * HZ), 0, N - 1))]) for n in hands[h]["notes"]] for h in "LR"})
    beats = bar0 + spb * np.arange(-int(d["lead_beats"]), int((N / HZ - bar0) / spb) + 2); notes = [dict(tc=x["tc"], vel=x["vel"]) for x in d["all_notes"] if x["hands"]]; bw = BP.beat_weights(beats, notes)
    vs = sorted(n["vel"] for n in notes); loud = vs[int(0.8 * (len(vs) - 1))] if vs else 127
    acc = [(n["tc"], 100 + 27 * (n["vel"] - loud) / max(1, vs[-1] - loud)) for n in notes if n["vel"] >= loud and np.abs(beats - n["tc"]).min() > 0.05 and 0 <= n["tc"] < N / HZ]       # the loudest fifth of the notes, off the beat
    lay = BP.layers(N, beats, bw, bar0, bar_s, acc)
    pre = body.trunk(body_channels(body, L0, lay, None, N)); head_pos = BR.pt(pre["T"]["head"], AR.HEAD["head"] + np.array([0, -0.05, 0.10])); gev = []
    for h in "LR":
        prev = None
        for n in hands[h]["notes"]:
            f = int(np.clip(round(n["t"] * HZ), 0, N - 1)); A_ = hands[h]["pad"][f]; gev.append(dict(t=n["t"], A=A_, travel=1.0 if prev is None else float(np.linalg.norm(A_ - prev)), vel=n["vel"])); prev = A_
    gz = BP.gaze(body, gev, L0["turn"] + lay["turn"], head_pos, N); ch = body_channels(body, L0, lay, gz, N); K = body.trunk(ch); T = K["T"]
    feet = {s: body.foot_on_floor(s, N) for s in "LR"}; legs = {s: body.leg(s, T["hips"], feet[s]["ankle"], feet[s]["foot_dir"], feet[s]["toe_dir"], foot_x=feet[s]["foot_x"]) for s in "LR"}; caps = body.caps(T, legs); arms = {}
    for h in "LR":
        rig = AR.ArmRig(T["chest"], caps, h); tg = hands[h]; cg = np.arange(0, 0.8001, 0.01); tab = []; r0 = AR.ArmRig(side=h)
        for c in cg:
            _, tp = r0.hand_bones(np.eye(3), np.zeros(3), [tg["thumb_curl"], c, c, c, c], tg["spread"]); tab.append(np.mean([tp[f] for f in ("index", "middle", "ring")], 0))
        tab = np.array(tab); tl = lambda c, tab=tab: np.stack([np.interp(c, cg, tab[:, i]) for i in range(3)], 1)                       # the fingertips' centre in the hand's frame, continuous in the curl
        tg["w_floor"] = rim_floor(d)
        kp = keys_plan.plan(rig, tg, tl); arms[h] = dict(rig=rig, kp=kp, out=kp["out"], tg=tg)
        if verbose:
            fl = kp["out"]["flags"]; print(f"  arm {h}: passes {[(x['clamp_frames'], x['wrist_accel_max']) for x in kp['passes']]}, reach max {fl['reach_ratio'].max():.3f} ({int(fl['reach_over'].sum())} frames > 0.97), unattained {fl['unattained_m'].max() * 1000:.1f} mm, "
                                     f"limit clamps { {k: int(v.sum()) for k, v in fl['limit_clamp'].items() if v.any()} }, {time.time() - t0:.0f}s", flush=True)
    return dict(d=d, body=body, N=N, ch=ch, K=K, T=T, L0=L0, lay=lay, gz=gz, feet=feet, legs=legs, caps=caps, arms=arms, beats=beats, bw=bw, bpm=d["bpm"], accents=acc, bar0=bar0, bar_s=bar_s)


def run_piano(write=True, cfg=None):
    """cfg (the piano ladder, tools/ladder.py): dict(bt=BT.piano's arguments, ds=the inspector dataset, ident, title, audio (from inspector/), render=the render perf's path, extra=more inspector fields); none = the full-body round's clip"""
    import body_bake as BB
    cfg = cfg or {}; P = plan_piano(bt=cfg.get("bt")); d = P["d"]; N = P["N"]; RG = d["RG"]; perfs = {}; R_arm = {}; to_w = lambda p: p @ d["Rz"].T + d["mark"]; rows = []; TOUCH = d["touch"]; M = len(range(0, N, EV))
    gend = dict(TAP=0.15, HOLD=0.13, SWEEP=0.14, SLAM=0.22, FLICK=0.34); sink = np.zeros((M, RG.NK)); KSTEP = 2 * RG.SPAN / RG.NK
    for h in "LR":
        a = P["arms"][h]; kp, out, rig, tg = a["kp"], a["out"], a["rig"], a["tg"]; curl = kp["curl"]; curls = np.stack([np.full(N, tg["thumb_curl"]), curl, curl, curl, curl], 1)
        ev = [dict(f=int(round(n["t"] * HZ)), f0=int(round((n["t"] - (0.14 if n["type"] == "SLAM" else 0.11)) * HZ)), f_end=int(round((n["t"] + (n["dur"] if n["type"] in ("HOLD", "SWEEP") else 0) + gend[n["type"]]) * HZ)), t=round(n["t"], 4), type=n["type"], vel=n["vel"], lane=n["lane"], lane_end=n["lane_end"], id=n["id"], bar=n["bar"]) for n in tg["notes"]]
        perf = bake.assemble(rig, out, kp["W"], kp["Hm"], curls, tg["spread"], None, "keys", cfg.get("ident", "piano_b65-72_1P") + f"_{h}", W_raw=tg["W"], events=ev, contacts=[int(x) for x in kp["hitf"]], extra=dict(env=dict(surfaces=d["surfaces"], to_world=to_w), bpm=d["bpm"], lam=kp["lam"]))
        R_arm[h] = checks.run(perf); perfs[h] = perf
        # sync: chart_play's own audit on these fingertips at 30 fps (as the proof ran it for the right hand)
        tips = np.stack([to_w(perf["tips"][f][::EV]) for f in ("index", "middle", "ring", "pinky")], 1); low = tips[np.arange(M), tips[:, :, 2].argmin(1)]; z = low[:, 2]
        for f in range(M):
            for q in tips[f]:
                if q[2] <= TOUCH:
                    aang, dd = RG.console_d(q[0], q[1]); k2 = int((aang + RG.SPAN) / KSTEP)
                    if 0.03 <= dd <= RG.KD and 0 <= k2 < RG.NK: sink[f, k2] = 1.0
        for n in tg["notes"]:
            f0 = n["t"] * 30; lo, hi = max(0, int(f0) - 3), min(M - 1, int(f0) + 6); c = next((f for f in range(lo, hi + 1) if z[f] <= TOUCH and f > 0 and z[f - 1] > TOUCH), None)
            r = dict(id=n["id"], hand=h, type=n["type"], f=int(round(n["t"] * HZ)), frame=int(round(f0)), t=round(n["t"], 4), vel=n["vel"], lane=n["lane"], played=c is not None, err=None if c is None else round(c - f0, 2), lane_off=None if c is None else round(float(d["lane_of"](low[c]) - n["lane"]), 2))
            if c is not None and n["type"] in ("HOLD", "SWEEP"):
                fe = (n["t"] + n["dur"]) * 30; rel = next((f for f in range(c + 1, M) if z[f] > TOUCH), M - 1); r["release_err"] = round(rel - fe, 2); r["held"] = round(float((z[c:int(fe)] <= TOUCH).mean()) if int(fe) > c else 1.0, 2)
                if n["type"] == "SWEEP": r["end_lane_off"] = round(float(d["lane_of"](low[min(M - 1, int(fe) - 1)]) - n["lane_end"]), 2)
            if c is None: r["why"] = "hand already down: no new strike" if (z[lo:hi + 1] <= TOUCH).any() else "never reached the keybed"
            r["fail"] = (c is None) or abs(r["err"]) > 1.0 or abs(r["lane_off"]) > 0.5 or abs(r.get("release_err", 0)) > 2 or r.get("held", 1) < 0.9; r["ok"] = not r["fail"]; rows.append(r)
        perf["tips_low"] = low
    pl = [r for r in rows if r["played"]]; unpl = [x for x in d["all_notes"] if not x["hands"]]
    R_sync = checks.res(not any(r["fail"] for r in rows), "every note the chart deals to a hand is struck within +-1 frame (30 fps) on its lane, holds held and released on time (chart_play's own audit, on these fingertips)", [r["f"] for r in rows if r["fail"]],
                        notes={h: sum(r["hand"] == h for r in rows) for h in "LR"}, ok_by_hand={h: sum(r["hand"] == h and r["ok"] for r in rows) for h in "LR"}, hit_err_max_frames=round(max(abs(r["err"]) for r in pl), 2) if pl else None,
                        hit_err_mean_abs_frames=round(float(np.mean([abs(r["err"]) for r in pl])), 2) if pl else None, chart_notes_no_hand=len(unpl), failing=[r for r in rows if r["fail"]][:12])
    P["keys_sink"] = sink.tolist(); old = d["old"]
    hits = [dict(t=r["t"], limb=r["hand"], piece=f"lane {r['lane']}", note=r["type"], vel=r["vel"]) for r in rows]
    extra = dict(title=cfg.get("title", "D1 piano chart, full body: 1P both hands, closure bars 65-72"), key_quads=old["key_quads"], key_z=old["key_z"], mark=rl(d["mark"], 4), yaw=d["yaw"], beat0=d["b0"], bars=d["bars"], hits=hits,
                 audio=cfg.get("audio", "../../2026-11-15-android-mocap-midi/inspector/audio/closure_b65-72.mp3"), tips_low={h: rl(perfs[h]["tips_low"]) for h in "LR"}, keys_lit=old["keys"], keys_sink=P["keys_sink"])
    extra.update(cfg.get("extra", {}))
    R, delta, aux = finish(P, "keys", cfg.get("ident", "piano_b65-72_1P") + "_fullbody", perfs, R_arm, R_sync, rows, {"L": [], "R": []}, extra, ds=cfg.get("ds"))
    if write: BB.render_piano(P, delta, LAB / cfg.get("render", f"work/fullbody/render_fullbody_piano_{V}.json"))
    info = dict(trunk_range={k: [r1(P["ch"][k].min()), r1(P["ch"][k].max())] for k in ("lean", "side", "turn")}, pelvis_shift_mm=[r1(P["ch"]["shift"][:, 0].min() * 1000), r1(P["ch"]["shift"][:, 0].max() * 1000)],
                planner_passes={h: P["arms"][h]["kp"]["passes"] for h in "LR"}, gaze_keys=len(P["gz"]["keys"]), chart_notes_no_hand=[dict(id=x["id"], type=x["type"], t=round(x["tc"], 3)) for x in unpl], sync_rows=rows)
    return R, info, P, perfs


def summary(R):
    for k, v in R.items():
        keep = {a: b for a, b in v.items() if a not in ("frames", "note", "ok", "rows", "raw_frames", "failing", "ranges_deg", "input_before_planning", "runs")}
        print(("  pass " if v["ok"] else "  FAIL ") + k.ljust(22), ("" if v["ok"] else f"[{v['n_frames']} frames] ") + json.dumps(keep, default=str)[:360])

# midi2motion: the lab's command line (proof sets, piano ladder) was dropped
