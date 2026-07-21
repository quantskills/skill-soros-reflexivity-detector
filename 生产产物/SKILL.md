---
name: skill-soros-reflexivity-detector-production
description: 当需要读取索罗斯反身性识别器（#48）的生产结果时，使用此 skill。读取已生成的 Parquet 结果（反身性阶段/评分/仓位建议/脆弱预警），不重复执行拉数与状态机计算。
tags: [quant, build, production, reflexivity, soros]
---

# 索罗斯反身性识别器生产结果（#48）

## 工具定位

- 工具类型：监控预警 + 分析报告型 BUILD 的生产结果
- 服务对象：盘后复盘 agent / 择时风控 agent / 人工研究 / 组合 Alpha
- 是否可被 Alpha 调用：是（`score`/`stage`/`fb_long`/`fb_neg` 等作特征）

## 结果文件

- 路径：`database.parquet`
- 格式：Parquet（无 pyarrow 时开发脚本降级 CSV）
- 更新频率：每日收盘后 `maintain_daily()` 追加
- 生成任务：`scripts/build.py`（watchlist 或 scan 漏斗）

## 当前内容（随包样例，真实数据）

- **溯源**：由 `python scripts/build.py --mode watchlist --symbols 300750.SZ 688256.SH --date 20260710 --save`
  从 **真实 PandaData** 生成（非合成/非测试桩），可用同一命令重建。
- 规模：**3 行 / 1 个交易日（20260710）** ——
  2 行 `reflexivity_stock`（300750.SZ 宁德时代、688256.SH 寒武纪）+ 1 行 `reflexivity_summary`（MARKET 汇总）。
- `data_version` / `build_id`：见文件内字段（`build_id="48"`）。

> 随包样例仅为**可跑通的演示结果**，只有 1 天 2 票；生产使用请按自己的股票池跑 `maintain_daily()` 逐日累积，
> 或用 `--mode scan` 做全市场漏斗。

## 主键

`trade_date` + `build_id`(="48") + `target_id` + `result_type`

## 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| trade_date | string | 交易日 |
| build_id / build_name | string | "48" / 索罗斯反身性识别器 |
| target_id / ts_code | string | 股票代码（汇总行为 MARKET） |
| result_type | string | `reflexivity_stock`（个股行）/ `reflexivity_summary`（每日汇总行） |
| result_value | string | 阶段 S0..S5（汇总行为 "N只/M脆弱"） |
| loop_type | string | fast / slow / dual / none |
| score | float | 反身性分 0-100 |
| position_advice | string | observe / add / hold / reduce / exit / avoid |
| conviction / in_test | int / bool | 信念计数（扛过几次考验）/ 是否考验中 |
| fragile_flag | bool | 脆弱预警（高质押/大解禁/折价出货） |
| p_trend/f_slope/fb_long/fb_neg/cog_f/par_f/fast_loop/sync/gap_pct | float | 各读数（可追溯） |
| dd_from_high / vol_div_peak / fuel_drop | float | 破裂(S4)判定三件套：距高点回撤% / 近 60 日量价顶背离峰值 / 燃料 20 日下滑 |
| plain_text | string | 一段人话研判（可直接引用给用户） |
| result_json | string | 完整诊断 JSON（含全中间状态） |
| data_version / update_time | string | 版本 / 生成时间 |

## 读取规则

```python
import pandas as pd, json
df = pd.read_parquet("database.parquet")
stocks = df[df.result_type == "reflexivity_stock"]
# 今日建议减仓（狂热）的票
reduce = stocks[stocks.position_advice == "reduce"]
# 脆弱预警
fragile = stocks[stocks.fragile_flag]
# 直接引用人话研判
for _, r in stocks.iterrows():
    print(r.ts_code, r.plain_text)
# 深挖中间读数
detail = json.loads(stocks.iloc[0].result_json)
```

默认使用最新有效交易日结果；若最新不存在可回退最近有效日，但须说明数据日期。
回答时必须带边界：**不预测顶底、非投资建议**。

## 禁止行为

- 不允许 agent 查询时重新拉数 / 重跑状态机。
- 不允许手工修改 Parquet。
- 生产结果异常时须提示数据日期与异常原因。

## 示例样本

- `sample_reflexivity.html` — 暗色诊断看板（宁德 S0 / 寒武纪 S1，学术读数+通俗解读）
- `sample_reflexivity.md` — markdown 档案样本
- `sample_688981_dashboard.html` — 单票诊断看板样本（688981.SH 中芯国际，含六维雷达 + 阶段时间序列 SVG）
