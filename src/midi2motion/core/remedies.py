#!/usr/bin/env python3
"""LIBRARY COPY of drum-benchmark/tools/remedies.py (the adopted solver's adapter; see library/performers/drums/README.md), lab paths turned into params, one() takes the window as params.
remedies.py: LAYER 1, a remedy table inside R-417's repair loop (an adapter: the wrapped rig lab is imported and monkeypatched in memory, never edited or copied).

        -> out/remedies/judgement_<key>_<tag>.json   the judge's file (unchanged judge) + `remedy`: the remedies tried, kept and reverted, the passes, the losses

WHY. The round-3 solver answers every hard-limit violation the same way: the nearest note of that limb steps down (R-448's re-deal or nearest piece, then softer, then
cut). A collision is geometry, and cutting a note does not move a stick; a violation with no note within 0.4 s is never paid at all, so it stays in the played clip.

THE TABLE (cheapest first; cut stays the last resort; every limit stays frozen: C-COL-1's 3 mm and the struck piece's 22 mm, the speed ceilings, the joint ranges, the judge):
  collision, the limb WAITING (no stroke of that limb within 0.15 s of the frames):
     W1  lift the waiting stick: the tip's target height gets a smooth extra lift over the waiting part of the gap (from the rebound's settle to before the next
         stroke's preparation). Tried at +20 mm, then +40 mm, then +60 mm (the clearance is measured, not assumed: the kept lift is reported).
  collision, the limb STRIKING or TRAVELLING (a stroke of that limb within 0.15 s):
     P1  raise the arc: the travel's hump (stroke_plan.tip_plan: 4u(1-u) x min(70 mm, 0.18 x distance)) gets +30 mm, then +60 mm, on the stroke the limb travels to.
     then the existing ladder: R-448 a (the other hand), R-448 b (the nearest neighbouring piece), softer, cut.
  every other limit (speed ceiling, continuity, end-point speed, joint range, the shift table): the existing ladder, unchanged.
  R-529, no freeze: a violation with no note near (the old "unresolved") gets W1 too instead of being left in the clip; a cut never charges a neighbour for the same
     collision run twice in a pass.
ACCEPTANCE (local): a remedy is applied for the next pass; after that pass's solve, the frames over a hard limit in its window (+-0.5 s around the failure, on that
limb) must have fallen and no new kind of violation may appear there, else it is reverted and the failure goes on down the table. The planner itself re-solves the whole
clip each pass (its targets are clip-wide); only the acceptance is local.
NOT BUILT (said plainly): "another approach direction" (the stroke planner has no approach-direction parameter to steer without editing it); R-528 (rebound).
ROUND 2 (2026-11-22, tag v007; REMEDY_ROWS=W1,P1 reproduces round 1):
  T1  lift the tail rest: after a limb's LAST stroke tip_plan aims the rest at a phantom stroke on the same piece 3 s later, so a resting stick sinks toward that head
      and W1 (which lifts a gap INTO a stroke) never reaches it. T1 lifts the tail itself (+20/40/60 mm, a smoothstep over 0.2 s from the rebound's settle).
  A1  arm-assisted accent (R-402, R-405): a loud stroke (MIDI velocity >= 90) asks for lift_h(v) (up to 325 mm); the grip's alpha cone (stick_alpha hard 35 deg)
      cannot take it with the rig's arm share (S-GRIP-4: 6 % unless loud AND slow), so stroke_plan.plan lowers the lift (S-GRIP-2, down to 0.45x) and the stroke
      comes out soft. Measured each pass: when the first plan's cone cuts a loud stroke's lift and the solve delivers < 75 % of lift_h(v), the arm's share over that
      stroke's lift and downstroke rises by +0.17, then +0.34 (capped at the rig's own 0.40). Kept only if that stroke's tip speed rises >= 5 % and its window gets
      no new violation; the speed ceilings judge the faster arm as before.
  P2  rise first, then over (tried on the busy fill, tag v007u; REMEDY_ROWS must name P2): a stick travelling INTO a cymbal from below its rim (the tip at or under the
      cymbal's plane during the collision) gets an early-peaking hump, sin(pi u^0.4), +30/60/90 mm: up, then in, then down. P1's 4u(1-u) peaks mid-travel and
      W1 lifts a wait, and both push the stick up through the rim from below (the cap sweep's finding).
  W2  lower the stick under a cymbal (REMEDY_ROWS must name W2): a WAITING stick that meets a cymbal from below gets the W1 shape downward, -20/40/60 mm.
  CAP REMEDY_MAXIT (the repair-pass cap, a solver budget; default run2.MAX_IT = 16). REMEDY_JUDGE_FROM=k judges every pass from k on and writes
      judgement_<key>_<tag>_cap<pass>.json: the loop is deterministic and the cap only stops it, so pass k IS the run with cap k (one run gives the whole sweep).
  `remedy.cone`: per loud stroke, the first plan's alpha_free and the S-GRIP-2 scale it implies; `remedy.strokes`: the solve's per-stroke lift and tip speed.
"""
import json, os, pathlib, sys, time, collections
sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent; sys.path.insert(0, str(HERE))
import rigenv as bench
import numpy as np
OUT = None; PRESET = "hh_out30_down65"      # library: OUT is set by perform() (the judgement's folder); the lab wrote out/remedies/
OFF = bool(os.environ.get("REMEDY_OFF"))   # the control: the same adapter and pipeline with the table off (must reproduce the v005 loop)
WAIT_STEPS = [0.020, 0.040, 0.060]; ARC_STEPS = [0.030, 0.060]; NEAR_STROKE = 0.15; WIN = 0.5
ARM_STEPS = [0.17, 0.34]; LOUD_V = 90; LIFT_SHORT = 0.75; ARM_MAX = 0.40    # A1 (round 2): extra arm share for a loud stroke the grip cone cut; 0.40 = the rig's own most (base 0.06 + loud_slow 0.34)
ROWS = set((os.environ.get("REMEDY_ROWS") or "W1,P1,T1,P2,W2,A1p,G,D558,SPL").split(","))   # round 5: the v009 table + D558 (R-558: no substitution in easy spans, the nearest drum as the last resort in hard ones) + SPL (R-557: the stick-splay cost); HP* (hand preference, R-556) and S1 are flags     # round 1 = W1,P1 (tag v006); round 2 adds T1 (the tail rest) and A1 (the accent's arm)
CAP = int(os.environ["REMEDY_MAXIT"]) if os.environ.get("REMEDY_MAXIT") else None   # the repair-pass cap (a solver budget; None = run2.MAX_IT, 16)
JUDGE_FROM = int(os.environ["REMEDY_JUDGE_FROM"]) if os.environ.get("REMEDY_JUDGE_FROM", "-") not in ("", "-") else None   # judge every pass from this one on (the cap sweep: pass k = the run with cap k)
BOOST = {}          # (hand, round(t, 3), piece) of the stroke the limb travels to -> {"wait": m, "arc": m, "arm": share}; (hand, "tail", None) -> {"wait": m}
DIAG = {}           # (hand, round(t, 3), piece) -> the grip cone's verdict on that stroke's lift in its first plan (S-GRIP-2), for the loud-softer diagnosis
JUDGE_V = os.environ.get("REMEDY_JUDGE", "v2")   # round 4: new runs are judged by judge_v2 (the two foot fixes); "v1" = the wrapped judge alone
SWEEP_IDS = set()   # round 4, R-551: the chart's note ids inside drum sweeps (tools/sweeps.py)
HARD_IDS = set()    # round 5, R-558: the chart's hand notes in HARD spans (tools/difficulty.py); every other hand note is in an easy span
SPLAY_W = float(os.environ.get("REMEDY_SPLAY_W", "0.5"))   # R-557's planner cost: per (deg over 15)^2 / 100 of a far-side stroke's inward stick heading at contact
SWEEP_VETO = set()  # (hand, round(t, 3), piece) of a sweep move whose arc broke a limit: given back for the clip (never paid with a note)
SWEEP_ARC = float(os.environ.get("REMEDY_SWEEP_ARC", "0.04"))   # S1: the arc over the rims between two drums of a sweep, m
GRID = {}           # round 4: {"bpb": quarters per bar, "bar0": the window's first real bar} for a window not in 4/4
INS = {}            # "path": the inspector dataset each solve writes (the stroke stats A1 reads)
A1ON = {"on": False}   # A1p runs only in the accent phase, after the geometry converged
AUTO = {}           # A1p (round 3): (hand, round(t, 3), piece) -> the arm share the in-plan accent gives a loud stroke the cone cut (recomputed in every plan; vetoed in BOOST)
REG = {}            # (hand, t or "tail", piece, what) -> [t0, t1]: where a remedy changes the targets (the seam check reads its edges)
LIFT_H = lambda v: 0.025 + 0.30 * (v / 127.0) ** 1.6                            # android-drums drum_perf.lift_h (R-402's velocity -> lift), for reporting


GRIP_DEG = os.environ.get("REMEDY_GRIP_DEG")          # round 4, item C: the stick's angle across the palm, an IN-MEMORY override of rig.yaml grip.stick_in_hand_deg (60)
HEAD_PT = os.environ.get("REMEDY_HEAD_PT")            # "x,y,z": an in-memory override of rig.yaml swivel.head_point (where the palm heads: the elbow's swivel)
ELBOW_K = os.environ.get("REMEDY_ELBOW_K")            # a factor on the natural-elbow prior's swivel (S-IK-3; 0 = straight down, 1 = rig.yaml's Kim/Rosen + CMU table): < 1 = lower, tucked elbows
GRIPDIAG = {"homes": collections.Counter(), "report": {}}


def install(R2):
    """patch the planner in memory: strokes carry their hand; tip_plan adds the boosts"""
    import stroke_plan as SP, arm_rig as AR
    if GRIP_DEG: SP.G["stick_in_hand_deg"] = float(GRIP_DEG)                            # SP.G is arm_rig.CFG["grip"]: the file is never written
    if HEAD_PT: AR.CFG["swivel"]["head_point"] = [float(x) for x in HEAD_PT.split(",")]
    if ELBOW_K and not hasattr(AR.ArmRig.prior, "_remedy"):
        orig_prior = AR.ArmRig.prior
        def prior(self, S, W): return float(ELBOW_K) * orig_prior(self, S, W)          # the swivel the planner prefers, pulled toward elbow-down; the joint limits and the solver are unchanged
        prior._remedy = True; AR.ArmRig.prior = prior
    orig_homes = SP.homes if not hasattr(SP.homes, "_remedy") else SP.homes._orig
    if "SPL" in ROWS and not hasattr(orig_homes, "_splay"):                               # R-557: the splay cost in the contact-attitude choice (homes' own cost line + one term; recompiled in memory, the file untouched)
        import inspect, math as _m
        src = inspect.getsource(orig_homes); old = "+ 0.3 * (daz / 0.6) ** 2 + 0.2 * (dphi / 40) ** 2"; assert src.count(old) == 1, "homes' cost line moved"
        src = src.replace(old, old + " + _SPLAYC(rig, s, d0)").replace("def homes(", "def _homes_splay(", 1)
        def splay_cost(rig_, s_, d0_):
            sg = rig_.sg; A = s_["A"]
            if sg * float(A[0]) <= 0.25: return 0.0                                     # the stroke is not on this hand's far side of the kit
            inward = -sg * _m.degrees(_m.atan2(float(d0_[0]), -float(d0_[1])))
            return SPLAY_W * max(0.0, inward - 15.0) ** 2 / 100.0
        ns = SP.__dict__; ns["_SPLAYC"] = splay_cost; exec(compile(src, "<remedies: stroke_plan.homes + the R-557 splay term>", "exec"), ns); orig_homes = ns["_homes_splay"]; orig_homes._splay = True
    def homes(rig, grip, S):
        out = orig_homes(rig, grip, S)
        for s_ in S:
            p_ = s_.get("probe") or {}; GRIPDIAG["homes"]["strokes"] += 1
            if p_.get("ellipse", 0) > 1.0: GRIPDIAG["homes"]["home outside the wrist ellipse"] += 1
        GRIPDIAG["report"][S[0].get("_hand") if S else "?"] = getattr(grip, "report", {})
        return out
    homes._remedy = True; homes._orig = orig_homes; SP.homes = homes
    orig_tip = SP.tip_plan if not hasattr(SP.tip_plan, "_remedy") else SP.tip_plan._orig
    def tip_plan(S, N, lead, beat_s, DP, kit):
        T = orig_tip(S, N, lead, beat_s, DP, kit)
        if not S or not (BOOST or ("S1" in ROWS and SWEEP_IDS)): return T
        h = S[0].get("_hand"); t = np.arange(N) / 120.0; add = np.zeros(N)
        bt = BOOST.get((h, "tail", None))
        if bt and bt.get("wait"):                                                        # T1: the rest after the limb's last stroke (tip_plan aims it at a phantom stroke on the same piece 3 s later)
            w0 = S[-1].get("t_end", S[-1]["t"]) + 0.08; u = np.clip((t - w0) / 0.20, 0, 1); add += bt["wait"] * u * u * (3 - 2 * u); REG[(h, "tail", None, "wait")] = [round(w0, 3), round(float(t[-1]), 3)]
        for j, b in enumerate(S):
            if "S1" in ROWS and j > 0 and b["piece"] != S[j - 1]["piece"] and set(b.get("ids") or ()) & SWEEP_IDS and set(S[j - 1].get("ids") or ()) & SWEEP_IDS and (h, round(b["t"], 3), b["piece"]) not in SWEEP_VETO:
                m = (T["ib"] == j) & (T["u"] > 0) & (T["u"] < 1); add[m] += SWEEP_ARC * np.sin(np.pi * T["u"][m])          # S1 (R-551): inside a sweep, every move to the next drum rides an arc over the rims
                if m.any(): REG[(h, round(b["t"], 3), b["piece"], "sweep")] = [round(float(t[m].min()), 3), round(float(t[m].max()), 3)]
            bo = BOOST.get((h, round(b["t"], 3), b["piece"]))
            if not bo: continue
            a = S[j - 1] if j > 0 else None; ta = a["t_end"] if a is not None else b["t"] - 2.0; Td = DP.down_t(b["vel"])
            lw = bo.get("wait", 0.0) - bo.get("drop", 0.0)
            if lw:                                                                       # W1: a smooth lift over the waiting part of the gap (W2: the same shape, downward)
                w0, w1 = ta + 0.08, b["t"] - Td - 0.06
                if w1 - w0 > 0.06:
                    u = np.clip((t - w0) / (w1 - w0), 0, 1); m = (t >= w0) & (t <= w1); add[m] += lw * np.sin(np.pi * u[m]) ** 2; REG[(h, round(b["t"], 3), b["piece"], "wait" if lw > 0 else "drop")] = [round(w0, 3), round(w1, 3)]
            if bo.get("over"):                                                           # P2: rise first, then travel over (an early-peaking hump: up, then in, then down onto b)
                m = (T["ib"] == j) & (T["u"] > 0) & (T["u"] < 1); add[m] += bo["over"] * np.sin(np.pi * T["u"][m] ** 0.4)
                if m.any(): REG[(h, round(b["t"], 3), b["piece"], "over")] = [round(float(t[m].min()), 3), round(float(t[m].max()), 3)]
            if bo.get("arc"):                                                            # P1: a higher arc on the travel into b
                m = (T["ib"] == j) & (T["u"] > 0) & (T["u"] < 1); add[m] += bo["arc"] * 4 * T["u"][m] * (1 - T["u"][m])
                if m.any(): REG[(h, round(b["t"], 3), b["piece"], "arc")] = [round(float(t[m].min()), 3), round(float(t[m].max()), 3)]
        T["h"] = T["h"] + add; return T
    tip_plan._remedy = True; tip_plan._orig = orig_tip; SP.tip_plan = tip_plan
    orig_targets = R2.targets if not hasattr(R2.targets, "_remedy") else R2.targets._orig
    def targets(*a, **k):
        d = orig_targets(*a, **k)
        for hh in "LR":
            for s in d["S"][hh]: s["_hand"] = hh
        return d
    targets._remedy = True; targets._orig = orig_targets; R2.targets = targets
    orig_near = R2.Ladder.nearest if not hasattr(R2.Ladder.nearest, "_remedy") else R2.Ladder.nearest._orig
    def nearest(self, n, h, piece0, zone0):
        if "S0" in ROWS and n.get("id") in SWEEP_IDS: return None                     # S0 (R-551): no nearest-piece substitution inside a sweep (re-deal, softer or cut)
        return orig_near(self, n, h, piece0, zone0)
    nearest._remedy = True; nearest._orig = orig_near; R2.Ladder.nearest = nearest
    orig_nearest_d = orig_near
    def nearest_d(self, n, h, piece0, zone0):
        if "D558" in ROWS: return None                                                  # R-558: never offered at R-448's early step (easy spans: never; hard spans: only as the last resort, in step_down)
        return nearest(self, n, h, piece0, zone0)
    nearest_d._remedy = True; nearest_d._orig = orig_near; R2.Ladder.nearest = nearest_d
    orig_sd = R2.step_down if not hasattr(R2.step_down, "_remedy") else R2.step_down._orig
    def step_down(n, limit, log, n_frames, check, stage="loop", lad=None):
        st = n["_state"]
        if "D558" in ROWS and st.get("late_sub"):                                       # the substitute was charged too: cut
            st.update(step=3, pre=3); [st.pop(k, None) for k in ("piece_to", "zone_to", "note_to", "late_sub")]
            log.append(dict(id=n["id"], t=round(n["tc"], 4), bar=n.get("bar"), limb=n["limb"], piece=n.get("piece_was", n["piece"]), note=n.get("note_was", n["note"]), vel=n.get("vel_midi", n["vel"]), limit=limit, check=check, frames=n_frames, rule="h cut", stage=stage)); return
        if "D558" in ROWS and lad is not None and n.get("id") in HARD_IDS and st.get("pre", 0) >= 1:
            nxt = st.get("step", 0) + 1; nxt = 3 if (nxt == 2 and not n.get("art")) else nxt
            if nxt >= 3 and lad.eligible(n):                                             # R-558, a hard span: the nearest drum as the LAST resort before the cut
                h0 = st.get("hand0") or n["limb"]; piece0 = n.get("piece_was", n["piece"]); zone0 = n.get("zone_was", n["zone"]); b = orig_nearest_d(lad, n, h0, piece0, zone0)
                if b:
                    st.update(step=0, pre=2, piece_to=b[1], zone_to=b[2], note_to=b[3], late_sub=True)
                    log.append(dict(id=n["id"], t=round(n["tc"], 4), bar=n.get("bar"), limb=h0, piece=piece0, note=n.get("note_was", n["note"]), vel=n.get("vel_midi", n["vel"]), limit=limit, check=check, frames=n_frames,
                                    rule=f"b nearest reachable piece: {b[1]} (R-448, last resort in a hard span, R-558)", stage=stage)); return
        return orig_sd(n, limit, log, n_frames, check, stage=stage, lad=lad)
    step_down._remedy = True; step_down._orig = orig_sd; R2.step_down = step_down
    orig_p = SP._plan if not hasattr(SP._plan, "_remedy") else SP._plan._orig; orig_plan = SP.plan if not hasattr(SP.plan, "_remedy") else SP.plan._orig; first = {"on": False}
    def plan(*a, **k):
        g_ = k.get("grip"); S_ = a[1] if len(a) > 1 else k.get("S")
        if g_ is not None and S_: GRIPDIAG["report"][S_[0].get("_hand", "?")] = getattr(g_, "report", {})       # the finger fit of the grip this hand plays with
        first["on"] = True
        try: return orig_plan(*a, **k)
        finally: first["on"] = False
    def _plan(rig, grip, S, T, N, *a, **k):
        h = S[0].get("_hand") if S else None; t = T["t"]; hi = SP.CFG["limits"]["stick_alpha"]["hard"][1]
        keys = [(h, round(s_["t"], 3), s_["piece"]) for s_ in S]
        def extras(auto=True):
            e = {}
            for j, key in enumerate(keys):
                bo = BOOST.get(key, {})
                if bo.get("veto"): continue
                x = max(bo.get("arm", 0.0), AUTO.get(key, 0.0) if auto else 0.0)
                if x: e[j] = x
            return e
        def run(e):
            base0 = SP.G["arm_share"]
            if e:                                                                        # A1: the arm carries more of THESE strokes' lift (a per-frame base share; the rig's formula and smoothing unchanged)
                arr = np.full(N, float(base0["base"]))
                for j, x in e.items():
                    b = S[j]; m = (T["ib"] == j) & (t >= b["t"] - 0.30) & (t <= b["t"] + 0.02); arr[m] += x; REG[(h, keys[j][1], keys[j][2], "arm")] = [round(b["t"] - 0.30, 3), round(b["t"] + 0.02, 3)]
                SP.G["arm_share"] = dict(base0, base=np.minimum(arr, ARM_MAX))
            try: return orig_p(rig, grip, S, T, N, *a, **k)
            finally: SP.G["arm_share"] = base0
        if not (first["on"] and h): return run(extras())
        first["on"] = False; out = run(extras(auto=False))                              # the first plan without the in-plan accent: what the cone asks of each loud stroke
        kc = [int(c) for c in out["kc"]]; new = {}
        for j, s_ in enumerate(S):
            if s_["vel"] < LOUD_V or not (0 <= kc[j] < N): continue
            f0 = kc[j - 1] if j > 0 and 0 <= kc[j - 1] < N else max(0, kc[j] - 60); mx = float(out["alpha_free"][f0:kc[j] + 1].max())
            DIAG[keys[j]] = dict(vel=s_["vel"], gap=round(float(s_["t"] - (S[j - 1].get("t_end", S[j - 1]["t"]) if j else s_["t"] - 1.0)), 3), lift_plan_mm=round(1000 * LIFT_H(s_["vel"]) * s_.get("lift", 1.0), 1),
                                 alpha_free_max_deg=round(mx, 1), cone_scale=round(max(0.45, 0.93 * (hi - 1.0) / mx), 2) if mx > hi - 1.0 else 1.0, arm_extra=extras(auto=False).get(j, 0.0))
            if "A1p" in ROWS and not OFF and A1ON["on"] and mx > hi - 1.0 and not BOOST.get(keys[j], {}).get("veto"): new[keys[j]] = ARM_STEPS[-1]
        for kk in [kk for kk in AUTO if kk[0] == h and kk not in new]: AUTO.pop(kk)
        AUTO.update(new)
        if not new: return out
        for j, key in enumerate(keys):
            if key in DIAG: DIAG[key]["arm_extra"] = extras().get(j, 0.0)
        return run(extras())                                                             # A1p: the same first plan with the accent's arm share (plan() then runs its own S-GRIP-2 passes on it)
    _plan._remedy = True; _plan._orig = orig_p; SP._plan = _plan; plan._remedy = True; plan._orig = orig_plan; SP.plan = plan


def limb_of(v):
    if v["limb"] in ("L", "R"): return v["limb"]
    for p in v.get("pairs") or []:
        for hh in "LR":
            if f".{hh} " in p + " " or p.endswith(f".{hh}") or f"(arm {hh})" in p: return hh
    return None


def local(V, limb, f0, f1, ex=()):
    """frames over a hard limit for `limb` (or unattributed) within the window, and their kinds (ex: excused runs (limb, f0, f1, kinds), left out: a baseline never counts what a reverted remedy broke)"""
    n = 0; kinds = set()
    for v in V:
        lb = limb_of(v)
        if lb not in (limb, None): continue
        k = sum(1 for f in v["frames"] if f0 <= f <= f1 and not any(same_limb(lb, e[0]) and e[1] <= f <= e[2] and v["limit"] in e[3] for e in ex))
        if k: n += k; kinds.add(v["limit"])
    return n, kinds


CYMBALS = ("ride", "crash", "hat")


def pose_of(path):
    """the solve's stick tips (120 Hz) and the kit's cymbal planes -> for W2's 'is the stick under the cymbal it hits?'"""
    try:
        D = json.load(open(path)); P = {p["id"]: (np.array(p["c"], float), np.array(p["n"], float)) for p in D["kit"]["pieces"] if p["id"] in CYMBALS}
        return dict(tip={h: np.asarray(D["arms"][h]["stick"]["tip"], float) for h in "LR"}, cym=P)
    except Exception: return None


def under_cymbal(PO, limb, f0, f1, v):
    """the colliding cymbal, if the stick's tip is below its plane at the middle of the run (lifting would push the stick into it from below)"""
    if not PO: return None
    for pr in v.get("pairs") or []:
        a = pr.split(" (")[0].split(" x ")
        if len(a) != 2 or f"stick.{limb}" not in a: continue
        cid = a[1] if a[0] == f"stick.{limb}" else a[0]
        if cid in PO["cym"]:
            c, n = PO["cym"][cid]; tp = PO["tip"][limb][max(0, f0):min(f1, len(PO["tip"][limb]) - 1) + 1]
            if len(tp) and float(((tp - c) @ n).min()) < 0.005: return cid               # the tip at or below the cymbal's plane during the run: it meets the cymbal from below
    return None


def strokes_of(path):
    """the solve's per-stroke stats (fullbody: lift_mm, tip_speed_m_s, share, gap_s) -> {hand: [stroke]}"""
    try: D = json.load(open(path)); return {h: D["arms"][h].get("strokes") or [] for h in "LR"}
    except Exception: return {"L": [], "R": []}


def stat_of(ST, h, s):
    c = [x for x in ST.get(h, []) if abs(x["t"] - s["t"]) < 0.01 and x["piece"] == s["piece"]]; return c[0] if c else None


def runs_of(V):
    """every run of frames over a hard limit -> (limb or None, kind, f0, f1)"""
    out = []
    for v in V:
        fr = np.array(sorted(v["frames"])); lb = v["limb"] if v["limb"] in ("LF", "RF") else limb_of(v)
        for r in np.split(fr, np.nonzero(np.diff(fr) > 12)[0] + 1): out.append((lb, v["limit"], int(r[0]), int(r[-1])))
    return out


def same_limb(a, b): return a is None or b is None or a == b


def loop(R2, K, C, grips, ident, title, audio, state, log, DP, verbose=True, hook=None):
    """R2.loop with the remedy table in front of the ladder (its shape and stop rules kept; the cap is CAP or run2.MAX_IT)"""
    hist = []; pending = []; tried = collections.defaultdict(list); stats = collections.Counter(); HZ = R2.HZ; cap = CAP if CAP is not None else R2.MAX_IT
    GUARD = "G" in ROWS and not OFF; prev_runs = []; last_changed = []                    # round 3: the churn guard
    phase = "geometry"; A1ON["on"] = False                                               # A1p: "accent" once the geometry is clean; there a violation only ever vetoes accents, never costs a note
    for it in range(cap + 1):
        d = R2.shift_table(K, C, state, log, DP, redeal=R2.REDEAL)
        S = R2.solve(K, d, grips, ident, title, audio); V = R2.violations(S); miss = [r for r in S["rows"] if not r["ok"]]
        ST = strokes_of(INS["path"]) if INS.get("path") else {"L": [], "R": []}; PO = pose_of(INS["path"]) if INS.get("path") and ("W2" in ROWS or "P2" in ROWS) else None
        excused = []; n_rev = 0; cur_runs = runs_of(V)
        for rm in pending:                                                               # acceptance of last pass's remedies, on their own windows
            n1, k1 = local(V, rm["limb"], rm["f0"], rm["f1"]); keep = n1 < rm["n0"] and not (k1 - rm["k0"])
            if rm["what"] == "arm":                                                      # A1: the stroke got faster and its window got no worse
                x = stat_of(ST, rm["limb"], rm["stroke"]); sp1 = (x or {}).get("tip_speed_m_s") or 0.0; rm["speed1"] = sp1
                keep = sp1 >= 1.05 * rm["speed0"] and n1 <= rm["n0"] and not (k1 - rm["k0"])
            rm.update(n1=n1, kept=keep); stats[f"{rm['row']} {'kept' if keep else 'reverted'}"] += 1
            if not keep:
                cur = BOOST.get(rm["key"], {}); cur[rm["what"]] = rm["prev"]; BOOST[rm["key"]] = cur
                if GUARD: n_rev += 1                                                     # a reverted remedy forces one more solve (else the last solve would keep its geometry)
                if "D" in ROWS and not (k1 - rm["k0"]) and rm["what"] != "arm":            # D: the largest step did not clear it and broke nothing: a smaller one won't clear it either
                    for y in {"wait": WAIT_STEPS, "drop": WAIT_STEPS, "arc": ARC_STEPS, "over": ARC_STEPS + [0.09]}.get(rm["what"], []):
                        if y < rm["step_m"] and (rm["key"], rm["what"], y) not in tried[rm["key"]]: tried[rm["key"]].append((rm["key"], rm["what"], y))
                if GUARD and (k1 - rm["k0"]):
                    excused.append((rm["limb"], rm["f0"], rm["f1"], set(k1 - rm["k0"])))   # G1: the NEW kinds the reverted remedy broke in its own window are not charged to a note this pass
                    steps_ = {"wait": WAIT_STEPS, "drop": WAIT_STEPS, "arc": ARC_STEPS, "over": ARC_STEPS + [0.09], "arm": ARM_STEPS}.get(rm["what"], [])
                    for y in steps_:                                                     # G3: a larger step of the same row would break it harder: that row is done for this stroke (saves the passes)
                        if y > rm["step_m"] and (rm["key"], rm["what"], y) not in tried[rm["key"]]: tried[rm["key"]].append((rm["key"], rm["what"], y)); stats["guard G3 skipped a larger step"] += 1
        if GUARD and pending:                                                            # G2: a new run over a hard limit OUTSIDE every window changed last pass = churn: revert last pass's kept remedies
            wins = [(p_["limb"], p_["f0"], p_["f1"]) for p_ in pending] + last_changed
            new_out = [r for r in cur_runs if not any(same_limb(r[0], q[0]) and r[2] <= q[3] + 12 and q[2] <= r[3] + 12 for q in prev_runs)
                       and not any(same_limb(r[0], w[0]) and r[2] <= w[2] and w[1] <= r[3] for w in wins)]
            if new_out:
                stats["guard G2 fired"] += 1
                for rm in pending:
                    if rm.get("kept"):
                        cur = BOOST.get(rm["key"], {}); cur[rm["what"]] = rm["prev"]; BOOST[rm["key"]] = cur; rm["kept"] = False; n_rev += 1; stats[f"guard reverted {rm['row']}"] += 1
                        stats[f"{rm['row']} kept"] -= 1; stats[f"{rm['row']} reverted"] += 1
                excused += [(r[0], r[2], r[3], {r[1]}) for r in new_out]
        prev_runs = cur_runs; pending = []
        hist.append(dict(pass_=it, phys_frames=R2.phys(V), not_struck=len(miss), changes=0, solve_s=S["seconds"], plan_cuts=sum(1 for v_ in state.values() if isinstance(v_, dict) and v_.get("step", 0) >= 3),
                         a1p=sum(1 for k_ in AUTO if not BOOST.get(k_, {}).get("veto")), excused=len(excused)))
        if verbose: print(f"    pass {it}: over a hard limit {R2.phys(V)}, not struck {len(miss)}, {S['seconds']} s", flush=True)
        if hook: hook(it, S, d, hist)
        acc = []
        if "A1" in ROWS and not OFF and it < cap:                                       # A1 candidates: a loud stroke whose lift the cone cut and that came out short
            for hh in "LR":
                for s_ in d["S"][hh]:
                    key = (hh, round(s_["t"], 3), s_["piece"]); dg = DIAG.get(key); x = stat_of(ST, hh, s_)
                    if s_["vel"] < LOUD_V or not dg or dg["cone_scale"] >= 1.0 or not x or (x.get("lift_mm") or 0) >= LIFT_SHORT * 1000 * LIFT_H(s_["vel"]): continue
                    cur = BOOST.get(key, {}); prev = cur.get("arm", 0.0); nx = next((y for y in ARM_STEPS if y > prev + 1e-9 and (key, "arm", y) not in tried[key]), None)
                    if nx is not None: acc.append((key, s_, x, prev, nx))
        hist[-1]["phase"] = phase
        if phase == "accent" and (V or miss) and it == cap:                              # out of budget inside the accent phase: one more solve with every accent given back (= the converged clip)
            for k_ in list(AUTO): cur = BOOST.get(k_, {}); cur["veto"] = True; BOOST[k_] = cur
            stats["A1p all given back at the cap"] += 1; A1ON["on"] = False; S = R2.solve(K, d, grips, ident, title, audio); hist.append(dict(pass_=it + 1, phys_frames=R2.phys(R2.violations(S)), phase="restore")); return S, d, hist, stats, tried
        if phase == "accent" and (V or miss) and it < cap:                               # A1p's pass: give the accents near each failure back (the rest of the clip is the converged geometry)
            nv = 0
            for lb_, kind_, f0_, f1_ in cur_runs + [(r_["limb"], "sync", 4 * r_["frame"], 4 * r_["frame"]) for r_ in miss]:
                act = [k_ for k_ in AUTO if not BOOST.get(k_, {}).get("veto") and (lb_ is None or k_[0] == lb_)]
                hit = [k_ for k_ in act if f0_ / HZ - WIN <= k_[1] <= f1_ / HZ + WIN] or act
                for k_ in hit: cur = BOOST.get(k_, {}); cur["veto"] = True; BOOST[k_] = cur; stats["A1p veto"] += 1; nv += 1
            if nv: hist[-1]["changes"] = nv; continue
            phase = "geometry"; A1ON["on"] = False; stats["A1p fell back"] += 1                 # nothing left to give back: the normal loop takes over (never seen: all vetoed = the converged clip)
        if phase == "geometry" and not V and not miss and not acc and not n_rev and "A1p" in ROWS and not OFF and not A1ON["on"] and it < cap:
            phase = "accent"; A1ON["on"] = True; hist[-1]["changes"] = 0; continue          # the geometry converged: one more solve with the accents
        if (not V and not miss and not acc and not n_rev) or it == cap: return S, d, hist, stats, tried
        notes = {n["id"]: n for n in d["notes_all"] if n["limb"] and 0 <= n["tc"] < C["dur"] + 0.5 and not n.get("merged")}; done = set(); ch = 0; unresolved = []
        for n in notes.values(): n["_state"] = state.setdefault(n["id"], dict(step=0))
        lad = R2.Ladder(K, d) if R2.REDEAL else None
        strokes = {hh: sorted(d["S"][hh], key=lambda s: s["t"]) for hh in "LR"}
        for key, s_, x, prev, nx in acc:                                                 # A1: apply (acceptance next pass, on the stroke's speed and its window)
            tried[key].append((key, "arm", nx)); cur = BOOST.get(key, {}); cur["arm"] = nx; BOOST[key] = cur; f = int(round(s_["t"] * HZ)); w0, w1 = max(0, int(f - WIN * HZ)), int(f + WIN * HZ); n0, k0 = local(V, key[0], w0, w1)
            pending.append(dict(row="A1 arm-assisted accent", what="arm", key=key, prev=prev, limb=key[0], f0=w0, f1=w1, n0=n0, k0=k0, step_m=nx, t=round(s_["t"], 3), stroke=s_, speed0=x.get("tip_speed_m_s") or 0.0))
            stats["A1 arm-assisted accent tried"] += 1
        def remedy(limb, f0, f1, v):
            """try the next untried remedy row for this collision -> True if one was applied"""
            nonlocal ch
            if limb not in ("L", "R"): return False
            tm = 0.5 * (f0 + f1) / HZ; S_ = strokes[limb]
            if not S_: return False
            nxt = next((s for s in S_ if s["t"] >= tm - 1e-6), None)
            near = min((abs(s["t"] - tm) for s in S_), default=9.0) < NEAR_STROKE or min((abs(s["t"] - f0 / HZ) for s in S_), default=9.0) < NEAR_STROKE
            if nxt is None and not near and "T1" in ROWS:                               # T1: after the limb's last stroke there is no gap into a stroke: lift the tail rest itself
                key = (limb, "tail", None); what, steps, row = "wait", WAIT_STEPS, "T1 lift the tail rest"
            else:
                nxt = nxt or S_[-1]; key = (limb, round(nxt["t"], 3), nxt["piece"]); what, steps, row = ("arc", ARC_STEPS, "P1 raise the arc") if near else ("wait", WAIT_STEPS, "W1 lift the waiting stick")
                cid = under_cymbal(PO, limb, f0, f1, v) if ("W2" in ROWS or "P2" in ROWS) else None
                p1_left = near and any((key, "arc", x) not in tried[key] and x > BOOST.get(key, {}).get("arc", 0.0) + 1e-9 for x in ARC_STEPS)
                if cid and nxt["piece"] == cid and "P2" in ROWS and not ("G" in ROWS and p1_left): what, steps, row = "over", ARC_STEPS + [0.09], "P2 rise first, then over"       # travelling INTO that cymbal from below its rim (round 3: after P1 when the stroke is near)
                elif cid and not near and "W2" in ROWS: what, row = "drop", "W2 lower the stick under a cymbal"                                  # waiting under it: lifting would push the stick into it
                if row[:2] not in ROWS: return False
            cur = BOOST.get(key, {}); prev = cur.get(what, 0.0); order = sorted(steps, reverse=True) if "D" in ROWS else steps   # D (round 3): the largest step first, smaller ones only if it broke something new
            nxt_step = next((x for x in order if x > prev + 1e-9 and (key, what, x) not in tried[key]), None)
            if nxt_step is None: return False
            tried[key].append((key, what, nxt_step)); cur[what] = nxt_step; BOOST[key] = cur
            w0, w1 = max(0, int(f0 - WIN * HZ)), int(f1 + WIN * HZ); n0, k0 = local(V, limb, w0, w1, excused)
            pending.append(dict(row=row, what=what, key=key, prev=prev, limb=limb, f0=w0, f1=w1, n0=n0, k0=k0, step_m=nxt_step, t=round(tm, 3)))
            stats[f"{row} tried"] += 1; ch += 1; return True
        def veto_a1(limb, f0, f1):
            """A1p first: an accent (in-plan or A1) of this limb whose stroke is at or just after the run gives way (vetoed for the clip) before any other row or a note"""
            nonlocal ch
            if limb not in ("L", "R"): return False
            hit = [k_ for k_ in set(AUTO) | {k_ for k_, b_ in BOOST.items() if b_.get("arm")} if k_[0] == limb and isinstance(k_[1], float) and not BOOST.get(k_, {}).get("veto") and f0 / HZ - 0.10 <= k_[1] <= f1 / HZ + 0.35]
            for k_ in hit: cur = BOOST.get(k_, {}); cur["veto"] = True; BOOST[k_] = cur; stats["A1p veto"] += 1
            if hit: ch += 1
            return bool(hit)
        def pay(limbs, f0, f1, limit, check, nfr):
            nonlocal ch
            tm = 0.5 * (f0 + f1) / HZ; cand = [n for n in notes.values() if n["limb"] in limbs and not (n.get("art", {}).get("kind") == "sweep" and n["art"]["i"] > 0) and n["id"] not in done and n["_state"]["step"] < 3]
            if not cand: unresolved.append(dict(limit=limit, check=check, frames=[f0, f1], n=nfr)); return
            n = min(cand, key=lambda n: (abs(n["tc"] - tm) if not (f0 / HZ - 0.02 <= n["tc"] <= f1 / HZ + 0.02) else 0.0, n["vel"]))
            if not (f0 / HZ - 0.4 <= n["tc"] <= f1 / HZ + 0.4): unresolved.append(dict(limit=limit, check=check, frames=[f0, f1], n=nfr)); return
            done.add(n["id"]); R2.step_down(n, limit, log, nfr, check, lad=lad); ch += 1; changed.append((n["limb"] if n["limb"] in ("L", "R", "LF", "RF") else None, int(n["tc"] * HZ - WIN * HZ), int(n["tc"] * HZ + WIN * HZ)))
        changed = []
        for v in V:
            fr = np.array(sorted(v["frames"])); limbs = (v["limb"],) if v["limb"] else ("L", "R")
            if v["limb"] is None and v.get("pairs") and all(("thigh" in p or "shin" in p) and "stick" not in p for p in v["pairs"]): limbs = ("LF", "RF")
            for run in np.split(fr, np.nonzero(np.diff(fr) > 12)[0] + 1):
                f0, f1 = int(run[0]), int(run[-1]); lb0 = v["limb"] if v["limb"] in ("LF", "RF") else limb_of(v)
                if excused and any(same_limb(lb0, e[0]) and f0 <= e[2] and e[1] <= f1 and v["limit"] in e[3] for e in excused): stats["guard excused run"] += 1; continue
                if "S1" in ROWS and v["limit"] != "collision" and lb0 in ("L", "R"):     # S1's arc broke a speed, continuity, end-point or joint limit: give that arc back (the arc is ours, never the note's fault)
                    arcs = [k_ for k_, r_ in REG.items() if k_[3] == "sweep" and k_[0] == lb0 and (k_[0], k_[1], k_[2]) not in SWEEP_VETO and r_[0] * HZ - 6 <= f1 and f0 <= r_[1] * HZ + 6]
                    if arcs:
                        for k_ in arcs: SWEEP_VETO.add((k_[0], k_[1], k_[2])); stats["S1 arc given back"] += 1
                        ch += 1; continue

                if v["limit"] == "collision" and not OFF:
                    lb = limb_of(v)
                    if remedy(lb, f0, f1, v): continue                                   # geometry first: a remedy row, not a note
                    if lb in ("L", "R"): limbs = (lb,)
                pay(limbs, f0, f1, v["limit"], v["check"], int(len(run)))
        for r in miss: pay((r["limb"],), 4 * r["frame"], 4 * r["frame"], "not struck on its frame", "sync", 1)
        for nid in [k for k, v_ in state.items() if isinstance(v_, dict) and v_.get("step", 0) == 0 and not v_.get("pre")]: state.pop(nid)
        for n in notes.values(): n.pop("_state", None)
        ch += len(acc) + n_rev; last_changed = changed; hist[-1]["changes"] = ch; hist[-1]["unresolved"] = unresolved; hist[-1]["remedies"] = [dict(row=p["row"], t=p["t"], limb=p["limb"], step_m=p["step_m"]) for p in pending]
        if ch == 0: return S, d, hist, stats, tried
    return S, d, hist, stats, tried


def judged(R2, MD, JG, C, d, log, hist, src, clip, cdir):
    """fates + the inspector dataset at `src` -> body_<clip>.json, measured and judged -> (J, fate counts, rows)"""
    import copy
    cnt, rows = R2.fates(C, d, copy.deepcopy(log)); raw = {n["id"]: n["tc"] for n in C["notes"]}
    for r in rows: r["t_snap"] = r["t"]; r["t"] = round(raw[r["midi"]], 5)
    D = json.load(open(src)); D.update(hits=R2.hits_of(rows), fate_rows=rows, loop_log=log, loop=hist, mode="played"); dst = bench.SCR / f"inspector/data/drums2/body_{clip}.json"
    json.dump(D, open(dst, "w"), separators=(",", ":"), default=lambda x: x.tolist() if hasattr(x, "tolist") else str(x))
    if (cdir / f"contacts_drums_{clip}.json").exists(): os.replace(cdir / f"contacts_drums_{clip}.json", cdir / f"contacts_drums_{clip}.prev")
    Jm = MD.measure(clip, cdir)
    if GRID.get("bpb"): Jm["grid"].update(GRID)                                         # round 4: the page's bar lines and bar.beat in the window's own meter (measure_drums writes bpb 4)
    if JUDGE_V == "v2":
        import judge_v2; return judge_v2.add_habits(judge_v2.add_splay(judge_v2.judge(Jm), D), D), cnt, rows
    return JG.judge(Jm), cnt, rows


def one(key, tag="v006", midi=None, bars=None, bpb=4.0, preset=None, deal="beam", deal_terms=None, window=None):
    """LIBRARY: the lab's one(key, tag) with the window read from params, not work/windows.json. midi = the source MIDI file; bars = (first, last) real bar, 1-based, both inclusive;
    bpb = quarter notes per bar (3/4 -> 3, 6/8 -> 3, 5/4 -> 5; 4/4 -> 4); preset = the kit (drumkit.yaml preset; default the adopted PRESET); deal = "beam" (adopted) | "dp" (planner v2, NOT adopted).
    Writes OUT/judgement_<key>_<tag>.json and leaves the 120 Hz inspector dataset at bench.SCR/inspector/data/drums2/body_remedy_<key>_<tag>.json (INS['path'])."""
    global GRIP_DEG, ELBOW_K, PRESET
    import re
    mg = re.search(r"g(\d+)(e?)$", tag)                                                   # round 4, item C: a grip test named in its tag (v009g25 = the stick 25 deg across the palm; a trailing e = elbows pulled down, prior x 0.6)
    if mg: GRIP_DEG = GRIP_DEG or mg.group(1); ELBOW_K = ELBOW_K or ("0.6" if mg.group(2) else None)
    if preset: PRESET = preset
    W = dict(window or {}, key=key, bpb=bpb, b0=bars[0], b1=bars[1]); OUT.mkdir(parents=True, exist_ok=True); t0 = time.time(); bpb = float(W.get("bpb", 4))
    o = OUT / f"judgement_{key}_{tag}.json"; assert not o.exists(), f"{o} exists: versions only go up"
    import run2 as R2, kitdata, chart2, measure_drums as MD, judge as JG, plan_faults as PF
    GRIPDIAG["homes"].clear(); GRIPDIAG["report"].clear(); install(R2); BOOST.clear(); DIAG.clear(); AUTO.clear(); REG.clear(); GRID.clear(); SWEEP_IDS.clear(); SWEEP_VETO.clear(); HARD_IDS.clear()
    mid = bench.SCR / f"remedy_midi/{key}.mid"; rm = bench.remap(pathlib.Path(midi), W["b0"], W["b1"], mid, bpb=bpb)
    vb = (rm["b0"], rm["b1"]) if bpb == 4 else (1 + (rm["b0"] - 1) * bpb / 4, rm["b1"] * bpb / 4)   # chart2 counts 4-quarter bars: a window in real bars of another meter is passed as fractional 4/4 bars (same span)
    K = kitdata.load(PRESET); HPT = next((x for x in ("HPA1", "HPA2", "HPB1", "HPB2", "HPAB", "HPB2c") if x in ROWS), None)
    if HPT:
        import hand_pref; hand_pref.install(chart2, K, HPT, bpb * rm["tpb"])            # round 5 (R-556): a hand-preference hypothesis as an added deal cost
    if deal == "dp":                                                                    # planner v2's exact DP deal (NOT adopted; deal_dp.py), in memory
        import deal_dp; deal_dp.install(chart2, deal_terms or {}); deal_dp.set_grid(pathlib.Path(midi), bpb)
    C = chart2.build(K, vb, mid=mid); DP = R2.drum_perf(K)
    if bpb != 4: GRID.update(bpb=bpb, bar0=rm["b0"], meter=W.get("meter"))
    if "D558" in ROWS:
        import difficulty as DFC
        HARD_IDS.update(DFC.hard_ids([dict(t=n["tc"], piece=n.get("piece"), limb=n.get("limb"), vel=n.get("vel", 0), id=n["id"]) for n in C["notes"]], C["bar_s"] / 4))
    if "S0" in ROWS or "S1" in ROWS:
        import sweeps as SWP
        for run in SWP.find([dict(t=n["tc"], row=n["piece"], id=n["id"]) for n in C["notes"] if n.get("piece") and n.get("limb") in ("L", "R")], C["bar_s"] / 4): SWEEP_IDS.update(x["id"] for x in run)
    clip = f"remedy_{key}_{tag}"; ins = bench.SCR / f"inspector/data/drums2/body_{clip}.json"; ins.parent.mkdir(parents=True, exist_ok=True); orig = R2.solve
    R2.solve = lambda K_, d, g, i, t, a, paths=None, write_render=None, verbose=False: orig(K_, d, g, i, t, a, paths=dict(drive="/dev/null", inspector=ins), write_render=None, verbose=verbose)
    INS["path"] = ins; MD.LAB = bench.SCR; cdir = bench.SCR / "remedy_contacts"; per_pass = []
    def hook(it, S_, d_, hist_):                                                         # the cap sweep: pass k judged = the run with cap k (the loop is deterministic; the cap only stops it)
        if JUDGE_FROM is None or it < JUDGE_FROM: return
        Jp, _, _ = judged(R2, MD, JG, C, d_, log, hist_, ins, f"{clip}_p{it}", cdir); Ap = Jp["tally"]["all"]; mp = R2.metrics(S_, d_)
        json.dump(Jp, open(OUT / f"judgement_{key}_{tag}_cap{it}.json", "w"), indent=0, default=lambda x: x.tolist() if hasattr(x, "tolist") else str(x))     # this pass's judgement = the run with cap `it`
        per_pass.append(dict(cap=it, played_pct=Ap["accuracy_pct"], collision_cuts=Ap["missed_by"].get("collision", 0), softer=Ap["softer"], hard_frames=mp["phys_frames_total"], collisions=mp["collisions"], phys=R2.phys(R2.violations(S_))))
        print(f"      cap {it}: played {Ap['accuracy_pct']} %, hard frames in the played clip {mp['phys_frames_total']} {mp['collisions']}", flush=True)
    state = {}; log = []; S, d, hist, stats, tried = loop(R2, K, C, dict(K.GRIP), clip, clip, "none.opus", state, log, DP, verbose=True, hook=hook)
    m = R2.metrics(S, d); J, cnt, rows = judged(R2, MD, JG, C, d, log, hist, ins, clip, cdir)
    A = J["tally"]["all"]; mb = A["missed_by"]
    J["remedy"] = dict(key=key, tag=tag, control=OFF, preset=PRESET, passes=len(hist), seconds=round(time.time() - t0, 1), fate=cnt, stats=dict(stats), boosts_kept={f"{k[0]} {k[1]} {k[2]}": v for k, v in BOOST.items() if any(v.values())},
                       loop=[{k: v for k, v in h.items() if k != "where"} for h in hist], played_pct=A["accuracy_pct"], collision_cuts=mb.get("collision", 0), hand_shift=mb.get("hand shift time", 0),
                       played_clip_hard_frames=m["phys_frames_total"], played_clip_collisions=m["collisions"], freezes=PF.freezes(J), crossed=PF.crossed(J, "R"), window=W,
                       rows=sorted(ROWS), cap=CAP if CAP is not None else R2.MAX_IT, per_pass=per_pass, cone={f"{k[0]} {k[1]} {k[2]}": v for k, v in DIAG.items()},
                       strokes=strokes_of(ins), auto_a1={f"{k[0]} {k[1]} {k[2]}": v for k, v in AUTO.items() if not BOOST.get(k, {}).get("veto")},
                       vetoed=[f"{k[0]} {k[1]} {k[2]}" for k, v in BOOST.items() if v.get("veto")], sweep_ids=sorted(SWEEP_IDS), hard_ids=sorted(HARD_IDS), sweep_arcs_given_back=sorted(f"{k[0]} {k[1]} {k[2]}" for k in SWEEP_VETO),
                       grip=dict(stick_in_hand_deg=GRIP_DEG or 60, head_point=HEAD_PT or "rig.yaml", elbow_k=ELBOW_K or 1, homes=dict(GRIPDIAG["homes"]), finger_fit=GRIPDIAG["report"]), judge=JUDGE_V, grid_override=dict(GRID), hand_pref=(dict(token=HPT, **__import__("hand_pref").ARMS[HPT], stats=dict(__import__("hand_pref").S["stats"])) if HPT else None), regions={f"{k[0]} {k[1]} {k[2]} {k[3]}": v for k, v in REG.items()})
    json.dump(J, open(o, "w"), indent=0, default=lambda x: x.tolist() if hasattr(x, "tolist") else str(x))          # the inspector dataset stays in the scratchpad (body_remedy_<key>_<tag>.json): verify/export.py remedy <key> <tag> reads it
    R = J["remedy"]; print(f"{key} {tag}: played {R['played_pct']} % · collision cuts {R['collision_cuts']} · freezes {len(R['freezes'])} · crossed {len(R['crossed'])} · hard frames left {R['played_clip_hard_frames']} · passes {R['passes']} · {R['seconds']} s · {dict(stats)}", flush=True)
