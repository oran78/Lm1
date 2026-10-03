# Klop Apex v2.5 — Momentum Pullback Scalper + chart execution

## Strategy (backend/strategy.py) — closed candles only
* Bias: EMA9 > EMA21 and EMA21 rising -> BUY only; EMA9 < EMA21 and falling -> SELL only.
* CHOP: |EMA9-EMA21| < 0.3 x ATR -> no trading.
* `PLANNED_SETUP`: bias active, price within 0.75 ATR of / inside the EMA9-EMA21 zone, RSI(14) cooled to 42-58
  (lowest/highest of the last 3 closed candles). `planned_entry_price = EMA9`.
* Trigger: closed candle touches the zone and closes back beyond EMA9 with a real body or a rejection tail.
  Blocked if spread > 35 points or > 0.5 x ATR. Max 1 open trade.
* Trade plan (`plan_trade`): SL 1.2 x ATR, TP 1.8 x ATR (R:R 1.5). The stop is pushed beyond the pullback swing
  (+0.1 ATR) when the swing is further away, TP is stretched to keep R:R >= 1.5, and the trade is skipped if the
  stop would need > 2 x ATR.
* Auto break-even (`break_even_sl`): at +1R the SL moves to entry +/- spread, once (MetaApi `POSITION_MODIFY`).
* ADX is still reported for the UI but no longer gates trades.

## Engine / telemetry
* `bot.planned_setup` {side, entry_price} and `bot.active_trade` {ticket, side, lot, entry, sl, tp, be_active} are in
  `/api/status` and `/ws/telemetry` (now every 1 s). Markers carry `ticket` and the REAL fill price from the broker
  position, and are rebuilt from open positions after a restart.
* Time-stop uses the broker's open time (survives restarts). Loop split into `_step()`.
* Config defaults: SL 1.2 / TP 1.8 ATR, max spread 35 pts, `be_enabled`, `be_trigger_r` = 1.0.

## MetaApi / safety
* `modify_position()` added (MetaApi + paper + native MT5). Orders with SL/TP on the wrong side are rejected before
  they reach the broker; volume is floored to the lot step (never rounded up). Gold symbol still resolved per account.
* Removed the hard-coded 4141.5 fallback tick in main.py (no fabricated prices).

## Frontend
* `TradingChart`: amber dashed `TARGET ENTRY @ price`; TP green, SL red, BREAK-EVEN cyan lines; BUY/SELL arrows
  labelled `BUY 0.03 @ 4141.50`. Lines/markers update in place (no chart reload). Types in `src/lib/types.ts`.
* Not verified: `npm install && npm run build` (no network here) — only `tsc --noEmit` against stubbed React/Next types.

## Tests
`python backend/tests/test_strategy.py | test_engine.py | test_metaapi.py | test_chart_state.py` — all pass on
SIMULATED data. Run one demo account before real money.

---

# Klop Apex v2.4 — MetaApi + XAUUSD activation, new frontend

## Why XAUUSD never became "active" after connecting MetaApi
1. Wrong price endpoint: code called `/symbols/X/currentPrice`; MetaApi's is `/symbols/X/current-price` -> always 404 -> no live tick.
2. Symbol name: Exness names gold per account type (`XAUUSD`, `XAUUSDm`, `XAUUSDc`, `XAUUSDz`...). The symbol is now looked up in the broker's own list (`/symbols`) and cached; positions are mapped back to `XAUUSD`.
3. Close used a non-existent route; now `POST /trade {actionType: POSITION_CLOSE_ID}`.
4. HTTP 200 from `/trade` was treated as filled. Now `stringCode` is checked (e.g. MARKET_CLOSED, NO_MONEY, INVALID_STOPS are reported as errors).
5. A provisioning request ran before every tick/position/order (rate-limit + slow). Region host is cached; telemetry runs off the event loop.
6. Chart/history endpoints ignored MetaApi (chart showed fallback data). They now use broker candles / deals.
7. Risk maths now uses the broker's real contract size, min lot and lot step (important for Cent accounts).
8. Auto-reconnect on startup when `METAAPI_TOKEN` + `METAAPI_ACCOUNT_ID` are set (Railway restarts no longer drop the connection).

## New
* `GET /api/xau/status` — readiness checklist (account, symbol, live tick, candles, fresh market, session).
* `POST /api/xau/activate` — resolves the gold symbol, subscribes the price, warms candles, points the bot at XAUUSD. Does NOT start trading.
* Frontend rebuilt: XAUUSD hero + checklist, flicker-free chart with M1/M5/M15/H1, indicator meters, bot form no longer resets while typing, manual trades attach ATR SL/TP and ask for confirmation, risk input validated (0.1-5%).
* Connect now auto-activates XAUUSD.

## Not verified (no live account/network in the build environment)
* `python backend/tests/test_metaapi.py` runs against a SIMULATED MetaApi (paths follow the official docs). Run one demo-account connect before real money.
* Frontend was syntax-checked but not built (`npm install && npm run build` on your side).
* Symbol spec field names (contractSize/minVolume/volumeStep/digits) fall back to safe defaults if absent.

---

# Klop Apex v2.3 — fixes (backend)

## Critical bugs fixed
1. Fake data: candles were a RANDOM WALK and prices got random jitter -> signals on noise. Now real 1m history (Binance PAXG, shifted to spot) + live ticks; MetaApi/MT5 candles used when connected. No fabricated prices.
2. Duplicate trades: same EMA cross re-fired every ~12 s while the candle was open. Now 1 signal per CLOSED candle, max 1 open position.
3. Lot/risk maths wrong for XAUUSD (1 lot = 100 oz). A "3% risk" trade on $10 really risked 20-50%. Fixed; trades whose minimum-lot risk exceeds the hard cap are blocked.
4. Paper positions never hit SL/TP and balance never changed. Fixed.
5. Closes recorded P/L = 0 -> win rate / PnL were meaningless. Real P/L tracked; daily loss limit enforced.
6. No exit management. Added opposite-signal close + time-stop; broker SL/TP closes detected.
7. ADX was raw DX; indicators repainted on the forming candle. Real Wilder ADX, closed candles only; new pullback setup; spread filter relative to ATR; session_filter honoured (weekends blocked).
8. /api/bot/start refused to start with MetaApi; blocking HTTP inside async loop. Fixed.

## Not changed / not verified
* frontend/ untouched. MetaApi get_candles endpoint is unverified against a live account.
* Run `python backend/tests/test_strategy.py` and `python backend/tests/test_engine.py`.
