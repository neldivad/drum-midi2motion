# LIBRARY COPY of drum-planner-v2/tools/deal_dp.py (NOT ADOPTED) (nelvids lab, 2026-11-2x), packaged in midi2motion (vendored from the nelvids drums library): analysis-only functions and the lab's CLI dropped, lab paths -> rigenv.
#!/usr/bin/env python3
"""deal_dp.py: the deal (notes -> hands) as an EXACT dynamic programme with pluggable costs. Replaces chart2.stick's beam (width 160) in memory; chart2 itself is
imported by path and never edited.

    import deal_dp; deal_dp.install(chart2, terms={"rebound": 0.0, ...})      # then chart2.build(...) deals with the DP
    deal_dp.compare(chart2, K, mid)                                           # beam vs DP on one chart: cost of each, notes dealt differently

WHY EXACT. chart2.stick scores a deal note by note; every term reads only (a) the note and the hand it goes to and (b) each hand's LAST stroke: its piece, zone, the
time it is free again (a sweep's end) and its role. So the state after an onset is the pair (last stroke of L, last stroke of R), and the cheapest deal is a shortest
path over those pairs (Viterbi). The beam keeps the 160 cheapest pairs per onset; the DP keeps EVERY distinct pair with its cheapest cost, so its answer is the true
optimum of the same cost. The state space is not (L piece, R piece) = 144: the terms read the time since each hand's last stroke (the repeat, travel-speed and R-441
shift-time terms), so the state carries that stroke's time too; one of the two is always the current onset, so an onset holds O(onsets so far) states and the
whole chart is O(n^2): about 0.1-2 s in Python for a window with its context.
Ties: candidates are generated in the beam's order and a state keeps its first cheapest arrival, so on a chart where the beam never pruned the optimum the two deals
are identical (parity).

THE COST, term by term (the base = chart2.stick's own, unchanged; the rest are hooks, weight 0 unless named in `terms`):
  base      K.PREF (hand preference per piece, derived from the layout), a same-hand repeat < 100 ms (+60), travel speed over 1.5 m/s (2 (v - 1.5)^2), a close repeat
            (+2 < 125 ms, +0.4 < 160 ms), R-441's minimum-jerk shift that does not fit (30 (1 - have/need)), crossed arms (drumkit.yaml preference.crossing), a note no
            free hand can take (+40, the quietest first).
  rebound   (R-528, built, off in phase 1) a note on the ride or a crash given to the hand that did NOT play that cymbal's previous note when that note was < 0.25 s ago:
            the other hand crossing in to help a fast cymbal pattern. Cost = weight per note.
  splay     (R-557, hook only) needs the stick's heading at contact (stroke_plan.homes), which the deal does not have: not built.
  collision (hook only) a predicted clearance cost for a hand's lane (e.g. the left hand to tom 1 past the hi-hat): needs the kit's swept volumes: not built.
  motif     (R-449, hook only) repeated figures tied to one sticking: needs a figure detector and a tie between DP stages: not built.
  handpref  (R-556 hypotheses, hook only) round 5's hand_pref.py costs, on only by flag: not wired here.
"""
import collections, time
import numpy as np

TERMS = {"rebound": 0.0, "splay": 0.0, "collision": 0.0, "motif": 0.0, "handpref": 0.0, "role": 0.0, "bounce": 0.0, "reserve": 0.0, "accent": 0.0}
BUILT = {"rebound", "role", "bounce", "reserve", "accent"}
FILL_ROLE = 0.25; GRID = {}                                                    # GRID: {"bar_ticks": ...} set by the caller (planner.py) for round 6's bar-based fill test            # R-574 (1): a piece's role hand = >= 75 % of its >= 4 non-fill notes in the first pass; inside a fill a role break costs a quarter


def _habits():
    """round 6's habit checks (the benchmark's tools/habits.py, by path): their thresholds are the deal's, so the cost and the error are the same thing"""
    import importlib, sys, pathlib
    p = str(pathlib.Path(__file__).resolve().parent)      # library: habits.py sits beside this file
    if p not in sys.path: sys.path.insert(0, p)
    return importlib.import_module("habits")
REB_WIN = 0.25
STATS = {}


def stick_dp(N, spt, groups, K, chart2, terms=None, width=None):
    """chart2.stick with the beam replaced by the exact DP (width None) or the beam itself (width 160: the reference). Pre- and post-processing as chart2.stick."""
    EPT = chart2.EPT; MIN_REPEAT = chart2.MIN_REPEAT; MIN_FOOT = chart2.MIN_FOOT
    terms = dict(TERMS, **(terms or {})); w_reb = float(terms.get("rebound", 0.0))
    for k, v in terms.items():
        if v and k not in BUILT: raise NotImplementedError(f"deal term {k} is a hook only (phase 1)")
    issues = []; hands = []; lead = K.LEAD; CR = K.CROSSING
    for n in N:
        m = K.NOTE_MAP.get(n["note"]); n["t"] = n["tick"] * spt
        if m is None: n.update(piece=None, zone=None, limb=None, why="layer (R-401): sounds, no limb" if n["note"] not in K.NOTE_UNMAPPED else f"no {K.NOTE_UNMAPPED[n['note']]} in this layout"); continue
        n["piece"], n["zone"] = m[0], m[1]
        if m[2] != "hand": n["limb"] = m[2]
        else: hands.append(n)
    if len(K.KICKS) > 1:
        f2 = K.FOOT_OF[K.KICKS[1]] + "F"; last = -9.0; ped = [n["t"] for n in N if n.get("zone") == "pedal"]
        for n in N:
            if n.get("zone") != "beater": continue
            if n["t"] - last < MIN_FOOT and not any(abs(n["t"] - x) < 0.2 for x in ped): n["piece"] = K.KICKS[1]; n["limb"] = f2
            else: last = n["t"]
    sweep_of = {}
    for g in groups:
        if g["kind"] == "sweep":
            for n in g["notes"]: sweep_of[id(n)] = g
    onsets = collections.OrderedDict()
    for n in hands:
        g = sweep_of.get(id(n))
        if g is not None and n is not g["notes"][0]: n["limb"] = "sweep"; continue
        onsets.setdefault(n["tick"], []).append(n)
    merged = []
    for tick, L in onsets.items():
        for n in sorted(L, key=lambda x: -x["vel"]):
            if n in L and any(m is not n and m in L and m["piece"] == n["piece"] and m["zone"] != n["zone"] and m["vel"] >= n["vel"] for m in L):
                ld = max((m for m in L if m is not n and m["piece"] == n["piece"] and m["zone"] != n["zone"]), key=lambda x: x["vel"]); L.remove(n); merged.append((n, ld))
    SP = {(p, z, h): K.strike_point(p, z, h) for p, z, h in {(n["piece"], n["zone"], h) for n in hands for h in "LR"}}
    key = lambda n: "cross" if n["zone"] == "cross" else n["piece"]
    CYM_REB = {p["id"] for p in K.PIECES if p["kind"] == "cymbal" and p["id"] != K.HAT}
    t0 = time.time()
    w_role, w_bnc, w_res = float(terms.get("role", 0.0)), float(terms.get("bounce", 0.0)), float(terms.get("reserve", 0.0)); w_acc = float(terms.get("accent", 0.0))   # accent (2026-11-24, pedagogy G2): an accent's taps go to its hand
    def dp(extra=None):
      # each state: (cost, gen index, (sL, sR), back), s = chart2's own (piece, zone, t_free, t_last, role) per hand; back = (previous back, tick, opt, dropped), a linked list
      states = [(0.0, 0, (None, None), None)]; nstates = []
      for tick, L in onsets.items():
          t = tick * spt; best = {}; gen = 0
          for cost, _, (sL, sR), back in states:
              st = {"L": sL, "R": sR}
              free = [h for h in "LR" if st[h] is None or st[h][2] <= t + 1e-6]
              cand = sorted(L, key=lambda n: (-(n.get("art", {}).get("kind") == "sweep"), -n["vel"])); keep, dropped = cand[:len(free)], cand[len(free):]
              opts = [((keep[0], h),) for h in free] if len(keep) == 1 else [((keep[0], "L"), (keep[1], "R")), ((keep[0], "R"), (keep[1], "L"))] if len(keep) == 2 else [()]
              for opt in opts:
                  c = cost + 40.0 * len(dropped); s2 = dict(st)
                  for n, h in opt:
                      c += K.PREF[key(n)][h]; prev = st[h]
                      if prev is not None:
                          dt = t - prev[3]; dist = float(np.linalg.norm(SP[(n["piece"], n["zone"], h)] - SP[(prev[0], prev[1], h)]))
                          if dt < MIN_REPEAT - 1e-6: c += 60.0
                          c += 2.0 * max(0.0, dist / max(dt, 1e-3) - 1.5) ** 2 + (2.0 if dt < 0.125 else 0.4 if dt < 0.16 else 0.0)
                          need = EPT.shift_time(dist); have = max(1e-3, dt - 0.05)
                          if dist > 0.05 and have < need: c += 30.0 * (1 - have / need)
                      if w_reb and n["piece"] in CYM_REB:                                       # R-528: the other hand played this cymbal's last note a moment ago: this note crosses in to help
                          o = "L" if h == "R" else "R"; po = st[o]
                          if po is not None and po[0] == n["piece"] and t - po[3] < REB_WIN and (prev is None or prev[0] != n["piece"] or t - prev[3] > t - po[3]): c += w_reb
                      if extra is not None: c += extra(n, h, st, t)
                      g = sweep_of.get(id(n)); tf = g["notes"][-1]["tick"] * spt if g is not None else t; s2[h] = (n["piece"], n["zone"], tf, tf, K.ROLE[n["piece"]])
                  if s2["L"] is not None and s2["R"] is not None and min(t - s2["L"][3], t - s2["R"][3]) > -1e-6 and max(t - s2["L"][3], t - s2["R"][3]) < 0.4 and opt:
                      xl = SP[(s2["L"][0], s2["L"][1], "L")][0]; xr = SP[(s2["R"][0], s2["R"][1], "R")][0]
                      if xr > xl + 0.05:
                          pair = [s2[lead][4], s2["L" if lead == "R" else "R"][4]]; c += 0.0 if pair in CR["free"] else CR["cheap"]["cost"] if pair in CR["cheap"]["pairs"] else CR["cost"]
                  k2 = (s2["L"], s2["R"]); entry = (c, gen, k2, (back, tick, tuple((id(n), h) for n, h in opt), tuple(id(n) for n in dropped))); gen += 1
                  if k2 not in best or c < best[k2][0]: best[k2] = entry
          states = sorted(best.values(), key=lambda e: (e[0], e[1]))
          if width is not None: states = states[:width]
          nstates.append(len(best))
      c_best, _, _, back = states[0]; chain = []
      while back is not None: back, tick, opt, dropped = back; chain.append((tick, opt, dropped))
      chain.reverse(); return chain, c_best, nstates
    chain, c_best, nstates = dp(); keep_ = {k: STATS[k] for k in ("habits_from",) if k in STATS}; STATS.clear(); STATS.update(keep_); STATS["base_cost"] = round(c_best, 4)
    if w_role or w_bnc or w_res or w_acc:                                                              # R-574 / R-575 (phase 2 plan): a second pass with the habit costs, the roles read from the first. Definitions = round 6's checks (benchmark tools/habits.py)
        import statistics
        hn = sorted(hands, key=lambda n: n["t"]); byid0 = {id(n): n for n in hands}; dealt = {}
        for tick, opt, dropped in chain:
            for i, h in opt: dealt[i] = h
        for n in hn:                                                                          # a sweep's later notes follow its first
            g = sweep_of.get(id(n))
            if g is not None and id(n) not in dealt and id(g["notes"][0]) in dealt: dealt[id(n)] = dealt[id(g["notes"][0])]
        HB = _habits(); prev_in = {}; nclu = 0; byp = collections.defaultdict(list)
        for n in hn: byp[n["piece"]].append(n)
        for pc, L_ in byp.items():                                                            # bounces: >= 2 notes on one piece, <= 120 ms apart, velocity flat or falling (round 6)
            run = [L_[0]]
            for x, y in list(zip(L_[:-1], L_[1:])) + [(None, None)]:
                if y is not None and y["t"] - x["t"] <= HB.BOUNCE_GAP and y["vel"] <= max(HB.BOUNCE_UP * x["vel"], x["vel"] + 8): run.append(y); continue
                if len(run) >= 2: nclu += 1; [prev_in.__setitem__(id(b_), a_["t"]) for a_, b_ in zip(run[:-1], run[1:])]
                if y is not None: run = [y]
        import accent as ACM; acc_in = {}                                                      # accent chains (tools/accent.py): each tap chained to the note before it, so the chain is one hand
        for ch in ACM.chains(hn): [acc_in.__setitem__(id(b_), a_["t"]) for a_, b_ in zip(ch[:-1], ch[1:])]
        bar_t = GRID.get("bar_ticks"); bar = (lambda n: int(n["tick"] // bar_t)) if bar_t else (lambda n: int(n["t"] // 2.0))
        per = collections.defaultdict(list)
        for n in hn: per[bar(n)].append(n)
        med_sn = statistics.median([sum(1 for n in L_ if n["piece"] == "snare") for L_ in per.values()]) if per else 0; med_v = statistics.median([statistics.mean(n["vel"] for n in L_) for L_ in per.values()]) if per else 0
        def is_fill(LL):
            if not LL: return False
            pcs = {n["piece"] for n in LL}; toms = sum(1 for n in LL if n["piece"] in HB.TOMS); sn = sum(1 for n in LL if n["piece"] == "snare")
            return statistics.mean(n["vel"] for n in LL) >= med_v - 5 and ((len(pcs) >= 2 and toms >= 2) or (len(pcs) >= 3 and sn > med_sn))
        fbars = {b_ for b_, L_ in per.items() if is_fill([n for n in L_ if id(n) not in prev_in])}; fill = {id(n): bar(n) in fbars for n in hn}
        cnt = collections.defaultdict(collections.Counter)
        for n in hn:
            if not fill[id(n)] and id(n) in dealt: cnt[n["piece"]][dealt[id(n)]] += 1
        role = {p_: c.most_common(1)[0][0] for p_, c in cnt.items() if sum(c.values()) >= 4}
        import bisect
        TA = {h: sorted(byid0[i]["t"] for i, hh in dealt.items() if hh == h) for h in "LR"}        # the first pass's note times per hand: the reservation's look-ahead
        def nxt(h, t):
            L_ = TA[h]; i = bisect.bisect_right(L_, t + HB.SIMUL); return L_[i] - t if i < len(L_) else 9.0
        def last(h, t):
            L_ = TA[h]; i = bisect.bisect_left(L_, t - HB.SIMUL) - 1; return t - L_[i] if i >= 0 else 9.0
        def extra(n, h, st, t):
            c = 0.0; r = role.get(n["piece"]); o = "L" if h == "R" else "R"
            if w_role and r is not None and r != h and id(n) not in prev_in: c += w_role * (FILL_ROLE if fill.get(id(n)) else 1.0)       # R-574 (1)(2): the role hand; a fill may borrow
            if w_bnc and id(n) in prev_in:                                                    # R-528 / R-574: a bounce note goes to the hand that played the one before it
                tp = prev_in[id(n)]; me = st[h]
                if not (me is not None and me[0] == n["piece"] and abs(me[3] - tp) < 1e-6): c += w_bnc
            if w_acc and id(n) in acc_in:                                                      # pedagogy G2: an accent's tap goes to the hand that played the note before it in the chain
                tp = acc_in[id(n)]; me = st[h]
                if not (me is not None and me[0] == n["piece"] and abs(me[3] - tp) < 1e-6): c += w_acc
            if w_res and role.get(n["piece"], "R") != h:                                      # R-574 (3): not this hand's piece, its next note soon, the other hand free longer
                dh = nxt(h, t)
                if dh <= HB.STEAL_WIN and nxt(o, t) > dh and last(o, t) >= 0.10: c += w_res
            return c
        chain, c_best, nstates = dp(extra)
        STATS.update(roles=role, fill_bars=sorted(fbars), bounce_clusters=nclu, bounce_notes=len(prev_in), fill_notes=sum(1 for v in fill.values() if v),
                     bounce_ids=sorted(byid0[i]["id"] for i in prev_in), accent_taps=len(acc_in), accent_ids=sorted(byid0[i]["id"] for i in acc_in), fill_ids=sorted(byid0[i]["id"] for i, v in fill.items() if v))
    STATS.update(seconds=round(time.time() - t0, 3), onsets=len(onsets), states_max=max(nstates or [0]), states_mean=round(float(np.mean(nstates or [0])), 1), cost=round(c_best, 4), width=width)
    byid = {id(n): n for n in hands}
    for tick, opt, dropped in chain:
        for i, h in opt: byid[i]["limb"] = h
        for i in dropped:
            n = byid[i]; n["limb"] = None; busy = [g for g in groups if g["kind"] == "sweep" and g["notes"][0]["tick"] < tick <= g["notes"][-1]["tick"]]
            n["why"] = "more hand hits than free hands: dropped (the quietest)" + ("; one hand is in a sweep" if busy else ""); n["limit"] = "two hands"
            issues.append(dict(tick=tick, kind="more hits than hands", hits=[f'{K.NAMES.get(x["note"], x["note"])} v{x["vel"]}' for x in onsets[tick]], dropped=f'{K.NAMES.get(n["note"], n["note"])} v{n["vel"]}', sweep=bool(busy)))
    for g in groups:
        if g["kind"] == "sweep":
            for n in g["notes"][1:]: n["limb"] = g["notes"][0]["limb"]
    for n, ld in merged: n["limb"] = ld["limb"]; n["merged"] = True; n["why"] = f"one stroke with {K.NAMES.get(ld['note'], ld['note'])} (two zones of one piece)"
    return issues


def set_grid(src_mid, bpb=4.0):
    """the window's real bar length in MIDI ticks (the source file's ticks per beat x its quarters per bar), for round 6's bar-based fill test"""
    import mido
    GRID["bar_ticks"] = int(round(mido.MidiFile(str(src_mid)).ticks_per_beat * float(bpb)))


def install(chart2, terms=None, width=None):
    """chart2.stick -> the DP (width None) in memory; chart2.py is never written"""
    orig = chart2.stick if not hasattr(chart2.stick, "_pv2") else chart2.stick._orig
    def stick(N, spt, groups, K): return stick_dp(N, spt, groups, K, chart2, terms, width)
    stick._pv2 = True; stick._orig = orig; chart2.stick = stick
    return orig
