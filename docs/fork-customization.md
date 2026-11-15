# 本 fork 的定制说明

这是 [`rg-ut/uav-inspection`](https://github.com/rg-ut/uav-inspection) 的定制分支，维护者
[HangShu001](https://github.com/HangShu001)。上游项目是 FastAPI + Vue 3 的无人机巡检演示平台，
本 fork 在上游基础上增加了一个「车辆车牌巡检」业务模块，并补齐了跨平台开发与上游同步的配套。

上游代码保持可追溯：**所有新增能力都是加装，不修改上游模块的行为**。这样既能单独部署自己的版本，
也能把通用改进以 PR 形式回馈上游。

---

## 一、相对上游新增了什么

### 1. 车辆车牌巡检模块（主体）

一个两段式车牌检测 + 识别模块，接法与上游其他巡检模块完全一致（`xxxapp/detector.py` +
`xxxapp/api/detect.py` + 前端 View + 路由 + 首页卡片）。

| 位置 | 文件 | 说明 |
|---|---|---|
| 后端 | `app/uav-inspection-backend/plateapp/detector.py` | YOLO 检测车牌，兼容普通检测框与 OBB 旋转框；按类别名映射蓝/绿/黄/白/黑牌 |
| 后端 | `app/uav-inspection-backend/plateapp/recognizer.py` | 可插拔的第二级字符识别（ONNX 或 TorchScript），权重缺失时自动降级为「只检测不识别」 |
| 后端 | `app/uav-inspection-backend/plateapp/api/detect.py` | 健康检查 / 配置 / 单帧检测 / 视频抽帧检测 / 离线结果回放 |
| 后端 | `app/uav-inspection-backend/plateapp/data/` | 内置一次真实验收的回放数据与 7 张识别结果卡（约 1 MB） |
| 前端 | `app/uav-inspection-ui/src/views/PlateInspectionView.vue` | 双页签页面：实时检测 + 巡检结果 |
| 前端 | `app/uav-inspection-ui/src/api1/plate.ts` | 接口客户端与类型定义 |

注册点（都是小改，便于审查）：

- `heatmapapp/main.py` — 挂载 router、静态卡片目录，`spa_routes` 加 `plate`
- `deployment_readiness.py` — `MODEL_PATHS` 加 `plate`，`module_status()` 加模块就绪判定
- `assetsapp/api.py` — 新增 `plate-media` / `plate-model` / `plate-recognizer` 三个上传分类
- `uav-inspection-ui/src/router/index.ts`、`views/HomeView.vue`、`config/moduleThemes.ts` — 路由、卡片、主题色

### 2. 接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/plate/health` | 服务与模型加载状态（不触发模型加载） |
| GET | `/api/v1/plate/info` | 模型类别、任务类型、识别器状态、推理设备；权重缺失返回 503 |
| GET/POST | `/api/v1/plate/config` | 读取/更新置信度、IoU、单帧最大车牌数 |
| POST | `/api/v1/plate/detect` | 单帧检测，JSON 传 base64 图片 |
| POST | `/api/v1/plate/detect/upload` | 单帧检测，multipart 传文件（页面用这个） |
| POST | `/api/v1/plate/detect/video` | 视频抽帧检测，返回去重车牌清单与代表帧 |
| GET | `/api/v1/plate/acceptance` | 内置验收结果回放（无需权重） |
| GET | `/api/v1/plate/cards/{name}.jpg` | 识别结果卡静态图 |

运行时的完整 OpenAPI 在 `/docs`。

### 3. 模型权重约定

权重**不进仓库**，与上游其他模块一样走素材上传中心或 `UAV_DATA_DIR`：

| 分类 | 目标目录 | 文件名要求 |
|---|---|---|
| `plate-model` | `<数据根>/uav-inspection-backend/plateapp/` | 必须为 `plate-det-best.pt`，子目录留空 |
| `plate-recognizer` | 同上 `/recognizer/` | `model.onnx` 或 `model.pt` + `charset.txt`（+ 可选 `meta.json`） |
| `plate-media` | 同上 `/platedata/media/` | 巡检照片或视频，仅留档 |

识别器的输入输出约定写在 `plateapp/recognizer.py` 的文件头注释里。**约定不符不会报错，
只会得到乱码**，所以页面对识别文本始终附带 `text_score`。

### 4. 工程配套

- `.gitattributes`：统一行尾（`.sh`/`.py`/`.ts` 一律 LF，`.bat` 保持 CRLF）。上游在 Windows
  上 clone 后 `.sh` 会被转成 CRLF，传到 Linux 直接跑不起来。
- `.gitignore` 补 `.venv/`：上游 README 让人 `python -m venv .venv`，但忽略规则只写了 `.venv-deploy/`，
  照做之后 `git status` 会多出一堆未跟踪文件。
- `scripts/sync-upstream.sh`：一键查看落后上游多少、合并或变基。

---

## 二、上游同步

一次性配置（fork 后只做一次）：

```bash
git remote add upstream https://github.com/rg-ut/uav-inspection.git
git remote -v      # origin 指向自己的 fork，upstream 指向原始仓库
```

日常同步：

```bash
bash scripts/sync-upstream.sh            # 只看落后多少
bash scripts/sync-upstream.sh merge      # 合并进当前分支
bash scripts/sync-upstream.sh rebase     # 变基（历史更干净，推过的话要 --force-with-lease）
```

**合并后必须验证**，别只信文件数：

```bash
cd app/uav-inspection-ui && npm run build
cd app/uav-inspection-backend && .venv/Scripts/python.exe -m compileall -q . && echo OK
```

前端 `vue-tsc -b` 会把跨文件的类型断裂直接抓出来，这是最省事的回归手段。

---

## 三、向上游提 PR

本 fork 的改动分两类，只有第二类适合提 PR：

| 类型 | 例子 | 处理 |
|---|---|---|
| 本 fork 专属 | 车牌模块、内置验收数据、README 的 fork 说明 | 留在 fork，不提 |
| 上游也能受益 | `.gitattributes` 行尾统一、`.gitignore` 补 `.venv/`、车牌模块的**通用部分**（如 OBB 结果分支） | 提 PR |

推荐流程（改动隔离在独立分支，`main` 保持与上游可同步）：

```bash
git switch -c feat/plate-inspection upstream/main   # 从上游切，不带自己的定制
# 只挑通用改动落地、提交
git push -u origin feat/plate-inspection
gh pr create --repo rg-ut/uav-inspection --base main \
  --title "feat: 新增车辆车牌巡检模块" \
  --body "改动说明、验证方式、对现有模块零影响"
```

从 `upstream/main` 切分支的好处：PR 的 diff 只有你能贡献的那部分，不会混进无关的定制提交，
上游作者审起来也轻松。PR 被合回来之后，本地 `main` 通过 `sync-upstream.sh merge` 收进来即可，
不会产生重复提交。

---

## 四、本机开发环境（Windows 实测）

| 项 | 版本 | 备注 |
|---|---|---|
| Node | 22.22.2 | 上游要求 22.12+ |
| Python | 3.12.14 | 上游要求 3.10–3.13；用独立 venv，别动系统环境 |
| Docker | 未安装 | 本机只跑开发模式；容器部署在 Linux 服务器上验证 |

国内装 Python 依赖时，清华源可能返回 403，换阿里云：

```bash
cd app/uav-inspection-backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-base-lock.txt \
  -i https://mirrors.aliyun.com/pypi/simple/
```

启动：

```bash
# 后端（终端一）
cd app/uav-inspection-backend
.venv/Scripts/python.exe -m uvicorn heatmapapp.main:app --port 8002

# 前端（终端二，热更）
cd app/uav-inspection-ui
npm run dev
```

后端默认不带前端构建产物，所以开发期开 Vite 的 5173；要看单端口效果就先 `npm run build`。

---

## 五、实测精度

用 v2.0 验收轮同一批 7 辆车、17 条拍摄腿，在 RTX 3070 上跑
（检测 `ccpd_obb_640_c2`，识别 `green_detcrop_v5_p76` 的 ONNX）：

| 指标 | 数值 |
|---|---|
| 逐腿整牌全对 | 11 / 17 |
| 多帧投票后全对 | 5 / 7 |
| 单帧识别置信度 | 0.79 ~ 1.00 |

两个不符合预期但都说得通的样本：

- **car_0 三条腿全部漏检**。这辆车在场景里被挡板挡住，检测器给不出框是对的；
  真实流程靠「判定无效 → 第二轮补拍」解决，不是识别问题。
- **car_2 的 `V` 被认成 `5`**，两条腿给出同样的错值。这是模型精度，不是解码
  或预处理问题，加长约束也救不回来。

把 car_0 排除后，可见车是 5 / 6 —— 与该项目在 CCPD test 上报告的端到端
87.30%（带长度约束）同一量级。

接权重时踩到的三个坑已经写进 `plateapp/recognizer.py` 的文件头注释：
通道顺序（BGR/RGB）、四点定角、输入尺寸与归一化。字符表模板见
`plateapp/data/charset_ccpd.txt`。

---

## 六、这个版本的边界

- **精度数据来自仿真场景**（Gazebo 渲染 + CCPD 权重），不是真实道路采集；
  逆光、夜间、雨雪、运动模糊都没有覆盖。
- **识别器的输入输出约定只对 CCPD 这一系模型验证过**。换成别的训练集，
  字符表顺序、输入尺寸、归一化方式都可能不同，需要重写 `meta.json`。
- **视频检测是同步执行的**，服务端硬上限 40 帧采样 / 60 秒，超出部分截断并
  在响应里标注。没有做异步任务化。
- **未在 Docker 容器内验证**。本机与实机都没有 Docker，`deploy/compose.yml`
  与新模块的关系只是「新代码会被打进镜像」。
- **页面视觉没有截图确认**。开发机的浏览器截图接口返回「exceeds the 10 MiB
  image limit」，DOM 快照工具只暴露 `<a>` 元素、拿不到按钮卡片。改用类型检查、
  构建产物文案核对、路由守卫与接口实测替代，这不等于人工看过页面。

## 七、分发给别人

源码 8.1 MB，加上预构建前端（3.1 MB）与车牌三个权重（25 MB），打成一个 zip 约 29 MB，
解压即用。**接收方不需要 Node.js**，只要 Python 3.10~3.13。

三步：`首次安装.bat` →（可选，要做真检测才需要）`安装推理依赖.bat` → `打开车牌巡检.bat`。

**两个必须知道的坑（2026-11-15 实测）**：

1. **官方 PyPI 在国内基本连不上**。`files.pythonhosted.org` 报
   `SSLEOFError(8, 'UNEXPECTED_EOF_WHILE_READING')`，自动重试五次后失败，一个包都没落地。
   同一份 requirements 换阿里云镜像 **38 s 装完 55 个包**。所以 `首次安装.bat`
   默认走阿里云、失败才退回官方源，并设 `PIP_NO_CACHE_DIR=1`（某些环境清理下载缓存
   会被权限拦，`--no-cache-dir` 直接绕开这条路径）。

2. **不要用 `app/scripts/build_delivery.py` 打这个 fork 的数据包**。
   它按 `app/uav-inspection-backend/<模块>/` 找权重，而本 fork 的
   `app/deployment-layout.json` 把数据根指向了仓库根的 `02-data/`，
   `--dry-run` 直接显示 `data: 0 files`。源码包可以用它
   （`--root app --without-data`），数据包只能手工装配：把
   `02-data/uav-inspection-backend/plateapp/` 下的 `plate-det-best.pt` 与
   `recognizer/{model.onnx,charset.txt}` 拷到解压后的同名目录即可。

**包内结构**：

```
uav-plate-demo/
  接收方必读.md
  首次安装.bat / 安装推理依赖.bat / 打开车牌巡检.bat
  app/                                      ← 源码 + 预构建的 ui/dist/
  02-data/uav-inspection-backend/plateapp/  ← 三个权重
```

**验证口径**（换一台机器复现时应看到同样的结果）：解压到任意目录，用
`app/.venv-deploy` 里的 Python 起 `uvicorn heatmapapp.main:app --port 8002`，
`/plate` 返回 200；只装基础依赖时 `/api/v1/plate/detect/upload` 返回 503 并提示缺推理依赖；
装完 `--inference` 后同一接口对 `plateapp/data/cards/car_6.jpg` 返回
`皖ACS122`（绿）与 `皖5021`（蓝，背景车，部分遮挡）。
