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
`~/runs/mission_20261114_190947/fsm.json` 重跑，与盘上原有的 `timeline.json`
逐字段一致（20 条事件 / 5 段阶段 / 3 条 rounds / `wall 1319` / `elapsed 1296` /
`19568 帧 @15fps → 1304.5 s`）——**除 `offset_s` 一处，而那一处原本就是错的**，见下。

各字段真源见脚本文件头那张表。三个容易踩的点：

1. **`kpi` 只能从 `fsm.json` 取**，不能从日志反推。`rounds[].new` 在日志里没有，
   只有 `fsm.json` 有；硬从日志猜会给出一个和状态机不一致的数。
2. **`events` 要剔除 SURVEY 参数铺设的 6 行**（聚类半径 / 场景 / 车位清单 / 范围 /
   起 stage1 / 日志）。它们缩进对齐，`strip()` 之后再判，否则漏掉一条并导致后续全部错位一位。
3. **`video.offset_s` 必须用录制开始的时间戳算**，见下节。

### `offset_s` 修正：此前整条时间轴晚约 24 秒（2026-11-16）

原算法是「（record.log 的脚本结束时刻 − 任务开始时刻）− 视频秒数」。**这个时刻是
整个脚本收尾的时间**（停 stage1、建车位图、写 `DONE.rc`），比录屏停止晚约 24 秒。
p9 因此算成 29.5 s，而真实值是 6.4 s。

现算法取 record.log 里 `[INFO] [<unix>]: 录制开始` 的时间戳，减去任务开始时刻：

| 批次 | 原值 | 实测真值 | 偏差 |
|---|---|---|---|
| p9 `p9_v2_final_20261114` | 29.5 s | **6.4 s** | −23.1 s |
| p10 `p10_v2_final2_20261114` | 33.0 s | **8.7 s** | −24.3 s |

后果：`seekToPhase` 用 `t0 − offset_s` 定位，offset 偏大 24 秒，等于**每次点「段首」
都跳到比实际早 24 秒的位置**。对 SURVEY 段（t0=0）无所谓（都 clamp 到 0），
但对只有 1~22 秒长的 `wrap` 段，会直接跳到上一段里去。

`timeline.json` 的 `video.note` 现在会写明 offset 的来源，出现
「（来源：脚本结束时刻（偏大，不可靠））」就说明时间戳没抓到、用了兜底，要查日志。

封面抽帧同样受这个影响：取帧时刻 = 阶段中点 − `offset_s`，offset 错就整套封面晚 24 秒。

## 三、`coverage.json`：已可复现（2026-11-16 找回原脚本）

原先这里写着「缺 5 个口径、不能猜」。2026-11-16 在实机 `~/runs/` 下找到了真正的
生成器 `v4e_coverage_report.py`，源头是 `v4d_l4_quality_20261115.py` 产出的 npz。
两份都已收进仓库 `scripts/onsite/`，5 个口径全部有答案：

| 原先的疑问 | 脚本给出的答案 |
|---|---|
| `grid [213,147]` 比 rect 大一圈，外扩规则未知 | 栅格固定取 `x±16 / y±11`（0.15 m 格），**与 rect 无关**。rect 只用于算分母 |
| `car_cells 3048` 是怎么膨胀的 | 车体按 **4.69×1.88**（`model.sdf` 4.5×1.8 × `box_scale` 1.0432）铺，轴对齐，不膨胀 |
| `rows` 合计 16557 < 19461，剩 2904 格归属未知 | 三排各取 `|x−xc| ≤ 6.25` 且 `|y| ≤ 6.25` 的带；**带外格本来就不进任何一排** |
| `slots` 的 `frames/points/min_dist` 定义 | 车位中心 3×3 邻域取 **max**：`frames`=最大观测帧数、`points`=最大点数、`min_dist`=最小距离 |
| `depth` 的统计单位 | 按**格**（先取 `cf[obs]` 再取分位），不是按点或按帧 |

核心三个比值不变：`cells / observable_cells`，阈值 1 / 3 / 10 帧。

用法（必须在实机跑，依赖 cv2 / PIL / yaml）：

```bash
python3 scripts/onsite/v4d_l4_quality_20261115.py <采集目录> <out.npz>
python3 scripts/onsite/v4e_coverage_report.py <in.npz> <out.json> <out.png> <采集帧数> <采集目录名>
```

第 4 个参数是**采集深度帧数**（291/309），不是视频帧数（19568/18180）——传错会让
`source.frames_used` 差一个数量级。第 5 个是采集目录名，原先硬编码成 p9 的
`map_20261114_190944`，用它算 p10 会把错的目录名写进 JSON。

口径细节见 `scripts/onsite/README.md`。

## 四、静态素材：需要 ffmpeg

`replay.mp4`、`poster.jpg`、`cover_survey.jpg`、`cover_inspect_r*.jpg`、`cover_wrap.jpg`
都从该批的 `watch_raw.mp4`（1280×720 @15fps）转码与抽帧：

```bash
# 原速回放片：854×480，CRF 32，无音轨
ffmpeg -y -i watch_raw.mp4 -vf scale=854:480 -r 15 -an \
       -c:v libx264 -crf 32 -preset medium -pix_fmt yuv420p \
       -movflags +faststart replay.mp4

# 阶段封面 480×270；取帧时刻 = 阶段中点 − offset_s
ffmpeg -y -ss <t> -i replay.mp4 -frames:v 1 -vf scale=480:270 -q:v 2 cover_<key>.jpg
cp cover_survey.jpg poster.jpg          # poster 就是 survey 封面
```

当前这批（p10）：1212.0 s / 18180 帧 / **4.9 MB**（CRF 26 转的，比原定的 CRF 32 大一倍，
画质更保守）；4 张封面 + poster，p10 只有 2 轮 INSPECT，**没有 `cover_inspect_r3`**。
抽帧时刻为 191.3 / 735.3 / 1141.3 / 1211.3 s。

片子小得反常（1212 s 只有几 MB）不是转码出错：场景是固定监控机位俯拍、车不动，
只有无人机在动且占比不足 1%，实测 99.8% 宏块被 skip。要确认画质就 `-ss` 抽一帧看，
画面是清晰的。

`wrap` 段中点常已超出录屏末尾（p10 差 9.3 s），ffmpeg 会取最后一帧，属正常。
自检对这处的判据是：超出 ≤ 60 s 记 WARN 并注明「收尾段未被录屏覆盖」，> 60 s 才 FAIL。

**本机没有 ffmpeg**（`where ffmpeg` 为空），所以转码/抽帧只能在大机器上做。

## 五、交付自检（`scripts/check_replay_data.py`）

三个 JSON 是分批塞进来的，彼此没有约束。跑一次自检把「能不能演示」变成可执行判定：

```bash
python scripts/check_replay_data.py            # 默认查 plateapp/data
python scripts/check_replay_data.py --strict-batch   # 两处批次不同即 FAIL
```

查 8 类：JSON 可解析、引用的素材存在且非空、**MP4 真实时长**（直接解 `mvhd` box，
不需要 ffmpeg）与 `video.seconds` 是否一致、`phases` 区间自洽且不越界、
`kpi` 汇总数与 rounds 一致、`coverage` 的 `cells/observable` 与 `ratio` 自洽、
`acceptance` 车辆数与缩略图齐全、两处批次是否同一跑次。

**当前状态（p10 数据）**：**12 项通过、1 个 WARN、0 个 FAIL**。

- 视频时长实测 1212.0 s，与声明差 0.0 s。
- 批次两处都是 `p10_v2_final2_20261114`，原 WARN 已消。
- 唯一 WARN 是「末段 t1=1230 比录屏末尾 1220.7 晚 9 s」——脚本收尾比录屏停得晚，
  属正常，判据见 §四末段那条。

### 批次不一致：已对齐到 p10（2026-11-16 修）

原先 `acceptance.json` 是 **p10**（19:39:07 起），`timeline.json` 与 `coverage.json`
是 **p9**（19:09:47 起）——「巡检结果」与「过程回放」展示的不是同一跑次，页面却不提示。

现在三份都是 `p10_v2_final2_20261114`，自检的批次项从 WARN 转为 OK。

**为什么选 p10 而不是 p9**：p10 才是干净那轮。

| | p9 | p10 |
|---|---|---|
| INSPECT 轮次 | **3 轮**（第 2 轮 `rc=4` 失败） | **2 轮**，全 `rc=0` |
| `fail_classes` | `{rc_4: 1}` | `{}` |
| 时长 | 1304.5 s | 1212.0 s |

把回放切到 p10 后，时间轴上不再出现一整轮失败的补拍。`acceptance.json` 本来就是 p10，
现在三份数据讲的是一件事。

前端仍保留「回放批次 ≠ 巡检结果批次」的琥珀色提示，作为换批时的防呆。

### 媒体缓存：URL 已加内容戳（2026-11-16）

静态挂载不带 `Cache-Control`，浏览器对同 URL 的 mp4 会**强缓存**。实测把 p9 换成 p10 后，
页面上仍显示旧的 `21:44`（1304 s）而不是新的 `20:12`（1212 s），普通刷新与 F5 都无效，
必须硬清缓存——演示时这会让所有人看到旧数据。

`plateapp/api/detect.py` 的 `_media_versioned()` 现在给 `video.src` / `poster` /
`phases[].cover` / `coverage.image` 统一追加 `?v=<文件 mtime>`。文件一换 URL 就变，
客户端自然重新拉取，不用再教用户清缓存。

## 六、和 `output/v2demo_web` 的关系

那个目录是**另一个东西**：v2.0 验收汇报页，零依赖 `http.server`，读的是
`p7_v2_accept_20261113`（11-13 那轮）。本仓库三份数据现在统一读
`p10_v2_final2_20261114`（11-14 19:39 那轮）。两者**数据批次不同、用途不同、技术栈不同**，
不是重复工作；重叠的只是「把一次跑批展示成回放」这个能力。
见 `Doudou/00_导航/项目_车牌巡检平台.md` §七-5。
