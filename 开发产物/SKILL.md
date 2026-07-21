---
name: skill-soros-reflexivity-detector
description: 当需要判断一只/一组 A 股"这波涨跌是不是自我强化的反身性行情、转到哪一圈了、燃料和裂缝在哪"时，使用此 skill。基于索罗斯反身性理论 + A 股市场视角，用双环模型（快环情绪-资金 / 慢环基本面-资本）做阶段识别与仓位纪律。可被复盘 agent 或 Alpha 调用。
tags: [quant, build, development, reflexivity, soros, regime, monitor]
---

# 索罗斯反身性识别器 BUILD（#48）

## 工具定位

- 工具类型：监控预警 + 分析报告型 BUILD
- 解决问题：把"价格自己制造行情"的**强度与阶段**量化出来——回答交易上三个要命问题：
  1. 这波涨/跌是不是**自我强化**的（能不能顺势）？
  2. 循环转到**哪一圈**了（决定仓位纪律）？
  3. **增量资金**还在流入吗、**潜在抛压**（质押/解禁/大宗折价）在积累吗（何时退出、出事跌多深）？
- 使用对象：盘后复盘 agent / 择时与风控 agent / 人工研究 / 组合 Alpha（当特征）
- **明确不做**：不预测顶底、不判断"价值"、不假设市场有效。仅研究/教育示例，**不构成投资建议**。

## 核心框架：双环模型（市场视角 × 索罗斯学院视角）

> 反身性（通俗）：**涨会让它更涨、跌会让它更跌**——参与者的认知/偏见改变价格，价格又反过来改变认知，形成自我强化回路。有效市场假说在真实市场基本失真，追涨杀跌是常态。

| 环 | 回路（人话） | 周期 | 主战场 | 判定读数 |
|---|---|---|---|---|
| **快环**（情绪-资金） | 涨→上热榜→更多人买→再涨 | 天–周 | 题材股、游资股（**可无基本面**） | FastLoop（价格×关注度×资金 共振） |
| **慢环**（基本面-资本） | 涨→增发/回购改善报表→基本面上修→再涨 | 季–年 | 趋势白马、产业主升浪 | CogF×ParF（双函数活跃） |
| **双环共振** | 快慢同时闭合 | — | 最强反身性（如全民追捧的高景气龙头） | 两者皆高 |

输出 `loop_type ∈ {fast, slow, dual, none}` 决定用哪套窗口参数（快环按天、慢环按季）。

## 阶段状态机（六阶段 + 考验，连续确认防抖）

| 阶段 | 人话 | 建议 |
|---|---|---|
| S0 中性 | 没有自我强化回路 | observe |
| S1 萌芽 | 先知先觉资金进场，趋势未被大众认知 | observe |
| S2 加速 | 大众追涨、增量资金充足、在加速（含 **考验 S2T**：回调洗盘扛过则 conviction+1） | **add** |
| S3 狂热→暮色 | 分位极高、基本面跟不上；**"利好不涨"(CogF 衰减)= 暮色第一信号** | **reduce** |
| S4 破裂 | 自高点回撤 ≥ `break_dd`(15%) + （**量价顶背离** 或 资金退潮 或 基本面转弱） | exit |
| S5 负反身性 | 越跌越卖（含质押螺旋：跌→强平→再跌） | avoid |

`conviction`（信念计数）= 扛过几次洗盘考验，越高破裂越猛（S3 减得越坚决）。

### 破裂（S4）判定口径

**破裂只能从回路里掉出来**——状态机限定前一阶段必须是 S1/S2/S3，从未入过回路的票即便深度回撤
也只是普通下跌，落 S0 而不冒认破裂（防误报，真实数据实测见 quality_evidence.md）。三项依据均写入诊断可追溯：

| 字段 | 含义 | 口径 |
|---|---|---|
| `dd_from_high` | 距近期高点回撤 % | 门槛 `break_dd = 15%` |
| `vol_div_peak` | 近 60 日**量价顶背离**峰值 | 价近滚动高点(≥0.95) 且 20 日均量相对基准缩量；门槛 `voldiv_break = 60` |
| `fuel_drop` | 增量资金 20 日下滑幅度 | 门槛 `fuel_drop_break = 20`（融资/游资明显退潮） |

> 顶背离是**顶部**信号，跌下来后当日 `vol_divergence` 自然归零，故判定用的是 60 日峰值
> `vol_div_peak`——语义即"顶部出现过背离，随后跌破"。

## 输入

数据来自 PandaData（凭证走环境变量/`~/.pandadata/pandadata.env`），或调用方直接传入标准面板。

`run(input_data, config=None)` 三种输入：

| 形态 | 例 | 说明 |
|---|---|---|
| watchlist | `{"symbols":["300750.SZ"],"date":"20260710"}` | 逐票深算（实时） |
| scan | `{"mode":"scan","date":"20260710","top_n":300}` | 漏斗全市场（重，生产用） |
| 直连 | `{"panel":<DataFrame>,"events":[...],"symbol":"X"}` | 调用方已有数据，跳过拉数（离线可用） |

## 输出（BUILD §11 标准面板）

主键 `(trade_date, build_id="48", target_id, result_type)`。`result_type`：个股行 `reflexivity_stock` + 每日 `reflexivity_summary` 汇总行。

| 字段 | 说明 |
|---|---|
| result_value | 阶段 S0..S5 |
| loop_type | fast/slow/dual/none |
| score | 反身性分 0-100 |
| position_advice | observe/add/hold/reduce/exit/avoid |
| conviction / in_test | 信念计数 / 是否考验中 |
| fragile_flag | 脆弱预警（高质押/大解禁/折价出货） |
| p_trend/f_slope/fb_long/fb_neg/cog_f/par_f/fast_loop/sync/gap_pct | 各读数（全落盘，可追溯） |
| **plain_text** | 一段人话研判（agent 可直接引用给用户） |
| result_json | 完整诊断 JSON |

## 调用方式

```python
from scripts.build import run, maintain_daily, save_parquet
panel = run({"symbols": ["300750.SZ", "688256.SH"], "date": "20260710"})   # watchlist
panel = run({"mode": "scan", "date": "20260710", "top_n": 300})            # 全市场漏斗
# 调用方已有数据（离线）：
panel = run({"panel": my_df, "events": my_events, "symbol": "X.SZ"})

from scripts.render import render_markdown, render_html
md = render_markdown(panel); html = render_html(panel)             # 学术读数+通俗解读

# 生产维护
save_parquet(maintain_daily(symbols=["300750.SZ"], date="20260710"))
```

命令行：
```bash
export PANDA_USERNAME=<手机号>; export PANDA_PASSWORD=<密码>   # 或用 ~/.pandadata/pandadata.env
python scripts/build.py --mode watchlist --symbols 300750.SZ 688256.SH --date 20260710 --save
python scripts/build.py --mode scan --date 20260710 --top-n 300 --save
python scripts/test.py                                        # 全离线自测（无 SDK 也全绿）
```

## Agent 执行规则

1. 调用方已有面板数据 → 用 `run({"panel":...})`，不重复拉数。
2. 每日生产用 `maintain_daily()` + `save_parquet()`，他人读 parquet 不重算。
3. **问答**：读 `database.parquet` 按 `result_type` 拆分，用 `plain_text` 直接回答；深挖读 `result_json`。
4. 引用阶段/建议时必须带上"非投资建议、不预测顶底"的边界。
5. 先 `python scripts/test.py` 全绿；真实数据因配额/无 SDK 自动跳过（不判失败）。

## 术语表（学术 → 人话，交付语言规范）

| 学术术语 | 人话解读 |
|---|---|
| 反身性 | 涨会让它更涨、跌会让它更跌的自我强化循环 |
| 快环 / 慢环 | 情绪-资金环（题材股，按天）/ 基本面-资本环（白马，按季） |
| CogF 认知弹性 | 市场对利好的兴奋度；"利好不涨"=兴奋耗尽（暮色） |
| ParF 参与活跃 | 股价是否在"改造"公司（高位增发圈钱、回购增厚 EPS） |
| FastLoop | 热度和钱是否在互相点火 |
| GAP 裂口 | 股价跑在基本面前面多远（透支多少） |
| conviction | 扛过几次洗盘考验；越扛越信、越信越危险 |
| FB_long / FB_neg | 增量资金（新资金流入强度）/ 潜在抛压（高质押、大解禁、折价出货） |
| Sync | 价格与基本面是否同向共振（回路是否闭合） |
| S0–S5 | 中性→先知先觉→大众追涨→狂热见暮色→破裂→越跌越卖 |
| PIT | 只用当时已公告的信息，不偷看后来才发布的数据 |

## 可被 Alpha 调用

- 是。`run()` 返回标准面板，`score`/`stage`/`fb_long`/`fb_neg` 等可作因子特征输入。
- 调用限制：watchlist 模式输入需 `symbols`；深算需能拉到该票的价格+资金+事件。
- 依赖数据：见 `references/api_guide.md`。

## 是否需要生产结果

- 生成 `database.parquet`：是（结果型，盘后统一计算，多人复用）。
- 更新频率：每日收盘后 `maintain_daily()` 追加。
- 字段结构：见 `../生产产物/SKILL.md`。

## 依赖

- panda_data ≥ 0.0.9（`get_stock_daily`/`get_factor`/`get_margin`/`get_holder_count`/`get_stock_pledge`/`get_lhb_list`/`get_hsgt_hold`/`get_fina_forecast`/`get_fina_reports`/`get_fina_performance`/`get_repurchase`/`get_stock_private_placement`/`get_stock_shareholder_change`/`get_restricted_list`/`get_block_trade`/`get_stock_status_change`/`get_trade_cal`）
- pandas、numpy、pyarrow（生产 parquet；缺失自动降级 CSV）
- 凭证：`PANDA_USERNAME`/`PANDA_PASSWORD` 或 `~/.pandadata/pandadata.env`（**绝不硬编码**）
- 核心逻辑 `reflexivity.py` 纯逻辑零 IO，`test.py` 全离线可跑（无 panda_data 也全绿）

## 数据边界 / 免责

数据源 PandaData。假设：反身性阶段可由价格趋势 + 基本面事件 + 资金/行为证据识别；有效市场失真是前提。已知限制：北向个股数据 2024/08 后多停披露（FB_long 北向权重默认 0）；快报覆盖不全（F 链以预告+财报为主）；不预测破裂点。风险边界：**仅量化研究与教育示例，不构成投资建议，不承诺收益**；阶段与仓位建议为纪律参考，非交易指令。
