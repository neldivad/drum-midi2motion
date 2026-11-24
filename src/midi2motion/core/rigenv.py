# midi2motion: from the nelvids drums library (core/rigenv.py), packaged: the rig is vendored in ../rig, so no lab folder and no lab venv are needed.
"""rigenv.py: where the rig is, and the MIDI -> kit note map. Replaces the lab's bench.py (the lab's `import bench` became `import rigenv as bench`).

The rig, planner and judge (R-447) are vendored in `midi2motion/rig/` (flat modules on sys.path, as the lab imported them): `rig/` (arm and body rig, stroke planner, checks),
`rig/drums2/` (kit data, chart, the repair loop), `rig/review3/` (contact measure, the judge), `rig/sibling/` (the android's rest pose, kit class, drum_chart, drum_perf), `rig/data/` (rig.yaml, drumkit.yaml).
`mido` is a normal dependency. `SCR` is assigned by perform() before a solve (scratch for the 120 Hz dataset); the adapter modules read it as `bench.SCR` at call time.
"""
import os, pathlib, sys
sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent; PKG = HERE.parent; RIG = PKG / "rig"
for p in (RIG / "review3", RIG / "sibling", RIG / "drums2", RIG):
    if str(p) not in sys.path: sys.path.insert(0, str(p))
if str(HERE) not in sys.path: sys.path.insert(0, str(HERE))
import mido                                                                           # noqa: F401
import numpy as np
SCR = pathlib.Path(os.environ["NELPERFORM_SCRATCH"]) if os.environ.get("NELPERFORM_SCRATCH") else None

# TD-11 (Groove MIDI Dataset README / Gillick et al. 2019, table 1) -> this kit's note map (drumkit.yaml note_map). Standard GM drum pitches pass through unchanged.
TD11 = {36: (36, "kick"), 38: (38, "snare head"), 40: (40, "snare rim"), 37: (37, "snare x-stick"), 48: (48, "tom 1"), 50: (48, "tom 1 rim"), 45: (47, "tom 2"), 47: (47, "tom 2 rim"),
        43: (43, "tom 3 (floor)"), 58: (43, "tom 3 rim"), 46: (46, "hh open bow"), 26: (46, "hh open edge"), 42: (42, "hh closed bow"), 22: (42, "hh closed edge"), 44: (44, "hh pedal"),
        49: (49, "crash 1 bow"), 55: (49, "crash 1 edge"), 57: (49, "crash 2 bow"), 52: (49, "crash 2 edge"), 51: (51, "ride bow"), 59: (51, "ride edge"), 53: (53, "ride bell")}
FOLD = {50: "tom rim -> head", 47: "tom rim -> head", 58: "tom rim -> head", 26: "hh edge -> bow", 22: "hh edge -> bow", 55: "crash edge -> crash", 57: "crash 2 -> crash", 52: "crash 2 -> crash", 59: "ride edge -> bow"}


def bar_info(src, bpb=4):
    """(ticks per beat, ticks per bar, the last note-on tick, bars in the file) of a MIDI file: for bars=None (the whole file)"""
    m = mido.MidiFile(str(src)); tpb = m.ticks_per_beat; last = 0
    for tr in m.tracks:
        t = 0
        for msg in tr:
            t += msg.time
            if msg.type == "note_on" and msg.velocity > 0: last = max(last, t)
    bar = int(round(bpb * tpb)); return tpb, bar, last, max(1, last // bar + 1)


def remap(src, b0, b1, out, ctx_before=2, ctx_after=1, dup_ms=30, leadin=False, bpb=4):
    """the window's MIDI with TD-11 pitches mapped onto the kit; notes outside [b0 - ctx_before, b1 + ctx_after] bars dropped (ticks kept, so bar numbers hold).
    (bench.remap, unchanged.) leadin: the lab's workaround for the solver crashing on a bare 1-2 bar clip, off (a synthetic first bar that is never judged)."""
    m = mido.MidiFile(str(src)); tpb = m.ticks_per_beat; bar = int(round(bpb * tpb)); tempo = None; N = []
    for tr in m.tracks:
        t = 0
        for msg in tr:
            t += msg.time
            if msg.type == "set_tempo" and tempo is None: tempo = msg.tempo
            if msg.type == "note_on" and msg.velocity > 0: N.append([t, msg.note, msg.velocity])
    tempo = tempo or 500000; spt = tempo / 1e6 / tpb; syn = []
    if leadin:
        N = [[t + bar, p, v] for t, p, v in N]; b0 += 1; b1 += 1
        for k in range(8):
            pos = k * tpb // 2
            if (bar - pos) * spt < 1.0: continue
            syn += [[pos, 42, 80]] + ([[pos, 36, 100]] if k in (0, 4) else []) + ([[pos, 38, 100]] if k in (2, 6) else [])
    lo, hi = (b0 - 1 - ctx_before) * bar, (b1 + ctx_after) * bar
    inwin = lambda t: (b0 - 1) * bar - 0.5 / spt <= t < b1 * bar + 0.7 / spt           # the judged span (chart2's lead 0.5 s, tail 0.7 s)
    cnt = dict(notes_in_window=0, folded={}, dropped_unknown={}, folded_duplicates=0, by_source_pitch={})
    keep = [dict(t=t, src="synthetic", note=p, vel=v, w=False) for t, p, v in syn]
    for t, p, v in N:
        if not (lo <= t < hi): continue
        w = inwin(t)
        if p not in TD11:
            if w: cnt["dropped_unknown"][str(p)] = cnt["dropped_unknown"].get(str(p), 0) + 1
            continue
        q = TD11[p][0]
        if w:
            cnt["notes_in_window"] += 1; cnt["by_source_pitch"][str(p)] = cnt["by_source_pitch"].get(str(p), 0) + 1
            if p in FOLD: cnt["folded"][FOLD[p]] = cnt["folded"].get(FOLD[p], 0) + 1
        keep.append(dict(t=t, src=p, note=q, vel=v, w=w))
    keep.sort(key=lambda n: (n["t"], n["note"])); dup = dup_ms / 1000 / spt; drop = set()
    for i, a in enumerate(keep):                                                          # two source pitches folded onto one piece and zone within 30 ms: one stroke (crash 1 + crash 2 together)
        for j in range(i + 1, len(keep)):
            b = keep[j]
            if b["t"] - a["t"] > dup: break
            if b["note"] == a["note"] and b["src"] != a["src"] and i not in drop and j not in drop:
                k = j if b["vel"] <= a["vel"] else i; drop.add(k); cnt["folded_duplicates"] += keep[k]["w"]
    keep = [n for i, n in enumerate(keep) if i not in drop]
    ev = []
    for n in keep: ev += [(n["t"], 1, n["note"], n["vel"]), (n["t"] + max(1, tpb // 16), 0, n["note"], 0)]
    ev.sort(key=lambda e: (e[0], e[1])); tr = mido.MidiTrack(); tr.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0)); last = 0
    for t, on, note, v in ev: tr.append(mido.Message("note_on" if on else "note_off", channel=9, note=note, velocity=v if on else 0, time=t - last)); last = t
    mf = mido.MidiFile(ticks_per_beat=tpb); mf.tracks.append(tr); out.parent.mkdir(parents=True, exist_ok=True); mf.save(str(out))
    return dict(cnt, b0=b0, b1=b1, leadin=leadin, synthetic_notes=len(syn), tpb=tpb, tempo_bpm=round(60e6 / tempo, 2), sec_per_bar=round(bar * spt, 4))
