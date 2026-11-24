#!/usr/bin/env python3
# midi2motion: vendored from nelvids/lab/wrapped/3d/2026-11-16-rig-foundations/tools/drums2/chart2.py (a wrapped lab, read-only source). Solver behaviour unchanged; only data paths and the lab command line were changed.
"""chart2.py: his drum MIDI -> a playable chart for ANY layout of drumkit.yaml (drum round 2). The sibling's drum_chart.py is reused by path (its MIDI reader and its
articulation finder: sweeps and crescendo rolls stay their own gestures, R-401); its sticking is restated here because it named a right-handed kit:

    sibling drum_chart.py                      here
    PREF (typed per piece, right-handed)       K.PREF, derived from the layout and the lead hand (kitdata.derive_pref)
    NOTE_MAP kick -> RF, hat -> LF             the foot on the pedal's side (kitdata: K.FOOT_OF); a second kick takes the notes the first foot cannot repeat
    crossing: `hat over snare` is free         the LEAD hand on a time-keeper over the WEAK hand's backbeat is free (roles, drumkit.yaml preference.crossing)
    travel: (speed - 1.5 m/s)^2                the same, plus R-441: a minimum-jerk shift that cannot fit its window is priced, so the deal avoids it when it can

Every note carries its MIDI id (R-400: `D:<index in the file's sorted note list>`, with tick, note and track), so every later cut or misplay is logged against it.

(mido is read from the sibling lab's venv by path.)
"""
import argparse, collections, importlib.util, json, pathlib, sys
sys.dont_write_bytecode = True
import numpy as np
HERE = pathlib.Path(__file__).resolve().parent; DRUMS = HERE.parent / "sibling"      # midi2motion: the sibling modules are packaged beside the rig
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE)); sys.path.insert(0, str(DRUMS))
import kitdata, endpoints as EPT
MID = None; MIN_REPEAT = 0.100; FLAG_REPEAT = 0.140        # S-GRIP-6: >= 100 ms same hand (hard), < 140 ms flagged
MIN_FOOT = 0.150                                                                               # one foot's shortest re-strike on a pedal [ours, unverified: no pedal kinematics found]; a second kick takes what is faster


def sibling_chart(K):
    spec = importlib.util.spec_from_file_location(f"drum_chart_{K.PRESET}", DRUMS / "drum_chart.py"); DC = importlib.util.module_from_spec(spec); spec.loader.exec_module(DC); DC.kit = K; return DC


def stick(N, spt, groups, K):
    """limbs for every note, in place -> the impossible moments (more hand hits than hands)"""
    issues = []; hands = []; lead = K.LEAD; CR = K.CROSSING; role = lambda n: K.ROLE[n["piece"]]
    for n in N:
        m = K.NOTE_MAP.get(n["note"]); n["t"] = n["tick"] * spt
        if m is None: n.update(piece=None, zone=None, limb=None, why="layer (R-401): sounds, no limb" if n["note"] not in K.NOTE_UNMAPPED else f"no {K.NOTE_UNMAPPED[n['note']]} in this layout"); continue
        n["piece"], n["zone"] = m[0], m[1]
        if m[2] != "hand": n["limb"] = m[2]
        else: hands.append(n)
    if len(K.KICKS) > 1:                                                                # a second kick: its foot takes a kick the first foot cannot repeat in time, unless that foot is at work on the hi-hat pedal
        f2 = K.FOOT_OF[K.KICKS[1]] + "F"; last = -9.0; ped = [n["t"] for n in N if n.get("zone") == "pedal"]
        for n in N:
            if n.get("zone") != "beater": continue
            if n["t"] - last < MIN_FOOT and not any(abs(n["t"] - x) < 0.2 for x in ped): n["piece"] = K.KICKS[1]; n["limb"] = f2
            else: last = n["t"]
    sweep_of = {}
    for g in groups:
        if g["kind"] == "sweep":
            for n in g["notes"]: sweep_of[id(n)] = g
    onsets = collections.OrderedDict()
    for n in hands:
        g = sweep_of.get(id(n))
        if g is not None and n is not g["notes"][0]: n["limb"] = "sweep"; continue
        onsets.setdefault(n["tick"], []).append(n)
    merged = []                                                                          # two zones of ONE piece at one instant are one stroke (the sibling's rule)
    for tick, L in onsets.items():
        for n in sorted(L, key=lambda x: -x["vel"]):
            if n in L and any(m is not n and m in L and m["piece"] == n["piece"] and m["zone"] != n["zone"] and m["vel"] >= n["vel"] for m in L):
                ld = max((m for m in L if m is not n and m["piece"] == n["piece"] and m["zone"] != n["zone"]), key=lambda x: x["vel"]); L.remove(n); merged.append((n, ld))
    SP = {(p, z, h): K.strike_point(p, z, h) for p, z, h in {(n["piece"], n["zone"], h) for n in hands for h in "LR"}}
    key = lambda n: "cross" if n["zone"] == "cross" else n["piece"]
    beam = [(0.0, {"L": None, "R": None}, [])]
    for tick, L in onsets.items():
        t = tick * spt; new = []
        for cost, st, ch in beam:
            free = [h for h in "LR" if st[h] is None or st[h][2] <= t + 1e-6]
            cand = sorted(L, key=lambda n: (-(n.get("art", {}).get("kind") == "sweep"), -n["vel"])); keep, dropped = cand[:len(free)], cand[len(free):]
            opts = [((keep[0], h),) for h in free] if len(keep) == 1 else [((keep[0], "L"), (keep[1], "R")), ((keep[0], "R"), (keep[1], "L"))] if len(keep) == 2 else [()]
            for opt in opts:
                c = cost + 40.0 * len(dropped); s2 = dict(st)
                for n, h in opt:
                    c += K.PREF[key(n)][h]; prev = st[h]
                    if prev is not None:
                        dt = t - prev[3]; dist = float(np.linalg.norm(SP[(n["piece"], n["zone"], h)] - SP[(prev[0], prev[1], h)]))
                        if dt < MIN_REPEAT - 1e-6: c += 60.0
                        c += 2.0 * max(0.0, dist / max(dt, 1e-3) - 1.5) ** 2 + (2.0 if dt < 0.125 else 0.4 if dt < 0.16 else 0.0)
                        need = EPT.shift_time(dist); have = max(1e-3, dt - 0.05)             # R-441: the travel has the gap less the downstroke's last 50 ms
                        if dist > 0.05 and have < need: c += 30.0 * (1 - have / need)
                    g = sweep_of.get(id(n)); tf = g["notes"][-1]["tick"] * spt if g is not None else t; s2[h] = (n["piece"], n["zone"], tf, tf, K.ROLE[n["piece"]])
                if s2["L"] is not None and s2["R"] is not None and min(t - s2["L"][3], t - s2["R"][3]) > -1e-6 and max(t - s2["L"][3], t - s2["R"][3]) < 0.4 and opt:
                    xl = SP[(s2["L"][0], s2["L"][1], "L")][0]; xr = SP[(s2["R"][0], s2["R"][1], "R")][0]
                    if xr > xl + 0.05:                                                # crossed: the right hand is on the left of the left hand
                        pair = [s2[lead][4], s2["L" if lead == "R" else "R"][4]]; c += 0.0 if pair in CR["free"] else CR["cheap"]["cost"] if pair in CR["cheap"]["pairs"] else CR["cost"]
                new.append((c, s2, ch + [(tick, tuple((id(n), h) for n, h in opt), tuple(id(n) for n in dropped))]))
        new.sort(key=lambda x: x[0]); seen = set(); beam = []
        for c, s2, ch in new:
            k = tuple((h, s2[h]) for h in "LR")
            if k in seen: continue
            seen.add(k); beam.append((c, s2, ch))
            if len(beam) >= 160: break
    byid = {id(n): n for n in hands}
    for tick, opt, dropped in beam[0][2]:
        for i, h in opt: byid[i]["limb"] = h
        for i in dropped:
            n = byid[i]; n["limb"] = None; busy = [g for g in groups if g["kind"] == "sweep" and g["notes"][0]["tick"] < tick <= g["notes"][-1]["tick"]]
            n["why"] = "more hand hits than free hands: dropped (the quietest)" + ("; one hand is in a sweep" if busy else ""); n["limit"] = "two hands"
            issues.append(dict(tick=tick, kind="more hits than hands", hits=[f'{K.NAMES.get(x["note"], x["note"])} v{x["vel"]}' for x in onsets[tick]], dropped=f'{K.NAMES.get(n["note"], n["note"])} v{n["vel"]}', sweep=bool(busy)))
    for g in groups:
        if g["kind"] == "sweep":
            for n in g["notes"][1:]: n["limb"] = g["notes"][0]["limb"]
    for n, ld in merged: n["limb"] = ld["limb"]; n["merged"] = True; n["why"] = f"one stroke with {K.NAMES.get(ld['note'], ld['note'])} (two zones of one piece)"
    return issues


def song(K, mid=MID):
    DC = sibling_chart(K); N, tpb, spt = DC.read(str(mid))
    for i, n in enumerate(N): n["id"] = f"D:{i}"
    groups = DC.articulations(N, tpb); issues = stick(N, spt, groups, K); bar = tpb * 4
    for n in N: n["bar"] = round(n["tick"] / bar + 1, 3)
    for i in issues: i["bar"] = round(i["tick"] / bar + 1, 3)
    return N, tpb, spt, groups, issues


def difficulty(K, N, spt, tpb, b0, b1, groups):
    """one stated measure of a window (bars b0..b1 inclusive), on the dealt chart:
    D = hand strokes/s / 4 + foot notes/s / 4 + same-hand gaps under 140 ms per s + strike-point travel of both hands (m/s) + (pieces used - 3) / 4 + articulation gestures / 2 + notes no limb could take per s"""
    bar = tpb * 4 * spt; t0, t1 = (b0 - 1) * bar, b1 * bar; sec = t1 - t0; W = [n for n in N if t0 <= n["t"] < t1]; hs = [n for n in W if n["limb"] in ("L", "R") and not n.get("merged") and not (n.get("art", {}).get("kind") == "sweep" and n["art"]["i"] > 0)]
    fast = 0; travel = 0.0
    for h in "LR":
        L = sorted((n for n in hs if n["limb"] == h), key=lambda n: n["t"])
        for a, b in zip(L[:-1], L[1:]):
            fast += (b["t"] - a["t"]) < FLAG_REPEAT; travel += float(np.linalg.norm(K.strike_point(b["piece"], b["zone"], h) - K.strike_point(a["piece"], a["zone"], h)))
    feet = [n for n in W if n["limb"] in ("LF", "RF")]; arts = [g for g in groups if t0 <= g["notes"][0]["t"] < t1]; lost = [n for n in W if n["piece"] and not n["limb"]]; pcs = {n["piece"] for n in W if n["piece"]}
    D = len(hs) / sec / 4 + len(feet) / sec / 4 + fast / sec + travel / sec + (len(pcs) - 3) / 4 + len(arts) / 2 + len(lost) / sec
    return dict(bars=[b0, b1], seconds=round(sec, 2), notes=len(W), hand_strokes_per_s=round(len(hs) / sec, 2), foot_notes_per_s=round(len(feet) / sec, 2), fast_repeats_per_s=round(fast / sec, 2), travel_m_per_s=round(travel / sec, 2), pieces=sorted(pcs),
                articulations=[g["kind"] for g in arts], notes_no_limb=len(lost), D=round(D, 2))


def build(K, bars, mid=MID, fps=30, lead=0.5, tail=0.7):
    N, tpb, spt, groups, issues = song(K, mid); bar = tpb * 4; b0, b1 = bars; t0 = (b0 - 1) * bar * spt - lead; dur = (b1 - b0 + 1) * bar * spt + lead + tail
    for n in N: n["tc"] = round(n["t"] - t0, 5); n["frame"] = int(round(n["tc"] * fps)); n["t"] = round(n["t"], 5)
    sec = [n for n in N if -1.6 <= n["tc"] <= dur + 1.6]
    return dict(source=str(mid), preset=K.PRESET, bars=[b0, b1], fps=fps, t0=round(t0, 5), dur=round(dur, 5), frames=int(round(dur * fps)), spt=spt, tpb=tpb, bar_s=bar * spt, lead=lead, notes=sec,
                difficulty=difficulty(K, N, spt, tpb, b0, b1, groups), impossible=[i for i in issues if b0 <= i["bar"] < b1 + 1], names={str(k): v for k, v in K.NAMES.items()},
                articulations=[dict(id=g["id"], kind=g["kind"], zone=g["zone"], bar=round(g["notes"][0]["tick"] / bar + 1, 3), n=len(g["notes"]), limb=g["notes"][0].get("limb"), ids=[x["id"] for x in g["notes"]]) for g in groups if b0 <= g["notes"][0]["tick"] / bar + 1 < b1 + 1])

# midi2motion: the lab's command line (section scoring, chart dumps) was dropped
