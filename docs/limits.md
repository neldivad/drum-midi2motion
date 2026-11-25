# Limits, and open questions

The solver is **frozen**: it is packaged at its adopted settings and its known failures are listed here as limits, not fixed. If you tune it, you are starting a new research round, so freeze the judge first (see [lessons.md](lessons.md)).

## Cost

One solve is one process, 1 to 3 GB of memory, CPU only, no model, no network. A 4-bar groove takes about 2 to 3 minutes, a fill 2 to 8 minutes, 8 bars 10 to 30 minutes. Run it under a memory cap and keep to two at once on a laptop.

## Quality, by the numbers

The Groove MIDI Dataset, 73 windows from 9 drummers (32 typical beats, 11 busy beats, 30 fills). *Played* means a contact on the note's own piece within 100 ms. The adopted line was **never re-run on all 73 windows**: the last full run is from before the remedies, and the remedy tables were run on subsets, so every number names its run.

| run | windows | judged notes | played % | notes lost | collision cuts | freezes | crossed rides |
|---|---|---|---|---|---|---|---|
| baseline (no remedies) | 73 | 4,677 | 93.1 | 325 | 112 | 8 | 25 |
| with the remedy table | 26 | 2,260 | 93.6 | 144 | 37 | 4 | 8 |
| the adopted line | 21 | 1,783 | 94.2 | 104 | 35 | 3 | 8 |

On the baseline: common grooves (32) 95.3 % played; fills (30) 90.1 %; busy beats (17) 90.1 %; 0 crashes of the program, 0 teleports of an end point; 99.9 % of played hits land within 33 ms (the solver strikes on the snapped frame, so timing is easy by construction).

## Known limits

- **Fills are the weakest regime.** 90.1 % played on the 30 fills against 95.3 % on common grooves, and 7 fill windows still collide. One punk fill scores 68 to 82 % depending on the order the repairs are tried in. A bare one-bar clip works.
- **A repeated figure does not keep one sticking.** A drummer plays a figure (the same notes in the same rhythm, such as a triple crash into a fill) the same way each time. The solver plans each pass over the clip and nothing ties a repeat to its first instance. The author's closure preset (bars 85 to 92) shows it.
- **Tom sweeps.** 54 sweeps in 73 windows hold 508 notes; 57 of them are lost (11.2 % against 9.7 % elsewhere): collision 28, hand-shift time 15, continuity 8. Forbidding the nearest-piece substitution inside a sweep removes the wrong drums but raises in-sweep misses from 10.2 to 13.8 %.
- **Inward sticks.** 9.8 % of frames on the baseline (4.3 % with the splay cost the solver now carries; 481 of 6,569 frames on the adopted line). A 25-degree grip removes it at a price in notes. This is a grip artifact of the android.
- **Hand-habit errors.** 393 on the baseline (bounce splits 209, one-note swaps 101, reserved-limb steals 83). They are measured and not planned against.
- **Hands do not work by family of pieces.** The rule (metals, snare, toms; one hand per piece outside fills; no two hands on a cymbal) is not in the solver, which deals each note by cost and calls the other hand for help on bursts and on cymbals. Related counts on the baseline: 161 of 686 hi-hat pairs changed hands; 25 crossed rides (8 on the adopted line). Two cases you can watch in the presets:
  - `prog-five-four-110`, bars 20 to 27: a snare and tom-1 figure. The hands trade the two drums on almost every note, where a drummer keeps the snare in one hand and the tom in the other.
  - `closure-85-92`, bars 85 and 91: from snare (left) and ride (right), both hands cross to crash (left) and snare (right). The deal picks the nearest hand for each piece, so it pays for two moves where one hand change, or none, would do.

  The fix is a lane cost in the deal: a hand that leaves its family (metals, snare, toms) pays, unless the bar is a fill. It changes every solve, so it was left for future work.
- **Remedy-order noise.** Rule order alone moved one window by 14 points. Every pass re-solves the whole clip, so a kept remedy anywhere changes the ladder's later choices.
- **The zones are ours.** The allowed stick directions per piece are fitted on this rig's own cleanest frames. Straight arms: 0 frames. The rebound table is measured, not used by the planner. Nothing flags non-human MIDI.
- **Meter.** 3/4, 6/8, 5/4 and 5/8 windows are solved with `--meter`. The 6/8 window in the presets leaves 67 hard frames. Kit layouts other than the adopted one were solved only for the lab's own proof clips.
- **Input.** Standard General MIDI drum pitches pass through. The Groove dataset's electronic-kit rims and edges fold onto the head or bow (and the count is in the judgement). Other pitches (claps, clicks, triangles, other percussion) are dropped and counted; a low floor tom (note 41) is not in the Groove map and is dropped too. Two notes within 30 ms folded onto one piece are one stroke.
- **Sound is a checking aid.** The player's sound is for checking timing, not for listening; bring a kit ([kits.md](kits.md)) if you want it to sound like drums.

## Parked hypotheses (not worked)

1. **Home and pre-set limb positions.** After a sparse hit, does a limb return to a home pose? Before a familiar section or fill, are the limbs assigned their pieces in advance ("divide and conquer")?
2. **Judge by the pattern of mistakes per regime** (groove, fill, sweep, cymbal stack) rather than one percentage, so the next decision is made on the pattern.
3. **A human-likeness flag**, so the motion is never calibrated to non-human MIDI at the expense of human patterns.
4. **Cells and stroke tables.** Solve the common beat cells once, reuse them through their transformations, full-solve only what is new.

## Open questions

- How do grips change by phrase (German grip for power, French for finesse), and what triggers a change?
- Where does each limb actually play, by playing type (groove, fill, tempo)? This needs human data.
- What is the smallest cell vocabulary that covers a style, and is it per style or universal?
- Does fixing a cell fix its look everywhere, or do the joins between cells reintroduce the errors?
- Is rebound a property of the drum or a choice of stroke set by the next note? Teachers say the second: players can stop a rebound on any drum.
- Are open-handed and crossed playing fixed per player? Groove has 10 drummers, so this can be tested across their sessions.

## Not packaged

An exact dynamic-programming deal (a second planner) and a windowed re-solve were built in the research lab. They are not adopted and not part of the supported command line. The code of the dynamic-programming deal and of the hand-preference hypotheses is present under `core/` for reference; the options that switch them on are not exposed by the CLI.
