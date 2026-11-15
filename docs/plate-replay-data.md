# 车牌回放页的数据从哪来

> 面向维护者。回答一个问题：`plateapp/data/` 里那些文件，换一批跑批数据要怎么办。

## 一、页面用哪些文件

| 文件 | 谁在用 | 作用 |
|---|---|---|
| `timeline.json` | `plateapp/api/detect.py` → `/api/v1/plate/timeline`；前端 `PlateInspectionView.vue` 的「过程回放」tab | 视频 + 阶段条 + 事件流 + KPI |
| `coverage.json` | 同上 → `/api/v1/plate/coverage`；「覆盖质量」tab | 建图覆盖率、三排分项、15 个车位的观测数 |
| `acceptance.json` | `/api/v1/plate/acceptance`；「巡检结果」tab | 逐车结果、违停、补拍轮次 |
| `cards/car_N.jpg` | 逐车卡片缩略图 | 静态素材 |
| `media/replay.mp4` `poster.jpg` `cover_*.jpg` `heatmap.png` | 回放播放器与阶段封面 | 静态素材 |

## 二、`timeline.json`：已可复现（2026-11-15）

生成器：`scripts/build_replay.py timeline`

```bash
python scripts/build_replay.py timeline \
    --record-log ~/runs/<run_name>/record.log \
    --fsm-json  ~/runs/<mission_id>/fsm.json \
    --out app/uav-inspection-backend/plateapp/data/timeline.json \
    --diff app/uav-inspection-backend/plateapp/data/timeline.json   # 先比再覆盖
```

**验证记录**：用 `~/runs/p9_v2_final_20261114/record.log` +
`~/runs/mission_20261114_190947/fsm.json` 重跑，与盘上现有的 `timeline.json`
**逐字段一致**（20 条事件 / 5 段阶段 / 3 条 rounds / `wall 1319` / `elapsed 1296` /
`19568 帧 @15fps → 1304.5 s` / `offset 29.5 s`）。

各字段真源见脚本文件头那张表。三个容易踩的点：

1. **`kpi` 只能从 `fsm.json` 取**，不能从日志反推。`rounds[].new` 在日志里没有，
   只有 `fsm.json` 有；硬从日志猜会给出一个和状态机不一致的数。
2. **`events` 要剔除 SURVEY 参数铺设的 6 行**（聚类半径 / 场景 / 车位清单 / 范围 /
   起 stage1 / 日志）。它们缩进对齐，`strip()` 之后再判，否则漏掉一条并导致后续全部错位一位。
3. **`video.offset_s` 的算法**是「（结束时刻 − 任务开始时刻）− 视频秒数」——
   录屏在收尾时停，所以视频起点必然晚这么多。本批算出 29.5 s，与盘上一致。

## 三、`coverage.json`：**还不能复现**，缺 5 个口径

已知的（从数值反推，可信）：

| 字段 | 值 | 说明 |
|---|---|---|
| `source.cell_m` | 0.15 | 格边长 |
| `source.frames_used` | 291 | 恰好等于 `map_20261114_190944` 的 `*_color.png` 帧数 |
| `source.rect` | `[-13.7, 13.7, -9.2, 9.2]` | 贴墙内表面内缩 0.3 m |
| `area.site_cells` | 22509 | = 183 × 123，正好铺满 rect |
| `area.observable_cells` | 19461 | = 22509 − 3048（扣除车体遮挡区） |
| `coverage[].ratio` | 98.49 / 95.74 / 61.29 | = `cells / observable_cells`，三个阈值 1 / 3 / 10 帧 |

**缺的 5 个，必须问出原脚本或重跑原逻辑才能补**（不猜，猜出来的数会看着像对的）：

1. `source.grid = [213, 147]`（31.95 × 22.05 m）比 rect 大一圈——**外扩规则未知**。
   可能是给热力图留边，也可能是裁剪窗口。不影响上面那些比值，但影响热力图画布。
2. `area.car_cells = 3048`（7 车平均 435 格 = 9.79 m²）比真值矩形 4.5×1.8 = 8.1 m² 大
   约 21%——**车体遮挡区是按什么膨胀出来的**（0.3 m？还是取凸包？）未知。
3. `rows[]` 只有 3 条（左/中/右排，x = −8.28 / 0 / 8.28），`cells` 合计 16557 < 19461
   ——**不属于任何一排的 2904 格是什么**（通道？边缘带？）未知。
4. `slots[].frames / points / min_dist` 三个量的定义：`frames` 是「该车位多边形内被
   看到的帧数」还是「格级中位」？`points` 是车位多边形的点数和还是区域内点数？
   `min_dist` 是「任一点到车位中心的最小水平距离」吗？——都没记录。
5. `depth.frames_p50/p95`、`dist_p50/p95`、`pts_p50` 的统计单位
   （按格？按点？按帧？）未知。

**建议**：这 5 条要么找回当初的临时脚本，要么由 CX 按上表口径重写并接受数字可能
小幅变化（`coverage` 三个比值是核心，`rows`/`slots` 是分项展示）。

## 四、静态素材：需要 ffmpeg

`replay.mp4`（1280×720 @15fps，19568 帧，1306 s）、`poster.jpg`、`cover_survey.jpg`、
`cover_inspect_r1~r3.jpg`、`cover_wrap.jpg` 都是从 `watch_raw.mp4` 转码/抽帧来的。
阶段封面的取帧时刻 = 各阶段中点（`phases[].t0` 与 `t1` 的平均，再减 `offset_s`）。

**本机没有 ffmpeg**（`where ffmpeg` 为空），所以这一步目前只能在大机器上做，或先装
ffmpeg 再加进本脚本。这是补齐交付链路的下一个缺口。

## 五、交付自检（`scripts/check_replay_data.py`）

三个 JSON 是分批塞进来的，彼此没有约束。跑一次自检把「能不能演示」变成可执行判定：

```bash
python scripts/check_replay_data.py            # 默认查 plateapp/data
python scripts/check_replay_data.py --strict-batch   # 两处批次不同即 FAIL
```

查 7 类：JSON 可解析、引用的素材存在且非空、**MP4 真实时长**（直接解 `mvhd` box，
不需要 ffmpeg）与 `video.seconds` 是否一致、`phases` 区间自洽且不越界、
`kpi` 汇总数与 rounds 一致、`coverage` 的 `cells/observable` 与 `ratio` 自洽、
`acceptance` 车辆数与缩略图齐全、两处批次是否同一跑次。

**2026-11-16 首次运行结果**：11 项通过、1 个 WARN、0 个 FAIL。唯一 WARN 是批次不一致
（见下），其余全过——包括 `replay.mp4` 实测 **1304.5 s** 与声明完全一致
（2.6 MB 的片子确实是 1304 s，压缩率高但时长没错）。

### 已知的批次不一致（WARN，未修）

| 位置 | 批次 | 起始 |
|---|---|---|
| `acceptance.json` → 巡检结果 tab | `p10_v2_final2_20261114` | 19:39:07 |
| `timeline.json` → 过程回放 tab | `p9_v2_final_20261114` | 19:09:47 |

两处展示的不是同一跑次。**2026-11-16 已在前端加提示**：回放页头显示 `mission.run`，
并在两者不同时挂一枚琥珀色说明「回放批次 ≠ 巡检结果批次」。不再让它在页面上悄悄过去。

根治要等能连上实机：用 p10 的 `record.log` + `fsm.json` 重跑
`build_replay.py timeline`，把两份数据对齐到同一跑次。

## 六、和 `output/v2demo_web` 的关系

那个目录是**另一个东西**：v2.0 验收汇报页，零依赖 `http.server`，读的是
`p7_v2_accept_20261113`（11-13 那轮）。本仓库回放读的是 `p10_v2_final2_20261114`
与 `p9_v2_final_20261114`。两者**数据批次不同、用途不同、技术栈不同**，
不是重复工作；重叠的只是「把一次跑批展示成回放」这个能力。
见 `Doudou/00_导航/项目_车牌巡检平台.md` §七-5。
