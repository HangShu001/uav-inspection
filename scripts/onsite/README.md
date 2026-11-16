# 实机侧数据生成脚本

`plateapp/data` 下三类文件各有唯一生产者，缺一个就换不了批次：

| 产物 | 生产者 | 在哪跑 |
|---|---|---|
| `timeline.json` | `scripts/build_replay.py` | 任何机器（只读日志） |
| `coverage.json` + `heatmap.png` | `scripts/onsite/v4e_coverage_report.py` | **实机**（要 cv2 + PIL + yaml） |
| `replay.mp4` / `poster.jpg` / `cover_*.jpg` | ffmpeg，见下 | **实机**（本机无 ffmpeg） |

本目录这两个脚本是实机 `~/runs/` 下同名文件的正规副本。2026-11-16 补入仓库前，
它们只存在于实机，导致「换一批跑批数据，覆盖质量页就做不出来」。

## 一、L4 质量栅格 → `coverage.json`

两段流水线，中间产物是 npz：

```bash
# ① 逐帧反投影，统计每格：观测帧数（帧-格去重）/ 点数 / 最近视角距离 / 最高点
python3 v4d_l4_quality_20261115.py <采集目录> <out.npz> [等帧数抽样]

# ② 转成前端 JSON + 热力图
python3 v4e_coverage_report.py <in.npz> <out.json> <out.png> [采集帧数] [采集目录名]
```

`v4d_l4_quality` 第 3 个参数是**等帧数抽样**：两轮采集帧数不同（p9 291 / p10 309）时，
覆盖率随帧数单调上涨，直接比会把「多拍了 18 帧」误读成「覆盖更好」。要做两轮对比就
传较小那个帧数，消掉混淆变量；只做单批交付则不传，用全部帧。

`v4e_coverage_report` 第 4 个参数是**采集深度帧数**（291/309），不是视频帧数（19568/18180）。
传错会让 JSON 里的 `source.frames_used` 差一个数量级。第 5 个参数是采集目录名，
不传则写 `unknown`——原先这里硬编码成单次跑批的目录名，换批就写错。

环境变量（换机器/换副本时才需要）：

- `UAV_V4_ROOT`：v4 副本根，默认 `~/uav_plate/code/v4`（`v4d_l4_quality` 要 import 它的
  `free_space_targets` 做反投影，保证与目标发现同一套相机模型）
- `UAV_V4_CFG`：车位/车表 yaml 所在目录，默认 `<UAV_V4_ROOT>/ws/src/uav_viewpoint/config`
- `UAV_CJK_FONT`：热力图用的中文字体，默认 Noto CJK

### 三个口径（每一个都踩过）

1. **分母用贴墙矩形** `x±13.7 / y±9.2`，不是栅格全域 `x±16 / y±11`。墙外 2 m 本来就看不到，
   算进分母会把覆盖率压到 89%。
2. **再扣掉 7 辆车自身的遮挡区**（碰撞盒 4.69×1.88）。车底被车身挡住是物理必然，
   11-15 那轮实测 5 处「覆盖缺口」有 56% 落在车体矩形内。
3. **观测帧数按帧-格去重**，不是按点数。按点数近处帧会独大，远处扫过的区域被低估。

## 二、`replay.mp4` 与封面

```bash
# 原速回放片：1280x720 → 854x480，CRF 32，无音轨
ffmpeg -y -i watch_raw.mp4 -vf scale=854:480 -r 15 -an \
       -c:v libx264 -crf 32 -preset medium -pix_fmt yuv420p \
       -movflags +faststart replay.mp4

# 阶段封面 480x270，抽帧时刻 = 该阶段中点 − video.offset_s（墙钟转视频时间）
ffmpeg -y -ss <t> -i replay.mp4 -frames:v 1 -vf scale=480:270 -q:v 2 cover_<key>.jpg
cp cover_survey.jpg poster.jpg      # poster 就是 survey 封面
```

**抽帧时刻必须减 `offset_s`**，否则每张封面都晚 8.7 秒（p10）。`wrap` 段中点常常
已经超出录屏末尾，ffmpeg 会取最后一帧，这是正常的。

场景是固定监控机位俯拍、车不动，只有无人机在动且占比不足 1%，所以片子会小得反常
（p10：1212 s 只有 4.9 MB / CRF 26）。真实画质正常，不是转码出错——用 `-ss` 抽一帧
看一眼即可确认。

## 三、产物清单与命名

`timeline.json` 的 `phases[].cover` 约定为 `/api/v1/plate/media/cover_<key>.jpg`，
其中 `<key>` 是 `survey` / `inspect_r1` / `inspect_r2` / … / `wrap`。
**阶段少一轮就要把多余的封面文件删掉**（p9 有 `cover_inspect_r3`，p10 没有）。

## 四、和 `ai/analysis/v4e_timeline_20261115.py` 的关系

那份是 11-15 生成 p9 时间线的一次性脚本：`RUN_DIR`、mission id、`VIDEO_OFFSET_S=29.5`
全部写死。2026-11-16 用 p9 数据与 `scripts/build_replay.py` 逐字段比对过，
除 `offset_s` 外完全一致——而 `offset_s` 那处是原脚本错了（见下）。

现在以 `scripts/build_replay.py` 为准，原因是它参数化、可换批次，且修正了 offset 算法。
