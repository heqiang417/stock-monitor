#!/usr/bin/env python3
"""
方向8：基于方向7结果的收敛搜索。

目标：
1. 固定方向7已验证的核心参数（BB1.00, TOP800, H5, SL3.5, TP4.0）
2. 围绕"轻弱市过滤+RSI阈值+VOL"三个维度继续细化
3. 重点验证：RSI18~20细分、VOL1.0~1.3细分、弱市阈值0.2~0.5细分

输出：
- data/results/explore_direction_8_converge.json
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

OUTPUT = os.path.join(os.path.dirname(DB), 'results', 'explore_direction_8_converge.json')
MIN_TRADES = 30
MIN_WIN_RATE = 55.0
WORKERS = max(1, int(os.environ.get('D8_WORKERS', '1')))
BATCH_SIZE = max(8, int(os.environ.get('D8_BATCH_SIZE', '24')))


def build_combos():
    combos = []

    # === 核心主线：固定 TOP800/H5/SL3.5/TP4.0，RSI/VOL/弱市 三个维度细化 ===
    for rsi_thresh, bb_mult, vol_mult, weak_thresh, use_weak in product(
        [18, 19, 20],        # RSI 细到 18（之前只有 19/20）
        [1.00],              # BB1.00 已验证为稳
        [1.0, 1.1, 1.2, 1.3],  # VOL 扩展到 1.0（原方向7没有 VOL1.0）
        [0.2, 0.3, 0.4, 0.5],  # 弱市阈值全段探针（之前只探了 0.3/0.4）
        [False, True],       # 有/无弱市过滤都验证
    ):
        combos.append({
            'family': 'core_fixed',
            'rsi_thresh': rsi_thresh,
            'bb_mult': bb_mult,
            'vol_mult': vol_mult,
            'weak_thresh': weak_thresh,
            'use_weak': use_weak,
            'top_n': 800,       # 固定 TOP800（样本量最优）
            'stop_loss': 3.5,   # 固定 SL3.5
            'take_profit': 4.0,  # 固定 TP4.0
            'max_hold_days': 5,  # 固定 H5
        })

    # === 少量 TOP500 对照：确认 TOP800 vs TOP500 差异 ===
    for rsi_thresh, vol_mult, weak_thresh, use_weak in product(
        [19, 20],
        [1.1, 1.2],
        [0.3, 0.4],
        [True],
    ):
        combos.append({
            'family': 'top500_ctrl',
            'rsi_thresh': rsi_thresh,
            'bb_mult': 1.00,
            'vol_mult': vol_mult,
            'weak_thresh': weak_thresh,
            'use_weak': use_weak,
            'top_n': 500,
            'stop_loss': 3.5,
            'take_profit': 4.0,
            'max_hold_days': 5,
        })

    # === TP 探针：确认 TP4.0 vs TP4.5 vs TP5.0 ===
    for rsi_thresh, vol_mult, weak_thresh, use_weak, take_profit in product(
        [19, 20],
        [1.1, 1.2],
        [0.3, 0.4],
        [True],
        [4.0, 4.5, 5.0],
    ):
        combos.append({
            'family': 'tp_probe',
            'rsi_thresh': rsi_thresh,
            'bb_mult': 1.00,
            'vol_mult': vol_mult,
            'weak_thresh': weak_thresh,
            'use_weak': use_weak,
            'top_n': 800,
            'stop_loss': 3.5,
            'take_profit': take_profit,
            'max_hold_days': 5,
        })

    # 去重
    seen = set()
    deduped = []
    for c in combos:
        key = tuple(sorted(c.items()))
        if key not in seen:
            seen.add(key)
            deduped.append(c)
    return deduped


def stable_spread(t, v, te):
    rates = [t['positive_rate'], v['positive_rate'], te['positive_rate']]
    return round(max(rates) - min(rates), 2)


def make_name(params):
    weak = f"_weak{int(params['weak_thresh']*10)}" if params['use_weak'] else "_noWeak"
    return (f"{params['family']}_RSI{int(params['rsi_thresh'])}_"
            f"BB{params['bb_mult']:.2f}_VOL{params['vol_mult']}_TOP{int(params['top_n'])}"
            f"{weak}_SL{params['stop_loss']}_TP{params['take_profit']}_H{int(params['max_hold_days'])}")


def score(row):
    r = row['results']
    t, v, te = r['train']['metrics'], r['val']['metrics'], r['test']['metrics']
    if not (t['positive_rate'] >= MIN_WIN_RATE and v['positive_rate'] >= MIN_WIN_RATE and te['positive_rate'] >= MIN_WIN_RATE):
        return None
    if t['total_trades'] < MIN_TRADES or v['total_trades'] < MIN_TRADES or te['total_trades'] < MIN_TRADES:
        return None
    spread = stable_spread(t, v, te)
    return {
        'name': row['name'],
        'train_wr': round(t['positive_rate'], 2),
        'val_wr': round(v['positive_rate'], 2),
        'test_wr': round(te['positive_rate'], 2),
        'train_trades': t['total_trades'],
        'val_trades': v['total_trades'],
        'test_trades': te['total_trades'],
        'spread': spread,
        'sharpe': round(te['sharpe'], 2),
    }


def run_batch(batch, sym_data, sym_scores_pit, weak_maps):
    results = []
    for params in batch:
        name = make_name(params)
        try:
            phase_results = run_backtest(sym_data, sym_scores_pit, weak_maps, params)
            row = {
                'name': name,
                'params': dict(params),
                'results': phase_results,
            }
            row['qualified'] = qualifies(phase_results)
            row['classification'] = 'qualified' if row['qualified'] else 'promising'
            row['stability_spread'] = stable_spread(
                phase_results['train']['metrics'],
                phase_results['val']['metrics'],
                phase_results['test']['metrics'],
            )
            sc = score(row)
            results.append((row, sc))
        except Exception as e:
            log(f"   ERROR {name}: {e}")
    return results


def main():
    t0 = datetime.now()
    combos = build_combos()
    total = len(combos)
    log(f"方向8收敛搜索：共 {total} 个组合 | workers={WORKERS} | batch={BATCH_SIZE}")

    conn = sqlite3.connect(DB)
    log("加载数据...")
    sym_data, sym_scores_pit, weak_maps = load_data(conn)
    conn.close()

    batches = [combos[i:i+BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
    n_batches = len(batches)

    all_rows = []
    qualified_count = 0
    promising_count = 0

    for batch_idx, batch in enumerate(batches, 1):
        log(f"批次 {batch_idx}/{n_batches}")
        batch_results = run_batch(batch, sym_data, sym_scores_pit, weak_maps)

        for row, sc in batch_results:
            all_rows.append(row)
            if sc is not None:
                qualified_count += 1
                log(f"  ✅ {sc['name']} | train {sc['train_trades']}/{sc['train_wr']}% | "
                    f"val {sc['val_trades']}/{sc['val_wr']}% | test {sc['test_trades']}/{sc['test_wr']}% | "
                    f"spread {sc['spread']} | test Sharpe {sc['sharpe']}")
            else:
                m = row['results']
                t, v, te = m['train']['metrics'], m['val']['metrics'], m['test']['metrics']
                promising = min(t['positive_rate'], v['positive_rate'], te['positive_rate']) >= 50.0
                if promising:
                    promising_count += 1
                log(f"  {'⭐' if promising else '  '} {row['name']} | "
                    f"train {t['total_trades']}/{t['positive_rate']:.2f}% | "
                    f"val {v['total_trades']}/{v['positive_rate']:.2f}% | "
                    f"test {te['total_trades']}/{te['positive_rate']:.2f}%")


    # 排序输出
    all_rows.sort(key=lambda r: (
        r.get('qualified', False),
        -(min(r['results']['train']['metrics']['positive_rate'],
              r['results']['val']['metrics']['positive_rate'],
              r['results']['test']['metrics']['positive_rate']) if r.get('qualified') else 0),
        r.get('stability_spread', 999)
    ), reverse=True)

    top20 = all_rows[:20]
    qualified = [r for r in all_rows if r.get('qualified')]
    promising = [r for r in all_rows if not r.get('qualified') and
                 min(r['results']['train']['metrics']['positive_rate'],
                     r['results']['val']['metrics']['positive_rate'],
                     r['results']['test']['metrics']['positive_rate']) >= 50.0]

    out = {
        'generated_at': datetime.now().isoformat(),
        'goal': '方向8：收敛搜索，围绕方向7验证的核心区域（TOP800/H5/SL3.5/TP4.0）细化 RSI/VOL/弱市阈值',
        'baseline': BASELINE,
        'rules': {'min_trades': MIN_TRADES, 'min_win_rate': MIN_WIN_RATE},
        'total_combos': total,
        'qualified_count': qualified_count,
        'promising_count': promising_count,
        'top20': top20,
        'qualified': qualified,
        'promising': promising,
        'all_results_count': len(all_rows),
    }

    with open(OUTPUT, 'w') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    elapsed = (datetime.now() - t0).total_seconds()
    log(f"完成！共 {total} 组合 | qualified {qualified_count} | promising {promising_count} | 耗时 {elapsed:.1f}s")
    log(f"结果已保存: {OUTPUT}")


if __name__ == '__main__':
    mp.set_start_method('spawn', force=True)
    main()
