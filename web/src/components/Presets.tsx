import { useEffect, useMemo, useRef } from 'react';
import { SlidersHorizontal, X } from 'lucide-react';
import { S, save, useS } from '@/engine/state';
import { setS, loadPreset, visiblePresets, fmtMeter, played, SRC_LABEL, type Preset } from '@/engine/player';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { Pick, usePlayer } from './common';
import { cn } from '@/lib/utils';

const KIND_TONE: Record<string, string> = { groove: 'bg-[#1f3326] text-[#8fe0ad]', fill: 'bg-[#3a2d18] text-[#f2c07a]', song: 'bg-[#2b2347] text-[#b8a6ff]' };
const SORTS: [string, string][] = [['worst', 'Worst first'], ['best', 'Best first'], ['worst_orn', 'Worst first (ornament-aware)'], ['style', 'Style'], ['bpm', 'Tempo'], ['name', 'Name']];
const uniq = (a: any[]) => [...new Set(a.filter((x) => x != null && x !== ''))].sort() as string[];

export function PresetPanel({ phone = false }: { phone?: boolean }) {
  const presets = usePlayer((v) => v.presets), man = usePlayer((v) => v.man);
  const f = useS((s) => s.f), sort = useS((s) => s.sort), clip = useS((s) => s.clip), open = useS((s) => s.panels.filters);
  const vis = useMemo(() => visiblePresets(presets), [presets, f, sort]); // eslint-disable-line react-hooks/exhaustive-deps
  const opts = useMemo(() => ({
    style: uniq(presets.map((p) => p.style)).map((s) => [s, s] as [string, string]),
    meter: uniq(presets.map((p) => fmtMeter(p.meter))).map((s) => [s, s] as [string, string]),
    source: uniq(presets.map((p) => p.source)).map((s) => [s, SRC_LABEL[s] || s] as [string, string]),
  }), [presets]);
  const anyF = Object.values(f).some(Boolean);
  const setF = (k: keyof typeof S.f, v: string) => setS(() => { S.f[k] = v; });
  const vp = useRef<HTMLDivElement>(null);
  useEffect(() => { if (presets.length && vp.current) vp.current.scrollTop = S.scroll || 0; }, [presets.length]);
  const listRef = useRef<HTMLDivElement>(null);
  const onKey = (e: React.KeyboardEvent, p: Preset) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); loadPreset(p); }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); e.stopPropagation(); const i = vis.indexOf(p) + (e.key === 'ArrowDown' ? 1 : -1); const n = vis[i];
      if (n) { (listRef.current?.querySelector(`[data-id="${CSS.escape(n.id)}"]`) as HTMLElement | null)?.focus(); loadPreset(n); } }
  };
  return (
    <aside className="flex h-full min-h-0 flex-col bg-card" aria-label="Presets">
      <Collapsible open={open} onOpenChange={(o) => setS(() => { S.panels.filters = o; })}>
        <div className="flex items-center gap-2 px-3 pt-3 pb-1.5">
          <h2 className="text-sm font-semibold">Presets</h2>
          <span className="text-xs text-muted-foreground tabular-nums">{presets.length ? (vis.length === presets.length ? presets.length : `${vis.length} of ${presets.length}`) : ''}</span>
          <CollapsibleTrigger asChild><Button variant="ghost" size="sm" className="ml-auto text-muted-foreground" aria-label="Show or hide the filters"><SlidersHorizontal />Filters</Button></CollapsibleTrigger>
        </div>
        <CollapsibleContent className="grid gap-1.5 border-b px-3 pb-2.5">
          <Input type="search" data-testid="f-q" placeholder="Search title, style, author…" autoComplete="off" aria-label="Search presets" value={f.q} onChange={(e) => setF('q', e.target.value.trimStart())} />
          <div className="grid grid-cols-2 gap-1.5">
            <Pick label="Kind" testid="f-kind" value={f.kind} onChange={(v) => setF('kind', v)} items={[['', 'Any kind'], ['groove', 'Groove'], ['fill', 'Fill'], ['song', 'Song']]} />
            <Pick label="Style" testid="f-style" value={f.style} onChange={(v) => setF('style', v)} items={[['', 'Any style'], ...withCur(opts.style, f.style)]} />
            <Pick label="Meter" testid="f-meter" value={f.meter} onChange={(v) => setF('meter', v)} items={[['', 'Any meter'], ...withCur(opts.meter, f.meter)]} />
            <Pick label="Source" testid="f-source" value={f.source} onChange={(v) => setF('source', v)} items={[['', 'Any source'], ...withCur(opts.source, f.source)]} />
          </div>
          <div className="flex items-center gap-1.5">
            <Pick label="Sort" testid="f-sort" value={sort} onChange={(v) => setS(() => { S.sort = v; })} items={SORTS} className="flex-1" />
            {anyF && <Button variant="ghost" size="sm" data-testid="f-clear" onClick={() => setS(() => { for (const k of Object.keys(S.f)) (S.f as any)[k] = ''; })}><X />Clear</Button>}
          </div>
        </CollapsibleContent>
      </Collapsible>
      <ScrollArea data-testid="preset-list" className={cn('min-h-0 flex-1', phone && 'max-h-80')} viewportRef={vp}
        viewportProps={{ onScroll: (e) => { S.scroll = Math.round((e.target as HTMLElement).scrollTop); save(); } }}>
        <div ref={listRef} role="listbox" aria-label="Preset clips" className="grid gap-0.5 p-1.5">
          {!presets.length && <div className="p-2 text-sm text-muted-foreground">{man === false ? 'No presets are published yet. Drop a motion file to play one.' : 'Loading presets…'}</div>}
          {!!presets.length && !vis.length && <div className="p-2 text-sm text-muted-foreground">No preset matches these filters.</div>}
          {vis.map((p) => <PresetRow key={p.id} p={p} on={p.id === clip} onKey={onKey} />)}
        </div>
      </ScrollArea>
      <div className="m-2 rounded-md border border-dashed p-2.5 text-xs text-muted-foreground">
        <b className="text-foreground">Your own drums</b>
        <p className="mt-1">Drop a <code>.mid</code> to chart it and get the solve command, or a <code>.motion.json</code> to play it.</p>
      </div>
    </aside>
  );
}
const withCur = (o: [string, string][], cur: string): [string, string][] => (cur && !o.some(([v]) => v === cur) ? [...o, [cur, cur]] : o);

function PresetRow({ p, on, onKey }: { p: Preset; on: boolean; onKey: (e: React.KeyboardEvent, p: Preset) => void }) {
  const pct = played(p.played_pct), bars = Array.isArray(p.bars) ? `bars ${p.bars[0]}–${p.bars[1]}` : '';
  return (
    <div role="option" tabIndex={0} aria-selected={on} data-id={p.id} onClick={() => loadPreset(p)} onKeyDown={(e) => onKey(e, p)}
      className={cn('grid cursor-pointer grid-cols-[minmax(0,1fr)_auto] gap-x-2 gap-y-0.5 rounded-md border border-transparent px-2.5 py-2 outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring/60', on && 'border-[#34406a] bg-accent')}>
      <span className="truncate font-semibold">{p.title || p.id}</span>
      <span className={cn('row-span-2 self-center text-xs tabular-nums text-muted-foreground', pct === 100 && 'text-ok')} title="notes played">{pct != null ? `${pct.toFixed(pct === 100 ? 0 : 1)} %` : ''}</span>
      <span className="flex min-w-0 items-center gap-1.5 truncate text-xs text-muted-foreground">
        {p.kind && <Badge variant="secondary" className={cn('uppercase tracking-wide text-[10px]', KIND_TONE[p.kind])}>{p.kind}</Badge>}
        <span className="truncate">{[p.style, p.bpm ? Math.round(p.bpm) + ' bpm' : '', fmtMeter(p.meter), bars].filter(Boolean).join(' · ')}</span>
      </span>
    </div>
  );
}
