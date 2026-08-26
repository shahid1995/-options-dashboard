"""Configuration constants for the candle data pipeline (Phase 7.8).

Centralizes instrument keys, chunk sizes, retry parameters, and NSE
trading-hour constants so they are discoverable in one place and
shared across the adapter, ingestion, validation, and backfill layers.
"""

# ---------------------------------------------------------------------------
# Upstox instrument keys
# ---------------------------------------------------------------------------

# V3 Historical Candle API instrument key for NIFTY 50 index
NIFTY_INSTRUMENT_KEY = "NSE_INDEX|Nifty 50"

# V2 Expired Instruments API instrument key (same underlying)
EXPIRED_NIFTY_INSTRUMENT_KEY = "NSE_INDEX|Nifty 50"

# ---------------------------------------------------------------------------
# Candle pipeline defaults
# ---------------------------------------------------------------------------

CANDLE_UNIT = "minutes"
CANDLE_INTERVAL = 3  # 3-minute candles

# For 3-min intervals the max retrieval window is 1 month.
# 28 days is conservative and uniform across all calendar months.
MAX_CHUNK_DAYS = 28

# ---------------------------------------------------------------------------
# Rate-limit headroom
# ---------------------------------------------------------------------------

# Upstox allows 50/sec, 500/min, 2000/30min.
# We're well below these with monthly chunks, but set a floor anyway.
MIN_REQUEST_INTERVAL_SECONDS = 0.1  # 100 ms between requests

# ---------------------------------------------------------------------------
# Retry / back-off configuration
# ---------------------------------------------------------------------------

MAX_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 1.0
RETRY_MAX_DELAY_SECONDS = 30.0
RETRY_BACKOFF_MULTIPLIER = 2.0

# ---------------------------------------------------------------------------
# NSE trading hours (IST)
# ---------------------------------------------------------------------------

MARKET_OPEN_IST = "09:15"

# NIFTY index closes at 15:27 IST
INDEX_MARKET_CLOSE_IST = "15:27"
INDEX_CANDLES_PER_TRADING_DAY = 124  # 09:15-15:27 = 6h12m / 3min

# NIFTY options trade until 15:40 IST (extended session)
OPTION_MARKET_CLOSE_IST = "15:40"
OPTION_CANDLES_PER_TRADING_DAY = 128  # 09:15-15:40 = 6h25m / 3min

# Legacy alias (index candles)
MARKET_CLOSE_IST = INDEX_MARKET_CLOSE_IST
CANDLES_PER_TRADING_DAY = INDEX_CANDLES_PER_TRADING_DAY
