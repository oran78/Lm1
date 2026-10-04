# Klop Apex v2.7 — ownership, fixed daily-loss reference, real H1 context

## Safety fixes (verified against the code first)
* **The bot managed ANY position on the symbol** (break-even, opposite-signal close, time-stop, "1 position max"), including manual trades
  and other EAs. Now every order carries a magic number (`ownership.py`: bot `20260611`, manual UI/API `20260612`) and the bot only
  counts / modifies / closes positions with its magic (or tickets it opened in this process). Foreign positions are ignored and do not block entries.
  A position whose broker layer reports no magic at all is "unknown": untouched, and no new entry is opened beside it (fail safe).
  Applied to MetaApi (`magic`/`comment` on orders, echoed on positions), native MT5, the Windows bridge and paper mode.
  **Upgrade note:** positions opened by v2.6 or earlier have no bot magic -> v2.7 will not manage them (their broker-side SL/TP stay active).
* **Daily-loss limit moved with the balance** (`-pct * CURRENT balance`). It is now `pct * day-start balance`, fixed for the UTC day
  (`bot_stats.day_start_balance`, reset at the new day; after a restart it is the balance at restart, like the P/L counters).
* **`POST /api/trade` bypassed the risk engine** (only lot bounds were checked). It now runs the same gates as the bot
  (`bot_engine.manual_trade_check`): daily-loss limit, per-trade risk cap when an SL is attached, margin, lot bounds, hourly limit; fails closed without
  account data. Manual orders are tagged with the manual magic so the auto-trader never touches them.
* **RSI**: the pullback RSI (lowest/highest of the last 3 candles) alone could satisfy the band while the current candle's RSI was already
  extended. `rsi_ok()` now also requires the current RSI to be <= 65 for BUY / >= 35 for SELL.
* Minimum-lot rejection already existed and is unchanged: a trade whose real risk exceeds `risk_cap_pct` is blocked, never resized upwards.

## Strategy: real context layer (all switchable, library default = off = the v2.6 behaviour)
* `market_context.py`: look-ahead-free fractal swings (a swing is reported only after 2 later candles closed and never changes), M5 structure
  (HH+HL = BULL, LH+LL = BEAR) and a real **H1 bias** (EMA20/EMA50 gap in H1 ATR, EMA50 slope, close vs EMA50, H1 structure) from CLOSED H1 candles.
* `htf_mode` (default **counter**): off / counter (block trades against H1) / strict (H1 must agree; no H1 data = no trade).
* `structure_mode` (default **counter**): same three modes for the M5 structure.
* Every trigger now lists why it fired (`why: H1 BULL; M5 structure RANGE; EMA9/21 pullback; bullish rejection; RSI 55→60; Stoch 52/18; liquidity sweep`).
  The sweep is information only (no gate).
* UI: "Market context" selects in the Auto Flip card.

## Deliberately NOT done (and why)
* Backtest engine / A-B report / walk-forward / session statistics: you asked for no backtest and there is no historical data in this environment.
  So the defaults above are reasoned, **not measured**; nothing here shows the strategy is profitable.
* Weighted signal score: weights would have to come from backtest evidence. The hard gates + the printed reasons are used instead.
* ADX filter, BE-at-1.2R / structure-based BE, swing-target TP, session selector: no evidence to choose between variants. Spike guard, spread guard and the
  ATR SL/TP baseline are unchanged. No news filter was invented (none exists in the project).

## Tests
`backend/tests/test_v27.py` (new): ownership split, manual/unknown/bot positions inside the real engine loop, swing no-look-ahead, structure, H1 bias, RSI rule,
strategy gates, day-start reference, min-lot rejection, manual-trade gate, config hygiene. Engine-level tests pin the context filters to "off" so they keep testing the engine.

---

# Klop Apex v2.6 — conflicts resolved, loss protection, honest stats

## One parameter set (code == defaults == this file)
The v2.5 notes and the code disagreed (code had silently been loosened to "Pro Scalper" values, bot_config overrode the strategy defaults).
`strategy.py` constants are now the single source of truth and the bot/UI defaults match them:
| setting | v2.5 notes | v2.5 code | **v2.6** |
|---|---|---|---|
| SL / TP (x ATR) | 1.2 / 1.8 | 1.0 / 1.5 (bot_config) | **1.2 / 1.8** |
| break-even trigger | 1R | 0.8R | **1.0R** |
| CHOP gap | 0.3 x ATR | 0.25 | **0.30** |
| RSI cooled band | 42-58 | 38-62 | **42-58** |
| approach zone | 0.75 ATR | 0.85 | **0.75** |
| EMA50 macro filter | (undocumented) | on | **on, documented** (`MACRO_EMA`) |

## Strategy changes
* **Stochastic(5,3) is a real gate** (it only changed a confidence number before, and `K < 70` was almost always true):
  BUY needs K > D and K < 80, SELL needs K < D and K > 20. Switch off with `STOCH_CONFIRM = False`.
* **Spike guard**: a closed candle with true range > 2.5 x (pre-spike) ATR in the last 2 candles blocks entries
  (news / stop-run protection without needing a calendar). `SPIKE_ATR`, `SPIKE_LOOKBACK`.
* Removed the unused Bollinger code. Chart label "TARGET ENTRY" -> "PULLBACK ZONE (EMA9)": the bot enters at market on the
  rejection close, it does not rest a limit order at EMA9.

## Engine / stats fixes
* **Real P/L**: a closed trade is priced from the broker's deal history (profit + commission + swap, matched by position id).
  Last floating P/L is only a fallback, used after 20 s without a deal. History now returns `position_id/commission/swap`.
* **Scratch trades** (|P/L| < 15% of the initial risk, i.e. break-even exits) are counted as `breakevens`, not wins -> win rate is honest.
* `total_trades` counted twice (open + close) -> now once, on close.
* First pass after start/restart seeds the candle clock: it never trades an already-closed (stale) candle.
* **Loss handling, no day-long stop**: `cooldown_candles_after_loss` (2) skips a couple of candles after a loss; after
  `loss_streak_trigger` (3) losses in a row the break is `loss_streak_cooldown_candles` (6 = 30 min on M5). Then the bot searches again.
  It keeps looking for entries until `max_trades_per_day` or the flip target is reached. Set the trigger to 0 to keep only the short cooldown.
* **Risk limits are editable in the UI** (Auto Flip Engine card -> "Risk limits"):
  * *Daily loss limit* switch + % (`daily_loss_limit_enabled`, `max_daily_loss_pct`, default ON / 8). OFF = the bot trades until
    `max_trades_per_day` or the flip target. This is the only day-long stop left.
  * *Max risk cap / trade %* (`risk_cap_pct`, default 20): a trade whose real risk (e.g. min lot on a tiny account) is above it is blocked.
    It replaces the hidden 10% / 20% / 35% caps. "$10 Flip Mode" is now just a preset that fills the cap with 20 (off = 10).
  * *Risk / trade %* accepts 0.1-25 (was 0.1-5); the UI warns above 2% and turns red above 10% / when the daily limit is off.
  * The server clamps everything too (risk 0.05-50, cap 0.5-100, daily 0-100).
* Managed closes (opposite signal / time-stop) no longer book P/L themselves; the sync step books it once from broker deals.
* When the minimum lot forces more than 2x the configured risk_pct, the log says so
  (e.g. "min lot 0.01 forces 20.0% risk (setting is 1%)").

## Tests
`python backend/tests/test_strategy.py | test_engine.py | test_metaapi.py | test_chart_state.py | test_v26.py` - all pass on SIMULATED data.
Two existing tests were corrected: the no-repaint test compared different candle windows (it only passed because the old loose filters
fired on consecutive candles) and the chart-state test now expects broker-priced P/L. No backtest was run: profitability is NOT demonstrated.

---

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
