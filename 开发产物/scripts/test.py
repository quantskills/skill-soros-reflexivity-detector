#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
skill-soros-reflexivity-detector · 测试（全离线）
================================================================================
全部用合成剧本夹具，不联网、不 import panda_data（懒加载），干净环境须全绿。
运行：python test.py
覆盖：状态机确定性(boom/负反身/夭折) · 考验conviction · 暮色CogF衰减 · 质押螺旋fragile ·
     快环loop_type · 环型参数切换 · PIT(as_of) · 空/单边缺失/dtype · validate · run直连 · render ·
     真实数据(optional，配额/无SDK自动跳过)。
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd

import reflexivity as rx
import build as B
import render as R
import datasource as DS


class _FakeAPI:
    """最小假 api：默认所有接口返回空 DataFrame，只有指定的返回数据（供 datasource 离线单测）。"""
    def __init__(self, **overrides):
        self._ov = overrides

    def __getattr__(self, name):
        return lambda *a, **k: self._ov.get(name, pd.DataFrame())


# ============================================================================
# 合成剧本夹具
# ============================================================================
def _mk(close, n, **cols):
    dates = pd.bdate_range("2023-06-01", periods=n)
    close = np.asarray(close, dtype=float)
    pre = np.r_[close[0], close[:-1]]
    panel = pd.DataFrame({
        "close_adj": close, "close_raw": close, "high": close * 1.015, "low": close * 0.985,
        "open": pre, "pre_close": pre, "volume": np.full(n, 2e7), "amount": close * 2e7,
        "turnover": cols.get("turnover", np.full(n, 2.0)),
        "amplitude": cols.get("amplitude", np.full(n, 0.03)),
        "is_limit_up": cols.get("is_limit_up", np.zeros(n)),
        "lhb": cols.get("lhb", np.zeros(n)),
        "margin_balance": cols.get("margin_balance", np.full(n, 1e9)),
        "holder_count": cols.get("holder_count", np.full(n, 4e5)),
        "acc_pledge_ratio": cols.get("acc_pledge_ratio", np.zeros(n)),
    }, index=dates)
    return panel, dates


def _boom(n=360, seed=1):
    """盘整→加速上涨 + 融资升 + 户数集中 + 基本面上修（教科书 boom）。"""
    rng = np.random.RandomState(seed)
    drift = np.r_[np.zeros(150), np.linspace(0.001, 0.006, 120), np.full(n - 270, 0.006)]
    ret = drift + rng.normal(0, 0.008, n)
    close = 10 * np.exp(np.cumsum(ret))
    panel, dates = _mk(close, n,
                       turnover=np.clip(1.5 + drift * 500 + rng.normal(0, 0.3, n), 0.2, 15),
                       margin_balance=np.cumsum(np.r_[1e9, drift[1:] * 8e9 + rng.normal(0, 5e7, n - 1)]),
                       holder_count=np.linspace(6e5, 3e5, n))
    events = [{"date": dates[160].strftime("%Y%m%d"), "kind": "forecast", "value": 30.0},
              {"date": dates[210].strftime("%Y%m%d"), "kind": "report", "value": 45.0},
              {"date": dates[260].strftime("%Y%m%d"), "kind": "report", "value": 60.0},
              {"date": dates[280].strftime("%Y%m%d"), "kind": "placement", "value": 1.0}]
    return panel, events, dates


def _neg(n=360, seed=2):
    """持续下跌 + 基本面下修 + 融资降（负反身性）。"""
    rng = np.random.RandomState(seed)
    drift = np.r_[np.zeros(120), np.linspace(-0.001, -0.006, 120), np.full(n - 240, -0.006)]
    ret = drift + rng.normal(0, 0.008, n)
    close = 30 * np.exp(np.cumsum(ret))
    panel, dates = _mk(close, n,
                       margin_balance=np.cumsum(np.r_[5e9, drift[1:] * 8e9 - rng.uniform(0, 3e7, n - 1)]))
    events = [{"date": dates[130].strftime("%Y%m%d"), "kind": "forecast", "value": -10.0},
              {"date": dates[200].strftime("%Y%m%d"), "kind": "report", "value": -35.0}]
    return panel, events, dates


def _fast(n=200, seed=3):
    """涨停密集 + 龙虎榜 + 融资升，无基本面事件（纯快环）。"""
    rng = np.random.RandomState(seed)
    ret = np.r_[np.zeros(120), rng.choice([0.10, 0.10, 0.02, -0.03], n - 120)]
    close = 8 * np.exp(np.cumsum(ret))
    lu = (ret > 0.09).astype(float)
    panel, dates = _mk(close, n, is_limit_up=lu, lhb=lu,
                       turnover=np.clip(2 + lu * 8 + rng.normal(0, 0.5, n), 0.5, 20),
                       margin_balance=np.cumsum(np.r_[1e9, np.where(ret[1:] > 0, 3e8, -5e7)]))
    return panel, [], dates


def _pledge(n=360, seed=4):
    """高累计质押率 + 下跌（质押螺旋 → fragile + S5）。"""
    _, dates = _mk(np.ones(n), n)
    p, ev, dates = _neg(n, seed)
    p["acc_pledge_ratio"] = 72.0
    return p, ev, dates


# ============================================================================
# 测试
# ============================================================================
def test_state_machine_boom():
    panel, events, _ = _boom()
    df = rx.compute_series(panel, events)
    stages = set(df["stage"].unique())
    assert "S2" in stages, f"boom 应识别出加速期 S2，实际 {sorted(stages)}"
    d = rx.analyze(panel, events)
    assert d["stage"] in ("S1", "S2", "S3"), d["stage"]
    assert d["loop_type"] in ("slow", "dual"), d["loop_type"]
    print(f"✅ test_state_machine_boom（阶段含 S2，末态 {d['stage']}/{d['loop_type']}）")


def test_negative_reflexivity():
    panel, events, _ = _neg()
    df = rx.compute_series(panel, events)
    d = rx.analyze(panel, events)
    assert "S5" in set(df["stage"].unique()) or d["stage"] == "S5", f"负反身性应出现 S5，末态 {d['stage']}"
    assert d["position_advice"] in ("avoid", "exit", "observe")
    print(f"✅ test_negative_reflexivity（出现 S5，末态 {d['stage']}）")


def test_no_false_S3_on_flat():
    """横盘不应误触发狂热 S3。"""
    rng = np.random.RandomState(9)
    n = 320
    close = 20 * np.exp(np.cumsum(rng.normal(0, 0.006, n)))
    panel, _ = _mk(close, n)
    df = rx.compute_series(panel, [])
    assert (df["stage"] == "S3").sum() == 0, "横盘不应出现 S3"
    print("✅ test_no_false_S3_on_flat（横盘无误报 S3）")


def test_conviction_on_test():
    """加速中经历回调考验并创新高 → conviction 累加。用 boom 加速轨迹(确保先进 S2)再插回调。"""
    n = 360
    rng = np.random.RandomState(5)
    drift = np.r_[np.zeros(150), np.linspace(0.002, 0.007, 120), np.full(n - 270, 0.006)]
    ret = drift + rng.normal(0, 0.004, n)
    ret[226:232] -= 0.022  # 加速段中一次 ~10% 回调考验，之后恢复上涨创新高
    close = 10 * np.exp(np.cumsum(ret))
    lu = (ret > 0.02).astype(float)  # 上涨日频繁上榜（燃料）
    panel, dates = _mk(close, n,
                       turnover=np.clip(2 + drift * 800, 0.2, 18),
                       lhb=lu, is_limit_up=lu,
                       margin_balance=np.cumsum(np.r_[1e9, np.maximum(drift[1:], 0) * 3e10]),
                       holder_count=np.linspace(7e5, 2.5e5, n))
    events = [{"date": dates[200].strftime("%Y%m%d"), "kind": "repurchase", "value": 1.0},
              {"date": dates[160].strftime("%Y%m%d"), "kind": "forecast", "value": 30.0},
              {"date": dates[210].strftime("%Y%m%d"), "kind": "report", "value": 55.0}]
    df = rx.compute_series(panel, events)
    assert df["conviction"].max() >= 1, f"应累计至少 1 次考验通过，实际 max={df['conviction'].max()}"
    print(f"✅ test_conviction_on_test（考验通过 conviction max={int(df['conviction'].max())}）")


def test_cogf_decay_twilight():
    """利好不涨：后一个正 surprise 的价格弹性弱于前一个 → CogF 下降（暮色）。"""
    n = 320
    close = np.r_[10 * np.exp(np.cumsum(np.r_[np.zeros(100), np.full(60, 0.01)])),  # 事件1后大涨
                  np.full(160, np.nan)]
    close = pd.Series(close).ffill().values
    close[160:] = close[159]  # 事件2后价格走平（利好不涨）
    close = close * (1 + np.random.RandomState(6).normal(0, 0.002, n))
    panel, dates = _mk(close, n)
    events = [{"date": dates[95].strftime("%Y%m%d"), "kind": "report", "value": 30.0},
              {"date": dates[158].strftime("%Y%m%d"), "kind": "report", "value": 60.0}]
    cog = rx.cog_f_series(panel, events)
    early = cog.iloc[110]
    late = cog.iloc[-1]
    assert late <= early + 1, f"利好不涨应使 CogF 不升反降：early={early:.1f} late={late:.1f}"
    print(f"✅ test_cogf_decay_twilight（CogF {early:.0f}→{late:.0f}，暮色信号）")


def test_fast_loop_type():
    panel, events, _ = _fast()
    lt = rx.classify_loop_type(panel, events, rx._merge_cfg(None))
    assert lt == "fast", f"涨停+龙虎榜+融资无基本面应判 fast，实际 {lt}"
    d = rx.analyze(panel, events)
    assert d["fast_loop"] >= 55, f"FastLoop 应偏高，实际 {d['fast_loop']}"
    print(f"✅ test_fast_loop_type（loop_type=fast, FastLoop={d['fast_loop']}）")


def test_pledge_fragile():
    panel, events, _ = _pledge()
    d = rx.analyze(panel, events)
    assert d["fragile"] is True, f"高质押+下跌应 fragile，fb_neg={d['fb_neg']}"
    print(f"✅ test_pledge_fragile（fragile=True, fb_neg={d['fb_neg']}）")


def test_pit_as_of():
    """PIT：未来事件/未来价格不得影响 as_of 当日诊断。"""
    panel, events, dates = _boom()
    mid = dates[250].strftime("%Y%m%d")
    d_full = rx.analyze(panel, events, as_of=mid)
    # 追加一个未来事件 + 篡改未来价格，as_of 结果应不变
    ev2 = events + [{"date": dates[350].strftime("%Y%m%d"), "kind": "report", "value": 999.0}]
    panel2 = panel.copy()
    panel2.iloc[300:] *= 3.0
    d_cut = rx.analyze(panel2, ev2, as_of=mid)
    assert d_full["stage"] == d_cut["stage"] and abs(d_full["score"] - d_cut["score"]) < 0.1, \
        f"未来信息泄漏：{d_full['stage']}/{d_full['score']} vs {d_cut['stage']}/{d_cut['score']}"
    print(f"✅ test_pit_as_of（as_of={mid} 不受未来价格/事件影响）")


def test_empty_and_missing_cols():
    try:
        rx.analyze(pd.DataFrame(), [])
    except ValueError:
        pass
    else:
        raise AssertionError("空 panel 必须抛 ValueError")
    # 缺资金列 + 全 None dtype 列不崩
    n = 300
    close = 10 * np.exp(np.cumsum(np.random.RandomState(8).normal(0.001, 0.01, n)))
    dates = pd.bdate_range("2023-06-01", periods=n)
    panel = pd.DataFrame({"close_adj": close, "close_raw": close, "high": close, "low": close,
                          "open": close, "pre_close": close, "volume": 1e7, "amount": 1e8,
                          "acc_pledge_ratio": [None] * n}, index=dates)
    d = rx.analyze(panel, [])
    assert d["stage"] in rx.STAGES
    print("✅ test_empty_and_missing_cols（空抛错；缺列/None dtype 不崩）")


def test_short_history_guard():
    close = 10 * np.exp(np.cumsum(np.full(40, 0.01)))
    panel, _ = _mk(close, 40)
    d = rx.analyze(panel, [])
    assert d["stage"] == "S0" and "历史不足" in d.get("note", ""), d
    print("✅ test_short_history_guard（历史不足保守置 S0）")


def test_validate_input():
    for bad in (None, [], {}, {"foo": 1}):
        try:
            B.validate_input(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} 应抛 ValueError")
    assert B.validate_input("300750.SZ") == {"symbols": ["300750.SZ"]}
    assert B.validate_input(["a", "b"])["symbols"] == ["a", "b"]
    print("✅ test_validate_input（None/空/无键抛错，字符串/列表归一化）")


def test_run_direct_and_output():
    """run 直连模式（传 panel，不联网）+ 标准面板结构 + result_json 可解析。"""
    panel, events, _ = _boom()
    out = B.run({"panel": panel, "events": events, "symbol": "TEST.SZ", "date": "20240101"})
    assert {"trade_date", "build_id", "target_id", "result_type", "result_value",
            "result_json", "plain_text", "loop_type", "score"} <= set(out.columns)
    assert (out["build_id"] == "48").all()
    stock = out[out["result_type"] == B.RESULT_STOCK].iloc[0]
    assert stock["ts_code"] == "TEST.SZ"
    summ = out[out["result_type"] == B.RESULT_SUMMARY]
    assert len(summ) == 1
    for j in out["result_json"]:
        json.loads(j)
    print(f"✅ test_run_direct_and_output（直连出诊断 {stock['result_value']}，面板+汇总+JSON 全合规）")


def test_render():
    panel, events, _ = _boom()
    out = B.run({"panel": panel, "events": events, "symbol": "TEST.SZ", "date": "20240101"})
    md = R.render_markdown(out)
    assert "反身性诊断档案" in md and "通俗解读" in md and "术语表" in md
    html = R.render_html(out)
    assert "<html" in html and "反身性" in html and "TEST.SZ" in html
    print("✅ test_render（markdown 双行+术语表 / HTML 看板）")


def test_block_discount_gating():
    """大宗折价：只有对当日收盘折价≥3% 才计入（滤掉平价/溢价/微折）。"""
    idx = pd.bdate_range("2024-01-01", periods=5)
    close = pd.Series(100.0, index=idx)
    bt = pd.DataFrame({"date": ["20240101", "20240102", "20240103"],
                       "price": [95.0, 100.0, 99.0],  # 折价5% / 平价 / 折价1%
                       "seller": ["x"] * 3, "buyer": ["y"] * 3, "amount": [1] * 3, "volume": [1] * 3})
    api = _FakeAPI(get_block_trade=bt)
    ev = DS.load_corp_action_events("X.SZ", "20240101", "20240110", api, close=close)
    bd = [e for e in ev if e["kind"] == "block_discount"]
    assert len(bd) == 1 and abs(bd[0]["meta"]["discount"] - 0.05) < 1e-6, bd
    ev2 = DS.load_corp_action_events("X.SZ", "20240101", "20240110", api, close=None)  # 无参照→保守跳过
    assert not [e for e in ev2 if e["kind"] == "block_discount"]
    print("✅ test_block_discount_gating（仅折价≥3% 计入；无收盘价参照保守跳过，不再对每笔大宗都报）")


def test_pledge_holder_ratio():
    """质押口径：取大股东(持股≥5%)质押占其持股比例的最高者，小股东满仓质押被滤。"""
    idx = pd.bdate_range("2024-01-01", periods=10)
    pl = pd.DataFrame({"publish_date": ["20240102"] * 3,
                       "acc_pledged_hold_ratio": [77.0, 40.0, 100.0],   # 三个股东
                       "acc_pledge_total_ratio": [6.0, 3.0, 1.0],
                       "hold_ratio": [8.0, 7.0, 1.0]})                  # 第三个持股仅1%→滤
    api = _FakeAPI(get_stock_pledge=pl)
    s = DS.load_pledge("X.SZ", "20240101", "20240110", api, idx)
    assert abs(s.dropna().iloc[-1] - 77.0) < 1e-6, s.tail()             # 大股东最高=77%，非总股本口径6%
    print("✅ test_pledge_holder_ratio（大股东持股口径质押=77% 触发脆弱，小股东满仓质押被滤避免误报）")


def test_render_charts():
    """artifact 第五节②：六维雷达 + 阶段时间序列 SVG（纯 SVG，离线）。"""
    diag = {"stage": "S1", "p_trend": 1.2, "gap_pct": 40, "sync": 55, "cog_f": 50, "par_f": 60, "fast_loop": 70}
    svg = R._radar_svg(diag)
    assert "<svg" in svg and "polygon" in svg, svg[:80]
    df = pd.DataFrame({"score": [10, 20, 50, 80], "stage": ["S0", "S1", "S2", "S2"],
                       "conviction": [0, 0, 1, 1], "in_test": [False, False, True, False]})
    tl = R.render_timeline_svg(df)
    assert "<svg" in tl and "polyline" in tl, tl[:80]
    print("✅ test_render_charts（六维雷达 + 阶段时间序列 SVG）")


def test_plain_text_dynamic():
    """artifact P1#3/#9/#10：_plain_text 六阶段读实际读数（非静态模板）+ 把握度 + 监控清单。"""
    d = {"stage": "S0", "stage_name": "S0 中性", "loop_type": "none", "gap_pct": 62.5, "sync": 33.9,
         "cog_f": 50, "fb_long": 48, "fb_neg": 0, "conviction": 0, "in_test": False, "fragile": False,
         "confidence": 0.29, "confidence_band": "低", "position_advice": "observe"}
    t = rx._plain_text(d)
    assert "GAP=62.5" in t and "Sync=33.9" in t and "背离" in t, t     # 读数进了结论（中芯案例）
    assert "把握低" in t and "confidence=0.29" in t, t                  # 把握度进了结论
    assert "接下来盯" in t, t                                           # 监控清单
    d1 = dict(d, stage="S1", stage_name="S1 萌芽", conviction=2, in_test=True)
    t1 = rx._plain_text(d1)
    assert "2 次" in t1 and "第 3 次考验" in t1, t1                     # S1 也引用 conviction/in_test
    print("✅ test_plain_text_dynamic（六阶段读数插值 + 把握度 + 监控清单，非静态模板）")


def test_score_breakdown():
    r = pd.Series({"Sync": 80, "FB_long": 60, "P": 1.5, "CogF": 50, "ParF": 50})
    b = rx._score_breakdown(r)
    assert abs(rx._score(r) - (b["sync"] + b["fb_long"] + b["trend"] + b["dual"])) < 0.2
    print("✅ test_score_breakdown（score 四分量可拆解且加总一致）")


def test_real_data_optional():
    """真实数据：无 SDK/凭证/配额自动跳过（不判失败）。"""
    try:
        out = B.maintain_daily(symbols=["300750.SZ"], date="20260710")
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if any(k in msg for k in ("无法导入", "panda_data", "pip", "凭证", "500009", "单日总流量",
                                   "200103", "权限", "ServiceError", "504", "网络", "DNS", "超时", "Timeout")):
            print(f"⏭️  test_real_data_optional 跳过（无 SDK/凭证/配额）：{msg[:50]}")
            return
        raise
    stock = out[out["result_type"] == B.RESULT_STOCK]
    if stock.empty:
        print("⏭️  test_real_data_optional：无结果（非交易日/停牌）")
        return
    assert {"trade_date", "build_id", "target_id"} <= set(out.columns)
    print(f"✅ test_real_data_optional（真实 {len(stock)} 只：{stock.iloc[0]['ts_code']}={stock.iloc[0]['result_value']}）")


if __name__ == "__main__":
    test_state_machine_boom()
    test_negative_reflexivity()
    test_no_false_S3_on_flat()
    test_conviction_on_test()
    test_cogf_decay_twilight()
    test_fast_loop_type()
    test_pledge_fragile()
    test_pit_as_of()
    test_empty_and_missing_cols()
    test_short_history_guard()
    test_validate_input()
    test_run_direct_and_output()
    test_render()
    test_block_discount_gating()
    test_pledge_holder_ratio()
    test_render_charts()
    test_plain_text_dynamic()
    test_score_breakdown()
    test_real_data_optional()
    print("\n🎉 全部测试通过")
