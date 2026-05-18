import importlib.util
import pathlib
import sys
import types
from datetime import date

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
JOINQUANT_DIR = REPO_ROOT / "scripts" / "joinquant"


def install_jqdata_stub():
    module = types.ModuleType("jqdata")
    module.g = types.SimpleNamespace()

    def _placeholder(*args, **kwargs):
        raise RuntimeError("jqdata stub function should be monkeypatched in tests")

    module.set_benchmark = lambda *args, **kwargs: None
    module.set_option = lambda *args, **kwargs: None
    module.run_daily = lambda *args, **kwargs: None
    module.set_order_cost = lambda *args, **kwargs: None
    module.OrderCost = lambda **kwargs: kwargs
    module.log = types.SimpleNamespace(info=lambda *args, **kwargs: None)
    module.get_trades = lambda: {}
    module.get_current_data = _placeholder
    module.get_all_securities = _placeholder
    module.get_security_info = _placeholder
    module.get_fundamentals = _placeholder
    module.query = _placeholder
    module.valuation = types.SimpleNamespace(code=None, circulating_market_cap=None)
    module.get_bars = _placeholder
    sys.modules["jqdata"] = module
    return module


@pytest.fixture
def jqdata_stub(monkeypatch):
    module = install_jqdata_stub()
    yield module
    sys.modules.pop("jqdata", None)


def load_script(name: str):
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, JOINQUANT_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fixed_hold_uses_trading_days_and_sells_on_next_trading_close(jqdata_stub):
    script = load_script("jq_bb100")

    script.g.hold_info = {
        "AAA": {
            "buy_date": date(2026, 4, 1),
            "buy_price": 10.0,
            "trading_days": 7,
        }
    }
    script.g.hold_days = 7

    sell_calls = []
    script.order_target = lambda stock, amount: sell_calls.append((stock, amount))

    class Position:
        closeable_amount = 100
        avg_cost = 10.0

    context = types.SimpleNamespace(
        current_dt=types.SimpleNamespace(date=lambda: date(2026, 4, 10)),
        portfolio=types.SimpleNamespace(positions={"AAA": Position()}),
    )

    script.sell_stocks(context)

    assert sell_calls == [("AAA", 0)]
    assert "AAA" not in script.g.hold_info


def test_fixed_hold_does_not_sell_before_next_trading_day(jqdata_stub):
    script = load_script("jq_bb102_kdj")

    script.g.hold_info = {
        "AAA": {
            "buy_date": date(2026, 4, 1),
            "buy_price": 10.0,
            "trading_days": 6,
        }
    }
    script.g.hold_days = 7

    sell_calls = []
    script.order_target = lambda stock, amount: sell_calls.append((stock, amount))

    class Position:
        closeable_amount = 100
        avg_cost = 10.0

    context = types.SimpleNamespace(
        current_dt=types.SimpleNamespace(date=lambda: date(2026, 4, 9)),
        portfolio=types.SimpleNamespace(positions={"AAA": Position()}),
    )

    script.sell_stocks(context)

    assert sell_calls == []
    assert script.g.hold_info["AAA"]["trading_days"] == 7


def test_tp45_stop_profit_uses_trading_days_counter(jqdata_stub):
    script = load_script("jq_tp45")

    script.g.hold_info = {
        "AAA": {
            "buy_date": date(2026, 4, 1),
            "buy_price": 10.0,
            "trading_days": 1,
        }
    }
    script.g.hold_days = 5
    script.g.stop_loss = 0.035
    script.g.take_profit = 0.045

    sell_calls = []
    script.order_target = lambda stock, amount: sell_calls.append((stock, amount))
    script.get_current_data = lambda: {"AAA": types.SimpleNamespace(last_price=10.5)}

    class Position:
        closeable_amount = 100
        avg_cost = 10.0

    context = types.SimpleNamespace(
        current_dt=types.SimpleNamespace(date=lambda: date(2026, 4, 3)),
        portfolio=types.SimpleNamespace(positions={"AAA": Position()}),
    )

    script.sell_stocks(context)

    assert sell_calls == [("AAA", 0)]
    assert "AAA" not in script.g.hold_info


def test_stock_pool_config_matches_strategy_index(jqdata_stub):
    bb100 = load_script("jq_bb100")
    bb102 = load_script("jq_bb102_kdj")
    tp45 = load_script("jq_tp45")

    for module in (bb100, bb102, tp45):
        module.g = types.SimpleNamespace()
        module.run_daily = lambda *args, **kwargs: None
        module.set_benchmark = lambda *args, **kwargs: None
        module.set_option = lambda *args, **kwargs: None
        module.set_order_cost = lambda *args, **kwargs: None
        module.OrderCost = lambda **kwargs: kwargs

    bb100.initialize(types.SimpleNamespace())
    bb102.initialize(types.SimpleNamespace())
    tp45.initialize(types.SimpleNamespace())

    assert bb100.g.top_n == 300
    assert bb102.g.top_n == 500
    assert tp45.g.top_n == 800
    assert bb100.g.weak_pct == pytest.approx(0.70)
    assert bb102.g.weak_pct == pytest.approx(0.70)
    assert tp45.g.weak_pct == pytest.approx(0.40)


def test_tp45_buy_skips_star_board_without_protection_limit_and_too_small_orders(jqdata_stub):
    script = load_script("jq_tp45")
    script.g.buy_list = ["688599.XSHG", "000001.XSHE", "600436.XSHG"]
    script.g.max_positions = 5
    script.g.hold_info = {}

    order_calls = []
    script.order_value = lambda stock, cash: order_calls.append((stock, cash))
    script.get_current_data = lambda: {
        "688599.XSHG": types.SimpleNamespace(day_open=120.0, last_price=120.0),
        "000001.XSHE": types.SimpleNamespace(day_open=10.0, last_price=10.0),
        "600436.XSHG": types.SimpleNamespace(day_open=250.0, last_price=250.0),
    }

    context = types.SimpleNamespace(
        current_dt=types.SimpleNamespace(date=lambda: date(2026, 4, 3)),
        portfolio=types.SimpleNamespace(positions={}, available_cash=30000.0),
    )

    script.buy_stocks(context)

    assert order_calls == [("000001.XSHE", pytest.approx(30000.0))]
    assert set(script.g.hold_info) == {"000001.XSHE"}
    assert script.g.hold_info["000001.XSHE"]["buy_price"] == 10.0
