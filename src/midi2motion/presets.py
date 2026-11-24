"""presets.py: `midi2motion presets build`. Solves the preset list (presets/presets.json) with the packaged CLI, one process per preset, and writes
web/public/presets/<id>/<id>.motion.json + <id>.judgement.json + <id>.mid (the source cut to its bars, bar `a` at tick 0), and web/public/presets/manifest.json.
One folder per preset keeps every folder small. Presets already built are skipped (nothing is overwritten); an older flat <id>.json / <id>.judgement.json is moved into its folder."""
import json, os, pathlib, shutil, subprocess, sys, threading, time

from .midiutil import cut_window, tempo_bpm


KIT = "virtuosity-cc0"          # the default kit id of web/public/kits/ (the page falls back to this kit per preset)


def _src(d, groove_dir, author_dir):
    base = groove_dir if d["source"] == "groove" else author_dir
    if not base: sys.exit(f"preset {d['id']}: pass --{'groove' if d['source'] == 'groove' else 'author'}-dir")
    p = pathlib.Path(base) / d["src"]
    if not p.exists(): sys.exit(f"preset {d['id']}: {p} not found")
    return p


def _solve_one(d, src, out, mem):
    cmd = [sys.executable, "-B", "-m", "midi2motion", "solve", str(src), "--bars", f"{d['bars'][0]}-{d['bars'][1]}", "--meter", str(d["bpb"]), "--out", str(out / d["id"] / f"{d['id']}.motion.json")]
    if mem and shutil.which("systemd-run"): cmd = ["systemd-run", "--user", "--scope", "-q", "-p", f"MemoryMax={mem}", "nice", "-n", "15"] + cmd
    t0 = time.time(); r = subprocess.run(cmd, capture_output=True, text=True)
    print(f"{d['id']}: exit {r.returncode} in {time.time() - t0:.0f} s" + ("" if r.returncode == 0 else "\n" + r.stderr[-800:]), flush=True)
    return r.returncode == 0


def build(out, defs_path, groove_dir=None, author_dir=None, jobs=1, only=None, mem="4G"):
    out = pathlib.Path(out); out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*.json"):                                             # migrate an older flat layout
        i = f.name.removesuffix(".judgement.json") if f.name.endswith(".judgement.json") else f.name.removesuffix(".json")
        if f.name != "manifest.json":
            (out / i).mkdir(exist_ok=True); shutil.move(str(f), out / i / (f"{i}.judgement.json" if f.name.endswith(".judgement.json") else f"{i}.motion.json"))
    defs = json.load(open(defs_path))["definitions"]
    if only: defs = [d for d in defs if d["id"] in only]
    todo = [d for d in defs if not (out / d["id"] / f"{d['id']}.motion.json").exists()]
    sem = threading.Semaphore(max(1, min(2, jobs))); res = {}
    def work(d):
        with sem:
            (out / d["id"]).mkdir(exist_ok=True); res[d["id"]] = _solve_one(d, _src(d, groove_dir, author_dir), out, mem)
    ts = [threading.Thread(target=work, args=(d,)) for d in todo]
    for t in ts: t.start()
    for t in ts: t.join()
    entries = []
    for d in defs:
        if not (out / d["id"] / f"{d['id']}.motion.json").exists(): print(f"{d['id']}: not built, left out of the manifest"); continue
        src = _src(d, groove_dir, author_dir); J = json.load(open(out / d["id"] / f"{d['id']}.judgement.json")); R = J["remedy"]
        if not (out / d["id"] / f"{d['id']}.mid").exists(): cut_window(src, out / d["id"] / f"{d['id']}.mid", d["bars"], d["bpb"], ts=d["meter"])
        bpm = d.get("bpm") or tempo_bpm(src)
        entries.append(dict(id=d["id"], kit=KIT, title=d["title"], kind=d["kind"], style=d["style"], bpm=bpm, meter=d["meter"], bars=d["bars"], source=d["source"], credit=d["credit"],
                            midi=f"presets/{d['id']}/{d['id']}.mid", motion=f"presets/{d['id']}/{d['id']}.motion.json", judgement=f"presets/{d['id']}/{d['id']}.judgement.json", played_pct=R["played_pct"], notes=d["notes"],
                            collision_cuts=R["collision_cuts"], freezes=len(R["freezes"]), hard_frames=R["played_clip_hard_frames"], bpb=d["bpb"]))
    json.dump(dict(version=1, kit=KIT, presets=entries), open(out / "manifest.json", "w"), indent=1)
    print(f"manifest: {len(entries)} presets"); return entries
