'use client';
import { useEffect, useState, useCallback } from 'react';
import TradingChart from '@/components/TradingChart';
import StatsCard from '@/components/StatsCard';
import { apiUrl } from '@/lib/api';

const EXNESS_SERVERS = ['Exness-MT5Real','Exness-MT5Real2','Exness-MT5Real3','Exness-MT5Real4','Exness-MT5Real5','Exness-MT5Real6','Exness-MT5Real7','Exness-MT5Trial'];

export default function Page() {
  const [connected, setConnected] = useState(false);
  const [mode, setMode] = useState('');
  const [acc, setAcc] = useState<any>(null);
  const [symbol, setSymbol] = useState('XAUUSD');
  const [symbols] = useState(['XAUUSD','EURUSD','GBPUSD','USDJPY']);
  const [tick, setTick] = useState<any>(null);
  const [candles, setCandles] = useState<any[]>([]);
  const [analysis, setAnalysis] = useState<any>(null);
  const [positions, setPositions] = useState<any[]>([]);
  const [tab, setTab] = useState<'trade'|'positions'|'history'|'log'>('trade');
  const [history, setHistory] = useState<any[]>([]);
  const [wsOk, setWsOk] = useState(false);

  // connect
  const [login, setLogin] = useState(''); const [password, setPassword] = useState('');
  const [server, setServer] = useState(EXNESS_SERVERS[0]); const [customServer, setCustomServer] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [msg, setMsg] = useState<{t:'ok'|'err';m:string}|null>(null);

  // bot dashboard state
  const [bot, setBot] = useState<any>(null);
  const [riskPct, setRiskPct] = useState('2'); const [targetMult, setTargetMult] = useState('2');
  const [maxDay, setMaxDay] = useState('20'); const [autoLot, setAutoLot] = useState(true);
  const [fixedLot, setFixedLot] = useState('0.10'); const [slAtr, setSlAtr] = useState('1.6'); const [tpAtr, setTpAtr] = useState('2.8');
  const [trading, setTrading] = useState(false);
  const [balInput, setBalInput] = useState('10');

  const fetchAll = useCallback(async () => {
    try {
      const s:any = await fetch(apiUrl('/api/status')).then(r=>r.json()).catch(()=>null);
      if (s) { setConnected(!!s.connected); setMode(s.mode||''); if (s.account) setAcc(s.account); if (s.bot) { setBot(s.bot); setRiskPct(String(s.bot.config.risk_pct)); setTargetMult(String(s.bot.config.target_multiplier)); setMaxDay(String(s.bot.config.max_trades_per_day)); setAutoLot(!!s.bot.config.auto_lot); setFixedLot(String(s.bot.config.fixed_lot)); setSlAtr(String(s.bot.config.sl_atr_mult)); setTpAtr(String(s.bot.config.tp_atr_mult)); } }
      if (s?.connected) {
        const [t,c,an,pos,bs] = await Promise.all([
          fetch(apiUrl(`/api/tick/${symbol}`)).then(r=>r.json()).catch(()=>null),
          fetch(apiUrl(`/api/candles/${symbol}?timeframe=M5&count=100`)).then(r=>r.json()).catch(()=>null),
          fetch(apiUrl(`/api/analysis/${symbol}`)).then(r=>r.json()).catch(()=>null),
          fetch(apiUrl(`/api/positions`)).then(r=>r.json()).catch(()=>null),
          fetch(apiUrl('/api/bot/state')).then(r=>r.json()).catch(()=>null),
        ]);
        if (t) setTick(t); if (c?.candles) setCandles(c.candles); if (an) setAnalysis(an); if (pos?.positions) setPositions(pos.positions); if (bs) setBot(bs);
        const h:any = await fetch(apiUrl('/api/history?days=7')).then(r=>r.json()).catch(()=>null);
        if (h?.history) setHistory(h.history);
      }
    } catch {}
  }, [symbol]);

  useEffect(()=>{ fetchAll(); const id=setInterval(fetchAll, 3000); return ()=>clearInterval(id); }, [fetchAll]);

  useEffect(()=>{
    const base = apiUrl(''); const wsBase = base ? base.replace(/^http/,'ws') : (typeof window!=='undefined'?`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}`:'');
    let ws: WebSocket|null=null;
    try { ws=new WebSocket(`${wsBase}/ws/telemetry`); ws.onopen=()=>setWsOk(true); ws.onclose=()=>setWsOk(false);
      ws.onmessage=(e)=>{ try{ const d=JSON.parse(e.data); if(d.connected!==undefined) setConnected(d.connected); if(d.mode) setMode(d.mode); if(d.account) setAcc(d.account); const t=d.ticks?.[symbol]||d.ticks?.XAUUSD; if(t) setTick(t); if(d.bot) setBot(d.bot); }catch{}}
    } catch{ setWsOk(false); }
    return ()=>{ try{ws?.close();}catch{}}
  },[symbol]);

  const doConnect=async()=>{
    setConnecting(true); setMsg(null);
    try{ const r=await fetch(apiUrl('/api/connect'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({login,password,server})}); const j=await r.json(); if(!r.ok) throw new Error(j.detail||j.message); setMsg({t:'ok',m:j.message}); setConnected(true); fetchAll(); }catch(e:any){ setMsg({t:'err',m:e.message}); }
    setConnecting(false);
  };
  const doTrade=async(a:'BUY'|'SELL')=>{
    setTrading(true); try{ const vol=autoLot?undefined:parseFloat(fixedLot); const body:any={symbol,action:a,volume:vol??0.1}; const r=await fetch(apiUrl('/api/trade'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); const j=await r.json(); if(!r.ok) throw new Error(j.detail||j.message); setMsg({t:'ok',m:j.message}); fetchAll(); }catch(e:any){ setMsg({t:'err',m:e.message}); } setTrading(false);
  };
  const saveBotConfig=async()=>{
    try{ const r=await fetch(apiUrl('/api/bot/config'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({risk_pct:parseFloat(riskPct),target_multiplier:parseFloat(targetMult),max_trades_per_day:parseInt(maxDay),auto_lot:autoLot,fixed_lot:parseFloat(fixedLot),sl_atr_mult:parseFloat(slAtr),tp_atr_mult:parseFloat(tpAtr),symbol})}); const j=await r.json(); if(!r.ok) throw new Error(j.detail); setBot(j); setMsg({t:'ok',m:'Bot config saved'});}catch(e:any){ setMsg({t:'err',m:e.message}); }
  };
  const startBot=async()=>{
    try{ const r=await fetch(apiUrl('/api/bot/start'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({risk_pct:parseFloat(riskPct),target_multiplier:parseFloat(targetMult),max_trades_per_day:parseInt(maxDay),auto_lot:autoLot,fixed_lot:parseFloat(fixedLot),sl_atr_mult:parseFloat(slAtr),tp_atr_mult:parseFloat(tpAtr),symbol})}); const j=await r.json(); if(!r.ok) throw new Error(j.detail||j.message); setBot(j); setMsg({t:'ok',m:'🚀 Auto Flip STARTED'});}catch(e:any){ setMsg({t:'err',m:e.message}); }
  };
  const stopBot=async()=>{ try{ const r=await fetch(apiUrl('/api/bot/stop'),{method:'POST'}); const j=await r.json(); setBot(j); setMsg({t:'ok',m:'Bot stopped'});}catch(e:any){ setMsg({t:'err',m:e.message}); } };

  const signalColor=(s?:string)=> s==='BUY'?'text-emerald-400 border-emerald-500/30 bg-emerald-500/10': s==='SELL'?'text-red-400 border-red-500/30 bg-red-500/10': s?.includes('OVER')?'text-amber-400 border-amber-500/30 bg-amber-500/10':'text-zinc-400 border-zinc-700 bg-zinc-800';

  const flipPct = bot?.stats?.flip_progress ?? 0;
  const equityCurve = bot?.stats?.equity_curve || [];

  // attach markers to candles for chart overlay (simple: append markers array to chart via prop)
  const markers = bot?.stats?.markers || [];

  return (
    <div className="min-h-screen bg-[#09090b]">
      <header className="sticky top-0 z-30 backdrop-blur-xl bg-zinc-950/80 border-b border-zinc-800">
        <div className="max-w-[1480px] mx-auto px-4 sm:px-6 py-3 flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-amber-400 to-orange-600 flex items-center justify-center font-black text-zinc-950">K</div>
            <div><h1 className="font-semibold tracking-tight leading-none">Klop Apex <span className="text-amber-400 font-mono text-xs ml-1">FLIP ENGINE</span></h1><p className="text-[11px] tracking-widest uppercase text-zinc-500">Exness MT5 • Auto Scalper • Railway</p></div>
            <span className={`ml-3 hidden sm:inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border ${connected?'border-emerald-500/30 bg-emerald-500/10 text-emerald-400':'border-zinc-700 bg-zinc-800 text-zinc-400'}`}><span className={`w-2 h-2 rounded-full ${connected?'bg-emerald-400 animate-pulse':'bg-zinc-500'}`}/>{connected?(mode==='mock'?'DEMO Connected':'LIVE Connected'):'Disconnected'}</span>
            {bot?.enabled && <span className="hidden sm:inline-flex text-xs px-2.5 py-1 rounded-full bg-amber-500 text-zinc-950 font-bold animate-pulse">AUTO ON</span>}
          </div>
          <div className="flex items-center gap-2">
            {tick && <div className="hidden md:flex items-center gap-3 text-xs font-mono bg-zinc-900 border border-zinc-800 rounded-full px-3 py-1.5"><span className="text-zinc-500">{symbol}</span><span className="text-white">{typeof tick.bid==='number'?tick.bid.toFixed(2):tick.bid}</span><span className="text-zinc-500">spr {tick.spread??'-'}</span><span className={`w-2 h-2 rounded-full ${wsOk?'bg-emerald-400':'bg-amber-400'}`} title={wsOk?'WS live':'polling'}/></div>}
            <select value={symbol} onChange={e=>setSymbol(e.target.value)} className="bg-zinc-900 border border-zinc-800 rounded-xl px-3 py-2 text-sm">{symbols.map(s=><option key={s} value={s}>{s}</option>)}</select>
            {connected && <button onClick={async()=>{ await fetch(apiUrl('/api/disconnect'),{method:'POST'}); setConnected(false); setAcc(null); }} className="text-xs px-3 py-2 rounded-xl border border-zinc-800 hover:bg-zinc-900">Disconnect</button>}
          </div>
        </div>
      </header>

      <main className="max-w-[1480px] mx-auto px-4 sm:px-6 py-6 space-y-6">
        {msg && <div className={`rounded-xl border px-4 py-3 text-sm ${msg.t==='ok'?'border-emerald-500/30 bg-emerald-500/10 text-emerald-300':'border-red-500/30 bg-red-500/10 text-red-300'}`}>{msg.m}</div>}

        {!connected && (
          <div className="bg-gradient-to-br from-zinc-900 to-zinc-950 border border-zinc-800 rounded-2xl p-6">
            <h2 className="font-semibold">Connect Exness MT5</h2>
            <p className="text-sm text-zinc-500 mt-1">Direct — no MetaApi — free. Railway Wine = live fills, otherwise DEMO simulation.</p>
            <div className="grid sm:grid-cols-4 gap-3 mt-4">
              <input value={login} onChange={e=>setLogin(e.target.value)} placeholder="MT5 Login" className="bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-amber-500/50"/>
              <input value={password} onChange={e=>setPassword(e.target.value)} type="password" placeholder="Master password" className="bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-amber-500/50"/>
              {!customServer ? <select value={server} onChange={e=>setServer(e.target.value)} className="bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-2.5 text-sm">{EXNESS_SERVERS.map(s=><option key={s} value={s}>{s}</option>)}</select> : <input value={server} onChange={e=>setServer(e.target.value)} placeholder="Exness-MT5Real" className="bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-2.5 text-sm"/>}
              <button onClick={doConnect} disabled={connecting||!login||!password} className="bg-amber-500 hover:bg-amber-400 disabled:opacity-40 text-zinc-950 font-semibold rounded-xl px-4 py-2.5 text-sm">{connecting?'Connecting…':'Connect'}</button>
            </div>
            <label className="flex items-center gap-2 mt-3 text-xs text-zinc-500"><input type="checkbox" checked={customServer} onChange={e=>setCustomServer(e.target.checked)}/> Custom server</label>
          </div>
        )}

        {/* KPI row */}
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
          <StatsCard label="Balance" value={acc?`$${Number(acc.balance).toLocaleString(undefined,{minimumFractionDigits:2})}`:'--'} sub={acc?.login?`${acc.login} @ ${acc.server}`:'Not connected'}/>
          <StatsCard label="Equity" value={acc?`$${Number(acc.equity).toLocaleString(undefined,{minimumFractionDigits:2})}`:'--'} accent={(acc?.equity??0)>=(acc?.balance??0)?'text-emerald-400':'text-red-400'}/>
          <StatsCard label="Floating P/L" value={acc?`$${Number(acc.profit).toFixed(2)}`:'--'} accent={(acc?.profit??0)>=0?'text-emerald-400':'text-red-400'}/>
          <StatsCard label="Today P/L" value={bot?`$${Number(bot.stats.pnl_today).toFixed(2)}`:'--'} sub={bot?`${bot.stats.wins}W / ${bot.stats.losses}L • ${bot.stats.win_rate}%` : undefined} accent={(bot?.stats.pnl_today??0)>=0?'text-emerald-400':'text-red-400'}/>
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 col-span-2 lg:col-span-1">
            <p className="text-xs tracking-widest uppercase text-zinc-500">Flip Progress</p>
            <p className="text-xl font-mono font-semibold mt-1">{flipPct.toFixed(1)}%</p>
            <div className="w-full h-2 bg-zinc-800 rounded-full mt-2 overflow-hidden"><div className="h-full bg-gradient-to-r from-amber-400 to-orange-500" style={{width:`${Math.min(100,flipPct)}%`}}/></div>
            <p className="text-[11px] text-zinc-500 mt-1">{bot?`$${bot.stats.current_balance} → $${bot.stats.target_balance} (x${bot?.config.target_multiplier})`:''}</p>
          </div>
        </div>
        {connected && mode==='REAL' && (
          <div className="bg-amber-500/10 border border-amber-500/20 rounded-xl p-3 flex items-center gap-3 flex-wrap">
            <span className="text-sm font-semibold text-amber-300">REAL Market LIVE — but balance needs sync (no Wine yet):</span>
            <input value={balInput} onChange={e=>setBalInput(e.target.value)} placeholder="10" className="w-28 bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-2 text-sm font-mono"/>
            <button onClick={async()=>{ try{ const r=await fetch(apiUrl('/api/balance/set'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({balance:parseFloat(balInput)})}); const j=await r.json(); if(!r.ok) throw new Error(j.detail); setMsg({t:'ok',m:j.message}); fetchAll(); }catch(e:any){ setMsg({t:'err',m:e.message}); } }} className="px-4 py-2 rounded-xl bg-amber-500 text-zinc-950 font-bold text-sm">Sync Balance</button>
            <span className="text-xs text-zinc-500">Enter your REAL Exness balance (e.g. 10). Chart & signals already use live XAU price (~$4131).</span>
          </div>
        )}

        <div className="grid lg:grid-cols-[1fr_380px] gap-6">
          <div className="space-y-4">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <h3 className="text-sm font-semibold tracking-wide uppercase text-zinc-400">{symbol} • M5 • {bot?.stats.last_signal||'HOLD'} {analysis?.rsi?`RSI ${analysis.rsi}`:''}</h3>
              <span className={`text-xs px-2.5 py-1 rounded-full border font-medium ${signalColor(bot?.stats.last_signal||analysis?.signal)}`}>{bot?.stats.last_signal||analysis?.signal||'HOLD'}</span>
            </div>
            <TradingChart data={candles} markers={markers}/>
            <p className="text-sm text-zinc-400 bg-zinc-900 border border-zinc-800 rounded-xl p-3">{bot?.stats.last_reason || analysis?.reason || 'Awaiting signal'} <span className="text-zinc-500 font-mono text-xs ml-2">EMA9 {analysis?.ema9} • EMA21 {analysis?.ema21} • {analysis?.price}</span></p>

            {/* Equity mini */}
            {equityCurve.length>1 && (
              <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-3">
                <p className="text-xs text-zinc-500 mb-2">Equity Curve (today)</p>
                <div className="flex items-end gap-[2px] h-14">
                  {equityCurve.slice(-40).map((p:any,i:number)=>{
                    const min=Math.min(...equityCurve.map((x:any)=>x.equity)); const max=Math.max(...equityCurve.map((x:any)=>x.equity)); const range=max-min||1;
                    const h=((p.equity-min)/range)*100;
                    return <div key={i} className="flex-1 bg-emerald-500/80 rounded-sm" style={{height:`${Math.max(4,h)}%`}} title={`${p.equity}`} />
                  })}
                </div>
              </div>
            )}

            {/* Trades today counter */}
            <div className="grid grid-cols-4 gap-2 text-center">
              <div className="bg-zinc-900 border border-zinc-800 rounded-xl py-3"><p className="text-lg font-mono font-bold">{bot?.stats.trades_today??0}/{bot?.config.max_trades_per_day??20}</p><p className="text-[11px] text-zinc-500 uppercase tracking-wide">Trades Today</p></div>
              <div className="bg-zinc-900 border border-zinc-800 rounded-xl py-3"><p className="text-lg font-mono font-bold text-emerald-400">{bot?.stats.wins??0}</p><p className="text-[11px] text-zinc-500 uppercase tracking-wide">Wins</p></div>
              <div className="bg-zinc-900 border border-zinc-800 rounded-xl py-3"><p className="text-lg font-mono font-bold text-red-400">{bot?.stats.losses??0}</p><p className="text-[11px] text-zinc-500 uppercase tracking-wide">Losses</p></div>
              <div className="bg-zinc-900 border border-zinc-800 rounded-xl py-3"><p className="text-lg font-mono font-bold">{bot?.stats.win_rate??0}%</p><p className="text-[11px] text-zinc-500 uppercase tracking-wide">Win Rate</p></div>
            </div>
          </div>

          <div className="space-y-4">
            {/* Auto Flip Controls — PROFESSIONAL */}
            <div className="bg-gradient-to-br from-amber-500/10 to-orange-600/10 border border-amber-500/20 rounded-2xl p-5">
              <h3 className="font-bold text-sm flex items-center gap-2">⚡ Auto Flip Engine {bot?.enabled && <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-500 text-white animate-pulse">RUNNING</span>}</h3>
              <div className="grid grid-cols-2 gap-3 mt-4">
                <label className="text-xs text-zinc-400">Risk / trade %<input value={riskPct} onChange={e=>setRiskPct(e.target.value)} className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-2 text-sm font-mono"/></label>
                <label className="text-xs text-zinc-400">Flip Target (×)<select value={targetMult} onChange={e=>setTargetMult(e.target.value)} className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-2 text-sm"><option value="1.5">×1.5</option><option value="2">×2 (double)</option><option value="3">×3</option><option value="5">×5</option><option value="10">×10</option></select></label>
                <label className="text-xs text-zinc-400">Max trades / day<input value={maxDay} onChange={e=>setMaxDay(e.target.value)} className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-2 text-sm font-mono"/></label>
                <label className="text-xs text-zinc-400">SL (ATR ×)<input value={slAtr} onChange={e=>setSlAtr(e.target.value)} className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-2 text-sm font-mono"/></label>
                <label className="text-xs text-zinc-400">TP (ATR ×)<input value={tpAtr} onChange={e=>setTpAtr(e.target.value)} className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-2 text-sm font-mono"/></label>
                <label className="text-xs text-zinc-400">Lot mode<select value={autoLot?'auto':'fixed'} onChange={e=>setAutoLot(e.target.value==='auto')} className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-2 text-sm"><option value="auto">Auto (risk %)</option><option value="fixed">Fixed</option></select></label>
                {!autoLot && <label className="text-xs text-zinc-400 col-span-2 sm:col-span-1">Fixed lot<input value={fixedLot} onChange={e=>setFixedLot(e.target.value)} className="mt-1 w-full bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-2 text-sm font-mono"/></label>}
              </div>
              <div className="flex gap-2 mt-4">
                <button onClick={saveBotConfig} className="flex-1 py-2.5 rounded-xl border border-zinc-700 bg-zinc-900 text-sm hover:bg-zinc-800">Save</button>
                {!bot?.enabled ? <button onClick={startBot} disabled={!connected} className="flex-1 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 disabled:opacity-40 text-zinc-950 font-bold text-sm">▶ START BOT</button> : <button onClick={stopBot} className="flex-1 py-2.5 rounded-xl bg-red-500 hover:bg-red-400 text-white font-bold text-sm">⏹ STOP BOT</button>}
              </div>
              <p className="text-[11px] text-zinc-500 mt-2">Auto lot = (balance × risk%) / stop. Flip target auto-calc from starting balance. WS streams live.</p>
            </div>

            {/* Manual trade */}
            <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5">
              <h3 className="font-semibold text-sm">Manual Trade</h3>
              <div className="grid grid-cols-2 gap-3 mt-3">
                <button onClick={()=>doTrade('BUY')} disabled={!connected||trading} className="bg-emerald-500 hover:bg-emerald-400 disabled:opacity-40 text-zinc-950 font-bold rounded-xl py-3">BUY</button>
                <button onClick={()=>doTrade('SELL')} disabled={!connected||trading} className="bg-red-500 hover:bg-red-400 disabled:opacity-40 text-white font-bold rounded-xl py-3">SELL</button>
              </div>
            </div>

            {/* Tabs */}
            <div className="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden">
              <div className="flex border-b border-zinc-800">
                {(['positions','history','log'] as const).map(t=>(
                  <button key={t} onClick={()=>setTab(t as any)} className={`flex-1 py-2.5 text-xs font-semibold uppercase tracking-wide ${tab===t?'text-white bg-zinc-800':'text-zinc-500 hover:text-zinc-300'}`}>{t}</button>
                ))}
              </div>
              <div className="p-3 max-h-[380px] overflow-auto">
                {tab==='positions' && (positions.length===0?<p className="text-sm text-zinc-500 py-6 text-center">No open positions</p>:
                  <div className="space-y-2">{positions.map((p:any)=><div key={p.ticket} className="flex items-center justify-between bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-2.5 text-sm"><div><span className={`text-xs font-bold px-1.5 py-0.5 rounded ${p.type==='BUY'?'bg-emerald-500/20 text-emerald-400':'bg-red-500/20 text-red-400'}`}>{p.type}</span><span className="ml-2 font-mono">{p.symbol} {p.volume}</span><span className={`ml-2 font-mono ${p.profit>=0?'text-emerald-400':'text-red-400'}`}>{p.profit?.toFixed(2)}</span></div><button onClick={async()=>{ await fetch(apiUrl(`/api/close/${p.ticket}`),{method:'POST'}); fetchAll(); }} className="text-xs px-2.5 py-1 rounded-lg bg-zinc-800 hover:bg-zinc-700 border border-zinc-700">Close</button></div>)}</div>)}
                {tab==='history' && (history.length===0?<p className="text-sm text-zinc-500 py-6 text-center">No history</p>:
                  <div className="space-y-1 text-xs font-mono">{history.slice(-20).reverse().map((h:any,i:number)=><div key={i} className="flex justify-between border-b border-zinc-800 py-1"><span>{h.symbol} {h.type}</span><span className={h.profit>=0?'text-emerald-400':'text-red-400'}>{h.profit}</span></div>)}</div>)}
                {tab==='log' && (
                  <div className="space-y-1 text-xs font-mono">
                    {(bot?.stats.log||[]).slice().reverse().map((l:any,i:number)=><div key={i} className={`py-1 border-b border-zinc-800 ${l.type==='success'?'text-emerald-400':l.type==='error'?'text-red-400':l.type==='warn'?'text-amber-400':'text-zinc-400'}`}><span className="text-zinc-600">[{l.time}]</span> {l.msg}</div>)}
                    {(bot?.stats.log||[]).length===0 && <p className="text-zinc-500 py-6 text-center">No bot logs yet — start the bot</p>}
                  </div>
                )}
              </div>
            </div>

            <p className="text-[11px] text-zinc-600 text-center">API <code className="bg-zinc-900 border border-zinc-800 px-1 py-0.5 rounded">{apiUrl('/api/status')}</code> • Set <code>NEXT_PUBLIC_API_URL</code> on Vercel to Railway backend URL.</p>
          </div>
        </div>
      </main>
    </div>
  );
}
