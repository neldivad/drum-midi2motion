# midi2motion

Drum MIDI in, an android drummer's motion out. **Realism first**: the drummer is a rigged android that has to reach every drum within human joint ranges, speed limits and without its arms going through the kit or its own body. When a note cannot be played that way, the note is softened, played on the nearest reachable drum (only where the passage is hard), or cut, and the loss is written down. A local web page plays the result in 3D with sound.

This is a private preview. The solver is **frozen**: it is packaged exactly as it finished its research, with its failures listed as limits instead of being fixed (see [Honest limits](#honest-limits)).

## Quick start

```bash
git clone <this repo> && cd drum-midi2motion
pip install -e .                                   # numpy, scipy, PyYAML, mido; Python 3.10+
midi2motion serve                                  # then open http://127.0.0.1:8814/
```

The page opens on the bundled presets, which are already solved. To solve your own MIDI file (minutes, 1 to 3 GB of memory, CPU only), then drop the two files it writes onto the page:

```bash
midi2motion solve my_beat.mid --bars 1-4 --out my_beat.motion.json      # also writes my_beat.judgement.json
```

## The command line

| command | what it does |
|---|---|
| `midi2motion solve IN.mid [--bars A-B] [--meter M] [--layout L] --out NAME.motion.json` | solves one MIDI file. `--bars` are real bars of the file, 1-based, inclusive (default: the whole file). `--meter` is quarter notes per bar or a time signature: `4`, `3`, `5`, `2.5`, `4/4`, `3/4`, `6/8`, `5/4`, `5/8` (default 4). Writes the motion and, next to it, `NAME.judgement.json`. Never overwrites. |
| `midi2motion serve [--kit DIR] [--port 8814]` | serves the built page (`web/dist/`, checked in: no Node needed) and its data (`web/public/`) on `127.0.0.1` only. `--kit DIR` mounts your own drum samples (see [Bring your own kit](#bring-your-own-kit)). |
| `midi2motion presets build [--groove-dir D] [--author-dir D] [--jobs 2] [--only ID ...]` | rebuilds `web/public/presets/` from `presets/presets.json`; skips presets already built. Needs the source MIDI (the [Groove MIDI Dataset](https://magenta.tensorflow.org/datasets/groove) folder, and the author's own files, which are not in this repo). |

A solve is one process and 1 to 3 GB. On a shared machine run it under a cap and at low priority, and no more than two at once:

```bash
systemd-run --user --scope -q -p MemoryMax=4G nice -n 15 midi2motion solve my_beat.mid --bars 1-8 --out my_beat.motion.json
```

Timing: about 2 to 3 minutes for a 4-bar groove, 10 to 30 minutes for 8 bars.

Input: standard General MIDI drum pitches. The Groove dataset's electronic-kit rims and edges are folded onto the head or bow. Claps, clicks and other percussion layers are left out, and anything not on the kit map is dropped and counted in the judgement.

## The motion JSON, in brief

A 30 fps file: the android's bones as quantised deltas from its rest pose (`web/public/assets/android_base.glb`), both sticks, the two pedals, the hi-hat opening, the kit layout, and the judged source notes (`[time, piece, velocity, zone]`, for sound). The judgement file holds one verdict per source note (hit, wrong drum, missed, extra, early/late, softer, and why) with tallies; `remedy.played_pct` is the headline number. Full schemas: [docs/formats.md](docs/formats.md).

## Presets and credits

Bundled in `web/public/presets/` (listed in `manifest.json`), each with its motion, judgement and the source MIDI cut to its bars. *Played* is the share of judged notes played on their own piece within 100 ms, from the judgement summary.

<!-- presets -->
| id | kind | style | bpm | meter | bars | played | credit |
|---|---|---|---|---|---|---|---|
| `rock-100` | groove | rock | 100 | 4/4 | 2-5 | 100 % | Groove MIDI Dataset, CC BY 4.0 |
| `funk-112` | groove | funk | 112 | 4/4 | 2-5 | 100 % | Groove MIDI Dataset, CC BY 4.0 |
| `jazz-waltz-120` | groove | jazz | 120 | 3/4 | 10-17 | 97.3 % | Groove MIDI Dataset, CC BY 4.0 |
| `latin-samba-116` | groove | latin | 116 | 4/4 | 4-7 | 95.4 % | Groove MIDI Dataset, CC BY 4.0 |
| `hiphop-70` | groove | hiphop | 70 | 4/4 | 28-31 | 91.9 % | Groove MIDI Dataset, CC BY 4.0 |
| `fill-funk-92` | fill | funk | 92 | 4/4 | 1-1 | 100 % | Groove MIDI Dataset, CC BY 4.0 |
| `shuffle-125` | groove | shuffle | 125 | 4/4 | 54-61 | 98.7 % | Groove MIDI Dataset, CC BY 4.0 |
| `six-eight-70` | groove | rock | 70 | 6/8 | 2-9 | 85.9 % | Groove MIDI Dataset, CC BY 4.0 |
| `prog-five-four-110` | groove | rock | 110 | 5/4 | 14-21 | 93.6 % | Groove MIDI Dataset, CC BY 4.0 |
| `closure-85-92` | song | song | 150 | 4/4 | 85-92 | 92.5 % | © the author, all rights reserved |
| `dumbrock-97-103` | song | song | 165 | 4/4 | 97-103 | 78.7 % | © the author, all rights reserved |
<!-- /presets -->

- **Groove presets** are windows of the [Groove MIDI Dataset](https://magenta.tensorflow.org/datasets/groove) (Gillick, Roberts, Engel, Tomer and Bamman, "Learning to Groove with Inverse Sequence Transformations", ICML 2019), licensed **CC BY 4.0**. The MIDI cut for each preset is a derivative of those performances; the motion and judgement files are ours.
- **The author's own songs** (closure, dumbrock) are marked `"source": "author"` in the manifest: **© the author, all rights reserved.** They are bundled for this preview only.
- **The drum kit** (sound) is [Virtuosity Drums](https://versilian-studios.com/virtuosity-drums/) by Versilian Studios, **CC0**; see below.
- **The android model** (`web/public/assets/android_base.glb`, 2.4 MB) is built in code by us (a Blender scene script that makes the android from a description of its bones) and is shipped as built. It was exported from the research lab where the rig was developed (`android-mocap-midi/out/android_base.glb`); the rest pose and bone names the solver uses (`src/midi2motion/rig/sibling/android_rest.json`) were dumped from the same scene.

## Bring your own kit

Sound is a checking aid, and the page ships a CC0 kit. To hear your own drums, put your samples in a folder with a `kit.json` (the format is in [docs/kits.md](docs/kits.md): a list of Ogg or WAV files per piece, with velocity ranges; paths may sit in subfolders) and run

```bash
midi2motion serve --kit ./my-kit
```

The folder is served from your machine only, as the kit named `user`. Nothing is uploaded and nothing is copied.

## Honest limits

The solver was benchmarked on the Groove MIDI Dataset (73 windows from 9 drummers): about 93 to 94 % of judged notes are played on their own piece, 95 % on plain grooves and 90 % on fills. Where it falls short, we have listed it rather than fixed it ([docs/limits.md](docs/limits.md)):

- **Fills** are the weakest regime, and the same fill can score 68 to 82 % depending on the order repairs are tried in.
- **Repeated figures** (the same notes in the same rhythm) are not played with the same sticking each time, as a drummer would.
- **Tom sweeps** lose more notes (11 % against 10 % elsewhere), mostly to collisions and hand-shift time.
- **Inward sticks**: in about 10 % of frames a stick points inward across the body, a habit that hurts real drummers, because of the android's palm grip.
- **Hand-habit errors**: hands swap roles, share a cymbal or take a note that belongs to the other hand's next stroke. They are counted in the judgement and not planned against, and the "hands work by family of pieces" rule is not in the solver.
- **The stick zones are ours**, fitted on the android's own motion, not human data. Nothing flags non-human MIDI.
- Dense odd-meter material (the bundled 6/8 preset) leaves frames over a hard limit.

## How it works

1. Read the MIDI and fold it onto a standard kit: kick, snare, hi-hat with its pedal, three toms and a floor tom, crash, ride and bell.
2. Deal every note to a hand or foot with a beam search whose costs prefer each hand's role and penalise crossing.
3. Plan the strokes: where the stick tip strikes, how high it lifts and how fast it moves, from the note's velocity, with the stick pivoting in the grip.
4. Solve the arms (inverse kinematics with an elbow swivel), torso and legs for the whole clip at 120 Hz, then downsample to 30 fps.
5. Check the hard limits: joint ranges, hand and foot speed and acceleration ceilings calibrated on motion capture of a real drum mime, collisions of body, arms, sticks and kit, continuity of every end point.
6. Repair, up to 16 passes: lift the waiting stick, raise the arc, let the free hand take the note, play the nearest reachable drum in hard passages only, play softer, and as a last resort cut the note.
7. Judge every source note against the result and write the motion and the judgement.

More: [what a drummer does](docs/drums-as-an-idea.md) · [what failing taught us](docs/lessons.md) · [limits and open questions](docs/limits.md) · [file formats](docs/formats.md) · [kits](docs/kits.md).

## Tests

```bash
pip install -e '.[test]'
pytest tests/                       # solves the three parity windows (about 15 minutes) and compares them with the reference
```

The parity test checks that the packaged solver reproduces the library it was packaged from: for three windows (a rock groove, a funk-rock fill, an 8-bar rock shuffle) the sha256 of the motion JSON, apart from its title and library-version fields, and the summary numbers must equal the reference recorded in `tests/reference.json`.

## Licence

TBD (private preview). The Groove MIDI cuts are CC BY 4.0, the kit is CC0, and the author's songs are all rights reserved.
