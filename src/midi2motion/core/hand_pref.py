# LIBRARY COPY of drum-benchmark/tools/hand_pref.py (nelvids lab, 2026-11-2x), packaged in midi2motion (vendored from the nelvids drums library): analysis-only functions and the lab's CLI dropped, lab paths -> rigenv.
#!/usr/bin/env python3
"""hand_pref.py: round 5 (R-556) hand-preference HYPOTHESES as extra costs in the deal (chart2.stick's beam search), installed in memory: the wrapped function's own
source is read and re-compiled with ONE added term (`+ _HP(n, h, st, t)` on its per-note hand cost line); the file is never edited or copied to disk. Every existing cost
(the kit's per-piece reach preference K.PREF, speed, R-441 shift time, crossing) stays as it is.

    import hand_pref; hand_pref.install(chart2, K, arm="A1", bar_ticks=..)     (remedies.one does this when REMEDY_ROWS names HPA1, HPA2, HPB1, HPB2 or HPAB)

PREFERRED HAND (both arms): the drummer's lead hand (K.LEAD) for the hi-hat, the ride, the crash, and a fill's entry (the first tom note after >= 0.5 s without one). The
snare has none: a left backbeat under a right-hand ostinato is normal.
ARM A, density (the author's first idea, was R-555): a light preference (w_pref for the weak hand on a preferred piece) + a HAND-CHANGE cost: when the other hand was the
last to play this piece within 0.5 s, the stroke pays w_chg x the piece's density (its notes per second in a 1 s window around the note): a hat or ride ostinato pays a lot to
switch hands, a lone crash little.
ARM B, groove bias (his second idea): the weak hand on a preferred piece pays w_bias in a groove bar, and 10 % of it where the other hand is tolerated:
  in a FILL BAR (found per bar from the music, listen_select's fill score: tom notes + snare notes beyond the window's median per bar >= 2), on an ACCENT (velocity >= 1.2 x
  and >= 12 above the median of that piece's notes in the previous 1 s, at least 2 of them), or in an ORNAMENT (R-527's rules: a flam or drag grace 15-60 ms before a
  louder (>= 1.25 x) main note, both notes; a roll, >= 3 notes on one piece each < 45 ms apart).
ARM AB: A's two costs, scaled down to 10 % in the same three places.
"""
import collections, inspect, sys
sys.dont_write_bytecode = True
ARMS = {"HPA1": dict(arm="A", w_pref=1.0, w_chg=0.25), "HPA2": dict(arm="A", w_pref=2.0, w_chg=1.0), "HPB1": dict(arm="B", w_bias=3.0), "HPB2": dict(arm="B", w_bias=8.0),
        "HPAB": dict(arm="AB", w_pref=2.0, w_chg=1.0),
        "HPB2c": dict(arm="B", w_bias=8.0, bounce_fix=True)}      # round 6 (R-574): arm B with bounces taken out of its fill test (not run yet)
PREF_PIECES = ("hat", "ride", "crash"); TOMS = ("tom1", "tom2", "tom3", "floor", "floor2")
S = dict(cfg=None, lead="R", times={}, fill_bars=set(), relax=set(), entry=set(), bar_ticks=1920, stats=collections.Counter())


def prepare(N, spt, K):
    """per call of the deal: the hand pieces' note times (density), fill bars, accents, ornaments and fill entries, from the window's MIDI"""
    S["lead"] = K.LEAD; hand = []
    for n in N:
        m = K.NOTE_MAP.get(n["note"])
        if m and m[2] == "hand": hand.append((n["tick"] * spt, m[0], n["vel"], n))
    hand.sort(key=lambda x: x[0]); S["times"] = collections.defaultdict(list)
    for t, p, v, n in hand: S["times"][p].append(t)
    bt = S["bar_ticks"]; per = collections.defaultdict(collections.Counter)
    bnc = set()
    if (S["cfg"] or {}).get("bounce_fix"):                                              # R-574: fast flat-or-decaying repeats on one piece are a bounce, never a fill
        byp = collections.defaultdict(list)
        for x in hand: byp[x[1]].append(x)
        for p, L in byp.items():
            run = [L[0]]
            for a, b in zip(L, L[1:]):
                if b[0] - a[0] <= 0.120 and b[2] <= max(1.10 * a[2], a[2] + 8): run.append(b); continue
                if len(run) >= 2: bnc.update(id(x[3]) for x in run)
                run = [b]
            if len(run) >= 2: bnc.update(id(x[3]) for x in run)
    for t, p, v, n in hand:
        if id(n) in bnc: continue
        b = n["tick"] // bt; per[b]["tom"] += p in TOMS; per[b]["sn"] += p == "snare"
    med = sorted(per[b]["sn"] for b in per)[len(per) // 2] if per else 0
    S["fill_bars"] = {b for b in per if per[b]["tom"] + max(0, per[b]["sn"] - med) >= 2}
    relax = set(); last_tom = -9.0; entry = set()
    for i, (t, p, v, n) in enumerate(hand):
        prev = [x[2] for x in hand[:i] if x[1] == p and t - 1.0 <= x[0] < t]
        if len(prev) >= 2:
            md = sorted(prev)[len(prev) // 2]
            if v >= 1.2 * md and v - md >= 12: relax.add(id(n)); S["stats"]["accents"] += 1
        for t2, p2, v2, n2 in hand[i + 1:]:
            if t2 - t > 0.060: break
            if t2 - t >= 0.015 and v2 >= 1.25 * v: relax.update((id(n), id(n2))); S["stats"]["flam/drag notes"] += 2
        if p in TOMS:
            if t - last_tom >= 0.5: entry.add(id(n))
            last_tom = t
    for p, ts in S["times"].items():                                                    # rolls: >= 3 notes on one piece < 45 ms apart
        run = [0]
        for k in range(1, len(ts) + 1):
            if k < len(ts) and ts[k] - ts[k - 1] < 0.045: run.append(k); continue
            if len(run) >= 3:
                for x in hand:
                    if x[1] == p and ts[run[0]] - 1e-6 <= x[0] <= ts[run[-1]] + 1e-6: relax.add(id(x[3]))
            run = [k]
    S["relax"] = relax; S["entry"] = entry; S["fill_ticks"] = None


def dens(p, t):
    ts = S["times"].get(p, []); return sum(1 for x in ts if t - 0.5 <= x <= t + 0.5) / 1.0


def cost(n, h, st, t):
    cfg = S["cfg"]; p = n["piece"]; o = "L" if h == "R" else "R"; weak = h != S["lead"]
    pref = p in PREF_PIECES or id(n) in S["entry"]; relaxed = id(n) in S["relax"] or (n["tick"] // S["bar_ticks"]) in S["fill_bars"]; c = 0.0
    if cfg["arm"] in ("A", "AB"):
        a = 0.0
        if pref and weak: a += cfg["w_pref"]
        po, ph = st[o], st[h]
        if po is not None and po[0] == p and t - po[3] < 0.5 and (ph is None or ph[0] != p or ph[3] < po[3]): a += cfg["w_chg"] * dens(p, t)
        c += a * (0.1 if (cfg["arm"] == "AB" and relaxed) else 1.0)
    if cfg["arm"] == "B" and pref and weak: c += cfg["w_bias"] * (0.1 if relaxed else 1.0)
    return c


def install(chart2, K, token, bar_ticks):
    """re-compile chart2.stick with the added term (once), then point it at this arm"""
    S["cfg"] = ARMS[token]; S["bar_ticks"] = int(bar_ticks); S["stats"].clear()
    if not hasattr(chart2.stick, "_hp"):
        src = inspect.getsource(chart2.stick); old = 'c += K.PREF[key(n)][h]; prev = st[h]'; assert src.count(old) == 1, "the deal's cost line moved: stop (the patch needs the wrapped planner)"
        src = src.replace(old, 'c += K.PREF[key(n)][h] + _HP(n, h, st, t); prev = st[h]').replace("def stick(", "def _stick_hp(", 1)
        ns = chart2.__dict__; ns["_HP"] = cost; exec(compile(src, "<hand_pref: chart2.stick + one term>", "exec"), ns); patched = ns["_stick_hp"]; orig = chart2.stick
        def stick(N, spt, groups, K_):
            prepare(N, spt, K_); return patched(N, spt, groups, K_)
        stick._hp = True; stick._orig = orig; chart2.stick = stick
