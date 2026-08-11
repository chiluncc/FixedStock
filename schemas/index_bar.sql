-- 指数日线（沪深300 / 中证500）
CREATE TABLE IF NOT EXISTS index_bar (
    index_code TEXT NOT NULL,        -- '000300' / '000905'
    date       INTEGER NOT NULL,     -- Unix 秒
    open REAL, high REAL, low REAL, close REAL,
    volume REAL, amount REAL,
    PRIMARY KEY (index_code, date)
);
