'use client';
import { useEffect, useRef } from 'react';
import type { ActiveTrade, Candle, PlannedSetup, TradeMarker } from '@/lib/types';

type Line = { price: number; color: string; title: string; style: number; width: number };
const SOLID = 0, DASHED = 2;               // lightweight-charts LineStyle values
const fmt = (n: number) => n.toFixed(2);

type Props = {
  data: Candle[]; markers?: TradeMarker[]; resetKey?: string; height?: number;
  planned?: PlannedSetup | null; trade?: ActiveTrade | null;
};

/** Candlestick chart. Created once; candles, markers and price lines are pushed in place so the chart never
 *  reloads or flickers when telemetry updates. Change `resetKey` (symbol / timeframe) to re-fit the view. Times are UTC. */
export default function TradingChart({ data, markers, resetKey, height = 420, planned, trade }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const seriesRef = useRef<any>(null);
  const linesRef = useRef<any[]>([]);
  const linesSig = useRef('');
  const latest = useRef<Props>({ data, markers, resetKey, planned, trade });
  const fittedFor = useRef<string | undefined>(undefined);
  latest.current = { data, markers, resetKey, planned, trade };

  /** amber dashed TARGET ENTRY line + TP / SL / break-even lines, rebuilt only when something actually changed */
  const pushLines = () => {
    const series = seriesRef.current;
    if (!series) return;
    const { planned: pl, trade: tr } = latest.current;
    const want: Line[] = [];
    if (pl) want.push({ price: pl.price, color: '#fbbf24', title: `TARGET ENTRY @ ${fmt(pl.price)}`, style: DASHED, width: 2 });
    if (tr) {
      if (tr.tp !== null) want.push({ price: tr.tp, color: '#34d399', title: `TP @ ${fmt(tr.tp)}`, style: SOLID, width: 2 });
      if (tr.sl !== null) {
        if (tr.beActive) want.push({ price: tr.sl, color: '#22d3ee', title: `BREAK-EVEN @ ${fmt(tr.sl)}`, style: SOLID, width: 2 });
        else want.push({ price: tr.sl, color: '#f87171', title: `SL @ ${fmt(tr.sl)}`, style: SOLID, width: 2 });
      }
    }
    const sig = JSON.stringify(want);
    if (sig === linesSig.current) return;
    linesRef.current.forEach(l => { try { series.removePriceLine(l); } catch {} });
    linesRef.current = want.map(w => series.createPriceLine({
      price: w.price, color: w.color, lineWidth: w.width, lineStyle: w.style, axisLabelVisible: true, title: w.title,
    }));
    linesSig.current = sig;
  };

  const push = () => {
    const series = seriesRef.current, chart = chartRef.current;
    if (!series || !chart) return;
    const { data, markers, resetKey } = latest.current;
    const seen = new Map<number, Candle>();
    (data || []).forEach(c => seen.set(c.time, c));
    const rows = Array.from(seen.values()).sort((a, b) => a.time - b.time);
    series.setData(rows.map(c => ({ time: c.time as any, open: c.open, high: c.high, low: c.low, close: c.close })));
    // executed orders: BUY = green arrowUp below the bar, SELL = red arrowDown above it, on the candle they happened in
    const mk: any[] = [];
    (markers || []).forEach(m => {
      let t = -1;
      for (const c of rows) { if (c.time <= m.time) t = c.time; else break; }
      if (t < 0) return;
      const buy = m.type === 'BUY';
      const label = [m.type, m.lot ? String(m.lot) : '', typeof m.price === 'number' ? `@ ${fmt(m.price)}` : ''].filter(Boolean).join(' ');
      mk.push({ time: t as any, position: buy ? 'belowBar' : 'aboveBar', color: buy ? '#34d399' : '#f87171', shape: buy ? 'arrowUp' : 'arrowDown', text: label });
    });
    mk.sort((a, b) => a.time - b.time);
    try { series.setMarkers(mk); } catch {}
    pushLines();
    if (rows.length && fittedFor.current !== resetKey) { chart.timeScale().fitContent(); fittedFor.current = resetKey; }
  };

  useEffect(() => {
    let disposed = false; let ro: ResizeObserver | undefined;
    (async () => {
      const lw: any = await import('lightweight-charts');
      if (disposed || !host.current) return;
      const chart = lw.createChart(host.current, {
        width: host.current.clientWidth, height,
        layout: { background: { type: lw.ColorType.Solid, color: 'transparent' }, textColor: '#8b8b98', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 11 },
        grid: { vertLines: { color: 'rgba(255,255,255,0.025)' }, horzLines: { color: 'rgba(255,255,255,0.04)' } },
        crosshair: { mode: lw.CrosshairMode.Normal },
        timeScale: { borderColor: 'rgba(255,255,255,0.08)', timeVisible: true, secondsVisible: false, rightOffset: 6 },
        rightPriceScale: { borderColor: 'rgba(255,255,255,0.08)', scaleMargins: { top: 0.1, bottom: 0.12 } },
      });
      const series = chart.addCandlestickSeries({
        upColor: '#34d399', downColor: '#f87171', borderVisible: false, wickUpColor: '#34d399', wickDownColor: '#f87171',
      });
      chartRef.current = chart; seriesRef.current = series;
      linesRef.current = []; linesSig.current = '';
      ro = new ResizeObserver(() => { if (host.current) chart.applyOptions({ width: host.current.clientWidth }); });
      ro.observe(host.current);
      fittedFor.current = undefined;
      push();
    })();
    return () => {
      disposed = true; ro?.disconnect();
      try { chartRef.current?.remove(); } catch {}
      chartRef.current = null; seriesRef.current = null; linesRef.current = []; linesSig.current = '';
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height]);

  useEffect(() => { push(); }); // cheap: setData is incremental and price lines only change when their values change

  return (
    <div className="relative">
      <div ref={host} style={{ height }} className="w-full" />
      {(!data || data.length === 0) && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-sm text-zinc-500">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-zinc-700 border-t-amber-400" />
          Waiting for candles…
        </div>
      )}
    </div>
  );
}
