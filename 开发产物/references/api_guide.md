# API 指南 · skill-soros-reflexivity-detector（#48）

> 数据源：PandaData（panda_data ≥ 0.0.9）。所有接口字段/频率经 **D1 真机实测（2026-07-11，
> 宁德时代/欧菲光/比亚迪/茅台）**，以下为落地口径。凭证走环境变量或 `~/.pandadata/pandadata.env`。

## 一、接口清单与用途

| 接口 | 用途 | 频率/口径（实测） | 标准面板列 / 事件 |
|---|---|---|---|
| `get_stock_daily` | 不复权 OHLC / 涨停 / 量 | 日频；**无 turnover** | close_raw/high/low/open/pre_close/volume/amount/is_limit_up/amplitude |
| `get_factor` | 后复权 close / 换手 / 市值 | 日频；turnover=换手% | close_adj/turnover/market_cap |
| `get_margin` | 融资余额（FB_long 燃料） | **日频**（融资 margin_type=cash） | margin_balance |
| `get_holder_count` | 股东户数（集中度） | 季频，公告日生效 | holder_count（as-of ffill） |
| `get_stock_pledge` | 累计质押率（FB_neg 质押螺旋） | 事件型，publish_date；`acc_pledge_total_ratio` | acc_pledge_ratio（as-of ffill） |
| `get_lhb_list` | 龙虎榜上榜（快环热度） | 事件型 | lhb（当日标记） |
| `get_hsgt_hold` | 北向持股 | **2024/08 后个股多停披露** → 常空 | north_ratio（有则用，权重默认 0） |
| `get_fina_forecast` | 业绩预告增速中值 | info_date；`(growth_floor+ceiling)/2` | 事件 forecast（净利同比%） |
| `get_fina_reports` | 财报归母净利同比 | 320 列，`is_n_income_attr_p`；`if_adjusted` 过滤；date=公告日 | 事件 report（累计同比%） |
| `get_fina_performance` | 业绩快报同比（可选补） | 覆盖不全（大票常空） | 事件 express |
| `get_repurchase` | 回购脉冲 | `procedure` 进度（实施/预案） | 事件 repurchase(+) |
| `get_stock_private_placement` | 定增实施（资本闭环） | `issue_status`="实施完成" | 事件 placement(+) |
| `get_stock_shareholder_change` | 增减持计划 | `direction` 增持/减持，info_date | 事件 holder_add(+)/holder_reduce(−) |
| `get_restricted_list` | 解禁供给（FB_neg 前瞻承压） | relieve_date | 事件 unlock |
| `get_block_trade` | 大宗折价（FB_neg 出货） | symbol+区间，含 buyer/seller/price | 事件 block_discount |
| `get_stock_status_change` | ST/退市风险（FB_neg 监管） | `type`/`description` | 事件 st |
| `get_trade_cal` | 交易日历（backfill） | — | — |

## 二、D1 实测关键结论（决定设计）

1. **`get_stock_daily` 无 turnover** → 换手率一律取自 `get_factor`（同时提供后复权 close 与市值）。
2. **北向个股数据 2024/08 起停披露**（茅台 2023/2024H1 有日频、宁德 2025-26 空）——政策性。FB_long 北向成分权重默认 0，`load_north` 返回 None 时优雅降级。
3. **快报覆盖不全**（宁德 `get_fina_performance` 空）→ F 链以预告(增速中值)+财报(自算累计同比)为主，快报为可选补充。
4. **`net_profit_yoy_const_forecast`（一致预期）常为 None** → surprise 不强依赖它，用 F_slope（相邻事件修正）为主。
5. **财报归母净利 = `is_n_income_attr_p`**（320 列中）；同 quarter 多行按 `if_adjusted` 优先当期、取最新公告日；累计同比 = 本期 / 去年同 quarter − 1，事件生效日 = 公告日 `date`。
6. **质押 `acc_pledge_total_ratio` = 累计质押总比例**（欧菲光实测 80%）——质押螺旋核心指标；`get_stock_pledge` 需 `start_date` 必填，`get_stock_pledge_stat` 是全市场统计（不吃 symbol，本 skill 不用）。

## 三、PIT（时点正确）口径

- 一切事件按**公告日**生效（forecast=info_date，report=公告 date，回购/增减持=公告日）；`analyze(as_of=...)` **先按 as_of 截断 panel/events 再计算**，杜绝前视泄漏（`cog_f`/`par_f` 含 shift 前视，必须先截断）。
- 财报 `is_latest=False` 拉全部，按公告日回放；同报告期取当期非追溯。
- 低频资金（融资/户数/质押）as-of ffill 到交易日（公告日当日起生效）。

## 四、流量预算与漏斗

- **watchlist 模式**（5–50 只）：每票约 12 个接口调用，单票 ~2–4s，流量可控，实时可用。
- **scan 模式**（全市场）：`funnel_universe` 先用一次全市场 `get_stock_daily` 算强趋势 top_n ∪ 近 20d 涨停≥2 的快环活跃票，再逐票深算——避免全市场逐票拉 margin/pledge（单股接口）造成流量爆。默认 `max_symbols=400`。
- 分段：全市场大跨度用 `chunk_pull`（365 天/段，600003/504 自动降级 90 天/段）。
- 错误码：500009（单日总流量超限，等次日）/ 600003（结果集超限，拆段）/ 200103（权限）/ 504（重试）——`_is_quota_or_service_error` 统一识别，scan 中单票失败跳过不中断。

## 五、依赖与运行

```bash
pip install --upgrade panda_data pyarrow      # ≥0.0.9
export PANDA_USERNAME=<手机号>; export PANDA_PASSWORD=<密码>   # 或 ~/.pandadata/pandadata.env
python scripts/build.py --mode watchlist --symbols 300750.SZ --date 20260710 --save
```

核心 `reflexivity.py` 零第三方重依赖（仅 numpy/pandas），`test.py` 全离线（无 panda_data 也全绿）。
