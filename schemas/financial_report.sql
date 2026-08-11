-- 全部股票财报
CREATE TABLE IF NOT EXISTS financial_report (
    code          TEXT NOT NULL,
    report_date   INTEGER NOT NULL,  -- 报告期（Unix 秒）
    announce_date INTEGER,           -- 披露日期（合规过滤：必须早于买入时点）
    roe           REAL,
    revenue_yoy   REAL,              -- 营收同比
    netprofit_yoy REAL,              -- 归母净利同比
    gross_margin  REAL,
    debt_ratio    REAL,
    PRIMARY KEY (code, report_date)
);
