#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
skill-soros-reflexivity-detector · 核心逻辑层（纯逻辑，零 IO）
================================================================================
把索罗斯《金融炼金术》的反身性（reflexivity）落成可计算的"趋势成色探测器"。

一句话（通俗）：这波涨/跌是不是"自己喂养自己"的自我强化循环？转到哪一圈了？
燃料（新钱）还在进吗、油箱（质押/解禁/大宗）在漏吗？——不预测顶底，只做阶段识别与仓位纪律。

学术 → 通俗对照（术语表见 GLOSSARY，交付时 SKILL.md/报告同步给出通俗解读）：
  反身性 reflexivity        涨会让它更涨、跌会让它更跌的自我强化回路
  快环 fast loop            情绪-资金环：涨→上热榜→更多人买→再涨（题材股，按天/周）
  慢环 slow loop            基本面-资本环：涨→增发/回购改善报表→基本面上修→再涨（白马，按季）
  CogF 认知函数弹性         市场对利好的兴奋度；"利好不涨"=兴奋度耗尽（暮色期第一信号）
  ParF 参与函数活跃度       股价是否在"创造"基本面（高位增发圈钱、回购做厚 EPS）
  FastLoop 快环强度         热度和钱是否在互相点火
  FB_long / FB_neg          燃料表（还有多少新钱）/ 油箱裂缝（高质押、大解禁、大宗折价出货）
  GAP 裂口                  股价跑在基本面前面多远（透支了多少）
  conviction 信念计数       这波趋势扛过几次洗盘；越扛越信、越信越危险
  阶段 S1..S5               先知先觉→大众追涨→洗盘考验→最后的傻瓜/利好不涨→破裂→越跌越卖

本模块**不**拉数、不读盘、不 import panda_data。它吃 datasource.py 整理好的"标准面板"
（一只股票的对齐时间序列 DataFrame + 事件列表），输出反身性诊断。可被合成夹具离线单测。

数据边界 / 免责：仅量化研究与教育示例，不构成投资建议，不承诺收益。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

# ============================================================================
# 术语表（交付时 SKILL.md 与报告须给通俗解读；plain_text 生成也参考它）
# ============================================================================
GLOSSARY: dict[str, str] = {
    "反身性": "涨会让它更涨、跌会让它更跌——价格自己制造行情的自我强化循环",
    "快环": "情绪-资金环：涨→上热榜→更多人买→再涨（题材股，周期以天/周计）",
    "慢环": "基本面-资本环：涨→增发/回购改善报表→基本面上修→再涨（白马，周期以季计）",
    "CogF": "市场对利好的兴奋度；'利好不涨'=兴奋度耗尽，行情进入尾声",
    "ParF": "股价是否在'创造'基本面：高位增发圈到钱、回购做厚每股收益",
    "FastLoop": "热度和钱是否在互相点火：涨→上榜→更多人买→再涨",
    "GAP": "股价跑在基本面前面多远（透支了多少）",
    "conviction": "这波趋势扛过几次回调洗盘；越扛越信，越信越危险",
    "FB_long": "燃料表：还有多少新钱在进场（融资/游资/换手/回购增持）",
    "FB_neg": "油箱裂缝：高质押、大额解禁、大宗折价出货等随时引爆的脆弱度",
    "P趋势强度": "价格趋势的陡峭+稳定程度（斜率÷波动，类似 t 值）",
    "Sync": "价格和基本面是否同向共振（反身性回路是否闭合）",
    "阶段S0-S5": "S0中性/S1先知先觉/S2大众追涨/S3狂热见暮色/S4破裂/S5越跌越卖",
    "PIT": "只用当时已公告的信息下判断，不偷看后来才发布的数据",
}

# ============================================================================
# 参数（集中管理，核心阈值 ≤ 8 个 + 环型参数组；整定过程见 quality_evidence.md）
# ============================================================================
DEFAULT_CONFIG: dict[str, Any] = {
    # —— 核心阈值 ——
    "p_s1": 0.5,           # 萌芽：趋势强度门槛（弱趋势）
    "p_s2": 1.0,           # 加速：趋势强度门槛（明确趋势）
    "fb_s2": 60.0,         # 加速：正反馈燃料分位门槛
    "hot_pctl": 90.0,      # 狂热：趋势/拥挤分位门槛
    "gap_hot": 90.0,       # 狂热：价格-基本面裂口分位门槛
    "fragile_pledge": 55.0,  # 脆弱：累计质押率警戒线(%)
    "break_dd": 0.15,      # 破裂：距阶段高点回撤门槛
    "neg_p": -1.0,         # 负反身性：下跌趋势强度门槛
    # —— 事件新鲜度（基本面事件多少交易日后衰减到 0）——
    "event_decay_days": 60,
    # —— 环型参数组（同一状态机，按 loop_type 切换窗口）——
    "loops": {
        "slow": {"trend_win": 60, "pct_win": 250, "confirm": 5},
        "fast": {"trend_win": 20, "pct_win": 60, "confirm": 2},
        "dual": {"trend_win": 60, "pct_win": 250, "confirm": 5},
        "none": {"trend_win": 60, "pct_win": 250, "confirm": 5},
    },
    # —— FB_long 成分权重（北向因政策 2024/08 后个股停披露，默认 0）——
    "fb_long_weights": {
        "margin": 0.30, "lhb": 0.20, "turnover": 0.20,
        "holder_concentrate": 0.15, "corp_action": 0.15, "north": 0.0,
    },
    # —— FB_neg 成分权重 ——
    "fb_neg_weights": {
        "pledge": 0.35, "unlock": 0.20, "block_discount": 0.20,
        "insider_reduce": 0.15, "regulatory": 0.10,
    },
    "fast_loop_on_threshold": 60.0,   # FastLoop 判定 fast 环型的门槛
    "min_history": 80,                 # 少于该交易日数不出阶段判定
}

STAGES = ("S0", "S1", "S2", "S3", "S4", "S5")
STAGE_NAME = {
    "S0": "中性/未识别", "S1": "萌芽(先知先觉)", "S2": "加速(大众追涨)",
    "S3": "狂热→暮色", "S4": "破裂", "S5": "负反身性(越跌越卖)",
}
ADVICE = {
    "S0": "observe", "S1": "observe", "S2": "add", "S3": "reduce",
    "S4": "exit", "S5": "avoid",
}


# ============================================================================
# 数值工具（全部对 NaN / 短序列 robust）
# ============================================================================
def _safe(x: float, default: float = 0.0) -> float:
    try:
        return default if x is None or not np.isfinite(x) else float(x)
    except (TypeError, ValueError):
        return default


def _roll_slope(y: pd.Series, win: int) -> pd.Series:
    """滚动 OLS 斜率（对时间 x=0..win-1）。x 固定 → 向量化。"""
    n = win
    if n < 3:
        return pd.Series(np.nan, index=y.index)
    x = np.arange(n, dtype=float)
    xm = x.mean()
    denom = ((x - xm) ** 2).sum()
    xc = x - xm
    def _f(w: np.ndarray) -> float:
        if np.isnan(w).any():
            return np.nan
        return float((xc * (w - w.mean())).sum() / denom)
    return y.rolling(n).apply(_f, raw=True)


def _roll_pct_rank(s: pd.Series, win: int) -> pd.Series:
    """当前值在过去 win 窗口内的分位（0..100，midrank）。
    用 midrank 使常数窗口→50（中性），避免恒定序列被算成 100 分位而误触发阈值。"""
    def _f(w: np.ndarray) -> float:
        if np.isnan(w).any() or len(w) < 3:
            return np.nan
        last = w[-1]
        return float(((w < last).sum() + 0.5 * (w == last).sum()) / len(w) * 100.0)
    return s.rolling(win, min_periods=max(3, win // 3)).apply(_f, raw=True)


def _pct_of_last(s: pd.Series, win: int) -> float:
    """序列最后一个值在其过去 win 窗口的分位（标量，midrank）。"""
    tail = s.dropna().tail(win).values
    if len(tail) < 3:
        return 50.0
    last = tail[-1]
    return float(((tail < last).sum() + 0.5 * (tail == last).sum()) / len(tail) * 100.0)


def _zclip(x: pd.Series, lo: float = -4, hi: float = 4) -> pd.Series:
    sd = x.std(ddof=0)
    if not sd or np.isnan(sd):
        return pd.Series(0.0, index=x.index)
    return ((x - x.mean()) / sd).clip(lo, hi)


# ============================================================================
# 三条序列：P（价格趋势）/ F（基本面预期）/ FB（反馈证据）
# ============================================================================
def price_trend(panel: pd.DataFrame, win: int) -> pd.Series:
    """P：趋势强度 = 对数价 win 日 OLS 斜率 ÷ win 日日收益波动（≈趋势 t 值）。
    通俗：价格涨得又陡又稳 → P 高；震荡 → P 近 0；下跌 → P 负。"""
    close = panel["close_adj"].astype(float)
    logp = np.log(close.where(close > 0))
    slope = _roll_slope(logp, win)
    vol = logp.diff().rolling(win).std(ddof=0)
    p = slope / vol.replace(0, np.nan) * np.sqrt(win)
    return p.rename("P")


def fundamental_series(panel: pd.DataFrame, events: list[dict], cfg: dict) -> pd.DataFrame:
    """F：基本面预期水平（阶梯函数）+ 修正斜率 F_slope + 事件后新鲜度。
    用业绩预告/快报/财报事件（value=净利同比%）按公告日拼阶梯，事件间保持水平，
    event_decay_days 内线性衰减新鲜度（防陈旧预告长期支撑高分）。
    通俗：把'公司利润预期'画成台阶——每次新公告抬高/压低台阶，斜率=这次修了多少。"""
    idx = panel.index
    f_level = pd.Series(np.nan, index=idx, dtype=float)
    f_slope = pd.Series(0.0, index=idx, dtype=float)
    freshness = pd.Series(0.0, index=idx, dtype=float)
    fund = [e for e in events if e.get("kind") in ("forecast", "express", "report")]
    fund = sorted(fund, key=lambda e: pd.Timestamp(e["date"]))
    decay = max(1, int(cfg["event_decay_days"]))
    prev_val = None
    for e in fund:
        d = pd.Timestamp(e["date"])
        pos = idx.searchsorted(d)
        if pos >= len(idx):
            continue
        val = _safe(e.get("value"), 0.0)
        f_level.iloc[pos:] = val
        slope = val - prev_val if prev_val is not None else val
        # 新鲜度：事件日=1，decay 日后=0
        for k in range(pos, min(pos + decay, len(idx))):
            fresh = 1.0 - (k - pos) / decay
            if fresh > freshness.iloc[k]:
                freshness.iloc[k] = fresh
                f_slope.iloc[k] = slope
        prev_val = val
    f_level = f_level.ffill().fillna(0.0)
    return pd.DataFrame({"F_level": f_level, "F_slope": f_slope, "F_fresh": freshness})


def _component_pctl(s: Optional[pd.Series], win: int, invert: bool = False) -> pd.Series:
    """把一个原始序列转成 0..100 分位成分；缺失→中性 50。invert：越低越强。"""
    if s is None:
        return None
    r = _roll_pct_rank(s.astype(float), win)
    if invert:
        r = 100.0 - r
    return r


def fb_long_series(panel: pd.DataFrame, events: list[dict], win: int, cfg: dict) -> pd.Series:
    """正反馈燃料分（0..100）：融资动量 + 龙虎榜热度 + 换手拥挤 + 户数集中 + 公司行为脉冲(+北向)。
    通俗：还有多少'新钱/新关注'在往里冲。"""
    idx = panel.index
    w = cfg["fb_long_weights"]
    comps: dict[str, pd.Series] = {}
    # 融资余额 20d 变化率的分位
    if "margin_balance" in panel:
        chg = panel["margin_balance"].astype(float).pct_change(20)
        comps["margin"] = _component_pctl(chg, win)
    # 龙虎榜 20d 上榜次数
    if "lhb" in panel:
        comps["lhb"] = _component_pctl(panel["lhb"].astype(float).rolling(20).sum(), win)
    # 换手拥挤
    if "turnover" in panel:
        comps["turnover"] = _component_pctl(panel["turnover"].astype(float), win)
    # 户数集中（环比下降=集中=强 → invert）
    if "holder_count" in panel:
        comps["holder_concentrate"] = _component_pctl(
            panel["holder_count"].astype(float).pct_change(), win, invert=True)
    # 北向（政策后多为空；有则用）
    if "north_ratio" in panel and panel["north_ratio"].notna().any():
        comps["north"] = _component_pctl(panel["north_ratio"].astype(float).diff(20), win)
    # 公司行为脉冲（回购进行/增持/定增实施 → 事件日起 40d 衰减脉冲）
    comps["corp_action"] = _event_pulse(
        idx, events, kinds=("repurchase", "holder_add", "placement"), horizon=40)

    total_w, acc = 0.0, pd.Series(0.0, index=idx)
    for k, series in comps.items():
        if series is None:
            continue
        wk = w.get(k, 0.0)
        if wk <= 0:
            continue
        acc = acc.add(series.fillna(50.0) * wk, fill_value=0.0)
        total_w += wk
    return (acc / total_w).clip(0, 100).rename("FB_long") if total_w else pd.Series(50.0, index=idx, name="FB_long")


def fb_neg_series(panel: pd.DataFrame, events: list[dict], win: int, cfg: dict) -> pd.Series:
    """负反馈脆弱度分（0..100）：质押螺旋 + 解禁供给 + 大宗折价 + 高管减持 + 监管事件。
    通俗：油箱有多少裂缝——越高越容易在下跌里被强平/踩踏放大。"""
    idx = panel.index
    w = cfg["fb_neg_weights"]
    comps: dict[str, pd.Series] = {}
    # 质押：累计质押率水平（绝对水平映射，不用分位——80% 就是危险）
    if "acc_pledge_ratio" in panel:
        comps["pledge"] = (panel["acc_pledge_ratio"].astype(float).ffill()
                           .clip(0, 100)).fillna(0.0)
    # 解禁：未来 90d 解禁股/流通盘 的脉冲（在解禁前生效）
    comps["unlock"] = _event_pulse(idx, events, kinds=("unlock",), horizon=90, pre=True)
    # 大宗折价、监管、减持：事件脉冲
    comps["block_discount"] = _event_pulse(idx, events, kinds=("block_discount",), horizon=20)
    comps["insider_reduce"] = _event_pulse(idx, events, kinds=("holder_reduce",), horizon=40)
    comps["regulatory"] = _event_pulse(idx, events, kinds=("st",), horizon=60)
    total_w, acc = 0.0, pd.Series(0.0, index=idx)
    for k, series in comps.items():
        wk = w.get(k, 0.0)
        if series is None or wk <= 0:
            continue
        acc = acc.add(series.fillna(0.0) * wk, fill_value=0.0)
        total_w += wk
    return (acc / total_w).clip(0, 100).rename("FB_neg") if total_w else pd.Series(0.0, index=idx, name="FB_neg")


def _event_pulse(idx: pd.DatetimeIndex, events: list[dict], kinds: tuple,
                 horizon: int, pre: bool = False, scale: float = 100.0) -> pd.Series:
    """事件脉冲：事件日(或事件前 horizon 日起)置高分，horizon 内线性衰减。
    pre=True 用于'解禁前承压'这类前瞻事件。value 若给则乘以强度。"""
    out = pd.Series(0.0, index=idx)
    for e in events:
        if e.get("kind") not in kinds:
            continue
        d = pd.Timestamp(e["date"])
        pos = idx.searchsorted(d)
        strength = min(1.0, abs(_safe(e.get("value"), 1.0))) if e.get("value") is not None else 1.0
        if pre:
            lo = max(0, pos - horizon)
            for k in range(lo, min(pos + 1, len(idx))):
                frac = 1.0 - (pos - k) / horizon
                out.iloc[k] = max(out.iloc[k], frac * scale * strength)
        else:
            if pos >= len(idx):
                continue
            for k in range(pos, min(pos + horizon, len(idx))):
                frac = 1.0 - (k - pos) / horizon
                out.iloc[k] = max(out.iloc[k], frac * scale * strength)
    return out


# ============================================================================
# 双函数（CogF 认知 / ParF 参与）+ 关系量（Sync / GAP / FastLoop）
# ============================================================================
def cog_f_series(panel: pd.DataFrame, events: list[dict], win: int = 120) -> pd.Series:
    """认知函数弹性 CogF（0..100）：基本面事件公告后 2 日超额收益 对 surprise 的响应强度。
    通俗：市场对利好还兴不兴奋。正 surprise 却不涨 → CogF 掉 → 暮色。"""
    idx = panel.index
    close = panel["close_adj"].astype(float)
    ret2 = close.shift(-2) / close - 1.0  # 事件后 2 日收益（评估用，非信号）
    base = close.pct_change().rolling(20).mean()  # 个股自身漂移做基准
    fund = sorted([e for e in events if e.get("kind") in ("forecast", "express", "report")],
                  key=lambda e: pd.Timestamp(e["date"]))
    pts, prev = [], None
    for e in fund:
        d = pd.Timestamp(e["date"])
        pos = idx.searchsorted(d)
        if pos >= len(idx) - 2:
            continue
        surprise = (_safe(e.get("value")) - prev) if prev is not None else _safe(e.get("value"))
        prev = _safe(e.get("value"))
        excess = _safe(ret2.iloc[pos]) - _safe(base.iloc[pos]) * 2
        # 弹性：surprise 与超额同号且量级 → 高兴奋
        elast = np.sign(surprise) * excess
        pts.append((idx[pos], elast))
    out = pd.Series(np.nan, index=idx, dtype=float)
    if not pts:
        return out.fillna(50.0).rename("CogF")
    # 最近 K 个事件弹性的滚动均值 → 映射 0..100（正=兴奋）
    ev = pd.Series({t: v for t, v in pts}).sort_index()
    ev_roll = ev.rolling(3, min_periods=1).mean()
    for t, v in ev_roll.items():
        pos = idx.searchsorted(pd.Timestamp(t))
        score = 50.0 + np.tanh(v * 8) * 50.0  # 弹性→分数
        out.iloc[pos:] = score
    return out.ffill().fillna(50.0).clip(0, 100).rename("CogF")


def par_f_series(panel: pd.DataFrame, events: list[dict], p_series: pd.Series,
                 f_df: pd.DataFrame, win: int = 60) -> pd.Series:
    """参与函数活跃度 ParF（0..100）：价格是否领先基本面 + 资本行为脉冲。
    通俗：股价是不是真的在'改造'公司（高位圈钱、回购做厚 EPS）。"""
    idx = panel.index
    # 价格领先基本面：P 的 20d 变化领先 F_slope（正=价格先动）
    p_lead = p_series.diff(20).fillna(0.0)
    f_move = f_df["F_slope"].fillna(0.0)
    lead_corr = p_lead.rolling(win).corr(f_move.shift(-10)).fillna(0.0)  # P 领先 F 10 日
    lead_score = (lead_corr.clip(-1, 1) + 1) * 50.0
    # 资本行为脉冲（定增实施/回购）
    cap_pulse = _event_pulse(idx, events, kinds=("placement", "repurchase"), horizon=60)
    par = 0.6 * lead_score + 0.4 * cap_pulse
    return par.clip(0, 100).rename("ParF")


def sync_series(p_series: pd.Series, f_df: pd.DataFrame, win: int = 120) -> pd.Series:
    """Sync：价格趋势与基本面修正的同向性（滚动秩相关，0..100，>50 同向）。"""
    p_chg = p_series.diff(5)
    f_chg = f_df["F_level"].diff(20)
    corr = p_chg.rolling(win).corr(f_chg).fillna(0.0)
    return ((corr.clip(-1, 1) + 1) * 50.0).rename("Sync")


def gap_series(panel: pd.DataFrame, f_df: pd.DataFrame, win: int) -> pd.Series:
    """GAP：价格累计涨幅分位 − 基本面上修幅度分位（>0 = 价格透支基本面）。"""
    close = panel["close_adj"].astype(float)
    ret_cum = close / close.shift(win) - 1.0
    price_pctl = _roll_pct_rank(ret_cum, win)
    fund_pctl = _roll_pct_rank(f_df["F_level"], win)
    return (price_pctl - fund_pctl).rename("GAP")


def attention_score(panel: pd.DataFrame, win: int) -> pd.Series:
    """关注度分（0..100）：涨停次数 + 龙虎榜 + 换手分位 + 振幅分位（快环用）。"""
    idx = panel.index
    parts = []
    if "is_limit_up" in panel:
        parts.append(_roll_pct_rank(panel["is_limit_up"].astype(float).rolling(20).sum(), win))
    if "lhb" in panel:
        parts.append(_roll_pct_rank(panel["lhb"].astype(float).rolling(20).sum(), win))
    if "turnover" in panel:
        parts.append(_roll_pct_rank(panel["turnover"].astype(float), win))
    if "amplitude" in panel:
        parts.append(_roll_pct_rank(panel["amplitude"].astype(float), win))
    if not parts:
        return pd.Series(50.0, index=idx, name="Attn")
    return pd.concat(parts, axis=1).mean(axis=1).fillna(50.0).rename("Attn")


def money_score(panel: pd.DataFrame, win: int) -> pd.Series:
    """资金分（0..100）：融资余额动量 + 户数集中（快环用）。"""
    idx = panel.index
    parts = []
    if "margin_balance" in panel:
        parts.append(_roll_pct_rank(panel["margin_balance"].astype(float).pct_change(20), win))
    if "holder_count" in panel:
        parts.append(100.0 - _roll_pct_rank(panel["holder_count"].astype(float).pct_change(), win))
    if not parts:
        return pd.Series(50.0, index=idx, name="Money")
    return pd.concat(parts, axis=1).mean(axis=1).fillna(50.0).rename("Money")


def fast_loop_series(p_series: pd.Series, attn: pd.Series, money: pd.Series) -> pd.Series:
    """FastLoop（0..100）：价格动量 × 关注度 × 资金 三者共振度（几何均 → 三者都高才高）。
    通俗：热度和钱在互相点火的程度。"""
    p_norm = (p_series.clip(-3, 3) + 3) / 6 * 100.0
    stack = pd.concat([p_norm.rename("p"), attn.rename("a"), money.rename("m")], axis=1).fillna(50.0)
    geo = (stack["p"].clip(1, 100) * stack["a"].clip(1, 100) * stack["m"].clip(1, 100)) ** (1 / 3)
    return geo.clip(0, 100).rename("FastLoop")


# ============================================================================
# 环型判定 + 逐日读数装配
# ============================================================================
def compute_series(panel: pd.DataFrame, events: Optional[list[dict]] = None,
                   config: Optional[dict] = None) -> pd.DataFrame:
    """把标准面板 + 事件 → 全序列反身性读数 DataFrame（供 render / 回溯 / 状态机）。"""
    cfg = _merge_cfg(config)
    events = events or []
    panel = panel.sort_index()
    # 先用慢环窗口算一组"环型判定用"读数
    loop_type = classify_loop_type(panel, events, cfg)
    lp = cfg["loops"][loop_type]
    tw, pw = lp["trend_win"], lp["pct_win"]

    P = price_trend(panel, tw)
    P_acc = P.diff(20).rename("P_acc")
    Fdf = fundamental_series(panel, events, cfg)
    FBL = fb_long_series(panel, events, pw, cfg)
    FBN = fb_neg_series(panel, events, pw, cfg)
    CogF = cog_f_series(panel, events)
    ParF = par_f_series(panel, events, P, Fdf)
    Sync = sync_series(P, Fdf)
    GAP = gap_series(panel, Fdf, tw)
    Attn = attention_score(panel, pw)
    Money = money_score(panel, pw)
    FastLoop = fast_loop_series(P, Attn, Money)
    P_pctl = _roll_pct_rank(P, pw).rename("P_pctl")
    GAP_pctl = _roll_pct_rank(GAP, pw).rename("GAP_pctl")

    df = pd.concat([panel.get("close_adj"), P, P_acc, Fdf, FBL, FBN, CogF, ParF,
                    Sync, GAP, GAP_pctl, P_pctl, Attn, Money, FastLoop], axis=1)
    df["loop_type"] = loop_type
    # 逐日原始阶段 + 状态机确认
    df["raw_stage"] = df.apply(lambda r: _raw_stage(r, cfg), axis=1)
    stage, conviction, in_test, fragile = _run_state_machine(df, panel, cfg, lp["confirm"])
    df["stage"] = stage
    df["conviction"] = conviction
    df["in_test"] = in_test
    df["fragile"] = fragile
    df["score"] = df.apply(lambda r: _score(r), axis=1)
    return df


def classify_loop_type(panel: pd.DataFrame, events: list[dict], cfg: dict) -> str:
    """判环型：fast(纯情绪资金) / slow(基本面参与) / dual(共振) / none。
    通俗：先认出这是'题材股快环'还是'白马慢环'，再用对应的尺子量。"""
    # 快环强度（用快环窗口）
    fw = cfg["loops"]["fast"]
    P_fast = price_trend(panel, fw["trend_win"])
    attn = attention_score(panel, fw["pct_win"])
    money = money_score(panel, fw["pct_win"])
    fl = fast_loop_series(P_fast, attn, money)
    fast_on = _safe(fl.dropna().iloc[-1] if fl.notna().any() else 0) >= cfg["fast_loop_on_threshold"]
    # 慢环：近 250 日有基本面事件且 P>0
    recent = panel.index[-1] - pd.Timedelta(days=400)
    has_fund = any(e.get("kind") in ("forecast", "express", "report")
                   and pd.Timestamp(e["date"]) >= recent for e in events)
    P_slow = price_trend(panel, cfg["loops"]["slow"]["trend_win"])
    slow_on = has_fund and _safe(P_slow.dropna().iloc[-1] if P_slow.notna().any() else 0) > cfg["p_s1"]
    if fast_on and slow_on:
        return "dual"
    if fast_on:
        return "fast"
    if slow_on:
        return "slow"
    return "none"


def _raw_stage(r: pd.Series, cfg: dict) -> str:
    """单日原始阶段判定（未经状态机确认）。按方向与强度匹配。"""
    P = _safe(r.get("P"))
    P_acc = _safe(r.get("P_acc"))
    Fs = _safe(r.get("F_slope"))
    FBL = _safe(r.get("FB_long"), 50)
    P_pctl = _safe(r.get("P_pctl"), 50)
    GAP_pctl = _safe(r.get("GAP_pctl"), 50)
    turn_hot = _safe(r.get("Attn"), 50) >= cfg["hot_pctl"]
    # 负反身性侧
    if P <= cfg["neg_p"] and Fs <= 0:
        return "S5"
    # 狂热：高分位 + (基本面停修 或 裂口过大) + 拥挤/情绪极端
    if P_pctl >= cfg["hot_pctl"] and (Fs <= 0 or GAP_pctl >= cfg["gap_hot"]) and turn_hot:
        return "S3"
    # 加速：明确趋势 + 加速 + 基本面上修 + 燃料足
    if P >= cfg["p_s2"] and P_acc > 0 and Fs >= 0 and FBL >= cfg["fb_s2"]:
        return "S2"
    # 萌芽：弱趋势 + 上修 + 同向
    if P >= cfg["p_s1"] and Fs >= 0 and _safe(r.get("Sync"), 50) >= 50:
        return "S1"
    return "S0"


def _run_state_machine(df: pd.DataFrame, panel: pd.DataFrame, cfg: dict, confirm: int):
    """状态机：raw_stage 连续 confirm 日一致才切换；S2 内检测考验(回调洗盘)→conviction。
    通俗：不被一两天的波动骗到，连着好几天成立才认；每扛过一次洗盘信念+1。"""
    idx = df.index
    n = len(df)
    stage = pd.Series("S0", index=idx)
    conviction = pd.Series(0, index=idx, dtype=int)
    in_test = pd.Series(False, index=idx)
    fragile = pd.Series(False, index=idx)
    close = panel["close_adj"].astype(float).values
    pledge_col = (panel["acc_pledge_ratio"].astype(float).fillna(0).values
                  if "acc_pledge_ratio" in panel else np.zeros(n))

    cur, conv = "S0", 0
    test_active, test_ref_high = False, np.nan
    raw = df["raw_stage"].values
    fbn = df["FB_neg"].fillna(0.0).values
    Pv = df["P"].fillna(0.0).values
    Fs = df["F_slope"].fillna(0.0).values
    for i in range(n):
        # 连续确认切换
        if i >= confirm - 1:
            window = raw[i - confirm + 1:i + 1]
            if len(set(window)) == 1 and window[0] != cur:
                nxt = window[0]
                # 从 S2/S3 掉出且非破裂/负侧时，若仍上涨→视作考验而非切换
                cur = nxt
        # 考验：触发须在 S2；但"回调→创新高"的跟踪独立于 cur——回调必然让 cur 暂时切出
        # S2，若把跟踪锁在 S2 内，创新高（考验通过）发生时考验已被清掉，永远 +不了 conviction。
        # 触发：强趋势(P≥p_s2)中的回调即可——洗盘考验常在加速末段(P_acc 已转负、raw 掉出 S2)发生
        if cur in ("S1", "S2") and Pv[i] >= cfg["p_s2"] and not test_active:
            hi = np.nanmax(close[max(0, i - 20):i + 1])
            dd = 1.0 - close[i] / hi if hi > 0 else 0.0
            if 0.05 <= dd <= 0.12 and Fs[i] >= 0:
                test_active, test_ref_high = True, hi
        elif test_active:
            if Pv[i] <= -0.5 or close[i] < test_ref_high * 0.85:
                test_active = False       # 跌破趋势 / 深跌 → 考验失败
            elif close[i] >= test_ref_high:
                conv += 1                  # 创新高 → 考验通过，信念 +1
                test_active = False
        stage.iloc[i] = cur
        conviction.iloc[i] = conv
        in_test.iloc[i] = test_active
        # 质押螺旋是水平型硬风险，单独触发 fragile（不被无事件的其他负成分稀释）
        fragile.iloc[i] = bool(fbn[i] >= 60 or pledge_col[i] >= cfg["fragile_pledge"])
        if cur in ("S0", "S4", "S5"):
            conv = 0  # 复位/破裂后信念清零
    return stage, conviction, in_test, fragile


def _score_breakdown(r: pd.Series) -> dict:
    """score 四分量贡献值（agent/用户不用读源码就知道分是怎么来的）。"""
    sync = _safe(r.get("Sync"), 50) / 100.0
    fbl = _safe(r.get("FB_long"), 50) / 100.0
    p_persist = min(1.0, max(0.0, _safe(r.get("P")) / 3.0))
    dual = (_safe(r.get("CogF"), 50) / 100.0 * _safe(r.get("ParF"), 50) / 100.0) ** 0.5
    return {"sync": round(25 * sync, 1), "fb_long": round(25 * fbl, 1),
            "trend": round(20 * p_persist, 1), "dual": round(30 * dual, 1)}


def _score(r: pd.Series) -> float:
    """reflexivity_score(0..100) = 25·Sync + 25·FB_long + 20·趋势持续 + 30·双函数活跃度。"""
    b = _score_breakdown(r)
    return round(b["sync"] + b["fb_long"] + b["trend"] + b["dual"], 1)


def _band(v: float, lo: float, hi: float, labels=("低", "中", "高")) -> str:
    return labels[0] if v < lo else (labels[2] if v > hi else labels[1])


# ============================================================================
# 主入口：analyze —— 取某一日（默认最后一日）的诊断 dict
# ============================================================================
def analyze(panel: pd.DataFrame, events: Optional[list[dict]] = None,
            config: Optional[dict] = None, as_of: Optional[str] = None) -> dict:
    """一只股票的反身性诊断（默认最后一交易日）。返回可直接落面板/渲染的 dict。"""
    cfg = _merge_cfg(config)
    if panel is None or len(panel) == 0:
        raise ValueError("panel 为空，无法分析")
    # PIT：先按 as_of 截断 panel/events 再计算——绝不让未来数据参与
    # （否则 cog_f/par_f 的前视计算、classify_loop_type 用末日 都会泄漏未来）
    if as_of is not None:
        d = pd.Timestamp(as_of)
        panel = panel[panel.index <= d]
        events = [e for e in (events or []) if pd.Timestamp(str(e["date"])) <= d]
        if len(panel) == 0:
            raise ValueError(f"as_of={as_of} 之前无数据")
    df = compute_series(panel, events, cfg)
    row = df.iloc[-1]
    enough = len(panel) >= cfg["min_history"]
    stage = row["stage"] if enough else "S0"
    diag = {
        "trade_date": df.index[-1].strftime("%Y%m%d"),
        "loop_type": row["loop_type"],
        "stage": stage,
        "stage_name": STAGE_NAME.get(stage, stage),
        "score": _safe(row["score"]),
        "position_advice": ADVICE.get(stage, "observe"),
        "conviction": int(_safe(row["conviction"])),
        "in_test": bool(row["in_test"]),
        "fragile": bool(row["fragile"]),
        "confidence": _confidence(row, cfg, enough),
        # 读数
        "p_trend": round(_safe(row["P"]), 3),
        "p_pctl": round(_safe(row.get("P_pctl"), 50), 1),
        "f_slope": round(_safe(row["F_slope"]), 3),
        "fb_long": round(_safe(row["FB_long"], 50), 1),
        "fb_neg": round(_safe(row["FB_neg"], 0), 1),
        "cog_f": round(_safe(row["CogF"], 50), 1),
        "par_f": round(_safe(row["ParF"], 50), 1),
        "fast_loop": round(_safe(row["FastLoop"], 50), 1),
        "sync": round(_safe(row["Sync"], 50), 1),
        "gap_pct": round(_safe(row["GAP"], 0), 1),
        "score_breakdown": _score_breakdown(row),
    }
    diag["confidence_band"] = _band(diag["confidence"], 0.3, 0.6)
    if not enough:
        diag["note"] = f"历史不足 {cfg['min_history']} 日，阶段判定保守置 S0"
    diag["plain_text"] = _plain_text(diag)
    return diag


def _confidence(row: pd.Series, cfg: dict, enough: bool) -> float:
    """置信度：各触发条件的裕度综合（粗略 0..1）。"""
    if not enough:
        return 0.2
    marg = []
    marg.append(min(1.0, abs(_safe(row.get("P"))) / 2.0))
    marg.append(abs(_safe(row.get("Sync"), 50) - 50) / 50.0)
    marg.append(abs(_safe(row.get("FB_long"), 50) - 50) / 50.0)
    return round(float(np.clip(np.mean(marg), 0, 1)), 2)


def _plain_text(d: dict) -> str:
    """把诊断拼成有结论性的一段人话——六阶段都读实际读数（GAP/Sync/CogF/conviction/燃料/把握度），
    不是纯查表；并给"接下来盯什么"监控清单。面板 plain_text 字段 / agent 可直接引用。"""
    loop_zh = {"fast": "快环(情绪-资金)", "slow": "慢环(基本面-资本)",
               "dual": "双环共振", "none": "无明显反身性"}[d["loop_type"]]
    gap, sync, cog = d["gap_pct"], d["sync"], d["cog_f"]
    fbl, fbn, conv = d["fb_long"], d["fb_neg"], d["conviction"]
    fuel = _band(fbl, 40, 60, ("偏枯", "一般", "充足"))
    parts = [f"该股处于{d['stage_name']}（{loop_zh}）。"]
    st = d["stage"]
    # —— 阶段动态解读（读数插值，非固定模板）——
    if st == "S0":
        if gap >= 55 and sync <= 40:
            parts.append(f"未成自我强化回路，但价格分位已明显领先基本面（GAP={gap}）、二者走势还背离（Sync={sync}）"
                         "——属'价格跑在前面、方向对不上'的透支型，不是典型反身性，别当趋势去追。")
        elif gap >= 55:
            parts.append(f"未成回路，但 GAP={gap} 显示价格已透支基本面，留意回补压力。")
        else:
            parts.append(f"未识别出自我强化回路（GAP={gap}、Sync={sync} 均无极端），方向未定。")
    elif st == "S1":
        tt = f"，且正处第 {conv + 1} 次考验中" if d["in_test"] else ""
        parts.append(f"先知先觉资金进场、趋势尚未被大众充分认知；已扛过 {conv} 次洗盘考验{tt}"
                     "——越扛越稳，但也越接近大众追涨的加速段。")
    elif st == "S2":
        parts.append(f"趋势明确且在加速，燃料{fuel}（FB_long={fbl}）、已扛过 {conv} 次洗盘考验；"
                     "这是顺势持有区，越往后越要盯燃料能不能续上。")
    elif st == "S3":
        cogtxt = f"、'利好不涨'迹象已现（CogF={cog}，认知弹性在衰减）" if cog <= 45 else f"（CogF={cog}）"
        parts.append(f"价格分位极高、基本面跟不上{cogtxt}，进入狂热见暮色区（GAP={gap}）；透支越深，一旦转向回撤越急。")
    elif st == "S4":
        parts.append(f"自高点显著回撤、量价背离、融资退潮，反身性回路破裂（脆弱度 FB_neg={fbn}）。")
    elif st == "S5":
        spiral = "（含质押螺旋：跌→强平→再跌）" if d["fragile"] else ""
        parts.append(f"价格与基本面同步向下、越跌越卖的负反身性{spiral}；脆弱度 FB_neg={fbn}。")
    if d["loop_type"] == "fast" and st in ("S2", "S3"):
        parts.append("属纯情绪-资金反身性、无基本面支撑，来得快去得也快。")
    # —— 燃料常态化（S2 已在正文说，其余阶段这里补）——
    if st != "S2":
        parts.append(f"燃料表：新钱{fuel}（FB_long={fbl}）。")
    if d["fragile"]:
        parts.append(f"⚠️ 脆弱度偏高（FB_neg={fbn}：高质押/大解禁/折价出货），一旦下跌易被放大。")
    # —— 判断把握度 ——
    parts.append(f"本次判断把握{d.get('confidence_band', _band(d['confidence'], 0.3, 0.6))}"
                 f"（confidence={d['confidence']}，趋势/背离/燃料裕度综合）。")
    # —— 纪律 + 监控清单（不是预测，是盯盘清单）——
    advice_zh = {"observe": "观察为主", "add": "可顺势持有/加仓，但守纪律",
                 "hold": "持有", "reduce": "逢强减仓、不追高",
                 "exit": "清仓/规避", "avoid": "规避，勿抄底"}[d["position_advice"]]
    watch = {"S0": "Sync 是否转正、GAP 是否回补", "S1": "能否放量突破、conviction 是否再+1",
             "S2": "FB_long 是否续上、CogF 是否开始衰减", "S3": "对利好的反应(CogF)、是否放量滞涨",
             "S4": "是否止跌、融资余额是否企稳", "S5": "质押/强平压力、是否缩量止跌"}.get(st, "关键读数变化")
    tail = "；快环衰竭信号（炸板/断板/知名席位兑现）一出现即离场" if d["loop_type"] == "fast" and st in ("S2", "S3") else ""
    parts.append(f"纪律：{advice_zh}{tail}；接下来盯：{watch}。（不预测顶底，非投资建议）")
    return "".join(parts)


def _merge_cfg(config: Optional[dict]) -> dict:
    cfg = {k: (v.copy() if isinstance(v, dict) else v) for k, v in DEFAULT_CONFIG.items()}
    if config:
        for k, v in config.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


# ============================================================================
# 冒烟自测（`python reflexivity.py`）—— 正式测试见 test.py
# ============================================================================
def _demo_panel(n: int = 400, seed: int = 7) -> tuple[pd.DataFrame, list[dict]]:
    """构造一条'教科书 boom'合成轨迹：前段盘整→中段加速上涨+资金进+基本面上修。"""
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2024-01-01", periods=n)
    drift = np.concatenate([np.zeros(150), np.linspace(0, 0.004, 150), np.full(n - 300, 0.004)])
    ret = drift + rng.normal(0, 0.012, n)
    close = 10 * np.exp(np.cumsum(ret))
    panel = pd.DataFrame({
        "close_adj": close, "close_raw": close, "high": close * 1.02, "low": close * 0.98,
        "open": close, "pre_close": np.r_[close[0], close[:-1]],
        "volume": rng.uniform(1e7, 3e7, n), "amount": close * rng.uniform(1e7, 3e7, n),
        "turnover": np.clip(1 + drift * 400 + rng.normal(0, 0.5, n), 0.1, 12),
        "amplitude": np.abs(rng.normal(0.03, 0.01, n)),
        "is_limit_up": (ret > 0.09).astype(float),
        "lhb": (ret > 0.08).astype(float),
        "margin_balance": np.cumsum(np.r_[1e9, (drift[1:] * 5e9 + rng.normal(0, 1e8, n - 1))]),
        "holder_count": np.linspace(5e5, 3e5, n),  # 户数下降=集中
        "acc_pledge_ratio": np.full(n, 8.0),
    }, index=dates)
    events = [
        {"date": dates[160], "kind": "forecast", "value": 25.0},
        {"date": dates[220], "kind": "report", "value": 40.0},
        {"date": dates[250], "kind": "placement", "value": 1.0},
        {"date": dates[300], "kind": "report", "value": 55.0},
    ]
    return panel, events


if __name__ == "__main__":
    panel, events = _demo_panel()
    diag = analyze(panel, events)
    import json
    print(json.dumps({k: v for k, v in diag.items() if k != "plain_text"},
                     ensure_ascii=False, indent=2))
    print("\nplain_text:\n" + diag["plain_text"])
    # 全序列阶段分布
    df = compute_series(panel, events)
    print("\n阶段分布:", df["stage"].value_counts().to_dict())
    print("环型:", df["loop_type"].iloc[-1], "| 末日 score:", diag["score"])
