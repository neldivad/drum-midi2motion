# LIBRARY COPY of drum-benchmark/tools/difficulty.py (nelvids lab, 2026-11-2x), packaged in midi2motion (vendored from the nelvids drums library): analysis-only functions and the lab's CLI dropped, lab paths -> rigenv.
#!/usr/bin/env python3
"""difficulty.py: R-558's difficulty per note, so a wrong drum's weight and whether substitution may be offered follow how hard the span is.

    import difficulty; hard = difficulty.hard_ids(notes)     notes: dicts with t (s), piece/row, limb (L/R/...), vel, id -> the ids of the notes in HARD spans
    difficulty.split(J)                                       a judgement: easy / hard notes and wrong drums in each (on the hand rows)

THE MEASURE (stated plainly; hand notes only):
  density  = hand notes in the second around the note (t - 0.5 .. t + 0.5), per second;
  busy     = the other hand has a note within 150 ms of it;
  cluster  = the note is in a recognised cluster: a drum sweep (tools/sweeps.py), a flam or drag (a grace 15-60 ms before a louder (>= 1.25 x) note, both notes),
             or a roll (>= 3 notes on one piece < 45 ms apart).
  HARD  = density >= 10 per second AND the other hand busy AND not in a cluster (a dense two-handed passage that isn't an ornament);
  EASY  = everything else (plain groove bars, sparse or slow notes, every recognised cluster).
In an easy span the nearest drum is never offered and a wrong drum is a full error; in a hard span the nearest drum is the last resort before a cut (remedies: row D558).
"""
import collections, pathlib, sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import sweeps as SW
HAND_ROWS = {"snare", "tom1", "tom2", "tom3", "floor", "floor2", "hat", "ride", "crash", "crash2", "china", "splash"}


def hard_ids(notes, beat_s, key="piece"):
    hand = sorted([n for n in notes if n.get(key) in HAND_ROWS and n.get("limb") in ("L", "R")], key=lambda n: n["t"]); T = [n["t"] for n in hand]; cl = set()
    for run in SW.find([dict(t=n["t"], row=n[key], id=n["id"]) for n in hand], beat_s): cl.update(x["id"] for x in run)
    for i, n in enumerate(hand):
        for m in hand[i + 1:]:
            if m["t"] - n["t"] > 0.060: break
            if m["t"] - n["t"] >= 0.015 and m.get("vel", 0) >= 1.25 * n.get("vel", 0): cl.update((n["id"], m["id"]))
    byp = collections.defaultdict(list)
    for n in hand: byp[n[key]].append(n)
    for p, L in byp.items():
        run = [L[0]]
        for a, b in zip(L, L[1:]):
            if b["t"] - a["t"] < 0.045: run.append(b); continue
            if len(run) >= 3: cl.update(x["id"] for x in run)
            run = [b]
        if len(run) >= 3: cl.update(x["id"] for x in run)
    import bisect
    out = set()
    for n in hand:
        dens = (bisect.bisect_right(T, n["t"] + 0.5) - bisect.bisect_left(T, n["t"] - 0.5)) / 1.0
        busy = any(m["limb"] != n["limb"] and abs(m["t"] - n["t"]) <= 0.150 for m in hand[max(0, bisect.bisect_left(T, n["t"] - 0.15)):bisect.bisect_right(T, n["t"] + 0.15)])
        if dens >= 10 and busy and n["id"] not in cl: out.add(n["id"])
    return out


def split(J):
    src = [dict(t=s["t"], row=s["row"], limb=(s.get("plan") or {}).get("limb") or (s.get("verdict") or {}).get("limb"), vel=s["vel"], id=s["id"], v=s.get("verdict") or {}) for s in J["source"] if s.get("judged") and s["row"] in HAND_ROWS]
    H = hard_ids(src, J["grid"]["beat_s"], key="row"); c = collections.Counter()
    for s in src:
        g = "hard" if s["id"] in H else "easy"; c[f"{g} notes"] += 1; c[f"{g} wrong"] += s["v"].get("cls") == "wrong"; c[f"{g} missed"] += s["v"].get("cls") == "missed"
    return c
