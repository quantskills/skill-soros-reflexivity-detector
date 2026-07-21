#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
skill-soros-reflexivity-detector · 数据层（PandaData → reflexivity 标准面板）
================================================================================
职责：用 PandaData 把一只股票的原始接口数据，整理成 reflexivity.py 消费的"标准面板"
（对齐到交易日的时间序列 DataFrame）+ 事件列表（基本面/公司行为，按公告日 PIT）。

数据源一律 PandaData（panda_data ≥ 0.0.9），凭证走 ~/.pandadata/pandadata.env
或环境变量 PANDA_USERNAME/PANDA_PASSWORD（**绝不硬编码**）。本模块所有拉数经 D1 真机实测
（2026-07-11，宁德/欧菲光/比亚迪/茅台），字段口径见 references/api_guide.md。

关键实测结论（决定本层设计）：
  · get_stock_daily 无 turnover → 用 get_factor 补 turnover/market_cap/后复权 close
  · get_hsgt_hold 个股北向 2024/08 起停止披露 → north 优雅降级（列缺失，FB_long 权重 0）
  · get_fina_performance 覆盖不全 → F 链以预告(增速中值)+财报(is_n_income_attr_p 同比)为主
  · get_fina_reports 320 列，归母净利=is_n_income_attr_p，if_adjusted 过滤，date=公告日 PIT
  · get_stock_pledge 事件型，acc_pledge_total_ratio=累计质押率 → as-of ffill 成脆弱度

免责：仅研究/教育示例，不构成投资建议。
"""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd


# ============================================================================
# 凭证 / 客户端（内联精简版，不跨仓库共享）
# ============================================================================
def _read_env_file() -> dict:
    env = {}
    p = Path.home() / ".pandadata" / "pandadata.env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def init_panda() -> Any:
    """初始化 panda_data。凭证优先环境变量，回退官方 env 文件。"""
    try:
        import panda_data
    except ModuleNotFoundError as exc:
        raise RuntimeError("无法导入 panda_data，请先 `pip install --upgrade panda_data`（需 ≥0.0.9）") from exc
    envf = _read_env_file()
    user = os.getenv("PANDA_USERNAME") or os.getenv("PANDA_DATA_USERNAME") or envf.get("DEFAULT_USERNAME", "")
    pwd = os.getenv("PANDA_PASSWORD") or os.getenv("PANDA_DATA_PASSWORD") or envf.get("DEFAULT_PASSWORD", "")
    base = os.getenv("PANDA_BASE_URL") or envf.get("JAVA_SERVICE_BASE_URL")
    if not (user and pwd):
        raise RuntimeError("缺少 PANDA 凭证（环境变量 PANDA_USERNAME/PANDA_PASSWORD 或 ~/.pandadata/pandadata.env）")
    if base:
        panda_data.init_token(username=user, password=pwd, base_url=base)
    else:
        panda_data.init_token(username=user, password=pwd)
    return panda_data


def _is_quota_or_service_error(exc: Exception) -> bool:
    t = str(exc)
    return any(k in t for k in ("500009", "单日总流量", "200103", "权限", "ServiceError",
                                 "空 detail", "504", "Gateway Time-out", "600003"))


def _compact(s: Any) -> str:
    return str(s).strip().replace("-", "").replace("/", "")[:8]


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _to_dt(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s.astype(str).str.replace(r"\.0$", "", regex=True), format="%Y%m%d", errors="coerce")


def board_rate(ts_code: str) -> float:
    c = str(ts_code).upper()
    if (c.startswith(("300", "301")) and c.endswith(".SZ")) or (c.startswith(("688", "689")) and c.endswith(".SH")):
        return 1.20
    if c.endswith(".BJ"):
        return 1.30
    return 1.10


def chunk_pull(fetch_fn, start: str, end: str, chunk_days: int = 365,
               retry_days: int = 90) -> pd.DataFrame:
    """按 chunk_days 分段拉取，超限/超时自动降级到 retry_days。用于全市场大跨度。"""
    cur = pd.to_datetime(_compact(start)).date()
    end_d = pd.to_datetime(_compact(end)).date()
    frames = []
    while cur <= end_d:
        seg_end = min(cur + timedelta(days=chunk_days - 1), end_d)
        try:
            f = fetch_fn(cur.strftime("%Y%m%d"), seg_end.strftime("%Y%m%d"))
            if f is not None and not f.empty:
                frames.append(f)
        except Exception as exc:  # noqa: BLE001
            if _is_quota_or_service_error(exc):
                sub = cur
                while sub <= seg_end:
                    se = min(sub + timedelta(days=retry_days - 1), seg_end)
                    try:
                        ff = fetch_fn(sub.strftime("%Y%m%d"), se.strftime("%Y%m%d"))
                        if ff is not None and not ff.empty:
                            frames.append(ff)
                    except Exception:  # noqa: BLE001
                        pass
                    sub = se + timedelta(days=1)
            else:
                raise
        cur = seg_end + timedelta(days=1)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _safe_call(fn, *, default=None):
    """接口调用容错：单源失败不拖垮整体（返回 default 并静默）。"""
    try:
        r = fn()
        return r if r is not None else default
    except Exception:  # noqa: BLE001
        return default


# ============================================================================
# 单票 loaders（列名/口径均按 D1 实测）
# ============================================================================
def load_price(sym: str, start: str, end: str, api) -> pd.DataFrame:
    """日线(不复权 OHLC/涨停/量) + 因子(后复权 close/turnover/市值) 合并到交易日。"""
    daily = _safe_call(lambda: api.get_stock_daily(symbol=[sym], start_date=_compact(start),
                                                   end_date=_compact(end), fields=[], indicator="", st=True))
    if daily is None or daily.empty:
        return pd.DataFrame()
    daily = daily.copy()
    daily["dt"] = _to_dt(daily["date"])
    for c in ("close", "high", "low", "open", "pre_close", "limit_up", "volume", "amount", "trade_status"):
        if c in daily:
            daily[c] = _num(daily[c])
    daily = daily.dropna(subset=["dt"]).set_index("dt").sort_index()
    rate = board_rate(sym)
    eff_lu = daily["limit_up"].where(daily["limit_up"] > 0, (daily["pre_close"] * rate).round(2))
    out = pd.DataFrame(index=daily.index)
    out["close_raw"] = daily["close"]
    out["high"] = daily["high"]; out["low"] = daily["low"]; out["open"] = daily["open"]
    out["pre_close"] = daily["pre_close"]; out["volume"] = daily["volume"]; out["amount"] = daily["amount"]
    out["is_limit_up"] = ((daily.get("trade_status", 0) == 0) & (daily["close"] >= eff_lu * 0.999)).astype(float)
    out["amplitude"] = ((daily["high"] - daily["low"]) / daily["pre_close"].replace(0, np.nan)).abs()

    factor = _safe_call(lambda: api.get_factor(symbol=[sym], start_date=_compact(start), end_date=_compact(end),
                                               factors=["turnover", "market_cap", "close"]))
    if factor is not None and not factor.empty:
        factor = factor.copy()
        factor["dt"] = _to_dt(factor["date"])
        factor = factor.dropna(subset=["dt"]).set_index("dt").sort_index()
        out["close_adj"] = _num(factor["close"]).reindex(out.index)
        out["turnover"] = _num(factor["turnover"]).reindex(out.index)
        out["market_cap"] = _num(factor.get("market_cap")).reindex(out.index) if "market_cap" in factor else np.nan
    # 后复权缺失 → 用不复权兜底（趋势跨除权略失真，标注可接受）
    out["close_adj"] = out.get("close_adj", pd.Series(index=out.index)).fillna(out["close_raw"])
    return out


def _asof_ffill(index: pd.DatetimeIndex, dates: pd.Series, values: pd.Series) -> pd.Series:
    """把稀疏(公告日, 值)按 as-of ffill 对齐到交易日 index（PIT：公告日当日起生效）。"""
    s = pd.Series(values.values, index=pd.to_datetime(dates.values)).dropna().sort_index()
    if s.empty:
        return pd.Series(np.nan, index=index)
    s = s[~s.index.duplicated(keep="last")]
    return s.reindex(index.union(s.index)).ffill().reindex(index)


def load_margin(sym, start, end, api, index) -> pd.Series:
    df = _safe_call(lambda: api.get_margin(symbol=sym, start_date=_compact(start), end_date=_compact(end),
                                           margin_type="cash", fields=[]))
    if df is None or df.empty or "margin_balance" not in df:
        return pd.Series(np.nan, index=index)
    return _asof_ffill(index, _to_dt(df["date"]), _num(df["margin_balance"]))


def load_holder(sym, start, end, api, index) -> pd.Series:
    df = _safe_call(lambda: api.get_holder_count(symbol=sym, start_date=_compact(start),
                                                 end_date=_compact(end), fields=[]))
    if df is None or df.empty:
        return pd.Series(np.nan, index=index)
    col = "holders" if "holders" in df else ("a_holders" if "a_holders" in df else None)
    if col is None:
        return pd.Series(np.nan, index=index)
    return _asof_ffill(index, _to_dt(df["date"]), _num(df[col]))


def load_pledge(sym, start, end, api, index) -> pd.Series:
    """大股东质押占其持股比例（acc_pledged_hold_ratio，同披露日多股东取最高=最脆弱者）as-of ffill。
    质押螺旋看的是大股东押了自己持股的多少（>55% 危险区）——不是总股本口径。
    总股本口径(acc_pledge_total_ratio)常 <10%，配 55% 阈值会让脆弱预警永不触发（已实测欧菲光该口径仅 ~7%，
    而其大股东持股口径达 ~77%）。仅取持股≥5% 的大股东，避免小股东满仓质押误报。"""
    df = _safe_call(lambda: api.get_stock_pledge(symbol=sym, start_date=_compact(start),
                                                 end_date=_compact(end), fields=[]))
    if df is None or df.empty:
        return pd.Series(0.0, index=index)  # 无质押记录=0（而非 NaN）
    col = next((c for c in ("acc_pledged_hold_ratio", "acc_pledge_total_ratio") if c in df), None)
    if col is None:
        return pd.Series(0.0, index=index)
    dcol = "publish_date" if "publish_date" in df else "date"
    tmp = pd.DataFrame({"_d": _to_dt(df[dcol]), "_v": _num(df[col]),
                        "_hold": _num(df["hold_ratio"]) if "hold_ratio" in df else 100.0}).dropna(subset=["_d", "_v"])
    tmp = tmp[tmp["_hold"].fillna(0) >= 5.0]                 # 只看大股东（持股≥5%）
    if tmp.empty:
        return pd.Series(0.0, index=index)
    g = tmp.groupby("_d")["_v"].max().sort_index()          # 同披露日取最脆弱大股东
    return _asof_ffill(index, pd.Series(g.index), pd.Series(g.values)).fillna(0.0)


def load_lhb_flag(sym, start, end, api, index) -> pd.Series:
    df = _safe_call(lambda: api.get_lhb_list(symbol=sym, start_date=_compact(start),
                                             end_date=_compact(end), type="", fields=[]))
    flag = pd.Series(0.0, index=index)
    if df is not None and not df.empty and "date" in df:
        days = _to_dt(df["date"]).dropna().unique()
        flag.loc[flag.index.isin(days)] = 1.0
    return flag


def load_north(sym, start, end, api, index) -> Optional[pd.Series]:
    """北向持股比例（2024/08 后个股多停披露 → 常空，返回 None 让上层降级）。"""
    df = _safe_call(lambda: api.get_hsgt_hold(symbol=sym, start_date=_compact(start),
                                              end_date=_compact(end), fields=[]))
    if df is None or df.empty or "holding_ratio" not in df:
        return None
    return _asof_ffill(index, _to_dt(df["date"]), _num(df["holding_ratio"]))


# ============================================================================
# 事件 loaders（→ [{date(公告日), kind, value, meta}]，全部 PIT）
# ============================================================================
def load_fundamental_events(sym, api, start_q="2022q1", end_q="2026q4") -> list[dict]:
    """基本面 F 链：预告(增速中值) + 财报(归母净利累计同比) → 净利同比% 事件。"""
    events: list[dict] = []
    # 预告
    fc = _safe_call(lambda: api.get_fina_forecast(symbol=sym, fields=[]))
    if fc is not None and not fc.empty:
        for _, r in fc.iterrows():
            lo, hi = _num_scalar(r.get("forecast_growth_rate_floor")), _num_scalar(r.get("forecast_growth_rate_ceiling"))
            mid = np.nanmean([v for v in (lo, hi) if v is not None]) if (lo is not None or hi is not None) else None
            if mid is None or not np.isfinite(mid):
                continue
            events.append({"date": _compact(r["info_date"]), "kind": "forecast", "value": float(mid),
                           "meta": {"type": r.get("forecast_type")}})
    # 财报归母净利累计同比
    # as-of 取 end_q 所在年年末（派生而非硬编码未来常量）；事件仍带各自真实公告日，跨窗口自然落边界外
    as_of = _compact(str(end_q)[:4] + "1231")
    rp = _safe_call(lambda: api.get_fina_reports(symbol=sym, date=as_of,
                                                 start_quarter=start_q, end_quarter=end_q, is_latest=False,
                                                 fields=["symbol", "date", "quarter", "if_adjusted", "is_n_income_attr_p"]))
    if rp is not None and not rp.empty and "is_n_income_attr_p" in rp:
        rp = rp.copy()
        rp["np"] = _num(rp["is_n_income_attr_p"])
        rp["ann"] = _to_dt(rp["date"])
        # 每个 quarter 取当期(if_adjusted==0 优先)最新公告
        rp = rp.dropna(subset=["np", "ann", "quarter"])
        rp["adj"] = _num(rp.get("if_adjusted", 0)).fillna(0)
        rp = rp.sort_values(["quarter", "adj", "ann"]).groupby("quarter", as_index=False).first()
        by_q = {q: (float(v), a) for q, v, a in zip(rp["quarter"], rp["np"], rp["ann"])}
        for q, (npv, ann) in by_q.items():
            py = _prev_year_q(q)
            if py in by_q and by_q[py][0] not in (0, None) and np.isfinite(by_q[py][0]) and by_q[py][0] != 0:
                yoy = (npv / abs(by_q[py][0]) - 1.0) * 100.0 * (1 if by_q[py][0] > 0 else -1)
                events.append({"date": ann.strftime("%Y%m%d"), "kind": "report", "value": float(yoy),
                               "meta": {"quarter": q}})
    # 快报（覆盖不全，可选补充）
    perf = _safe_call(lambda: api.get_fina_performance(symbol=sym, end_quarter=end_q, fields=[]))
    if perf is not None and not perf.empty and "np_parent_minority_pany_yoy" in perf:
        for _, r in perf.iterrows():
            yoy = _num_scalar(r.get("np_parent_minority_pany_yoy"))
            if yoy is not None and np.isfinite(yoy):
                events.append({"date": _compact(r["info_date"]), "kind": "express", "value": float(yoy),
                               "meta": {}})
    return events


def load_corp_action_events(sym, start, end, api, close: Optional[pd.Series] = None) -> list[dict]:
    """公司行为脉冲：回购/定增/增减持/解禁/大宗折价/ST。close=当日不复权收盘（判大宗折价用）。"""
    events: list[dict] = []
    # 回购（进行中/实施 → 正脉冲）
    rp = _safe_call(lambda: api.get_repurchase(symbol=sym, start_date=_compact(start), end_date=_compact(end), fields=[]))
    if rp is not None and not rp.empty:
        for _, r in rp.iterrows():
            proc = str(r.get("procedure", ""))
            if any(k in proc for k in ("实施", "完成", "进行")):
                events.append({"date": _compact(r["date"]), "kind": "repurchase", "value": 1.0, "meta": {"proc": proc}})
    # 定增（实施完成 → 资本闭环正脉冲）
    pp = _safe_call(lambda: api.get_stock_private_placement(symbol=sym, start_date=_compact(start), end_date=_compact(end), fields=[]))
    if pp is not None and not pp.empty:
        for _, r in pp.iterrows():
            if "实施" in str(r.get("issue_status", "")):
                d = r.get("listed_date") or r.get("announcement_date")
                events.append({"date": _compact(d), "kind": "placement", "value": 1.0, "meta": {}})
    # 增减持计划
    sc = _safe_call(lambda: api.get_stock_shareholder_change(symbol=sym, start_date=_compact(start), end_date=_compact(end), fields=[]))
    if sc is not None and not sc.empty:
        for _, r in sc.iterrows():
            d = _compact(r.get("info_date"))
            direction = str(r.get("direction", ""))
            ratio = _num_scalar(r.get("ratio_up_limit")) or 0.5
            if "增持" in direction:
                events.append({"date": d, "kind": "holder_add", "value": float(min(1, ratio)), "meta": {}})
            elif "减持" in direction:
                events.append({"date": d, "kind": "holder_reduce", "value": float(min(1, ratio)), "meta": {}})
    # 解禁（前瞻承压，事件日=解禁日；纳入条件=公告日在区间内）
    rl = _safe_call(lambda: api.get_restricted_list(symbol=sym, start_date=_compact(start), end_date=_compact(end), fields=[]))
    if rl is not None and not rl.empty and "relieve_date" in rl:
        for _, r in rl.iterrows():
            events.append({"date": _compact(r["relieve_date"]), "kind": "unlock", "value": 1.0,
                           "meta": {"announce": _compact(r.get("date"))}})
    # 大宗折价：只有"对当日收盘折价≥3%"才算折价出货（脆弱信号）；无收盘价参照→保守跳过（不误报）
    bt = _safe_call(lambda: api.get_block_trade(symbol=sym, start_date=_compact(start), end_date=_compact(end), fields=[]))
    if bt is not None and not bt.empty and "price" in bt and close is not None and not close.empty:
        cmap = {pd.Timestamp(d).normalize(): float(v) for d, v in close.dropna().items()}
        for _, r in bt.iterrows():
            dt = _to_dt(pd.Series([r.get("date")])).iloc[0]
            px = _num_scalar(r.get("price"))
            c = cmap.get(pd.Timestamp(dt).normalize()) if pd.notna(dt) else None
            if px and c and c > 0 and (1.0 - px / c) >= 0.03:   # 折价≥3% 才计入（滤掉平价/溢价成交）
                events.append({"date": _compact(r["date"]), "kind": "block_discount", "value": 1.0,
                               "meta": {"discount": round(1.0 - px / c, 4)}})
    # ST / 退市风险
    st = _safe_call(lambda: api.get_stock_status_change(symbol=sym, start_date=_compact(start), end_date=_compact(end), fields=[]))
    if st is not None and not st.empty:
        for _, r in st.iterrows():
            typ = str(r.get("type", ""))
            if "ST" in typ and "撤销" not in typ:
                events.append({"date": _compact(r["date"]), "kind": "st", "value": 1.0, "meta": {"type": typ}})
    return events


def _num_scalar(x):
    try:
        v = float(x)
        return v if np.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _prev_year_q(q: str) -> str:
    try:
        y, qq = q.lower().split("q")
        return f"{int(y) - 1}q{qq}"
    except Exception:  # noqa: BLE001
        return ""


# ============================================================================
# 组装：build_panel（供 build.py 调用）
# ============================================================================
def build_panel(sym: str, start: str, end: str, api=None,
                lookback_days: int = 500) -> tuple[pd.DataFrame, list[dict]]:
    """一只股票的标准面板 + 事件列表。start 应比分析起点早 lookback_days（保证分位/趋势窗口）。"""
    if api is None:
        api = init_panda()
    price = load_price(sym, start, end, api)
    if price.empty:
        return pd.DataFrame(), []
    idx = price.index
    price["margin_balance"] = load_margin(sym, start, end, api, idx)
    price["holder_count"] = load_holder(sym, start, end, api, idx)
    price["acc_pledge_ratio"] = load_pledge(sym, start, end, api, idx)
    price["lhb"] = load_lhb_flag(sym, start, end, api, idx)
    north = load_north(sym, start, end, api, idx)
    if north is not None and north.notna().any():
        price["north_ratio"] = north
    events = load_fundamental_events(sym, api) + load_corp_action_events(sym, start, end, api, close=price.get("close_raw"))
    events = [e for e in events if e.get("date") and _compact(e["date"]) <= _compact(end)]
    return price, events


# ============================================================================
# 漏斗宇宙（scan 模式）：全市场先筛候选，再逐票深算（省流量）
# ============================================================================
def funnel_universe(end: str, api=None, top_n: int = 300, cfg: Optional[dict] = None) -> list[str]:
    """强趋势 top_n ∪ 近 60d 有基本面事件 ∪ 近 20d 快环活跃（涨停≥2/上榜）。
    ⚠️ 全市场日线是大流量操作，scan 模式专用；watchlist 模式不走此路。"""
    if api is None:
        api = init_panda()
    end_c = _compact(end)
    start_c = _compact((pd.to_datetime(end_c) - timedelta(days=110)).strftime("%Y%m%d"))
    daily = _safe_call(lambda: api.get_stock_daily(symbol="", start_date=start_c, end_date=end_c,
                                                   fields=["symbol", "date", "close", "pre_close", "limit_up", "trade_status"],
                                                   indicator="", st=False))
    if daily is None or daily.empty:
        return []
    daily = daily.copy()
    daily["dt"] = _to_dt(daily["date"])
    daily["close"] = _num(daily["close"])
    cand: set[str] = set()
    # 强趋势：60 日对数收益（近似 P 的方向强度）
    piv = daily.pivot_table(index="dt", columns="symbol", values="close").sort_index()
    if len(piv) >= 40:
        logret = np.log(piv.iloc[-1] / piv.iloc[max(0, len(piv) - 60)])
        strong = logret.abs().sort_values(ascending=False).head(top_n).index.tolist()
        cand.update(strong)
    # 快环活跃：近 20 日涨停≥2
    tail = daily[daily["dt"] >= daily["dt"].max() - pd.Timedelta(days=30)]
    rate_ok = tail.assign(lu=(_num(tail["close"]) >= _num(tail["limit_up"]) * 0.999)).groupby("symbol")["lu"].sum()
    cand.update(rate_ok[rate_ok >= 2].index.tolist())
    return sorted(cand)


if __name__ == "__main__":
    # 真机冒烟：拉宁德近 2 年标准面板 + 事件（需凭证）
    import json
    api = init_panda()
    panel, events = build_panel("300750.SZ", "20240101", "20260711", api)
    print(f"panel {panel.shape} cols={list(panel.columns)}")
    print(panel.tail(3).to_string())
    print(f"\n事件 {len(events)} 条:")
    for e in events[-8:]:
        print(" ", json.dumps(e, ensure_ascii=False, default=str))
