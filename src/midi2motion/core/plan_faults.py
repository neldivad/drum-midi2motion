# LIBRARY COPY of drum-benchmark/tools/plan_faults.py (freezes R-529, crossed rides)
#!/usr/bin/env python3
"""plan_faults.py: two faults read from a judgement's plan (R-417's fate per MIDI note), measured, nothing fixed.

  FREEZE (R-529): a limb with >= 3 consecutive MISSED notes (the judge's verdict; consecutive among the notes the plan dealt to that limb, in time order) spanning >= 0.5 s.
                  Misses the judge files as "not cut in the log" are left out (on the hat pedal they are the judge's artefact: the shut filed as a stick stroke's articulation; the
                  benchmark's reconcile step counts them as hits), so they break a run. Reported with its limb, start, span, notes and the limit behind most of them.
                  (Variants measured on v005: the plan's cut notes alone give 8 freezes too but a different left-hand run in the jazz window; counting the pedal artefacts gives 14.)
  CROSSED HAND (R-528): a ride note (bow, edge or bell) the plan gave to the WEAK hand, the hand that is not the kit's lead (the left on a right-handed kit): the deal crossed it
                  over to the ride. The lead hand comes from the motion file's kit (`lead_hand`).
    import plan_faults as PF;  PF.freezes(J);  PF.crossed(J, lead="R")
"""
import collections
HANDS = ("L", "R")


def freezes(J, min_notes=3, min_span=0.5):
    src = sorted([s for s in J["source"] if s["judged"] and s["plan"].get("limb")], key=lambda s: s["t"]); out = []
    for limb in sorted({s["plan"]["limb"] for s in src}):
        L = [s for s in src if s["plan"]["limb"] == limb]; run = []
        for s in L + [None]:
            if s is not None and s["verdict"]["cls"] == "missed" and s["verdict"].get("limit") != "not cut in the log": run.append(s); continue
            if len(run) >= min_notes and run[-1]["t"] - run[0]["t"] >= min_span:
                lim = collections.Counter(x["verdict"].get("limit") or x["plan"].get("limit") for x in run).most_common(1)[0][0]
                out.append(dict(limb=limb, t0=round(run[0]["t"], 4), t1=round(run[-1]["t"], 4), span_s=round(run[-1]["t"] - run[0]["t"], 2), notes=len(run), mostly=lim, ids=[x["id"] for x in run], rows=sorted({x["row"] for x in run})))
            run = []
    return sorted(out, key=lambda f: f["t0"])


def crossed(J, lead="R"):
    weak = "L" if lead == "R" else "R"
    return [dict(id=s["id"], t=round(s["t"], 4), zone=s.get("zone"), fate=s["plan"].get("fate")) for s in J["source"] if s["judged"] and s["row"] == "ride" and s["plan"].get("limb") == weak]


def ride_notes(J):
    return sum(1 for s in J["source"] if s["judged"] and s["row"] == "ride")
