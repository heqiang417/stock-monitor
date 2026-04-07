#!/usr/bin/env python3
"""
根据最新 Fstop3 eval JSON 自动生成回测报告。
核心数字只读 eval JSON，不允许手填。
"""
import json
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVAL = PROJECT_ROOT / "data/results/fstop3_v10_framework_eval.json"
DEFAULT_REPORT = PROJECT_ROOT / "docs/strategy/Fstop3_pt5_v10/backtest_report.md"

METRIC_ROWS = [
    ("total_trades", "总交易笔数"),
    ("positive_rate", "正收益率(%)"),
    ("avg_return", "平均收益率(%)"),
    ("median_return", "中位数收益率(%)"),
    ("max_return", "最高收益率(%)"),
    ("min_return", "最低收益率(%)"),
    ("hit_stocks", "命中股票数"),
    ("sharpe", "夏普比率"),
    ("sortino", "索提诺比率"),
    ("max_drawdown", "最大回撤(%)"),
    ("volatility", "波动率"),
    ("downside_volatility", "下行波动率"),
    ("profit_loss_ratio", "盈亏比"),
    ("avg_win", "平均盈利(%)"),
    ("avg_loss", "平均亏损(%)"),
    ("max_consec_wins", "最大连赢"),
    ("max_consec_losses", "最大连亏"),
    ("annual_return", "年化收益率(%)"),
    ("calmar", "卡尔马比率"),
    ("recovery_factor", "恢复因子"),
    ("breakeven_wr", "盈亏平衡胜率(%)"),
    ("expectancy", "期望值(%)"),
    ("avg_hold_days", "平均持仓天数"),
    ("train_test_ratio", "训练/测试收益比"),
    ("three_phase_consistency", "三阶段一致性(%)"),
]


def _fmt(v):
    if isinstance(v, float):
        s = f"{v:.4f}".rstrip("0").rstrip(".")
        return s if s else "0"
    return str(v)


def generate_report_from_eval(eval_path: str = str(DEFAULT_EVAL), report_path: str = str(DEFAULT_REPORT)):
    eval_p = Path(eval_path)
    report_p = Path(report_path)
    if not eval_p.exists():
        raise FileNotFoundError(f"eval 文件不存在: {eval_p}")

    payload = json.loads(eval_p.read_text(encoding="utf-8"))
    results = payload.get("results", {})
    phases = payload.get("phases", {})
    params = payload.get("params", {})

    # 校验必须字段
    for p in ["train", "val", "test"]:
        if p not in results or "metrics" not in results[p]:
            raise ValueError(f"eval 缺少阶段指标: {p}")

    train = results["train"]["metrics"]
    val = results["val"]["metrics"]
    test = results["test"]["metrics"]

    lines = [
        "# Fstop3_pt5 v10 回测报告",
        "",
        f"> 自动生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> 评估数据源：`{eval_p}`",
        f"> 交易数据源：`{payload.get('source_trades', '')}`",
        "",
        "## 策略参数（来自最新 eval）",
        "",
        f"- RSI 阈值：<{params.get('rsi', '')}",
        f"- 布林触底：{params.get('bb', '')}",
        f"- 放量倍数：{params.get('vol', '')}x",
        f"- 弱市阈值：>{params.get('weak', '')*100 if isinstance(params.get('weak'), (int, float)) else params.get('weak', '')}% 个股低于 MA20",
        f"- 基本面股票池：TOP{params.get('top', '')}",
        f"- 卖出模式：{params.get('sell', '')}（止损{params.get('stop_loss', '')}% / 止盈{params.get('take_profit', '')}% / 最长持有{params.get('hold', '')}天）",
        f"- 交易成本：{params.get('cost', '')}%",
        "",
        "## 三阶段核心指标",
        "",
        "| 阶段 | 时间范围 | 笔数 | 正率 | 夏普 |",
        "|---|---|---:|---:|---:|",
        f"| train | {phases.get('train', ['', ''])[0]} ~ {phases.get('train', ['', ''])[1]} | {train.get('total_trades', 0)} | {_fmt(train.get('positive_rate', 0))}% | {_fmt(train.get('sharpe', 0))} |",
        f"| val | {phases.get('val', ['', ''])[0]} ~ {phases.get('val', ['', ''])[1]} | {val.get('total_trades', 0)} | {_fmt(val.get('positive_rate', 0))}% | {_fmt(val.get('sharpe', 0))} |",
        f"| test | {phases.get('test', ['', ''])[0]} ~ {phases.get('test', ['', ''])[1]} | {test.get('total_trades', 0)} | {_fmt(test.get('positive_rate', 0))}% | {_fmt(test.get('sharpe', 0))} |",
        "",
        "## 28项指标（train / val / test）",
        "",
        "| 指标 | train | val | test |",
        "|---|---:|---:|---:|",
    ]

    for key, label in METRIC_ROWS:
        lines.append(
            f"| {label} | {_fmt(train.get(key, 0))} | {_fmt(val.get(key, 0))} | {_fmt(test.get(key, 0))} |"
        )

    lines += [
        "",
        "---",
        "",
        "说明：本报告由脚本自动生成，所有数字来自 eval JSON 真源。",
    ]

    report_p.parent.mkdir(parents=True, exist_ok=True)
    report_p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(report_p)


if __name__ == "__main__":
    out = generate_report_from_eval()
    print(f"report updated: {out}")
