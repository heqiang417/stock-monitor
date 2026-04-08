#!/usr/bin/env python3
"""
【DEPRECATED】历史生产脚本，已不再作为当前官方入口。

当前唯一官方生产入口：
- scripts/daily/daily_pick_combined.py

保留原因：
- 作为 BB1.00 单策略历史版本参考
- 便于回溯旧推送逻辑

每日选股 - BB1.00 策略（v1）
策略条件：大盘弱市70% + 个股RSI<20 + 收盘价≤布林带下轨×1.00 + 放量1.5倍 + T+1开盘买入 + 7天固定持有
核心理念：固定3%止损 + 5%止盈，条件单由用户自行设置

用法: python3 daily_pick_v10.py [--date 2026-04-01] [--push] [--wait]
"""
import sqlite3, json, subprocess, os, argparse, time
from datetime import datetime, timedelta

parser = argparse.ArgumentParser()
parser.add_argument('--date', default=None, help='选股日期（默认今天）')
parser.add_argument('--push', action='store_true', help='推送飞书卡片')
parser.add_argument('--wait', action='store_true', help='数据不足时等待重试')
args = parser.parse_args()

DB_PATH = os.environ.get('STOCK_DB',
    '/home/heqiang/.openclaw/workspace/stock-monitor-app-py/data/stock_data.db')
READY_FLAG = '/tmp/stock_data_ready.flag'
TODAY = datetime.now().strftime('%Y-%m-%d')
MIN_STOCKS = 4000

db = sqlite3.connect(DB_PATH)
db.execute('PRAGMA journal_mode=WAL')

# === 确定日期 ===
if args.date:
    latest = args.date
else:
    latest = TODAY
    if args.wait:
        waited = 0
        max_wait = 180
        while waited < max_wait:
            ready_date = None
            try:
                with open(READY_FLAG) as f:
                    ready_date = f.read().strip()
            except FileNotFoundError:
                pass
            if ready_date == latest or (waited >= 1 and ready_date):
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 收到就绪信号，数据日期: {latest}")
                break
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 等待就绪信号... ({waited}/{max_wait}分钟)")
            time.sleep(60)
            waited += 1
        else:
            print(f"等待{max_wait}分钟未收到就绪信号，跳过")
            db.close()
            exit(1)
        db.close()
        db = sqlite3.connect(DB_PATH)
        db.execute('PRAGMA journal_mode=WAL')

# === 数据校验 ===
def validate_data(db, date):
    errors = []
    total = db.execute(f"SELECT COUNT(*) FROM kline_daily WHERE trade_date='{date}'").fetchone()[0]
    if total < MIN_STOCKS:
        errors.append(f"K线不足: {total}只(需>={MIN_STOCKS})")
    has_rsi = db.execute(f"SELECT COUNT(*) FROM kline_daily WHERE trade_date='{date}' AND rsi14 IS NOT NULL").fetchone()[0]
    has_bb = db.execute(f"SELECT COUNT(*) FROM kline_daily WHERE trade_date='{date}' AND boll_lower IS NOT NULL").fetchone()[0]
    has_ma20 = db.execute(f"SELECT COUNT(*) FROM kline_daily WHERE trade_date='{date}' AND ma20 IS NOT NULL").fetchone()[0]
    if has_rsi < total * 0.8:
        errors.append(f"RSI未计算: {has_rsi}/{total}")
    if has_bb < total * 0.8:
        errors.append(f"BB未计算: {has_bb}/{total}，需重算技术指标")
    fund_count = db.execute("SELECT COUNT(DISTINCT symbol) FROM financial_indicators WHERE roe IS NOT NULL").fetchone()[0]
    return errors, {"total": total, "rsi": has_rsi, "bb": has_bb, "ma20": has_ma20, "fund": fund_count}

errors, stats = validate_data(db, latest)
if errors:
    print(f"数据校验失败: {errors}")
    db.close()
    exit(1)
print(f"数据校验通过 ({latest}): K线{stats['total']} RSI{stats['rsi']} BB{stats['bb']}")

# === 大盘条件：市场宽度（个股MA20下方比例）>50% ===
m = db.execute(f"""
    SELECT COUNT(*) total,
        SUM(CASE WHEN ma20 IS NOT NULL THEN 1 ELSE 0 END) has_ma20,
        SUM(CASE WHEN ma20 IS NOT NULL AND close<ma20 THEN 1 ELSE 0 END) below
    FROM kline_daily WHERE trade_date='{latest}'
""").fetchone()
total_mkt = m[1] or 1
below = m[2] or 0
weak_pct = below / total_mkt * 100
market_ok = weak_pct >= 70
print(f"大盘弱市: {weak_pct:.1f}%个股在MA20下方，{'✅ 通过' if market_ok else '❌ 未通过'}")

# === 基本面打分（TOP300过滤） ===
fund_rows = db.execute("""
    SELECT f.symbol, f.roe, f.revenue_growth, f.profit_growth, f.gross_margin, f.debt_ratio
    FROM financial_indicators f
    INNER JOIN (SELECT symbol, MAX(report_date) d FROM financial_indicators GROUP BY symbol) t
    ON f.symbol=t.symbol AND f.report_date=t.d
""").fetchall()

def score_fundamentals(r):
    roe = r[1] or 0
    rev_g = r[2] or 0
    profit_g = r[3] or 0
    gross = r[4] or 0
    debt = r[5] if r[5] is not None else 100
    roe_score = min(max(roe / 30 * 30, 0), 30)
    rev_score = min(max((rev_g + 20) / 60 * 20, 0), 20)
    profit_score = min(max((profit_g + 20) / 60 * 20, 0), 20)
    gross_score = min(max(gross / 60 * 15, 0), 15)
    debt_score = min(max((100 - debt) / 100 * 15, 0), 15)
    return round(roe_score + rev_score + profit_score + gross_score + debt_score, 1)

fund = {r[0]: score_fundamentals(r) for r in fund_rows}
top300 = {sym for sym, _ in sorted(fund.items(), key=lambda x: -x[1])[:300]}
print(f"基本面TOP300: 已加载 {len(top300)} 只")

# === 第一步：找 RSI<18 + BB触底 的候选股 ===
# BB触底：close <= boll_lower * 1.00（触及或穿透布林下轨）
candidates = db.execute(f"""
    SELECT symbol, close, rsi14, boll_lower
    FROM kline_daily
    WHERE trade_date = '{latest}'
      AND rsi14 < 20
      AND boll_lower IS NOT NULL
      AND close IS NOT NULL
      AND close <= boll_lower * 1.00
    ORDER BY rsi14 ASC
""").fetchall()
print(f"RSI<20 + BB1.00触底候选: {len(candidates)} 只")

if not candidates:
    picks = []
else:
    sym_list = [c[0] for c in candidates]
    sym_placeholders = ','.join(f'"{s}"' for s in sym_list)

    # 第二步：获取最近5天成交量（用于计算5日均量）
    # 只查候选股，减少数据量
    cutoff = (datetime.strptime(latest, '%Y-%m-%d') - timedelta(days=30)).strftime('%Y-%m-%d')
    vol_rows = db.execute(f"""
        SELECT symbol, trade_date, volume
        FROM kline_daily
        WHERE symbol IN ({sym_placeholders})
          AND trade_date <= '{latest}'
          AND trade_date >= '{cutoff}'
        ORDER BY symbol, trade_date DESC
    """).fetchall()

    # 按symbol分组，取最近5条
    from collections import defaultdict
    vol_by_sym = defaultdict(list)
    for sym, td, vol in vol_rows:
        if len(vol_by_sym[sym]) < 5:
            vol_by_sym[sym].append(vol)

    # 第三步：计算5日均量，筛选放量1.5x
    picks = []
    for sym, close, rsi, bb in candidates:
        vols = vol_by_sym.get(sym, [])
        if len(vols) < 2:
            continue
        vol_ma5 = sum(vols) / len(vols)
        if vol_ma5 <= 0:
            continue
        vol_today = vols[0]
        vol_ratio = vol_today / vol_ma5
        if vol_ratio >= 1.5:
            fs = fund.get(sym, 0)
            picks.append((sym, close, rsi, bb, vol_today, round(vol_ma5, 0), round(vol_ratio, 2), fs))

    picks.sort(key=lambda x: x[2])  # 按RSI升序
    picks = picks[:20]
    print(f"放量1.5x筛选后: {len(picks)} 只")

# === 打印结果 ===
for p in picks:
    print(f"  {p[0]} RSI={p[2]:.1f} BB={p[3]:.2f} close={p[1]:.2f} vol={p[4]:.0f}/ma5={p[5]:.0f} ratio={p[6]}x fs={p[7]:.0f}")

# === 加载股票名称（用于历史记录）===
stock_names = {}
try:
    import akshare as ak
    df = ak.stock_info_a_code_name()
    for _, row in df.iterrows():
        code = str(row['code'])
        sym = f'sh{code}' if code.startswith(('6','9')) else f'sz{code}'
        stock_names[sym] = row['name']
except:
    pass

# === 保存历史记录 ===
import os
HISTORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'reports', 'daily_picks')
os.makedirs(HISTORY_DIR, exist_ok=True)

result_record = {
    "date": latest,
    "strategy": "BB1.00_v1",
    "market": {
        "weak_pct": round(weak_pct, 1),
        "total": total_mkt,
        "below": below,
        "trigger": market_ok,
    },
    "picks": []
}

for p in picks:
    result_record["picks"].append({
        "symbol": p[0],
        "name": stock_names.get(p[0], p[0]),
        "price": round(p[1], 2),
        "rsi": round(p[2], 1),
        "boll_lower": round(p[3], 2),
        "vol_today": float(p[4]),
        "vol_ma5": float(p[5]),
        "vol_ratio": round(p[6], 2),
        "fund_score": round(p[7], 1),
    })

history_file = os.path.join(HISTORY_DIR, f"{latest}.json")
with open(history_file, 'w', encoding='utf-8') as f:
    json.dump(result_record, f, ensure_ascii=False, indent=2)
print(f"历史记录已保存: {history_file}")

# === 推送飞书 ===
if not args.push:
    print("(--push 未指定，仅输出结果)")
    db.close()
    exit(0)

def fmt(sym, close, rsi, bb, vol_today, vol_ma5, vol_r, fs):
    name = stock_names.get(sym, sym)
    return f"{name}({sym[-6:]} 收{round(close,2)} RSI{round(rsi,1)}触BB 放量{round(vol_r,1)}x)"

if picks:
    best_md = " | ".join(fmt(*p) for p in picks[:5])
    picks_md = "\n".join(fmt(*p) for p in picks)
else:
    best_md = "无候选"
    picks_md = "无满足BB1.00条件的股票，建议观望"

card = {
    "elements": [
        {"tag": "div", "text": {"tag": "lark_md",
            "content": f"**📈 每日选股 {latest} | BB1.00 v10**"}},
        {"tag": "hr"},
        {"tag": "div", "text": {"tag": "lark_md",
            "content": f"{'🟢' if market_ok else '🟥'} 大盘弱市 {'✅ 通过' if market_ok else '❌ 未通过'}（{weak_pct:.1f}%在MA20下）| 个股RSI<18 | BB触底 | 放量≥1.5x"}},
        {"tag": "div", "text": {"tag": "lark_md",
            "content": "**📋 操作建议：** T+1开盘价买入 | 条件单：🔴止损3% / 🟢止盈5% | 持有≤10天了结"}},
        {"tag": "hr"},
        {"tag": "div", "text": {"tag": "lark_md",
            "content": f"**BB1.00** 候选（{len(picks)}只）TOP5："}},
        {"tag": "div", "text": {"tag": "lark_md", "content": best_md}},
        {"tag": "hr"},
        {"tag": "div", "text": {"tag": "lark_md", "content": picks_md}},
        {"tag": "note", "elements": [{"tag": "plain_text",
            "content": f"数据: {latest} | BB1.00 | 条件单止损3%止盈5% | 不构成投资建议"}]}
    ]
}

APP_ID = os.environ.get("APP_ID_BOT2", "cli_a938ffaf9738dbc6")
APP_SECRET = os.environ.get("APP_SECRET_BOT2", "ulvmnUvH1VBlqgPq298isdQ1VFURenaR")
OPEN_ID = os.environ.get("OPEN_ID_WIFE", "ou_8822a58f429ea317ab49166d79533b0f")

r = subprocess.run(["curl","-s","-X","POST",
    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
    "-H","Content-Type: application/json",
    "-d",json.dumps({"app_id":APP_ID,"app_secret":APP_SECRET})],
    capture_output=True, text=True)
token = json.loads(r.stdout).get("tenant_access_token","")

payload = json.dumps({"receive_id":OPEN_ID,"msg_type":"interactive",
    "content":json.dumps(card,ensure_ascii=False)}, ensure_ascii=False)

with open("/tmp/daily-pick-v10-card.json","w") as f: f.write(payload)

r = subprocess.run(["curl","-s","-X","POST",
    "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
    "-H",f"Authorization: Bearer {token}",
    "-H","Content-Type: application/json",
    "-d","@/tmp/daily-pick-v10-card.json"],
    capture_output=True, text=True)
resp = json.loads(r.stdout)
if resp.get("code") == 0:
    print(f"✅ 飞书推送成功 ({len(picks)}只)")
else:
    print(f"❌ 推送失败: {resp}")

db.close()
print("完成")
