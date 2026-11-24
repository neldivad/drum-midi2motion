# What failing taught us, and how to work on it

The solver in this repo is the end of a long optimisation. These are the lessons from getting it there, written for whoever picks the problem up again. Each number names the run it came from.

## What failing taught us

- **Collisions were the first wall.** 168 notes were cut on the baseline. Cutting a note does not move the stick that collides, so the repair loop cut its way into a freeze (a limb with three or more consecutive cut notes over half a second or more). A fix table tried in order of cost (lift the waiting stick, raise the arc of travel, rise first then go over a cymbal) took collision cuts from 37 to 13 and the played share from 74.9 to 87.2 % on the 6 tempo windows.
- **Re-planning the whole clip makes scores chaotic.** The punk fill scored between 68 and 82 % depending only on the order the fixes were tried in. We then pinned every whole-clip stage outside a short window, so a pass re-planned 36 % of the clip instead of 88 %. Errors did not fall. The noise lives inside one stroke's own window: two orders give the same stroke different fixes. **Locality is necessary, not sufficient.** The next step would be to try every fix on the window and keep the cheapest, not to apply them in a fixed order.
- **The search was never the problem.** An exact hand-assignment search (Viterbi) found that the old approximate search was already optimal on all 20 test windows. What was missing was the *costs*: habits, bounces, look-ahead. Search is cheap; knowing what to want is the work.
- **Swapping a drum hides a miss.** Playing the nearest drum when the right one cannot be reached looked like a fix, but in easy stretches every note has a right drum. Making a wrong drum a full error (and not offering it at all in easy spans) cut wrong drums in easy spans from 37 to 1. Substitution is now a last resort in genuinely hard spans only.
- **Technique intuitions are hypotheses.** Two plausible ideas lost their test: scaling hand preference by note density (worse on the held-back windows), and relaxing the preference in fills and accents (it looked better, hard frames 94 to 36, but played worse). A rule enters the defaults only when the error counts fall with no regression on held-back windows.
- **The judge can be the bug.** A per-clip loudness fit hid most soft strokes (190 flagged where one fixed model would flag 816), and a pedal mis-filing invented 37 foot misses. Freeze the judge while tuning; fix it as its own step.
- **A belief was corrected by reading the teachers.** We thought loud accents came from the arm. The pedagogy and Dahl's data say the wrist. Letting the arm help raised stroke lift from 0.47 to 0.72 of the target and tip speed from 3.0 to 3.9 m/s, but that is a rig fix (the rig's stick turn in the hand is too small), not a human habit.

## How to work on it

- **Measure before fixing.** Triage every lost note into data, kit, rig, solver or judge. The biggest class, not the loudest example, sets the next round.
- **Freeze the judge and the realism limits** (collision depth, speed ceilings, joint ranges, the arm's share). A gain bought by loosening them does not count.
- **Keep held-back windows and a noise band.** Report how many windows got better, worse or tied, not only means. Rule order alone moved one window by 14 points, and a window is path-sensitive under any change.
- **Realism outranks accuracy.** A note that cannot be played inside the hard limits is cut, thinned or misplayed (late, softer, the nearest reachable drum) and logged against the source note. It is never played with an impossible movement.
- **Represent strokes, not frames.** A beat is a small table: time, drum, hand, height, velocity. Frames are regenerated from it. Per-frame motion files run 0.4 to 1.2 MB per clip, so reading them is expensive; work from the judgement and the stroke tables.
- **Solve cells, not bars.** Solve the common beat cells once, reuse them through their transformations, and full-solve only what is new.
- **Read teachers, then test them.** Pedagogy gives hypotheses with tests, not rules.
- **Human ground truth is the missing piece.** Disney Research's mocap of jazz drummers names hand assignment the "arm ambiguity" and is not public. Until there is human data, posture rules come from a person's eye.

## The method the adopted solver follows

The solver is not a learned model. It is a planner with a repair loop:

1. read the MIDI, map every note to a piece of the kit and a hand or foot (a beam search over hand assignments with costs for roles, crossing and reach);
2. plan the strokes (where the stick tip strikes, how high it lifts, from the note's velocity), then solve the arms, torso and legs for the whole clip at 120 Hz;
3. check hard limits: joint ranges, speed and acceleration ceilings of the hands and feet (calibrated on motion-capture of a real drum mime), collisions between body, arms, sticks and kit, continuity;
4. repair: for each violation try, in order, the cheapest fixes (lift the waiting stick, raise the arc, let the other hand take the note, play the nearest reachable piece in hard spans, play softer, and last cut the note), and re-plan, up to 16 passes;
5. judge every source note against the result with a note-by-note judge (hit, wrong drum, missed, extra, timing, softer) and write the motion and the judgement.

The solver then stops. Hand-habit errors and the family-of-pieces rule are *measured* in the judgement and not yet planned against. That is the honest state: see [limits.md](limits.md).
