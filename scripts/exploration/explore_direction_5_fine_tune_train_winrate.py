#!/usr/bin/env python3
"""
方向5：基于 direction4 的精修搜索
目标：在样本已足够的 TOP500 / noWeak / RSI20 邻域里，重点提升 train 胜率。
"""
import json
import os
from datetime import datetime
from itertools import product

from explore_direction_4_expand_test_samples import load_data, run_backtest, qualifies, log, BASELINE, sqlite3, DB

OUTPUT = os.path.join(os.path.dirname(DB), 'results', 'explore_direction_5_fine_tune_train_winrate.json')


def score(x):
    r = x['results']
    t, v, te = r['train']['metrics'], r['val']['metrics'], r['test']['metrics']
    return (
        1 if x['qualified'] else 0,
        min(t['positive_rate'], v['positive_rate'], te['positive_rate']),
        te['total_trades'],
        te['sharpe'],
    )


def main():
    log('连接数据库...')
    conn = sqlite3.connect(DB, timeout=120)
    sym_data, sym_scores_pit, weak_maps = load_data(conn)
    conn.close()

    combos = []

    # 以最接近达标的 TOP500/noWeak/RSI20/BB1.01~1.02 为核心，精修 train 胜率
    for rsi_thresh, bb_mult, vol_mult, top_n, hold_days, stop_loss, take_profit in product(
        [19, 20, 21],
        [1.00, 1.01, 1.02],
        [0.0, 1.2, 1.5],
        [300, 500, 800],
        [5, 6, 7, 8, 10],
        [2.5, 3.0, 3.5, 4.0],
        [4.0, 4.5, 5.0, 5.5, 6.0],
    ):
        # 缩小组合空间：优先保留有希望的邻域
        if top_n == 800 and vol_mult == 0.0 and bb_mult == 1.00:
            continue
        if hold_days >= 8 and take_profit <= 4.5:
            continue
        if hold_days <= 6 and take_profit >= 5.5:
            continue
        combos.append({
            'family': 'fine_tune',
            'rsi_thresh': rsi_thresh,
            'bb_mult': bb_mult,
            'vol_mult': vol_mult,
            'weak_thresh': 0.5,
            'use_weak': False,
            'top_n': top_n,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'max_hold_days': hold_days,
        })

    # 加几组保留弱市但更宽松的对照
    for weak_thresh, hold_days, stop_loss, take_profit in product(
        [0.4, 0.5], [7, 10], [2.5, 3.0, 3.5], [4.5, 5.0, 5.5]
    ):
        combos.append({
            'family': 'fine_tune_weak',
            'rsi_thresh': 20,
            'bb_mult': 1.02,
            'vol_mult': 1.2,
            'weak_thresh': weak_thresh,
            'use_weak': True,
            'top_n': 500,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'max_hold_days': hold_days,
        })

    log(f'共 {len(combos)} 个组合待测')
    all_results = []
    qualified = []

    for idx, params in enumerate(combos, 1):
        label = (
            f"{params['family']}_RSI{params['rsi_thresh']}_BB{params['bb_mult']:.2f}"
            f"_VOL{params['vol_mult']}_TOP{params['top_n'] if params['top_n']>0 else 'ALL'}"
            f"_{'weak'+str(params['weak_thresh']) if params['use_weak'] else 'noWeak'}"
            f"_SL{params['stop_loss']}_TP{params['take_profit']}_H{params['max_hold_days']}"
        )
        log(f'[{idx}/{len(combos)}] {label}')
        try:
            res = run_backtest(sym_data, sym_scores_pit, weak_maps, params)
        except Exception as e:
            log(f'  ERROR: {e}')
            continue
        row = {'name': label, 'params': params, 'results': res, 'qualified': qualifies(res)}
        all_results.append(row)
        if row['qualified']:
            qualified.append(row)
        te = res['test']['metrics']
        tr = res['train']['metrics']
        va = res['val']['metrics']
        log(f"  train: {tr['total_trades']}笔 / WR {tr['positive_rate']:.2f}% | val: {va['total_trades']}笔 / WR {va['positive_rate']:.2f}% | test: {te['total_trades']}笔 / WR {te['positive_rate']:.2f}% / Sharpe {te['sharpe']:.2f}")

    all_results.sort(key=score, reverse=True)
    qualified.sort(key=score, reverse=True)

    payload = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'goal': 'fine tune train win-rate after solving sample-count problem',
        'baseline': BASELINE,
        'qualified_count': len(qualified),
        'top20': all_results[:20],
        'qualified': qualified[:30],
        'all_results_count': len(all_results),
    }
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    log(f'结果已保存: {OUTPUT}')
    log(f'qualified: {len(qualified)}')


if __name__ == '__main__':
    main()
