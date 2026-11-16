# 与 10.50.2.92「/uav/」平台的对齐分析

> 分析对象：`http://10.50.2.92/uav/`（线上运行实例）
> 对照对象：本仓库 `D:\1_AiMemory\Wenwen\uav-inspection`
> 数据来源：线上 `openapi.json`（65,696 B，96 路径 / 101 操作）、线上前端 `index-twuMyzCZ.js`
> （125,259 B，12 个 View chunk）、`request-C-jJLbrS.js`，以及本仓库源码逐行核对
> 分析时间：2026-11-16

---

## 0 结论摘要

**那台机器跑的不是另一个项目，是同一个 `rg-ut/uav-inspection` 的旧构建。**

三条硬证据：

1. `openapi.json` 的 `info.title` 是 `园区无人机巡检系统` —— 与本仓库
   `heatmapapp/main.py:27` 的 `FastAPI(title='园区无人机巡检系统')` 完全一致；
2. 12 个业务模块的操作数**逐个相等**：`tasks 7 / predict 1 / pest 16 / rose 4 / telecom 10 /
   roof 10 / power 7 / wall 16 / pruning 9 / vegetation 6 / assets 7 / fendai 2`；
3. 线上前端 `request-C-jJLbrS.js` 里是 `` `${BASE_URL}api/v1` `` —— 与本仓库
   `src/utils/request.ts:6` 的 `` `${BASE_URL}api/v1` `` 同一份实现，只是用 `VITE_BASE=/uav/` 构建。

**差额只有两处**：线上**没有 `authapp`（4 个端点）**、**没有 `plateapp`（10 个端点）**。
101 + 4 + 10 = 115，与本仓库的操作总数对上。

所以"对齐"不是重新学一套架构，而是三件事：

| # | 要做的事 | 性质 |
|---|---|---|
| 1 | 把车牌模块的数据落点改回平台约定的 `<数据根>/uav-inspection-backend/platedata/` | **硬偏离，必须改** |
| 2 | 镜像上下文清理（61 个 `pip-*` 临时目录 + 77 MB 数据） | 硬隐患，必须改 |
| 3 | 决定登录门要不要跟着上那台机器（线上没有 auth） | 产品取舍，已给默认方案 |

模块划分、接口路径、响应封套、命名风格这四项**已经一致**，不需要返工。

---

## 1 远端的项目画像（实测，非推测）

| 项 | 值 | 怎么得到的 |
|---|---|---|
| 系统名 / 版本 | 园区无人机巡检系统 / 0.1.0 | `openapi.json` 的 `info` |
| 接口前缀 | `/api/v1/<domain>` | 96 条路径全部符合，无例外 |
| 操作总数 | 101（含 6 个根/公共接口） | 按 method 计数 |
| 业务 tag | 12 个，全中文：病虫害巡检、建筑外墙巡检、通信基站巡检、屋顶巡检、乔木修剪检测、任务、杆路线路巡检、素材上传、乔木与绿化测量、玫瑰检测、粉黛花漫游、客流预测（另有 6 个公共接口不带 tag） | `openapi.json` 的 `tags` |
| 前端部署 | `base = /uav/`，资源 `/uav/assets/...` | `index.html` 实际引用 |
| 前端框架 | Vue 3 + vue-router `createWebHistory` | chunk 名与路由行为 |
| 后端框架 | FastAPI + StaticFiles，单容器同源托管前端 | `/uav/docs` 是 Swagger UI |
| 子路径方案 | 反向代理剥前缀（`proxy_pass .../`），应用侧按根路径工作 | `/uav/pest` 200 而 `/uav/nonexist` 404 |
| 认证 | **无**（线上 JS 里 `登录`/`注册` 出现 0 次，无 `/api/v1/auth` 调用） | 全文 grep |
| 车牌模块 | **无**（无 `PlateInspectionView` chunk，`/api/v1/plate/*` 全 404） | chunk 清单 + 逐条探测 |

**一处更正我上一轮的判断**：我当时说"nginx 没配 SPA 回退，所以要加 `try_files`"。实测
`/uav/pest` 返回 **200**、`/uav/wall` 返回 **200**、`/uav/rose-yield` 返回 **200**，
只有 `/uav/plate` 是 404。这说明 SPA 回退**在应用层**（`heatmapapp/main.py:161-163` 的
`spa_routes` 集合 + `:151` 的 `/{path:path}` 兜底），不是 nginx 的事。线上 404 的唯一原因是
那台机器的构建里 `spa_routes` 还没有 `plate`。**nginx 不用改。**

---

## 2 该项目的关键约定（11 条，逐条给落点）

### A. 仓库结构：`app/` 装代码，数据在仓库根的 `02-data/`

```
<repo>/
├─ app/
│  ├─ deployment-layout.json        # {"data_directory": "../02-data"}
│  ├─ uav-inspection-backend/       # 全部后端包，扁平放，不嵌套 src/
│  └─ uav-inspection-ui/            # Vite + Vue3
├─ deploy/                          # compose.yml / docker/ / nginx/ / scripts/ / .env.example
├─ docs/                            # 架构图、定制说明、回放数据说明
├─ scripts/                         # 离线数据生产脚本（不进镜像）
└─ 02-data/                         # 数据根，git 忽略，容器里挂成 /data
```

### B. 后端模块骨架：一个 `<domain>app` 包 = 一个业务模块

```
<domain>app/
├─ __init__.py
├─ detector.py        # 模型加载与推理（单例，如 plate_detector）
├─ recognizer.py      # 可选：二级识别/后处理
└─ api/               # 或 api/v1/
   └─ detect.py       # router = APIRouter()，不含 app 实例
```

`heatmapapp` 是例外（它是宿主：`main.py` + `api/v1/` + `services/`），其余 12 个模块都是上式。

### C. 路由注册：集中在 `heatmapapp/main.py`，路径与中文 tag 成对出现

```python
app.include_router(plate_detect.router, prefix='/api/v1/plate', tags=['车辆车牌巡检'])
```

tag 必须是中文业务名（线上 12 个 tag 全是中文，无一个英文）。`main.py:54-68` 是唯一注册处。

### D. 响应封套：`{"code": 200, "message": "success", "data": ...}`

新模块（wall / tree / power / telecom / plate）用带 `message` 的三段式；老模块
（assets / rose / pest）只有 `code` + `data`。**车牌模块已经是三段式，符合新模块口径。**

静态资源例外：媒体、卡片、报告直接 `FileResponse` / `StaticFiles` 返回二进制，不套封套。

### E. 数据与权重的落点（最容易踩的一条）

由 `deployment_paths.py` 统一定义，**绝对不在包目录里**：

| 类型 | 落点 | 代码写法 |
|---|---|---|
| 媒体/结果 | `<DATA_ROOT>/uav-inspection-backend/<domain>data/media/` | `backend_path('<domain>data', 'media')` |
| 报告 | 同上 `/reports/` | `backend_path('<domain>data', 'reports')` |
| 模型权重 | `<DATA_ROOT>/uav-inspection-backend/<domain>app/` | `backend_path('<domain>app', 'xxx-best.pt')` |

`DATA_ROOT` 由环境变量 `UAV_DATA_DIR` 决定；开发机走 `app/deployment-layout.json`（`../02-data`），
容器里是 `UAV_DATA_DIR=/data` + 命名卷 `uav-data`。

**这条的推论**：写进包目录的数据 = 进了镜像层，容器重建（`docker compose up -d --force-recreate`）
就丢，而且每次构建都要重新打包一遍。

### F. 子路径部署：三处前缀必须一致

| 层 | 变量 | 线上值 |
|---|---|---|
| 前端构建 | `VITE_BASE` | `/uav/` |
| 后端返回的 URL | `UAV_URL_PREFIX` | `/uav`（`uav_url_prefix.prefixed()`） |
| nginx | `proxy_pass http://127.0.0.1:<port>/`（**尾斜杠剥前缀**） | `/uav/` location |

前端拿 `import.meta.env.BASE_URL` 拼 API 基址；后端在 JSON 里返回的绝对 URL 必须过 `prefixed()`。

### G. SPA 回退在应用层

`heatmapapp/main.py:151` `@app.get('/{path:path}')` + `:161-163` 的 `spa_routes` 集合。
**新增页面必须往 `spa_routes` 里加一条**，否则刷新页面 404。`api`/`ws` 开头一律 404，
不会把未知接口变成 HTML。

### H. 前端接一个模块要动五个点

| 点 | 上游写法 | 车牌对应 |
|---|---|---|
| 接口客户端 | `src/api1/<domain>.ts`（复杂模块用 `src/api1/<domain>/` 多文件 + `request.ts`） | `src/api1/plate.ts` |
| 页面 | `src/views/<Domain>InspectionView.vue` | `PlateInspectionView.vue` |
| 路由 | `src/router/index.ts`，path 用 kebab-case | `/plate` |
| 首页卡片 | `HomeView.vue` 的模块数组，`{name, path, theme, icon, desc}` | 已加（136-141 行） |
| 主题色 | `src/config/moduleThemes.ts` | `plate` 已加（第 149 行） |

请求一律走 `src/utils/request.ts` 的 `request<T>()`，不自己 new axios。

### I. 素材上传中心：`assetsapp` 按分类收文件

新模块要在 `assetsapp/api.py` 注册一个上传分类（`<domain>-media` / `<domain>-model`），
让用户从页面把权重和素材传到数据根，而不是手工拷文件。

### J. 部署自检：`/api/deployment/status` + `module_status()`

每个模块要在 `deployment_readiness.py` 的 `MODEL_PATHS` 和 `module_status()` 里各登记一条，
返回"缺什么"而不是"能不能跑"。模型缺失只降级，不阻断（`configured: false` + `missing[]`）。

### K. 交付形态：单容器 + 三个 bat + `docs/`

一个镜像（前端 dist 由 FastAPI 同源托管）、`deploy/deploy.sh up|update|down|status|logs`、
Windows 侧 `首次安装.bat` / `打开车牌巡检.bat`。

---

## 3 本仓库 vs 约定：逐项对照

| # | 约定 | 本仓库现状 | 判定 |
|---|---|---|---|
| A | 目录结构 `app/` + `deploy/` + `docs/` + `02-data/` | 一致 | ✅ |
| B | `<domain>app` 包骨架 | `plateapp/{detector,recognizer,api/detect}.py` | ✅ |
| C | 路由集中注册 + 中文 tag | `main.py:68` `tags=['车辆车牌巡检']` | ✅ |
| C2 | 端点命名 | `health/info/config/detect*/acceptance`，与 wall/tree/power 同构 | ✅ |
| D | 响应封套三段式 | plate 全部 `{code,message,data}` | ✅ |
| E1 | 权重落 `<数据根>/<domain>app/` | `backend_path('plateapp','plate-det-best.pt')` | ✅ |
| E2 | 识别器落 `<数据根>/<domain>app/recognizer/` | `backend_path('plateapp','recognizer')` | ✅ |
| E3 | **媒体/结果落 `<数据根>/<domain>data/`** | **落在包目录 `plateapp/data/`（77 MB，20 个文件已入库）** | ❌ **P0** |
| F | `prefixed()` 包装返回 URL | plate 已 `from uav_url_prefix import prefixed` 并在 URL 上调用 | ✅ |
| G | `spa_routes` 含新页面 | `main.py:161` 已含 `plate` | ✅ |
| H1 | `api1/<domain>.ts` + 共享 request | `src/api1/plate.ts` 导入 `utils/request` | ✅ |
| H2 | View 命名 `<Domain>InspectionView.vue` | `PlateInspectionView.vue` | ✅ |
| H3 | 首页卡片 + 主题 | 均已加 | ✅ |
| I | assetsapp 上传分类 | 已加 `plate-media` / `plate-model` / `plate-recognizer` | ✅ |
| J1 | `MODEL_PATHS` 登记 | `deployment_readiness.py:28` | ✅ |
| J2 | `module_status()` 条目 | `:124-135` | ✅ 但内部自相矛盾，见 P1-2 |
| K | 单容器同源 | `deploy/docker/Dockerfile` 已含前端多阶段构建 | ✅ |

**四项硬偏离（E3 及其连带），三项工程隐患，两项口径瑕疵。**

---

## 4 需要调整的具体之处

### P0-1 车牌数据落在包目录里（最该先改）

**证据**

```
app/uav-inspection-backend/plateapp/api/detect.py
20: DATA_DIR = Path(__file__).resolve().parent.parent / 'data'
21: ACCEPTANCE_PATH = DATA_DIR / 'acceptance.json'
22: CARDS_DIR = DATA_DIR / 'cards'
26: TIMELINE_PATH = DATA_DIR / 'timeline.json'
27: COVERAGE_PATH = DATA_DIR / 'coverage.json'
28: MEDIA_DIR = DATA_DIR / 'media'
```

`git ls-files` 显示这 20 个文件（含 `replay.mp4` 8 MB、`rviz_process.mp4` 67 MB）**已提交进仓库**。

**为什么必须改**（四条后果，都可实测）

1. **镜像体积**：`deploy/docker/Dockerfile:37` 是 `COPY app/uav-inspection-backend/ /app/uav-inspection-backend/`，
   `.dockerignore` 没有排除它 → 每次构建把 77 MB 数据打进镜像层。
2. **容器重建丢数据**：容器里 `UAV_DATA_DIR=/data` 是命名卷，包目录在 `/app/...` 属容器可写层，
   `docker compose up -d --force-recreate` 后运行期写入（新批次的 timeline/coverage）全部丢失。
3. **自检与实际读取位置不一致**：`deployment_readiness.py:125` 查的是
   `backend_path('platedata','media')`（平台约定），`:131` 查的却是
   `plateapp/data/acceptance.json`（包目录）。同一模块两套口径，`configured` 会随文件摆放漂移。
4. **与本仓库自己的文档矛盾**：`docs/fork-customization.md:58` 写的是
   `plate-media → <数据根>/uav-inspection-backend/platedata/media/`，代码没照做。

**改法**（3 个文件，逐行）

`plateapp/api/detect.py` —— 加 import，换落点：

```python
from deployment_paths import backend_path      # 新增

DATA_DIR = backend_path('platedata')            # 原 20 行
ACCEPTANCE_PATH = DATA_DIR / 'acceptance.json'  # 以下不变
CARDS_DIR = DATA_DIR / 'cards'
TIMELINE_PATH = DATA_DIR / 'timeline.json'
COVERAGE_PATH = DATA_DIR / 'coverage.json'
MEDIA_DIR = DATA_DIR / 'media'
```

`heatmapapp/main.py` —— 与 wall 等模块写成同一种形式（`:47` 后加常量，`:51` 的 mkdir 列表加两项，
`:81-86` 改成挂常量）：

```python
PLATE_MEDIA_PATH = backend_path('platedata', 'media')     # 新增
PLATE_CARDS_PATH = backend_path('platedata', 'cards')     # 新增

# :51 的 for 列表里追加 PLATE_MEDIA_PATH, PLATE_CARDS_PATH

app.mount('/api/v1/plate/cards', StaticFiles(directory=PLATE_CARDS_PATH), name='plate_cards')
app.mount('/api/v1/plate/media', StaticFiles(directory=PLATE_MEDIA_PATH), name='plate_media')
```

`deployment_readiness.py:131` —— 去掉包目录硬编码：

```python
acceptance_ready = backend_path('platedata', 'acceptance.json').is_file()
```

**连带动作（必须做，否则页面回放空白）**

```bash
# 1) 搬文件（保留 git 历史用 git mv，只搬一次）
mkdir -p 02-data/uav-inspection-backend/platedata
git mv app/uav-inspection-backend/plateapp/data/* 02-data/uav-inspection-backend/platedata/

# 2) 02-data 已被 git 忽略，搬完要主动出仓：
git rm -r --cached app/uav-inspection-backend/plateapp/data 2>/dev/null || true

# 3) 容器部署时把数据灌进命名卷
docker cp 02-data/uav-inspection-backend/platedata uav-uav-1:/data/uav-inspection-backend/
```

第 2 步之后，仓库里不再有 75 MB 视频；第 3 步是容器部署的固定步骤，写进
`deploy/deploy.sh up` 的注释或 `docs/`。

**这条搬迁会碰到三处文档与一个孤立文件**（都在同一批里改掉，别留半截）：

| 位置 | 现状 | 搬完要改成 |
|---|---|---|
| `docs/fork-customization.md:24` | 表格里写 `plateapp/data/` | `<数据根>/uav-inspection-backend/platedata/` |
| `docs/fork-customization.md:183` | 提到 `plateapp/data/charset_ccpd.txt` | 见下一行处理 |
| `plateapp/data/charset_ccpd.txt` | 字符表留档，**代码里 0 处引用**（`grep -rn charset_ccpd` 空） | 并入 `plateapp/recognizer/charset.txt` 或随数据搬到 `platedata/`，二选一，不留在包目录 |

`docs/fork-customization.md:237` 里的 `plateapp/data/cards/car_6.jpg` 是**接口 URL 示例**
（`/api/v1/plate/cards/car_6.jpg`），搬完 URL 不变，只需改文字里的物理路径。

---

### P0-2 镜像上下文带了 61 个 pip 临时目录（71 MB）

**证据**：`app/uav-inspection-backend/` 下 `ls -d pip-* | wc -l` = **61**，`du -sh pip-*` 合计 **71 MB**。
`.gitignore` 已经忽略了 `pip-unpack-*/`、`pip-metadata-*/`，但 `.dockerignore` 没有。

**后果**：`COPY app/uav-inspection-backend/` 会把 71 MB 垃圾打进镜像；这些目录还会让
`pip install` 的缓存判定变脏。

**改法**：`.dockerignore` 追加

```
**/pip-unpack-*/
**/pip-metadata-*/
**/pip-install-*/
**/pip-ephem-wheel-cache-*/
**/torchinductor_hang/
```

顺带在开发机删一次：`rm -rf app/uav-inspection-backend/pip-*`（这些是 pip 在 Windows 上把
解包临时目录建到项目里的产物，删了不影响任何东西）。

---

### P0-3 前端 base：本机 dist 是 `/`，那台机器要 `/uav/`

**证据**：`dist/index.html` 现在是 `src="/assets/js/index-Ca3nNtWt.js"`（今天 13:33 构建，`VITE_BASE` 未传）。
线上是 `src="/uav/assets/js/index-twuMyzCZ.js"`。

**后果**：把本机 `dist` 直接拷过去 → 白屏（资源 404）；即使资源能找，`utils/request.ts:7` 拼出的
`/api/v1` 也会打到根路径上，全 404。

**改法**：**不要手拷 dist**。走既定通道，两条都默认 `/uav/`：

```bash
# 走脚本（推荐）
deploy/scripts/build_and_push.sh          # 内部 --build-arg VITE_BASE="${VITE_BASE:-/uav/}"

# 或本地只构建前端核实
cd app/uav-inspection-ui && VITE_BASE=/uav/ npm run build
```

本机日常开发用 `npm run dev`（proxy 到 8002），**不需要**改 base；只有出镜像/出静态包时要 `/uav/`。

---

### P0-4 线上没有 auth，我们的构建有登录门（取舍项）

**证据**

| 项 | 线上 | 本仓库 |
|---|---|---|
| `/api/v1/auth/{register,login,me,logout}` | 全 404，openapi 里没有 | `authapp/api.py:84,100,109,119` |
| 前端 `登录`/`注册` 文案 | 0 次 | `HomeView.vue:192` 有登录/注册/退出 |
| 路由守卫 | 无 | `src/router/index.ts` `beforeEach` 非 `/` 一律要求 `account.user` |

**后果**：把这套构建部署到那台机器，首页会变成"请登录"，所有子页面要注册后才能进——
**这是平台现状的可见变化**，不是技术问题。

**我的默认方案（可直接执行，不需要你决策）**：**保留登录，但独立部署**。
理由是这台机器的 `/uav/` 是别人的生产入口，已有用户和链接；用另一个端口/前缀
（如 `127.0.0.1:18021` + `/uav-plate/`）并存，互不影响。
真要合到同一个 `/uav/`，必须先把 auth 做成开关：

```python
# heatmapapp/main.py
if os.getenv('UAV_AUTH_ENABLED', '1') == '1':
    app.include_router(auth_api.router, prefix='/api/v1/auth', tags=['账号'])
```

前端对应 `beforeEach` 读一个运行时开关（`/api/deployment/status` 里返回 `auth_enabled`），
关掉时直接放行。这一改动约 20 行，等真正合并时再做，不提前引入分支。

---

### P1-1 `main.py` 里 plate 的静态挂载没走 `backend_path`

`main.py:81-86` 直接 `plate_detect.CARDS_DIR.mkdir(...)` + `app.mount(..., directory=plate_detect.CARDS_DIR)`，
而 wall 等模块是 `WALL_MEDIA_PATH = backend_path(...)` + `app.mount(..., directory=WALL_MEDIA_PATH)`。
**这是 P0-1 的同一处问题在宿主侧的表现**，改 P0-1 时一并改掉，让 12 个模块的挂载写法完全同构。

### P1-2 `media_roots` 漏了 plate

`main.py:111-112` 的 `media_roots` 列了 9 个模块的媒体目录，**没有 plate**。
后果：`/api/deployment/status` 的 `data_available` 不含车牌素材，前端"部署提示"在只有车牌数据时会误报。
改法：`media_roots` 里追加 `PLATE_MEDIA_PATH`（随 P0-1 一起加）。

### P1-3 `02-data` 里已有 `platedata`，但内容不完整

`02-data/uav-inspection-backend/platedata/media/` 里只有 6 张 `car_*.png`，
而 `plateapp/data/` 里是完整的一套（cards 7 张 + 4 个 json + 9 个媒体）。
说明这个目录**曾经被建过、后来没维护**。P0-1 的 `git mv` 会把两边合并成一个，之后只留这一处。

### P2-1 缺数据时返回 HTTP 200 + 体内 `code: 404`

`plateapp/api/detect.py:267,283,308`：

```python
return {'code': 404, 'message': '未找到验收回放数据', 'data': {'available': False}}
```

HTTP 状态是 200。平台其他模块遇到缺数据走 `HTTPException(status_code=404, detail='中文')`。
**口径不一致的真实代价**：网关/监控按 HTTP 状态判健康，会始终认为这三个接口正常。
建议保留体内 `code`（前端已在用），但**同时**把 HTTP 状态码设成 404：

```python
return JSONResponse(status_code=404, content={'code': 404, 'message': '未找到验收回放数据',
                                              'data': {'available': False}})
```

### P2-2 `docs/fork-customization.md:24` 写的体积已过时

原文"内置一次真实验收的回放数据与 7 张识别结果卡（约 1 MB）"，实际现在 **77 MB**
（加了 `replay.mp4` 8 MB 与 `rviz_process.mp4` 67 MB）。P0-1 搬完之后这段要一并改写，
说明"数据不在仓库内，部署时灌入数据卷"。

### P2-3 `scripts/` 与 `scripts/onsite/` 的定位要写清

根 `scripts/` 里有 `build_replay.py` / `gen_acceptance.py` / `check_replay_data.py`（离线数据生产）
和 `scripts/onsite/`（只能在 Ubuntu 实机上跑的两个脚本）。
Dockerfile 只 `COPY app/...`，所以它们**不会进镜像**——这是对的，但需要在
`docs/plate-replay-data.md` 里写一句"这些脚本不随镜像分发，数据在出镜像前生成好"，
否则接入方会以为容器里能跑。

---

## 5 落地顺序（建议）

| 步骤 | 动作 | 预计 | 验证 |
|---|---|---|---|
| 1 | P0-1 三个文件改动 + `git mv` 数据 + `git rm --cached` | 30 min | `python -c "import"` 起服务，`/api/v1/plate/acceptance` 有数据；`git status` 不再出现 video |
| 2 | P0-2 `.dockerignore` 追加 + 删本地 `pip-*` | 5 min | `docker build --no-cache` 镜像体积对比 |
| 3 | P1-1 / P1-2 宿主侧同构化 | 10 min | `/api/deployment/status` 的 `data_available` 为 true |
| 4 | P2-1 三处 HTTP 状态码 | 10 min | `curl -o /dev/null -w '%{http_code}'` 得 404 |
| 5 | 出镜像（`VITE_BASE=/uav/`）+ 部署到**独立端口** | 20 min | 见第 6 节 |
| 6 | 若要并入 `/uav/`：加 auth 开关 + 合并 | 40 min | 首页不弹登录、`/uav/plate` 200 |

---

## 6 接入验收清单（可直接复制执行）

```bash
H=http://10.50.2.92/uav

# 1) 页面级：SPA 路由通（应用层 spa_routes 生效）
for p in "" pest wall plate; do
  printf "%-10s %s\n" "/$p" "$(curl -s -o /dev/null -w '%{http_code}' $H/$p)"
done
# 期望：200 200 200 200（plate 只有在部署了我们的构建后才是 200）

# 2) 接口级：车牌 10 个端点全在
curl -s $H/openapi.json | python -c "import sys,json;d=json.load(sys.stdin);\
print(sorted(p for p in d['paths'] if '/plate' in p))"
# 期望：10 条，/health /info /config(GET,POST) /detect /detect/upload /detect/video
#       /acceptance /replay /coverage

# 3) 资源级：静态挂载与媒体 Range
curl -sI $H/api/v1/plate/media/rviz_process.mp4 | head -5
# 期望：200 或 206，Content-Type: video/mp4，Accept-Ranges: bytes

# 4) 前缀一致性：接口返回的 URL 必须带 /uav
curl -s $H/api/v1/plate/coverage | python -c "import sys,json;d=json.load(sys.stdin);\
print(d['data']['rviz']['src'])"
# 期望：/uav/api/v1/plate/media/rviz_process.mp4

# 5) 部署自检：plate 条目存在且 configured
curl -s $H/api/deployment/status | python -c "import sys,json;d=json.load(sys.stdin)['data'];\
print(d['modules']['plate'])"
# 期望：{'title':'车辆车牌巡检','route':'/plate','configured':True,'missing':[],...}
```

---

## 7 一句话总结

**架构早就同源，接口风格已经对齐，真正卡住"直接接入"的是数据落点和镜像卫生**——
把 `plateapp/data/` 搬回 `platedata/`、把 61 个 pip 临时目录挡在镜像外、
出包时带上 `VITE_BASE=/uav/`，这套代码就能以最小改动挂到那台机器的 `/uav/` 下。
登录门是唯一需要产品判断的地方，已给默认方案（独立端口并存，不动机器上现有入口）。

---

## 8 执行记录（2026-11-16 19:5x）

P0-1 / P0-2 / P1-1 / P1-2 / P1-3 / P2-1 / P2-2 / P2-3 已落地。P0-3（构建参数）属出包动作，
P0-4（auth 开关）按第 4 节留到真正并入 `/uav/` 时再做。

### 改了什么

| 文件 | 改动 |
|---|---|
| `plateapp/api/detect.py` | `DATA_DIR = backend_path('platedata')`；三个缺数据端点改 `JSONResponse(404)` 并加 `response_model=None` |
| `heatmapapp/main.py` | 新增 `PLATE_MEDIA_PATH` / `PLATE_CARDS_PATH`（`backend_path('platedata', ...)`），进 mkdir 列表，挂载改常量；`media_roots` 补 `PLATE_MEDIA_PATH` |
| `deployment_readiness.py` | `acceptance_ready` 改走 `backend_path('platedata','acceptance.json')`；删掉已无用的 `Path` 导入 |
| `.dockerignore` | 排掉 `plateapp/data/` 与 6 类 `pip-*` / `torchinductor_hang` |
| `app/scripts/build_delivery.py` | `RUNTIME_DIRS` 加 `platedata`，`ACTIVE_WEIGHTS` 加 `plateapp/plate-det-best.pt`，删掉指向不存在目录的空转段 |
| `scripts/{check_replay_data,add_rviz_block,build_replay,gen_acceptance}.py` | 默认路径与用法示例改到 `02-data/uav-inspection-backend/platedata` |
| `docs/fork-customization.md`、`docs/plate-replay-data.md` | 路径与体积口径改写；补第 7 节「数据放哪、脚本随不随镜像」 |

### 数据搬迁

- `git rm -r --cached app/uav-inspection-backend/plateapp/data` → 20 个文件出仓（含 `rviz_process.mp4` 67 MB、`replay.mp4` 8 MB），**仓库不再跟踪车牌回放素材**；
- 文件复制到 `02-data/uav-inspection-backend/platedata/`，逐文件 `cmp` 全等（20/20）；与原有 6 张 `car_*.png` 合并后 25 个文件、80 MB；
- `charset_ccpd.txt` 归到 `02-data/uav-inspection-backend/plateapp/recognizer/`（模型侧，代码不读它）。

### 验证

| 项 | 结果 |
|---|---|
| `py_compile`（4 个 py） | 退出码 0 |
| `import heatmapapp.main` | 通过（43 个顶层路由对象，此版 FastAPI 用 `_IncludedRouter` 包裹子路由） |
| `/api/v1/plate/{acceptance,replay,coverage}`（有数据） | 全 200，`code=200`，字段齐全；`coverage.rviz.src` 带 `?v=1794803534` |
| 同上（`UAV_DATA_DIR` 指向空目录、另起 8011） | 全 **HTTP 404** + 体内 `code=404`；`module_status.plate.configured=false`，缺 `plate-media` / `plate-model` |
| `/api/v1/plate/media/rviz_process.mp4`、`/cards/car_6.jpg`、`/media/replay.mp4` | 全 200 |
| `scripts/check_replay_data.py`（默认新路径） | **13 通过 / 0 WARN / 0 FAIL** |

### 顺带修掉的三处既有缺陷

1. `build_delivery.py` 原「车牌回放随源码走」那段走的是 `backend/"plateapp"/"data"`，而该目录从来不存在——**一直是空转**，交付包里从来没有回放数据；现由 `RUNTIME_DIRS` 统一收。
2. `ACTIVE_WEIGHTS` 缺 `plateapp/plate-det-best.pt`，数据包里不会带车牌权重。
3. `docs/plate-replay-data.md` 两处失真：接口写成 `/api/v1/plate/timeline`（实际 `/replay`）、批次写 p10（实际 p12）。
