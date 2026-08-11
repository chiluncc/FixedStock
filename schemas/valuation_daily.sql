-- 日频估值序列（PE(TTM) / PB）
CREATE TABLE IF NOT EXISTS valuation_daily (
    code     TEXT NOT NULL,
    date     INTEGER NOT NULL,
    pe_ttm   REAL,
    pb       REAL,
    total_mv REAL,
    PRIMARY KEY (code, date)
);
CREATE INDEX IF NOT EXISTS idx_valuation_date ON valuation_daily(date);
