"""Parity test: the packaged solver must equal the library it was packaged from (R-590: frozen, no behaviour changes).

For each window in windows.json the CLI solves the MIDI and the result is compared with tests/reference.json, which was recorded from the original library
(nelvids library/performers/drums, `perform.py --key clip --tag v001`) on the same windows with the same package versions:
  - motion_sha256: sha256 of the canonical motion JSON (sorted keys, compact) with the two metadata fields `title` and `library` removed
                   (they name the producing package and version; everything else, including every pose byte, must be identical);
  - summary: played_pct, collision_cuts, freezes, hard_frames, crossed, passes, notes, missed, wrong, extra.

A solve takes minutes (1-3 GB): the three windows run two at a time. Run `pytest tests/ -s`.
Record a new reference from library outputs:  python tests/test_parity.py --record NAME motion.json judgement.json
"""
import hashlib, json, pathlib, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor


HERE = pathlib.Path(__file__).resolve().parent
DROP = ("title", "library")


def motion_sha(path):
    m = json.load(open(path))
    for k in DROP: m.pop(k, None)
    return hashlib.sha256(json.dumps(m, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def summary(judgement_path):
    J = json.load(open(judgement_path)); R = J["remedy"]; A = J["tally"]["all"]
    return dict(played_pct=R["played_pct"], collision_cuts=R["collision_cuts"], freezes=len(R["freezes"]), hard_frames=R["played_clip_hard_frames"], crossed=len(R["crossed"]),
                passes=R["passes"], notes=A["notes"], missed=A["missed"], wrong=A["wrong"], extra=A["extra"])


def solve(w, out):
    cmd = [sys.executable, "-B", "-m", "midi2motion", "solve", str(HERE / "data" / w["file"]), "--bars", w["bars"], "--meter", w["meter"], "--out", str(out / f"{w['name']}.motion.json")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    return out / f"{w['name']}.motion.json", out / f"{w['name']}.judgement.json"


def test_parity():
    W = json.load(open(HERE / "windows.json"))["windows"]; ref = json.load(open(HERE / "reference.json"))
    with tempfile.TemporaryDirectory(prefix="m2m_parity_") as td, ThreadPoolExecutor(2) as ex:
        out = pathlib.Path(td); res = list(ex.map(lambda w: solve(w, out), W))
        report = {}
        for w, (m, j) in zip(W, res):
            got = dict(motion_sha256=motion_sha(m), summary=summary(j)); report[w["name"]] = got
            print(w["name"], got["motion_sha256"][:16], got["summary"])
        bad = {k: (ref[k], report[k]) for k in report if report[k] != ref[k]}
        assert not bad, json.dumps(bad, indent=1)


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--record":
        name, m, j = sys.argv[2:]
        p = HERE / "reference.json"; ref = json.load(open(p)) if p.exists() else {}
        ref[name] = dict(motion_sha256=motion_sha(m), summary=summary(j)); json.dump(ref, open(p, "w"), indent=1); print(name, ref[name])
    else: sys.exit(__doc__)
