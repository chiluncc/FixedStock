# A股个股量化投资研报生成系统

基于公开历史行情、财务与估值数据，对股票池内的每只股票独立生成量化投资研报（PDF/HTML），并输出投资组合权重。研报内容包括价格与均线走势、量价关系、财务估值、因子评分雷达、未来收益预测与风险分析；投资观点摘要与投资分析由 LLM（DeepSeek）撰写，量化图表与统计由固定算法计算。

## 项目结构

```text
stock/
├── config/config.json          # 运行配置（数据目录、股票池、买入时点等）
├── schemas/*.sql               # SQLite 建表/视图 SQL
├── data/market.db              # 本地数据库（行情/财务/估值/交易日历）
├── .keys/llm.yaml              # LLM API Key（gitignore）
├── src/stock/
│   ├── ui/main.py              # 命令行入口
│   ├── ui/data_build.py        # 数据抓取与本地库构建
│   ├── ui/data_analysis.py     # 指标计算、LLM 分析、报告输出、组合权重
│   ├── agent/                  # LLM Agent（提示词、工具）
│   ├── structures/             # 配置与研报数据结构
│   └── utils/                  # SQL、HTML 渲染、WeasyPrint PDF 转换、日志等
└── tests/                      # 单只报告渲染/PDF 转换等辅助脚本
```

## 输入与输出

### 输入

| 输入 | 说明 |
|---|---|
| `config/config.json` | 数据目录、输出目录、买入时点、持仓天数、股票池分组 |
| `.keys/llm.yaml` | DeepSeek API Key |

### 输出

| 输出 | 说明 |
|---|---|
| `output/个股投资研报/<code>.pdf` | 单只研报 PDF（默认） |
| `output/个股投资研报/<code>.html` | PDF 生成失败（如缺 libpango）时自动回退的 HTML |
| `output/Portfolio.json` | 组合权重，格式 `{"000333": 0.032, "000001": 0, ...}` |
| `output/logging.log` | 主日志 |
| `output/logs/stock_<code>/logging.log` | 每只股票的 LLM 分析日志 |

## 配置说明

### config.json

| 字段 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `stocks` | 是 | 无 | 股票池，按板块分组，值为 6 位代码数组 |
| `local_data_dir` | 否 | `data` | 本地数据目录（含 `market.db`） |
| `output_dir` | 否 | `output` | 输出根目录 |
| `time_start` | 否 | 当前时间 | 买入时点，格式 `YYYY-MM-DD`；所有分析以该日期为数据截止日。建议显式填写以保证可复现 |
| `time_position` | 否 | `20` | 持仓交易日数（报告中"20 个交易日"等均取自该值） |
| `portfolio_power` | 否 | `0.7` | 组合权重幂指数 |

最简配置只需 `stocks` 字段，其余均按默认值生效。

### .keys 配置

在 `.keys/llm.yaml` 中配置 DeepSeek API Key：

```yaml
deepseek: sk-xxxxxxxx
```

## 环境与复现

### 环境要求

- Python 3.12，使用`UV`进行环境管理
- 系统字体：`Droid Sans Fallback`（中文字体，通常随系统自带）
- PDF 输出依赖 WeasyPrint 及其系统库 `libpango-1.0-0`、`libpangoft2-1.0-0`；未安装时自动回退输出 HTML

### 安装

```bash
uv sync
```

### 运行

```bash
uv run generate -c config/config.json
```

## 免责声明

本项目基于公开历史数据与量化模型生成研报，仅用于研究分析，不构成投资建议。
