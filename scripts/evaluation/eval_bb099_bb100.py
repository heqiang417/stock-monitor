#!/usr/bin/env python3
"""
BB0.99无KDJ 和 BB1.00无KDJ 完整28项指标评估
策略：RSI<20 + price <= boll_lower * multiplier + 弱市70% + TOP300 + 7天持有 + 无KDJ
三阶段：训练2021-01-01~2024-06-30 / 验证2024-07-01~2025-07-31 / 测试2025-08-01~2026-03-31
"""
import sys, os, json, time
import numpy as np

sys.path.insert(0, '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/scripts')
from strategy_evaluator import StrategyEvaluator, calc_metrics, calc_phase_consistency

# ========== 配置 ==========
PROJECT = '/home/heqiang/.openclaw/workspace/stock-monitor-app-py'
DB = f'{PROJECT}/data/stock_data.db'
OUTPUT_DIR = f'{PROJECT}/data/results'
os.makedirs(OUTPUT_DIR, exist_ok=True)

TOP_N = 300
HOLD_DAYS = 7
RSI_THRESH = 20
BB_CONFIGS = [
    ('BB0.99无KDJ', 0.99),
    ('BB1.00无KDJ', 1.00),
]

PHASES = {
    'train': ('2021-01-01', '2024-06-30'),
    'val':   ('2024-07-01', '2025-07-31'),
    'test':  ('2025-08-01', '2026-03-31'),
}

print("=" * 70)
print("BB0.99/BB1.00 无KDJ 完整28项指标评估")
print(f"TOP{TOP_N} | {HOLD_DAYS}天持有 | RSI<{RSI_THRESH} | 弱市70%")
print(f"阶段: train={PHASES['train']} | val={PHASES['val']} | test={PHASES['test']}")
print("=" * 70)

# ========== 加载数据 ==========
t0 = time.time()
ev = StrategyEvaluator(DB)
ev.load_data()
print(f"数据加载完成: {time.time()-t0:.1f}s")

# ========== 定义BB信号函数 ==========
def make_bb_signal(multiplier):
    def signal(sd, i, params):
        rsi_thresh = params.get('rsi_thresh', 20)
        rsi = sd['rsi'][i]
        # RSI过滤
        if np.isnan(rsi) or rsi >= rsi_thresh or rsi < 10:
            return False
        # BB过滤: price <= boll_lower * multiplier
        bb = sd['bb_lower'][i]
        cl = sd['close'][i]
        if np.isnan(bb) or np.isnan(cl):
            return False
        return cl <= bb * multiplier
    return signal

# ========== 评估 ==========
categories = {
    '基础指标（7）': ['total_trades','positive_rate','avg_return','median_return','max_return','min_return','hit_stocks'],
    '风险指标（5）': ['sharpe','max_drawdown','volatility','downside_volatility','sortino'],
    '交易质量（8）': ['win_rate','profit_loss_ratio','avg_win','avg_loss','max_win','max_loss','max_consec_win','max_consec_loss'],
    '效率指标（5）': ['annual_return','calmar','recovery_factor','break_even_wr','expectancy'],
    '稳定性（3）': ['train_test_ratio','three_phase_consistency','avg_hold_days'],
}

all_results = {}

for name, mult in BB_CONFIGS:
    print(f"\n{'='*70}")
    print(f"策略: {name} (BB multiplier={mult})")
    print("=" * 70)
    
    signal_fn = make_bb_signal(mult)
    params = {'rsi_thresh': RSI_THRESH}
    
    result = ev.evaluate(
        signal_fn=signal_fn,
        hold_days=HOLD_DAYS,
        params=params,
        use_weak=True,
        weak_threshold=0.7,
        top_n=TOP_N,
        phases=PHASES,
        sell_mode='fixed_hold'
    )
    
    # 打印28项指标
    for cat, keys in categories.items():
        print(f"\n{cat}")
        print(f"{'指标':<25} {'训练':>12} {'验证':>12} {'测试':>12}")
        print("-" * 65)
        for k in keys:
            vals = []
            for p in ['train', 'val', 'test']:
                if p in result:
                    vals.append(str(getattr(result[p], k)))
                else:
                    vals.append('-')
            print(f"  {k:<23} {vals[0]:>12} {vals[1]:>12} {vals[2]:>12}")
    
    # 保存结果
    output_name = 'bb099_full_28metrics' if mult == 0.99 else 'bb100_full_28metrics'
    output_path = os.path.join(OUTPUT_DIR, f'{output_name}.json')
    
    data = {
        'name': name,
        'strategy': f'RSI<{RSI_THRESH} + price<=BB_lower*{mult} + 弱市70% + TOP{TOP_N} + {HOLD_DAYS}天持有 + 无KDJ',
        'bb_multiplier': mult,
        'date': time.strftime('%Y-%m-%d %H:%M'),
        'config': {
            'top_n': TOP_N,
            'hold_days': HOLD_DAYS,
            'rsi_threshold': RSI_THRESH,
            'weak_market': '>70% stocks < MA20',
            'pit_delay': '按财报类型(Q1=30/H1=62/Q3=31/年报=120)',
            'cost': '0.30% (0.15%单边x2)',
            'sell_mode': 'T+1固定持有',
            'kdj': '无过滤'
        },
        'phases': PHASES,
        'per_phase': {p: result[p].to_dict() for p in result}
    }
    
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存: {output_path}")
    
    all_results[name] = {
        'result': result,
        'path': output_path,
        'bb_mult': mult
    }

# ========== 汇总检查 ==========
print("\n" + "=" * 70)
print("通过标准检查")
print("=" * 70)
print(f"通过标准: 三阶段正收益率>55% & 胜率>50% & 测试笔数>=30")
print()

pass_notification = []
for name, info in all_results.items():
    r = info['result']
    test = r.get('test')
    train = r.get('train')
    val = r.get('val')
    
    test_pos = test.positive_rate if test else 0
    test_trades = test.total_trades if test else 0
    train_pos = train.positive_rate if train else 0
    val_pos = val.positive_rate if val else 0
    test_wr = test.win_rate if test else 0
    
    all_three_pos = (train_pos > 55) and (val_pos > 55) and (test_pos > 55)
    win_rate_ok = test_wr > 50
    test_trades_ok = test_trades >= 30
    
    passed = all_three_pos and win_rate_ok and test_trades_ok
    
    print(f"\n【{name}】")
    print(f"  训练正收益率: {train_pos:.2f}% {'✓' if train_pos > 55 else '✗'}")
    print(f"  验证正收益率: {val_pos:.2f}% {'✓' if val_pos > 55 else '✗'}")
    print(f"  测试正收益率: {test_pos:.2f}% {'✓' if test_pos > 55 else '✗'}")
    print(f"  测试胜率: {test_wr:.2f}% {'✓' if test_wr > 50 else '✗'}")
    print(f"  测试笔数: {test_trades} {'✓' if test_trades >= 30 else '✗'}")
    print(f"  三阶段全部>55%: {all_three_pos}")
    print(f"  → {'✅ 通过' if passed else '❌ 不通过'}")
    
    if passed:
        pass_notification.append(name)

print(f"\n通过策略: {pass_notification if pass_notification else '无'}")
print(f"总耗时: {time.time()-t0:.1f}s")
