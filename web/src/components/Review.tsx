import { memo, useCallback, useLayoutEffect, useMemo } from 'react';
import { ChevronDown, Repeat } from 'lucide-react';
import { S, useS } from '@/engine/state';
import { setS, jumpTo, loopMistake, attachCum, bindReadout, remarkPast, barbeat, fmtMeter, played, SRC_CREDIT, drums } from '@/engine/player';
import { filterMist, series, COL, CATS, TYPES } from '@/engine/review';
import { PCOL, VCOL, LABEL } from '@/engine/lanes';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Tip } from '@/components/ui/tooltip';
import { Chip, usePlayer } from './common';
import { cn } from '@/lib/utils';

export function ReviewPanel({ phone = false }: { phone?: boolean }) {
  if (phone) return (
    <div className="grid gap-2 p-2"><Info /><TallyCard /><Mistakes phone /></div>
  );
  return (
    <aside className="flex h-full min-h-0 flex-col gap-2 bg-background p-2" aria-label="Check">
      <ScrollArea className="max-h-[58%] shrink-0"><div className="grid gap-2"><Info /><TallyCard /></div></ScrollArea>
      <Mistakes />
    </aside>
  );
}

function Info() {
  const clip = usePlayer((v) => v.clip), kitName = usePlayer((v) => v.kit.name), presets = usePlayer((v) => v.presets), loadingTitle = usePlayer((v) => v.loadingTitle), open = useS((s) => s.panels.info);
  const body = useMemo(() => {
    if (!clip) return null;
    const { M, J, meta, G } = clip, m = meta || {};
    const credit = m.credit || SRC_CREDIT[m.source] || (clip.kind === 'file' ? `Your file: ${m.file}` : '');
    const kitc = drums.kit ? `Drum sounds: ${drums.kit.name || drums.kit.id}${drums.kit.license ? ` (${drums.kit.license})` : ''}` : '';
    const A = J && J.tally && J.tally.all, pct = played(A ? A.accuracy_pct : m.played_pct ?? (M.remedy && M.remedy.played_pct));
    const bpm = m.bpm || (G ? 60 / G.beat : null), meter = fmtMeter(m.meter) || (G ? fmtMeter(G.bpb) : ''), bars = Array.isArray(m.bars) ? m.bars : M.chart && M.chart.bars;
    return { title: m.title || M.title || M.key || 'Motion', lines: [credit, kitc, typeof m.notes === 'string' ? m.notes : ''].filter(Boolean), pct, bpm, meter, bars, n: J ? clip.marks.filter((x: any) => x.cls !== 'none').length : clip.notes.length };
  }, [clip, kitName]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Card className="gap-1.5 py-2.5">
      <Collapsible open={open} onOpenChange={(o) => setS(() => { S.panels.info = o; })}>
        <CardHeader>
          <CardTitle className="min-w-0 flex-1 truncate" data-testid="ititle">{body ? body.title : loadingTitle || (presets.length ? 'Pick a preset' : 'No clip yet')}</CardTitle>
          <CollapsibleTrigger asChild><Button variant="ghost" size="icon-sm" aria-label={open ? 'Hide the clip details' : 'Show the clip details'}><ChevronDown className={cn('transition-transform', !open && '-rotate-90')} /></Button></CollapsibleTrigger>
        </CardHeader>
        <CollapsibleContent>
          {body && <CardContent className="grid gap-2 pt-1.5">
            <div className="grid gap-0.5 text-xs text-muted-foreground">{body.lines.map((x, i) => <div key={i}>{x}</div>)}</div>
            <div className="flex flex-wrap gap-1.5">
              <Chip k="played" v={body.pct != null ? `${body.pct.toFixed(body.pct === 100 ? 0 : 1)} %` : null} tone={body.pct === 100 ? 'ok' : body.pct != null && body.pct < 90 ? 'warn' : ''} />
              <Chip k="tempo" v={body.bpm ? `${Math.round(body.bpm)} bpm` : null} /><Chip k="meter" v={body.meter} />
              <Chip k="bars" v={body.bars ? `${body.bars[0]}–${body.bars[1]}` : null} /><Chip k="length" v={`${clip.dur.toFixed(1)} s`} /><Chip k="notes" v={body.n} />
            </div>
            <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
              {clip.rows.map((id: string) => <span key={id}><i className="sw" style={{ background: PCOL[id] || '#888' }} />{LABEL[id] || id}</span>)}
              {clip.J ? <><span><i className="sw" style={{ background: VCOL.missed }} />missed</span><span><i className="sw" style={{ border: `1px solid ${VCOL.wrong}` }} />wrong drum</span></> : <span>(no judgement file: every note shown as played)</span>}
            </div>
          </CardContent>}
        </CollapsibleContent>
      </Collapsible>
    </Card>
  );
}

const EXT: [string, string][] = [['collision', 'collisions'], ['freeze', 'freezes'], ['crossed', 'crossed'], ['habit', 'habits'], ['splay', 'splay runs'], ['zone', 'zone runs']];
function TallyCard() {
  const clip = usePlayer((v) => v.clip), T = usePlayer((v) => v.tally), tview = useS((s) => s.tview);
  const legend = useMemo(() => { const s = clip ? series(clip.R) : {}; return TYPES.filter(([k]) => s[k] && s[k].length).map(([k, l, c]) => ({ k, l, c, n: s[k].length })); }, [clip]);
  const cumRef = useCallback((el: HTMLDivElement | null) => { if (!el) attachCum(null, null); else attachCum(el.children[0] as HTMLCanvasElement, el.children[1] as HTMLCanvasElement); }, []);
  const limbs = clip && clip.J ? Object.fromEntries((clip.J.limbs || []).map((l: any) => [l.id, l])) : {};
  return (
    <Card className="gap-1.5 py-2.5" data-testid="tally">
      <Tabs value={tview} onValueChange={(v) => setS(() => { S.tview = v; })} className="gap-1.5">
        <CardHeader><CardTitle className="flex-1">Tally to the playhead</CardTitle>
          <TabsList aria-label="Tally view"><TabsTrigger value="cat">By category</TabsTrigger><TabsTrigger value="limb">Per limb</TabsTrigger></TabsList></CardHeader>
        <CardContent>
          {!clip ? null : !clip.J ? <p className="text-xs text-muted-foreground">No judgement file: drop the clip's .judgement.json with it to see the tally.</p> : T && <>
            <TabsContent value="cat">
              <table className="tally w-full border-collapse text-[12.5px] tabular-nums"><tbody>
                {pairs([...CATS.map((k) => [k, k, T.c[k]] as [string, string, number]), ...EXT.map(([k, l]) => [k, l, T.ext[k]] as [string, string, number])]).map((row, i) => (
                  <tr key={i}>{row.map((c, j) => c ? [<td key={j + 'a'} className={c[2] ? '' : 'z'}><span className="sw" style={{ background: COL[c[0]] }} />{c[1]}</td>, <td key={j + 'b'} className={cn('n', !c[2] && 'z')}>{c[2]}</td>] : [<td key={j + 'a'} />, <td key={j + 'b'} />])}</tr>))}
                {Object.keys(T.by).length > 0 && <tr className="sub"><td colSpan={4}>missed by: {Object.entries(T.by).map(([l, v]) => `${l} ${v}`).join(' · ')}</td></tr>}
                <tr className="sum"><td colSpan={3}>notes judged so far · played</td><td className="n">{T.notes} · {T.acc.toFixed(1)} %</td></tr>
                {T.orn != null && <tr className="sum"><td colSpan={3}>played, ornament-aware</td><td className="n">{T.orn.toFixed(1)} %</td></tr>}
              </tbody></table>
            </TabsContent>
            <TabsContent value="limb">
              <table className="tally w-full border-collapse text-[12.5px] tabular-nums"><tbody>
                <tr><th>limb</th><th>hit</th><th>missed</th><th>wrong</th><th>extra</th></tr>
                {Object.entries(T.lb).map(([l, v]) => { const L: any = limbs[l]; return <tr key={l}><td><span className="sw" style={{ background: L ? `rgb(${L.color})` : '#555' }} />{L ? L.label.toLowerCase() : 'no limb (cut before a limb had it)'}</td><td className="n">{v[0]}</td><td className="n">{v[1]}</td><td className="n">{v[3]}</td><td className="n">{v[2]}</td></tr>; })}
              </tbody></table>
            </TabsContent>
          </>}
          <div className="cstack mt-2 h-[110px] overflow-hidden rounded" ref={cumRef}><canvas /><canvas /></div>
          <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">{legend.map((x) => <span key={x.k}><i className="sw" style={{ background: x.c }} />{x.l} {x.n}</span>)}</div>
        </CardContent>
      </Tabs>
    </Card>
  );
}
const pairs = <T,>(a: T[]) => { const o: (T | null)[][] = []; for (let i = 0; i < a.length; i += 2) o.push([a[i], a[i + 1] ?? null]); return o; };

const MF: [keyof typeof S.mf, string, string?][] = [['col', 'collisions'], ['soft', 'softer / simplified'], ['good', 'good (≤ 67 ms)'], ['frz', 'freezes / crossed / splay / habits / zones'], ['orn', 'hide ornament notes costing < 0.5', 'R-527: ornament notes after the transient whose cost is under 0.5']];
function Mistakes({ phone = false }: { phone?: boolean }) {
  const clip = usePlayer((v) => v.clip), hl = usePlayer((v) => v.hl), mf = useS((s) => s.mf), mfKey = useS((s) => Object.values(s.mf).join());
  const shown = useMemo(() => (clip ? filterMist(clip.R, S.mf) : []), [clip, mfKey]); // eslint-disable-line react-hooks/exhaustive-deps
  useLayoutEffect(() => { remarkPast(); }, [shown, hl]);
  const listRef = useCallback((el: HTMLDivElement | null) => bindReadout('mlist', el), []);
  return (
    <Card className={cn('min-h-0 gap-1.5 py-2.5', !phone && 'flex-1')}>
      <CardHeader><CardTitle>Mistakes <span className="font-normal text-muted-foreground" data-testid="nmist">{clip ? `(${shown.length})` : ''}</span></CardTitle><span className="ml-auto text-xs text-muted-foreground">click: jump there at ¼×</span></CardHeader>
      <CardContent className="grid gap-1.5">
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
          {MF.map(([k, l, t]) => <label key={k} className="flex items-center gap-1.5" title={t}><Checkbox checked={mf[k]} onCheckedChange={(c) => setS(() => { S.mf[k] = c === true; })} data-testid={`mf-${k}`} />{l}</label>)}
        </div>
        <Tip label="Loop 1 s before to 1 s after the selected mistake"><Button variant="outline" size="sm" className="justify-self-start" disabled={hl == null} onClick={loopMistake} data-testid="mloop"><Repeat />Loop ±1 s around the selected mistake</Button></Tip>
      </CardContent>
      <ScrollArea className={cn('min-h-0', phone ? 'h-72' : 'flex-1')} data-testid="mist-list">
        <div ref={listRef} role="list" className="px-2">
          {clip && !shown.length && <div className="px-1 py-2 text-xs text-muted-foreground">{clip.J ? 'No mistakes under these filters.' : 'No judgement file.'}</div>}
          {shown.map((m: any) => <MistRow key={m.i} m={m} cur={hl === m.i} lshort={clip.R.lshort} />)}
        </div>
      </ScrollArea>
    </Card>
  );
}
// memoised rows: a selection re-renders two of them; the "past" marks are a data attribute the engine sets (no render)
const MistRow = memo(function MistRow({ m, cur, lshort }: { m: any; cur: boolean; lshort: Record<string, string> }) {
  return (
    <div role="listitem" tabIndex={0} data-i={m.i} data-cur={cur || undefined} onClick={() => jumpTo(m.i)} onKeyDown={(e) => { if (e.key === 'Enter') jumpTo(m.i); }}
      className="mi grid cursor-pointer grid-cols-[3.6em_2.6em_minmax(0,1fr)] gap-x-1.5 border-b border-[#1f2130] px-1 py-1 text-[12.5px] tabular-nums outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/60">
      <span>{m.t.toFixed(2)}</span><span className="text-muted-foreground">{barbeat(m.t)}</span>
      <span className="truncate"><span className="sw" style={{ background: m.col }} /><span className="font-semibold tracking-wide" style={{ color: m.col }}>{m.cat}</span> {m.piece}{m.limbs.length ? ' · ' + m.limbs.map((l: string) => lshort[l] || l).join('+') : ''}</span>
      {m.reason && <span className="col-start-3 text-[11.5px] break-words text-muted-foreground">{m.reason}</span>}
    </div>
  );
});
