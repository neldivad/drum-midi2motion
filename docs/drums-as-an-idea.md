# Drums as an idea: what a drummer is doing

This page is what we learned about *drumming* while trying to turn drum MIDI into believable motion. It is written for anyone who wants to build, judge or improve something similar. The goal was never only "animate a MIDI file": it was to understand what a drummer is doing, so the motion can be right for the right reasons. Where a number appears, the run it came from is named (the benchmark: 73 windows of the Groove MIDI Dataset, solved and judged note by note).

Everything here is a finding or a hypothesis, not a standard. Where we were wrong, [lessons.md](lessons.md) says so.

## Roles, not notes

A groove is a few **roles** held for the whole track, not a stream of notes to deal out:

- one hand **keeps time** (the hi-hat or ride pattern);
- the other hand **places the backbeat** and the quiet ghost notes on the snare;
- the feet **keep the floor**: the kick, and the hi-hat pedal on the pulse or the backbeat.

A fill *borrows* a hand for a moment, and the habit **returns** afterwards. A left-hand backbeat under a right-hand hi-hat is the normal case, not a swap.

Our solver did not know this. It dealt each note to whichever hand was cheapest, so the hands traded roles in the middle of a groove. On the baseline run the hi-hat changed hands on 23 % of back-to-back hat notes (161 of 686 within half a second). Habit errors outnumbered lost notes, 393 against 325: 209 bounces split between hands, 101 one-note swaps onto the other hand's drum and back, 83 times a hand was taken from its own next note while the other hand was free.

**Hands work by family.** The ruling we ended on: metals (hi-hat, ride, bell, crashes), snare, toms.

- Outside fills each hand stays on its own piece. A fast burst on one piece is that hand bouncing faster, not a call for the other hand.
- In a fill a hand may move, but for a short window each limb still has one family: one on metals, one on toms or snare.
- A tom sweep is played by one hand, unless toms and crashes are swept together.
- Two hands share a piece only on the snare or the toms (rolls, unison hits). Two hands on one cymbal almost never happens.

The solver does **not** follow this rule yet. It is listed in [limits.md](limits.md).

## Gestures, not hits

- **A fast quiet repeat on one drum is one wrist motion: a bounce.** The stick rebounds and the fingers place the next note. The research agrees: Dahl's measurements of drummers (Frontiers, 2020) show strokes riding the rebound.
- **A fill is different.** It moves across drums and keeps or raises its accents. A bounce stays on one drum and its velocity stays flat or fades. Telling the two apart by velocity alone mistook 8 of 45 "fills" in our test.
- **Each drum rebounds differently.** Snare, ride and toms rebound well; crash, floor tom and hi-hat much less. A one-hand hi-hat run faster than a human can play would mean machine-made MIDI. The whole Groove dataset contains none.
- **Ornaments are one gesture**: flams, drags, rolls, sweeps and crescendos should be judged by their main transient, not note for note. Groove's 73 windows hold 93 such clusters (45 flams, 23 rolls, 13 drags, 12 sweeps). Scoring them as gestures moved the total only from 91.7 to 92.2 %, so ornaments are not where the losses are, but they are where a note-by-note judge is wrong.
- **Loud strokes come from a whipping wrist, not the arm.** Experts keep elbow and shoulder nearly still; the forearm lifts only to prepare. Soft and fast strokes are wrist and fingers. (We first believed the opposite and corrected it after reading the pedagogy; see [lessons.md](lessons.md).)
- **Strokes chain.** Teachers name four strokes by where the stick starts and ends: full (high to high), down (high to low), tap (low to low) and up (low to high). The stroke before an accent is quieter and already rising: in Groove the note before an accent sits at 0.92 of the local level, a real but mild dip. Our solver sets each stroke's height note by note, with no memory of where the last stroke left the stick.

## The feet do one thing

On the baseline, every one of the 47 foot "losses" came from the judge or the data, none from the motion. The judge was filing the hi-hat pedal's close under a hand stroke. The one real foot fault: the pedal closes at a hand stroke's slow speed instead of with the pedal note's force (10 notes in one performance).

## Posture and grip

- **Sticks splay outward.** Seen from above, the two sticks form a V opening forward; a stick pointing inward across the body from a hand at the far side is a habit that injures real drummers. Our rig does exactly that in 9.8 % of frames (55 of 73 windows), mostly the left stick at the hi-hat.
- **The cause is the grip.** The stick crosses the android's palm at a fixed 60 degrees. At 25 degrees the inward sticks disappear, but the ring and little fingers no longer wrap the stick and notes are lost.
- **The allowed stick direction depends on where the hand is playing.** Our "zones" are fitted on the rig's own cleanest frames, so they catch departures from the rig's habit, not from a human's. Real zones need human data.

## The music is a vocabulary

Of Groove's 491 beat performances in 4/4 (19,959 bars):

| unit | repeats earlier in the same performance | coverage |
|---|---|---|
| whole bar | 8 to 13 % | 85 % of bars are unique |
| half bar | 30 % | the top 500 patterns cover 30 % |
| **one beat** | **59 %** | **the top 500 beat patterns cover 63 % of all beats** |

A drummer almost never repeats a bar exactly, but the bars are recombinations of a few hundred beat-sized cells, and the variations are simple transformations: stretch it for tempo, change the lift height for loudness, move the same hand from hi-hat to ride, mirror the sticking.

With a tolerant grid (each beat snapped to 16ths, triplets, sextuplets or 32nds, whichever fits; all of Groove, 75,728 beats) there are 8,640 distinct beat cells: the top 50 cover 39 %, the top 200 cover 59 %, the top 500 cover 72 %, the top 2,000 cover 88 %. The vocabulary is per style. The top 50 cells cover:

| style | coverage |
|---|---|
| hip-hop | 78 % |
| funk | 62 % |
| afrobeat | 61 % |
| jazz | 44 % |
| rock | 43 % |
| afro-cuban | 37 % |
| latin | 34 % |

This is the basis for the most promising unbuilt idea: solve the common cells once and reuse them (see [limits.md](limits.md), open questions).

## Meter and tempo

- 1,138 of Groove's 1,150 performances are in 4/4; the rest are 3/4, 6/8, 5/4 and 5/8. Nothing in the motion depends on the meter: only the bookkeeping (bar grids, chart bars) did, and that is handled by the `--meter` option.
- **Slowing down** removes the speed-limited losses (hand-shift cuts went from 17 to 0 at half tempo) but not the structural ones (collisions, freezes, crossed hands). "If you can play it slow you can play it fast" holds only after it is playable slow.
- **Practising slow and reusing the sticking at full speed** helped: jazz went from 60.5 to 67.9 % played at full tempo.

## The recordings are clean

Groove's human electronic-kit MIDI is playable as recorded: across the 73 windows there were 0 double triggers, 4 crosstalk flags and 19 pedal-noise flags, and only 2 of those notes were lost. Only 37 notes landed on the wrong piece because of the note-to-drum table. **The losses are ours, not the data's.**
