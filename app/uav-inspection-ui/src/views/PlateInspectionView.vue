<script setup lang="ts">
import { computed, markRaw, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ChevronRight, ClipboardList, Film, Layers, Maximize2, Minimize2, RefreshCw } from 'lucide-vue-next'
import { useRoute } from 'vue-router'
import InspectionHeader from '../components/common/InspectionHeader.vue'
import PlaybackRateMenu from '../components/common/PlaybackRateMenu.vue'
import ReplayTransport from '../components/common/ReplayTransport.vue'
import {
  plateApi,
  type AcceptanceData,
  type CoverageData,
  type PlatePathData,
  type ReplayData,
  type ReplayPhase,
} from '../api1/plate'

// 2026-11-20 改版：删除「实时检测」模块（单张图检测工具，与巡检演示主线无关）。
// 「过程回放」与「覆盖质量」原本是两个切换页，现合并为一页四宫格，靠同一时间轴驱动。
// 页内只剩两个视图，不再有回放/覆盖之间的模块切换。
type TabKey = 'result' | 'mission'

const route = useRoute()

const LEGACY_ALIAS: Record<string, TabKey> = { replay: 'mission', coverage: 'mission', detect: 'mission', mission: 'mission', result: 'result' }
const initialView = LEGACY_ALIAS[String(route.query.view ?? '')] ?? 'mission'
const activeTab = ref<TabKey>(initialView)
const tabs: ReadonlyArray<{ key: TabKey; label: string; icon: unknown }> = [
  { key: 'mission', label: '巡检过程', icon: markRaw(Film) },
  { key: 'result', label: '巡检结果', icon: markRaw(ClipboardList) },
]
const refreshing = ref(false)
const online = ref<boolean | null>(null)
const acceptance = ref<AcceptanceData | null>(null)
const loadingAcceptance = ref(false)
const replay = ref<ReplayData | null>(null)
const loadingReplay = ref(false)
const replayError = ref('')
const coverage = ref<CoverageData | null>(null)
const loadingCoverage = ref(false)
const videoTime = ref(0)
const playing = ref(false)
const previewCard = ref('')

// 四宫格里的两个视频源：总览用 Gazebo 俯视录屏，其余三格从 RViz 全屏录屏里裁。
// 三格要同时显示同一段录屏的不同区域，只能各挂一个 video 元素（一个元素占一个位置），
// 所以用一个数组收三个实例，同步时统一 follow。
const overviewEl = ref<HTMLVideoElement | null>(null)
const rvizEls = ref<Array<HTMLVideoElement | null>>([null, null])
function bindRviz(index: number) {
  return (el: unknown) => {
    rvizEls.value[index] = (el as HTMLVideoElement | null) ?? null
  }
}

// ---------------- 放大观看 / 播放倍速（2026-11-20 新增） ----------------
/**
 * 四个窗格都能单独放大到整屏。实现不是「再开一份播放器」，而是把同一个 <figure>
 * 用 position:fixed 撑满视口：video 元素还是原来那一个，时间轴不断、播放不中断，
 * 也就不需要让两份视频互相同步（那样必然出漂移，四格又对不上了）。
 */
type CellKey = 'overview' | 'onboard' | 'viewpoint' | 'path'

const zoomCell = ref<CellKey | null>(null)

// 倍速是全局的：四格共用一条时间轴，单格变速会让四格当场错开。
// 四个入口（每格一个 + 放大顶栏一个）改的都是这一个值。
const playbackRate = ref(1)

function openZoom(cell: CellKey) {
  zoomCell.value = cell
}
function closeZoom() {
  zoomCell.value = null
}

/** 把当前倍速应用到所有视频实例（RViz 裁剪格是按需挂载的，得跟着补设） */
function applyRate() {
  const els = [overviewEl.value, ...rvizEls.value]
  for (const el of els) {
    if (el && el.playbackRate !== playbackRate.value) el.playbackRate = playbackRate.value
  }
}
watch(playbackRate, () => applyRate())

// 放大时锁背景滚动。中栏是独立滚动容器，只锁 body 不够，模板里还有一处 overflow 切换。
watch(zoomCell, (cell) => {
  document.body.style.overflow = cell ? 'hidden' : ''
})

function onWindowKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && zoomCell.value) closeZoom()
}
onMounted(() => window.addEventListener('keydown', onWindowKeydown))
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onWindowKeydown)
  document.body.style.overflow = ''
})

const summaryCards = computed(() => acceptance.value?.summary ?? [])
const vehicles = computed(() => acceptance.value?.vehicles ?? [])
const violations = computed(() => acceptance.value?.violations ?? [])
const violatedCount = computed(() => violations.value.filter((item) => item.margin_m < 0).length)
const batchLabel = computed(() => {
  const batch = acceptance.value?.batch
  if (!batch) return '尚未载入巡检批次'
  return `${batch.start} 起 · ${batch.fsm}`
})
// 「巡检结果」与「过程回放」是两份独立 JSON，可能来自不同跑次（2026-11-16 实测：
// 结果 p10_v2_final2_20261114、回放 p9_v2_final_20261114）。不同就必须在页面上说出来，
// 否则演示时两处时间对不上却没人知道为什么。
const acceptanceRun = computed(() => {
  const dir = (acceptance.value?.batch?.batch_dir ?? '').replace(/[\\/]+$/, '')
  return dir.split(/[\\/]/).pop() ?? ''
})
const replayRun = computed(() => replay.value?.mission?.run ?? '')
const batchMismatch = computed(
  () => Boolean(acceptanceRun.value && replayRun.value && acceptanceRun.value !== replayRun.value),
)
const statusText = computed(() => {
  if (online.value === false) return '后端离线'
  if (loadingReplay.value || loadingCoverage.value) return '正在载入录屏'
  return '就绪 · 双源录屏'
})

async function refreshHealth() {
  try {
    await plateApi.getHealth()
    online.value = true
  } catch {
    online.value = false
  }
}

async function refreshAll() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    await refreshHealth()
    // 巡检过程页需要回放与覆盖两份数据；结果页只拉验收数据。
    if (activeTab.value === 'result') await loadAcceptance()
    else await Promise.all([loadReplay(), loadCoverage(), loadPath()])
  } finally {
    refreshing.value = false
  }
}

async function loadAcceptance() {
  loadingAcceptance.value = true
  try {
    const result = await plateApi.getAcceptance()
    acceptance.value = result.data?.available ? result.data : null
  } catch {
    acceptance.value = null
  } finally {
    loadingAcceptance.value = false
  }
}

function showCard(url: string | null) {
  previewCard.value = url || ''
}

// ---------------- 过程回放 / 覆盖质量 ----------------

async function loadReplay() {
  if (loadingReplay.value) return
  loadingReplay.value = true
  replayError.value = ''
  try {
    const result = await plateApi.getReplay()
    replay.value = result.data?.available === false ? null : (result.data ?? null)
    if (!replay.value) replayError.value = '服务端没有找到 timeline.json，回放数据不可用。'
  } catch (err) {
    replay.value = null
    replayError.value = err instanceof Error ? err.message : '回放数据加载失败'
  } finally {
    loadingReplay.value = false
  }
}

async function loadCoverage() {
  if (loadingCoverage.value) return
  loadingCoverage.value = true
  try {
    const result = await plateApi.getCoverage()
    coverage.value = result.data?.available === false ? null : (result.data ?? null)
  } catch {
    coverage.value = null
  } finally {
    loadingCoverage.value = false
  }
}

// 2026-11-20：第四格改成俯视路径图，数据来自 /plate/path（从任务日志 GOTO 序列重建）。
const pathData = ref<PlatePathData | null>(null)
const loadingPath = ref(false)

async function loadPath() {
  if (loadingPath.value) return
  loadingPath.value = true
  try {
    const result = await plateApi.getPath()
    pathData.value = result.data?.steps?.length ? result.data : null
  } catch {
    pathData.value = null
  } finally {
    loadingPath.value = false
  }
}

function fmtTime(sec: number) {
  const total = Math.max(0, Math.round(sec))
  const m = Math.floor(total / 60)
  return `${m}:${String(total % 60).padStart(2, '0')}`
}

// ---------------- 四宫格：两路录屏 + 数据化路径点 ----------------

/**
 * 2026-11-20 用像素亮度跳变实测的分区（1920×1080，非目测）：
 *   左栏 x 0..476 分三段，第 2 段 y451..768 是机载视角，第 3 段 y775..1050 是深度灰度图；
 *   右侧 x477..1920、y47..984 是 RViz 三维视图，点云与占据栅格都在这里。
 * 四格统一按 16:10 显示，所以每块都按 1.6 重新取中（x 从 54 起是为了避开 Ubuntu 左侧栏，
 * 那段是深紫竖条，留在画面里很难看）。取中后不裁切，四格等高对齐。
 */
const RVIZ_W = 1920
const RVIZ_H = 1080
const CELL_RATIO = 2.2

const RV_SLOTS = {
  onboard: { x: 54, y: 470, w: 422, h: 264 },
  // 2026-11-20：原「深度相机视角」那一格用户明确不要（灰度图对巡检演示无信息量），
  // 换成 RViz 三维视图的中央放大区——同一块画面里能看到无人机位姿（红绿坐标轴）、
  // 指向当前拍摄目标的灰色相机视锥、以及被拍车辆的橙色点云。
  viewpoint: { x: 760, y: 300, w: 960, h: 600 },
} as const

/**
 * 把「原视频中的一块矩形」铺进一个固定 16:10 的容器：
 * 以容器宽为 1 个单位推缩放，再换算成 CSS 百分比（width/left 相对容器宽，height/top 相对容器高）。
 * 裁剪区比例与 16:10 不完全一致，四边最多裁掉约 4%，换取四格等高不错位。
 */
function cropStyle(box: { x: number; y: number; w: number; h: number }) {
  const s = 1 / box.w
  const vidW = RVIZ_W * s
  const vidH = RVIZ_H * s
  const cellH = 1 / CELL_RATIO
  const left = -box.x * s
  const top = cellH / 2 - (box.y + box.h / 2) * s
  return {
    width: `${vidW * 100}%`,
    height: `${(vidH / cellH) * 100}%`,
    left: `${left * 100}%`,
    top: `${(top / cellH) * 100}%`,
    // 必须写进 inline style：Tailwind preflight 给 video 定了 max-width:100%，
    // 单靠 max-w-none 这个类在这套构建里压不住，实测 computed 仍是 100%，
    // 会把 403% 的宽度压回容器宽，画面变成整幅而不是裁出的一个窗口。
    maxWidth: 'none',
    maxHeight: 'none',
    objectFit: 'fill' as const,
  }
}
// ---------------- 第四格：俯视路径图（数据来自任务日志的 GOTO 序列） ----------------
// 2026-11-20：原本这里是 RViz 点云全景，与第三格内容重叠；改成按日志重建的路径图。
// 坐标口径见后端 /plate/path 的 docstring：front/* 按车轴前推 d 米复算，transit/* 取车坐标。
const PATH_SCALE = 10 // 1 m = 10 个 SVG 单位
const pathGeom = computed(() => {
  const d = pathData.value
  if (!d || !d.steps.length) return null
  const { x0, x1, y0, y1 } = d.area
  const w = (x1 - x0) * PATH_SCALE
  const h = (y1 - y0) * PATH_SCALE
  const px = (x: number) => (x - x0) * PATH_SCALE
  const py = (y: number) => (y1 - y) * PATH_SCALE // ROS 的 y 向上，SVG 向下，这里翻转
  const cars = d.cars.map((c) => ({ ...c, cx: px(c.x), cy: py(c.y), deg: (-c.yaw * 180) / Math.PI }))
  const steps = d.steps.map((s, idx) => ({ ...s, idx, cx: px(s.x), cy: py(s.y) }))
  return { w, h, cars, steps, x0, x1, y0, y1 }
})

const pathNow = computed(() => videoTime.value + (replay.value?.video.offset_s ?? 0))
const pathCursor = computed(() => {
  const g = pathGeom.value
  if (!g) return -1
  let last = -1
  for (let i = 0; i < g.steps.length; i += 1) {
    if (g.steps[i].t <= pathNow.value) last = i
    else break
  }
  return last
})
const pathWalked = computed(() => {
  const g = pathGeom.value
  const c = pathCursor.value
  if (!g || c < 0) return ''
  return g.steps.slice(0, c + 1).map((s) => `${s.cx.toFixed(1)},${s.cy.toFixed(1)}`).join(' ')
})
const pathAll = computed(() => {
  const g = pathGeom.value
  if (!g) return ''
  return g.steps.map((s) => `${s.cx.toFixed(1)},${s.cy.toFixed(1)}`).join(' ')
})
const pathActive = computed(() => {
  const g = pathGeom.value
  const c = pathCursor.value
  return g && c >= 0 ? g.steps[c] : null
})

/** 每 5 m 一条网格线，给俯视图一个尺度参照 */
const pathGrid = computed(() => {
  const g = pathGeom.value
  if (!g) return { x: [] as number[], y: [] as number[] }
  const xs: number[] = []
  const ys: number[] = []
  for (let m = Math.ceil(g.x0 / 5) * 5; m <= g.x1; m += 5) xs.push((m - g.x0) * PATH_SCALE)
  for (let m = Math.ceil(g.y0 / 5) * 5; m <= g.y1; m += 5) ys.push((g.y1 - m) * PATH_SCALE)
  return { x: xs, y: ys }
})

const onboardStyle = cropStyle(RV_SLOTS.onboard)
const viewpointStyle = cropStyle(RV_SLOTS.viewpoint)

/**
 * 放大态的覆盖样式：按裁剪区的宽度定标，高度按 16:9 自己推出，再用 translate 把
 * 裁剪区中心对到容器中心。
 *
 * 不能沿用 cropStyle：那套 left/top/width/height 全是百分比，width 相对容器宽、
 * height 相对容器高，只有容器比例恰好等于裁剪区比例时画面才不变形；整屏放大后
 * 容器变成视口比例，直接套会横向压扁。
 *
 * 这里的关键是 translate 的百分比以**元素自身尺寸**为基准（不是容器），
 * 所以「视频宽度 = k 倍容器宽 → 居中偏移」可以完全脱离容器比例计算。
 */
function zoomCropStyle(box: { x: number; y: number; w: number; h: number }) {
  const k = RVIZ_W / box.w // 视频宽度是容器宽的多少倍
  const nx = (box.x + box.w / 2) / RVIZ_W // 裁剪区中心在整幅里的相对位置
  const ny = (box.y + box.h / 2) / RVIZ_H
  return {
    position: 'absolute' as const,
    left: '50%',
    top: '50%',
    width: `${k * 100}%`,
    height: 'auto',
    // 竖屏时「按宽度定标」算出的高度会小于容器高，上下露黑边；
    // minHeight 兜底 + object-fit: cover 让内容始终等比铺满，不拉伸。
    minHeight: '100%',
    objectFit: 'cover' as const,
    aspectRatio: `${RVIZ_W} / ${RVIZ_H}`,
    transform: `translate(${(-nx * 100).toFixed(2)}%, ${(-ny * 100).toFixed(2)}%)`,
    maxWidth: 'none',
    maxHeight: 'none',
  }
}

const onboardZoomStyle = zoomCropStyle(RV_SLOTS.onboard)
const viewpointZoomStyle = zoomCropStyle(RV_SLOTS.viewpoint)

const overviewOffset = computed(() => replay.value?.video.offset_s ?? 0)
const rvizOffset = computed(() => coverage.value?.rviz?.offset_s ?? overviewOffset.value)

/**
 * 按墙钟对齐两段录屏：wall = 视频秒 + 录屏起点偏移，两路 wall 相等即同一时刻。
 * 总览 209.3 s 起录、RViz 209 s 起录，差 0.3 s；写成公式而不是写死 0.3，
 * 换批次时自动跟随。
 */
function followOverview() {
  const a = overviewEl.value
  if (!a) return
  const target = a.currentTime + (overviewOffset.value - rvizOffset.value)
  if (!Number.isFinite(target)) return
  // 容差随倍速放宽：4× 时 timeupdate 的间隔没变、每次前进的秒数却是 4 倍，
  // 还用 0.35 s 会因两路解码速度微差而反复纠偏，画面一顿一顿。
  const tol = 0.35 * Math.max(1, playbackRate.value)
  for (const b of rvizEls.value) {
    if (!b) continue
    if (Math.abs(b.currentTime - target) > tol) {
      b.currentTime = Math.max(0, target)
    }
  }
}

function onVideoTime(e: Event) {
  const el = e.target as HTMLVideoElement
  videoTime.value = el.currentTime
  // RViz 裁剪格是按需挂载的，挂载那一刻会回落到 1×；每帧顺手补设一次，代价可忽略。
  if (el.playbackRate !== playbackRate.value) applyRate()
  followOverview()
}

/**
 * 录屏开头几秒 RViz 还在初始化，三格会全是黑块。元数据到手后直接跳到第 5 秒，
 * 保证第一屏就有画面；只在用户还没动过进度时跳，避免覆盖手动定位。
 */
function onOverviewReady() {
  const el = overviewEl.value
  if (!el) return
  applyRate()
  if (el.currentTime < 1 && (el.duration || 0) > 6) {
    el.currentTime = 5
    videoTime.value = 5
    followOverview()
  }
}

function onPlayState(e: Event) {
  const a = e.target as HTMLVideoElement
  playing.value = !a.paused
  if (playing.value) applyRate()
  for (const b of rvizEls.value) {
    if (!b) continue
    if (playing.value) void b.play().catch(() => undefined)
    else b.pause()
  }
}

function togglePlay() {
  const a = overviewEl.value
  if (!a) return
  if (a.paused) void a.play().catch(() => undefined)
  else a.pause()
}

function seekToPhase(ph: ReplayPhase) {
  const el = overviewEl.value
  if (!el) return
  const target = Math.max(0, ph.t0 - overviewOffset.value)
  el.currentTime = target
  videoTime.value = target
  followOverview()
  void el.play().catch(() => undefined)
}

// 进度条拖动：以总览为主时钟，三格跟随（与 timeupdate 同一套对齐逻辑）
function seekTo(t: number) {
  const el = overviewEl.value
  if (!el || !Number.isFinite(t)) return
  el.currentTime = t
  videoTime.value = t
  followOverview()
  applyRate()
}

const phaseCursor = computed(() => {
  const phases = replay.value?.phases ?? []
  const wall = videoTime.value + overviewOffset.value
  for (let i = 0; i < phases.length; i += 1) {
    if (wall >= phases[i].t0 && wall < phases[i].t1) return i
  }
  return phases.length ? phases.length - 1 : -1
})

const currentPhase = computed(() => replay.value?.phases?.[phaseCursor.value] ?? null)

/**
 * 每段的「在做什么 / 产出什么」。操作描述走流程常量（不随跑次变），
 * 结果取 timeline.json 的 detail（随批次变），避免把 7 辆、6 辆这类数字写死在前端。
 */
const PHASE_TEXT: Record<string, { action: string }> = {
  survey: { action: '沿弓字航线巡航整个场区，机载深度相机逐帧建云，同步检测车位与车牌候选。' },
  inspect_r1: { action: '按规划视点逐车进近，每车远、近、补三视角拍摄，逐帧校验源帧位姿后整组准入。' },
  inspect_r2: { action: '只对上一轮未达标的目标补拍，已认定的车不重复进近。' },
  wrap: { action: '停止巡航节点、清理场景，返航到起降点并降落上锁。' },
}
const phaseAction = computed(() => {
  const key = currentPhase.value?.key ?? ''
  return PHASE_TEXT[key]?.action ?? '等待载入时间轴。'
})
const phaseResult = computed(() => currentPhase.value?.detail ?? '—')

const coverageRviz = computed(() => coverage.value?.rviz ?? null)
const coverageRows = computed(() => coverage.value?.rows ?? [])
const coverageSlots = computed(() => coverage.value?.slots ?? [])
const budgetUsedPct = computed(() => {
  const b = replay.value?.budget
  if (!b || !b.budget_s) return 0
  return Math.min(100, Math.round((b.wall_clock_s / b.budget_s) * 100))
})

watch(activeTab, (tab) => {
  if (tab !== 'mission') return
  if (!replay.value && !loadingReplay.value) void loadReplay()
  if (!coverage.value && !loadingCoverage.value) void loadCoverage()
  if (!pathData.value && !loadingPath.value) void loadPath()
}, { immediate: true })

// 从首页再次点入口而当前已经在本页时，query 变化要能切过去（含旧参数 replay / coverage）
watch(() => route.query.view, (view) => {
  const next = LEGACY_ALIAS[String(view ?? '')]
  if (next) activeTab.value = next
})

onMounted(async () => {
  await refreshHealth()
  await loadAcceptance()
})

// ---------------- 三栏工作台：批次 KPI / 左下角页内导航 ----------------
const stageTitle = computed(() => tabs.find((tab) => tab.key === activeTab.value)?.label ?? '巡检过程')
// 优先用回放的批次 KPI（整轮最权威的口径）；回放没载入时退回巡检结果的车辆清单
/**
 * 左栏「自动巡航与补拍」说明卡。
 *
 * 三步对应真实状态机（SURVEY → SCHEDULE → INSPECT → DONE，见 platedata/timeline.json
 * 的 events 字段）：巡航落一份待拍清单、按清单逐车拍、按认定率缺口补拍。
 * 这里只讲流程，辆数与时长交给下方阶段条与上方 KPI，避免同一件事在页面上写两遍数字。
 */
const FLOW_STEPS = [
  { title: '巡航发现', desc: '沿弓字航线扫全场，深度相机边飞边建云，定位车位与车牌候选。' },
  { title: '逐车拍摄', desc: '按清单逐车进近，每车备远、近、补三个机位。' },
  { title: '缺口补拍', desc: '按认定率算缺口，只补没拍成的车，不再全场重飞。' },
]

/** 本批次的拍摄账：N 辆 → 首轮拍成 X 辆 → 补拍 Y 辆 → Z/N 达标（全部取自 timeline.json） */
const flowNote = computed(() => {
  const k = replay.value?.kpi
  const first = k?.rounds?.[0]
  if (!k || !first) return ''
  const laterCars = k.rounds.slice(1).reduce((sum, r) => sum + r.cars, 0)
  const parts = [`${k.n_cars} 辆`, `首轮拍成 ${first.captured} 辆`]
  if (laterCars > 0) parts.push(`补拍 ${laterCars} 辆`)
  parts.push(`${k.n_captured}/${k.n_cars} 达标`)
  return parts.join(' → ')
})

const kpi = computed(() => {
  const nCars = replay.value?.kpi.n_cars ?? vehicles.value.length
  const nCaptured = replay.value?.kpi.n_captured ?? vehicles.value.filter((v) => Boolean(v.plate && v.plate.trim())).length
  const violated = violatedCount.value
  const run = (replay.value?.mission.run || acceptanceRun.value || '').trim()
  return {
    nCars,
    nCaptured,
    violated,
    pending: Math.max(0, nCars - nCaptured),
    wallText: acceptance.value?.summary.find((row) => row.label.includes('墙钟'))?.value
      ?? (replay.value?.budget.wall_clock_s ? `${replay.value.budget.wall_clock_s} s` : '—'),
    runShort: run ? (run.split(/[\\/]/).filter(Boolean).pop() ?? '').slice(0, 22) : '',
    rate: nCars ? Math.round((nCaptured / nCars) * 100) : 0,
  }
})
// 环形图三段必须互斥：已认定且未越界 / 已认定但越界 / 未认定。
// 早前直接把「已认定 7」与「越界 4」拼成两段，合计 11 > 总数 7，角度溢出被浏览器裁掉。
const ring = computed(() => {
  const total = Math.max(1, kpi.value.nCars)
  const flagged = new Set(violations.value.filter((row) => row.margin_m < 0).map((row) => row.car))
  const captured = new Set(vehicles.value.filter((row) => Boolean(row.plate && row.plate.trim())).map((row) => row.car))
  const both = [...captured].filter((car) => flagged.has(car)).length
  const clean = Math.max(0, captured.size - both)
  const miss = Math.max(0, kpi.value.nCars - captured.size)
  const a = (clean / total) * 360
  const b = ((clean + both) / total) * 360
  return { clean, both, miss, gradient: `conic-gradient(#2563eb 0 ${a}deg, #f43f5e ${a}deg ${b}deg, #e2e8f0 ${b}deg 360deg)` }
})
</script>

<template>
  <div class="relative min-h-screen overflow-x-hidden bg-slate-50 text-slate-800 xl:flex xl:h-screen xl:min-h-0 xl:flex-col xl:overflow-hidden">
    <div class="relative z-10 w-full shrink-0 px-4 pt-4 md:px-5">
      <InspectionHeader title="无人机车牌巡检" :task-name="batchLabel" task-label="巡检批次" :online="online">
        <template #actions>
          <button
            class="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-sm font-medium text-slate-700 transition hover:border-indigo-300 hover:bg-indigo-50"
            :disabled="refreshing"
            @click="refreshAll"
          >
            <RefreshCw :size="16" :class="refreshing ? 'animate-spin' : ''" />
            {{ refreshing ? '刷新中…' : '刷新数据' }}
          </button>
        </template>
      </InspectionHeader>
    </div>

    <main class="relative z-10 grid grid-cols-1 gap-3 px-4 pb-6 pt-3 md:px-5 xl:min-h-0 xl:flex-1 xl:grid-cols-[232px_minmax(0,1fr)_266px] xl:overflow-hidden">
      <!-- ===== 左栏：批次遥测 → 认定分布 → 左下角功能坞 ===== -->
      <aside class="order-2 flex min-h-0 flex-col gap-3 xl:order-none xl:overflow-y-auto xl:pr-0.5">
        <section class="rounded-lg border border-slate-200 bg-white p-3.5">
          <div class="mb-3 flex items-center justify-between gap-2">
            <h2 class="flex items-center gap-1.5 text-xs font-semibold text-slate-900">
              <span class="h-1.5 w-1.5 rounded-full" :class="online ? 'bg-emerald-500' : 'bg-slate-400'"></span>
              批次遥测
            </h2>
            <span class="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[9px] tracking-wide text-slate-500">UAV · PLATE V2</span>
          </div>
          <div class="grid grid-cols-2 gap-x-2 gap-y-2.5">
            <div>
              <span class="text-[10px] text-slate-400">在册车辆</span>
              <strong class="mt-0.5 block text-lg font-semibold leading-tight text-slate-900 tabular-nums">{{ kpi.nCars }}<small class="ml-0.5 text-[10px] font-normal text-slate-400">辆</small></strong>
            </div>
            <div>
              <span class="text-[10px] text-slate-400">已认定</span>
              <strong class="mt-0.5 block text-lg font-semibold leading-tight text-slate-900 tabular-nums">{{ kpi.nCaptured }}<small class="ml-0.5 text-[10px] font-normal text-slate-400">辆</small></strong>
            </div>
            <div>
              <span class="text-[10px] text-slate-400">越界判定</span>
              <strong class="mt-0.5 block text-lg font-semibold leading-tight tabular-nums" :class="kpi.violated ? 'text-rose-600' : 'text-slate-900'">{{ kpi.violated }}<small class="ml-0.5 text-[10px] font-normal text-slate-400">辆</small></strong>
            </div>
            <div>
              <span class="text-[10px] text-slate-400">墙钟 / 预算</span>
              <strong class="mt-0.5 block text-sm font-semibold leading-tight text-slate-900 tabular-nums">{{ kpi.wallText }}</strong>
            </div>
          </div>
          <div class="mt-3 flex items-center justify-between gap-2 border-t border-slate-100 pt-2">
            <span class="flex items-center gap-1 rounded bg-slate-100 px-1.5 py-0.5 text-[9.5px] text-slate-600">
              <span class="h-1 w-1 rounded-full" :class="online ? 'bg-emerald-500' : 'bg-rose-500'"></span>{{ statusText }}
            </span>
            <span class="text-[9px] text-slate-400">{{ kpi.runShort || '无批次' }}</span>
          </div>
        </section>

        <section class="rounded-lg border border-slate-200 bg-white p-3.5">
          <div class="mb-2.5 flex items-center justify-between gap-2">
            <h2 class="flex items-center gap-1.5 text-xs font-semibold text-slate-900">车牌认定占比</h2>
            <span class="text-[9px] tracking-widest text-slate-400">AI</span>
          </div>
          <div class="flex items-center gap-3">
            <div class="grid h-[66px] w-[66px] shrink-0 place-items-center rounded-full" :style="{ background: ring.gradient }">
              <div class="flex h-[46px] w-[46px] flex-col items-center justify-center rounded-full bg-white shadow-[inset_0_0_0_1px_#f1f5f9]">
                <strong class="text-[15px] font-semibold leading-none text-slate-900">{{ kpi.nCaptured }}</strong>
                <span class="mt-0.5 text-[8px] text-slate-400">已认定</span>
              </div>
            </div>
            <ul class="min-w-0 flex-1 space-y-1">
              <li class="flex items-center gap-1.5 text-[9.5px] text-slate-500"><i class="h-1.5 w-1.5 shrink-0 rounded-sm bg-blue-600"></i>认定 · 合规<b class="ml-auto font-semibold text-slate-700 tabular-nums">{{ ring.clean }}</b></li>
              <li class="flex items-center gap-1.5 text-[9.5px] text-slate-500"><i class="h-1.5 w-1.5 shrink-0 rounded-sm bg-rose-500"></i>认定 · 越界<b class="ml-auto font-semibold text-slate-700 tabular-nums">{{ ring.both }}</b></li>
              <li class="flex items-center gap-1.5 text-[9.5px] text-slate-500"><i class="h-1.5 w-1.5 shrink-0 rounded-sm bg-slate-300"></i>未认定<b class="ml-auto font-semibold text-slate-700 tabular-nums">{{ ring.miss }}</b></li>
            </ul>
          </div>
          <div class="mt-2.5 flex items-center justify-between gap-2 border-t border-slate-100 pt-2 text-[9px] text-slate-400">
            <span>认定率 {{ kpi.rate }}%（批次口径）</span>
            <button class="flex items-center gap-0.5 text-[9px] font-semibold text-blue-600" @click="activeTab = 'result'">看明细<ChevronRight :size="11" /></button>
          </div>
        </section>

        <!-- 自动巡航与补拍：填在左栏中段原本的弹性空白里，页内导航仍压在最底 -->
        <section class="rounded-lg border border-slate-200 bg-white p-3">
          <div class="mb-1 flex items-center justify-between gap-2">
            <h2 class="text-[10.5px] font-semibold tracking-wide text-slate-500">自动巡航与补拍</h2>
            <span class="text-[8.5px] tracking-widest text-slate-400">AUTO</span>
          </div>
          <p class="mb-2.5 text-[9px] leading-snug text-slate-400">飞一遍全场 → 逐车拍三个机位 → 缺口补一轮</p>
          <ol class="space-y-2">
            <li v-for="(step, i) in FLOW_STEPS" :key="step.title" class="flex gap-2">
              <span class="mt-[1.5px] grid h-3.5 w-3.5 shrink-0 place-items-center rounded-full bg-slate-900 text-[8px] font-semibold leading-none text-white">{{ i + 1 }}</span>
              <div class="min-w-0">
                <p class="text-[10.5px] font-semibold leading-tight text-slate-800">{{ step.title }}</p>
                <p class="mt-0.5 text-[9.5px] leading-[1.45] text-slate-500">{{ step.desc }}</p>
              </div>
            </li>
          </ol>
          <p v-if="flowNote" class="mt-2.5 border-t border-slate-100 pt-2 text-[9px] leading-snug text-slate-400">
            本批次：{{ flowNote }}
          </p>
        </section>

        <!-- 弹性占位：把页内导航压到左下角 -->
        <div class="hidden flex-1 xl:block" aria-hidden="true"></div>

        <!-- 页内导航：固定在左下角。
             2026-11-20 删除「模块切换」下拉——改版后跨业务模块跳转由平台顶栏负责，
             这页只保留「巡检过程 / 巡检结果」两个页内视图。 -->
        <section class="mt-auto rounded-lg border border-slate-200 bg-white p-2.5">
          <div class="mb-1.5 flex items-center justify-between gap-2">
            <h2 class="text-[10.5px] font-semibold tracking-wide text-slate-500">页内视图</h2>
          </div>
          <div class="space-y-0.5">
            <button
              v-for="tab in tabs"
              :key="tab.key"
              type="button"
              class="flex w-full items-center gap-2 rounded-md px-1.5 py-1.5 text-left text-[11px] transition"
              :class="activeTab === tab.key ? 'bg-blue-50 font-semibold text-blue-700' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'"
              @click="activeTab = tab.key"
            >
              <component :is="tab.icon" :size="15" :class="activeTab === tab.key ? 'text-blue-600' : 'text-slate-400'" />
              <span class="flex-1">{{ tab.label }}</span>
              <ChevronRight :size="11" class="text-slate-300" />
            </button>
          </div>
        </section>
      </aside>

      <!-- ===== 中栏：主视图（过程回放为显式主入口） ===== -->
      <section class="order-1 flex min-h-0 flex-col gap-3 xl:order-none">
        <div class="flex shrink-0 flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-900 px-3 py-2">
          <div class="flex min-w-0 items-center gap-2">
            <span class="h-1.5 w-1.5 shrink-0 rounded-full" :class="online ? 'bg-emerald-400' : 'bg-rose-400'"></span>
            <strong class="truncate text-[11.5px] font-semibold text-slate-100">{{ stageTitle }}</strong>
            <span class="hidden truncate text-[9.5px] text-slate-500 sm:inline">作业区域 · {{ kpi.runShort || '未载入批次' }}</span>
          </div>
          <div class="flex shrink-0 items-center gap-1.5">
            <span v-if="batchMismatch" class="rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[9px] text-amber-300" :title="`巡检结果 ${acceptanceRun} / 回放 ${replayRun}`">批次不一致</span>
            <span class="hidden rounded border border-slate-700 bg-slate-800 px-2 py-1 text-[10px] text-slate-400 sm:inline">三路视频 + 路径图 · 同步时间轴</span>
          </div>
        </div>

        <div class="flex min-h-0 flex-1 flex-col gap-3 pr-0.5" :class="zoomCell ? 'overflow-hidden' : 'overflow-y-auto'">
          <!-- 巡检结果 -->
          <template v-if="activeTab === 'result'">
            <section v-if="!acceptance" class="rounded-lg border border-slate-200 bg-white px-6 py-14 text-center">
              <Layers :size="34" class="mx-auto text-slate-300" />
              <p class="mt-3 text-sm text-slate-500">{{ loadingAcceptance ? '正在载入巡检结果…' : '还没有可回放的巡检批次。' }}</p>
            </section>
            <template v-else>
              <section class="rounded-lg border border-slate-200 bg-white p-4">
                <div class="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <h2 class="text-sm font-semibold text-slate-900">最近一次自主巡检</h2>
                    <p class="mt-1 text-[11px] text-slate-500">{{ acceptance.batch.start }} — {{ acceptance.batch.end }} · 退出码 {{ acceptance.batch.exit_code }} · {{ acceptance.batch.fsm }}</p>
                  </div>
                  <span class="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-[11px] font-medium text-emerald-700">{{ violatedCount }} 辆压线越界 / {{ violations.length }} 辆受检</span>
                </div>
                <div class="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <div v-for="card in summaryCards" :key="card.label" class="rounded-lg border border-slate-200 bg-slate-50/80 px-2.5 py-2.5">
                    <div class="text-[10px] text-slate-500">{{ card.label }}</div>
                    <div class="mt-0.5 text-lg font-semibold text-slate-900">{{ card.value }}</div>
                    <div class="mt-0.5 text-[10px] leading-snug text-slate-500">{{ card.note }}</div>
                  </div>
                </div>
              </section>

              <section class="rounded-lg border border-slate-200 bg-white p-4">
                <div class="flex items-center justify-between">
                  <h2 class="text-sm font-semibold text-slate-900">车辆认定</h2>
                  <span class="text-[11px] text-slate-500">点击缩略图查看识别卡</span>
                </div>
                <div class="mt-3 overflow-x-auto">
                  <table class="min-w-full text-sm">
                    <thead>
                      <tr class="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                        <th class="px-2.5 py-2 font-medium">车辆</th>
                        <th class="px-2.5 py-2 font-medium">场景实体</th>
                        <th class="px-2.5 py-2 font-medium">车牌号</th>
                        <th class="px-2.5 py-2 font-medium">置信度</th>
                        <th class="px-2.5 py-2 font-medium">拍摄距离</th>
                        <th class="px-2.5 py-2 font-medium">腿</th>
                        <th class="px-2.5 py-2 font-medium">备注</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="vehicle in vehicles" :key="vehicle.car" class="border-b border-slate-100 last:border-0">
                        <td class="px-2.5 py-2">
                          <button v-if="vehicle.card_url" class="overflow-hidden rounded border border-slate-200 transition hover:border-indigo-400" @click="showCard(vehicle.card_url)">
                            <img :src="vehicle.card_url" :alt="vehicle.car" class="h-11 w-16 object-cover" />
                          </button>
                          <span v-else class="text-slate-500">{{ vehicle.car }}</span>
                        </td>
                        <td class="px-2.5 py-2 text-slate-500">{{ vehicle.real_car }}</td>
                        <td class="px-2.5 py-2 font-semibold text-slate-900">{{ vehicle.plate }}</td>
                        <td class="px-2.5 py-2 text-slate-600">{{ vehicle.confidence.toFixed(3) }}</td>
                        <td class="px-2.5 py-2 text-slate-600">{{ vehicle.distance_m }} m</td>
                        <td class="px-2.5 py-2 text-slate-600">{{ vehicle.leg }}</td>
                        <td class="px-2.5 py-2 text-xs text-slate-500">{{ vehicle.note || '—' }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </section>

              <section class="rounded-lg border border-slate-200 bg-white p-4">
                <div class="flex items-center justify-between">
                  <h2 class="text-sm font-semibold text-slate-900">违停判定</h2>
                  <span class="text-[11px] text-slate-500">最小余量为负即越界</span>
                </div>
                <div class="mt-3 overflow-x-auto">
                  <table class="min-w-full text-sm">
                    <thead>
                      <tr class="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                        <th class="px-2.5 py-2 font-medium">车辆</th>
                        <th class="px-2.5 py-2 font-medium">车位</th>
                        <th class="px-2.5 py-2 font-medium">横向偏移</th>
                        <th class="px-2.5 py-2 font-medium">纵向偏移</th>
                        <th class="px-2.5 py-2 font-medium">最小余量</th>
                        <th class="px-2.5 py-2 font-medium">形状误差</th>
                        <th class="px-2.5 py-2 font-medium">判定</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="row in violations" :key="row.car" class="border-b border-slate-100 last:border-0">
                        <td class="px-2.5 py-2 font-medium text-slate-900">{{ row.car }}</td>
                        <td class="px-2.5 py-2 text-slate-600">{{ row.slot }}</td>
                        <td class="px-2.5 py-2 text-slate-600">{{ row.lateral_m.toFixed(3) }} m</td>
                        <td class="px-2.5 py-2 text-slate-600">{{ row.longitudinal_m.toFixed(3) }} m</td>
                        <td class="px-2.5 py-2 font-medium" :class="row.margin_m < 0 ? 'text-rose-600' : 'text-emerald-600'">{{ row.margin_m.toFixed(3) }} m</td>
                        <td class="px-2.5 py-2 text-slate-600">{{ row.shape_error_m.toFixed(3) }} m</td>
                        <td class="px-2.5 py-2">
                          <span class="rounded-full px-2 py-0.5 text-xs font-medium" :class="row.margin_m < 0 ? 'bg-rose-50 text-rose-700 ring-1 ring-rose-200' : 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200'">{{ row.verdict }}</span>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </div>
                <p class="mt-3 text-[11px] leading-relaxed text-slate-500">最小余量 = 标准半尺寸 −（车心偏移 + 车体投影半尺寸），负值即越界。形状误差是车牌四点反算的车体四角与真实四角之差。</p>
                <p v-if="acceptance.geometry" class="mt-2 rounded-lg bg-amber-50 px-2.5 py-1.5 text-[10.5px] leading-relaxed text-amber-700">
                  本表几何量来自 {{ acceptance.geometry.batch }}（{{ acceptance.geometry.start }}）那一轮的复算，按车体标注（real_car）重挂到本次车号；本次跑次只做检测/识别/覆盖，未重算车位与余量。
                </p>
              </section>

              <section class="rounded-lg border border-indigo-100 bg-indigo-50/60 p-4">
                <div class="flex items-start gap-2.5">
                  <Sparkles :size="17" class="mt-0.5 shrink-0 text-indigo-500" />
                  <div class="text-[11px] leading-relaxed text-indigo-900">
                    <p class="font-semibold">这批结果怎么来的</p>
                    <p class="mt-1">{{ acceptance.retry.触发 }}，系统按轮次补拍 {{ acceptance.retry.补拍 }}，结果 {{ acceptance.retry.结果 }}。本批共 {{ acceptance.retry.轮次 }} 轮 INSPECT，车号与真值按起降点坐标映射后逐字比对。</p>
                  </div>
                </div>
              </section>
            </template>
          </template>

          <!-- 巡检过程：四宫格同步时间轴（2026-11-20 由「过程回放」+「覆盖质量」合并） -->
          <template v-else>
            <section class="rounded-lg border border-slate-200 bg-white p-3">
              <div v-if="loadingReplay" class="py-20 text-center text-sm text-slate-500">正在载入巡检过程…</div>
              <div v-else-if="!replay" class="py-20 text-center text-sm text-slate-500">{{ replayError || '没有可用的回放数据。' }}</div>
              <template v-else>
                <div class="flex flex-wrap items-baseline justify-between gap-2 pb-1.5">
                  <div>
                    <p class="text-[10px] uppercase tracking-[0.3em] text-indigo-400">MISSION REPLAY</p>
                    <h2 class="mt-0.5 text-base font-semibold text-slate-900">{{ replay.mission.scenario }}</h2>
                  </div>
                  <div class="text-right text-[11px] leading-snug text-slate-500">
                    <p class="font-mono text-[10.5px] text-slate-600">{{ replay.mission.run }}</p>
                    <p>{{ replay.mission.started_at }} 起 · {{ replay.mission.platform }}</p>
                  </div>
                </div>

                <div class="mt-1.5 rounded-lg border border-indigo-100 bg-indigo-50/70 p-2">
                  <div class="flex flex-wrap items-center gap-1.5">
                    <span class="rounded bg-indigo-600 px-1.5 py-0.5 text-[9px] font-semibold text-white">当前阶段</span>
                    <strong class="text-[12px] font-semibold text-indigo-900">{{ currentPhase?.label ?? '—' }}</strong>
                    <span class="font-mono text-[9.5px] text-indigo-400">{{ fmtTime(currentPhase?.t0 ?? 0) }} – {{ fmtTime(currentPhase?.t1 ?? 0) }}</span>
                  </div>
                  <dl class="mt-1 space-y-0.5 text-[11px] leading-snug">
                    <div class="flex gap-1.5"><dt class="w-[52px] shrink-0 font-semibold text-indigo-700">正在执行</dt><dd class="min-w-0 text-indigo-900/90">{{ phaseAction }}</dd></div>
                    <div class="flex gap-1.5"><dt class="w-[52px] shrink-0 font-semibold text-indigo-700">产生结果</dt><dd class="min-w-0 text-indigo-900/90">{{ phaseResult }}</dd></div>
                  </dl>
                </div>

                <div class="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                  <figure
                    class="overflow-hidden rounded-lg border border-slate-800 bg-slate-950"
                    :class="zoomCell === 'overview' ? 'cell-zoom' : ''"
                  >
                    <!-- 放大态顶栏：标题 + 倍速 + 退出（原来那条 figcaption 在放大时被替换掉） -->
                    <div v-if="zoomCell === 'overview'" class="flex shrink-0 items-center justify-between gap-2 border-b border-slate-800 bg-slate-900 px-3 py-2">
                      <div class="flex min-w-0 items-center gap-2">
                        <span class="shrink-0 rounded bg-indigo-600 px-1.5 py-0.5 text-[9px] font-semibold text-white">放大观看</span>
                        <strong class="truncate text-[13px] font-semibold text-slate-100">总览视角</strong>
                        <span class="hidden truncate text-[10px] text-slate-500 sm:inline">固定机位俯视 · 全场</span>
                      </div>
                      <div class="flex shrink-0 items-center gap-1.5">
                        <PlaybackRateMenu v-model="playbackRate" />
                        <button type="button" class="grid h-7 w-7 place-items-center rounded border border-white/25 bg-slate-800 text-slate-200 transition hover:border-rose-400 hover:bg-rose-600 hover:text-white" title="退出放大（Esc）" @click="closeZoom">
                          <Minimize2 :size="14" />
                        </button>
                      </div>
                    </div>
                    <div class="relative overflow-hidden" :class="zoomCell === 'overview' ? 'min-h-0 flex-1' : 'aspect-[11/5]'">
                      <video
                        ref="overviewEl" :src="replay.video.src" :poster="replay.video.poster"
                        class="absolute inset-0 h-full w-full"
                        :class="zoomCell === 'overview' ? 'object-contain' : 'object-cover'"
                        playsinline preload="metadata"
                        @timeupdate="onVideoTime" @play="onPlayState" @pause="onPlayState" @loadedmetadata="onOverviewReady"
                      />
                      <!-- 常显的小工具条：图标别收进 hover，否则演示时用户找不到 -->
                      <div v-if="!zoomCell" class="absolute right-1.5 top-1.5 z-10 flex items-center gap-1">
                        <PlaybackRateMenu v-model="playbackRate" compact />
                        <button type="button" class="grid h-5 w-5 place-items-center rounded border border-white/25 bg-slate-900/75 text-slate-100 backdrop-blur transition hover:border-indigo-400 hover:bg-indigo-600" title="放大观看" aria-label="放大观看总览视角" @click="openZoom('overview')">
                          <Maximize2 :size="12" />
                        </button>
                      </div>
                    </div>
                    <figcaption v-if="zoomCell !== 'overview'" class="flex items-baseline justify-between gap-2 px-2.5 py-1">
                      <span class="text-[11px] font-semibold text-slate-100">总览视角</span>
                      <span class="text-[9px] text-slate-400">固定机位俯视 · 全场</span>
                    </figcaption>
                    <!-- 放大时页面底部那条被盖住，浮层自己带一条 -->
                    <div v-if="zoomCell === 'overview'" class="shrink-0 border-t border-slate-800 bg-slate-900 px-3 py-2">
                      <ReplayTransport dark :playing="playing" :current="videoTime" :duration="replay.video.seconds" @toggle="togglePlay" @seek="seekTo" />
                    </div>
                  </figure>

                  <figure
                    class="overflow-hidden rounded-lg border border-slate-800 bg-slate-950"
                    :class="zoomCell === 'onboard' ? 'cell-zoom' : ''"
                  >
                    <div v-if="zoomCell === 'onboard'" class="flex shrink-0 items-center justify-between gap-2 border-b border-slate-800 bg-slate-900 px-3 py-2">
                      <div class="flex min-w-0 items-center gap-2">
                        <span class="shrink-0 rounded bg-indigo-600 px-1.5 py-0.5 text-[9px] font-semibold text-white">放大观看</span>
                        <strong class="truncate text-[13px] font-semibold text-slate-100">无人机视角</strong>
                        <span class="hidden truncate text-[10px] text-slate-500 sm:inline">机载相机 · 进近与拍摄</span>
                      </div>
                      <div class="flex shrink-0 items-center gap-1.5">
                        <PlaybackRateMenu v-model="playbackRate" />
                        <button type="button" class="grid h-7 w-7 place-items-center rounded border border-white/25 bg-slate-800 text-slate-200 transition hover:border-rose-400 hover:bg-rose-600 hover:text-white" title="退出放大（Esc）" @click="closeZoom">
                          <Minimize2 :size="14" />
                        </button>
                      </div>
                    </div>
                    <div class="relative overflow-hidden" :class="zoomCell === 'onboard' ? 'min-h-0 flex-1' : 'aspect-[11/5]'">
                      <template v-if="coverageRviz">
                        <video :ref="bindRviz(0)" :src="coverageRviz.src" class="absolute max-w-none" :style="zoomCell === 'onboard' ? onboardZoomStyle : onboardStyle" muted playsinline preload="metadata" />
                      </template>
                      <div v-else class="grid h-full place-items-center text-[11px] text-slate-500">RViz 录屏未载入</div>
                      <div v-if="!zoomCell && coverageRviz" class="absolute right-1.5 top-1.5 z-10 flex items-center gap-1">
                        <PlaybackRateMenu v-model="playbackRate" compact />
                        <button type="button" class="grid h-5 w-5 place-items-center rounded border border-white/25 bg-slate-900/75 text-slate-100 backdrop-blur transition hover:border-indigo-400 hover:bg-indigo-600" title="放大观看" aria-label="放大观看无人机视角" @click="openZoom('onboard')">
                          <Maximize2 :size="12" />
                        </button>
                      </div>
                    </div>
                    <figcaption v-if="zoomCell !== 'onboard'" class="flex items-baseline justify-between gap-2 px-2.5 py-1">
                      <span class="text-[11px] font-semibold text-slate-100">无人机视角</span>
                      <span class="text-[9px] text-slate-400">机载相机 · 进近与拍摄</span>
                    </figcaption>
                    <div v-if="zoomCell === 'onboard'" class="shrink-0 border-t border-slate-800 bg-slate-900 px-3 py-2">
                      <ReplayTransport dark :playing="playing" :current="videoTime" :duration="replay.video.seconds" @toggle="togglePlay" @seek="seekTo" />
                    </div>
                  </figure>

                  <figure
                    class="overflow-hidden rounded-lg border border-slate-800 bg-slate-950"
                    :class="zoomCell === 'viewpoint' ? 'cell-zoom' : ''"
                  >
                    <div v-if="zoomCell === 'viewpoint'" class="flex shrink-0 items-center justify-between gap-2 border-b border-slate-800 bg-slate-900 px-3 py-2">
                      <div class="flex min-w-0 items-center gap-2">
                        <span class="shrink-0 rounded bg-indigo-600 px-1.5 py-0.5 text-[9px] font-semibold text-white">放大观看</span>
                        <strong class="truncate text-[13px] font-semibold text-slate-100">视点与位姿</strong>
                        <span class="hidden truncate text-[10px] text-slate-500 sm:inline">相机视锥 · 目标朝向</span>
                      </div>
                      <div class="flex shrink-0 items-center gap-1.5">
                        <PlaybackRateMenu v-model="playbackRate" />
                        <button type="button" class="grid h-7 w-7 place-items-center rounded border border-white/25 bg-slate-800 text-slate-200 transition hover:border-rose-400 hover:bg-rose-600 hover:text-white" title="退出放大（Esc）" @click="closeZoom">
                          <Minimize2 :size="14" />
                        </button>
                      </div>
                    </div>
                    <div class="relative overflow-hidden" :class="zoomCell === 'viewpoint' ? 'min-h-0 flex-1' : 'aspect-[11/5]'">
                      <template v-if="coverageRviz">
                        <video :ref="bindRviz(1)" :src="coverageRviz.src" class="absolute max-w-none" :style="zoomCell === 'viewpoint' ? viewpointZoomStyle : viewpointStyle" muted playsinline preload="metadata" />
                      </template>
                      <div v-else class="grid h-full place-items-center text-[11px] text-slate-500">RViz 录屏未载入</div>
                      <div v-if="!zoomCell && coverageRviz" class="absolute right-1.5 top-1.5 z-10 flex items-center gap-1">
                        <PlaybackRateMenu v-model="playbackRate" compact />
                        <button type="button" class="grid h-5 w-5 place-items-center rounded border border-white/25 bg-slate-900/75 text-slate-100 backdrop-blur transition hover:border-indigo-400 hover:bg-indigo-600" title="放大观看" aria-label="放大观看视点与位姿" @click="openZoom('viewpoint')">
                          <Maximize2 :size="12" />
                        </button>
                      </div>
                    </div>
                    <figcaption v-if="zoomCell !== 'viewpoint'" class="flex items-baseline justify-between gap-2 px-2.5 py-1">
                      <span class="text-[11px] font-semibold text-slate-100">视点与位姿</span>
                      <span class="text-[9px] text-slate-400">相机视锥 · 目标朝向</span>
                    </figcaption>
                    <div v-if="zoomCell === 'viewpoint'" class="shrink-0 border-t border-slate-800 bg-slate-900 px-3 py-2">
                      <ReplayTransport dark :playing="playing" :current="videoTime" :duration="replay.video.seconds" @toggle="togglePlay" @seek="seekTo" />
                    </div>
                  </figure>

                  <figure
                    class="overflow-hidden rounded-lg border border-slate-800 bg-slate-950"
                    :class="zoomCell === 'path' ? 'cell-zoom' : ''"
                  >
                    <div v-if="zoomCell === 'path'" class="flex shrink-0 items-center justify-between gap-2 border-b border-slate-800 bg-slate-900 px-3 py-2">
                      <div class="flex min-w-0 items-center gap-2">
                        <span class="shrink-0 rounded bg-indigo-600 px-1.5 py-0.5 text-[9px] font-semibold text-white">放大观看</span>
                        <strong class="truncate text-[13px] font-semibold text-slate-100">路径与视点</strong>
                        <span v-if="pathGeom" class="hidden truncate text-[10px] text-slate-500 sm:inline">{{ pathGeom.steps.length }} 步 · 第 {{ pathCursor + 1 }} 步 · 青色为已飞航段</span>
                      </div>
                      <div class="flex shrink-0 items-center gap-1.5">
                        <PlaybackRateMenu v-model="playbackRate" />
                        <button type="button" class="grid h-7 w-7 place-items-center rounded border border-white/25 bg-slate-800 text-slate-200 transition hover:border-rose-400 hover:bg-rose-600 hover:text-white" title="退出放大（Esc）" @click="closeZoom">
                          <Minimize2 :size="14" />
                        </button>
                      </div>
                    </div>
                    <div class="relative overflow-hidden" :class="zoomCell === 'path' ? 'min-h-0 flex-1' : 'aspect-[11/5]'">
                      <svg
                        v-if="pathGeom"
                        :viewBox="`0 0 ${pathGeom.w} ${pathGeom.h}`"
                        class="h-full w-full"
                        preserveAspectRatio="xMidYMid meet"
                      >
                        <rect x="0" y="0" :width="pathGeom.w" :height="pathGeom.h" fill="#020617" />
                        <!-- 5 m 网格 -->
                        <g stroke="#1e293b" stroke-width="0.4">
                          <line v-for="gx in pathGrid.x" :key="`gx${gx}`" :x1="gx" y1="0" :x2="gx" :y2="pathGeom.h" />
                          <line v-for="gy in pathGrid.y" :key="`gy${gy}`" x1="0" :y1="gy" :x2="pathGeom.w" :y2="gy" />
                        </g>
                        <!-- 场地边界（贴墙矩形 x±13.7 / y±9.2） -->
                        <rect x="0.8" y="0.8" :width="pathGeom.w - 1.6" :height="pathGeom.h - 1.6"
                              fill="none" stroke="#334155" stroke-width="0.8" stroke-dasharray="4 3" />
                        <!-- 车辆：4.4 × 1.8 m 的车体，车头短线指示朝向 -->
                        <g v-for="c in pathGeom.cars" :key="c.name" :transform="`rotate(${c.deg} ${c.cx} ${c.cy})`">
                          <rect :x="c.cx - 22" :y="c.cy - 9" width="44" height="18" rx="3"
                                fill="#1e293b" stroke="#64748b" stroke-width="0.7" />
                          <line :x1="c.cx + 14" :y1="c.cy" :x2="c.cx + 22" :y2="c.cy" stroke="#f59e0b" stroke-width="2" />
                        </g>
                        <!-- 车号单独画在旋转组外，否则文字会跟着车身一起转 -->
                        <text v-for="c in pathGeom.cars" :key="`n${c.name}`" :x="c.cx" :y="c.cy - 12"
                              font-size="7.5" fill="#64748b" text-anchor="middle">
                          {{ c.name.replace('car_', 'C') }}
                        </text>
                        <!-- 全量路径（未走：虚线灰）+ 已走（实线青） -->
                        <polyline :points="pathAll" fill="none" stroke="#334155" stroke-width="1" stroke-dasharray="2 2" />
                        <polyline :points="pathWalked" fill="none" stroke="#22d3ee" stroke-width="1.6" stroke-linejoin="round" />
                        <!-- 视点：拍摄腿为实心圆，转场腿为小点 -->
                        <circle
                          v-for="s in pathGeom.steps" :key="s.idx" :cx="s.cx" :cy="s.cy"
                          :r="s.kind === 'capture' ? 2.2 : 1.3"
                          :fill="s.idx <= pathCursor ? (s.kind === 'capture' ? '#22d3ee' : '#94a3b8') : (s.kind === 'capture' ? '#0e7490' : '#334155')"
                        />
                        <!-- 当前腿：外圈脉冲 + 实心点 -->
                        <g v-if="pathActive">
                          <circle :cx="pathActive.cx" :cy="pathActive.cy" r="6.5" fill="none" stroke="#22d3ee" stroke-width="1" opacity="0.55" />
                          <circle :cx="pathActive.cx" :cy="pathActive.cy" r="3" fill="#e0f2fe" stroke="#22d3ee" stroke-width="1" />
                        </g>
                      </svg>
                      <div v-else class="grid h-full place-items-center text-[11px] text-slate-500">
                        {{ loadingPath ? '正在载入路径…' : '路径数据未载入（/plate/path 与 media/path.json 均不可用）' }}
                      </div>
                      <div v-if="!zoomCell" class="absolute right-1.5 top-1.5 z-10 flex items-center gap-1">
                        <PlaybackRateMenu v-model="playbackRate" compact />
                        <button type="button" class="grid h-5 w-5 place-items-center rounded border border-white/25 bg-slate-900/75 text-slate-100 backdrop-blur transition hover:border-indigo-400 hover:bg-indigo-600" title="放大观看" aria-label="放大观看路径与视点" @click="openZoom('path')">
                          <Maximize2 :size="12" />
                        </button>
                      </div>
                    </div>
                    <figcaption v-if="zoomCell !== 'path'" class="flex items-baseline justify-between gap-2 px-2.5 py-1">
                      <span class="text-[11px] font-semibold text-slate-100">路径与视点</span>
                      <span class="text-[9px] text-slate-400">
                        <template v-if="pathGeom">{{ pathGeom.steps.length }} 步 · 第 {{ pathCursor + 1 }} 步</template>
                        <template v-else>按日志 GOTO 序列复算</template>
                      </span>
                    </figcaption>
                    <div v-if="zoomCell === 'path'" class="shrink-0 border-t border-slate-800 bg-slate-900 px-3 py-2">
                      <ReplayTransport dark :playing="playing" :current="videoTime" :duration="replay.video.seconds" @toggle="togglePlay" @seek="seekTo" />
                    </div>
                  </figure>
                </div>

                <div class="mt-1.5 flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5">
                  <ReplayTransport class="min-w-0 flex-1" :playing="playing" :current="videoTime" :duration="replay.video.seconds" @toggle="togglePlay" @seek="seekTo" />
                  <div class="flex shrink-0 items-center gap-1.5">
                    <span class="hidden text-[9px] text-slate-400 sm:inline">倍速 · 全窗格</span>
                    <PlaybackRateMenu v-model="playbackRate" compact />
                  </div>
                </div>

                <div class="mt-1.5 flex items-center gap-1">
                  <span class="shrink-0 text-[9px] text-slate-400">阶段</span>
                    <button
                      v-for="(ph, i) in replay.phases"
                      :key="ph.key"
                      class="group relative h-[42px] min-w-[58px] overflow-hidden rounded-lg border text-left transition"
                      :class="i === phaseCursor ? 'border-indigo-400 ring-2 ring-indigo-300' : 'border-slate-200 hover:border-indigo-300'"
                      :style="{ flexGrow: ph.seconds }"
                      :title="`${ph.label}（${fmtTime(ph.t0)}–${fmtTime(ph.t1)}，${ph.seconds} s）：${ph.detail}`"
                      @click="seekToPhase(ph)"
                    >
                      <img :src="ph.cover" :alt="ph.label" class="absolute inset-0 h-full w-full object-cover opacity-70" />
                      <span class="absolute inset-0 bg-gradient-to-t from-slate-900/85 via-slate-900/25 to-transparent" />
                      <span class="relative flex h-full flex-col justify-end gap-0.5 p-1.5">
                        <span class="truncate text-[10px] font-semibold leading-tight text-white">{{ ph.label }}</span>
                        <span class="truncate text-[9px] leading-tight text-indigo-200">{{ ph.detail }}<span class="ml-1 font-mono text-white/50">{{ fmtTime(ph.t0) }}</span></span>
                      </span>
                    </button>
                </div>

              </template>
            </section>
          </template>

        </div>
      </section>

      <!-- ===== 右栏：当前视图的上下文（任务结果 / 覆盖分级 / 事件） ===== -->
      <aside class="order-3 flex min-h-0 flex-col gap-3 xl:order-none xl:overflow-y-auto xl:pl-0.5">
        <template v-if="activeTab === 'mission'">
          <section v-if="replay" class="rounded-lg border border-slate-200 bg-white p-3.5">
            <h3 class="text-xs font-semibold text-slate-800">任务结果</h3>
            <dl class="mt-2.5 space-y-1.5 text-[11px]">
              <div class="flex justify-between gap-2"><dt class="text-slate-500">终态</dt><dd class="text-right font-semibold text-emerald-600">{{ replay.kpi.final }}</dd></div>
              <div class="flex justify-between gap-2"><dt class="text-slate-500">清单 / 拍成</dt><dd class="font-mono text-slate-800">{{ replay.kpi.n_cars }} / {{ replay.kpi.n_captured }}</dd></div>
              <div class="flex justify-between gap-2"><dt class="text-slate-500">补拍轮次</dt><dd class="font-mono text-slate-800">{{ replay.kpi.inspect_round }}</dd></div>
              <div class="flex justify-between gap-2"><dt class="text-slate-500">墙钟 / 预算</dt><dd class="font-mono text-slate-800">{{ replay.budget.wall_clock_s }} / {{ replay.budget.budget_s }} s</dd></div>
            </dl>
            <div class="mt-2.5">
              <div class="h-1.5 overflow-hidden rounded-full bg-slate-200"><div class="h-full rounded-full bg-indigo-500" :style="{ width: budgetUsedPct + '%' }" /></div>
              <p class="mt-1 text-[10px] text-slate-500">用掉预算的 {{ budgetUsedPct }}%</p>
            </div>
            <p class="mt-2 border-t border-slate-100 pt-1.5 text-[10px] leading-snug text-slate-500">{{ replay.kpi.note }}</p>
          </section>

          <!-- 2026-11-20 删除「覆盖分级」卡片（含覆盖热力图）：用户判断该图对演示无作用，
               分级比例与热力图与实际巡检决策无关，右栏保留任务结果、分排车位与关键事件。 -->

          <section v-if="coverage" class="rounded-lg border border-slate-200 bg-white p-3.5">
            <div class="flex items-center justify-between">
              <h3 class="text-xs font-semibold text-slate-800">分排与车位</h3>
              <span class="text-[9px] text-slate-400">中位帧 / 3 帧以上</span>
            </div>
            <table class="mt-2 w-full text-[10.5px]">
              <thead class="text-slate-500"><tr><th class="py-1 text-left font-medium">排</th><th class="py-1 text-right font-medium">中位帧</th><th class="py-1 text-right font-medium">3 帧以上</th></tr></thead>
              <tbody>
                <tr v-for="row in coverageRows" :key="row.label" class="border-t border-slate-100">
                  <td class="py-1 text-slate-700">{{ row.label }}</td>
                  <td class="py-1 text-right font-mono text-slate-700">{{ row.median_frames }}</td>
                  <td class="py-1 text-right font-mono text-slate-700">{{ row.ge3 }}%</td>
                </tr>
              </tbody>
            </table>
            <div class="mt-2 max-h-[220px] overflow-auto border-t border-slate-100 pt-1">
              <table class="w-full text-[10px]">
                <thead class="sticky top-0 bg-white text-slate-500"><tr><th class="py-1 text-left font-medium">车位</th><th class="py-1 text-right font-medium">帧</th><th class="py-1 text-right font-medium">点</th><th class="py-1 text-right font-medium">最近 m</th></tr></thead>
                <tbody>
                  <tr v-for="slot in coverageSlots" :key="slot.name" class="border-t border-slate-100">
                    <td class="py-1 text-slate-700">{{ slot.name }}</td>
                    <td class="py-1 text-right font-mono">{{ slot.frames }}</td>
                    <td class="py-1 text-right font-mono">{{ slot.points }}</td>
                    <td class="py-1 text-right font-mono">{{ slot.min_dist }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section v-if="replay" class="rounded-lg border border-slate-200 bg-white p-3.5">
            <h3 class="text-xs font-semibold text-slate-800">关键事件</h3>
            <ul class="mt-2 max-h-[260px] space-y-1 overflow-auto pr-1 text-[10px] leading-snug">
              <li v-for="(ev, i) in replay.events" :key="i" class="flex gap-1.5">
                <span class="w-9 shrink-0 font-mono text-slate-400">{{ fmtTime(ev.t) }}</span>
                <span :class="ev.kind === 'fsm' ? 'text-indigo-600' : 'text-slate-600'">{{ ev.text }}</span>
              </li>
            </ul>
          </section>
        </template>

        <template v-else>
          <section class="rounded-lg border border-slate-200 bg-white p-3.5">
            <h3 class="text-xs font-semibold text-slate-800">批次信息</h3>
            <dl class="mt-2 space-y-1.5 text-[10.5px]">
              <div class="flex justify-between gap-2"><dt class="text-slate-500">开始</dt><dd class="text-right font-mono text-slate-700">{{ acceptance?.batch.start || '—' }}</dd></div>
              <div class="flex justify-between gap-2"><dt class="text-slate-500">结束</dt><dd class="text-right font-mono text-slate-700">{{ acceptance?.batch.end || '—' }}</dd></div>
              <div class="flex justify-between gap-2"><dt class="text-slate-500">退出码</dt><dd class="text-right font-mono text-slate-700">{{ acceptance?.batch.exit_code ?? '—' }}</dd></div>
              <div class="flex justify-between gap-2"><dt class="text-slate-500">FSM</dt><dd class="truncate text-right font-mono text-slate-700">{{ acceptance?.batch.fsm || '—' }}</dd></div>
            </dl>
            <button class="mt-2.5 flex w-full items-center justify-center gap-1 rounded-md border border-indigo-200 bg-indigo-50 px-2 py-1.5 text-[10.5px] font-semibold text-indigo-700" @click="activeTab = 'mission'">
              <Film :size="12" />查看巡检过程
            </button>
          </section>
          <section class="rounded-lg border border-slate-200 bg-white p-3.5">
            <h3 class="text-xs font-semibold text-slate-800">口径提示</h3>
            <p class="mt-1.5 text-[10px] leading-relaxed text-slate-500">
              车号与真值按起降点坐标映射后逐字比对；几何量（车位、余量、形状误差）来自标注复算，不随本次跑次变化。回放批次与结果批次可能不同，页面顶部会标出不一致。
            </p>
          </section>
        </template>
      </aside>
    </main>

    <div v-if="previewCard" class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 p-6" @click="previewCard = ''">
      <img :src="previewCard" alt="识别结果卡" class="max-h-full max-w-4xl rounded-xl shadow-2xl" />
    </div>
  </div>
</template>

<style scoped>
/**
 * 放大观看：把四宫格里任意一张 figure 直接撑满视口。
 * 用 fixed 而不是另开一份播放器——video 元素没被搬动/重建，时间轴连续，
 * 也就不存在「旁边那格还在播、这格停在原地」的同步问题。
 * 选择器带上 figure 提高特异性，压过 Tailwind 的 rounded-lg / border 工具类。
 */
figure.cell-zoom {
  position: fixed;
  inset: 0;
  z-index: 70;
  display: flex;
  flex-direction: column;
  border-width: 0;
  border-radius: 0;
  background: #020617;
}
</style>
