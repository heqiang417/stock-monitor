# 发布检查清单 / Release Checklist

> 用于保证：**策略更新后，代码、文档、Git、运行口径同步一致。**

更新日期：2026-04-08

---

## 适用场景

满足任一情况，就必须走这份清单：

- 新增正式策略
- 删除正式策略
- 正式策略降级为参考/历史策略
- 改策略阈值、持有规则、筛选条件
- 改 `daily_pick_combined.py` / `daily_sync.py` / cron 主链路
- 改当前官方文档口径

---

## 发布前检查

### A. 代码
- [ ] 生产脚本已更新（如 `scripts/daily/daily_pick_combined.py`）
- [ ] 若涉及评估口径，评估脚本/评估真源已同步
- [ ] 若涉及运行链路，相关脚本（如 `daily_sync.py`）已同步

### B. 文档
- [ ] `docs/strategy/STRATEGY_INDEX.md` 已更新
- [ ] `docs/ops/crontab.md` 已更新
- [ ] `docs/ops/runtime.md` 已更新（若运行方式有变化）
- [ ] `README.md` / `scripts/README.md` 已更新（若入口口径有变化）

### C. 数据与口径
- [ ] 正式策略池与当前推送口径一致
- [ ] 不合格策略未继续作为正式策略展示
- [ ] 历史/参考策略已明确标记为 reference / deprecated / archive

### D. Git
- [ ] `git status` 已检查
- [ ] 本次变更已 `commit`
- [ ] 本次变更已 `push origin main`

---

## 当前默认发布规则

### 规则 1：策略更新 = 必须联动 Git
以后凡是“正式策略更新”，默认不是只改脚本，而是必须同步完成：

1. 改代码
2. 改文档
3. commit
4. push

### 规则 2：默认 push，除非用户明确说先别推
当前协作口径：

> 只要是正式策略池、生产脚本、官方文档口径的更新，默认需要推送到 GitHub。

除非用户明确说：
- 先别 push
- 先本地试
- 先做草稿

### 规则 3：历史策略不能伪装成正式策略
- 不合格策略可以保留
- 但必须放在 `reference` / `archive` / `deprecated` 语义下
- 不允许继续出现在正式每日策略池里

---

## 推荐执行顺序

```text
策略调整
  ↓
改生产脚本 / 评估口径
  ↓
改 STRATEGY_INDEX / ops 文档
  ↓
本地验证（语法 / 关键逻辑 / git status）
  ↓
commit
  ↓
push origin main
```

---

## 当前项目官方口径（2026-04-08）

### 当前正式每日策略池
1. `BB1.00`
2. `BB1.02+KDJ`

### 当前历史/对照策略
- `Fstop3_pt5 v10`

### 当前唯一官方每日选股入口
- `scripts/daily/daily_pick_combined.py`

---

## 一句话原则

> **策略变更不算完成，直到 GitHub 上也同步完成。**
