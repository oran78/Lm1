"""
Klop Apex — position ownership.

The bot may only count, manage (break-even), time-stop and close positions it opened itself. Everything else on the
same symbol (manual trades, other EAs, trades from the UI's manual buttons) is left strictly alone.

Ownership = the broker-side magic number, plus the tickets this process opened (a safety net while the broker's
position list does not yet echo the magic back). Positions whose layer does not report a magic at all are
"unknown": the bot neither touches them nor opens a new trade next to them (fail safe).
"""
from typing import Iterable

BOT_MAGIC = 20260611        # orders sent by the auto-trader
MANUAL_MAGIC = 20260612     # orders sent from the UI / POST /api/trade
BOT_COMMENT = "KlopApex-bot"
MANUAL_COMMENT = "KlopApex-manual"


def _magic(p: dict):
    m = p.get("magic")
    if m is None or m == "":
        return None
    try:
        return int(m)
    except (TypeError, ValueError):
        return None


def split_positions(positions: Iterable[dict], registry: set):
    """-> (owned, unknown). Anything else (foreign magic) is ignored by the bot."""
    owned, unknown = [], []
    for p in positions:
        if str(p.get("ticket")) in registry:
            owned.append(p)
            continue
        m = _magic(p)
        if m == BOT_MAGIC:
            owned.append(p)
        elif m is None:
            unknown.append(p)
    return owned, unknown
