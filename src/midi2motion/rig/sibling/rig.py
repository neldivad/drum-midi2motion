#!/usr/bin/env python3
# midi2motion: vendored from nelvids/lab/wrapped/3d/2026-11-15-android-mocap-midi/tools/rig.py (a wrapped lab, read-only source). Solver behaviour unchanged; only data paths and the lab command line were changed.
"""rig.py: the android's solver, outside Blender (numpy). One place poses are made, checked for collision and audited;
Blender (android_scene.py --perf) and the inspector (inspector/index.html) only APPLY what this bakes.

    from rig import Rig;  R = Rig();  P, info = R.solve(pose, state, collide=True, surfaces=[...])
    python tools/rig.py rebake work/motion_play.json work/perf_dumbrock_before.json --no-collide      (round 1's motion, as it was)
    python tools/rig.py rebake work/motion_play.json work/perf_dumbrock_after.json                    (the same targets, collision-solved)

Rest pose: out/android_rest.json (dumped by android_scene.py --dump-rest: bone heads, tails, rest matrices). Character space:
origin on the floor under the hips, facing -Y, +X = its left, Z up, metres.

A pose (per frame): root, hips/spine/chest/neck/head [pitch, roll, yaw] deg, shrug [L, R] deg, hand_L / hand_R:
  pos (wrist), dir (hand forward), up (back of hand), then EITHER curl[5] + spread (the simple hand) OR
  joints: 15 x [flex, abduct, twist] deg in MANO order (index, middle, pinky, ring, thumb; 3 joints each, base first): the data-driven
  hand (a retargeted hand track goes straight in), and wrist: [flex, deviation, twist] deg applied on top of dir/up.
  pole (legacy elbow hint) is used only with collide=False.

Collision (collide=True), per arm, per frame:
  1. the wrist target is pushed out of the torso/hip/head/thigh capsules, out of the other arm, kept in FRONT of the chest
     (never behind the back or inside the body's width), above every set surface (keybed, rim) and no closer to the shoulder
     than a 150 deg elbow allows;
  2. the elbow's swivel about the shoulder-wrist axis is searched over the natural range (-25 deg inward .. +60 deg outward
     of hanging straight down): no penetration first, then nearest to a relaxed 18 deg and to the previous frame (rate-limited);
  3. the shoulder stays within limits (no arm behind the back, across the midline or above the head): a cost in the same search;
  4. the hand's direction is clamped to 60 deg of the forearm's (the wrist's range).
Penetration is then MEASURED on whatever was solved (also with collide=False), capsule against capsule and capsule against
surfaces, in metres: that is the report, and what the inspector draws.
"""
import json, math, pathlib, sys
import numpy as np

LAB = pathlib.Path(__file__).resolve().parent          # midi2motion: android_rest.json and joint_fit.json sit beside this file
MANO = [f"{f}.{k:02d}" for f in ("index", "middle", "pinky", "ring", "thumb") for k in (1, 2, 3)]
FINGERS = ("thumb", "index", "middle", "ring", "pinky")


def rot(axis, ang):
    a = np.asarray(axis, float); a = a / (np.linalg.norm(a) + 1e-12); x, y, z = a; c, s = math.cos(ang), math.sin(ang); C = 1 - c
    return np.array([[c + x * x * C, x * y * C - z * s, x * z * C + y * s], [y * x * C + z * s, c + y * y * C, y * z * C - x * s], [z * x * C - y * s, z * y * C + x * s, c + z * z * C]])


def m4(R, t=(0, 0, 0)): M = np.eye(4); M[:3, :3] = R; M[:3, 3] = t; return M
def rot_about(p, R): return m4(R, np.asarray(p) - R @ np.asarray(p))
def eul(a):
    p, r, y = (math.radians(v) for v in a); return rot((0, 0, 1), y) @ rot((0, 1, 0), r) @ rot((1, 0, 0), p)
def nrm(v): return v / (np.linalg.norm(v) + 1e-12)


def frame(head, y, z):
    y = nrm(np.asarray(y, float)); x = np.cross(y, z)
    if np.linalg.norm(x) < 1e-6: x = np.cross(y, (1.0, 0, 0))
    x = nrm(x); z = np.cross(x, y); M = np.eye(4); M[:3, 0] = x; M[:3, 1] = y; M[:3, 2] = z; M[:3, 3] = head; return M


def seg_seg(p1, q1, p2, q2):
    """closest points between two segments -> (distance, point on 1, point on 2)"""
    d1, d2, r = q1 - p1, q2 - p2, p1 - p2; a, e, f = d1 @ d1, d2 @ d2, d2 @ r
    if a < 1e-12 and e < 1e-12: return np.linalg.norm(r), p1, p2
    if a < 1e-12: s, t = 0.0, min(1.0, max(0.0, f / e))
    else:
        c = d1 @ r
        if e < 1e-12: t, s = 0.0, min(1.0, max(0.0, -c / a))
        else:
            b = d1 @ d2; den = a * e - b * b; s = min(1.0, max(0.0, (b * f - c * e) / den)) if den > 1e-12 else 0.0
            t = (b * s + f) / e
            if t < 0: t, s = 0.0, min(1.0, max(0.0, -c / a))
            elif t > 1: t, s = 1.0, min(1.0, max(0.0, (b - c) / a))
    c1, c2 = p1 + d1 * s, p2 + d2 * t; return float(np.linalg.norm(c1 - c2)), c1, c2


class Rig:
    def __init__(self, rest=LAB / "android_rest.json"):
        J = json.load(open(rest)); self.names = [b["name"] for b in J["bones"]]; self.parent = {b["name"]: b["parent"] for b in J["bones"]}
        self.REST = {b["name"]: np.array(b["matrix"]) for b in J["bones"]}; self.RINV = {n: np.linalg.inv(M) for n, M in self.REST.items()}
        self.HEAD = {b["name"]: np.array(b["head"]) for b in J["bones"]}; self.TAIL = {b["name"]: np.array(b["tail"]) for b in J["bones"]}
        A = J["arm"]; self.L_UP, self.L_FO, self.L_PALM = A["L_UP"], A["L_FO"], A["L_PALM"]; self.AD, self.PN = np.array(A["AD"]), np.array(A["PN"])
        self.CURL = {}
        for s, sg in (("L", 1), ("R", -1)):
            pn = np.array([self.PN[0] * sg, 0, self.PN[2]])
            for fn in FINGERS:
                for k in (1, 2, 3):
                    b = f"{fn}.{k:02d}.{s}"; R = self.REST[b][:3, :3]; ax, y = R[:, 0], R[:, 1]
                    tgt = pn if fn != "thumb" else nrm(pn + np.array([self.AD[0] * sg * 0.6, 0.6, 0]))
                    self.CURL[b] = 1.0 if (rot(ax, 0.3) @ y) @ tgt > (rot(ax, -0.3) @ y) @ tgt else -1.0
        self.thigh_l = np.linalg.norm(self.TAIL["thigh.L"] - self.HEAD["thigh.L"]); self.shin_l = np.linalg.norm(self.TAIL["shin.L"] - self.HEAD["shin.L"])
        # body capsules: (name, bone that carries it, rest point a, rest point b, radius)
        self.BODY = [("pelvis", "hips", (-0.06, 0, 0.90), (0.06, 0, 0.90), 0.115), ("waist", "spine", (0, 0, 1.00), (0, 0, 1.14), 0.105),
                     ("chest", "chest", (-0.07, 0, 1.27), (0.07, 0, 1.27), 0.105), ("neck", "neck", (0, 0, 1.41), (0, 0, 1.47), 0.05), ("head", "head", (0, -0.008, 1.56), (0, -0.008, 1.63), 0.102)]

    # ---- the legacy two-bone solve (round 1): elbow from a pole hint
    @staticmethod
    def two_bone(S, W, l1, l2, pole):
        d = W - S; L = np.linalg.norm(d); mx = (l1 + l2) * 0.999
        if L > mx: W = S + d * (mx / L); d = W - S; L = mx
        L = max(L, abs(l1 - l2) + 1e-4); a = (l1 * l1 - l2 * l2 + L * L) / (2 * L); h = math.sqrt(max(l1 * l1 - a * a, 0.0)); u = d / L
        pv = pole - S; pv = pv - u * (pv @ u)
        if np.linalg.norm(pv) < 1e-5: pv = np.array([0, 0, -1.0]) - u * u[2]
        return S + u * a + nrm(pv) * h, W

    def body_caps(self, T):
        caps = []
        for name, bone, a, b, r in self.BODY:
            M = T[bone]; caps.append((name, (M @ np.array([*a, 1.0]))[:3], (M @ np.array([*b, 1.0]))[:3], r))
        return caps

    def arm_caps(self, s, S, E, W, hd):
        return [(f"upper_arm.{s}", S + (E - S) * 0.45, E, 0.043), (f"forearm.{s}", E, W, 0.038), (f"hand.{s}", W, W + nrm(hd) * 0.12, 0.028)]

    @staticmethod
    def surf_pen(surfaces, p, r):
        """how far a sphere (p, r) is sunk below the surface under it; surfaces: callables (x, y) -> top z or None"""
        best = 0.0
        for f in surfaces:
            z = f(p[0], p[1])
            if z is not None and p[2] - r < z and p[2] > z - 0.25: best = max(best, z + r - p[2])
        return best

    def arm_pen(self, caps, body, other, surfaces, mark):
        """penetrations of one arm's capsules -> list of (a, b, depth, point)"""
        out = []
        for na, a0, a1, ra in caps:
            for nb, b0, b1, rb in body + other:
                if na.startswith("upper_arm") and nb in ("chest", "neck"): continue          # the shoulder joint lives inside the chest's end
                d, c1, c2 = seg_seg(a0, a1, b0, b1)
                if d < ra + rb: out.append((na, nb, ra + rb - d, (c1 + c2) / 2, nrm(c1 - c2) if d > 1e-6 else np.array([0, -1.0, 0])))
            if not na.startswith("upper_arm"):
                pts = [a0 + (a1 - a0) * u for u in ((0.0, 0.33, 0.66, 1.0) if na.startswith("forearm") else (0.0, 0.7))]   # the hand: wrist..knuckles (fingertips are meant to touch)
                for p in pts:
                    d = self.surf_pen(surfaces, p + mark, 0.018 if na.startswith("hand") else ra)
                    if d > 0: out.append((na, "set", d, p, np.array([0, 0, 1.0]))); break
        return out

    def solve(self, pose, state=None, collide=True, surfaces=(), mark=(0, 0, 0)):
        """-> P {bone: 4x4 armature-space pose matrix}, info {caps, pens, angles, tips}"""
        R_, H, TL = self.REST, self.HEAD, self.TAIL; state = state if state is not None else {}; mark = np.asarray(mark, float); P = {}; T = {}
        Tm = m4(np.eye(3), pose.get("root", (0, 0, 0))) @ rot_about(H["hips"], eul(pose.get("hips", (0, 0, 0)))); T["hips"] = Tm; P["hips"] = Tm @ R_["hips"]
        for b in ("spine", "chest", "neck", "head"):
            Tm = Tm @ rot_about(H[b], eul(pose.get(b, (0, 0, 0)))); T[b] = Tm; P[b] = Tm @ R_[b]
        body = self.body_caps(T); Rc = T["chest"][:3, :3]; cpos = (T["chest"] @ np.array([0, 0, 1.30, 1.0]))[:3]
        legs = []
        for s, sg in (("L", 1), ("R", -1)):
            Hp = (T["hips"] @ np.append(H[f"thigh.{s}"], 1))[:3]; An = H[f"foot.{s}"]
            K, An2 = self.two_bone(Hp, An, self.thigh_l, self.shin_l, Hp + np.array([0, -1, -0.3]))
            P[f"thigh.{s}"] = frame(Hp, K - Hp, (0, -1, 0)); P[f"shin.{s}"] = frame(K, An2 - K, (0, -1, 0))
            Tf = m4(np.eye(3), An2 - An); P[f"foot.{s}"] = Tf @ R_[f"foot.{s}"]; P[f"toe.{s}"] = Tf @ R_[f"toe.{s}"]; legs.append((f"thigh.{s}", Hp, K, 0.075))
        body = body + legs; info = {"caps": [(n, a, b, r) for n, a, b, r in body], "pens": [], "angles": {}, "tips": {}, "limits": []}
        done = []
        for s, sg in (("L", 1), ("R", -1)):
            sh = pose.get("shrug", (0, 0))[0 if s == "L" else 1]
            Ts = T["chest"] @ rot_about(H[f"shoulder.{s}"], rot((0, 1, 0), -math.radians(sh) * sg)); P[f"shoulder.{s}"] = Ts @ R_[f"shoulder.{s}"]
            S = (Ts @ np.append(H[f"upper_arm.{s}"], 1))[:3]; h = pose.get(f"hand_{s}")
            if not h:
                for b in ("upper_arm", "forearm", "hand"): P[f"{b}.{s}"] = Ts @ R_[f"{b}.{s}"]
                E = P[f"forearm.{s}"][:3, 3]; W = P[f"hand.{s}"][:3, 3]; hd = P[f"hand.{s}"][:3, 1]; hu = P[f"hand.{s}"][:3, 2]; phi = 0.0
            else:
                W = np.array(h["pos"], float); hd = nrm(np.array(h["dir"], float)); hu = nrm(np.array(h["up"], float))
                if "wrist" in h:                                                  # data-driven wrist on top of dir/up: [flex (palmar), deviation (ulnar), twist]
                    fx, dv, tw = (math.radians(v) for v in h["wrist"]); side = np.cross(hd, hu); Rw = rot(hd, tw * sg) @ rot(hu, -dv * sg) @ rot(side, -fx)
                    hd, hu = Rw @ hd, Rw @ hu
                if not collide:
                    E, W = self.two_bone(S, W, self.L_UP, self.L_FO, np.array(h.get("pole", (0.6 * sg, 0.2, 0.9)), float)); phi = None
                else:
                    other = [c for c in done]; prev = state.get(f"phi_{s}"); hd0, hu0 = hd.copy(), hu.copy()
                    for outer in range(4):
                        hd, hu = hd0.copy(), hu0.copy()
                        for _ in range(5):                                        # 1. the wrist target out of bodies, in front of the chest, above the set
                            moved = False
                            for nb, b0, b1, rb in body + other:
                                d, c1, c2 = seg_seg(W, W + hd * 0.12, b0, b1); need = 0.028 + rb + 0.004
                                if d < need:
                                    n = c1 - c2; n = nrm(n) if np.linalg.norm(n) > 1e-6 else nrm(W - cpos); W = W + n * (need - d); moved = True
                            loc = Rc.T @ (W - cpos)
                            if abs(loc[0]) < 0.24 and loc[1] > -0.15: loc[1] = -0.15; W = Rc @ loc + cpos; moved = True     # never behind or inside the torso's width
                            if loc[0] * sg < -0.30: loc[0] = -0.30 * sg; W = Rc @ loc + cpos; moved = True                    # nor far across the midline
                            dz = max(self.surf_pen(surfaces, W + mark, 0.020), self.surf_pen(surfaces, W + hd * 0.085 + mark, 0.020))   # a hand is ~3.6 cm thick: 1.8 cm + 2 mm clear
                            if dz > 0: W = W + np.array([0, 0, dz]); moved = True
                            dS = W - S; L = np.linalg.norm(dS); dmin = math.sqrt(self.L_UP ** 2 + self.L_FO ** 2 - 2 * self.L_UP * self.L_FO * math.cos(math.radians(30)))
                            if L < dmin: W = S + nrm(dS) * dmin; moved = True
                            if not moved: break
                        d = W - S; L = np.linalg.norm(d); mx = (self.L_UP + self.L_FO) * 0.999
                        if L > mx: W = S + d * (mx / L); L = mx
                        u = (W - S) / L; a = (self.L_UP ** 2 - self.L_FO ** 2 + L * L) / (2 * L); rho = math.sqrt(max(self.L_UP ** 2 - a * a, 0.0)); c0 = S + u * a
                        down = np.array([0, 0, -1.0]) - u * (-u[2]); down = nrm(down) if np.linalg.norm(down) > 1e-4 else nrm(np.array([0, 1.0, 0]) - u * u[1])
                        outw = np.cross(u, down); outw = outw if outw @ (Rc[:, 0] * sg) + 0.3 * outw[1] > 0 else -outw       # +phi swings the elbow outward/back
                        best = None
                        for ph in np.radians(np.arange(-25, 61, 5.0)):                # 2-3. the elbow's swivel: no penetration, shoulder in range, relaxed, steady
                            E = c0 + rho * (math.cos(ph) * down + math.sin(ph) * outw); fd = nrm(W - E); hdc = hd
                            caps = self.arm_caps(s, S, E, W, hdc); pl = self.arm_pen(caps, body, other, surfaces, mark); pen = sum(q[2] for q in pl)
                            ul = Rc.T @ nrm(E - S); lim = max(0, ul[1] - 0.45) + max(0, -ul[0] * sg - 0.35) + max(0, ul[2] - 0.35)
                            cost = 400 * pen + 30 * lim + 0.6 * (ph - math.radians(18)) ** 2 + (1.5 * (ph - prev) ** 2 if prev is not None else 0)
                            if best is None or cost < best[0]: best = (cost, ph, pen)
                        phi = best[1]
                        if prev is not None:                                      # the elbow never pops (faster only to get out of a body)
                            rate = math.radians(10 if best[2] < 1e-4 else 25); phi = prev + float(np.clip(phi - prev, -rate, rate))
                        E = c0 + rho * (math.cos(phi) * down + math.sin(phi) * outw)
                        fd = nrm(W - E); ang = math.acos(float(np.clip(hd @ fd, -1, 1)))                                   # 4. the wrist's range
                        if ang > math.radians(60):
                            ax = np.cross(fd, hd); Rw = rot(ax, math.radians(60) - ang); hd = Rw @ hd; hu = Rw @ hu
                        pl = self.arm_pen(self.arm_caps(s, S, E, W, hd), body, other, surfaces, mark)
                        if not pl or outer == 3: break
                        for na, nb, dep, pt, n in pl: W = W + n * (dep + 0.003)   # what the swivel could not clear moves the wrist target itself
                    state[f"phi_{s}"] = phi
                yu, yf = nrm(E - S), nrm(W - E); zu = yf - yu * (yf @ yu)
                if np.linalg.norm(zu) < 1e-4:
                    m = E - (S + (W - S) * 0.5); zu = -m if np.linalg.norm(m) > 1e-4 else np.array([0, -1.0, 0])
                zu = nrm(zu); xh = nrm(np.cross(yu, zu))
                P[f"upper_arm.{s}"] = frame(S, yu, zu); P[f"forearm.{s}"] = frame(E, yf, np.cross(xh, yf)); P[f"hand.{s}"] = frame(W, hd, hu)
            Th = P[f"hand.{s}"] @ self.RINV[f"hand.{s}"]; hh = h or {}
            curl = hh.get("curl", (0.15,) * 5); spread = hh.get("spread", 0.0); jd = hh.get("joints")
            for i, fn in enumerate(FINGERS):
                Tf = Th
                for k in (1, 2, 3):
                    b = f"{fn}.{k:02d}.{s}"; R3 = R_[b][:3, :3]
                    if jd is not None:
                        fx, ab, tw = (math.radians(v) for v in jd[MANO.index(f"{fn}.{k:02d}")])
                        Rm = rot(R3[:, 1], tw * sg) @ rot(R3[:, 2], ab * sg) @ rot(R3[:, 0], fx * self.CURL[b])
                    else:
                        ang = curl[i] * (1.35 if k == 1 else 1.55 if k == 2 else 1.1) * (0.6 if fn == "thumb" else 1.0); Rm = rot(R3[:, 0], ang * self.CURL[b])
                        if k == 1 and fn != "thumb": Rm = rot(R3[:, 2], spread * (i - 2.2) * 0.12 * sg) @ Rm
                    Tf = Tf @ rot_about(H[b], Rm); P[b] = Tf @ R_[b]
                info["tips"][f"{fn}.{s}"] = (Tf @ np.append(TL[f"{fn}.03.{s}"], 1))[:3]
            caps = self.arm_caps(s, S, E, W, hd); done += caps; info["caps"] += caps
            ul = Rc.T @ nrm(E - S); fd = nrm(W - E)
            info["angles"][s] = dict(elbow=round(math.degrees(math.acos(float(np.clip(nrm(E - S) @ fd, -1, 1)))), 1),
                                     shoulder_elev=round(math.degrees(math.acos(float(np.clip(-ul[2], -1, 1)))), 1), shoulder_out=round(math.degrees(math.atan2(ul[0] * sg, -ul[1])), 1),
                                     swivel=None if phi is None else round(math.degrees(phi), 1), wrist=round(math.degrees(math.acos(float(np.clip(hd @ fd, -1, 1)))), 1),
                                     curl=[round(math.degrees(math.acos(float(np.clip(P[f"{fn}.03.{s}"][:3, 1] @ P[f"hand.{s}"][:3, 1], -1, 1)))), 0) for fn in FINGERS])
            if ul[1] > 0.45 or -ul[0] * sg > 0.35 or ul[2] > 0.35: info["limits"].append(f"shoulder.{s}")
            if info["angles"][s]["elbow"] > 152: info["limits"].append(f"elbow.{s}")
            if info["angles"][s]["wrist"] > 62: info["limits"].append(f"wrist.{s}")
        armsL = [c for c in info["caps"] if c[0].endswith(".L") and not c[0].startswith("thigh")]; armsR = [c for c in info["caps"] if c[0].endswith(".R") and not c[0].startswith("thigh")]
        info["pens"] = self.arm_pen(armsL, body, [], surfaces, mark) + self.arm_pen(armsR, body, armsL, surfaces, mark)
        return P, info

    def delta(self, P):
        """per bone: pose * rest^-1 (armature space), 12 floats row-major 3x4: what the inspector applies to the GLB's rest joints"""
        return [[round(float(v), 5) for v in (P[n] @ self.RINV[n])[:3].reshape(-1)] for n in self.names]


def bake(rig, chars, fps, collide, surfaces_for, extra=None):
    """chars: [{name, mark, accent, frames:[pose]}] -> perf dict (bones per frame for Blender + the audit data for the inspector)"""
    out = dict(fps=fps, frames=len(chars[0]["frames"]), bone_names=rig.names, collide=collide, chars=[])
    for ch in chars:
        mark = np.array([ch["mark"][0], ch["mark"][1], 0.0]); st = {}; yaw = ch.get("yaw", 0.0); Rz = rot((0, 0, 1), yaw)
        world = (lambda f: (lambda x, y: f(*(Rz @ np.array([x, y, 0.0]) + mark)[:2])))             # surfaces are in world space; the solver works in character space
        surfaces = [world(f) for f in (surfaces_for(ch) if surfaces_for else [])]
        C = dict(name=ch["name"], mark=ch["mark"], yaw=yaw, accent=ch["accent"], delta=[], caps=[], pens=[], pen_max=[], angles=[], tips=[], limits=[], joints=[])
        for pose in ch["frames"]:
            P, info = rig.solve(pose, st, collide=collide, surfaces=surfaces)
            C["delta"].append(rig.delta(P))
            C["caps"].append([[n, *[round(float(v), 4) for v in a], *[round(float(v), 4) for v in b], r] for n, a, b, r in info["caps"]])
            C["pens"].append([[a, b, round(float(d), 4), *[round(float(v), 4) for v in p]] for a, b, d, p, n in info["pens"] if d > 0.001])
            C["pen_max"].append(round(max([q[2] for q in info["pens"]] or [0.0]), 4))
            C["angles"].append(info["angles"]); C["limits"].append(info["limits"])
            C["tips"].append({k: [round(float(x), 4) for x in Rz @ v + mark] for k, v in info["tips"].items()})
        out["chars"].append(C)
    if extra: out.update(extra)
    return out


def pen_report(perf):
    rep = {}
    for C in perf["chars"]:
        pm = np.array(C["pen_max"]); pairs = {}
        for f, pl in enumerate(C["pens"]):
            for a, b, d, *_ in pl:
                k = f"{a} x {b}"; pairs.setdefault(k, [0, 0.0]); pairs[k][0] += 1; pairs[k][1] = max(pairs[k][1], d)
        el = np.array([[a[s]["elbow"] for s in "LR"] for a in C["angles"]]); sw = [a[s]["swivel"] for a in C["angles"] for s in "LR" if a[s]["swivel"] is not None]
        rep[C["name"]] = dict(frames=len(pm), frames_penetrating=int((pm > 0.001).sum()), max_depth_mm=round(float(pm.max()) * 1000, 1), mean_depth_mm_when_penetrating=round(float(pm[pm > 0.001].mean()) * 1000, 1) if (pm > 0.001).any() else 0.0,
                              pairs={k: dict(frames=v[0], max_mm=round(v[1] * 1000, 1)) for k, v in sorted(pairs.items(), key=lambda kv: -kv[1][0])},
                              limit_frames={k: int(sum(k in l for l in C["limits"])) for k in sorted({x for l in C["limits"] for x in l})}, elbow_max_deg=float(el.max()),
                              shoulder_out_max_deg=float(max(a[s]["shoulder_out"] for a in C["angles"] for s in "LR")), swivel_range_deg=[min(sw), max(sw)] if sw else None)
    return rep


# ---- the console as collision surfaces and as geometry (the remake's fitted desk)
JD = json.load(open(LAB / "joint_fit.json"))["duo"]
R1, AX, SPAN, NK, RIM_Z, DESK_Z, KD = JD["R1"], JD["ax"], math.radians(80), 60, 0.95, 0.905, 0.5
CAM_EYE = np.array([0, -JD["eye"][2], JD["eye"][1]])


def CP(a, d):
    ex, ez = AX * R1 * math.sin(a), R1 * math.cos(a); nx, nz = R1 * math.sin(a), AX * R1 * math.cos(a); l = math.hypot(nx, nz)
    return np.array([ex + d * nx / l, -(ez + d * nz / l)])


def console_d(x, y):
    """(angle a, signed distance d outward from the rim ellipse) of a world point"""
    a = math.atan2(x / AX, -y)
    for _ in range(6):
        e = CP(a, 0); nx, nz = R1 * math.sin(a), AX * R1 * math.cos(a); l = math.hypot(nx, nz); t = np.array([AX * R1 * math.cos(a), R1 * math.sin(a)])
        a += float((np.array([x, y]) - e) @ t) / float(t @ t)
    e = CP(a, 0); nx, nz = R1 * math.sin(a), AX * R1 * math.cos(a); l = math.hypot(nx, nz); n = np.array([nx / l, -nz / l])
    return a, float((np.array([x, y]) - e) @ n)


def console_surfaces():
    def top(x, y):
        a, d = console_d(x, y)
        if abs(a) > SPAN + 0.05: return None
        if -0.06 <= d <= 0.03: return RIM_Z
        if 0.03 < d <= KD + 0.06: return DESK_Z
        return None
    return [top]


def key_quads():
    ks = 2 * SPAN / NK; g = ks * 0.1; out = []
    for i in range(NK):
        a0, a1 = -SPAN + i * ks + g / 2, -SPAN + (i + 1) * ks - g / 2
        out.append([[round(float(v), 4) for v in CP(a, d)] for a, d in ((a0, 0.035), (a1, 0.035), (a1, KD), (a0, KD))])
    return out


def console_hand_tracks(perf):
    """for the inspector's graphs: per character and hand, per frame [lowest fingertip above the keybed (mm), its key coordinate (0..60, fractional)]"""
    ks = 2 * SPAN / NK
    for C in perf["chars"]:
        C["hand_track"] = {}
        for h in "LR":
            rows = []
            for tp in C["tips"]:
                low = min((tp[f"{fn}.{h}"] for fn in ("index", "middle", "ring", "pinky")), key=lambda q: q[2]); a_, d_ = console_d(low[0], low[1])
                rows.append([round((low[2] - DESK_Z) * 1000, 1), round((a_ + SPAN) / ks, 2)])
            C["hand_track"][h] = rows
    return perf


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "rebake":
    Mo = json.load(open(sys.argv[2])); collide = "--no-collide" not in sys.argv; rig = Rig()
    perf = bake(rig, Mo["chars"], Mo["fps"], collide, lambda ch: console_surfaces(),
                extra=dict(keys=Mo.get("keys"), notes=Mo.get("notes"), set=Mo.get("set", {}), audio=Mo.get("audio"), note_speed=Mo.get("note_speed"), key_quads=key_quads(), key_z=DESK_Z, source=sys.argv[2]))
    console_hand_tracks(perf); ev = []; names = [c["name"] for c in perf["chars"]]
    for i, n in enumerate(Mo.get("notes") or []):                                # round 1's notes as inspector events: did the assigned hand's fingertip touch its key at the onset?
        C = perf["chars"][n["player"]]; h = "R" if n["hand"] == 0 else "L"; f = min(perf["frames"] - 1, int(round(n["t"] * perf["fps"]))); z, k = C["hand_track"][h][f]
        ok = z <= 12 and abs(k - (n["key"] + 0.5)) <= 1.5
        ev.append(dict(id=f"N{i:03d}", player=n["player"] + 1, type="KEY", t=n["t"], dur=n["dur"], row=n["key"] - 30 * n["player"], hand=h, fail=not ok, info=f"key {n['key']} pitch {n['pitch']}: fingertip {z} mm above the key, {round(k - n['key'] - 0.5, 1)} keys off at the onset"))
    perf["events"] = ev; perf["rows"] = 30; perf["touch_mm"] = 12
    json.dump(perf, open(sys.argv[3], "w")); rep = pen_report(perf)
    rep["key_contact"] = {nm: dict(notes=sum(e["player"] == i + 1 for e in ev), touching_at_onset=sum(e["player"] == i + 1 and not e["fail"] for e in ev)) for i, nm in enumerate(names)}
    print(json.dumps(rep, indent=1))
