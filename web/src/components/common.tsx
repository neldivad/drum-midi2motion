import { useSyncExternalStore } from 'react';
import { viewStore, type View } from '@/engine/player';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { cn } from '@/lib/utils';

export function usePlayer<T>(sel: (v: View) => T): T { return useSyncExternalStore(viewStore.subscribe, () => sel(viewStore.get())); }

const phoneQ = typeof matchMedia === 'function' ? matchMedia('(max-width: 760px)') : null;
const subPhone = (f: () => void) => { phoneQ?.addEventListener('change', f); return () => phoneQ?.removeEventListener('change', f); };
export function useIsPhone() { return useSyncExternalStore(subPhone, () => !!phoneQ?.matches); }

// a shadcn Select over [value, label] pairs; '' (the "any" option) is carried as a sentinel since Radix items cannot hold ''
const ANY = '__any';
export function Pick({ value, onChange, items, label, testid, className, size = 'sm' }: { value: string; onChange: (v: string) => void; items: [string, string][]; label: string; testid?: string; className?: string; size?: 'sm' | 'default' }) {
  return (
    <Select value={value === '' ? ANY : value} onValueChange={(v) => onChange(v === ANY ? '' : v)}>
      <SelectTrigger size={size} aria-label={label} data-testid={testid} className={cn('w-full min-w-0', className)}><SelectValue /></SelectTrigger>
      <SelectContent>{items.map(([v, l]) => <SelectItem key={v || ANY} value={v === '' ? ANY : v}>{l}</SelectItem>)}</SelectContent>
    </Select>
  );
}

export function Chip({ k, v, tone }: { k: string; v: React.ReactNode; tone?: 'ok' | 'warn' | 'bad' | '' }) {
  if (v == null || v === '') return null;
  return <span className="rounded-full border border-border bg-muted px-2.5 py-0.5 text-xs tabular-nums">{k} <b className={cn('font-semibold', tone === 'ok' && 'text-ok', tone === 'warn' && 'text-warn', tone === 'bad' && 'text-bad')}>{v}</b></span>;
}
