"""midiutil.py: small MIDI helpers around mido: the meter argument, and cutting a bar window out of a file (for the presets)."""
import pathlib, re

import mido


def parse_meter(m):
    """quarter notes per bar from '4', '3', '2.5', or a time signature '6/8' '3/4' '5/4' '5/8' '12/8' (n/d -> n * 4 / d)"""
    if m is None: return 4.0
    if isinstance(m, (int, float)): return float(m)
    m = str(m).strip()
    f = re.fullmatch(r"(\d+)\s*/\s*(\d+)", m)
    if f: return int(f.group(1)) * 4.0 / int(f.group(2))
    return float(m)


def meter_label(bpb):
    """the time signature a bpb stands for: 4 -> 4/4, 3 -> 3/4, 5 -> 5/4, 2.5 -> 5/8 (6/8 is also bpb 3: the caller knows)"""
    return {4.0: "4/4", 3.0: "3/4", 5.0: "5/4", 2.5: "5/8", 2.0: "2/4", 6.0: "6/4"}.get(float(bpb), f"{bpb:g} quarter notes")


def tempo_bpm(path):
    m = mido.MidiFile(str(path))
    for tr in m.tracks:
        for msg in tr:
            if msg.type == "set_tempo": return round(60e6 / msg.tempo, 2)
    return 120.0


def cut_window(src, dst, bars, bpb=4.0, ts=None):
    """write the notes of real bars [a, b] (1-based, inclusive) of `src` to `dst`, shifted so bar a starts at tick 0. Tempo and ticks per beat are kept; one channel-9 drum track; ts = the time signature to write ("6/8")."""
    m = mido.MidiFile(str(src)); tpb = m.ticks_per_beat; bar = int(round(bpb * tpb)); lo, hi = (bars[0] - 1) * bar, bars[1] * bar
    tempo = None; ev = []
    for tr in m.tracks:
        t = 0
        for msg in tr:
            t += msg.time
            if msg.type == "set_tempo" and tempo is None: tempo = msg.tempo
            if msg.type in ("note_on", "note_off") and lo <= t < hi + (tpb // 8 if msg.type == "note_off" else 0):
                ev.append((t - lo, 1 if (msg.type == "note_on" and msg.velocity > 0) else 0, msg.note, msg.velocity))
    ev.sort(key=lambda e: (e[0], e[1]))
    out = mido.MidiFile(ticks_per_beat=tpb); tr = mido.MidiTrack(); out.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=tempo or 500000, time=0))
    num, den = (int(x) for x in ts.split("/")) if ts else ((int(bpb), 4) if bpb == int(bpb) else (int(bpb * 2), 8))
    tr.append(mido.MetaMessage("time_signature", numerator=num, denominator=den, time=0))
    last = 0
    for t, on, note, v in ev:
        tr.append(mido.Message("note_on" if on else "note_off", channel=9, note=note, velocity=v if on else 0, time=t - last)); last = t
    pathlib.Path(dst).parent.mkdir(parents=True, exist_ok=True); out.save(str(dst))
    return dict(notes=sum(1 for e in ev if e[1]), ticks_per_beat=tpb, bpm=round(60e6 / (tempo or 500000), 2))
