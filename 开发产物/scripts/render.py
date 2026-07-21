#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
skill-soros-reflexivity-detector · 渲染层
================================================================================
把 build.run() 的标准面板渲染成人看的档案：
  · render_markdown(panel)      —— 个股反身性档案（学术读数 + 通俗解读双行）
  · render_html(panel)          —— 暗色多票看板（列表 + 逐票展开详情）
所有学术术语都紧跟一行"通俗解读"（交付语言规范：学术必配人话）。
纯字符串处理，零 IO / 零联网，可离线测。
"""
from __future__ import annotations

import json
import math
from typing import Any

import pandas as pd

from reflexivity import GLOSSARY, STAGE_NAME

STOCK, SUMMARY = "reflexivity_stock", "reflexivity_summary"
STAGE_COLOR = {"S0": "#888", "S1": "#3b82f6", "S2": "#22c55e", "S3": "#f59e0b", "S4": "#ef4444", "S5": "#a855f7"}


def _clip(v, lo, hi):
    try:
        v = float(v)
    except (TypeError, ValueError):
        v = 0.0
    return max(lo, min(hi, v))


def _radar_svg(diag: dict, size: int = 210) -> str:
    """六维雷达图（P趋势/GAP/Sync/CogF/ParF/FastLoop，全归一 0-100）。纯 SVG。"""
    axes = [
        ("P趋势", (_clip(diag.get("p_trend", 0), -3, 3) + 3) / 6 * 100),
        ("GAP", (_clip(diag.get("gap_pct", 0), -100, 100) + 100) / 2),
        ("Sync", _clip(diag.get("sync", 50), 0, 100)),
        ("CogF", _clip(diag.get("cog_f", 50), 0, 100)),
        ("ParF", _clip(diag.get("par_f", 50), 0, 100)),
        ("FastLoop", _clip(diag.get("fast_loop", 50), 0, 100)),
    ]
    cx = cy = size / 2
    R = size / 2 - 30
    n = len(axes)
    grid = []
    for ring in (0.25, 0.5, 0.75, 1.0):
        p = " ".join(f"{cx + R * ring * math.cos(-math.pi / 2 + i * 2 * math.pi / n):.1f},"
                     f"{cy + R * ring * math.sin(-math.pi / 2 + i * 2 * math.pi / n):.1f}" for i in range(n))
        grid.append(f"<polygon points='{p}' fill='none' stroke='#2a2f3a' stroke-width='1'/>")
    labels, poly = [], []
    for i, (nm, val) in enumerate(axes):
        ang = -math.pi / 2 + i * 2 * math.pi / n
        ex, ey = cx + R * math.cos(ang), cy + R * math.sin(ang)
        grid.append(f"<line x1='{cx:.1f}' y1='{cy:.1f}' x2='{ex:.1f}' y2='{ey:.1f}' stroke='#2a2f3a'/>")
        lx, ly = cx + (R + 16) * math.cos(ang), cy + (R + 16) * math.sin(ang)
        anchor = "middle" if abs(math.cos(ang)) < 0.3 else ("start" if math.cos(ang) > 0 else "end")
        labels.append(f"<text x='{lx:.1f}' y='{ly + 3:.1f}' fill='#9aa' font-size='10.5' text-anchor='{anchor}'>{nm}</text>")
        rr = R * val / 100
        poly.append(f"{cx + rr * math.cos(ang):.1f},{cy + rr * math.sin(ang):.1f}")
    col = STAGE_COLOR.get(diag.get("stage"), "#4FC3BE")
    return (f"<svg viewBox='0 0 {size} {size}' width='{size}' height='{size}' xmlns='http://www.w3.org/2000/svg'>"
            f"{''.join(grid)}<polygon points='{' '.join(poly)}' fill='{col}' fill-opacity='0.28' stroke='{col}' stroke-width='2'/>"
            f"{''.join(labels)}</svg>")


def render_timeline_svg(df: pd.DataFrame, w: int = 720, h: int = 220) -> str:
    """阶段时间序列：score 折线 + 底部阶段色带 + conviction 台阶 + in_test 阴影。
    入参 df = reflexivity.compute_series() 输出（index=交易日，含 stage/score/conviction/in_test）。"""
    if df is None or len(df) == 0:
        return "<svg/>"
    d = df.dropna(subset=["score"]) if "score" in df else df
    n = len(d)
    ml, mr, mt, mb = 40, 14, 16, 40
    iw, ih = w - ml - mr, h - mt - mb

    def X(i):
        return ml + iw * (i / max(1, n - 1))

    def Y(s):
        return mt + ih * (1 - _clip(s, 0, 100) / 100)
    scores = list(d["score"])
    line = " ".join(f"{X(i):.1f},{Y(s):.1f}" for i, s in enumerate(scores))
    parts = [f"<line x1='{ml}' y1='{Y(50):.1f}' x2='{w - mr}' y2='{Y(50):.1f}' stroke='#232733' stroke-dasharray='3 3'/>"]
    # in_test 阴影
    if "in_test" in d:
        it = list(d["in_test"])
        i = 0
        while i < n:
            if it[i]:
                j = i
                while j < n and it[j]:
                    j += 1
                parts.append(f"<rect x='{X(i):.1f}' y='{mt}' width='{max(1, X(j - 1) - X(i)):.1f}' height='{ih}' fill='#f59e0b' opacity='0.08'/>")
                i = j
            else:
                i += 1
    # 阶段色带
    if "stage" in d:
        st = list(d["stage"])
        i = 0
        while i < n:
            j = i
            while j < n and st[j] == st[i]:
                j += 1
            parts.append(f"<rect x='{X(i):.1f}' y='{h - mb + 6}' width='{max(1, X(j - 1) - X(i) + iw / n):.1f}' height='10' fill='{STAGE_COLOR.get(st[i], '#888')}' opacity='0.85'/>")
            mid = (i + j - 1) / 2
            if j - i > n * 0.06:
                parts.append(f"<text x='{X(mid):.1f}' y='{h - mb + 30:.1f}' fill='#8b93a2' font-size='10' text-anchor='middle'>{st[i]}</text>")
            i = j
    parts.append(f"<polyline points='{line}' fill='none' stroke='#4FC3BE' stroke-width='1.8'/>")
    # conviction 标记（变化点）
    if "conviction" in d:
        cv = list(d["conviction"])
        for i in range(1, n):
            if cv[i] > cv[i - 1]:
                parts.append(f"<circle cx='{X(i):.1f}' cy='{Y(scores[i]):.1f}' r='3.2' fill='#22c55e'/>"
                             f"<text x='{X(i):.1f}' y='{Y(scores[i]) - 7:.1f}' fill='#22c55e' font-size='9' text-anchor='middle'>+{cv[i]}</text>")
    parts.append(f"<text x='{ml - 6}' y='{Y(100) + 4:.1f}' fill='#8b93a2' font-size='9' text-anchor='end'>100</text>"
                 f"<text x='{ml - 6}' y='{Y(0) + 4:.1f}' fill='#8b93a2' font-size='9' text-anchor='end'>0</text>"
                 f"<text x='{ml}' y='{mt - 4:.1f}' fill='#8b93a2' font-size='10'>反身性分 score（折线）· 阶段（底部色带）· ●=conviction+1 · 黄=考验中</text>")
    return f"<svg viewBox='0 0 {w} {h}' width='100%' xmlns='http://www.w3.org/2000/svg' font-family='-apple-system,sans-serif'>{''.join(parts)}</svg>"


def _reads(diag: dict) -> list[tuple[str, Any, str]]:
    """(指标, 值, 人话) 三列——人话按当前值动态给。"""
    def h_cog(v):
        return "市场对利好很兴奋（偏见在强化）" if v >= 60 else ("利好不涨、兴奋耗尽（暮色信号）" if v < 40 else "反应中性")
    def h_par(v):
        return "股价正在'改造'公司（增发圈钱/回购增厚）" if v >= 60 else "价格还没反过来改变基本面"
    def h_fbl(v):
        return "新钱仍在涌入（燃料足）" if v >= 60 else ("燃料一般" if v >= 40 else "新钱在撤（燃料枯）")
    def h_fbn(v):
        return "⚠️ 潜在抛压大（高质押/大解禁/折价出货）" if v >= 55 else ("有些脆弱" if v >= 30 else "脆弱度低")
    def h_fast(v):
        return "热度和钱在互相点火" if v >= 60 else "情绪-资金共振弱"
    def h_sync(v):
        return "价格与基本面同向共振（回路闭合）" if v >= 55 else ("背离" if v < 45 else "中性")
    def h_gap(v):
        return "价格已透支基本面（跑太前）" if v >= 40 else ("基本面反跑在价格前（价格滞后）" if v <= -40 else "价格与基本面大致同步")
    def h_p(v):
        return "涨得又陡又稳" if v >= 1 else ("温和走强" if v > 0 else ("走弱" if v > -1 else "又急又稳地跌"))
    return [
        ("P 趋势强度", diag.get("p_trend"), h_p(diag.get("p_trend", 0))),
        ("CogF 认知弹性", diag.get("cog_f"), h_cog(diag.get("cog_f", 50))),
        ("ParF 参与活跃", diag.get("par_f"), h_par(diag.get("par_f", 50))),
        ("FastLoop 快环", diag.get("fast_loop"), h_fast(diag.get("fast_loop", 50))),
        ("FB_long 燃料", diag.get("fb_long"), h_fbl(diag.get("fb_long", 50))),
        ("FB_neg 脆弱", diag.get("fb_neg"), h_fbn(diag.get("fb_neg", 0))),
        ("Sync 同步性", diag.get("sync"), h_sync(diag.get("sync", 50))),
        ("GAP 裂口", diag.get("gap_pct"), h_gap(diag.get("gap_pct", 0))),
        ("conviction 信念", diag.get("conviction"), f"扛过 {diag.get('conviction',0)} 次洗盘考验"),
    ]


def _diag_of(row: pd.Series) -> dict:
    try:
        return json.loads(row["result_json"])
    except Exception:  # noqa: BLE001
        return row.to_dict()


def render_markdown(panel: pd.DataFrame) -> str:
    stocks = panel[panel["result_type"] == STOCK]
    lines = ["# 索罗斯反身性诊断档案", ""]
    lines.append("> 反身性=涨会让它更涨、跌会让它更跌的自我强化循环。本工具只做阶段识别与仓位纪律，"
                 "**不预测顶底、非投资建议**。")
    lines.append("")
    for _, r in stocks.iterrows():
        d = _diag_of(r)
        loop_zh = {"fast": "快环(情绪-资金)", "slow": "慢环(基本面-资本)", "dual": "双环共振", "none": "无明显反身性"}.get(d.get("loop_type"), d.get("loop_type"))
        lines.append(f"## {r['ts_code']} · {d.get('trade_date','')}")
        lines.append(f"**{STAGE_NAME.get(d.get('stage'), d.get('stage'))}** ｜ 环型 {loop_zh} ｜ "
                     f"反身性分 {d.get('score')} ｜ 建议 **{d.get('position_advice')}**"
                     + ("｜ ⚠️脆弱" if d.get("fragile") else ""))
        lines.append("")
        lines.append("| 指标 | 值 | 通俗解读 |")
        lines.append("|---|---:|---|")
        for name, val, hint in _reads(d):
            lines.append(f"| {name} | {val} | {hint} |")
        lines.append("")
        lines.append("**研判（人话）**：" + d.get("plain_text", ""))
        lines.append("")
    # 术语表
    lines.append("---")
    lines.append("### 术语表（学术 → 人话）")
    for k, v in GLOSSARY.items():
        lines.append(f"- **{k}**：{v}")
    return "\n".join(lines)


def render_html(panel: pd.DataFrame) -> str:
    stocks = panel[panel["result_type"] == STOCK]
    cards = []
    for _, r in stocks.iterrows():
        d = _diag_of(r)
        col = STAGE_COLOR.get(d.get("stage"), "#888")
        rows = "".join(f"<tr><td>{n}</td><td style='text-align:right'>{v}</td><td class='hint'>{h}</td></tr>"
                       for n, v, h in _reads(d))
        frag = "<span class='frag'>⚠️脆弱</span>" if d.get("fragile") else ""
        cards.append(f"""
        <div class="card">
          <div class="hd" style="border-left:5px solid {col}">
            <b>{r['ts_code']}</b> · {d.get('trade_date','')}
            <span class="stage" style="background:{col}">{STAGE_NAME.get(d.get('stage'),d.get('stage'))}</span>
            <span class="loop">{d.get('loop_type')}</span> 分 {d.get('score')} · {d.get('position_advice')} {frag}
          </div>
          <div class="pt">{d.get('plain_text','')}</div>
          <div class="body">
            <table>{rows}</table>
            <div class="radar"><div class="rlab">六维读数雷达</div>{_radar_svg(d)}</div>
          </div>
        </div>""")
    gloss = "".join(f"<li><b>{k}</b>：{v}</li>" for k, v in GLOSSARY.items())
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>反身性诊断看板</title><style>
body{{background:#0f1115;color:#e6e6e6;font-family:-apple-system,'PingFang SC',sans-serif;margin:0;padding:18px}}
h1{{font-size:18px}} .sub{{color:#9aa;font-size:12px;margin-bottom:14px}}
.card{{background:#171a21;border-radius:10px;margin:12px 0;padding:12px 14px}}
.hd{{padding-left:10px;font-size:15px}} .stage{{color:#111;padding:1px 8px;border-radius:6px;font-size:12px;margin:0 6px}}
.loop{{color:#9aa;font-size:12px}} .frag{{color:#ef4444;font-weight:bold}}
.pt{{color:#c8d0dc;font-size:13px;margin:8px 0;line-height:1.6}}
.body{{display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap}}
.body table{{flex:1;min-width:280px}} .radar{{flex:0 0 auto;text-align:center}}
.rlab{{color:#8b93a2;font-size:11px;margin-bottom:2px}}
table{{width:100%;border-collapse:collapse;font-size:12.5px}} td{{padding:3px 6px;border-bottom:1px solid #232733}}
.hint{{color:#8b93a2}} ul{{color:#9aa;font-size:12px;line-height:1.7}}
</style></head><body>
<h1>索罗斯反身性诊断看板</h1>
<div class="sub">反身性=涨会让它更涨、跌会让它更跌的自我强化循环。仅阶段识别与仓位纪律，不预测顶底、非投资建议。</div>
{''.join(cards)}
<h3>术语表（学术 → 人话）</h3><ul>{gloss}</ul>
</body></html>"""
