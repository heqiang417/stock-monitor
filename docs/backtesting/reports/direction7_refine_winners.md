# Direction7 精修结果报告

> 生成时间：2026-04-09  
> 脚本：`scripts/exploration/explore_direction_7_refine_winners.py`

## 一句话结论

Direction7 已经把搜索从“找方向”推进到“找到一批可用候选”。

- 总组合：**229**
- Qualified：**75**
- Promising：**154**

相比 direction6 半程只筛出 26 个合格组合，direction7 的精修已经明显收敛到赢家区域。

---

## 本轮最重要发现

### 1. 真正的赢家区已经很清楚
最稳主线集中在：

- `RSI 19 / 20`
- `BB 1.00`
- `VOL 1.1 ~ 1.3`
- `TOP 500 / 800`
- `H5`
- `SL 3.5`
- `TP 4.0 / 4.5`

### 2. H5 明显优于 H7
同区域参数下，H5 在：

- train 胜率
- test 胜率
- test Sharpe
- spread 稳定性

上整体都更优。

### 3. 轻弱市过滤不是坏事
`weak 0.3 / 0.4` 并没有把策略毁掉，反而在多个组合上把 train 胜率推过 55%。

这说明后续不应该简单取消弱市过滤，而应该把它当成一个可调增强器。

### 4. TP4.0 比 TP4.5 更稳
TP4.5 在一些组合上 Sharpe 也不错，但从三阶段一致性看，TP4.0 更稳、更适合当主版本继续细化。

---

## 最值得看的 15 个组合

按“三阶段最低胜率优先，再看稳定性”排序：

| # | 组合 | train | val | test | 样本(train/val/test) | spread | test Sharpe |
|---|---|---:|---:|---:|---|---:|---:|
| 1 | `refine_main_RSI19_BB1.00_VOL1.3_TOP800_noWeak_SL3.5_TP4.0_H5` | 56.91% | 79.13% | 66.36% | 1622 / 345 / 107 | 22.22 | 2.66 |
| 2 | `refine_light_weak_probe_RSI19_BB1.00_VOL1.2_TOP800_weak0.4_SL3.5_TP4.0_H5` | 56.89% | 77.96% | 65.81% | 1851 / 372 / 117 | 21.07 | 2.46 |
| 3 | `refine_light_weak_probe_RSI19_BB1.00_VOL1.1_TOP800_weak0.4_SL3.5_TP4.0_H5` | 56.84% | 76.23% | 67.13% | 2104 / 408 / 143 | 19.39 | 2.78 |
| 4 | `refine_main_RSI19_BB1.00_VOL1.3_TOP800_noWeak_SL3.5_TP4.0_H7` | 56.78% | 80.87% | 61.68% | 1622 / 345 / 107 | 24.09 | 1.92 |
| 5 | `refine_light_weak_probe_RSI19_BB1.00_VOL1.2_TOP500_weak0.4_SL3.5_TP4.0_H5` | 56.77% | 80.95% | 64.71% | 1122 / 231 / 68 | 24.18 | 2.44 |
| 6 | `refine_light_weak_probe_RSI19_BB1.00_VOL1.1_TOP500_weak0.4_SL3.5_TP4.0_H5` | 56.73% | 77.73% | 65.06% | 1278 / 256 / 83 | 21.00 | 2.63 |
| 7 | `refine_light_weak_probe_RSI19_BB1.00_VOL1.2_TOP800_weak0.3_SL3.5_TP4.0_H5` | 56.51% | 77.60% | 66.39% | 1874 / 375 / 119 | 21.09 | 2.60 |
| 8 | `refine_light_weak_probe_RSI19_BB1.00_VOL1.1_TOP800_weak0.3_SL3.5_TP4.0_H5` | 56.47% | 75.91% | 67.81% | 2134 / 411 / 146 | 19.44 | 2.95 |
| 9 | `refine_main_RSI20_BB1.00_VOL1.3_TOP800_noWeak_SL3.5_TP4.0_H5` | 56.46% | 78.48% | 64.23% | 1849 / 395 / 123 | 22.02 | 2.13 |
| 10 | `refine_seed_RSI20_BB1.00_VOL1.3_TOP800_noWeak_SL3.5_TP4.0_H5` | 56.46% | 78.48% | 64.23% | 1849 / 395 / 123 | 22.02 | 2.13 |
| 11 | `refine_main_RSI19_BB1.00_VOL1.2_TOP800_noWeak_SL3.5_TP4.0_H5` | 56.41% | 77.11% | 67.21% | 1888 / 380 / 122 | 20.70 | 2.72 |
| 12 | `refine_light_weak_probe_RSI19_BB1.00_VOL1.2_TOP500_weak0.3_SL3.5_TP4.0_H5` | 56.41% | 80.34% | 65.22% | 1138 / 234 / 69 | 23.93 | 2.56 |
| 13 | `refine_main_RSI19_BB1.00_VOL1.2_TOP500_noWeak_SL3.5_TP4.0_H5` | 56.36% | 79.66% | 66.67% | 1148 / 236 / 72 | 23.30 | 2.78 |
| 14 | `refine_main_RSI19_BB1.00_VOL1.2_TOP800_noWeak_SL3.5_TP4.0_H7` | 56.36% | 80.00% | 60.66% | 1888 / 380 / 122 | 23.64 | 1.92 |
| 15 | `refine_main_RSI19_BB1.00_VOL1.1_TOP800_noWeak_SL3.5_TP4.0_H5` | 56.35% | 75.48% | 68.46% | 2149 / 416 / 149 | 19.13 | 3.05 |

---

## 推荐的下一轮搜索方向

下一轮不要再回到大海捞针，而是围绕已验证核心继续收敛：

### 固定核心
- `BB = 1.00`
- `H = 5`
- `SL = 3.5`
- `TOP = 800`（主线）
- `TP = 4.0`（主线）

### 继续细化的变量
- `RSI = 19 / 20`（必要时探到 18）
- `VOL = 1.1 / 1.2 / 1.3`
- `weak = off / 0.3 / 0.4`
- `TOP500` 作为对照组保留少量探针

---

## 结果文件位置

### 本地结果
- 最佳组合摘录：`data/results/direction7_best_notes.md`
- 完整 JSON：`data/results/explore_direction_7_refine_winners.json`
- 原始日志：`data/results/explore_direction_7_refine_winners.log`

---

## 当前结论

Direction7 已经说明：

> **当前策略不是没有候选，而是已经有一批可用候选，接下来关键是从“75 个合格组合”继续压缩成“1~3 个可作为主版本推进的组合”。**
