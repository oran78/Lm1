'use client';
import { useEffect, useRef } from 'react';

type Candle = { time: number; open: number; high: number; low: number; close: number };
type Marker = { time: number; type: string; lot?: number };

/** Candlestick chart. Created once; data/markers are pushed in place so the chart never flickers on refresh.
 *  Change `resetKey` (symbol / timeframe) to re-fit the view. Times are UTC. */
export default function TradingChart({ data, markers, resetKey, height = 420 }: { data: Candle[]; markers?: Marker[]; resetKey?: string; height?: number }) {
  const host = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const seriesRef = useRef<any>(null);
  const latest = useRef({ data, markers, resetKey });
  const fittedFor = useRef<string | undefined>(undefined);
  latest.current = { data, markers, resetKey };

  const push = () => {
    const series = seriesRef.current, chart = chartRef.current;
    if (!series || !chart) return;
    const { data, markers, resetKey } = latest.current;
    const seen = new Map<number, Candle>();
    (data || []).forEach(c => seen.set(c.time, c));
    const rows = Array.from(seen.values()).sort((a, b) => a.time - b.time);
    series.setData(rows.map(c => ({ time: c.time as any, open: c.open, high: c.high, low: c.low, close: c.close })));
    // arrows: attach each marker to the candle it happened in
    const mk: any[] = [];
    (markers || []).forEach(m => {
      let t = -1;
      for (const c of rows) { if (c.time <= m.time) t = c.time; else break; }
      if (t < 0) return;
      const buy = m.type === 'BUY';
      mk.push({ time: t as any, position: buy ? 'belowBar' : 'aboveBar', color: buy ? '#34d399' : '#f87171', shape: buy ? 'arrowUp' : 'arrowDown', text: `${m.type}${m.lot ? ' ' + m.lot : ''}` });
    });
    mk.sort((a, b) => a.time - b.time);
    try { series.setMarkers(mk); } catch {}
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
      ro = new ResizeObserver(() => { if (host.current) chart.applyOptions({ width: host.current.clientWidth }); });
      ro.observe(host.current);
      fittedFor.current = undefined;
      push();
    })();
    return () => { disposed = true; ro?.disconnect(); try { chartRef.current?.remove(); } catch {} chartRef.current = null; seriesRef.current = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height]);

  useEffect(() => { push(); }); // cheap: runs after every render, setData is incremental

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
