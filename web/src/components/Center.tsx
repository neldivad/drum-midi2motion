import { useCallback } from 'react';
import { Pause, Play, SkipBack, SkipForward, Repeat, Volume2, VolumeX, X, Orbit, ScanEye, Zap, Tag, Highlighter } from 'lucide-react';
import { S, useS } from '@/engine/state';
import { setS, togglePlay, step, setA, setB, clearAB, setCam, setOrbit, bindReadout, attachStage, attachTimeline, attachLane, barbeat } from '@/engine/player';
import { Button } from '@/components/ui/button';
import { Toggle } from '@/components/ui/toggle';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Slider } from '@/components/ui/slider';
import { Tip } from '@/components/ui/tooltip';
import { Pick, usePlayer } from './common';
import { cn } from '@/lib/utils';

const CAMS: [string, string][] = [['perf', 'Front'], ['grip', 'Hands'], ['side', 'Side'], ['feet', 'Feet'], ['top', 'Top']];

export function StageView({ className }: { className?: string }) {
  const st = usePlayer((v) => v.stage), clip = usePlayer((v) => v.clip), presets = usePlayer((v) => v.presets), hl = usePlayer((v) => v.hl), loadingTitle = usePlayer((v) => v.loadingTitle);
  const cam = useS((s) => s.cam), orbit = useS((s) => s.orbit), ov = useS((s) => s.ov);
  const m = clip && hl != null ? clip.R.mist[hl] : null;
  return (
    <section className={cn('relative min-h-0 overflow-hidden bg-stage', className)} aria-label="Stage">
      <div ref={useCallback((el: HTMLDivElement | null) => attachStage(el), [])} className="absolute inset-0" data-testid="stage" />
      <div ref={useCallback((el: HTMLDivElement | null) => bindReadout('hud', el), [])} aria-live="off" className="pointer-events-none absolute top-2.5 left-3 max-w-[70%] rounded bg-black/60 px-2 py-0.5 text-[13px] font-semibold empty:hidden" />
      <pre ref={useCallback((el: HTMLPreElement | null) => bindReadout('perf', el), [])} hidden className="pointer-events-none absolute top-2.5 right-2.5 m-0 rounded bg-black/75 px-2 py-1.5 font-mono text-[11.5px] leading-snug text-[#cfe]" />
      {m && <div className="pointer-events-none absolute right-3 bottom-12 left-3 z-[1] rounded bg-black/70 px-2.5 py-1 text-[12.5px]" data-testid="sel"><b style={{ color: m.col }}>{m.cat.toUpperCase()}</b> · {m.t.toFixed(2)} s · bar.beat {barbeat(m.t)} · {m.piece} · {m.reason}</div>}
      {st.status !== 'ready' && <div className="absolute inset-0 flex items-center justify-center gap-2.5 bg-stage text-muted-foreground">
        {st.status === 'loading' ? <><span className="size-4 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />Loading the drummer… {Math.round(st.progress * 100)} %</> : 'Could not load the drummer model. Reload to try again.'}</div>}
      {st.status === 'ready' && !clip && <div className="absolute inset-0 flex flex-col items-center justify-center p-4 text-center text-muted-foreground">
        {loadingTitle ? <p>{loadingTitle}</p> : <><p><b className="text-foreground">No clip on stage.</b></p><p>{presets.length ? 'Pick a preset' : 'Drop a .motion.json here'} to see the drummer.</p></>}</div>}
      <div className="absolute bottom-2 left-2 flex max-w-[calc(100%-1rem)] flex-wrap items-center gap-1 rounded-md bg-black/55 p-1 backdrop-blur-sm">
        <ToggleGroup type="single" size="sm" aria-label="Camera" value={CAMS.some(([c]) => c === cam) ? cam : ''} onValueChange={(v) => v && setCam(v)} data-testid="cams">
          {CAMS.map(([c, l]) => <ToggleGroupItem key={c} value={c} aria-label={`${l} camera`} data-cam={c}>{l}</ToggleGroupItem>)}
        </ToggleGroup>
        <span className="mx-0.5 h-4 w-px bg-border" />
        <Tip span label="Slowly circle the drummer"><Toggle size="sm" pressed={orbit} onPressedChange={setOrbit} data-testid="orbit"><Orbit />Orbit</Toggle></Tip>
        <Tip span label="See-through body"><Toggle size="sm" pressed={ov.xray} onPressedChange={(p) => setS(() => { S.ov.xray = p; })} data-testid="xray"><ScanEye />X-ray</Toggle></Tip>
        <Tip span label="Light up each drum as it is struck"><Toggle size="sm" pressed={ov.flash} onPressedChange={(p) => setS(() => { S.ov.flash = p; })} data-testid="flash"><Zap />Hit flash</Toggle></Tip>
        <Tip span label="Name the drums as they sound"><Toggle size="sm" pressed={ov.hud} onPressedChange={(p) => setS(() => { S.ov.hud = p; })} data-testid="names"><Tag />Names</Toggle></Tip>
        <Tip span label="On the note lane: freezes, crossed hands, habit boxes, splay and zone bands, collisions"><Toggle size="sm" pressed={ov.lane} onPressedChange={(p) => setS(() => { S.ov.lane = p; })} data-testid="lanemarks"><Highlighter />Lane marks</Toggle></Tip>
      </div>
    </section>
  );
}

export function Transport() {
  const playing = usePlayer((v) => v.playing), clip = usePlayer((v) => v.clip), kit = usePlayer((v) => v.kit), audio = usePlayer((v) => v.audio);
  const speed = useS((s) => s.speed), loop = useS((s) => s.loop), ab = useS((s) => s.ab), abA = useS((s) => s.abA), snd = useS((s) => s.sound);
  const lstat = abA != null ? `A ${abA.toFixed(2)} s · set B` : ab ? `A–B ${ab[0].toFixed(2)}–${ab[1].toFixed(2)} s${loop ? '' : ' (loop off)'}` : '';
  const off = snd.muted;
  return (
    <div className="grid gap-1.5 border-y bg-card px-3 py-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <Tip label="Play / pause (Space) · ←/→ frame · L loop · P perf HUD"><Button size="icon" data-testid="play" aria-label={playing ? 'Pause' : 'Play'} disabled={!clip} onClick={() => togglePlay()}>{playing ? <Pause /> : <Play />}</Button></Tip>
        <Tip label="One frame back (←)"><Button size="icon" variant="ghost" aria-label="One frame back" onClick={() => step(-1)}><SkipBack /></Button></Tip>
        <Tip label="One frame on (→)"><Button size="icon" variant="ghost" aria-label="One frame on" onClick={() => step(1)}><SkipForward /></Button></Tip>
        <div className="flex min-w-[9.5em] items-baseline gap-2 tabular-nums">
          <span ref={useCallback((el: HTMLSpanElement | null) => bindReadout('bb', el), [])} title="bar.beat" data-testid="bb">–</span>
          <span ref={useCallback((el: HTMLSpanElement | null) => bindReadout('tt', el), [])} className="text-xs text-muted-foreground" />
        </div>
        <ToggleGroup type="single" variant="outline" size="sm" aria-label="Speed" value={String(speed)} onValueChange={(v) => v && setS(() => { S.speed = +v; }, { anchor: true })} data-testid="speed">
          {[['0.25', '¼×'], ['0.5', '½×'], ['1', '1×']].map(([v, l]) => <ToggleGroupItem key={v} value={v} aria-label={`Speed ${l}`} data-v={v}>{l}</ToggleGroupItem>)}
        </ToggleGroup>
        <div className="flex flex-wrap items-center gap-1">
          <Tip span label="Loop (L): the whole clip, or A–B when set"><Toggle variant="outline" size="sm" pressed={loop} onPressedChange={(p) => setS(() => { S.loop = p; }, { anchor: true })} data-testid="loop"><Repeat />Loop</Toggle></Tip>
          <Tip label="Set loop point A at the playhead"><Button variant="outline" size="sm" onClick={setA} data-testid="la">A</Button></Tip>
          <Tip label="Set loop point B at the playhead"><Button variant="outline" size="sm" onClick={setB} data-testid="lb">B</Button></Tip>
          <Tip label="Clear A–B (loop the whole clip)"><Button variant="ghost" size="icon-sm" aria-label="Clear the A–B loop" disabled={!ab && abA == null} onClick={clearAB}><X /></Button></Tip>
          <span className="text-xs text-muted-foreground tabular-nums">{lstat}</span>
        </div>
      </div>
      <div className="cstack h-[76px]" ref={useCallback((el: HTMLDivElement | null) => { if (!el) attachTimeline(null, null); else attachTimeline(el.children[0] as HTMLCanvasElement, el.children[1] as HTMLCanvasElement); }, [])}>
        <canvas /><canvas aria-label="Timeline: drag to scrub" className="cursor-pointer touch-none" data-testid="timeline" />
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className="text-xs text-muted-foreground">Sound</span>
        <ToggleGroup type="single" variant="outline" size="sm" aria-label="Sound source" value={snd.mode} onValueChange={(v) => v && setS(() => { S.sound.mode = v; }, { anchor: true })} data-testid="sound-mode">
          <ToggleGroupItem value="off" data-v="off" title="Silent">Off</ToggleGroupItem>
          <ToggleGroupItem value="midi" data-v="midi" title="What should sound: the judged MIDI notes">MIDI</ToggleGroupItem>
          <ToggleGroupItem value="hits" data-v="hits" title="What was played: the drummer's measured hits">Performance</ToggleGroupItem>
          <ToggleGroupItem value="stack" data-v="stack" title="Stack: MIDI on the left, the performance on the right (a late hit reads as a flam)">Stack</ToggleGroupItem>
        </ToggleGroup>
        <Pick label="Sound engine" testid="sound-engine" className="w-28" value={snd.engine} onChange={(v) => setS(() => { S.sound.engine = v; }, { anchor: true })} items={[['samples', 'Samples'], ['synth', 'Synth']]} />
        <Vol label="MIDI" value={snd.vm} on={(v) => { S.sound.vm = v; }} testid="vol-midi" />
        <Vol label="Played" value={snd.vp} on={(v) => { S.sound.vp = v; }} testid="vol-played" />
        <Tip span label={!audio ? 'Sound starts with the first play' : off ? 'Sound is muted: click to unmute' : 'Mute'}>
          <Toggle size="sm" aria-label="Mute" pressed={off} onPressedChange={(p) => setS(() => { S.sound.muted = p; }, { anchor: true })} data-testid="mute">{off ? <VolumeX /> : <Volume2 />}</Toggle>
        </Tip>
        <span className="text-xs text-muted-foreground" title={kit.title}>{kit.name}</span>
      </div>
    </div>
  );
}
function Vol({ label, value, on, testid }: { label: string; value: number; on: (v: number) => void; testid: string }) {
  return (
    <label className="flex items-center gap-2 text-xs text-muted-foreground" title={`${label} volume`}>{label}
      <Slider className="w-20" min={0} max={1.5} step={0.05} value={[value]} aria-label={`${label} volume`} data-testid={testid}
        onValueChange={([v]) => setS(() => on(v))} onValueCommit={([v]) => setS(() => on(v), { anchor: true })} />
    </label>
  );
}

export function LaneBox({ className }: { className?: string }) {
  const zoom = useS((s) => s.zoom);
  return (
    <section className={cn('flex min-h-[90px] flex-col bg-stage', className)} aria-label="Note lane">
      <div className="flex min-w-0 items-center gap-2 px-3 py-1">
        <span className="text-xs text-muted-foreground">Notes</span>
        <ToggleGroup type="single" size="sm" aria-label="Lane zoom" value={String(zoom)} onValueChange={(v) => v && setS(() => { S.zoom = +v; })} data-testid="zoom">
          {['5', '2.5', '1.25'].map((v) => <ToggleGroupItem key={v} value={v} data-v={v} className="h-6 px-2">{v} s</ToggleGroupItem>)}
        </ToggleGroup>
        <span className="truncate text-xs text-muted-foreground">outline = the MIDI (verdict colour once judged) · fill = the stroke, limb colour · click to seek</span>
      </div>
      <canvas ref={useCallback((el: HTMLCanvasElement | null) => attachLane(el), [])} aria-label="Note lane: click to seek" className="block min-h-0 w-full flex-1 cursor-pointer" data-testid="lane" />
    </section>
  );
}
