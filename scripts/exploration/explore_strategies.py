#!/usr/bin/env python3
"""
策略探索脚本 - 6个方向批量测试
"""
import sys, json, time, os
sys.path.insert(0, os.path.dirname(__file__))
from strategy_evaluator import StrategyEvaluator, Metrics28

OUTPUT = '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/results/strategy_exploration_20260331.json'

def fmt_result(phase_data):
    """格式化单阶段结果"""
    if not phase_data:
        return "N/A"
    m = Metrics28.from_dict(phase_data) if isinstance(phase_data, dict) else phase_data
    return f"{m.positive_rate}%/{m.total_trades}笔 | 夏普={m.sharpe} | 回撤={m.max_drawdown}% | 盈亏比={m.profit_loss_ratio}"

def run_explore(ev, name, signal_fn, hold_days, params, weak_thresh=0.7, top_n=200, top_n_per_day=0, score_fn=None):
    """运行单个策略评测"""
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    t0 = time.time()
    result = ev.evaluate(
        signal_fn, hold_days=hold_days, params=params,
        use_weak=True, weak_threshold=weak_thresh,
        top_n=top_n, top_n_per_day=top_n_per_day, score_fn=score_fn
    )
    elapsed = time.time() - t0

    summary = {}
    for phase in ['train', 'val', 'test']:
        if phase in result:
            m = result[phase]
            d = m.to_dict()
            summary[phase] = d
            print(f"  {phase:>5}: {m.positive_rate}%/{m.total_trades}笔 | 夏普={m.sharpe} | 回撤={m.max_drawdown}% | 一致性={m.three_phase_consistency} | 盈亏比={m.profit_loss_ratio}")

    # 合格判断
    test_m = summary.get('test', {})
    train_m = summary.get('train', {})
    val_m = summary.get('val', {})
    passed = (
        all(train_m.get('positive_rate', 0) > 55 for _ in [1]) and
        val_m.get('positive_rate', 0) > 55 and
        test_m.get('positive_rate', 0) > 55 and
        test_m.get('total_trades', 0) >= 30 and
        test_m.get('three_phase_consistency', 0) == 1 and
        test_m.get('sharpe', 0) > 1 and
        test_m.get('max_drawdown', 100) < 50 and
        test_m.get('profit_loss_ratio', 0) > 1
    )
    # 三阶段都>55%
    three_phase_ok = (
        train_m.get('positive_rate', 0) > 55 and
        val_m.get('positive_rate', 0) > 55 and
        test_m.get('positive_rate', 0) > 55
    )
    print(f"  耗时: {elapsed:.1f}s | 合格: {'✅' if passed else '❌'} | 三阶段>55%: {'✅' if three_phase_ok else '❌'}")

    return {
        'name': name,
        'signal': signal_fn.__name__,
        'params': params,
        'hold_days': hold_days,
        'weak_threshold': weak_thresh,
        'top_n': top_n,
        'top_n_per_day': top_n_per_day,
        'phases': summary,
        'passed': passed,
        'three_phase_ok': three_phase_ok,
        'elapsed': round(elapsed, 1)
    }


def main():
    ev = StrategyEvaluator()
    ev.load_data()

    all_results = []
    sections = {}

    # ============================================================
    # 探索1: RSI阈值 + BB组合（保持弱市70%、TOP200、hold7）
    # ============================================================
    print("\n" + "#"*70)
    print("# 探索1: RSI阈值 + BB触底组合")
    print("#"*70)
    sec1 = []
    for rsi_t in [15, 18, 22, 25]:
        name = f"RSI<{rsi_t}+BB触底 | 弱市>70% | TOP200 | hold7"
        r = run_explore(ev, name, ev.signal_rsi_bb, 7, {'rsi_thresh': rsi_t})
        sec1.append(r)
    sections['explore1_rsi_bb'] = sec1
    all_results.extend(sec1)

    # ============================================================
    # 探索2: 弱市阈值变化（保持RSI<20+BB、TOP200、hold7）
    # ============================================================
    print("\n" + "#"*70)
    print("# 探索2: 弱市阈值变化")
    print("#"*70)
    sec2 = []
    for wt in [0.6, 0.65, 0.75, 0.8]:
        name = f"RSI<20+BB触底 | 弱市>{int(wt*100)}% | TOP200 | hold7"
        r = run_explore(ev, name, ev.signal_rsi_bb, 7, {'rsi_thresh': 20}, weak_thresh=wt)
        sec2.append(r)
    sections['explore2_weak_threshold'] = sec2
    all_results.extend(sec2)

    # ============================================================
    # 探索3: 持有天数（保持RSI<20+BB、弱市70%、TOP200）
    # ============================================================
    print("\n" + "#"*70)
    print("# 探索3: 持有天数变化")
    print("#"*70)
    sec3 = []
    for hd in [3, 5, 14, 20]:
        name = f"RSI<20+BB触底 | 弱市>70% | TOP200 | hold{hd}"
        r = run_explore(ev, name, ev.signal_rsi_bb, hd, {'rsi_thresh': 20})
        sec3.append(r)
    sections['explore3_hold_days'] = sec3
    all_results.extend(sec3)

    # ============================================================
    # 探索4: TOP N变化（保持RSI<20+BB、弱市70%、hold7）
    # ============================================================
    print("\n" + "#"*70)
    print("# 探索4: TOP N变化")
    print("#"*70)
    sec4 = []
    for tn in [100, 300, 500]:
        name = f"RSI<20+BB触底 | 弱市>70% | TOP{tn} | hold7"
        r = run_explore(ev, name, ev.signal_rsi_bb, 7, {'rsi_thresh': 20}, top_n=tn)
        sec4.append(r)
    sections['explore4_top_n'] = sec4
    all_results.extend(sec4)

    # ============================================================
    # 探索5: 复合信号+BB（保持弱市70%、TOP200、hold7）
    # ============================================================
    print("\n" + "#"*70)
    print("# 探索5: 复合信号+BB")
    print("#"*70)
    sec5 = []

    # RSI<20+BB+MACD>0 — 需要自定义信号函数
    def signal_rsi_bb_macd(sd, i, params):
        rsi = sd['rsi'][i]
        if __import__('numpy').isnan(rsi) or rsi >= 20 or rsi < 10:
            return False
        bb = sd['bb_lower'][i]; cl = sd['close'][i]
        if __import__('numpy').isnan(bb) or cl > bb * 1.02:
            return False
        mh = sd['macd_hist'][i]
        return not __import__('numpy').isnan(mh) and mh > 0

    name = "RSI<20+BB+MACD>0 | 弱市>70% | TOP200 | hold7"
    r = run_explore(ev, name, signal_rsi_bb_macd, 7, {})
    sec5.append(r)

    # RSI<20+BB+放量
    def signal_rsi_bb_vol(sd, i, params):
        rsi = sd['rsi'][i]
        if __import__('numpy').isnan(rsi) or rsi >= 20 or rsi < 10:
            return False
        bb = sd['bb_lower'][i]; cl = sd['close'][i]
        if __import__('numpy').isnan(bb) or cl > bb * 1.02:
            return False
        vol = sd['volume'][i]
        if i < 5: return False
        avg_vol = __import__('numpy').nanmean(sd['volume'][max(0,i-5):i])
        return avg_vol > 0 and vol > avg_vol * 1.5

    name = "RSI<20+BB+放量 | 弱市>70% | TOP200 | hold7"
    r = run_explore(ev, name, signal_rsi_bb_vol, 7, {})
    sec5.append(r)

    # RSI<20+BB+MA5≥MA10
    def signal_rsi_bb_ma(sd, i, params):
        rsi = sd['rsi'][i]
        if __import__('numpy').isnan(rsi) or rsi >= 20 or rsi < 10:
            return False
        bb = sd['bb_lower'][i]; cl = sd['close'][i]
        if __import__('numpy').isnan(bb) or cl > bb * 1.02:
            return False
        ma5 = sd['ma5'][i]; ma10 = sd['ma10'][i]
        return not __import__('numpy').isnan(ma5) and not __import__('numpy').isnan(ma10) and ma5 >= ma10

    name = "RSI<20+BB+MA5≥MA10 | 弱市>70% | TOP200 | hold7"
    r = run_explore(ev, name, signal_rsi_bb_ma, 7, {})
    sec5.append(r)

    sections['explore5_composite'] = sec5
    all_results.extend(sec5)

    # ============================================================
    # 探索6: top_n_per_day 排序测试（RSI<20+BB、hold7）
    # ============================================================
    print("\n" + "#"*70)
    print("# 探索6: top_n_per_day 排序测试")
    print("#"*70)
    sec6 = []

    # 基本面打分排序函数
    def make_fund_sort_fn(rank):
        """创建按基本面排名排序的函数，rank=1最高分，rank=2次高..."""
        def fund_sort_fn(sd, i, sym, scores_list):
            # 返回负分数（因为按降序排，负数越大越靠前）
            # 这里用RSI越低越好 + 基本面分越高越好
            rsi_val = sd['rsi'][i]
            rsi_score = -rsi_val if not __import__('numpy').isnan(rsi_val) else 0
            # 基本面分
            latest_score = 0
            d = sd['dates'][i]
            for ad, sc in reversed(scores_list):
                if ad <= d:
                    latest_score = sc
                    break
            # 混合排序：基本面分权重 + RSI越低越好
            return latest_score * 10 + rsi_score
        return fund_sort_fn

    for top_per in [1, 2, 3, 5]:
        name = f"RSI<20+BB | 弱市>70% | TOP200 | hold7 | 每天Top{top_per}基本面"
        r = run_explore(ev, name, ev.signal_rsi_bb, 7, {'rsi_thresh': 20},
                       top_n_per_day=top_per, score_fn=make_fund_sort_fn(top_per))
        sec6.append(r)
    sections['explore6_sorting'] = sec6
    all_results.extend(sec6)

    # ============================================================
    # 汇总
    # ============================================================
    print("\n" + "="*70)
    print("  汇总: 合格策略筛选")
    print("  标准: 三阶段>55% | 测试>30笔 | 一致性=1 | 夏普>1 | 回撤<50% | 盈亏比>1")
    print("="*70)

    passed = [r for r in all_results if r['passed']]
    three_phase_passed = [r for r in all_results if r['three_phase_ok']]

    print(f"\n全部合格（6项标准）: {len(passed)}/{len(all_results)}")
    for r in sorted(passed, key=lambda x: x['phases']['test']['sharpe'], reverse=True):
        t = r['phases']['test']
        print(f"  ✅ {r['name']}")
        print(f"     test: {t['positive_rate']}%/{t['total_trades']}笔 | 夏普={t['sharpe']} | 回撤={t['max_drawdown']}% | 盈亏比={t['profit_loss_ratio']}")

    print(f"\n三阶段正率>55%: {len(three_phase_passed)}/{len(all_results)}")
    for r in sorted(three_phase_passed, key=lambda x: x['phases']['test']['sharpe'], reverse=True):
        t = r['phases']['test']
        flag = "✅" if r['passed'] else "⚠️"
        print(f"  {flag} {r['name']}")
        print(f"     test: {t['positive_rate']}%/{t['total_trades']}笔 | 夏普={t['sharpe']} | 回撤={t['max_drawdown']}% | 盈亏比={t['profit_loss_ratio']}")

    # 保存
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    output_data = {
        'date': '2026-03-31',
        'baseline': 'RSI<20+BB触底 | 弱市>70% | TOP200 | hold7',
        'total_tested': len(all_results),
        'passed_count': len(passed),
        'three_phase_ok_count': len(three_phase_passed),
        'sections': sections,
        'passed_strategies': [r['name'] for r in passed],
        'all_results': all_results
    }
    with open(OUTPUT, 'w') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存: {OUTPUT}")


if __name__ == '__main__':
    main()
