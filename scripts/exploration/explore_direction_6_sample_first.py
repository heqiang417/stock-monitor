#!/usr/bin/env python3
"""
样本优先的下一轮 Fstop3 策略搜索。

目标：
1. 先解决 test 样本量不足问题（硬约束：train/val/test 都 >= 30）
2. 在样本达标的前提下，再看三阶段胜率与稳定性
3. 避免继续堆更强过滤，改为“宽入口 + 轻过滤 + 稳定性排序”

输出：
- data/results/explore_direction_6_sample_first.json
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

OUTPUT = os.path.join(os.path.dirname(DB), 'results', 'explore_direction_6_sample_first.json')
MIN_TRADES = 30
MIN_WIN_RATE = 55.0
WORKERS = max(1, int(os.environ.get('D6_WORKERS', '1')))


def _build_label(params):
    return (
        f"{params['family']}_RSI{params['rsi_thresh']}_BB{params['bb_mult']:.2f}"
        f"_VOL{params['vol_mult']}_TOP{params['top_n'] if params['top_n'] > 0 else 'ALL'}"
        f"_{'weak'+str(params['weak_thresh']) if params['use_weak'] else 'noWeak'}"
        f"_SL{params['stop_loss']}_TP{params['take_profit']}_H{params['max_hold_days']}"
    )


def _run_one_batch(args):
    """每个worker进程：独立加载数据，独立处理一个batch。"""
    batch, db_path = args
    # worker进程内加载数据，避免父进程fork后内存膨胀
    conn = sqlite3.connect(db_path, timeout=120)
    sym_data, sym_scores_pit, weak_maps = load_data(conn)
    conn.close()
    results = []
    for params in batch:
        label = _build_label(params)
        try:
            res = run_backtest(sym_data, sym_scores_pit, weak_maps, params)
            t = res['train']['metrics']
            v = res['val']['metrics']
            te = res['test']['metrics']
            rates = [t['positive_rate'], v['positive_rate'], te['positive_rate']]
            spread = round(max(rates) - min(rates), 2)
            results.append({
                'name': label,
                'params': params,
                'results': res,
                'qualified': qualifies(res),
                'stability_spread': spread,
            })
        except Exception as e:
            results.append({'name': label, 'params': params, 'error': str(e)})
    return results


def build_combos():
    combos = []

    # A. 宽入口：去掉弱市硬过滤，优先恢复样本
    for rsi_thresh, bb_mult, vol_mult, top_n, hold_days, stop_loss, take_profit in product(
        [19, 20, 21, 22],
        [1.00, 1.01, 1.02, 1.03],
        [0.0, 1.1, 1.2, 1.3],
        [300, 500, 800, 0],
        [5, 7, 10],
        [2.5, 3.0, 3.5],
        [4.0, 4.5, 5.0, 5.5],
    ):
        # 避免明显过宽、意义不大的极端组合
        if top_n == 0 and vol_mult == 0.0 and bb_mult >= 1.03 and rsi_thresh >= 22:
            continue
        combos.append({
            'family': 'sample_first_no_weak',
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

    # B. 轻弱市过滤：保留弱市逻辑，但显著放宽阈值
    for rsi_thresh, bb_mult, vol_mult, weak_thresh, top_n, hold_days, stop_loss, take_profit in product(
        [19, 20, 21],
        [1.01, 1.02, 1.03],
        [0.0, 1.1, 1.2],
        [0.3, 0.4],
        [500, 800, 0],
        [5, 7, 10],
        [2.5, 3.0],
        [4.5, 5.0, 5.5],
    ):
        combos.append({
            'family': 'sample_first_light_weak',
            'rsi_thresh': rsi_thresh,
            'bb_mult': bb_mult,
            'vol_mult': vol_mult,
            'weak_thresh': weak_thresh,
            'use_weak': True,
            'top_n': top_n,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'max_hold_days': hold_days,
        })

    # C. 稳态中庸邻域：不追求极致胜率，优先找三阶段接近的方案
    seed_variants = [
        {'family': 'stability_seed', 'rsi_thresh': 20, 'bb_mult': 1.02, 'vol_mult': 1.1, 'weak_thresh': 0.4, 'use_weak': False, 'top_n': 500, 'stop_loss': 3.0, 'take_profit': 5.0, 'max_hold_days': 7},
        {'family': 'stability_seed', 'rsi_thresh': 20, 'bb_mult': 1.01, 'vol_mult': 1.2, 'weak_thresh': 0.4, 'use_weak': False, 'top_n': 500, 'stop_loss': 3.0, 'take_profit': 4.5, 'max_hold_days': 7},
        {'family': 'stability_seed', 'rsi_thresh': 21, 'bb_mult': 1.02, 'vol_mult': 1.1, 'weak_thresh': 0.3, 'use_weak': True,  'top_n': 800, 'stop_loss': 2.5, 'take_profit': 5.0, 'max_hold_days': 7},
        {'family': 'stability_seed', 'rsi_thresh': 19, 'bb_mult': 1.03, 'vol_mult': 0.0, 'weak_thresh': 0.4, 'use_weak': False, 'top_n': 300, 'stop_loss': 3.0, 'take_profit': 5.5, 'max_hold_days': 10},
    ]
    combos.extend(seed_variants)

    # 去重
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
        min_trades,
        min_win,
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
        f"_VOL{params['vol_mult']}_TOP{params['top_n'] if params['top_n'] > 0 else 'ALL'}"
        f"_{'weak'+str(params['weak_thresh']) if params['use_weak'] else 'noWeak'}"
        f"_SL{params['stop_loss']}_TP{params['take_profit']}_H{params['max_hold_days']}"
    )


def _run_one(params):
    label = _build_label(params)
    res = run_backtest(_GLOBALS['sym_data'], _GLOBALS['sym_scores_pit'], _GLOBALS['weak_maps'], params)
    row = {
        'name': label,
        'params': params,
        'results': res,
        'qualified': qualifies(res),
    }
    row['classification'] = classify(row)
    row['sample_first_score'] = score(row)
    row['stability_spread'] = stable_spread(*phase_summary(row))
    return row



def main():
    log('连接数据库...')
    conn = sqlite3.connect(DB, timeout=120)
    sym_data, sym_scores_pit, weak_maps = load_data(conn)
    conn.close()

    combos = build_combos()
    log(f'共 {len(combos)} 个组合待测 | workers={WORKERS}')

    all_results = []
    qualified = []
    promising_sample_first = []

    if WORKERS <= 1:
        _init_worker(sym_data, sym_scores_pit, weak_maps)
        for idx, params in enumerate(combos, 1):
            label = _build_label(params)
            log(f'[{idx}/{len(combos)}] {label}')
            try:
                row = _run_one(params)
            except Exception as e:
                log(f'  ERROR: {e}')
                continue

            all_results.append(row)
            t, v, te = phase_summary(row)
            log(
                f"  train {t['total_trades']} / {t['positive_rate']:.2f}% | "
                f"val {v['total_trades']} / {v['positive_rate']:.2f}% | "
                f"test {te['total_trades']} / {te['positive_rate']:.2f}% | "
                f"spread {row['stability_spread']:.2f} | test Sharpe {te['sharpe']:.2f}"
            )

            if row['classification'] == 'qualified':
                qualified.append(row)
            elif te['total_trades'] >= MIN_TRADES:
                promising_sample_first.append(row)
    else:
        future_to_meta = {}
        with ProcessPoolExecutor(max_workers=WORKERS, initializer=_init_worker, initargs=(sym_data, sym_scores_pit, weak_maps)) as ex:
            for idx, params in enumerate(combos, 1):
                label = _build_label(params)
                future = ex.submit(_run_one, params)
                future_to_meta[future] = (idx, label)

            done_count = 0
            for future in as_completed(future_to_meta):
                idx, label = future_to_meta[future]
                done_count += 1
                log(f'[{done_count}/{len(combos)}] done #{idx}: {label}')
                try:
                    row = future.result()
                except Exception as e:
                    log(f'  ERROR: {e}')
                    continue

                all_results.append(row)
                t, v, te = phase_summary(row)
                log(
                    f"  train {t['total_trades']} / {t['positive_rate']:.2f}% | "
                    f"val {v['total_trades']} / {v['positive_rate']:.2f}% | "
                    f"test {te['total_trades']} / {te['positive_rate']:.2f}% | "
                    f"spread {row['stability_spread']:.2f} | test Sharpe {te['sharpe']:.2f}"
                )

                if row['classification'] == 'qualified':
                    qualified.append(row)
                elif te['total_trades'] >= MIN_TRADES:
                    promising_sample_first.append(row)

    all_results.sort(key=score, reverse=True)
    qualified.sort(key=score, reverse=True)
    promising_sample_first.sort(key=score, reverse=True)

    payload = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'goal': 'sample-first search: restore enough test trades first, then optimize three-phase stability',
        'baseline': BASELINE,
        'rules': {
            'min_trades_each_phase': MIN_TRADES,
            'min_positive_rate_each_phase': MIN_WIN_RATE,
            'primary_sort': ['all_phases_sample_ok', 'all_phases_win_rate_ok', 'min_trades', 'min_win_rate', 'stability_spread', 'test_sharpe'],
        },
        'qualified_count': len(qualified),
        'promising_sample_first_count': len(promising_sample_first),
        'top20': all_results[:20],
        'qualified': qualified[:30],
        'promising_sample_first': promising_sample_first[:30],
        'all_results_count': len(all_results),
    }

    with open(OUTPUT, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    log(f'结果已保存: {OUTPUT}')
    log(f'qualified: {len(qualified)} | promising_sample_first: {len(promising_sample_first)}')


if __name__ == '__main__':
    main()
