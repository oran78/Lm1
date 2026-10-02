'use client';
import { useEffect, useRef } from 'react';
export default function TradingChart({ data, markers }: { data: any[]; markers?: any[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const markersRef = useRef<any[]>([]);
  useEffect(() => {
    markersRef.current = markers || [];
  }, [markers]);
  useEffect(() => {
    if (!ref.current || !data?.length) return;
    let chart: any, series: any, disposed=false;
    (async () => {
      const { createChart, ColorType } = await import('lightweight-charts');
      if (disposed || !ref.current) return;
      ref.current.innerHTML='';
      chart = createChart(ref.current, {
        layout: { background: { type: ColorType.Solid, color: '#18181b' }, textColor: '#a1a1aa' },
        grid: { vertLines: { color: '#27272a' }, horzLines: { color: '#27272a' } },
        width: ref.current.clientWidth, height: 380,
        timeScale: { borderColor: '#27272a' },
        rightPriceScale: { borderColor: '#27272a' },
      });
      series = chart.addCandlestickSeries({ upColor: '#22c55e', downColor: '#ef4444', borderVisible:false, wickUpColor:'#22c55e', wickDownColor:'#ef4444' });
      const mapped = data.map((c:any)=>({ time: c.time, open:c.open, high:c.high, low:c.low, close:c.close }));
      series.setData(mapped);
      // markers overlay (BUY/SELL arrows)
      const mks = (markersRef.current||[]).map((m:any)=>{
        // find closest candle index
        let idx = data.findIndex((c:any)=> Math.abs(c.time - m.time) < 600);
        if (idx<0) idx = data.length-1;
        const t = data[idx]?.time || m.time;
        return { time: t, position: m.type==='BUY'?'belowBar':'aboveBar', color: m.type==='BUY'?'#22c55e':'#ef4444', shape: m.type==='BUY'?'arrowUp':'arrowDown', text: `${m.type} ${m.lot||''}`.trim() };
      });
      if (mks.length) try { series.setMarkers(mks); } catch {}
      chart.timeScale().fitContent();
      const ro=new ResizeObserver(()=>{ if(chart&&ref.current) chart.applyOptions({width:ref.current.clientWidth}); });
      ro.observe(ref.current);
    })();
    return ()=>{ disposed=true; try{chart?.remove();}catch{} };
  }, [data, markers]);
  return <div ref={ref} className="w-full rounded-xl overflow-hidden border border-zinc-800 bg-zinc-900" />;
}
