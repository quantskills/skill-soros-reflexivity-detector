# skill-soros-reflexivity-detector（#48）

> 索罗斯反身性识别器 · BUILD 型 skill · Community Project
> **反身性 = 涨会让它更涨、跌会让它更跌的自我强化循环。** 本工具量化"价格自己制造行情"的强度与阶段。

## 它回答什么

交易上三个要命的问题：

1. 这波涨/跌是不是**自我强化**的（能不能顺势）？
2. 循环转到**哪一圈**了（决定仓位纪律）？
3. **燃料**（新钱）还在进吗、**油箱裂缝**（质押/解禁/大宗）在漏吗？

**明确不做**：不预测顶底、不判断"价值"、不假设市场有效。

## 双环模型

| 环 | 回路 | 周期 | 主战场 |
|---|---|---|---|
| 快环（情绪-资金） | 涨→上热榜→更多人买→再涨 | 天–周 | 题材股、游资股 |
| 慢环（基本面-资本） | 涨→增发/回购→基本面上修→再涨 | 季–年 | 趋势白马 |
| 双环共振 | 快慢同时闭合 | — | 最强反身性 |

八阶段：S0 中性 → S1 先知先觉 → S2 大众追涨（含考验）→ S3 狂热见暮色 → S4 破裂 → S5 越跌越卖。

## 快速开始

```bash
pip install --upgrade panda_data pyarrow
export PANDA_USERNAME=<手机号>; export PANDA_PASSWORD=<密码>   # 或 ~/.pandadata/pandadata.env

# 单票/多票诊断
python 开发产物/scripts/build.py --mode watchlist --symbols 300750.SZ 688256.SH --date 20260710 --save
# 全市场漏斗扫描
python 开发产物/scripts/build.py --mode scan --date 20260710 --top-n 300 --save
# 全离线自测（无 panda_data 也全绿）
python 开发产物/scripts/test.py
```

## 目录

```
开发产物/
  scripts/
    reflexivity.py   核心逻辑（纯逻辑零 IO：双环双函数状态机）
    datasource.py    PandaData → 标准面板 + 事件（PIT）
    build.py         run/validate_input/watchlist+scan/生产 parquet
    render.py        个股档案 markdown + HTML（学术读数+通俗解读）
    test.py          全离线合成夹具
  references/
    api_guide.md         数据接口 + D1 真机实测结论
    quality_evidence.md  参数整定 + 测试覆盖 + 缺陷修复记录
  SKILL.md / skill.json
生产产物/
  database.parquet              结果面板（随包样例：20260710 / 2 票 + MARKET 汇总）
  sample_reflexivity.html       诊断看板样本（宁德 S0 / 寒武纪 S1）
  sample_reflexivity.md         markdown 档案样本
  sample_688981_dashboard.html  单票看板样本（中芯国际，六维雷达 + 阶段时序）
  SKILL.md                      生产结果读取规则
```

## 数据与免责

数据源 PandaData（凭证走环境变量或 `~/.pandadata/pandadata.env`，**绝不硬编码**）。
北向个股数据 2024/08 后多停披露 → 相关成分默认零权重；快报覆盖不全 → 基本面链以预告+财报为主。

**Community Project，未经 QuantSkills 官方审核/认证/背书。仅量化研究与教育示例，不构成投资建议，不承诺收益，不预测顶底。** 反身性阶段与仓位建议为纪律参考、非交易指令。

License: GPL-3.0-only
