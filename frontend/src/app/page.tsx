'use client';
import { useEffect, useState, useCallback } from 'react';
import TradingChart from '@/components/TradingChart';
import { apiUrl } from '@/lib/api';

const SERVERS = ['Exness-MT5Real','Exness-MT5Real2','Exness-MT5Real3','Exness-MT5Real4','Exness-MT5Real5','Exness-MT5Trial'];

function Pill({children, tone="neutral"}:{children:any,tone?:string}){
  const m:any={ emerald:"bg-emerald-500/10 text-emerald-400 border-emerald-500/20", red:"bg-red-500/10 text-red-400 border-red-500/20", amber:"bg-amber-500/10 text-amber-400 border-amber-500/20", neutral:"bg-zinc-800 text-zinc-400 border-zinc-700" };
  return <span className={`inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full border font-medium ${m[tone]||m.neutral}`}>{children}</span>;
}

export default function Page(){
  const [connected,setConnected]=useState(false); const [mode,setMode]=useState(''); const [acc,setAcc]=useState<any>(null);
  const [symbol,setSymbol]=useState('XAUUSD'); const [symbols]=useState(['XAUUSD','EURUSD','GBPUSD','USDJPY']);
  const [tick,setTick]=useState<any>(null); const [candles,setCandles]=useState<any[]>([]); const [analysis,setAnalysis]=useState<any>(null);
  const [positions,setPositions]=useState<any[]>([]); const [history,setHistory]=useState<any[]>([]); const [tab,setTab]=useState<'trade'|'positions'|'history'|'log'>('trade');
  const [wsOk,setWsOk]=useState(false);
  const [login,setLogin]=useState(''); const [password,setPassword]=useState(''); const [server,setServer]=useState(SERVERS[0]); const [customServer,setCustomServer]=useState(false);
  const [connecting,setConnecting]=useState(false); const [msg,setMsg]=useState<{t:'ok'|'err';m:string}|null>(null);
  const [bot,setBot]=useState<any>(null);
  const [riskPct,setRiskPct]=useState('3'); const [targetMult,setTargetMult]=useState('2'); const [maxDay,setMaxDay]=useState('12');
  const [autoLot,setAutoLot]=useState(true); const [fixedLot,setFixedLot]=useState('0.01'); const [slAtr,setSlAtr]=useState('1.6'); const [tpAtr,setTpAtr]=useState('2.8');
  const [trading,setTrading]=useState(false); const [balInput,setBalInput]=useState('10');
  const [showConnect,setShowConnect]=useState(true);

  const fetchAll=useCallback(async()=>{
    try{
      const s:any=await fetch(apiUrl('/api/status')).then(r=>r.json()).catch(()=>null);
      if(s){ setConnected(!!s.connected); setMode(s.mode||''); if(s.account) setAcc(s.account); if(s.bot){
        setBot(s.bot); setRiskPct(String(s.bot.config.risk_pct)); setTargetMult(String(s.bot.config.target_multiplier));
        setMaxDay(String(s.bot.config.max_trades_per_day)); setAutoLot(!!s.bot.config.auto_lot); setFixedLot(String(s.bot.config.fixed_lot));
        setSlAtr(String(s.bot.config.sl_atr_mult)); setTpAtr(String(s.bot.config.tp_atr_mult));
        if(s.connected) setShowConnect(false);
      }}
      if(s?.connected){
        const [t,c,an,pos,bs]=await Promise.all([
          fetch(apiUrl(`/api/tick/${symbol}`)).then(r=>r.json()).catch(()=>null),
          fetch(apiUrl(`/api/candles/${symbol}?timeframe=M5&count=100`)).then(r=>r.json()).catch(()=>null),
          fetch(apiUrl(`/api/analysis/${symbol}`)).then(r=>r.json()).catch(()=>null),
          fetch(apiUrl(`/api/positions`)).then(r=>r.json()).catch(()=>null),
          fetch(apiUrl('/api/bot/state')).then(r=>r.json()).catch(()=>null),
        ]);
        if(t) setTick(t); if(c?.candles) setCandles(c.candles); if(an) setAnalysis(an); if(pos?.positions) setPositions(pos.positions); if(bs) setBot(bs);
        const h:any=await fetch(apiUrl('/api/history?days=7')).then(r=>r.json()).catch(()=>null);
        if(h?.history) setHistory(h.history);
      }
    }catch{}
  },[symbol]);

  useEffect(()=>{ fetchAll(); const id=setInterval(fetchAll,2800); return ()=>clearInterval(id); },[fetchAll]);
  useEffect(()=>{
    const base=apiUrl(''); const wsBase=base?base.replace(/^http/,'ws'):(typeof window!=='undefined'?`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}`:'');
    let ws:WebSocket|null=null;
    try{ ws=new WebSocket(`${wsBase}/ws/telemetry`); ws.onopen=()=>setWsOk(true); ws.onclose=()=>setWsOk(false);
      ws.onmessage=(e)=>{ try{ const d=JSON.parse(e.data); if(d.connected!==undefined) setConnected(d.connected); if(d.mode) setMode(d.mode); if(d.account) setAcc(d.account); const t=d.ticks?.[symbol]||d.ticks?.XAUUSD; if(t) setTick(t); if(d.bot) setBot(d.bot); }catch{}}
    }catch{ setWsOk(false); }
    return ()=>{ try{ws?.close();}catch{}}
  },[symbol]);

  const doConnect=async()=>{
    setConnecting(true); setMsg(null);
    try{
      const r=await fetch(apiUrl('/api/connect'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({login,password,server})});
      const j=await r.json(); if(!r.ok) throw new Error(j.detail||j.message||`HTTP ${r.status}`);
      setMsg({t:'ok',m:j.message}); setConnected(true); setShowConnect(false); fetchAll();
    }catch(e:any){
      const hint = e.message?.includes('Failed to fetch') ? ' — Railway backend unreachable. Check NEXT_PUBLIC_API_URL on Vercel points to https://lm1-production.up.railway.app' : '';
      setMsg({t:'err',m:e.message+hint});
    }
    setConnecting(false);
  };
  const doTrade=async(a:'BUY'|'SELL')=>{
    setTrading(true);
    try{
      const vol=autoLot?undefined:parseFloat(fixedLot);
      const body:any={symbol,action:a,volume:vol??0.01};
      const r=await fetch(apiUrl('/api/trade'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const j=await r.json(); if(!r.ok) throw new Error(j.detail||j.message); setMsg({t:'ok',m:j.message}); fetchAll();
    }catch(e:any){ setMsg({t:'err',m:e.message}); }
    setTrading(false);
  };
  const saveBotConfig=async()=>{
    try{
      const r=await fetch(apiUrl('/api/bot/config'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({risk_pct:parseFloat(riskPct),target_multiplier:parseFloat(targetMult),max_trades_per_day:parseInt(maxDay),auto_lot:autoLot,fixed_lot:parseFloat(fixedLot),sl_atr_mult:parseFloat(slAtr),tp_atr_mult:parseFloat(tpAtr),symbol})});
      const j=await r.json(); if(!r.ok) throw new Error(j.detail); setBot(j); setMsg({t:'ok',m:'✓ Bot config saved'});
    }catch(e:any){ setMsg({t:'err',m:e.message}); }
  };
  const startBot=async()=>{
    try{
      const r=await fetch(apiUrl('/api/bot/start'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({risk_pct:parseFloat(riskPct),target_multiplier:parseFloat(targetMult),max_trades_per_day:parseInt(maxDay),auto_lot:autoLot,fixed_lot:parseFloat(fixedLot),sl_atr_mult:parseFloat(slAtr),tp_atr_mult:parseFloat(tpAtr),symbol})});
      const j=await r.json(); if(!r.ok) throw new Error(j.detail||j.message); setBot(j); setMsg({t:'ok',m:'🚀 Auto Flip STARTED — watch Log & chart markers'});
    }catch(e:any){ setMsg({t:'err',m:e.message}); }
  };
  const stopBot=async()=>{
    try{ const r=await fetch(apiUrl('/api/bot/stop'),{method:'POST'}); const j=await r.json(); setBot(j); setMsg({t:'ok',m:'⏹ Bot stopped'});}catch(e:any){ setMsg({t:'err',m:e.message}); }
  };
  const closePos=async(ticket:number)=>{
    try{ const r=await fetch(apiUrl(`/api/close/${ticket}`),{method:'POST'}); const j=await r.json(); if(!r.ok) throw new Error(j.detail||j.message); setMsg({t:'ok',m:j.message}); fetchAll(); }catch(e:any){ setMsg({t:'err',m:e.message}); }
  };
  const sc=(s?:string)=> s==='BUY'?'emerald':s==='SELL'?'red':s?.includes('OVER')?'amber':'neutral';
  const flipPct=bot?.stats?.flip_progress??0; const equityCurve=bot?.stats?.equity_curve||[]; const markers=bot?.stats?.markers||[];

  const modeTone = mode==='NATIVE'?'emerald':mode==='BRIDGE'?'emerald':mode==='EXNESS_API'?'amber':mode==='REAL'?'amber':'neutral';
  const modeLabel = mode==='NATIVE'?'NATIVE (Broker)':mode==='BRIDGE'?'BRIDGE (Windows)':mode==='EXNESS_API'?'EXNESS API (cloudscraper)':mode==='REAL'?'PAPER on LIVE (CF blocked)':'—';

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-zinc-100 selection:bg-amber-500/30">
      {/* Glow */}
      <div className="fixed inset-0 pointer-events-none -z-10 bg-[radial-gradient(600px_400px_at_20%_0%,rgba(120,90,255,0.12),transparent_60%),radial-gradient(800px_500px_at_100%_10%,rgba(245,158,11,0.10),transparent_60%)]" />
      {/* Header — Revolut-inspired premium */}
      <header className="sticky top-0 z-30 backdrop-blur-2xl bg-[#0a0a0f]/80 border-b border-zinc-800/80">
        <div className="max-w-[1520px] mx-auto px-4 sm:px-6 h-[64px] flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-2xl bg-gradient-to-br from-violet-600 via-indigo-600 to-amber-500 flex items-center justify-center font-black text-white shadow-lg shadow-violet-600/20">◈</div>
            <div>
              <h1 className="font-semibold tracking-[-0.02em] text-[17px] leading-none">Klop Apex <span className="ml-1 text-[10px] tracking-[0.18em] uppercase font-bold px-1.5 py-0.5 rounded bg-amber-500 text-zinc-950">Flip Engine</span></h1>
              <p className="text-[11px] tracking-[0.14em] uppercase text-zinc-500 font-medium">Exness MT5 • Auto Scalper • Railway</p>
            </div>
            <div className="hidden lg:flex items-center gap-2 ml-4">
              <Pill tone={connected?'emerald':'neutral'}><span className={`w-1.5 h-1.5 rounded-full ${connected?'bg-emerald-400 animate-pulse':'bg-zinc-500'}`}/>{connected?'Connected':'Disconnected'}</Pill>
              {connected && <Pill tone={modeTone}>{modeLabel}</Pill>}
              {bot?.enabled && <span className="text-xs px-2.5 py-1 rounded-full bg-amber-500 text-zinc-950 font-black">AUTO ●</span>}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {tick && <div className="hidden md:flex items-center gap-2.5 text-xs font-mono bg-zinc-900/80 border border-zinc-800 rounded-full pl-3 pr-2 py-1.5 backdrop-blur">
              <span className="text-zinc-500">{symbol}</span><span className="text-white font-bold">{typeof tick.bid==='number'?tick.bid.toFixed(2):tick.bid}</span>
              <span className="w-px h-3 bg-zinc-800"/>{/* spread */}
              <span className="text-zinc-400">spr {tick.spread??'-'}</span>
              <span className={`w-2 h-2 rounded-full ${wsOk?'bg-emerald-400':'bg-amber-400'}`} title={wsOk?'WS live':'polling'}/>
            </div>}
            <select value={symbol} onChange={e=>setSymbol(e.target.value)} className="bg-zinc-900 border border-zinc-800 rounded-full px-3 py-1.5 text-sm focus:outline-none focus:border-violet-500/50">
              {symbols.map(s=><option key={s} value={s}>{s}</option>)}
            </select>
            {connected && <button onClick={async()=>{ await fetch(apiUrl('/api/disconnect'),{method:'POST'}); setConnected(false); setAcc(null); setShowConnect(true); }} className="hidden sm:inline text-xs px-3 py-1.5 rounded-full border border-zinc-800 hover:bg-zinc-900">Disconnect</button>}
            {!connected && <button onClick={()=>setShowConnect(v=>!v)} className="text-xs px-4 py-1.5 rounded-full bg-violet-600 hover:bg-violet-500 text-white font-semibold">Connect</button>}
          </div>
        </div>
      </header>

      <main className="max-w-[1520px] mx-auto px-4 sm:px-6 py-6 space-y-5">
        {msg && <div className={`rounded-2xl border px-4 py-3 text-sm backdrop-blur ${msg.t==='ok'?'border-emerald-500/20 bg-emerald-500/10 text-emerald-200':'border-red-500/20 bg-red-500/10 text-red-200'}`}>{msg.m}</div>}

        {(showConnect || !connected) && (
          <div className="rounded-[20px] border border-zinc-800 bg-gradient-to-br from-zinc-900/80 to-zinc-950/80 backdrop-blur p-6 shadow-2xl shadow-black/30">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold tracking-[-0.02em] text-lg">Connect Exness MT5</h2>
                <p className="text-sm text-zinc-500 mt-1">Numeric login or PA email. Railway Wine = NATIVE broker, otherwise live XAU price + REAL signals. No MetaApi, free.</p>
              </div>
              <Pill tone="amber">Live XAU {tick ? `$${Number(tick.bid).toFixed(2)}` : '~$4131'}</Pill>
            </div>
            <div className="grid sm:grid-cols-[1fr_1fr_1fr_auto] gap-3 mt-4">
              <input value={login} onChange={e=>setLogin(e.target.value)} placeholder="MT5 Login (e.g. 477338841)" className="bg-zinc-950 border border-zinc-800 rounded-2xl px-4 py-2.5 text-sm focus:outline-none focus:border-violet-500/50 placeholder:text-zinc-600"/>
              <input value={password} onChange={e=>setPassword(e.target.value)} type="password" placeholder="Master password" className="bg-zinc-950 border border-zinc-800 rounded-2xl px-4 py-2.5 text-sm focus:outline-none focus:border-violet-500/50"/>
              {!customServer ? <select value={server} onChange={e=>setServer(e.target.value)} className="bg-zinc-950 border border-zinc-800 rounded-2xl px-4 py-2.5 text-sm focus:outline-none focus:border-violet-500/50">{SERVERS.map(s=><option key={s} value={s}>{s}</option>)}</select> : <input value={server} onChange={e=>setServer(e.target.value)} placeholder="Exness-MT5Real" className="bg-zinc-950 border border-zinc-800 rounded-2xl px-4 py-2.5 text-sm"/>}
              <button onClick={doConnect} disabled={connecting||!login||!password} className="rounded-full bg-violet-600 hover:bg-violet-500 disabled:opacity-40 text-white font-semibold px-6 py-2.5 text-sm shadow-lg shadow-violet-600/20">{connecting?'Connecting…':'Connect →'}</button>
            </div>
            <label className="flex items-center gap-2 mt-3 text-xs text-zinc-500 cursor-pointer"><input type="checkbox" checked={customServer} onChange={e=>setCustomServer(e.target.checked)} className="rounded"/> Custom server (e.g. Exness-MT5Trial)</label>
            {!connected && tick && <p className="text-xs text-zinc-600 mt-2">Chart is LIVE (gold-api). Connect to see REAL balance — numeric MT5 uses bridge/Wine NATIVE, PA email uses EXNESS API.</p>}
          </div>
        )}

        {/* KPI — Revolut cards: pill, high contrast, no shadows */}
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
          {[
            {k:'Balance', v: acc?`$${Number(acc.balance).toLocaleString(undefined,{minimumFractionDigits:2})}`:'—', sub: acc?.login?`${acc.login} @ ${acc.server}`:'Not connected', tone: acc?'text-white':''},
            {k:'Equity', v: acc?`$${Number(acc.equity).toLocaleString(undefined,{minimumFractionDigits:2})}`:'—', tone:(acc?.equity??0)>=(acc?.balance??0)?'text-emerald-400':'text-red-400'},
            {k:'Floating P/L', v: acc?`$${Number(acc.profit).toFixed(2)}`:'—', tone:(acc?.profit??0)>=0?'text-emerald-400':'text-red-400'},
            {k:'Today P/L', v: bot?`$${Number(bot.stats.pnl_today).toFixed(2)}`:'—', sub: bot?`${bot.stats.wins}W / ${bot.stats.losses}L • ${bot.stats.win_rate}%`:'', tone:(bot?.stats.pnl_today??0)>=0?'text-emerald-400':'text-red-400'},
          ].map((c,i)=>
            <div key={i} className="rounded-[20px] border border-zinc-800 bg-zinc-900/70 backdrop-blur p-5">
              <p className="text-[11px] tracking-[0.16em] uppercase font-semibold text-zinc-500">{c.k}</p>
              <p className={`text-[22px] font-semibold tracking-[-0.02em] mt-1 font-mono ${c.tone||'text-zinc-500'}`}>{c.v}</p>
              {c.sub && <p className="text-xs text-zinc-500 mt-1 truncate">{c.sub}</p>}
            </div>
          )}
          <div className="rounded-[20px] border border-zinc-800 bg-zinc-900/70 backdrop-blur p-5 col-span-2 lg:col-span-1">
            <p className="text-[11px] tracking-[0.16em] uppercase font-semibold text-zinc-500">Flip Progress</p>
            <p className="text-[22px] font-semibold mt-1 font-mono">{flipPct.toFixed(1)}%</p>
            <div className="w-full h-2 bg-zinc-800 rounded-full mt-2 overflow-hidden"><div className="h-full bg-gradient-to-r from-violet-600 to-amber-500 transition-all duration-500" style={{width:`${Math.min(100,flipPct)}%`}}/></div>
            <p className="text-[11px] text-zinc-500 mt-1 truncate">{bot?`$${bot.stats.current_balance} → $${bot.stats.target_balance} (×${bot?.config.target_multiplier})`:'—'}</p>
          </div>
        </div>

        {connected && mode==='REAL' && (
          <div className="rounded-2xl border border-red-500/30 bg-red-500/10 backdrop-blur p-4 flex flex-wrap items-center gap-3">
            <span className="text-sm font-black text-red-300 animate-pulse">⚠️ REAL BALANCE NOT SYNCED — Enter your Exness balance:</span>
            <input value={balInput} onChange={e=>setBalInput(e.target.value)} placeholder="e.g. 10" className="w-28 bg-zinc-950 border border-red-900 rounded-full px-3 py-2 text-sm font-mono text-white placeholder:text-zinc-500 focus:border-red-500"/>
            <button onClick={async()=>{ try{ const r=await fetch(apiUrl('/api/balance/set'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({balance:parseFloat(balInput)})}); const j=await r.json(); if(!r.ok) throw new Error(j.detail); setMsg({t:'ok',m:j.message}); fetchAll(); }catch(e:any){ setMsg({t:'err',m:e.message}); } }} className="px-5 py-2 rounded-full bg-red-500 hover:bg-red-400 text-white font-black text-sm shadow-lg">Sync Balance →</button>
            <span className="text-xs text-zinc-400">Chart = LIVE $4141 ✅ | Exness PA is <b>Cloudflare blocked</b> on Railway — auto balance needs <b>BRIDGE_URL</b> (Windows) or <b>Wine</b>. Until then trades are PAPER on live price.</span>
          </div>
        )}

        <div className="grid lg:grid-cols-[1fr_380px] gap-5">
          {/* Chart */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-xs tracking-[0.14em] uppercase font-bold text-zinc-500">{symbol} • M5 • {bot?.stats.last_signal||'HOLD'} {analysis?.rsi?`RSI ${analysis.rsi}`:''}</h3>
              <Pill tone={sc(bot?.stats.last_signal||analysis?.signal)}>{bot?.stats.last_signal||analysis?.signal||'HOLD'}</Pill>
            </div>
            <div className="rounded-[20px] border border-zinc-800 overflow-hidden bg-zinc-900/50 backdrop-blur">
              <TradingChart data={candles} markers={markers}/>
            </div>
            <div className="rounded-2xl border border-zinc-800 bg-zinc-900/70 backdrop-blur p-4 text-sm">
              <p className="text-zinc-300 leading-relaxed">{bot?.stats.last_reason || analysis?.reason || 'Awaiting EMA×RSI + ADX signal…'}</p>
              <p className="text-xs text-zinc-500 mt-2 font-mono flex flex-wrap gap-x-3"><span>EMA9 {analysis?.ema9}</span><span>EMA21 {analysis?.ema21}</span><span>ADX {analysis?.adx}</span><span>ATR {analysis?.atr}</span><span>{analysis?.price && `$${analysis.price}`}</span></p>
            </div>
            {equityCurve.length>1 && (
              <div className="rounded-2xl border border-zinc-800 bg-zinc-900/70 backdrop-blur p-4">
                <p className="text-xs tracking-[0.14em] uppercase font-semibold text-zinc-500 mb-2">Equity Curve</p>
                <div className="flex items-end gap-[2px] h-14">
                  {equityCurve.slice(-40).map((p:any,i:number)=>{
                    const min=Math.min(...equityCurve.map((x:any)=>x.equity)); const max=Math.max(...equityCurve.map((x:any)=>x.equity)); const rng=max-min||1;
                    const h=((p.equity-min)/rng)*100;
                    return <div key={i} className="flex-1 bg-violet-500/80 rounded-sm" style={{height:`${Math.max(4,h)}%`}} title={`${p.equity}`} />;
                  })}
                </div>
              </div>
            )}
            <div className="grid grid-cols-4 gap-2 text-center">
              {[{v:`${bot?.stats.trades_today??0}/${bot?.config.max_trades_per_day??12}`,k:'Trades'},{v:String(bot?.stats.wins??0),k:'Wins',c:'text-emerald-400'},{v:String(bot?.stats.losses??0),k:'Losses',c:'text-red-400'},{v:`${bot?.stats.win_rate??0}%`,k:'Win Rate'}].map((s,i)=>
                <div key={i} className="rounded-2xl border border-zinc-800 bg-zinc-900/70 backdrop-blur py-3.5"><p className={`text-lg font-mono font-bold ${s.c||''}`}>{s.v}</p><p className="text-[11px] tracking-[0.12em] uppercase font-semibold text-zinc-500">{s.k}</p></div>
              )}
            </div>
          </div>

          {/* Controls */}
          <div className="space-y-4">
            <div className="rounded-[20px] border border-violet-500/20 bg-gradient-to-br from-violet-600/10 via-indigo-600/10 to-amber-500/10 backdrop-blur p-5">
              <h3 className="font-bold text-sm flex items-center gap-2">⚡ Auto Flip Engine {bot?.enabled && <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500 text-white animate-pulse">RUNNING</span>}</h3>
              <div className="grid grid-cols-2 gap-3 mt-4">
                <label className="text-xs font-medium text-zinc-400">Risk / trade %<input value={riskPct} onChange={e=>setRiskPct(e.target.value)} className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded-full px-3 py-2 text-sm font-mono focus:outline-none focus:border-violet-500/50"/></label>
                <label className="text-xs font-medium text-zinc-400">Flip Target (×)<select value={targetMult} onChange={e=>setTargetMult(e.target.value)} className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded-full px-3 py-2 text-sm"><option value="1.5">×1.5</option><option value="2">×2</option><option value="3">×3</option><option value="5">×5</option><option value="10">×10</option></select></label>
                <label className="text-xs font-medium text-zinc-400">Max / day<input value={maxDay} onChange={e=>setMaxDay(e.target.value)} className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded-full px-3 py-2 text-sm font-mono"/></label>
                <label className="text-xs font-medium text-zinc-400">SL (ATR ×)<input value={slAtr} onChange={e=>setSlAtr(e.target.value)} className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded-full px-3 py-2 text-sm font-mono"/></label>
                <label className="text-xs font-medium text-zinc-400">TP (ATR ×)<input value={tpAtr} onChange={e=>setTpAtr(e.target.value)} className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded-full px-3 py-2 text-sm font-mono"/></label>
                <label className="text-xs font-medium text-zinc-400">Lot mode<select value={autoLot?'auto':'fixed'} onChange={e=>setAutoLot(e.target.value==='auto')} className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded-full px-3 py-2 text-sm"><option value="auto">Auto (risk %)</option><option value="fixed">Fixed</option></select></label>
                {!autoLot && <label className="text-xs font-medium text-zinc-400">Fixed lot<input value={fixedLot} onChange={e=>setFixedLot(e.target.value)} className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded-full px-3 py-2 text-sm font-mono"/></label>}
              </div>
              <div className="flex gap-2 mt-4">
                <button onClick={saveBotConfig} className="flex-1 py-2.5 rounded-full border border-zinc-700 bg-zinc-900 text-sm hover:bg-zinc-800 font-medium">Save</button>
                {!bot?.enabled ? <button onClick={startBot} disabled={!connected} className="flex-1 py-2.5 rounded-full bg-violet-600 hover:bg-violet-500 disabled:opacity-40 text-white font-bold text-sm shadow-lg shadow-violet-600/20">▶ START</button> : <button onClick={stopBot} className="flex-1 py-2.5 rounded-full bg-red-500 hover:bg-red-400 text-white font-bold text-sm shadow">⏹ STOP</button>}
              </div>
              <p className="text-[11px] text-zinc-500 mt-2">EMA×RSI + ATR + ADX + session filter. Auto lot from balance × risk%.</p>
            </div>

            <div className="rounded-[20px] border border-zinc-800 bg-zinc-900/70 backdrop-blur p-5">
              <h3 className="font-semibold text-sm">Manual Trade</h3>
              <div className="grid grid-cols-2 gap-3 mt-3">
                <button onClick={()=>doTrade('BUY')} disabled={!connected||trading} className="rounded-full bg-emerald-500 hover:bg-emerald-400 disabled:opacity-40 text-zinc-950 font-bold py-3">BUY</button>
                <button onClick={()=>doTrade('SELL')} disabled={!connected||trading} className="rounded-full bg-red-500 hover:bg-red-400 disabled:opacity-40 text-white font-bold py-3">SELL</button>
              </div>
            </div>

            <div className="rounded-[20px] border border-zinc-800 bg-zinc-900/70 backdrop-blur overflow-hidden">
              <div className="flex border-b border-zinc-800">
                {(['positions','history','log'] as const).map(t=>
                  <button key={t} onClick={()=>setTab(t as any)} className={`flex-1 py-2.5 text-xs font-bold uppercase tracking-[0.12em] ${tab===t?'text-white bg-zinc-800':'text-zinc-500 hover:text-zinc-300'}`}>{t}</button>
                )}
              </div>
              <div className="p-3 max-h-[400px] overflow-auto">
                {tab==='positions' && (positions.length===0?<p className="text-sm text-zinc-500 py-8 text-center">No open positions</p>:
                  <div className="space-y-2">{positions.map((p:any)=>
                    <div key={p.ticket} className="flex items-center justify-between bg-zinc-950 border border-zinc-800 rounded-2xl px-3 py-2.5 text-sm">
                      <div className="flex items-center gap-2"><span className={`text-xs font-bold px-2 py-0.5 rounded-full ${p.type==='BUY'?'bg-emerald-500/15 text-emerald-400 border border-emerald-500/20':'bg-red-500/15 text-red-400 border border-red-500/20'}`}>{p.type}</span><span className="font-mono text-sm">{p.symbol} {p.volume}</span><span className={`font-mono ${p.profit>=0?'text-emerald-400':'text-red-400'}`}>{p.profit?.toFixed(2)}</span></div>
                      <button onClick={()=>closePos(p.ticket)} className="text-xs px-3 py-1 rounded-full bg-zinc-800 hover:bg-zinc-700 border border-zinc-700">Close</button>
                    </div>
                  )}</div>
                )}
                {tab==='history' && (history.length===0?<p className="text-sm text-zinc-500 py-8 text-center">No history</p>:
                  <div className="space-y-1 text-xs font-mono">{history.slice(-20).reverse().map((h:any,i:number)=><div key={i} className="flex justify-between border-b border-zinc-800 py-1.5"><span>{h.symbol} {h.type}</span><span className={h.profit>=0?'text-emerald-400':'text-red-400'}>{h.profit}</span></div>)}</div>
                )}
                {tab==='log' && (
                  <div className="space-y-1 text-xs font-mono">
                    {(bot?.stats.log||[]).slice().reverse().map((l:any,i:number)=><div key={i} className={`py-1 border-b border-zinc-800 ${l.type==='success'?'text-emerald-400':l.type==='error'?'text-red-400':l.type==='warn'?'text-amber-400':'text-zinc-400'}`}><span className="text-zinc-600">[{l.time}]</span> {l.msg}</div>)}
                    {(bot?.stats.log||[]).length===0 && <p className="text-zinc-500 py-8 text-center">No logs — start the bot</p>}
                  </div>
                )}
              </div>
            </div>
            <p className="text-[11px] text-zinc-600 text-center">API <code className="bg-zinc-900 border border-zinc-800 px-1.5 py-0.5 rounded-full">{apiUrl('/api/status')}</code></p>
          </div>
        </div>
      </main>
    </div>
  );
}
