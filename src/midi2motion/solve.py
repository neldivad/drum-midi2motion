"""solve.py: MIDI -> a drummer's performance. An android rig plays a standard kit from a drum MIDI file, solved at the ADOPTED settings (frozen, ruling R-590).

    from midi2motion.solve import perform
    r = perform("groove.mid", layout="standard", bars=(2, 5), out="out/")        # bars = (first, last) real bar, 1-based, inclusive; None = the whole file
    r["motion"], r["judgement"], r["summary"]                                     # two JSON paths (motion for the web player, the judge's file) + the numbers

Packaged from the nelvids drums library (`perform.py`). The solver is the wrapped lab's own chain, vendored in `midi2motion/rig/` and unchanged: kitdata -> chart2.build (the deal)
-> run2.loop (shift table, solve, the 120 Hz checks, the repair ladder) -> fates -> measure -> judge, with the benchmark's adapter on top (`core/remedies.py`: the remedy table
W1 P1 T1 P2 W2 A1p, the churn guard G, D558, the splay cost SPL; `core/judge_v2.py`; the error counts). Output:
    <out>/<key>_<tag>.motion.json       the player's file (30 fps compact pose + sticks + kit + the notes)
    <out>/<key>_<tag>.judgement.json    the judge's file: every source note's verdict, the tally, `remedy` (played %, collision cuts, freezes, hard frames, passes)
Versions only go up: an existing <key>_<tag> is never overwritten. The 120 Hz dataset is derived (tens of MB) and lives in a temporary directory dropped at the end.
A solve is one process and 1-3 GB; run it under a memory cap. The flags beyond the adopted rows (rows, grip_deg, elbow_k, deal) are research switches, off by default and not exposed by the CLI.
"""
import argparse, json, os, pathlib, re, sys, tempfile, time
sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent; CORE = HERE / "core"
from . import __version__ as VERSION
ADOPTED_ROWS = "W1,P1,T1,P2,W2,A1p,G,D558,SPL"      # = drum-benchmark/tools/remedies.py's default rows (round 5, 2026-11-23): the v009 table + D558 (R-558) + SPL (R-557, weight 0.5)
V009_ROWS = "W1,P1,T1,P2,W2,A1p,G"                  # the lab's tag v009 as run on 2026-11-22 (before D558 and SPL): for the reproduction test
LAYOUTS = {"standard": "hh_out30_down65", "standard-raw": "standard"}
_RAN = {}


def _parse_bars(s):
    if s is None: return None
    if isinstance(s, str): a, b = re.fullmatch(r"(\d+)-(\d+)", s).groups(); return int(a), int(b)
    return int(s[0]), int(s[1])


def perform(midi, layout="standard", bars=None, out=None, *, tag="v001", key=None, meter=4.0, rows=ADOPTED_ROWS, splay_weight=0.5, max_passes=None, grip_deg=None, elbow_k=None,
            deal="beam", deal_terms=None, scratch=None, verbose=True):
    midi = pathlib.Path(midi).resolve(); assert midi.exists(), midi
    sys.path.insert(0, str(CORE)); import rigenv
    rows = rows if isinstance(rows, (set, list, tuple)) else [x for x in str(rows).split(",") if x]; rows = sorted(set(rows))
    flags = dict(rows=rows, splay_weight=splay_weight, max_passes=max_passes, grip_deg=grip_deg, elbow_k=elbow_k, deal=deal, deal_terms=deal_terms or {})
    if _RAN and _RAN.get("flags") != flags: raise RuntimeError("this process already solved with other flags: the adapter patches the rig in memory; start a new process")
    out = pathlib.Path(out or "drums_out"); out.mkdir(parents=True, exist_ok=True)
    key = key or re.sub(r"[^A-Za-z0-9_.-]+", "_", midi.stem); bars = _parse_bars(bars)
    mo, jo = out / f"{key}_{tag}.motion.json", out / f"{key}_{tag}.judgement.json"
    for p in (mo, jo):
        if p.exists(): raise FileExistsError(f"{p} exists: versions only go up (pass a new tag)")
    tpb, bar_t, last, nbars = rigenv.bar_info(midi, meter)
    if bars is None: bars = (1, nbars)
    preset = LAYOUTS.get(layout, layout); t0 = time.time()
    tmp = None
    if scratch: scr = pathlib.Path(scratch); scr.mkdir(parents=True, exist_ok=True)
    else: tmp = tempfile.TemporaryDirectory(prefix="nelperform_"); scr = pathlib.Path(tmp.name)      # derived (the 120 Hz dataset is tens of MB): dropped at the end
    rigenv.SCR = scr
    import remedies as RM, export_motion as EM
    RM.ROWS.clear(); RM.ROWS.update(rows); RM.SPLAY_W = float(splay_weight); RM.CAP = int(max_passes) if max_passes else None
    RM.GRIP_DEG = str(grip_deg) if grip_deg else None; RM.ELBOW_K = str(elbow_k) if elbow_k else None; RM.OUT = scr / "judgements"; RM.PRESET = preset
    _RAN["flags"] = flags
    RM.one(key, tag, midi=midi, bars=bars, bpb=float(meter), preset=preset, deal=deal, deal_terms=deal_terms)
    J = json.load(open(RM.OUT / f"judgement_{key}_{tag}.json")); D = json.load(open(RM.INS["path"])); R = J["remedy"]
    title = f"{midi.name} · bars {bars[0]}-{bars[1]} · {layout} · drums performer {VERSION} {tag}"
    M = EM.compact(D, f"{key}_{tag}", title); M["remedy"] = {k: R[k] for k in ("stats", "boosts_kept", "passes", "played_pct", "collision_cuts")}; M["notes"] = EM.notes_of(J)
    M["library"] = dict(name="midi2motion", version=VERSION, schema="1.1", rows=rows)
    A = J["tally"]["all"]
    J["library"] = dict(name="midi2motion", version=VERSION, midi=midi.name, layout=layout, preset=preset, bars=list(bars), meter=float(meter), tag=tag, rows=rows, splay_weight=RM.SPLAY_W,
                        max_passes=R["cap"], grip_deg=grip_deg, elbow_k=elbow_k, deal=deal, seconds=round(time.time() - t0, 1), adopted=(rows == sorted(ADOPTED_ROWS.split(",")) and deal == "beam" and not grip_deg and not elbow_k))
    json.dump(M, open(mo, "w"), separators=(",", ":")); json.dump(J, open(jo, "w"), indent=0, default=lambda x: x.tolist() if hasattr(x, "tolist") else str(x))
    S = dict(played_pct=R["played_pct"], collision_cuts=R["collision_cuts"], freezes=len(R["freezes"]), hard_frames=R["played_clip_hard_frames"], crossed=len(R["crossed"]), passes=R["passes"],
             notes=A["notes"], missed=A["missed"], wrong=A["wrong"], extra=A["extra"], splay_frames=A.get("splay_frames"), seconds=J["library"]["seconds"])
    if tmp: tmp.cleanup()
    if verbose: print(f"{key} {tag}: played {S['played_pct']} % · collision cuts {S['collision_cuts']} · freezes {S['freezes']} · hard frames {S['hard_frames']} · {S['passes']} passes · {S['seconds']} s -> {mo.name}, {jo.name}", flush=True)
    return dict(motion=str(mo), judgement=str(jo), summary=S)
