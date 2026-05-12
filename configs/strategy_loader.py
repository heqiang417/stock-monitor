"""
策略配置加载器

从 configs/strategy/*.yaml 加载策略参数，作为唯一的参数来源。
daily_pick_combined.py 和 strategy_evaluator.py 都通过此模块读取配置。

用法:
    from configs.strategy_loader import load_all_strategies, load_strategy

    strategies = load_all_strategies()  # dict[str, dict]
    bb100 = load_strategy("bb100")      # 单个策略
"""

import os
import yaml

STRATEGY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "strategy")


def load_strategy(name: str) -> dict:
    """加载单个策略配置

    Args:
        name: 策略文件名（不含 .yaml），如 "bb100", "bb102_kdj", "tp45"

    Returns:
        策略参数字典

    Raises:
        FileNotFoundError: 配置文件不存在
    """
    path = os.path.join(STRATEGY_DIR, f"{name}.yaml")
    if not os.path.exists(path):
        raise FileNotFoundError(f"策略配置不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["_source"] = path
    return cfg


def load_all_strategies(enabled_only: bool = True) -> dict:
    """加载所有策略配置

    Args:
        enabled_only: 只返回 enabled=true 的策略

    Returns:
        dict[str, dict] — key 为 YAML 中的 name 字段
    """
    strategies = {}
    for fname in sorted(os.listdir(STRATEGY_DIR)):
        if not fname.endswith(".yaml"):
            continue
        name = fname.replace(".yaml", "")
        cfg = load_strategy(name)
        if enabled_only and not cfg.get("enabled", True):
            continue
        strategies[cfg["name"]] = cfg
    return strategies


def strategy_to_evaluator_params(cfg: dict) -> dict:
    """将 YAML 配置转换为 strategy_evaluator.evaluate() 所需的参数格式

    Returns:
        dict with keys: name, signal_fn, signal_params, hold_days
    """
    signal_params = {
        "rsi_threshold": cfg.get("rsi_threshold", 20),
        "bb_threshold": cfg.get("bb_mult", 1.02),
        "near_oversold": cfg.get("near_oversold", True),
        "weak_market_pct": cfg.get("weak_pct", 70) / 100.0,
        "fundamental_top_n": cfg.get("top_n", 500),
    }
    if cfg.get("take_profit"):
        signal_params["take_profit_pct"] = cfg["take_profit"]

    return {
        "name": cfg["name"],
        "signal_fn": cfg.get("signal_fn", "signal_rsi_bb"),
        "signal_params": signal_params,
        "hold_days": cfg.get("hold_days", 7),
    }
