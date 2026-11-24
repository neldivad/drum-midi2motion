# File formats

Four JSON files cross the boundary between the solver and the page: the **motion** (what to draw), the **judgement** (how well each source note was played), the **preset manifest** (the bundled examples) and the **kit** (samples; see [kits.md](kits.md)). All are plain JSON, UTF-8. `midi2motion solve IN.mid --out clip.json` writes `clip.json` (motion) and `clip.judgement.json` (judgement).

## Motion JSON (`schema: "verify.motion/1"`)

A compact 30 frames-per-second pose file. It is a few hundred kilobytes per clip, because poses are packed as little-endian 16-bit integers in base64 strings. Do not read it by eye; decode what you need.

| field | meaning |
|---|---|
| `schema` | always `"verify.motion/1"` |
| `key`, `title` | clip name and a human title (source file, bars, layout, version) |
| `fps`, `frames` | 30, and the number of frames `M` |
| `names` | the android's bones, in order (51 names); `nb = len(names)` |
| `delta` | base64 int16, shape `[M][nb][12]`: for each frame and bone a 3x4 matrix, row-major `[r00 r01 r02 tx, r10 r11 r12 ty, r20 r21 r22 tz]`, the **delta from the bone's rest pose** in its parent's frame. Rotation entries divide by 32000; translation entries (indices 3, 7, 11) divide by 10000 (metres). The rest pose ships as `web/public/assets/android_base.glb`. |
| `sticks` | base64 int16, shape `[M][2][6]`: hand `L` then `R`; `butt x y z, tip x y z`, divide by 10000 (metres, in the kit's frame) |
| `hat30` | base64 int16 `[M]`: how far the hi-hat is lifted (open) / closed, divide by 10000 |
| `kick_plate`, `hat_plate` | base64 int16 `[M]`: the two pedal boards' angle in degrees, divide by 100 |
| `kick_foot`, `hat_foot` | which foot plays each pedal (`"RF"` or `"LF"`) |
| `pen` | base64 int16 `[M]`: whole-body penetration in millimetres (max over the frame's four 120 Hz sub-frames), divide by 10 |
| `collisions`, `collision_pairs` | runs of frames over the 3 mm penetration limit (`f0`, `f1`, `max_mm`, `pairs`) and the colliding pairs the checks named |
| `kit` | the layout the clip was solved for: `pieces` (each `id`, `c` centre, `n` normal, `r` radius, `depth`, `kind` of `kick`, `drum` or `cymbal`, colour), `bell`, `seat_z`, `seat_y`, `stick`, `ankle`, `hat_gap`, `preset`, `foot_of`, `lead_hand` |
| `chart` | `{bars: [a, b], lead, bar_s}`: the real bars solved, the lead-in in seconds before the first bar line (0.5), and the bar length in seconds |
| `preset` | the layout preset name (`hh_out30_down65` is the adopted kit) |
| `remedy` | the repair loop's summary: `stats`, `boosts_kept`, `passes`, `played_pct`, `collision_cuts` |
| `notes` | `[[t_s, row, velocity, zone], ...]`: the **judged source notes**, for playing sound. `t_s` is seconds from frame 0 of the clip. |
| `library` | `{name: "midi2motion", version, schema: "1.1", rows}` |

**The note rows** (the piece ids the notes use, and the keys a kit must provide): `kick`, `snare`, `tom1`, `tom2`, `tom3`, `floor`, `hat`, `hatped`, `crash`, `ride`. **Zones** refine a row: `snare`: `head`, `rimshot`, `cross` (cross-stick); `hat`: `closed`, `open`; `ride`: `bow`, `bell`; `crash`: `edge`; the toms and floor: `head`; `kick`: `beater`; `hatped`: `pedal`.

**Time.** Frame `f` is at `f / 30` seconds. The notes' time and the poses share one clock; the solved window starts half a second (`chart.lead`) before the first bar line, so bar `a` begins at `chart.lead` seconds.

## Judgement JSON (`schema: "review3.judgement/1"`)

The judge's file: every source note's verdict, with tallies. It can be large (about 100 KB for a 4-bar clip), so use the summary fields first.

| field | meaning |
|---|---|
| `remedy.played_pct` | **the headline number**: the share of judged notes played on their own piece (a contact within 100 ms) |
| `remedy.collision_cuts`, `remedy.freezes`, `remedy.crossed`, `remedy.played_clip_hard_frames` | notes cut by collision; limbs that froze (a list); crossed rides (a list); frames still over a hard limit after all repairs |
| `remedy.passes`, `remedy.seconds`, `remedy.rows`, `remedy.window` | repair passes used, solve time, the repair rows applied, the window and what the MIDI mapping dropped or folded |
| `tally.all` | counts: `perfect`, `good`, `early`, `late` (timing classes), `softer`, `simplified`, `wrong`, `missed`, `extra`, `hits`, `notes`, `accuracy_pct`, plus `splay_frames`, `role_flips`, `swaps`, `steals`, `bounce_splits`, `zone_frames`, `straight_arm_frames` (the hand-habit and posture counts) and `missed_by` (why notes were missed, e.g. `collision`) |
| `tally.by_limb`, `tally.gestures` | the same by limb (`L`, `R`, `LF`, `RF`), and ornament clusters judged as one gesture |
| `source` | one entry per MIDI note: `id`, `t`, `row`, `vel`, `note`, `name`, `zone`, `bar`, `judged`, `plan` (`fate`: played, softer, cut ...; `limb`; `limit`: why it was changed; `how`), `verdict` (`cls`: hit, wrong, missed, extra; `offset_ms`; `limb`; `timing`; `softer`) |
| `events` | a time-ordered list of verdict events (`t`, `cat`, `limb`, `src`, ...) |
| `habits`, `splay`, `difficulty` | the habit counts, the inward-stick counts, the per-note difficulty split (easy and hard spans) |
| `grid` | `{lead, beat_s, bar0, bpb}`: the bar grid of the window in its own meter (`bpb` is quarter notes per bar) |
| `library` | `{name, version, midi, layout, preset, bars, meter, tag, rows, seconds, adopted}` |

## Preset manifest (`web/public/presets/manifest.json`)

```json
{
  "version": 1,
  "kit": "virtuosity-cc0",              // the default kit id (folder web/public/kits/<id>/)
  "presets": [
    {
      "id": "rock-100", "title": "Rock beat, 100 bpm",
      "kind": "groove",                  // groove | fill | song
      "style": "rock", "bpm": 100, "meter": "4/4", "bpb": 4,
      "bars": [2, 5],                    // real bars of the source file, 1-based, inclusive
      "source": "groove",                // groove (Groove MIDI Dataset) | author
      "credit": "Groove MIDI Dataset ... CC BY 4.0",
      "kit": "virtuosity-cc0",            // the kit id the preset plays with by default
      "midi": "presets/rock-100/rock-100.mid",    // the source cut to its bars; bar a starts at tick 0
      "motion": "presets/rock-100/rock-100.motion.json",
      "judgement": "presets/rock-100/rock-100.judgement.json",
      "played_pct": 100.0,               // from the judgement summary
      "collision_cuts": 0, "freezes": 0, "hard_frames": 0,
      "notes": "free text"
    }
  ]
}
```

Paths are relative to the page (`web/public/` in the repo); each preset has its own folder. `bpb` (quarter notes per bar: 3 for 3/4 and 6/8, 5 for 5/4) and the three counts are additions to the minimal schema. The cut `.mid` keeps the source tempo and ticks per beat, has one channel-9 track, and puts the first note of bar `a` at tick 0 (the motion's `chart.lead` seconds of lead-in are not in the cut).

## Kit index (`web/public/kits/index.json`)

```json
{ "kits": [ { "id": "virtuosity-cc0" } ] }
```

A static site cannot list folders, so this file does: each id names a folder `kits/<id>/` holding a `kit.json`, and the **first entry is the default kit**. `midi2motion serve --kit DIR` adds one entry, `{"id": "user", "name": ...}`, as the **first** entry (so it is the default) of the index it serves, and serves the folder under `kits/user/`. The kit file itself is described in [kits.md](kits.md).
