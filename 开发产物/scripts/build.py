#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
skill-soros-reflexivity-detector · BUILD 主入口（#48）
================================================================================
工具定位（BUILD开发与生产规则V2 §3）：监控预警 + 分析报告型 BUILD。
把"索罗斯反身性识别"封装成可被 agent 调用的工具：给一只/一组股票出
反身性阶段诊断 + 证据链 + 建议仓位（快环/慢环/双环）。

标准入口 run(input_data, config=None) 支持三种输入：
  1. watchlist：{"symbols": ["300750.SZ", ...], "date": "YYYYMMDD"} —— 逐票深算（实时）
  2. scan：     {"mode": "scan", "date": "YYYYMMDD", "top_n": 300} —— 漏斗全市场（重，生产用）
  3. 直连：     {"panel": <DataFrame/records>, "events": [...], "symbol": "..."} —— 调用方已有数据，跳过拉数

输出：BUILD §11 标准面板（个股行 reflexivity_stock + 每日汇总行 reflexivity_summary）。
生产：maintain_daily/backfill → 生产产物/database.parquet（结果型，agent 直接读，不重算）。

数据源 PandaData；凭证走环境变量/官方 env 文件。免责：仅研究/教育示例，不构成投资建议。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

import datasource as ds
import reflexivity as rx

BUILD_ID = "48"
BUILD_NAME = "索罗斯反身性识别器"
RESULT_STOCK = "reflexivity_stock"
RESULT_SUMMARY = "reflexivity_summary"
DATA_VERSION = "soros-reflexivity-v1"

DEV_ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = DEV_ROOT.parent
DEFAULT_OUT = BUILD_ROOT / "生产产物" / "database.parquet"

_PANEL_COLS = ["p_trend", "p_pctl", "f_slope", "fb_long", "fb_neg", "cog_f",
               "par_f", "fast_loop", "sync", "gap_pct", "conviction", "confidence"]


# ============================================================================
# 输入校验
# ============================================================================
def validate_input(input_data: Any) -> dict:
    """归一化输入为 dict；缺字段/空/类型错抛 ValueError（BUILD §6）。"""
    if input_data is None:
        raise ValueError("input_data 不能为 None")
    if isinstance(input_data, str):
        return {"symbols": [input_data]}
    if isinstance(input_data, (list, tuple)):
        if not input_data:
            raise ValueError("symbols 列表为空")
        return {"symbols": list(input_data)}
    if isinstance(input_data, dict):
        if "panel" in input_data:
            if input_data.get("panel") is None:
                raise ValueError("panel 为空")
            return input_data
        if input_data.get("mode") == "scan":
            return input_data
        if input_data.get("symbols"):
            return input_data
        raise ValueError("dict 输入必须含 symbols / mode=scan / panel 之一")
    raise ValueError(f"不支持的 input_data 类型：{type(input_data)}")


# ============================================================================
# 标准面板输出
# ============================================================================
def _stock_row(sym: str, diag: dict, date: str) -> dict:
    # trade_date 用真实交易日（diag），非入参日；入参为非交易日时显式标记（artifact P2#15）
    real = str(diag.get("trade_date") or date)
    adjusted = bool(date) and ds._compact(str(date)) != real
    row = {
        "trade_date": real, "build_id": BUILD_ID, "build_name": BUILD_NAME,
        "input_date_adjusted": adjusted,
        "target_id": sym, "ts_code": sym, "result_type": RESULT_STOCK,
        "result_value": diag["stage"], "loop_type": diag["loop_type"],
        "stage_name": diag["stage_name"], "score": diag["score"],
        "position_advice": diag["position_advice"], "fragile_flag": bool(diag["fragile"]),
        "in_test": bool(diag["in_test"]), "plain_text": diag["plain_text"],
        "result_json": json.dumps(diag, ensure_ascii=False, default=str),
        "data_version": DATA_VERSION, "update_time": datetime.now().isoformat(timespec="seconds"),
    }
    for c in _PANEL_COLS:
        row[c] = diag.get(c)
    return row


def _summary_row(rows: list[dict], date: str) -> dict:
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["result_value"])
    dist = df["result_value"].value_counts().to_dict() if not df.empty else {}
    fragile_n = int(df["fragile_flag"].sum()) if "fragile_flag" in df else 0
    summ = {
        "n_analyzed": len(rows),
        "stage_dist": dist,
        "n_fragile": fragile_n,
        "n_S2_add": int((df["result_value"] == "S2").sum()) if not df.empty else 0,
        "n_S3_reduce": int((df["result_value"] == "S3").sum()) if not df.empty else 0,
        "loop_dist": df["loop_type"].value_counts().to_dict() if "loop_type" in df else {},
    }
    return {
        "trade_date": date, "build_id": BUILD_ID, "build_name": BUILD_NAME,
        "target_id": "MARKET", "ts_code": "MARKET", "result_type": RESULT_SUMMARY,
        "result_value": f"{len(rows)}只/{fragile_n}脆弱", "loop_type": "", "stage_name": "",
        "score": np.nan, "position_advice": "", "fragile_flag": False, "in_test": False,
        "plain_text": f"当日分析 {len(rows)} 只，阶段分布 {dist}，脆弱标的 {fragile_n} 只。",
        "result_json": json.dumps(summ, ensure_ascii=False, default=str),
        "data_version": DATA_VERSION, "update_time": datetime.now().isoformat(timespec="seconds"),
        **{c: np.nan for c in _PANEL_COLS},
    }


def to_standard_output(rows: list[dict], date: str) -> pd.DataFrame:
    out = list(rows) + [_summary_row(rows, date)]
    return pd.DataFrame(out)


# ============================================================================
# 主入口
# ============================================================================
def run(input_data: Any, config: Optional[dict] = None) -> pd.DataFrame:
    """反身性诊断标准入口。返回 BUILD §11 标准面板。"""
    cfg = config or {}
    spec = validate_input(input_data)

    # 模式 3：调用方直连（已有 panel，跳过拉数）
    if "panel" in spec:
        panel = spec["panel"]
        if not isinstance(panel, pd.DataFrame):
            panel = pd.DataFrame(panel)
            if "dt" in panel:
                panel = panel.set_index("dt")
        sym = spec.get("symbol", "UNKNOWN")
        date = spec.get("date") or (panel.index[-1].strftime("%Y%m%d") if len(panel) else _today())
        diag = rx.analyze(panel, spec.get("events", []), cfg.get("reflexivity"), as_of=spec.get("date"))
        return to_standard_output([_stock_row(sym, diag, date)], date)

    date = spec.get("date") or _today()
    api = cfg.get("api") or ds.init_panda()

    # 模式 2：scan 漏斗
    if spec.get("mode") == "scan":
        top_n = int(spec.get("top_n", 300))
        max_sym = int(spec.get("max_symbols", cfg.get("max_symbols", 400)))
        syms = ds.funnel_universe(date, api, top_n=top_n)[:max_sym]
    else:
        # 模式 1：watchlist
        syms = list(spec["symbols"])

    start = _lookback_start(date, spec.get("lookback_days", 500))
    rows: list[dict] = []
    for sym in syms:
        try:
            panel, events = ds.build_panel(sym, start, date, api)
            if panel is None or len(panel) < 30:
                continue
            diag = rx.analyze(panel, events, cfg.get("reflexivity"), as_of=date)
            rows.append(_stock_row(sym, diag, date))   # 传入参日，让 _stock_row 判非交易日调整
        except Exception as exc:  # noqa: BLE001
            if ds._is_quota_or_service_error(exc):
                print(f"⏭️  {sym} 跳过（配额/服务）：{str(exc)[:50]}")
                continue
            print(f"⚠️  {sym} 分析失败：{type(exc).__name__}: {str(exc)[:60]}")
    return to_standard_output(rows, date)


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _lookback_start(date: str, days: int) -> str:
    return (pd.to_datetime(ds._compact(date)) - pd.Timedelta(days=days)).strftime("%Y%m%d")


# ============================================================================
# 生产维护
# ============================================================================
def maintain_daily(date: Optional[str] = None, symbols: Optional[list] = None,
                   config: Optional[dict] = None) -> pd.DataFrame:
    """每日生产：watchlist(给定 symbols) 或 scan(全市场漏斗)。"""
    date = date or _today()
    if symbols:
        return run({"symbols": symbols, "date": date}, config)
    return run({"mode": "scan", "date": date}, config)


def backfill(start: str, end: str, symbols: list, config: Optional[dict] = None) -> pd.DataFrame:
    """区间回填（按交易日逐日对给定 symbols 出诊断）。"""
    api = (config or {}).get("api") or ds.init_panda()
    cal = ds._safe_call(lambda: api.get_trade_cal(start_date=ds._compact(start), end_date=ds._compact(end),
                                                  exchange="SH", is_trading_day=1))
    dates = [str(d) for d in cal["nature_date"]] if cal is not None and not cal.empty else [end]
    frames = []
    for d in dates:
        frames.append(run({"symbols": symbols, "date": d}, {**(config or {}), "api": api}))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def save_parquet(panel: pd.DataFrame, out: Path = DEFAULT_OUT) -> Path:
    """落地/合并进生产 parquet（主键去重）。无 pyarrow 时降级 CSV 并提示。"""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    key = ["trade_date", "build_id", "target_id", "result_type"]
    combined = panel
    try:
        if out.exists():
            old = pd.read_parquet(out)
            combined = pd.concat([old, panel], ignore_index=True)
        combined = combined.drop_duplicates(subset=key, keep="last")
        combined.to_parquet(out, index=False)
        return out
    except ImportError:
        alt = out.with_suffix(".csv")
        print(f"⚠️ 无 pyarrow，降级写 CSV：{alt}")
        combined.drop_duplicates(subset=key, keep="last").to_csv(alt, index=False)
        return alt


# ============================================================================
# CLI
# ============================================================================
def _cli():
    ap = argparse.ArgumentParser(description="索罗斯反身性识别器 BUILD #48")
    ap.add_argument("--mode", choices=["watchlist", "scan"], default="watchlist")
    ap.add_argument("--symbols", nargs="*", default=["300750.SZ"])
    ap.add_argument("--date", default=None)
    ap.add_argument("--save", action="store_true", help="落地生产 parquet")
    ap.add_argument("--top-n", type=int, default=300)
    args = ap.parse_args()
    if args.mode == "scan":
        panel = run({"mode": "scan", "date": args.date, "top_n": args.top_n})
    else:
        panel = run({"symbols": args.symbols, "date": args.date})
    stocks = panel[panel["result_type"] == RESULT_STOCK]
    print(stocks[["ts_code", "result_value", "loop_type", "score", "position_advice", "fragile_flag"]].to_string(index=False))
    for _, r in stocks.iterrows():
        print(f"\n[{r['ts_code']}] {r['plain_text']}")
    if args.save:
        print("\n落地:", save_parquet(panel))


if __name__ == "__main__":
    _cli()
