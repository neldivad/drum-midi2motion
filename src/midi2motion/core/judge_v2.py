# LIBRARY COPY of drum-benchmark/tools/judge_v2.py (nelvids lab, 2026-11-2x), packaged in midi2motion (vendored from the nelvids drums library): analysis-only functions and the lab's CLI dropped, lab paths -> rigenv.
#!/usr/bin/env python3
"""judge_v2.py: the R-447 judge (rig-foundations review3/judge.py, imported unchanged) with the two FOOT fixes the author approved (round 4, item A), as an adapter.

    import judge_v2; J = judge_v2.judge(contacts_or_judgement)          (a deep copy is judged; the input is untouched)

FIX 1, the hi-hat pedal's close. The measurer marks a pedal close `under_stick` when a stick stroke on the hat follows within 80 ms (the foot shutting the hat FOR a
closed stroke: an articulation), and the judge leaves every `under_stick` contact out of its pool. When that close is also the MIDI's own pedal note, the note found no
contact and was filed MISSED (37 false misses on v005). Now the pedal notes are matched to the foot's contacts FIRST: each hat-pedal note takes the nearest pedal close
within the match window (100 ms, one to one, smallest total |offset|), `under_stick` or not. Only those closes join the pool; a pedal close that matched no pedal note
stays an articulation (out of the pool, never an extra), as before.
FIX 2, notes before the clip. A note whose onset is before the clip's first frame (t < 0, e.g. a kick at -0.013 s: the window's MIDI starts a hair before its own
start) cannot be played by a motion that starts at 0. When no sounding contact of its row answers it within the match window, it is no longer judged (`judged` False,
`excluded`: "before the clip start, unanswered"), so it is not a miss; one the motion did play (a contact at t ~ 0) is judged as before.
NOTHING ELSE CHANGES: the windows, the matching order, the ornament groups, the per-clip velocity fit and SOFTER are the wrapped judge's own.
"""
import collections, copy, glob, json, pathlib, sys
sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent; LAB = HERE.parent; sys.path.insert(0, str(HERE))
import rigenv as bench                                                                # the wrapped rig lab on the path (library: rigenv)
import numpy as np
from scipy.optimize import linear_sum_assignment
import judge as JG
VERSION = "judge_v2 (review3/judge.py + pedal-first matching + notes before the clip excluded)"
FOOT_ROWS = ("kick", "kick2", "hatped")


def prepare(J):
    """the two fixes, applied to the contact file before the unchanged judge runs"""
    J = copy.deepcopy(J); W = JG.WIN["match_ms"] / 1000 + 1e-6; fx = collections.Counter()
    for c in J["contacts"]: c.pop("matched", None); c.pop("vel_est", None)
    for s in J["source"]:
        s.pop("verdict", None)
        if s.get("judged") and s["t"] < 0 and not any(c["row"] == s["row"] and c.get("sounding") and abs(c["t"] - s["t"]) <= W for c in J["contacts"]):
            s["judged"] = False; s["excluded"] = "before the clip start, unanswered"; fx["excluded before the clip"] += 1
    ped_s = [s for s in J["source"] if s.get("judged") and s["row"] == "hatped"]; ped_c = [c for c in J["contacts"] if c["row"] == "hatped" and c.get("sounding")]
    if ped_s and ped_c:
        M = np.full((len(ped_s), len(ped_c)), 1e3)
        for a, s in enumerate(ped_s):
            for b, c in enumerate(ped_c):
                if abs(c["t"] - s["t"]) <= W: M[a, b] = abs(c["t"] - s["t"])
        for a, b in zip(*linear_sum_assignment(M)):
            if M[a, b] < 1e3 and ped_c[b].get("under_stick"):
                ped_c[b]["under_stick"] = False; ped_c[b]["pedal_note_first"] = ped_s[a]["id"]; fx["pedal closes given back to their pedal note"] += 1
    return J, dict(fx)


def judge(J):
    Jp, fx = prepare(J); out = JG.judge(Jp); out["judge_version"] = VERSION; out["judge_v2_fixes"] = fx; return out


def foot_losses(J):
    """lost notes (missed, wrong, softer, simplified) on the feet's rows"""
    n = collections.Counter()
    for s in J["source"]:
        if not s.get("judged") or s["row"] not in FOOT_ROWS: continue
        v = s.get("verdict") or {}
        if v.get("cls") in ("missed", "wrong"): n[f"{s['row']} {v['cls']}"] += 1
        elif v.get("cls") == "hit" and (v.get("softer") or v.get("simplified")): n[f"{s['row']} {'softer' if v.get('softer') else 'simplified'}"] += 1
    return n








def add_splay(J, D=None, motion=None):
    """round 5, R-557: the stick-splay check (tools/splay.py) as an ERROR next to collisions and freezes, from the solve's 120 Hz dataset (D) or the page's motion file; and
    R-558's difficulty split (tools/difficulty.py: wrong drums in easy vs hard spans). Adds J["splay"], J["difficulty"] and J["tally"]["all"]["splay_frames"]; changes no verdict."""
    import splay as SPL, difficulty as DF
    if D is not None: SL, SR = SPL.from_dataset(D); kit = D["kit"]
    else: SL, SR = SPL.from_motion(motion); kit = motion["kit"]
    r = SPL.check(SL, SR, kit); J["splay"] = r; J["tally"]["all"]["splay_frames"] = r["frames"]; J["difficulty"] = dict(DF.split(J)); J["judge_version"] = J.get("judge_version", VERSION) + " + R-557 splay tally"
    return J


def add_habits(J, D=None, zones_v="v001"):
    """round 6: R-574's habit errors (tools/habits.py: role flips, same-piece swaps, reserved-limb steals, split bounces) and, given the 120 Hz dataset, R-575's zone errors
    and straight arms (tools/zones.py, zones fitted on OUR cleanest frames) into the judgement and its tally. Measures only; no verdict changes."""
    import habits as HB
    h = HB.check(J); J["habits"] = h; T = J["tally"]["all"]
    for k in ("role_flips", "swaps", "steals", "bounce_splits"): T[k] = h["counts"][k]
    zf = pathlib.Path(__file__).resolve().parents[1] / f"data/zones_{zones_v}.json"      # library: the lab's out/zones_v001.json, copied to data/
    if D is not None and zf.exists():
        import zones as ZN
        F = ZN.frames(D, json.load(open(zf))["zones"]); T["zone_frames"] = int(sum(F[x]["zone"].sum() for x in "LR")); T["straight_arm_frames"] = int(sum(F[x]["straight"].sum() for x in "LR"))
    return J
