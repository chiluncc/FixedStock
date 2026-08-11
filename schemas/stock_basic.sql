-- 股票基本信息登记（全量保留，当前股票池由视图过滤）
CREATE TABLE IF NOT EXISTS stock_basic (
    code   TEXT PRIMARY KEY,   -- 6 位字符串代码，保留前导零
    name   TEXT NOT NULL,      -- 股票简称
    sector TEXT                -- 所属板块（来自 config/stocks.json）
);
