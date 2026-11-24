# LIBRARY COPY of drum-benchmark/tools/sweeps.py (nelvids lab, 2026-11-2x), packaged in midi2motion (vendored from the nelvids drums library): analysis-only functions and the lab's CLI dropped, lab paths -> rigenv.
#!/usr/bin/env python3
"""sweeps.py: R-551's drum sweeps (a run across toms, with or without the snare), found in the MIDI with R-527's run rule, and their loss statistics.

    import sweeps; runs = sweeps.find(notes, beat_s)            notes: dicts with t (s), row/piece, id (and vel); -> [[note, ...], ...] in time order

THE RULE (ornament_score.py's greedy run, with a sweep's own gap): hand notes on drums (toms, snare) in time order; the next note joins the run when it comes at most a
16th later (x 1.15 for human timing, never more than 200 ms). A run is a SWEEP when it has >= 3 notes, >= 2 different drums and at least one tom (a run on the snare
alone is a roll, not a sweep). Cymbals end a run.
"""
import collections, glob, json, pathlib, sys
sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent; LAB = HERE.parent; sys.path.insert(0, str(HERE))
TOMS = {"tom1", "tom2", "tom3", "floor", "floor2"}; DRUMS = TOMS | {"snare"}


def find(notes, beat_s, key="row"):
    gap = min(0.200, 1.15 * beat_s / 4); src = sorted([n for n in notes if n.get(key) in DRUMS or n.get(key) in ("crash", "ride", "hat", "crash2", "china", "splash")], key=lambda n: n["t"])
    runs = []; run = []
    for n in src:
        if n[key] not in DRUMS:
            if run: runs.append(run)
            run = []; continue
        if run and n["t"] - run[-1]["t"] > gap + 1e-9: runs.append(run); run = []
        run.append(n)
    if run: runs.append(run)
    return [r for r in runs if len(r) >= 3 and len({n[key] for n in r}) >= 2 and any(n[key] in TOMS for n in r)]
