#!/usr/bin/env python3
# midi2motion: vendored from nelvids/lab/wrapped/3d/2026-11-16-rig-foundations/tools/review3/judge.py (a wrapped lab, read-only source). Solver behaviour unchanged; only data paths and the lab command line were changed.
"""review3/judge.py: the source MIDI notes against the MEASURED contacts (R-446) -> one judgement file per clip, for any instrument.

        -> out/review3/judgement_<clip>_<v>.json   (the contact file + a verdict per source note, a cause per extra, the events the layout counts, the tallies)
           out/review3/judgement_<clip>_<v>.md     (the short table)

Reads only the common contact file (measure_drums.py, measure_piano.py: schema review3.contacts/1). Nothing here knows what a drum or a key is.
WINDOWS (30 fps frames, as a rhythm game): PERFECT |offset| <= 1 frame (33.3 ms) · GOOD <= 2 frames (66.7 ms) · EARLY / LATE <= 3 frames (100 ms) · beyond that the note
is MISSED and the contact is an EXTRA. offset = measured contact time - the MIDI onset (negative = early).
MATCHING is one to one:
  1. a `drag` contact (a tip that stays down and travels: a sweep) takes every source note of its row from its start to its end; the nearest to its start is timed,
     the rest are hits with no offset (`in_drag`);
  2. every other sounding contact and source note of the SAME row within 100 ms: the assignment with the smallest total |offset| (Hungarian);
  3. what is left, source note x sounding contact on a NEIGHBOURING row (`near` in the contact file) within 100 ms: WRONG (piece or key), the contact is used up;
  4. source notes still unmatched: MISSED, with the limit R-417's log gives that MIDI id (if the log says it was played, that is said: the plan and the motion disagree);
  5. contacts still unmatched: EXTRA (sounding) or BRUSH (touched, silent by the measuring file's threshold), each with what the limb was doing.
SOFTER is measured: per kind of contact the measured approach speed is regressed on the MIDI velocity over the clip's matched hits (Theil-Sen) and the line is inverted to
read a velocity off each contact's speed; where that relation exists (speed rises with velocity, median error <= 20 velocity steps) a hit whose speed reads <= 70 % of its
MIDI velocity and >= 15 below it is SOFTER. Where the motion does not carry velocity, nothing is called softer and it says so.
"""
import json, pathlib, sys
sys.dont_write_bytecode = True
import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.stats import theilslopes
LAB = pathlib.Path(__file__).resolve().parents[2]; FR = 1000.0 / 30
WIN = dict(perfect_ms=round(FR, 1), good_ms=round(2 * FR, 1), match_ms=round(3 * FR, 1))


def judge(J):
    src = J["source"]; C = J["contacts"]; W = WIN["match_ms"] / 1000 + 1e-6; rows = {r["id"]: r for r in J["rows"]}; lab = lambda r: rows.get(r, {}).get("label", r)
    for i, c in enumerate(C): c["i"] = i; c["matched"] = None
    for s in src: s["verdict"] = None
    pool_s = [s for s in src if s["judged"]]; pool_c = [c for c in C if c["sounding"] and not c.get("under_stick")]
    def hit(s, c, off, **kw): s["verdict"] = dict(cls="hit", contact=c["i"], offset_ms=None if off is None else round(off * 1000, 1), limb=c["limb"], sub=c.get("sub"), row_hit=c["row"], t_hit=c["t"], **kw); c["matched"] = c.get("matched") or s["id"]
    for c in [c for c in pool_c if c["kind"] == "drag"]:                                  # 1. drags
        ss = sorted([s for s in pool_s if s["verdict"] is None and s["row"] == c["row"] and c["t"] - W <= s["t"] <= c["t_off"] + 0.03], key=lambda s: abs(s["t"] - c["t"]))
        for k, s in enumerate(ss): hit(s, c, c["t"] - s["t"] if k == 0 else None, in_drag=k > 0)
    for wrong in (False, True):                                                           # 2. same row, 3. a neighbouring row
        ss = [s for s in pool_s if s["verdict"] is None]; cc = [c for c in pool_c if c["matched"] is None]
        if not ss or not cc: continue
        M = np.full((len(ss), len(cc)), 1e3)
        for a, s in enumerate(ss):
            for b, c in enumerate(cc):
                ok = (c["row"] in J["near"].get(s["row"], [])) if wrong else (c["row"] == s["row"])
                if ok and abs(c["t"] - s["t"]) <= W: M[a, b] = abs(c["t"] - s["t"])
        for a, b in zip(*linear_sum_assignment(M)):
            if M[a, b] < 1e3:
                hit(ss[a], cc[b], cc[b]["t"] - ss[a]["t"])
                if wrong: ss[a]["verdict"]["cls"] = "wrong"
    # ARTICULATIONS are one gesture (R-401: a ride sweep, a roll is never a run of separate hits; 2026-11-17 his "false positive for ride sweep, it logged
    # everythign as a miss"). A run of >= GROUP_MIN notes on one row, each <= GROUP_GAP s after the last, is ONE unit when the motion dragged through it or the
    # R-417 log played it as a 'simpler gesture'. Its head (the timed contact, else the first note) carries the verdict; the rest are `in_gesture` and are
    # not counted again. A unit struck once without its drag is a hit flagged `simplified`; a unit never struck is one miss.
    GROUP_GAP, GROUP_MIN = 0.085, 4
    for row in sorted({s["row"] for s in pool_s}):
        ss = sorted([s for s in pool_s if s["row"] == row], key=lambda s: s["t"]); runs_ = []; run = []
        for s in ss:
            if run and s["t"] - run[-1]["t"] > GROUP_GAP: runs_.append(run); run = []
            run.append(s)
        runs_.append(run)
        for g in [r for r in runs_ if len(r) >= GROUP_MIN]:
            dragged = any(s["verdict"] and s["verdict"].get("in_drag") for s in g); simpler = sum("simpler gesture" in (s["plan"].get("how") or "") for s in g) * 2 >= len(g)
            if not (dragged or simpler): continue
            struck = [s for s in g if s["verdict"] and s["verdict"]["cls"] in ("hit", "wrong") and not s["verdict"].get("in_drag")]
            head = min(struck, key=lambda s: s["t"]) if struck else g[0]; hv = head["verdict"]
            if hv is not None: hv.update(gesture_notes=len(g), simplified=not dragged)
            for s in g:
                if s is head: continue
                s["verdict"] = dict(cls="in_gesture", head=head["id"], limb=(hv or {}).get("limb") or s["plan"].get("limb"), sub=(hv or {}).get("sub"), simplified=not dragged,
                                    head_missed=hv is None, t_hit=(hv or {}).get("t_hit", head["t"] + W), row_hit=(hv or {}).get("row_hit", row))
    # velocity from approach speed, per kind of contact
    vel_models = {}
    for unit in sorted({c["unit"] for c in pool_c}):
        pr = [(C[s["verdict"]["contact"]]["speed"], s["vel"]) for s in pool_s if s["verdict"] and s["verdict"]["cls"] == "hit" and not s["verdict"].get("in_drag") and C[s["verdict"]["contact"]]["unit"] == unit and C[s["verdict"]["contact"]]["kind"] != "drag"]
        if len(pr) < 6 or np.std([p[0] for p in pr]) < 1e-9 or np.std([p[1] for p in pr]) < 1e-9: vel_models[unit] = dict(n=len(pr), usable=False, why="too few hits or no spread"); continue
        x, y = np.array(pr).T; r = float(np.corrcoef(x, y)[0, 1]); b, a, _, _ = theilslopes(x, y)                # speed = a + b * velocity (the causal way round), inverted to read a velocity off a speed
        if b <= 1e-9: vel_models[unit] = dict(n=len(pr), r=round(r, 2), usable=False, why="the measured approach speed does not rise with the MIDI velocity: softer is not judged for this kind of contact"); continue
        spread = float(np.median(np.abs((x - a) / b - y))); ok = spread <= 20
        vel_models[unit] = dict(n=len(pr), r=round(r, 2), speed_per_velocity=round(float(b), 5), speed_at_zero=round(float(a), 4), median_abs_error_velocity=round(spread, 1), usable=bool(ok), why=None if ok else "the measured approach speed follows the MIDI velocity too loosely (median error over 20 velocity steps): softer is not judged for this kind of contact")
    for c in C:
        m = vel_models.get(c["unit"])
        if m and m.get("usable") and c["sounding"] and c["kind"] != "drag": c["vel_est"] = int(np.clip(round((c["speed"] - m["speed_at_zero"]) / m["speed_per_velocity"]), 1, 127))
    for s in pool_s:
        v = s["verdict"]
        if v is not None and v["cls"] == "in_gesture": continue
        if v is None:
            p = s["plan"]; cut = p.get("fate") == "cut"; s["verdict"] = v = dict(cls="missed", limb=p.get("limb"), sub=p.get("sub"), limit=p.get("limit") if cut else "not cut in the log", reason=(p.get("limit") or "cut, no limit logged") if cut else f"the plan counts it {p.get('fate')}; no contact within {WIN['match_ms']:.0f} ms on this or a neighbouring row",
                                                                                 plan_disagrees=not cut); continue
        c = C[v["contact"]]; o = v["offset_ms"]
        v["timing"] = "in drag" if o is None else "perfect" if abs(o) <= WIN["perfect_ms"] + 1e-6 else "good" if abs(o) <= WIN["good_ms"] + 1e-6 else "early" if o < 0 else "late"
        if "vel_est" in c: v["vel_est"] = c["vel_est"]; v["softer"] = bool(c["vel_est"] <= 0.7 * s["vel"] and s["vel"] - c["vel_est"] >= 15)
        if s.get("dur", 0) >= 0.25 and c.get("dwell_s") is not None: v["held_frac"] = round(min(1.5, c["dwell_s"] / s["dur"]), 2); v["short"] = bool(v["held_frac"] < 0.5)
        if v["cls"] == "hit" and not v.get("in_drag") and s.get("zone") and J.get("zone_same") and c.get("zone") and s["zone"] in J["zone_same"]: v["zone_hit"] = c["zone"]; v["zone_off"] = c["zone"] not in J["zone_same"][s["zone"]]
        if s["plan"].get("fate") == "cut": v["plan_disagrees"] = True; v["plan_note"] = f"the R-417 log cut this note ({s['plan'].get('limit')}); the motion still sounds its row here (another note's stroke covers it)"
        elif s["plan"].get("limb") and v["cls"] == "hit" and s["plan"]["limb"] != v["limb"]: v["limb_differs"] = True
    for s in src:
        if not s["judged"]: s["verdict"] = dict(cls="layer", reason="sounds in the track, has no piece on this instrument: not judged")
    # extras: what was the limb doing
    hits_by = {}
    for s in pool_s:
        v = s["verdict"]
        if v["cls"] in ("hit", "wrong"): hits_by.setdefault(v["limb"], []).append((v["t_hit"], v["row_hit"], v.get("sub")))
    for k in hits_by: hits_by[k].sort()
    for c in C:
        if c["matched"] is not None: continue
        if c.get("under_stick"): c["role"] = "articulation"; c["cause"] = "the foot shuts the hi-hat for the closed stroke that follows within 80 ms: an articulation of that stroke, not a note"; continue
        c["role"] = "extra" if c["sounding"] else "brush"; hb = hits_by.get(c["limb"], []); prev = max([h for h in hb if h[0] <= c["t"]], default=None); nxt = min([h for h in hb if h[0] > c["t"]], default=None)
        c["between"] = dict(prev=dict(t=prev[0], row=lab(prev[1]), ago_s=round(c["t"] - prev[0], 3)) if prev else None, next=dict(t=nxt[0], row=lab(nxt[1]), in_s=round(nxt[0] - c["t"], 3)) if nxt else None)
        ctx = c.get("ctx") or {}; own = [h for h in hb if h[2] == c.get("sub") and abs(h[0] - c["t"]) <= 0.3] if c.get("sub") is not None else []
        if c["part"] == "shaft": c["cause"] = (f"a passing stroke: the {c['limb']} stick's shaft ({c['zone'].replace('shaft ', '')}) is {c['depth_mm']} mm inside the {lab(c['row'])}'s edge for {int(round(c['dwell_s'] * 1000))} ms"
                                                 + (f" while the hand travels from {prev[1] and lab(prev[1])} ({c['between']['prev']['ago_s']} s before) and lifts for {lab(nxt[1])} ({c['between']['next']['in_s']} s later)" if prev and nxt else ""))
        elif own and c["row"] in J["near"].get(own[0][1], []): c["cause"] = (f"the striking finger overlaps its neighbour: {J.get('sub_label', 'part')} {c['sub']} of the {c['limb']} hand pushes {lab(c['row'])} down {c['depth_mm']} mm" + (f" ({c['pct_of_travel']} % of its travel)" if "pct_of_travel" in c else "")
                                                                             + f" {'on its way down to' if c['t'] < own[0][0] else 'while on / coming up from'} its own key {lab(own[0][1])} (sounded at {own[0][0]:.2f} s)")
        elif c["kind"] == "pass-through": c["cause"] = (f"the {c['limb']} stick's tip goes THROUGH the {lab(c['row'])} {ctx.get('direction', '')} at {abs(c['speed'])} m/s, {ctx.get('inside_rim_mm')} mm inside its rim" + (f", on the way from {lab(prev[1])} ({c['between']['prev']['ago_s']} s before) to {lab(nxt[1])} ({c['between']['next']['in_s']} s later)" if prev and nxt else "")); ctx = {}
        elif prev and prev[1] == c["row"] and c["t"] - prev[0] <= 0.15: c["cause"] = f"a second touch {int(round((c['t'] - prev[0]) * 1000))} ms after its own stroke on the same row (a rebound)"
        elif c.get("dwell_s", 0) > 0.2: c["cause"] = f"resting on {lab(c['row'])} for {c['dwell_s']} s while waiting"
        else: c["cause"] = f"a stray contact on {lab(c['row'])}" + (f" between {lab(prev[1])} and {lab(nxt[1])}" if prev and nxt else "")
        if ctx: c["cause"] += f" [{'; '.join(f'{k}: {v}' for k, v in ctx.items() if v)}]"
    # the events the layout counts as they happen, and the tallies
    ev = []
    for s in pool_s:
        v = s["verdict"]
        if v["cls"] == "in_gesture": continue                                              # counted once, on its gesture's head
        if v["cls"] == "missed": ev.append(dict(t=round(s["t"] + W, 4), cat="missed", limit=v["limit"], limb=v["limb"], sub=v.get("sub"), src=s["id"], gesture=v.get("gesture_notes"))); continue
        cat = "wrong" if v["cls"] == "wrong" else ("perfect" if v["timing"] == "in drag" else v["timing"]); ev.append(dict(t=v["t_hit"], cat=cat, limb=v["limb"], sub=v.get("sub"), src=s["id"], softer=bool(v.get("softer")), simplified=bool(v.get("simplified")), gesture=v.get("gesture_notes")))
    for c in C:
        if c.get("role") in ("extra", "brush"): ev.append(dict(t=c["t"], cat=c["role"], limb=c["limb"], sub=c.get("sub"), contact=c["i"]))
    ev.sort(key=lambda e: e["t"]); J["events"] = ev; CATS = ["perfect", "good", "early", "late", "softer", "simplified", "wrong", "missed", "extra", "brush"]
    def count(evs):
        t = {k: 0 for k in CATS}; t["missed_by"] = {}
        for e in evs:
            t[e["cat"]] += 1
            if e.get("softer"): t["softer"] += 1
            if e.get("simplified"): t["simplified"] += 1
            if e["cat"] == "missed": t["missed_by"][e["limit"]] = t["missed_by"].get(e["limit"], 0) + 1
        t["hits"] = t["perfect"] + t["good"] + t["early"] + t["late"]; t["notes"] = t["hits"] + t["wrong"] + t["missed"]; t["accuracy_pct"] = round(100.0 * t["hits"] / max(1, t["notes"]), 1); return t
    offs = [s["verdict"]["offset_ms"] for s in pool_s if s["verdict"].get("offset_ms") is not None]
    J["windows"] = dict(WIN, statement=f"PERFECT <= {WIN['perfect_ms']:.0f} ms (1 frame) · GOOD <= {WIN['good_ms']:.0f} ms (2) · EARLY / LATE <= {WIN['match_ms']:.0f} ms (3) · beyond: MISSED + EXTRA")
    J["tally"] = dict(all=count(ev), by_limb={k: count([e for e in ev if e["limb"] == k]) for k in [l["id"] for l in J["limbs"]] + [None] if any(e["limb"] == k for e in ev)}, layers=sum(not s["judged"] for s in src),
                      by_sub={f"{l}{sb}": count([e for e in ev if e["limb"] == l and e.get("sub") == sb]) for l in [x["id"] for x in J["limbs"]] for sb in sorted({e.get("sub") for e in ev if e.get("sub") is not None})} if J.get("sub_label") else None,
                      offset_ms=dict(n=len(offs), mean=round(float(np.mean(offs)), 1), median=round(float(np.median(offs)), 1), min=min(offs), max=max(offs), abs_max=max(abs(o) for o in offs)) if offs else None,
                      gestures=sum(1 for s in pool_s if s["verdict"].get("gesture_notes")), notes_in_gestures=sum(s["verdict"].get("gesture_notes") or 0 for s in pool_s),
                      articulations=sum(c.get("role") == "articulation" for c in C), in_drag=sum(bool(s["verdict"].get("in_drag")) for s in pool_s), short=sum(bool(s["verdict"].get("short")) for s in pool_s), zone_off=sum(bool(s["verdict"].get("zone_off")) for s in pool_s))
    plan = dict(played=0, misplayed=0, cut=0); dis = []
    for s in pool_s:
        f = s["plan"].get("fate"); plan[f] = plan.get(f, 0) + 1; v = s["verdict"]
        if v.get("plan_disagrees"): dis.append(dict(id=s["id"], t=s["t"], row=lab(s["row"]), plan=f, plan_limit=s["plan"].get("limit"), measured=v["cls"], note=v.get("plan_note") or v.get("reason")))
    ps = [s for s in pool_s if s["plan"].get("how") and "softer" in s["plan"]["how"]]
    J["plan_vs_measured"] = dict(plan=plan, measured=dict(sounded_on_its_row=J["tally"]["all"]["hits"], wrong=J["tally"]["all"]["wrong"], missed=J["tally"]["all"]["missed"]), disagreements=dis,
                                 softer=dict(plan=len(ps), measured=J["tally"]["all"]["softer"], plan_softer_measured_softer=sum(bool(s["verdict"].get("softer")) for s in ps), measured_softer_not_in_plan=[dict(id=s["id"], t=s["t"], row=lab(s["row"]), vel=s["vel"], vel_est=s["verdict"].get("vel_est")) for s in pool_s if s["verdict"].get("softer") and s not in ps]))
    J["vel_models"] = vel_models; J["schema"] = "review3.judgement/1"; return J


def table(J):
    T = J["tally"]; A = T["all"]; L = []; rows = {r["id"]: r["label"] for r in J["rows"]}; lim = {l["id"]: l["label"] for l in J["limbs"]}; lim[None] = "no limb (cut before a limb had it)"
    L += [f"### {J['clip']}", "", f"{J['title']} · {J['windows']['statement']} · measured at {J['hz']} Hz ({J['measure']['resolution_ms']} ms steps).", ""]
    L += ["| | notes | hit | perfect | good | early | late | softer | simplified | wrong | missed | extra | brush | accuracy |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, t in [("ALL", A)] + [(lim.get(k, k), t) for k, t in T["by_limb"].items()]: L.append(f"| {k} | {t['notes']} | {t['hits']} | {t['perfect']} | {t['good']} | {t['early']} | {t['late']} | {t['softer']} | {t['simplified']} | {t['wrong']} | {t['missed']} | {t['extra']} | {t['brush']} | {t['accuracy_pct']} % |")
    if T.get("gestures"): L += ["", f"Articulations counted as ONE gesture each (R-401): {T['gestures']} gestures covering {T['notes_in_gestures']} MIDI notes (a sweep or roll is judged once, on its head note)."]
    if T.get("by_sub"):
        L += ["", f"By {J['sub_label']} (hit · missed · brush): " + " · ".join(f"{k} {t['hits']}·{t['missed']}·{t['brush']}" for k, t in T["by_sub"].items() if t["notes"] or t["brush"] or t["extra"])]
    L += ["", "Missed, by the limit that cut it: " + (", ".join(f"{k} {v}" for k, v in sorted(A["missed_by"].items(), key=lambda kv: -kv[1])) or "none") + "."]
    o = T["offset_ms"]
    if o: L += [f"Timing offsets over {o['n']} timed hits: mean {o['mean']} ms, median {o['median']} ms, range {o['min']} … {o['max']} ms." + (f" {T['in_drag']} more notes sound inside a drag (no offset)." if T["in_drag"] else "")]
    worst = sorted([s for s in J["source"] if s["verdict"].get("offset_ms") is not None], key=lambda s: -abs(s["verdict"]["offset_ms"]))[:5]
    L += ["", "Worst offsets: " + "; ".join(f"{rows.get(s['row'], s['row'])} at {s['t']:.2f} s {s['verdict']['offset_ms']:+.1f} ms ({s['verdict']['limb']})" for s in worst) + "."]
    L += [f"Layers not judged: {T['layers']}. Articulation contacts (not notes): {T['articulations']}. Held under half their length: {T['short']}. Zone off on the right piece: {T['zone_off']}."]
    for u, m in J["vel_models"].items(): L.append(f"Velocity from approach speed ({u}): " + (f"r = {m['r']} over {m['n']} hits, median error {m['median_abs_error_velocity']} velocity steps, usable" if m.get("usable") else f"not usable ({m.get('why')}" + (f", r = {m['r']}" if "r" in m else "") + ")") + ".")
    ex = [c for c in J["contacts"] if c.get("role") in ("extra", "brush")]
    L += ["", f"**Extras and brushes ({len(ex)})**", "", "| t (s) | class | where | limb | depth | cause |", "|---|---|---|---|---|---|"] if ex else ["", "**No extras and no brushes.**"]
    for c in ex: L.append(f"| {c['t']:.2f}–{c['t_off']:.2f} | {c['role'].upper()} ({c['kind']}) | {rows.get(c['row'], c['row'])} | {c['limb']} {c['part']} | {c['depth_mm']} mm | {c['cause']} |")
    P = J["plan_vs_measured"]; L += ["", f"**Plan against measurement.** The R-417 log: {P['plan']}. Measured: {P['measured']}. Softer: plan {P['softer']['plan']}, measured {P['softer']['measured']} ({P['softer']['plan_softer_measured_softer']} of the plan's read as softer; {len(P['softer']['measured_softer_not_in_plan'])} measured softer that the plan does not list)."]
    for d in P["disagreements"]: L.append(f"- {d['row']} at {d['t']:.2f} s ({d['id']}): plan {d['plan']}" + (f" ({d['plan_limit']})" if d["plan_limit"] else "") + f", measured {d['measured']}: {d['note']}")
    return "\n".join(L) + "\n"

# midi2motion: the lab's command line was dropped
