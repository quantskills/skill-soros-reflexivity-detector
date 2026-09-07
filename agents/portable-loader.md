# Portable Loader Prompt / 便携加载提示

This file is the portable entrypoint for Hermes, OpenClaw, and any agent runtime that does not
natively discover `SKILL.md` folders. Native runtimes (Claude Code, Codex, Cursor) should read
[SKILL.md](../SKILL.md) directly; the Cursor rule is [cursor-rule.mdc](cursor-rule.mdc) and the
Codex interface is [openai.yaml](openai.yaml).

本文件是 Hermes / OpenClaw 等不原生识别 `SKILL.md` 目录的运行时的便携入口。
把下面这段提示粘贴进运行时的系统提示或工具描述，并把占位路径替换成仓库根目录。

```text
You have access to a local skill named skill-soros-reflexivity-detector at:
<SKILL_SOROS_REFLEXIVITY_DETECTOR_ROOT>

Use it when the user wants to know whether an A-share move is a self-reinforcing reflexive regime, which of the eight stages it is in, where the fuel and cracks are, and what position discipline applies.

1. Read <SKILL_SOROS_REFLEXIVITY_DETECTOR_ROOT>/SKILL.md first; it is the canonical declaration.
2. Read <SKILL_SOROS_REFLEXIVITY_DETECTOR_ROOT>/开发产物/SKILL.md for the agent-facing interface (inputs, outputs, run()/validate_input()).
3. Read the references before touching data logic:
   - <SKILL_SOROS_REFLEXIVITY_DETECTOR_ROOT>/开发产物/references/api_guide.md
   - <SKILL_SOROS_REFLEXIVITY_DETECTOR_ROOT>/开发产物/references/quality_evidence.md
4. Run entrypoints from <SKILL_SOROS_REFLEXIVITY_DETECTOR_ROOT>:
   python 开发产物/scripts/build.py --mode watchlist --symbols 300750.SZ 688256.SH --date 20260710 --save
   python 开发产物/scripts/build.py --mode scan
   python 开发产物/scripts/test.py
5. Dual-loop model: score the fast loop (sentiment-flows) and the slow loop (fundamentals-capital) separately, then compose the stage; never present a single-loop reading as the overall verdict
6. Output is stage identification plus position discipline, not a top/bottom forecast and not a trade instruction; northbound per-stock data mostly stopped after 2024-08 and those components default to zero weight
7. Pair every academic term with a one-line plain-language gloss
8. Credentials come only from PANDA_USERNAME / PANDA_PASSWORD or ~/.pandadata/pandadata.env; never hard-code or print them.
9. This is a QuantSkills Community Project for research and education only: no investment advice, no return promises, no claim of official endorsement.
```
