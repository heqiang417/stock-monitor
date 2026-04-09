#!/usr/bin/env python3
"""
方向7：基于 direction6 半程结果的精修搜索。

目标：
1. 聚焦 direction6 已验证的优胜区域，避免继续全空间大海捞针
2. 优先寻找三阶段都 >55% 且样本足够的稳健组合
3. 重点验证：BB1.00、TOP500/800、H5、SL3.5、TP4.0/4.5、VOL1.1~1.3、RSI19/20

输出：
- data/results/explore_direction_7_refine_winners.json
"""
import json
import os
import multiprocessing as mp
from datetime import datetime
from itertools import product

from explore_direction_4_expand_test_samples import (
    BASELINE,
    DB,
    load_data,
    log,
    qualifies,
    run_backtest,
    sqlite3,
)

OUTPUT = os.path.join(os.path.dirname(DB), 'results', 'explore_direction_7_refine_winners.json')
MIN_TRADES = 30
MIN_WIN_RATE = 55.0
WORKERS = max(1, int(os.environ.get('D7_WORKERS', '4')))
BATCH_SIZE = max(8, int(os.environ.get('D7_BATCH_SIZE', '24')))


def build_combos():
    combos = []

    # A. 主搜索：完全围绕 direction6 已验证的赢家区域
    for rsi_thresh, bb_mult, vol_mult, top_n, hold_days, stop_loss, take_profit in product(
        [19, 20],
        [1.00, 1.01],
        [1.1, 1.2, 1.3],
        [500, 800],
        [5, 7],
        [3.0, 3.5],
        [4.0, 4.5],
    ):
        # 方向7 主判断：H5+SL3.5+TP4.x 是主区，H7/SL3.0/BB1.01 只作为边界验证
        combos.append({
            'family': 'refine_main',
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

    # B. 稳健优先种子：用 direction6 半程已出现的强组合做邻域微调
    seeds = [
        {'family': 'refine_seed', 'rsi_thresh': 19, 'bb_mult': 1.00, 'vol_mult': 1.1, 'weak_thresh': 0.5, 'use_weak': False, 'top_n': 500, 'stop_loss': 3.5, 'take_profit': 4.0, 'max_hold_days': 5},
        {'family': 'refine_seed', 'rsi_thresh': 19, 'bb_mult': 1.00, 'vol_mult': 1.1, 'weak_thresh': 0.5, 'use_weak': False, 'top_n': 800, 'stop_loss': 3.5, 'take_profit': 4.0, 'max_hold_days': 5},
        {'family': 'refine_seed', 'rsi_thresh': 20, 'bb_mult': 1.00, 'vol_mult': 1.1, 'weak_thresh': 0.5, 'use_weak': False, 'top_n': 800, 'stop_loss': 3.5, 'take_profit': 4.0, 'max_hold_days': 5},
        {'family': 'refine_seed', 'rsi_thresh': 20, 'bb_mult': 1.00, 'vol_mult': 1.2, 'weak_thresh': 0.5, 'use_weak': False, 'top_n': 800, 'stop_loss': 3.5, 'take_profit': 4.0, 'max_hold_days': 5},
        {'family': 'refine_seed', 'rsi_thresh': 20, 'bb_mult': 1.00, 'vol_mult': 1.3, 'weak_thresh': 0.5, 'use_weak': False, 'top_n': 800, 'stop_loss': 3.5, 'take_profit': 4.0, 'max_hold_days': 5},
    ]
    combos.extend(seeds)

    # C. 少量验证轻弱市过滤是否能降低 spread（只保留极小搜索面）
    for rsi_thresh, vol_mult, top_n, hold_days, take_profit, weak_thresh in product(
        [19, 20],
        [1.1, 1.2],
        [500, 800],
        [5],
        [4.0, 4.5],
        [0.3, 0.4],
    ):
        combos.append({
            'family': 'refine_light_weak_probe',
            'rsi_thresh': rsi_thresh,
            'bb_mult': 1.00,
            'vol_mult': vol_mult,
            'weak_thresh': weak_thresh,
            'use_weak': True,
            'top_n': top_n,
            'stop_loss': 3.5,
            'take_profit': take_profit,
            'max_hold_days': hold_days,
        })

    seen = set()
    deduped = []
    for c in combos:
        key = tuple(sorted(c.items()))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
    return deduped


def phase_summary(row):
    r = row['results']
    t, v, te = r['train']['metrics'], r['val']['metrics'], r['test']['metrics']
    return t, v, te


def sample_ok(metrics):
    return metrics['total_trades'] >= MIN_TRADES


def stable_spread(t, v, te):
    rates = [t['positive_rate'], v['positive_rate'], te['positive_rate']]
    return round(max(rates) - min(rates), 2)


def score(row):
    t, v, te = phase_summary(row)
    sample_all_ok = int(sample_ok(t) and sample_ok(v) and sample_ok(te))
    win_all_ok = int(t['positive_rate'] > MIN_WIN_RATE and v['positive_rate'] > MIN_WIN_RATE and te['positive_rate'] > MIN_WIN_RATE)
    min_trades = min(t['total_trades'], v['total_trades'], te['total_trades'])
    min_win = min(t['positive_rate'], v['positive_rate'], te['positive_rate'])
    spread = stable_spread(t, v, te)
    return (
        sample_all_ok,
        win_all_ok,
        min_win,
        min_trades,
        -spread,
        te['sharpe'],
    )


def classify(row):
    t, v, te = phase_summary(row)
    sample_all_ok = sample_ok(t) and sample_ok(v) and sample_ok(te)
    win_all_ok = t['positive_rate'] > MIN_WIN_RATE and v['positive_rate'] > MIN_WIN_RATE and te['positive_rate'] > MIN_WIN_RATE

    if sample_all_ok and win_all_ok:
        return 'qualified'
    if te['total_trades'] < MIN_TRADES:
        return 'rejected_low_test_samples'
    if not sample_all_ok:
        return 'rejected_low_phase_samples'
    if not win_all_ok:
        return 'rejected_low_win_rate'
    return 'rejected_other'


def _build_label(params):
    return (
        f"{params['family']}_RSI{params['rsi_thresh']}_BB{params['bb_mult']:.2f}"
        f"_VOL{params['vol_mult']}_TOP{params['top_n']}"
        f"_{'weak'+str(params['weak_thresh']) if params['use_weak'] else 'noWeak'}"
        f"_SL{params['stop_loss']}_TP{params['take_profit']}_H{params['max_hold_days']}"
    )


def _run_one_batch(args):
    batch, db_path = args
    conn = sqlite3.connect(db_path, timeout=120)
    sym_data, sym_scores_pit, weak_maps = load_data(conn)
    conn.close()

    results = []
    for params in batch:
        label = _build_label(params)
        try:
            res = run_backtest(sym_data, sym_scores_pit, weak_maps, params)
            row = {
                'name': label,
                'params': params,
                'results': res,
                'qualified': qualifies(res),
            }
            row['classification'] = classify(row)
            row['refine_score'] = score(row)
            row['stability_spread'] = stable_spread(*phase_summary(row))
            results.append(row)
        except Exception as e:
            results.append({'name': label, 'params': params, 'error': str(e)})
    return results


def main():
    combos = build_combos()
    log(f'方向7精修：共 {len(combos)} 个组合待测 | workers={WORKERS} | batch={BATCH_SIZE}')

    batches = [combos[i:i + BATCH_SIZE] for i in range(0, len(combos), BATCH_SIZE)]
    all_results = []
    qualified = []
    promising = []

    if WORKERS <= 1:
        for i, batch in enumerate(batches, 1):
            log(f'批次 {i}/{len(batches)}')
            for row in _run_one_batch((batch, DB)):
                if 'error' in row:
                    log(f"  ERROR: {row['name']} => {row['error']}")
                    continue
                all_results.append(row)
                t, v, te = phase_summary(row)
                log(
                    f"  {row['name']} | train {t['total_trades']} / {t['positive_rate']:.2f}% | "
                    f"val {v['total_trades']} / {v['positive_rate']:.2f}% | "
                    f"test {te['total_trades']} / {te['positive_rate']:.2f}% | "
                    f"spread {row['stability_spread']:.2f} | test Sharpe {te['sharpe']:.2f}"
                )
                if row['classification'] == 'qualified':
                    qualified.append(row)
                elif te['total_trades'] >= MIN_TRADES:
                    promising.append(row)
    else:
        with mp.Pool(processes=WORKERS) as pool:
            for done_idx, batch_rows in enumerate(pool.imap_unordered(_run_one_batch, [(b, DB) for b in batches]), 1):
                log(f'完成批次 {done_idx}/{len(batches)}')
                for row in batch_rows:
                    if 'error' in row:
                        log(f"  ERROR: {row['name']} => {row['error']}")
                        continue
                    all_results.append(row)
                    t, v, te = phase_summary(row)
                    log(
                        f"  {row['name']} | train {t['total_trades']} / {t['positive_rate']:.2f}% | "
                        f"val {v['total_trades']} / {v['positive_rate']:.2f}% | "
                        f"test {te['total_trades']} / {te['positive_rate']:.2f}% | "
                        f"spread {row['stability_spread']:.2f} | test Sharpe {te['sharpe']:.2f}"
                    )
                    if row['classification'] == 'qualified':
                        qualified.append(row)
                    elif te['total_trades'] >= MIN_TRADES:
                        promising.append(row)

    all_results.sort(key=score, reverse=True)
    qualified.sort(key=score, reverse=True)
    promising.sort(key=score, reverse=True)

    payload = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'goal': 'direction7 refine winners from direction6 half-run',
        'baseline': BASELINE,
        'rules': {
            'min_trades_each_phase': MIN_TRADES,
            'min_positive_rate_each_phase': MIN_WIN_RATE,
            'focus_zone': {
                'rsi': [19, 20],
                'bb': [1.00, 1.01],
                'vol': [1.1, 1.2, 1.3],
                'top_n': [500, 800],
                'hold_days': [5, 7],
                'stop_loss': [3.0, 3.5],
                'take_profit': [4.0, 4.5],
            },
        },
        'qualified_count': len(qualified),
        'promising_count': len(promising),
        'top20': all_results[:20],
        'qualified': qualified[:30],
        'promising': promising[:30],
        'all_results_count': len(all_results),
    }

    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    log(f'结果已保存: {OUTPUT}')
    log(f'qualified: {len(qualified)} | promising: {len(promising)}')


if __name__ == '__main__':
    main()
