# LIBRARY COPY of drum-benchmark/tools/habits.py (nelvids lab, 2026-11-2x), packaged in midi2motion (vendored from the nelvids drums library): analysis-only functions and the lab's CLI dropped, lab paths -> rigenv.
#!/usr/bin/env python3
"""habits.py: R-574's hand-habit ERRORS and R-575's per-piece rebound, measured on a judged performance (plan limbs, onsets, velocities); fixes nothing (round 6).

    import habits; H = habits.check(J)        -> dict(role_flips, swaps, steals, bounces, fills, roles, ...) with every event's time, piece and hand

HAND NOTES: the judged hand notes with their PLAN limb (L / R); a note the plan cut has no hand and is skipped.
BOUNCE (R-574, from the MIDI, whoever plays it): a run of >= 2 notes on ONE piece, each gap <= 120 ms, velocity flat or decaying (each note <= max(1.10 x, + 8) the one
  before). One hand, never a fill; a bounce the plan SPLITS between the hands is counted (bounce_splits, R-528).
FILL BAR: in a bar, the hand notes not in bounces cover >= 2 pieces with >= 2 tom notes, or >= 3 pieces with the snare above the track's median per bar; accents kept or rising
  (the bar's mean velocity >= the track's median bar mean - 5). PHRASE: the bars between two fill bars (or the clip's ends).
ROLE: the majority hand of each piece over the track's NON-fill bars (a piece needs >= 4 such notes to have a role).
  (a) ROLE FLIP: in a phrase that follows a fill, a piece with >= 3 notes whose majority hand is not its role. One error per (phrase, piece).
  (b) SAME-PIECE SWAP: 1 or 2 consecutive notes of a piece by the non-role hand, with the role hand playing that piece just before and just after, all within 1.0 s
      (bounces and fill bars excluded: a fill may borrow the other hand).
  (c) RESERVED-LIMB STEAL: a note on a piece that is NOT h's role (a piece with no role counts as the lead hand's) dealt to hand h whose NEXT note comes within 0.40 s (h is reserved for it), while the other hand's next note comes later than that and its
      last note was >= 0.10 s before (it was free for longer and had time to get there). Simultaneous two-hand notes (< 30 ms) are not counted. Fill bars count too (a fill may borrow a hand, not one about to be needed).
REBOUND (R-575): snare, ride, toms (not the floor tom) rebound: a bounced repeat is one hand. Crash, floor tom and hi-hat rebound little: a one-hand hi-hat run of >= 8 notes
  each <= 70 ms apart (above ~14 notes/s sustained by one wrist; ours, from the 16th-note hat ceiling at ~210 bpm) flags the MIDI as MACHINE-MADE, not a cue to share hands.
"""
import collections, glob, json, pathlib, statistics, sys
sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent; LAB = HERE.parent
HAND_ROWS = {"snare", "tom1", "tom2", "tom3", "floor", "floor2", "hat", "ride", "crash", "crash2", "china", "splash"}; TOMS = {"tom1", "tom2", "tom3", "floor", "floor2"}
BOUNCE_GAP, BOUNCE_UP = 0.120, 1.10; SWAP_WIN = 1.0; STEAL_WIN = 0.40; SIMUL = 0.030
REBOUNDS = {"snare": "rebounds", "ride": "rebounds", "tom1": "rebounds", "tom2": "rebounds", "tom3": "rebounds", "crash": "little", "floor": "little", "floor2": "little", "hat": "little"}
MACHINE_RUN, MACHINE_GAP = 8, 0.070


def notes_of(J):
    return sorted([dict(id=s["id"], t=s["t"], p=s["row"], h=(s.get("plan") or {}).get("limb"), v=s["vel"]) for s in J["source"] if s.get("judged") and s["row"] in HAND_ROWS and (s.get("plan") or {}).get("limb") in ("L", "R")], key=lambda n: n["t"])


def bounces(N):
    out = []; byph = collections.defaultdict(list)
    for n in N: byph[n["p"]].append(n)
    for p, L in byph.items():
        run = [L[0]]
        for a, b in zip(L, L[1:]):
            if b["t"] - a["t"] <= BOUNCE_GAP and b["v"] <= max(BOUNCE_UP * a["v"], a["v"] + 8): run.append(b); continue
            if len(run) >= 2: out.append(run)
            run = [b]
        if len(run) >= 2: out.append(run)
    return out


def check(J):
    N = notes_of(J); g = J["grid"]; beat = g["beat_s"]; bpb = g.get("bpb", 4); bar_s = beat * bpb; lead = g["lead"]
    B = bounces(N); in_b = {n["id"] for r in B for n in r}; bar = lambda t: int((t - lead) // bar_s); per = collections.defaultdict(list)
    for n in N: per[bar(n["t"])].append(n)
    med_sn = statistics.median([sum(1 for n in L if n["p"] == "snare") for L in per.values()]) if per else 0
    med_v = statistics.median([statistics.mean(n["v"] for n in L) for L in per.values()]) if per else 0
    fills = set(); fills_with_bounces = set()
    for b, L in per.items():
        def is_fill(LL):
            pcs = {n["p"] for n in LL}; toms = sum(1 for n in LL if n["p"] in TOMS); sn = sum(1 for n in LL if n["p"] == "snare")
            loud = (statistics.mean(n["v"] for n in LL) >= med_v - 5) if LL else False
            return loud and ((len(pcs) >= 2 and toms >= 2) or (len(pcs) >= 3 and sn > med_sn))
        if is_fill([n for n in L if n["id"] not in in_b]): fills.add(b)
        elif is_fill(L): fills_with_bounces.add(b)                                        # would be a "fill" only because of bounced notes
    role = {}
    for p in {n["p"] for n in N}:
        c = collections.Counter(n["h"] for n in N if n["p"] == p and bar(n["t"]) not in fills)
        if sum(c.values()) >= 4: role[p] = c.most_common(1)[0][0]
    # (a) role flips: phrases after a fill
    flips = []; fb = sorted(fills); bounds = []
    for k, f in enumerate(fb):
        end = fb[k + 1] if k + 1 < len(fb) else 10 ** 6; bounds.append((f + 1, end - 1))
    for b0, b1 in bounds:
        ph = [n for n in N if b0 <= bar(n["t"]) <= b1]
        for p, r in role.items():
            c = collections.Counter(n["h"] for n in ph if n["p"] == p)
            if sum(c.values()) >= 3 and c.most_common(1)[0][0] != r: flips.append(dict(t=min(n["t"] for n in ph if n["p"] == p), piece=p, hand=c.most_common(1)[0][0], role=r, bars=[b0, b1], notes=sum(c.values())))
    # (b) same-piece swaps
    swaps = []
    for p, r in role.items():
        L = [n for n in N if n["p"] == p]; k = 0
        while k < len(L):
            if L[k]["h"] != r and L[k]["id"] not in in_b and bar(L[k]["t"]) not in fills:
                j = k
                while j + 1 < len(L) and L[j + 1]["h"] != r: j += 1
                if j - k + 1 <= 2 and k > 0 and j + 1 < len(L) and L[k - 1]["h"] == r and L[j + 1]["h"] == r and L[j + 1]["t"] - L[k - 1]["t"] <= SWAP_WIN:
                    swaps.append(dict(t=L[k]["t"], piece=p, hand=L[k]["h"], role=r, notes=j - k + 1))
                k = j + 1
            else: k += 1
    # (c) reserved-limb steals
    steals = []; T = {h: [n["t"] for n in N if n["h"] == h] for h in "LR"}
    for n in N:
        h = n["h"]; o = "L" if h == "R" else "R"; t = n["t"]
        if any(abs(x - t) < SIMUL for x in T[o]): continue
        hn = min((x for x in T[h] if x > t + 1e-6), default=None); on = min((x for x in T[o] if x > t + SIMUL), default=9e9); op = max((x for x in T[o] if x < t - SIMUL), default=-9e9)
        mine = role.get(n["p"], "R") == h                                                 # its own piece (no role yet: the lead hand's) is never a steal
        if not mine and hn is not None and hn - t <= STEAL_WIN and on - t > hn - t and t - op >= 0.10: steals.append(dict(t=t, piece=n["p"], hand=h, free=o, own_next=round(hn - t, 3), other_next=round(min(on - t, 9.0), 3)))
    splits = [dict(t=r[0]["t"], piece=r[0]["p"], notes=len(r), hands="+".join(sorted({n["h"] for n in r}))) for r in B if len({n["h"] for n in r}) > 1]
    return dict(roles=role, fill_bars=sorted(fills), bounce_only_fill_bars=sorted(fills_with_bounces), bounces=[dict(t=r[0]["t"], piece=r[0]["p"], hands="+".join(sorted({n["h"] for n in r})), notes=len(r)) for r in B],
                role_flips=flips, swaps=swaps, steals=steals, bounce_splits=splits, counts=dict(role_flips=len(flips), swaps=len(swaps), steals=len(steals), bounce_splits=len(splits), bounces=len(B), fill_bars=len(fills), bounce_only_fill_bars=len(fills_with_bounces), hand_notes=len(N)))
