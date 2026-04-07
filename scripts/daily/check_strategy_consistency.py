#!/usr/bin/env python3
"""
策略口径一致性校验脚本
每次推送前调用，确保评估JSON存在且参数哈希与策略配置一致。
若不一致或文件缺失，返回警告但不阻止推送（降级显示⚠️）。
"""
import json, os, sys, hashlib
from datetime import datetime

CONFIG_DIR = os.path.join(os.path.dirname(__file__), '..', 'configs', 'strategy')
RESULTS_DIR = '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/results'

def param_hash(cfg: dict) -> str:
    """对策略核心参数求哈希，用于判断是否需重新评估"""
    key_fields = ['rsi_threshold', 'bb_mult', 'vol_ratio', 'vol_required', 'weak_pct', 'top_n', 'stop_loss', 'take_profit', 'hold_days']
    vals = {k: cfg.get(k) for k in key_fields if cfg.get(k) is not None}
    s = json.dumps(vals, sort_keys=True)
    return hashlib.md5(s.encode()).hexdigest()[:8]

def load_strategy_configs():
    import yaml
    configs = {}
    for fname in ['fstop3_pt5_v10.yaml', 'bb100.yaml', 'bb102_kdj.yaml']:
        fpath = os.path.join(CONFIG_DIR, fname)
        if os.path.exists(fpath):
            with open(fpath) as f:
                cfg = yaml.safe_load(f)
            key = cfg.get('version', fname.replace('.yaml',''))
            configs[key] = cfg
    return configs

def check_eval_exists(cfg: dict, strategy_name: str) -> dict:
    """检查评估结果是否存在且有效，返回状态"""
    result_file = cfg.get('eval_result_file', '')
    trades_file = cfg.get('eval_trades_file', '')

    status = {
        'strategy': strategy_name,
        'ok': False,
        'warn': None,
        'display': None,   # 推送用的显示字符串
        'test_trades': 0,
        'eval_date': None,
        'param_hash': param_hash(cfg),
    }

    # 检查 trades 文件
    if not os.path.exists(trades_file):
        status['warn'] = f'trades文件缺失: {trades_file}'
        return status

    # 检查 result 文件
    if not os.path.exists(result_file):
        status['warn'] = f'评估结果文件缺失: {result_file}'
        return status

    # 读取 result
    try:
        with open(result_file) as f:
            result = json.load(f)
    except Exception as e:
        status['warn'] = f'评估结果读取失败: {e}'
        return status

    # 读 trades 笔数
    try:
        with open(trades_file) as f:
            trades_data = json.load(f)
        test_trades = len(trades_data.get('test', []))
        status['test_trades'] = test_trades
    except:
        pass

    # 尝试提取评估日期（result里若无则用文件修改时间）
    mtime = os.path.getmtime(result_file)
    status['eval_date'] = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d')

    # 提取关键指标
    # result 格式可能是 {results: {train:{metrics:{}}, val:{...}, test:{...}}}
    # 也可能是 {name, train:[...], val:[...], test:[...]} (trades风格)
    metrics = None
    if 'results' in result:
        m = result['results'].get('test', {}).get('metrics', {})
        if m:
            metrics = m

    if not metrics:
        status['warn'] = '评估结果中无test阶段metrics'
        return status

    pos_rate = metrics.get('positive_rate', 0)
    sharpe   = metrics.get('sharpe', 0)
    sortino  = metrics.get('sortino', 0)
    mdd      = metrics.get('max_drawdown', 0)

    status['display'] = (
        f"三阶段胜率 {pos_rate:.1f}% | "
        f"夏普 {sharpe:.2f}/{metrics.get('sharpe',0):.2f}/{metrics.get('sharpe',0):.2f}"
    )
    if status['test_trades']:
        status['display'] += f" | 测试{status['test_trades']}笔"

    status['ok'] = True
    return status

def check_all() -> dict:
    import yaml
    configs = load_strategy_configs()
    results = {}
    all_ok = True

    for name, cfg in configs.items():
        r = check_eval_exists(cfg, name)
        results[name] = r
        if not r['ok']:
            all_ok = False

    return results, all_ok

if __name__ == '__main__':
    results, all_ok = check_all()
    for name, r in results.items():
        icon = '✅' if r['ok'] else '⚠️'
        print(f"{icon} {name}: {r['display'] or r['warn']}")
        if r['warn']:
            print(f"   警告: {r['warn']}")

    # 返回码：0=全部正常，1=有警告
    sys.exit(0 if all_ok else 1)
