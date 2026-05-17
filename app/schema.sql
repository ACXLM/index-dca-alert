PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS indices (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  market TEXT NOT NULL,
  category TEXT NOT NULL,
  currency TEXT NOT NULL,
  timezone TEXT NOT NULL,
  primary_provider TEXT NOT NULL,
  source_symbol TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS index_valuations (
  id TEXT PRIMARY KEY,
  index_id TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  pe REAL,
  pb REAL,
  cape REAL,
  dividend_yield REAL,
  close REAL,
  source TEXT NOT NULL,
  source_type TEXT NOT NULL DEFAULT 'native_index',
  metric_schema_version TEXT NOT NULL DEFAULT 'v1',
  raw_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(index_id, trade_date, source),
  FOREIGN KEY(index_id) REFERENCES indices(id)
);

CREATE TABLE IF NOT EXISTS dca_rules (
  id TEXT PRIMARY KEY,
  category TEXT NOT NULL UNIQUE,
  lookback_years INTEGER NOT NULL DEFAULT 5,
  minimum_observations INTEGER NOT NULL DEFAULT 500,
  metric_weights_json TEXT NOT NULL,
  zone_rules_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_subscriptions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  index_id TEXT NOT NULL,
  base_amount REAL NOT NULL DEFAULT 1000,
  notify_channel TEXT NOT NULL DEFAULT 'telegram',
  notify_target TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(index_id) REFERENCES indices(id)
);

CREATE TABLE IF NOT EXISTS valuation_signals (
  id TEXT PRIMARY KEY,
  user_subscription_id TEXT NOT NULL,
  index_id TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  pe_percentile REAL,
  pb_percentile REAL,
  cape_percentile REAL,
  dividend_yield_percentile REAL,
  dividend_yield_inverse_percentile REAL,
  price_percentile REAL,
  composite_percentile REAL,
  signal_quality TEXT NOT NULL,
  valuation_zone TEXT NOT NULL,
  dca_ratio REAL NOT NULL,
  suggested_amount REAL NOT NULL,
  message TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(user_subscription_id, trade_date),
  FOREIGN KEY(user_subscription_id) REFERENCES user_subscriptions(id),
  FOREIGN KEY(index_id) REFERENCES indices(id)
);

CREATE TABLE IF NOT EXISTS notifications (
  id TEXT PRIMARY KEY,
  signal_id TEXT NOT NULL,
  channel TEXT NOT NULL,
  target TEXT NOT NULL,
  status TEXT NOT NULL,
  error_message TEXT,
  sent_at TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(signal_id) REFERENCES valuation_signals(id)
);

CREATE TABLE IF NOT EXISTS market_runs (
  id TEXT PRIMARY KEY,
  market TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  run_type TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  error_message TEXT,
  UNIQUE(market, trade_date, run_type)
);

CREATE TABLE IF NOT EXISTS data_quality_events (
  id TEXT PRIMARY KEY,
  index_id TEXT NOT NULL,
  trade_date TEXT,
  source TEXT NOT NULL,
  event_type TEXT NOT NULL,
  message TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(index_id) REFERENCES indices(id)
);

