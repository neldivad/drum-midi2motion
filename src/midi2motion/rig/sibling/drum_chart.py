#!/usr/bin/env python3
# midi2motion: vendored from nelvids/lab/wrapped/3d/2026-11-16-android-drums/tools/drum_chart.py (a wrapped lab, read-only source). Solver behaviour unchanged; only data paths and the lab command line were changed.
"""drum_chart.py: his drum MIDI -> a playable drum chart: every note mapped to a kit piece and zone, articulations grouped into
gestures (R-401), limbs assigned by sticking rules with lookahead, impossible moments reported with how they were resolved.

    <venv>/python tools/drum_chart.py <drum-full.mid> out/closure_drum_chart.json [--bars 85-92] [--fps 30] [--lead 0.5] [--tail 0.7]

How his articulations are written (found by inspection of closure's drum-full.mid; no CC, no markers, no keyswitches, no track names beyond
the 8 pattern channels): as RUNS OF THE SAME NOTE, off the 16th grid, 8-16 ticks apart (96 ticks a beat), 3-9 ticks long, with a rising velocity
ramp, ending on one long note. So:
- sweep: >= 4 hits of one cymbal note (51 ride, 53 bell), each <= 16 ticks after the last. Its end note (the same or the other ride zone, <= 16
  ticks later) is the accent the sweep lands on.
- crescendo: >= 3 hits of one drum note, each <= 48 ticks (an 8th) after the last, velocities strictly rising from a ghost (<= 30) by >= 15.
One gesture each, one limb, never a run of separate strokes.

Sticking (a right-handed kit): right foot kick, left foot hat pedal; hands by a beam search over the whole song (so every choice sees the
future): each hand prefers its side's pieces (hats, ride, crash, low toms right; snare, cross-stick left), pays for travel speed, for
repeating faster than a hand can, and for crossing (the right hand left of the left hand), except the standard crossed hat-over-snare.
Layers (clap 39) sound but get no limb. Two zones of one piece at one instant (ride bow + bell) are one stroke. More hand hits than hands: the quietest go (ghosts first), reported.
"""
import argparse, collections, json, pathlib, sys
import numpy as np, mido
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import kit

PREF = {"hat": {"R": 0.0, "L": 1.5}, "ride": {"R": 0.0, "L": 6.0}, "crash": {"R": 0.4, "L": 0.5}, "snare": {"L": 0.0, "R": 0.6}, "cross": {"L": 0.0, "R": 5.0},
        "tom1": {"L": 0.3, "R": 0.3}, "tom2": {"R": 0.2, "L": 0.7}, "tom3": {"R": 0.0, "L": 2.0}, "floor": {"R": 0.0, "L": 2.5}}
MIN_REPEAT = 0.085          # s: one hand cannot restrike faster than this (a 16th at 150 BPM is 0.100)


def read(path):
    m = mido.MidiFile(path); tempo = 500000; N = []
    for i, tr in enumerate(m.tracks):
        t = 0; on = {}
        for msg in tr:
            t += msg.time
            if msg.type == "set_tempo" and t == 0: tempo = msg.tempo
            if msg.type == "note_on" and msg.velocity > 0: on[msg.note] = (t, msg.velocity)
            elif msg.type in ("note_off", "note_on") and msg.note in on:
                t0, v = on.pop(msg.note); N.append(dict(tick=t0, note=msg.note, vel=v, dur=t - t0, track=i))
    N.sort(key=lambda n: (n["tick"], n["note"])); return N, m.ticks_per_beat, tempo / 1e6 / m.ticks_per_beat


def articulations(N, tpb):
    """tag notes with art = {id, kind, i, n}; returns the groups"""
    groups = []; by = collections.defaultdict(list); u = tpb / 96.0
    for n in N: by[n["note"]].append(n)
    for note in (51, 53):
        L = by[note]; run = L[:1]
        for a in L[1:] + [None]:
            if a is not None and a["tick"] - run[-1]["tick"] <= 16 * u: run.append(a); continue
            if len(run) >= 4:
                end = [x for x in by[51] + by[53] if 0 < x["tick"] - run[-1]["tick"] <= 16 * u and x not in run]
                pre = [x for x in by[51] + by[53] if 0 <= run[0]["tick"] - x["tick"] <= 16 * u and x not in run]      # a hit on the same cymbal the sweep starts from
                groups.append(dict(kind="sweep", zone="bell" if note == 53 else "ride", notes=pre[-1:] + run + end[:1], lands_on=end[0]["note"] if end else note))
            run = [a] if a is not None else []
    for note in (38, 41, 43, 45, 47, 48, 50):
        L = by[note]; run = L[:1]
        def flush(run):
            while len(run) >= 3 and not (run[0]["vel"] <= 30): run = run[1:]
            if len(run) >= 3 and run[-1]["vel"] - run[0]["vel"] >= 15: groups.append(dict(kind="crescendo", zone=kit.NOTE_MAP[note][0], notes=run))
        for a in L[1:] + [None]:
            if a is not None and a["tick"] - run[-1]["tick"] <= 48 * u and a["vel"] > run[-1]["vel"]: run.append(a); continue
            flush(run); run = [a] if a is not None else []
    groups.sort(key=lambda g: g["notes"][0]["tick"])
    for gi, g in enumerate(groups):
        g["id"] = gi
        for i, n in enumerate(g["notes"]): n["art"] = dict(id=gi, kind=g["kind"], i=i, n=len(g["notes"]))
    return groups


def stick(N, spt, groups):
    """assign limbs in place (n['limb'] in RF LF R L, or None with n['why']); returns the impossible moments"""
    issues = []; hands = []
    for n in N:
        m = kit.NOTE_MAP.get(n["note"], None); n["t"] = n["tick"] * spt
        if m is None: n.update(piece=None, zone=None, limb=None, why="layer (R-401): sounds, no limb"); continue
        n["piece"], n["zone"] = m[0], m[1]
        if m[2] != "hand": n["limb"] = m[2]
        else: hands.append(n)
    sweep_of = {}
    for g in groups:
        if g["kind"] == "sweep":
            for n in g["notes"]: sweep_of[id(n)] = g
    onsets = collections.OrderedDict()
    for n in hands:
        g = sweep_of.get(id(n))
        if g is not None and n is not g["notes"][0]: n["limb"] = "sweep"; continue           # carried by the sweep's hand
        onsets.setdefault(n["tick"], []).append(n)
    merged = []                                                                      # two zones of ONE piece at one instant (ride bow + bell, snare head + rim) are one stroke: the louder zone plays, the other rides on it
    for tick, L in onsets.items():
        for n in sorted(L, key=lambda x: -x["vel"]):
            if n in L and any(m is not n and m in L and m["piece"] == n["piece"] and m["zone"] != n["zone"] and m["vel"] >= n["vel"] for m in L):
                lead = max((m for m in L if m is not n and m["piece"] == n["piece"] and m["zone"] != n["zone"]), key=lambda x: x["vel"]); L.remove(n); merged.append((n, lead))
    SP = {(p, z, h): kit.strike_point(p, z, h) for p, z, h in {(n["piece"], n["zone"], h) for n in hands for h in "LR"}}
    key = lambda n: "cross" if n["zone"] == "cross" else n["piece"]
    # beam: state = (cost, {hand: (piece, zone, t_free, t_last)}, choices)
    beam = [(0.0, {"L": None, "R": None}, [])]
    for tick, L in onsets.items():
        t = tick * spt; drop = []
        new = []
        for cost, st, ch in beam:
            free = [h for h in "LR" if st[h] is None or st[h][2] <= t + 1e-6]
            cand = sorted(L, key=lambda n: (-(n.get("art", {}).get("kind") == "sweep"), -n["vel"]))
            keep, dropped = cand[:len(free)], cand[len(free):]
            opts = []
            if len(keep) == 1: opts = [((keep[0], h),) for h in free]
            elif len(keep) == 2: opts = [((keep[0], "L"), (keep[1], "R")), ((keep[0], "R"), (keep[1], "L"))]
            elif len(keep) == 0: opts = [()]
            for opt in opts:
                c = cost + 40.0 * len(dropped); s2 = dict(st)
                for n, h in opt:
                    c += PREF[key(n)][h]; prev = st[h]
                    if prev is not None:
                        dt = t - prev[3]; dist = float(np.linalg.norm(SP[(n["piece"], n["zone"], h)] - SP[(prev[0], prev[1], h)]))
                        if dt < MIN_REPEAT: c += 60.0
                        c += 2.0 * max(0.0, dist / max(dt, 1e-3) - 1.5) ** 2 + (2.0 if dt < 0.125 else 0.4 if dt < 0.16 else 0.0)
                    g = sweep_of.get(id(n)); tf = g["notes"][-1]["tick"] * spt if g is not None else t
                    s2[h] = (n["piece"], n["zone"], tf, tf)
                if s2["L"] is not None and s2["R"] is not None and min(t - s2["L"][3], t - s2["R"][3]) > -1e-6 and max(t - s2["L"][3], t - s2["R"][3]) < 0.4 and opt:
                    xl = SP[(s2["L"][0], s2["L"][1], "L")][0]; xr = SP[(s2["R"][0], s2["R"][1], "R")][0]
                    if xr > xl + 0.05:                                                # the right hand is left of the left hand: crossed
                        pr, pl = s2["R"][0], s2["L"][0]
                        c += 0.0 if (pr == "hat" and pl == "snare") else 0.3 if (pr == "crash" and pl == "snare") else 2.5
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
            n = byid[i]; n["limb"] = None; L = onsets[tick]
            busy = [g for g in groups if g["kind"] == "sweep" and g["notes"][0]["tick"] < tick <= g["notes"][-1]["tick"]]
            n["why"] = "more hand hits than free hands: dropped (the quietest)" + ("; one hand is in a sweep" if busy else "")
            issues.append(dict(tick=tick, bar=round(tick * spt / (spt * 96 * 4) + 1, 3) if False else None, kind="more hits than hands", hits=[f'{kit.NAMES[x["note"]]} v{x["vel"]}' for x in L], dropped=f'{kit.NAMES[n["note"]]} v{n["vel"]}', sweep=bool(busy)))
    for g in groups:
        if g["kind"] == "sweep":
            for n in g["notes"][1:]: n["limb"] = g["notes"][0]["limb"]
    for n, lead in merged: n["limb"] = lead["limb"]; n["merged"] = True; n["why"] = f"one stroke with {kit.NAMES[lead['note']]} (two zones of one piece)"
    return issues


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("mid"); ap.add_argument("out"); ap.add_argument("--bars", default="85-92"); ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--lead", type=float, default=0.5); ap.add_argument("--tail", type=float, default=0.7); A = ap.parse_args()
    N, tpb, spt = read(A.mid); bar = tpb * 4; groups = articulations(N, tpb); issues = stick(N, spt, groups)
    for i in issues: i["bar"] = round(i["tick"] / bar + 1, 3)
    b0, b1 = (int(x) for x in A.bars.split("-")); t0 = (b0 - 1) * bar * spt - A.lead; dur = (b1 - b0 + 1) * bar * spt + A.lead + A.tail
    for n in N:
        n["tc"] = round(n["t"] - t0, 5); n["frame"] = int(round(n["tc"] * A.fps)); n["bar"] = round(n["tick"] / bar + 1, 3); n["t"] = round(n["t"], 5)
    # whole-song playability
    hand = [n for n in N if n["piece"] and n["limb"] in ("L", "R") and not n.get("merged")]; pair = collections.Counter(); cross = 0; fast = collections.Counter(); last = {}
    for n in hand:
        if n["limb"] in last:
            dt = n["t"] - last[n["limb"]]["t"]
            if 0 < dt < 0.125: fast[n["limb"]] += 1
        last[n["limb"]] = n
    sim = collections.defaultdict(list)
    for n in N: sim[n["tick"]].append(n)
    limbs = collections.Counter(n["limb"] for n in N if n["limb"]); layers = collections.Counter(kit.NAMES[n["note"]] for n in N if n["piece"] is None)
    most = max(len(v) for v in sim.values())
    stats = dict(notes=len(N), bpm=round(60 / (spt * tpb), 3), ticks_per_beat=tpb, by_note={kit.NAMES.get(k, str(k)): v for k, v in sorted(collections.Counter(n["note"] for n in N).items())},
                 by_limb=dict(limbs), layers_not_played=dict(layers), max_simultaneous=most, impossible=issues,
                 same_hand_repeats_under_125ms=dict(fast), merged_same_piece=sum(1 for n in N if n.get("merged")), articulations=[dict(id=g["id"], kind=g["kind"], zone=g["zone"], bar=round(g["notes"][0]["tick"] / bar + 1, 3), n=len(g["notes"]),
                 ticks=[n["tick"] - g["notes"][0]["tick"] for n in g["notes"]], vel=[n["vel"] for n in g["notes"]], dur=[n["dur"] for n in g["notes"]], notes=[n["note"] for n in g["notes"]], limb=g["notes"][0].get("limb")) for g in groups])
    sec = [n for n in N if -1.6 <= n["tc"] <= dur + 1.6]
    out = dict(source=str(A.mid), bars=[b0, b1], fps=A.fps, t0=round(t0, 5), dur=round(dur, 5), frames=int(round(dur * A.fps)), spt=spt, tpb=tpb, bar_s=bar * spt, lead=A.lead,
               notes=sec, song=stats, note_map={str(k): (list(v) if v else None) for k, v in kit.NOTE_MAP.items()}, names={str(k): v for k, v in kit.NAMES.items()})
    json.dump(out, open(A.out, "w"), indent=0)
    inside = [n for n in sec if 0 <= n["tc"] < dur]
    print(json.dumps(dict(section_notes=len(inside), section_by_limb=dict(collections.Counter(str(n["limb"]) for n in inside)), song_by_limb=stats["by_limb"], layers=stats["layers_not_played"],
                          impossible=len(issues), impossible_in_section=[i for i in issues if b0 <= i["bar"] < b1 + 1], fast_repeats=stats["same_hand_repeats_under_125ms"],
                          articulations=[(a["kind"], a["zone"], a["bar"], a["n"], a["limb"]) for a in stats["articulations"]]), indent=1))


if __name__ == "__main__": main()
