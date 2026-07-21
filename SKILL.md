---
name: skill-soros-reflexivity-detector
description: 索罗斯反身性识别器——用双环模型（快环情绪-资金 / 慢环基本面-资本）判断 A 股"这波涨跌是不是自我强化的反身性、转到哪一圈、燃料和裂缝在哪"，做阶段识别与仓位纪律。BUILD 型 skill，可被复盘 agent 或 Alpha 调用。
tags: [quant, build, reflexivity, soros, regime]
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-soros-reflexivity-detector
  repository_url: https://github.com/quantskills/skill-soros-reflexivity-detector
  project_type: skill
  collection: master-strategies
  license: GPL-3.0-only
  status: community-project
---

# 索罗斯反身性识别器（#48）

> **项目状态：Community Project（社区项目）。** 本项目由社区成员创建，**未经 QuantSkills 官方审核、认证、验证或背书**，
> 也非生产可用认证项目。名称中的 `quantskills/` 仅表示托管组织，不代表任何官方身份。

> **一句话**：反身性 = 涨会让它更涨、跌会让它更跌的自我强化循环。本工具量化"价格自己制造行情"的**强度与阶段**，回答"能不能顺势 / 转到哪一圈 / 何时下车"——**不预测顶底，非投资建议**。

## 这个工具做什么

真实市场里有效市场假说基本失真、追涨杀跌是常态。本 skill 用**双环模型**识别自我强化行情：

- **快环（情绪-资金）**：涨→上热榜→更多人买→再涨（题材股，按天/周，可无基本面）
- **慢环（基本面-资本）**：涨→增发/回购改善报表→基本面上修→再涨（白马，按季）
- **双环共振** = 最强反身性

输出八阶段（S0 中性 → S1 先知先觉 → S2 大众追涨 → S3 狂热见暮色 → S4 破裂 → S5 越跌越卖）+ 建议仓位 + 脆弱预警 + 一段人话研判。

## 快速使用

```bash
export PANDA_USERNAME=<手机号>; export PANDA_PASSWORD=<密码>   # 或 ~/.pandadata/pandadata.env
python 开发产物/scripts/build.py --mode watchlist --symbols 300750.SZ 688256.SH --date 20260710 --save
python 开发产物/scripts/test.py                              # 全离线自测
```

- 详细文档：[开发产物/SKILL.md](开发产物/SKILL.md)
- 数据接口与 D1 实测：[开发产物/references/api_guide.md](开发产物/references/api_guide.md)
- 质量证据：[开发产物/references/quality_evidence.md](开发产物/references/quality_evidence.md)
- 生产结果读取：[生产产物/SKILL.md](生产产物/SKILL.md)

## 边界与免责

数据源 PandaData。**Community Project，未经 QuantSkills 官方审核/认证/背书。仅量化研究与教育示例，不构成投资建议，不承诺收益，不预测顶底。** 反身性阶段与仓位建议为纪律参考，非交易指令。数据源/假设/参数/限制/风险边界见开发产物 SKILL.md 与 references/。
