import { useEffect, useRef, useState } from 'react';
import { ChevronDown, CircleHelp, FileJson, FileMusic } from 'lucide-react';
import type { ImperativePanelHandle } from 'react-resizable-panels';
import { S, DEFAULTS, save, useS } from '@/engine/state';
import { setS, handleFiles, openMidi } from '@/engine/player';
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable';
import { Button } from '@/components/ui/button';
import { Tip, TooltipProvider } from '@/components/ui/tooltip';
import { Toaster } from '@/components/ui/sonner';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { PresetPanel } from '@/components/Presets';
import { StageView, Transport, LaneBox } from '@/components/Center';
import { ReviewPanel } from '@/components/Review';
import { MidiDialog, HelpDialog } from '@/components/Dialogs';
import { useIsPhone } from '@/components/common';
import { cn } from '@/lib/utils';

function Logo() {
  return <svg viewBox="0 0 32 32" width="22" height="22" aria-hidden="true"><ellipse cx="16" cy="12" rx="12" ry="5" fill="var(--primary)" /><path d="M4 12v9c0 2.8 5.4 5 12 5s12-2.2 12-5v-9" fill="none" stroke="var(--primary)" strokeWidth="2.5" /></svg>;
}

export default function App() {
  const phone = useIsPhone();
  const midiIn = useRef<HTMLInputElement>(null), motionIn = useRef<HTMLInputElement>(null);
  const [help, setHelp] = useState(false), [veil, setVeil] = useState(false);
  const chooseMidi = () => midiIn.current?.click();
  useEffect(() => {      // drop files anywhere on the page
    let depth = 0;
    const enter = (e: DragEvent) => { if (![...(e.dataTransfer?.types || [])].includes('Files')) return; depth++; setVeil(true); };
    const leave = () => { depth = Math.max(0, depth - 1); if (!depth) setVeil(false); };
    const over = (e: DragEvent) => e.preventDefault();
    const drop = (e: DragEvent) => { e.preventDefault(); depth = 0; setVeil(false); handleFiles([...(e.dataTransfer?.files || [])]); };
    window.addEventListener('dragenter', enter); window.addEventListener('dragleave', leave); window.addEventListener('dragover', over); window.addEventListener('drop', drop);
    return () => { window.removeEventListener('dragenter', enter); window.removeEventListener('dragleave', leave); window.removeEventListener('dragover', over); window.removeEventListener('drop', drop); };
  }, []);
  return (
    <TooltipProvider>
      <div className={cn('flex flex-col', phone ? 'min-h-dvh' : 'h-dvh overflow-hidden')}>
        <header className="flex flex-none flex-wrap items-center justify-between gap-3 border-b bg-card px-4 py-2">
          <div className="flex min-w-0 items-center gap-2" data-testid="brand"><Logo /><b className="text-base tracking-tight">midi2motion</b><span className="truncate text-[13px] text-muted-foreground max-sm:hidden">a 3D drummer that plays drum MIDI</span></div>
          <div className="flex flex-wrap gap-1.5">
            <Tip label="Read a .mid file in your browser: see its notes and get the command that solves it"><Button size="sm" onClick={() => setS(() => { S.panels.midi = true; })} data-testid="btn-midi"><FileMusic />Upload MIDI</Button></Tip>
            <Tip label="Play a .motion.json the solver wrote (add its .judgement.json too for hit/miss lanes)"><Button size="sm" variant="outline" onClick={() => motionIn.current?.click()} data-testid="btn-motion"><FileJson />Drop motion file</Button></Tip>
            <Tip label="Keys and how the page works"><Button size="icon-sm" variant="ghost" aria-label="Help" onClick={() => setHelp(true)}><CircleHelp /></Button></Tip>
          </div>
          <input ref={midiIn} type="file" hidden accept=".mid,.midi,audio/midi,audio/x-midi" data-testid="file-midi" onChange={(e) => { const f = e.target.files?.[0]; if (f) openMidi(f); e.target.value = ''; }} />
          <input ref={motionIn} type="file" hidden multiple accept=".json,application/json" data-testid="file-motion" onChange={(e) => { handleFiles([...(e.target.files || [])]); e.target.value = ''; }} />
        </header>
        {phone ? <PhoneLayout /> : <DesktopLayout />}
      </div>
      <MidiDialog onChoose={chooseMidi} />
      <HelpDialog open={help} onOpenChange={setHelp} />
      {veil && <div className="pointer-events-none fixed inset-0 z-[60] flex items-center justify-center bg-[#0a0c16]/80"><div className="max-w-[90vw] rounded-2xl border-2 border-dashed border-primary px-8 py-7 text-center text-base">Drop a <b>.mid</b> to chart it, or a <b>.motion.json</b> to play it</div></div>}
      <Toaster />
    </TooltipProvider>
  );
}

// panel sizes: % of their group, written to S.sizes on every layout change (localStorage only, debounced; no React render while dragging)
function DesktopLayout() {
  const side = useRef<ImperativePanelHandle>(null), rev = useRef<ImperativePanelHandle>(null), stg = useRef<ImperativePanelHandle>(null);
  const z = S.sizes;
  return (
    <ResizablePanelGroup direction="horizontal" className="min-h-0 flex-1" onLayout={(l) => { S.sizes.side = +l[0].toFixed(2); S.sizes.review = +l[2].toFixed(2); save(); }}>
      <ResizablePanel ref={side} id="side" order={1} defaultSize={z.side} minSize={12} maxSize={40}><PresetPanel /></ResizablePanel>
      <ResizableHandle withHandle data-testid="h-side" title="Drag to resize · double-click to reset" onDoubleClick={() => side.current?.resize(DEFAULTS.sizes.side)} />
      <ResizablePanel id="center" order={2} minSize={30}>
        <ResizablePanelGroup direction="vertical" onLayout={(l) => { S.sizes.stage = +l[0].toFixed(2); save(); }}>
          <ResizablePanel ref={stg} id="stage" order={1} defaultSize={z.stage} minSize={20} maxSize={80}><StageView className="h-full" /></ResizablePanel>
          <ResizableHandle withHandle data-testid="h-stage" title="Drag to resize · double-click to reset" onDoubleClick={() => stg.current?.resize(DEFAULTS.sizes.stage)} />
          <ResizablePanel id="below" order={2} minSize={20}><div className="flex h-full min-h-0 flex-col"><Transport /><LaneBox className="min-h-0 flex-1" /></div></ResizablePanel>
        </ResizablePanelGroup>
      </ResizablePanel>
      <ResizableHandle withHandle data-testid="h-review" title="Drag to resize · double-click to reset" onDoubleClick={() => rev.current?.resize(DEFAULTS.sizes.review)} />
      <ResizablePanel ref={rev} id="review" order={3} defaultSize={z.review} minSize={16} maxSize={45}><ReviewPanel /></ResizablePanel>
    </ResizablePanelGroup>
  );
}

function PhoneLayout() {
  const open = useS((s) => s.panels.review);
  return (
    <main className="flex flex-col">
      <StageView className="h-[62vw] min-h-56" />
      <Transport />
      <LaneBox className="h-48 flex-none" />
      <PresetPanel phone />
      <Collapsible open={open} onOpenChange={(o) => setS(() => { S.panels.review = o; })}>
        <CollapsibleTrigger asChild><Button variant="secondary" className="m-2 w-[calc(100%-1rem)] justify-between" data-testid="tg-review">Check: tally and mistakes<ChevronDown className={cn('transition-transform', !open && '-rotate-90')} /></Button></CollapsibleTrigger>
        <CollapsibleContent><ReviewPanel phone /></CollapsibleContent>
      </Collapsible>
    </main>
  );
}
