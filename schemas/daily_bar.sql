-- 全部股票的前复权日线
CREATE TABLE IF NOT EXISTS daily_bar (
    code     TEXT NOT NULL,
    date     INTEGER NOT NULL,      -- Unix 秒
    open     REAL, high REAL, low REAL, close REAL,  -- 前复权价格
    volume   REAL,   -- 成交量，统一单位：股
    amount   REAL,   -- 成交额，元
    turnover REAL,   -- 换手率，统一单位：%
    PRIMARY KEY (code, date)
);
CREATE INDEX IF NOT EXISTS idx_bar_date ON daily_bar(date);
