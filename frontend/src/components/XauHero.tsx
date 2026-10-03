'use client';
import { useEffect, useRef, useState } from 'react';

export type XauStatus = {
  connected: boolean; broker_symbol?: string | null; ready?: boolean; session?: string; candles?: number; candle_age_s?: number | null;
  checks: { key: string; label: string; ok: boolean }[]; last_error?: string | null; message?: string;
};

const fmt = (n: any, d = 2) => (typeof n === 'number' && isFinite(n) ? n.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d }) : '—');

function Price({ value }: { value?: number }) {
  const prev = useRef<number | undefined>(undefined);
  const [dir, setDir] = useState<'up' | 'down' | ''>('');
  const [n, setN] = useState(0);
  useEffect(() => {
    if (typeof value !== 'number') return;
    if (prev.current !== undefined && value !== prev.current) { setDir(value > prev.current ? 'up' : 'down'); setN(x => x + 1); }
    prev.current = value;
  }, [value]);
  const s = typeof value === 'number' ? value.toFixed(2) : '——.——';
  const [i, f] = s.split('.');
  return (
    <span key={n} className={`font-mono font-semibold tracking-tight text-white ${dir === 'up' ? 'flash-up' : dir === 'down' ? 'flash-down' : ''}`}>
      <span className="text-5xl sm:text-6xl">{i}</span><span className="text-3xl text-zinc-400 sm:text-4xl">.{f}</span>
    </span>
  );
}

export default function XauHero({ tick, status, connected, wsOk, botOn, activating, onActivate, selected }: {
  tick: any; status: XauStatus | null; connected: boolean; wsOk: boolean; botOn: boolean; activating: boolean; onActivate: () => void; selected: boolean;
}) {
  const ready = !!status?.ready;
  const checks = status?.checks || [];
  const spreadUsd = tick?.spread != null ? tick.spread / 100 : undefined;
  return (
    <section className="card relative overflow-hidden p-5 sm:p-6 rise">
      <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-amber-400/10 blur-3xl" />
      <div className="relative flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="label">Gold • XAU / USD</span>
            {status?.broker_symbol && <span className="chip border-white/10 bg-white/5 font-mono text-zinc-300">{status.broker_symbol}</span>}
            {connected && (ready
              ? <span className="chip border-emerald-400/25 bg-emerald-400/10 text-emerald-300"><i className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />XAUUSD ACTIVE</span>
              : <span className="chip border-amber-400/25 bg-amber-400/10 text-amber-300">NOT ACTIVE</span>)}
            {botOn && <span className="chip border-amber-400/40 bg-amber-400 font-bold text-zinc-950">AUTO ●</span>}
          </div>
          <div className="mt-3"><Price value={tick?.bid} /></div>
          <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 font-mono text-xs text-zinc-400">
            <span>BID <b className="text-zinc-200">{fmt(tick?.bid)}</b></span>
            <span>ASK <b className="text-zinc-200">{fmt(tick?.ask)}</b></span>
            <span>SPREAD <b className="text-zinc-200">{spreadUsd !== undefined ? `$${spreadUsd.toFixed(2)}` : '—'}</b></span>
            <span className="inline-flex items-center gap-1.5"><i className={`h-1.5 w-1.5 rounded-full ${wsOk ? 'bg-emerald-400' : 'bg-amber-400'}`} />{wsOk ? 'live stream' : 'polling'}</span>
          </div>
        </div>
        <div className="flex flex-col items-end gap-2">
          <button onClick={onActivate} disabled={!connected || activating} className={ready && selected ? 'btn-ghost' : 'btn-gold'}>
            {activating ? 'Activating…' : ready && selected ? '↻ Re-check XAUUSD' : '⚡ Activate XAUUSD'}
          </button>
          {!connected && <span className="text-[11px] text-zinc-500">Connect MetaApi first</span>}
        </div>
      </div>

      {connected && checks.length > 0 && (
        <div className="relative mt-5 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {checks.map(c => {
            const warn = !c.ok && c.key === 'session';
            const tone = c.ok ? 'text-emerald-300 border-emerald-400/15 bg-emerald-400/[0.06]' : warn ? 'text-amber-300 border-amber-400/15 bg-amber-400/[0.06]' : 'text-rose-300 border-rose-400/15 bg-rose-400/[0.06]';
            return (
              <div key={c.key} className={`flex items-center gap-2.5 rounded-2xl border px-3 py-2 text-xs ${tone}`}>
                <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-black/30 text-[11px] font-bold">{c.ok ? '✓' : warn ? '!' : '✕'}</span>
                <span className="truncate" title={c.label}>{c.label}</span>
              </div>
            );
          })}
        </div>
      )}
      {status?.last_error && !ready && <p className="relative mt-3 break-words font-mono text-[11px] text-rose-300/80">candles: {status.last_error}</p>}
    </section>
  );
}
