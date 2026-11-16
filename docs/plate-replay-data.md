# 车牌回放页的数据从哪来

> 面向维护者。回答一个问题：`plateapp/data/` 里那些文件，换一批跑批数据要怎么办。

## 一、页面用哪些文件

| 文件 | 谁在用 | 作用 |
|---|---|---|
| `timeline.json` | `plateapp/api/detect.py` → `/api/v1/plate/timeline`；前端 `PlateInspectionView.vue` 的「过程回放」tab | 视频 + 阶段条 + 事件流 + KPI |
| `coverage.json` | 同上 → `/api/v1/plate/coverage`；「覆盖质量」tab | 建图覆盖率、三排分项、15 个车位的观测数；末尾的 `rviz` 段指向全流程录屏 |
| `acceptance.json` | `/api/v1/plate/acceptance`；「巡检结果」tab | 逐车结果、违停、补拍轮次 |
| `cards/car_N.jpg` | 逐车卡片缩略图 | 静态素材 |
| `media/replay.mp4` `poster.jpg` `cover_*.jpg` `heatmap.png` | 回放播放器与阶段封面 | 静态素材 |
| `media/rviz_process.mp4` `rviz_process_poster.jpg` | 「覆盖质量」tab 的「点云与栅格深度融合」区块 | RViz 全流程录屏（1920×1080），元数据写在 `coverage.json` 的 `rviz` 段 |

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

### 4.1 过程回放（`replay.mp4` + 4~5 张封面）

`replay.mp4` 就是该批的 `watch_raw.mp4` **原样重封装**（`-c copy`，不重编码）：

```bash
ffmpeg -y -i watch_raw.mp4 -c copy -movflags +faststart replay.mp4
```

- 源与成品都是 **1280×720 @15fps**（`watch_cam` 的 sensor 规格），比早先的 854×480 清晰一档；
  录屏由 `scripts/onsite` 那条链无关，用的是 `watch_recorder`（见 §4.3）。
- 分钟级体积约 8~11 MB：场景是固定监控机位、车不动，只有无人机在动，
  x264 的 CRF 20 自然压得很狠。**片子小不等于糊**，要看就 `-ss` 抽一帧。

封面按「阶段中点 − `offset_s`」抽，**640×360**，`poster.jpg` 直接复用 survey 那张：

```bash
ffmpeg -y -ss <t> -i replay.mp4 -frames:v 1 -vf scale=640:360 -q:v 2 cover_<key>.jpg
cp cover_survey.jpg poster.jpg
```

### 4.2 RViz 全流程录屏（`rviz_process.mp4`）

覆盖质量页里那段「点云与栅格深度融合」的录屏，**不是话题录屏，是屏幕录制**——
因为要同时看到 3D 障碍层与左下角的 RGB / 深度图两块面板，只有 RViz 界面能一次给全。

```bash
# 录：2560x1440 全屏 -> 1920x1080，NVENC，目标 8 Mbps
ffmpeg -y -f x11grab -video_size 2560x1440 -framerate 15 -i :1 \
       -vf scale=1920:1080:flags=bicubic \
       -c:v h264_nvenc -preset medium -b:v 8M -maxrate 8M -bufsize 8M \
       -pix_fmt yuv420p rviz_process.mp4

# 收：动态内容实测 5.2 Mbps（757 MB / 19 min），太重，转成 12fps CRF 28 -> 约 70 MB
ffmpeg -y -i rviz_process.mp4 -vf "fps=12,scale=1920:1080" \
       -c:v libx264 -crf 28 -preset veryfast -pix_fmt yuv420p \
       -movflags +faststart rviz_web.mp4
```

**两个必须知道的坑（都在实机踩过）：**

1. **这台机器没跑窗口管理器**（`xprop -root _NET_ACTIVE_WINDOW` 返回 `0x0`，
   `wmctrl`/`xdotool` 也没有），窗口层级就是「谁最后 map 谁在上」。
   `gzclient` 后起来就把 RViz 整个盖住，录出来全是 Gazebo。
   解法：`scripts/raise_rviz.sh` 直接调 `XRaiseWindow` 把 rviz 提到最前。
2. **抓屏量亮度（YAVG）不能证明「看得见的是 RViz」**。第一次就是这么翻车的：
   YAVG=113 判「可见」，实际亮的是盖在上面的 Gazebo，整段 20 分钟全白录。
   正确的自检顺序是：先 `raise_rviz.sh` 提窗口 → 抓一帧**人眼看一次**
   （或比对窗口树里 rviz 在 Gazebo 之上）→ 再开始长录制。

### 4.3 `watch_raw.mp4` 怎么来

用 `watch_recorder`（实机 `~/runs/watch_recorder_20261116.py`）把 `/watch/image_raw`
按**墙钟节拍**写成 mp4：固定 15 Hz 定时器每拍写「最新一帧」，丢帧补重复帧。
这样视频秒数 ≈ 墙钟秒数，`offset_s` 才对得上；逐帧写会因丢帧让视频比墙钟短，
「点段首」整体偏。

它开机第一帧会 `print` 一行 `[INFO] [<unix>]: 录制开始 ...` 到 stdout 并 flush——
**这行就是 `offset_s` 的唯一可信来源**，必须落在 `record.log` 里
（`rospy.loginfo` 走 logging 的块缓冲，重定向到文件时永远等不到 4 KB 刷新，所以是 print）。

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

### 批次现状：四份同批（`p12_accept_20261116_120345`）

| 文件 | 批次 | 起始 | 生成方式 |
|---|---|---|---|
| `timeline.json`（过程回放） | `p12_accept_20261116_120345` | 12:03:48 | `scripts/build_replay.py timeline` |
| `coverage.json`（覆盖质量） | 同上（采集 `map_20261116_120345`，267 帧） | — | `scripts/onsite/v4e_coverage_report.py` |
| `coverage.rviz`（RViz 录屏） | 同上 | 12:07:16 起录 | `scripts/add_rviz_block.py` |
| `acceptance.json`（巡检结果） | 同上 | 12:03:48 — 12:24:04 | `scripts/gen_acceptance.py` |

2026-11-16 补上 `acceptance.json` 的生产脚本后，自检从「12 通过 / 1 WARN」变成
**13 通过 / 0 WARN / 0 FAIL**，页面上那枚琥珀色「回放批次 ≠ 巡检结果批次」提示随之消失。

`gen_acceptance.py` 的输入与口径（详见脚本头注释）：

- 起跑时刻取 `timeline.mission.started_at`，收尾取 `fsm.json` 的 mtime，墙钟 **1216 s**；
  （此前口头的 1235 s 是 `timeline` 末段阶段标记，两者差 19 s，口径不同不算矛盾）
- 逐车结果取 `fsm.rounds[].run_dir` 下每腿的 `*_plate.json`，按「真值命中 > 轮次靠后 > 置信度高」选一条；
- **真值取 spawn 表 `parking_cars_v2.yaml`，不取 `inspect_r*.yaml`**：后者来自
  `cruise_discovered.yaml`，把 `car_0` 写成 `皖A17618`，而 spawn 表里那辆车（`car_park_02`）
  是 `皖BXH618`，p12 两腿识别也都是 `皖BXH618`（0.998 / 0.987）。这条差异已登记为
  **真值表待订正**（`cruise_discovered.yaml` 该字段），不影响本次认定 7/7。
- **违停余量按 `real_car` 重挂**：`car_N` 的编号每轮不同（p10 的 `car_4` 是 `car_park_04`，
  p12 的 `car_4` 是 `car_park_06`），按序号搬运会把余量算到别的车上。p12 未做车位重建，
  该表沿用 p10 几何复算结果，页面在表下方标注来源批次（`acceptance.geometry`）。

### 本轮（p12）的关键读数

| 项 | 值 |
|---|---|
| 结果 | `DONE`，`C_cap=1.000`（7/7），2 轮 INSPECT，墙钟 1216 s（timeline 末段 1235 s） |
| SURVEY | 400 s 发现 7 条 |
| 过程回放视频 | 1147.9 s / 1280×720 / 17218 帧 |
| RViz 录屏 | 1164.5 s / 1920×1080 / 12 fps / 70 MB |
| 覆盖率 | ≥1 帧 98.68% / ≥3 帧 95.80% / ≥10 帧 62.53%（分母 19461 格） |
| `offset_s` | **209.3 s** —— 录屏是任务开始后 3 分 29 秒才起的 |

**`offset_s` 209 s 要讲清楚**：先起 RViz、再把它从 Gazebo 底下提上来（机器没有窗口管理器），
提完才敢开录，所以前 3.5 分钟的 SURVEY 不在画面里。过程回放的阶段条仍按墙钟画，
点 SURVEY 段首会 clamp 到视频 0 s（即任务第 209 s）。要补这段就得重跑一轮、
把 `watch_recorder` 在 `rosmaster` 一起来就拉起（它不依赖 RViz，可以先录）。

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
