# Drum kits: the sound, and how to bring your own

The motion does not need sound. The page plays the judged source notes through a **kit**, so you can hear whether the drummer lands on the beat. A kit is a folder of audio files and one `kit.json` that says which file plays for which piece and how hard it was hit.

## The bundled kit

`web/kits/virtuosity-cc0/` is a reduction of **Virtuosity Drums v0.925** by Versilian Studios LLC, released under **Creative Commons 0** (public domain dedication; licence text in `LICENSE.txt` next to the samples, project page [versilian-studios.com/virtuosity-drums](https://versilian-studios.com/virtuosity-drums/)). We took the overhead-microphone recordings and kept up to three velocity layers per piece, converted to mono Ogg Vorbis, trimmed to the length each piece rings and faded out, with one static gain per piece (the loudest layer peaks at -3 dBFS, cymbals and hi-hat lower) and the softest layers lifted to at most 14 dB under the loudest. The recorded kit has two toms, so `tom2` and `tom3` are pitch-shifted copies of the high and low toms (minus and plus three semitones); `floor` is the low tom unshifted. The sound is a jazz kit with the snares on for the kick, not a rock kit: it is for checking, not for mixing.

## The kit format

```json
{
  "id": "my-kit",
  "name": "My kit",
  "license": "CC0-1.0",
  "credit": "who made it",
  "url": "where it comes from",
  "pieces": {
    "kick":  [ { "file": "kick_soft.ogg", "vel": [1, 70] },  { "file": "kick_hard.ogg", "vel": [71, 127] } ],
    "snare": [ { "file": "snare.ogg", "vel": [1, 127] } ],
    "hat":   [ ... ]
  }
}
```

- `file` is relative to the folder and may sit in a subfolder (`kick/kick_1.ogg`). Ogg Vorbis or Opus, MP3 or WAV: anything a browser decodes. Keep the whole folder small (the bundled kit is under 4 MB).
- `vel` is the inclusive MIDI velocity range (1 to 127) the file is used for. Give a piece a few layers at most. If several ranges overlap, the first match wins; if none matches, the nearest layer is used.
- `id`, `name`, `license`, `credit` and `url` are shown by the page. Say what you may redistribute.

## The piece keys

The keys are the **piece ids the motion JSON's notes use** (`notes: [[time, row, velocity, zone], ...]`, see [formats.md](formats.md)). A piece may also be keyed `row:zone` for a specific articulation; the page looks up `row:zone` first and then `row`.

| key | used for |
|---|---|
| `kick` | the kick drum |
| `snare` | the snare head (also the fallback for its zones) |
| `snare:cross` | cross-stick (a stick laid across the head, MIDI note 37) |
| `snare:rimshot` | rim shot (note 40) |
| `hat` | closed hi-hat (also the fallback for the other hi-hat zones) |
| `hat:open` | open hi-hat (note 46) |
| `hatped` | the hi-hat pedal "chick" (note 44) |
| `tom1`, `tom2`, `tom3` | the three rack toms, high to low |
| `floor` | the floor tom |
| `crash` | crash cymbal |
| `ride` | ride bow (the fallback for `ride:bell`) |
| `ride:bell` | ride bell (note 53) |

A piece with no entry is silent. A kit needs at minimum `kick`, `snare`, `hat`, `crash` and `ride` to be useful; the bundled kit provides every key above.

## Bring your own kit

1. Make a folder with your samples and a `kit.json` as above.
2. Run `midi2motion serve --kit ./my-kit`.
3. The page lists your kit as `user`. The folder is served from `127.0.0.1` only, read-only, from where it is: nothing is uploaded and nothing is copied into the repo.

This is for a local install only. Do not commit samples you may not redistribute: commercial drum libraries are licensed to you, not to the people who clone your repo. If you can share your kit, put it in `web/kits/<id>/`, add its id to `web/kits/index.json` and keep its licence text beside it.

## Finding a kit that may be redistributed

We looked for a kit with a licence page we could read, covering kick, snare, cross-stick, three hi-hat states, toms, crash, ride and bell. The other kits we checked (SM Drums: public domain, 2.2 GB; the Karoryfer CC0 kits Big Rusty, Swirly and Frankensnare: CC0 but each 1 to 2 GB and unusual kits; Salamander and DRS: licences with attribution or share-alike terms) either were not complete or were not CC0. Virtuosity Drums was the CC0 kit that matched the piece list. Its zip is 1.2 GB; we fetched only the files we kept.
