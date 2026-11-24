import { useCallback, useRef, useState } from 'react';
import { Copy, Check, Headphones, Square, FileUp } from 'lucide-react';
import { useS } from '@/engine/state';
import { setRange, toggleListen, closeMidi, attachChart, solveCommand, solveEstimate } from '@/engine/player';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Chip, usePlayer } from './common';

export function MidiDialog({ onChoose }: { onChoose: () => void }) {
  const open = useS((s) => s.panels.midi), A = usePlayer((v) => v.midi), err = usePlayer((v) => v.midiError), range = usePlayer((v) => v.range), listening = usePlayer((v) => v.listen);
  const [copied, setCopied] = useState('');
  const cmdRef = useRef<HTMLElement>(null);
  const chartRef = useCallback((el: HTMLCanvasElement | null) => attachChart(el), []);
  const cmd = A ? solveCommand(A, range) : '';
  const dropped = A ? [...A.dropped.values()].reduce((a, b) => a + b, 0) : 0;
  const copy = async () => {
    let ok = false;
    try { await navigator.clipboard.writeText(cmd); ok = true; } catch { try { const r = document.createRange(); r.selectNodeContents(cmdRef.current!); const sel = getSelection()!; sel.removeAllRanges(); sel.addRange(r); ok = document.execCommand('copy'); } catch { /* selected for a manual copy */ } }
    setCopied(ok ? 'Copied' : 'Select + copy'); setTimeout(() => setCopied(''), 1600);
  };
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) closeMidi(); }}>
      <DialogContent className="grid-rows-[auto_minmax(0,1fr)]" data-testid="midi-dialog">
        <DialogHeader><DialogTitle>{A ? `Your MIDI: ${A.name}` : 'Upload a MIDI'}</DialogTitle>
          <DialogDescription>Your MIDI is read here in the browser; nothing is uploaded anywhere. The solver runs on your own machine (minutes per clip), and you drop its result back on this page.</DialogDescription></DialogHeader>
        <ScrollArea className="min-h-0">
          {!A ? <div className="grid justify-items-start gap-2 py-2">{err && <p className="text-sm text-bad">{err}</p>}<Button onClick={onChoose}><FileUp />Choose a .mid file</Button></div> : <div className="grid min-w-0 gap-3">
            <div className="flex flex-wrap gap-1.5">
              <Chip k="tempo" v={`${Math.round(A.bpm)} bpm${A.tempoChanges ? ' (changes)' : ''}`} /><Chip k="meter" v={A.sig + (A.sigChanges ? ' (changes)' : '')} />
              <Chip k="bars" v={A.nbars} /><Chip k="drum notes" v={A.notes.length} /><Chip k="read from" v={A.channel} />
              {dropped > 0 && <span title={`pitches: ${[...A.dropped.keys()].join(', ')}`}><Chip k="left out" v={dropped} tone="warn" /></span>}
            </div>
            <ScrollArea className="w-full rounded"><canvas ref={chartRef} aria-label="Notes by drum and bar: drag across bars to pick the range" className="block touch-none" data-testid="chart" /></ScrollArea>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <label className="flex items-center gap-1.5">Bars <Input type="number" min={1} max={A.nbars} inputMode="numeric" className="h-7 w-16" value={range[0]} data-testid="b0" onChange={(e) => setRange(+e.target.value, Math.max(+e.target.value, range[1]))} /></label>
              <label className="flex items-center gap-1.5">to <Input type="number" min={1} max={A.nbars} inputMode="numeric" className="h-7 w-16" value={range[1]} data-testid="b1" onChange={(e) => setRange(Math.min(range[0], +e.target.value), +e.target.value)} /></label>
              <span className="text-muted-foreground">of {A.nbars}</span>
              <Button variant="outline" size="sm" onClick={toggleListen} data-testid="listen">{listening ? <><Square />Stop</> : <><Headphones />Listen</>}</Button>
              <span className="text-xs text-muted-foreground">{solveEstimate(A, range)}</span>
            </div>
            <ol className="ml-5 grid list-decimal gap-2 text-sm">
              <li>Run this where <code>midi2motion</code> is installed:
                <div className="mt-1.5 flex min-w-0 items-stretch gap-2">
                  <ScrollArea className="min-w-0 flex-1 rounded bg-muted"><code ref={cmdRef} className="block bg-transparent px-2.5 py-1.5 whitespace-nowrap" data-testid="cmd">{cmd}</code></ScrollArea>
                  <Button variant="secondary" size="sm" className="h-auto" onClick={copy} data-testid="copy">{copied === 'Copied' ? <Check /> : <Copy />}{copied || 'Copy'}</Button>
                </div></li>
              <li>Drop the <code>.motion.json</code> it writes on this page (and its <code>.judgement.json</code>, for the hit/miss lanes).</li>
            </ol>
            {(dropped > 0 || A.sigChanges || !A.notes.length) && <p className="text-xs text-muted-foreground">
              {dropped ? `${dropped} notes are on pitches the solver leaves out (${[...A.dropped.keys()].slice(0, 8).join(', ')}): claps, extra percussion or non-drum parts. ` : ''}
              {A.sigChanges ? 'The meter changes in this file: the solver counts bars in the first meter. ' : ''}{A.notes.length ? '' : 'No drum notes found.'}</p>}
            <div><Button variant="ghost" size="sm" onClick={onChoose}><FileUp />Choose another file</Button></div>
          </div>}
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}

const KEYS: [string, string][] = [['Space', 'play / pause'], ['← / →', 'one frame back / on'], ['L', 'loop on / off'], ['P', 'the perf HUD (or ?perf in the URL)'], ['Tab', 'move between controls; Enter or Space presses one']];
export function HelpDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader><DialogTitle>How this page works</DialogTitle>
          <DialogDescription>A 3D drummer plays solved drum MIDI. Nothing plays until you press play.</DialogDescription></DialogHeader>
        <div className="grid gap-3 text-sm">
          <ul className="ml-4 grid list-disc gap-1 text-muted-foreground">
            <li><b className="text-foreground">Presets</b>: pick one on the left; filters, camera, speed, loop and sizes stay as you set them.</li>
            <li><b className="text-foreground">Upload MIDI</b>: chart a .mid, pick bars, copy the <code>midi2motion solve</code> command.</li>
            <li><b className="text-foreground">Drop motion file</b>: play a .motion.json (with its .judgement.json for the hit/miss lanes).</li>
            <li><b className="text-foreground">Check</b>: the tally to the playhead, the cumulative errors, and the mistakes (click one to jump there at ¼×).</li>
            <li>The state lives in the URL (shareable) and this browser; drag the panel edges to resize, double-click an edge to reset it.</li>
          </ul>
          <table className="text-sm"><tbody>{KEYS.map(([k, v]) => <tr key={k}><td className="py-0.5 pr-4"><kbd className="rounded border bg-muted px-1.5 py-px font-mono text-xs">{k}</kbd></td><td className="text-muted-foreground">{v}</td></tr>)}</tbody></table>
        </div>
      </DialogContent>
    </Dialog>
  );
}
