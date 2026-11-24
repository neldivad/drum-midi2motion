"""cli.py: the `midi2motion` command.

    midi2motion solve IN.mid [--bars A-B] [--meter 4|6/8|5/4] --out NAME.motion.json   (also writes NAME.judgement.json beside it)
    midi2motion serve [--kit DIR] [--port 8814]                                     (a local server of web/, 127.0.0.1 only)
    midi2motion presets build [--groove-dir D] [--author-dir D] [--jobs 2] [--only id ...]
"""
import argparse, json, os, pathlib, shutil, subprocess, sys, tempfile

from . import __version__


def _solve(a):
    from .midiutil import parse_meter
    from .solve import perform
    out = pathlib.Path(a.out)
    if out.suffix != ".json": sys.exit(f"--out must be a .json path (got {out})")
    stem = out.name[:-len(".motion.json")] if out.name.endswith(".motion.json") else out.name[:-len(".json")]
    jout = out.with_name(stem + ".judgement.json")           # NAME.motion.json -> NAME.judgement.json ; NAME.json -> NAME.judgement.json
    for p in (out, jout):
        if p.exists(): sys.exit(f"{p} exists: nothing is overwritten (choose a new name)")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="midi2motion_out_") as td:
        r = perform(a.midi, layout=a.layout, bars=a.bars, out=td, meter=parse_meter(a.meter), key="clip", tag="v001")
        shutil.move(r["motion"], out); shutil.move(r["judgement"], jout)
    print(json.dumps(r["summary"])); print(f"wrote {out} and {jout}")


def web_dir(explicit=None):
    cands = [explicit, os.environ.get("MIDI2MOTION_WEB"), pathlib.Path(__file__).resolve().parents[2] / "web"]
    for c in cands:
        if c and (pathlib.Path(c) / "index.html").exists(): return pathlib.Path(c).resolve()
    sys.exit("web/ not found: run from a clone of the repo (pip install -e .), or pass --web DIR / set MIDI2MOTION_WEB")


def _serve(a):
    from .serve import run
    run(web_dir(a.web), kit=a.kit, port=a.port)


def _presets(a):
    from .presets import build
    build(web_dir(a.web) / "presets", pathlib.Path(a.defs) if a.defs else pathlib.Path(__file__).resolve().parents[2] / "presets" / "presets.json",
          groove_dir=a.groove_dir, author_dir=a.author_dir, jobs=a.jobs, only=a.only, mem=a.mem)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="midi2motion", description="drum MIDI -> an android drummer's motion")
    ap.add_argument("--version", action="version", version=f"midi2motion {__version__}")
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("solve", help="solve one MIDI file (one process, 1-3 GB, minutes: run it under a memory cap)")
    s.add_argument("midi"); s.add_argument("--bars", help="FIRST-LAST, real bars, 1-based, inclusive (default: the whole file)")
    s.add_argument("--meter", default="4", help="quarter notes per bar, or a time signature: 4, 3, 5, 2.5, 4/4, 3/4, 6/8, 5/4, 5/8 (default 4)")
    s.add_argument("--layout", default="standard", help="the kit layout (default: the adopted kit)")
    s.add_argument("--out", required=True, help="motion JSON path (NAME.motion.json or NAME.json); the judgement JSON is written next to it as NAME.judgement.json")
    s.set_defaults(fn=_solve)
    v = sp.add_parser("serve", help="serve web/ on 127.0.0.1 (local use only)")
    v.add_argument("--kit", help="a folder with kit.json + samples: mounted as the page's kit 'user' (see docs/kits.md)")
    v.add_argument("--port", type=int, default=8814); v.add_argument("--web", help="the web folder (default: the repo's web/)")
    v.set_defaults(fn=_serve)
    pr = sp.add_parser("presets", help="the bundled presets"); ps = pr.add_subparsers(dest="sub", required=True)
    b = ps.add_parser("build", help="solve the preset list into web/presets/ (skips presets already built)")
    b.add_argument("--defs", help="the preset list (default presets/presets.json)"); b.add_argument("--web")
    b.add_argument("--groove-dir", help="the Groove MIDI Dataset's groove/ folder (source of the groove presets)")
    b.add_argument("--author-dir", help="a folder holding the author's MIDI files named in the list")
    b.add_argument("--jobs", type=int, default=1, help="solves at once (1-2; each is 1-3 GB)"); b.add_argument("--only", nargs="*", help="build only these ids")
    b.add_argument("--mem", default="4G", help="memory cap per solve via systemd-run, when available ('' = none)")
    b.set_defaults(fn=_presets)
    a = ap.parse_args(argv); a.fn(a)


if __name__ == "__main__":
    main()
