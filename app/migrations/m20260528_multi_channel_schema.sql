PRAGMA foreign_keys = OFF;

DROP TABLE IF EXISTS notifications;
DROP TABLE IF EXISTS valuation_signals;
DROP TABLE IF EXISTS user_subscriptions;

PRAGMA foreign_keys = ON;

-- User Entity (Identity Layer)
CREATE TABLE IF NOT EXISTS users (
  id         TEXT    PRIMARY KEY,
  name       TEXT    NOT NULL,
  enabled    BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TEXT    NOT NULL,
  updated_at TEXT    NOT NULL
);

-- User x Index Subscriptions (Business Layer)
CREATE TABLE IF NOT EXISTS user_index_subscriptions (
  id          TEXT    PRIMARY KEY,
  user_id     TEXT    NOT NULL,
  index_id    TEXT    NOT NULL,
  base_amount REAL    NOT NULL DEFAULT 1000.0,
  enabled     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at  TEXT    NOT NULL,
  updated_at  TEXT    NOT NULL,
  UNIQUE(user_id, index_id),
  FOREIGN KEY(user_id)  REFERENCES users(id),
  FOREIGN KEY(index_id) REFERENCES indices(id)
);

-- User Notification Endpoints (Notification Layer)
CREATE TABLE IF NOT EXISTS user_notification_endpoints (
  id             TEXT    PRIMARY KEY,
  user_id        TEXT    NOT NULL,
  channel_type   TEXT    NOT NULL,   -- 'telegram' | 'feishu'
  target         TEXT    NOT NULL,   -- Non-sensitive identifier
  credential_enc TEXT    NOT NULL,   -- Fernet encrypted JSON blob
  enabled        BOOLEAN NOT NULL DEFAULT TRUE,
  created_at     TEXT    NOT NULL,
  updated_at     TEXT    NOT NULL,
  UNIQUE(user_id, channel_type, target),
  FOREIGN KEY(user_id) REFERENCES users(id)
);

-- Valuation Signals
CREATE TABLE IF NOT EXISTS valuation_signals (
  id                         TEXT    PRIMARY KEY,
  user_index_subscription_id TEXT    NOT NULL,
  index_id                   TEXT    NOT NULL,
  trade_date                 TEXT    NOT NULL,
  pe_percentile              REAL,
  pb_percentile              REAL,
  cape_percentile            REAL,
  dividend_yield_percentile  REAL,
  dividend_yield_inverse_percentile REAL,
  price_percentile           REAL,
  composite_percentile       REAL,
  signal_quality             TEXT    NOT NULL,
  valuation_zone             TEXT    NOT NULL,
  dca_ratio                  REAL    NOT NULL,
  suggested_amount           REAL    NOT NULL,
  message                    TEXT    NOT NULL,
  created_at                 TEXT    NOT NULL,
  UNIQUE(user_index_subscription_id, trade_date),
  FOREIGN KEY(user_index_subscription_id) REFERENCES user_index_subscriptions(id),
  FOREIGN KEY(index_id) REFERENCES indices(id)
);

-- Notification Send Attempts
CREATE TABLE IF NOT EXISTS notifications (
  id            TEXT    PRIMARY KEY,
  signal_id     TEXT    NOT NULL,
  endpoint_id   TEXT    NOT NULL,
  channel       TEXT    NOT NULL,   -- Redundant: 'telegram' | 'feishu'
  target        TEXT    NOT NULL,   -- Redundant identifier
  status        TEXT    NOT NULL,   -- 'sent' | 'failed'
  error_message TEXT,
  sent_at       TEXT,
  created_at    TEXT    NOT NULL,
  FOREIGN KEY(signal_id)   REFERENCES valuation_signals(id),
  FOREIGN KEY(endpoint_id) REFERENCES user_notification_endpoints(id)
);
