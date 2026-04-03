# 每日选股历史记录

> L1 历史推送：查看过往选股结果

---

每日选股结果 JSON 保存在本目录，按日期命名（如 `2026-03-31.json`）。

## 查看方式

```bash
# 列出所有日期
ls *.json | sort

# 查看某日结果
cat 2026-03-31.json | python3 -m json.tool
```

## 字段说明

```json
{
  "date": "2026-03-31",           // 信号日
  "strategy": "Fstop3_pt5_v10",  // 策略版本
  "market": {
    "weak_pct": 81.6,             // 大盘弱市比例（MA20下方%）
    "total": 5165,               // 当日有MA20的股票数
    "below": 4214,               // MA20下方股票数
    "trigger": true               // 是否满足弱市触发条件（≥50%）
  },
  "picks": [                      // 入选股票列表
    {
      "symbol": "sz002096",
      "name": "易普力",
      "price": 11.53,
      "rsi": 13.6,
      "boll_lower": 11.67,
      "vol_today": 204636.0,
      "vol_ma5": 129180.0,
      "vol_ratio": 1.58,
      "fund_score": 50.6
    }
  ]
}
```

---

**注意**：历史记录代表策略当天扫描结果，非推荐买入——请结合策略手册自行判断。
