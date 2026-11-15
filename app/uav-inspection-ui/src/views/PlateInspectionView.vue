<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { CircleAlert, ImageUp, Layers, RefreshCw, ScanLine, Sparkles } from 'lucide-vue-next'
import InspectionHeader from '../components/common/InspectionHeader.vue'
import FloatingNotice from '../components/common/FloatingNotice.vue'
import {
  plateApi,
  type AcceptanceData,
  type CoverageData,
  type PlateDetectResult,
  type PlateInfoResult,
  type RecognizerStatus,
  type ReplayData,
  type ReplayPhase,
} from '../api1/plate'

type TabKey = 'detect' | 'result' | 'replay' | 'coverage'

const activeTab = ref<TabKey>('detect')
const online = ref<boolean | null>(null)
const info = ref<PlateInfoResult | null>(null)
const acceptance = ref<AcceptanceData | null>(null)
const loadingAcceptance = ref(false)
const replay = ref<ReplayData | null>(null)
const loadingReplay = ref(false)
const replayError = ref('')
const coverage = ref<CoverageData | null>(null)
const loadingCoverage = ref(false)
const videoEl = ref<HTMLVideoElement | null>(null)
const videoTime = ref(0)
const detectResult = ref<PlateDetectResult | null>(null)
const sourceUrl = ref('')
const sourceName = ref('')
const busy = ref(false)
const dragging = ref(false)
const viewMode = ref<'annotated' | 'source'>('annotated')
const confThreshold = ref(0.35)
const recognizeEnabled = ref(true)
const previewCard = ref('')
const noticeMessage = ref('')
const noticeTone = ref<'info' | 'success' | 'warning' | 'error'>('info')
const noticeTrigger = ref(0)

const fileInput = ref<HTMLInputElement | null>(null)

const recognizer = computed<RecognizerStatus | null>(() => detectResult.value?.recognizer ?? info.value?.recognizer ?? null)
const detectorReady = computed(() => Boolean(info.value))
const hasResult = computed(() => Boolean(detectResult.value))
const annotatedUrl = computed(() =>
  detectResult.value ? `data:image/jpeg;base64,${detectResult.value.annotated_image}` : '',
)
const previewUrl = computed(() =>
  viewMode.value === 'annotated' && annotatedUrl.value ? annotatedUrl.value : sourceUrl.value,
)
const detections = computed(() => detectResult.value?.detections ?? [])
const colorStats = computed(() => {
  const stats = detectResult.value?.stats ?? {}
  return Object.entries(stats).filter(([, value]) => value > 0)
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
  if (busy.value) return '正在推理'
  if (!detectorReady.value) return '基础模式 · 检测权重未安装'
  return info.value?.capabilities.oriented_boxes ? '就绪 · OBB 旋转框' : '就绪 · 水平框'
})

function notify(message: string, tone: typeof noticeTone.value = 'info') {
  noticeMessage.value = message
  noticeTone.value = tone
  noticeTrigger.value += 1
}

function releaseSource() {
  if (sourceUrl.value.startsWith('blob:')) URL.revokeObjectURL(sourceUrl.value)
}

async function refreshHealth() {
  try {
    await plateApi.getHealth()
    online.value = true
  } catch {
    online.value = false
  }
}

async function loadInfo() {
  try {
    const result = await plateApi.getInfo()
    info.value = result.data
    confThreshold.value = result.data.config.confidence
  } catch {
    info.value = null
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

function pickFile() {
  fileInput.value?.click()
}

function handleFile(file: File | null | undefined) {
  if (!file) return
  if (!file.type.startsWith('image/')) {
    notify('请选择图片文件（JPG / PNG）', 'warning')
    return
  }
  releaseSource()
  sourceUrl.value = URL.createObjectURL(file)
  sourceName.value = file.name
  viewMode.value = 'source'
  void runDetect(file)
}

function onFileChange(event: Event) {
  const target = event.target as HTMLInputElement
  handleFile(target.files?.[0])
  target.value = ''
}

function onDrop(event: DragEvent) {
  dragging.value = false
  handleFile(event.dataTransfer?.files?.[0])
}

async function runDetect(file: File) {
  busy.value = true
  detectResult.value = null
  try {
    const result = await plateApi.detectUpload(file, confThreshold.value, recognizeEnabled.value)
    detectResult.value = result.data
    viewMode.value = 'annotated'
    const count = result.data.count
    if (count === 0) {
      notify('本帧没有检出车牌。可以调低置信度阈值再试，或确认车牌在画面中足够大。', 'warning')
    } else if (result.data.plates.length) {
      notify(`检出 ${count} 块车牌，识别出 ${result.data.plates.length} 个号码`, 'success')
    } else {
      notify(`检出 ${count} 块车牌，但识别器未安装，只有检测框与颜色分类`, 'info')
    }
  } catch (error) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    notify(detail || '检测失败，请查看后端日志', 'error')
  } finally {
    busy.value = false
  }
}

async function applyThreshold() {
  if (!detectorReady.value) return
  try {
    await plateApi.updateConfig({ confidence: confThreshold.value })
  } catch {
    notify('阈值保存失败', 'warning')
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

function fmtTime(sec: number) {
  const total = Math.max(0, Math.round(sec))
  const m = Math.floor(total / 60)
  return `${m}:${String(total % 60).padStart(2, '0')}`
}

function onVideoTime(e: Event) {
  videoTime.value = (e.target as HTMLVideoElement).currentTime
}

/** 墙钟秒 → 视频秒要减去录屏起始偏移，否则整条时间轴会早 30 秒 */
function seekToPhase(ph: ReplayPhase) {
  const el = videoEl.value
  if (!el) return
  const offset = replay.value?.video.offset_s ?? 0
  const target = Math.max(0, ph.t0 - offset)
  el.currentTime = target
  videoTime.value = target
  void el.play().catch(() => undefined)
}

const phaseCursor = computed(() => {
  const phases = replay.value?.phases ?? []
  const offset = replay.value?.video.offset_s ?? 0
  const wall = videoTime.value + offset
  for (let i = 0; i < phases.length; i += 1) {
    if (wall >= phases[i].t0 && wall < phases[i].t1) return i
  }
  return phases.length ? phases.length - 1 : -1
})

const coverageRows = computed(() => coverage.value?.rows ?? [])
const coverageSlots = computed(() => coverage.value?.slots ?? [])
const budgetUsedPct = computed(() => {
  const b = replay.value?.budget
  if (!b || !b.budget_s) return 0
  return Math.min(100, Math.round((b.wall_clock_s / b.budget_s) * 100))
})

watch(activeTab, (tab) => {
  if (tab === 'replay' && !replay.value && !loadingReplay.value) void loadReplay()
  if (tab === 'coverage' && !coverage.value && !loadingCoverage.value) void loadCoverage()
})

onMounted(async () => {
  await refreshHealth()
  await loadInfo()
  await loadAcceptance()
})

onUnmounted(() => {
  releaseSource()
})
</script>

<template>
  <div class="mobile-page relative min-h-screen overflow-x-hidden bg-slate-50 text-slate-800">
    <div class="pointer-events-none absolute top-[-10%] right-[-6%] h-[38%] w-[38%] rounded-full bg-indigo-300/20 blur-[120px]"></div>
    <div class="pointer-events-none absolute bottom-[-12%] left-[-6%] h-[38%] w-[38%] rounded-full bg-sky-300/16 blur-[120px]"></div>

    <div class="relative z-10 px-4 pt-4 md:px-6">
      <InspectionHeader title="车辆车牌巡检" :task-name="batchLabel" task-label="巡检批次" :online="online">
        <template #actions>
          <button
            class="rounded-2xl border px-5 py-3 text-sm font-medium transition"
            :class="activeTab === 'detect'
              ? 'border-indigo-300 bg-indigo-600 text-white shadow-[0_10px_25px_-15px_rgba(79,70,229,0.9)]'
              : 'border-slate-200 bg-slate-50 text-slate-700 hover:border-indigo-300 hover:bg-indigo-50'"
            @click="activeTab = 'detect'"
          >
            实时检测
          </button>
          <button
            class="rounded-2xl border px-5 py-3 text-sm font-medium transition"
            :class="activeTab === 'result'
              ? 'border-indigo-300 bg-indigo-600 text-white shadow-[0_10px_25px_-15px_rgba(79,70,229,0.9)]'
              : 'border-slate-200 bg-slate-50 text-slate-700 hover:border-indigo-300 hover:bg-indigo-50'"
            @click="activeTab = 'result'"
          >
            巡检结果
          </button>
          <button
            class="rounded-2xl border px-5 py-3 text-sm font-medium transition"
            :class="activeTab === 'replay'
              ? 'border-indigo-300 bg-indigo-600 text-white shadow-[0_10px_25px_-15px_rgba(79,70,229,0.9)]'
              : 'border-slate-200 bg-slate-50 text-slate-700 hover:border-indigo-300 hover:bg-indigo-50'"
            @click="activeTab = 'replay'"
          >
            过程回放
          </button>
          <button
            class="rounded-2xl border px-5 py-3 text-sm font-medium transition"
            :class="activeTab === 'coverage'
              ? 'border-indigo-300 bg-indigo-600 text-white shadow-[0_10px_25px_-15px_rgba(79,70,229,0.9)]'
              : 'border-slate-200 bg-slate-50 text-slate-700 hover:border-indigo-300 hover:bg-indigo-50'"
            @click="activeTab = 'coverage'"
          >
            覆盖质量
          </button>
          <button
            class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm font-medium text-slate-700 transition hover:border-indigo-300 hover:bg-indigo-50"
            @click="refreshHealth(); loadInfo()"
          >
            <RefreshCw :size="16" class="inline" />
          </button>
        </template>
      </InspectionHeader>
    </div>

    <FloatingNotice :message="noticeMessage" :tone="noticeTone" :trigger="noticeTrigger" :duration="3600" centered />

    <!-- 实时检测 -->
    <main v-if="activeTab === 'detect'" class="relative z-10 grid grid-cols-1 gap-4 px-4 pb-6 pt-2 md:px-6 xl:grid-cols-[368px_minmax(0,1fr)]">
      <aside class="space-y-3">
        <section class="rounded-[24px] border border-white bg-white/90 p-4 shadow-[0_12px_40px_-20px_rgba(79,70,229,0.24)]">
          <div class="flex items-center justify-between gap-3">
            <h2 class="text-base font-semibold text-slate-900">投放图片</h2>
            <span class="flex items-center gap-2 text-xs text-slate-500">
              <span class="h-2.5 w-2.5 rounded-full" :class="online ? 'bg-emerald-400' : 'bg-rose-400'"></span>
              {{ statusText }}
            </span>
          </div>

          <div
            class="mt-3 flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-4 py-8 text-center transition"
            :class="dragging ? 'border-indigo-400 bg-indigo-50' : 'border-slate-200 bg-slate-50/80 hover:border-indigo-300 hover:bg-indigo-50/60'"
            @click="pickFile"
            @dragover.prevent="dragging = true"
            @dragleave.prevent="dragging = false"
            @drop.prevent="onDrop"
          >
            <ImageUp :size="30" class="text-indigo-500" />
            <p class="mt-3 text-sm font-medium text-slate-800">点击选择，或把图片拖到这里</p>
            <p class="mt-1 text-xs text-slate-500">支持 JPG / PNG，单张检测</p>
            <p v-if="sourceName" class="mt-2 max-w-full truncate text-xs font-medium text-indigo-600">{{ sourceName }}</p>
          </div>
          <input ref="fileInput" type="file" accept="image/*" class="hidden" @change="onFileChange" />

          <div class="mt-4 space-y-3">
            <label class="block text-xs font-medium text-slate-600">
              置信度阈值 <span class="ml-1 font-semibold text-indigo-600">{{ confThreshold.toFixed(2) }}</span>
              <input
                v-model.number="confThreshold"
                type="range"
                min="0.05"
                max="0.95"
                step="0.05"
                class="mt-2 w-full accent-indigo-600"
                @change="applyThreshold"
              />
            </label>
            <label class="flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50/90 px-3 py-2 text-sm text-slate-700">
              <span>同时识别车牌号</span>
              <input v-model="recognizeEnabled" type="checkbox" class="h-4 w-4 accent-indigo-600" />
            </label>
          </div>
        </section>

        <section class="rounded-[24px] border border-white bg-white/90 p-4 shadow-[0_12px_40px_-20px_rgba(79,70,229,0.18)]">
          <h2 class="text-base font-semibold text-slate-900">模型状态</h2>
          <div class="mt-3 space-y-2 text-sm">
            <div class="flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50/90 px-3 py-2">
              <span class="text-slate-500">检测权重</span>
              <span class="font-medium" :class="detectorReady ? 'text-emerald-600' : 'text-amber-600'">
                {{ detectorReady ? info?.model.name : '未安装' }}
              </span>
            </div>
            <div class="flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50/90 px-3 py-2">
              <span class="text-slate-500">识别器</span>
              <span class="font-medium" :class="recognizer?.available ? 'text-emerald-600' : 'text-amber-600'">
                {{ recognizer?.available ? `${recognizer.backend} · ${recognizer.charset_size} 类` : '未安装' }}
              </span>
            </div>
            <div class="flex items-center justify-between rounded-xl border border-slate-200 bg-slate-50/90 px-3 py-2">
              <span class="text-slate-500">推理设备</span>
              <span class="font-medium text-slate-900">{{ info?.system.device || '—' }}</span>
            </div>
          </div>
          <p v-if="recognizer && !recognizer.available" class="mt-3 flex gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-800">
            <CircleAlert :size="15" class="mt-0.5 shrink-0" />
            <span>{{ recognizer.note }}</span>
          </p>
        </section>
      </aside>

      <section class="space-y-3">
        <div class="rounded-[24px] border border-white bg-white/90 p-4 shadow-[0_12px_40px_-20px_rgba(79,70,229,0.22)]">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <h2 class="text-base font-semibold text-slate-900">检测画面</h2>
            <div class="flex items-center gap-2">
              <div class="flex rounded-xl border border-slate-200 bg-slate-50 p-1 text-xs">
                <button
                  class="rounded-lg px-3 py-1.5 font-medium transition"
                  :class="viewMode === 'annotated' ? 'bg-white text-indigo-700 shadow-sm' : 'text-slate-500'"
                  :disabled="!annotatedUrl"
                  @click="viewMode = 'annotated'"
                >
                  标注图
                </button>
                <button
                  class="rounded-lg px-3 py-1.5 font-medium transition"
                  :class="viewMode === 'source' ? 'bg-white text-indigo-700 shadow-sm' : 'text-slate-500'"
                  :disabled="!sourceUrl"
                  @click="viewMode = 'source'"
                >
                  原图
                </button>
              </div>
            </div>
          </div>

          <div class="mt-3 flex min-h-[320px] items-center justify-center overflow-hidden rounded-2xl border border-slate-200 bg-slate-900/95">
            <img v-if="previewUrl" :src="previewUrl" alt="检测画面" class="max-h-[560px] w-full object-contain" />
            <div v-else class="px-6 py-16 text-center text-slate-400">
              <ScanLine :size="38" class="mx-auto" />
              <p class="mt-3 text-sm">还没有图片。左侧投放一张含车牌的图片开始检测。</p>
            </div>
          </div>

          <div v-if="hasResult" class="mt-3 flex flex-wrap items-center gap-2 text-xs">
            <span class="rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1 font-medium text-indigo-700">
              检出 {{ detectResult?.count }} 块
            </span>
            <span
              v-for="[key, value] in colorStats"
              :key="key"
              class="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-slate-600"
            >
              {{ key }} · {{ value }}
            </span>
            <span class="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-slate-600">
              推理 {{ detectResult?.inference_ms }} ms
            </span>
            <span class="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-slate-600">
              {{ detectResult?.image_size[0] }} × {{ detectResult?.image_size[1] }}
            </span>
          </div>
        </div>

        <div class="rounded-[24px] border border-white bg-white/90 p-4 shadow-[0_12px_40px_-20px_rgba(79,70,229,0.18)]">
          <h2 class="text-base font-semibold text-slate-900">识别结果</h2>
          <div v-if="!detections.length" class="mt-3 rounded-xl border border-dashed border-slate-200 px-4 py-8 text-center text-sm text-slate-500">
            {{ hasResult ? '本帧没有检出车牌' : '等待检测' }}
          </div>
          <div v-else class="mt-3 overflow-x-auto">
            <table class="min-w-full text-sm">
              <thead>
                <tr class="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th class="px-3 py-2 font-medium">序号</th>
                  <th class="px-3 py-2 font-medium">车牌号</th>
                  <th class="px-3 py-2 font-medium">颜色</th>
                  <th class="px-3 py-2 font-medium">检测置信度</th>
                  <th class="px-3 py-2 font-medium">识别置信度</th>
                  <th class="px-3 py-2 font-medium">位置</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(item, index) in detections" :key="index" class="border-b border-slate-100 last:border-0">
                  <td class="px-3 py-2 text-slate-500">{{ index + 1 }}</td>
                  <td class="px-3 py-2 font-semibold text-slate-900">
                    {{ item.text || '—' }}
                  </td>
                  <td class="px-3 py-2 text-slate-600">{{ item.color_cn }}</td>
                  <td class="px-3 py-2 text-slate-600">{{ item.conf.toFixed(3) }}</td>
                  <td class="px-3 py-2 text-slate-600">{{ item.text_score ? item.text_score.toFixed(3) : '—' }}</td>
                  <td class="px-3 py-2 text-xs text-slate-500">
                    {{ item.bbox.map((v) => Math.round(v)).join(', ') }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </main>

    <!-- 巡检结果 -->
    <main v-else-if="activeTab === 'result'" class="relative z-10 space-y-4 px-4 pb-8 pt-2 md:px-6">
      <section v-if="!acceptance" class="rounded-[24px] border border-white bg-white/90 px-6 py-14 text-center shadow-sm">
        <Layers :size="36" class="mx-auto text-slate-300" />
        <p class="mt-3 text-sm text-slate-500">
          {{ loadingAcceptance ? '正在载入巡检结果…' : '还没有可回放的巡检批次。' }}
        </p>
      </section>

      <template v-else>
        <section class="rounded-[24px] border border-white bg-white/90 p-4 shadow-[0_12px_40px_-20px_rgba(79,70,229,0.24)]">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 class="text-base font-semibold text-slate-900">最近一次自主巡检</h2>
              <p class="mt-1 text-xs text-slate-500">
                {{ acceptance.batch.start }} — {{ acceptance.batch.end }} · 退出码 {{ acceptance.batch.exit_code }} ·
                {{ acceptance.batch.fsm }}
              </p>
            </div>
            <span class="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">
              {{ violatedCount }} 辆压线越界 / {{ violations.length }} 辆受检
            </span>
          </div>

          <div class="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div
              v-for="card in summaryCards"
              :key="card.label"
              class="rounded-2xl border border-slate-200 bg-slate-50/80 px-3 py-3"
            >
              <div class="text-xs text-slate-500">{{ card.label }}</div>
              <div class="mt-1 text-xl font-semibold text-slate-900">{{ card.value }}</div>
              <div class="mt-1 text-[11px] leading-snug text-slate-500">{{ card.note }}</div>
            </div>
          </div>
        </section>

        <section class="rounded-[24px] border border-white bg-white/90 p-4 shadow-[0_12px_40px_-20px_rgba(79,70,229,0.18)]">
          <div class="flex items-center justify-between">
            <h2 class="text-base font-semibold text-slate-900">车辆认定</h2>
            <span class="text-xs text-slate-500">点击缩略图查看识别卡</span>
          </div>
          <div class="mt-3 overflow-x-auto">
            <table class="min-w-full text-sm">
              <thead>
                <tr class="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th class="px-3 py-2 font-medium">车辆</th>
                  <th class="px-3 py-2 font-medium">场景实体</th>
                  <th class="px-3 py-2 font-medium">车牌号</th>
                  <th class="px-3 py-2 font-medium">置信度</th>
                  <th class="px-3 py-2 font-medium">拍摄距离</th>
                  <th class="px-3 py-2 font-medium">腿</th>
                  <th class="px-3 py-2 font-medium">备注</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="vehicle in vehicles" :key="vehicle.car" class="border-b border-slate-100 last:border-0">
                  <td class="px-3 py-2">
                    <button
                      v-if="vehicle.card_url"
                      class="overflow-hidden rounded-lg border border-slate-200 transition hover:border-indigo-400"
                      @click="showCard(vehicle.card_url)"
                    >
                      <img :src="vehicle.card_url" :alt="vehicle.car" class="h-12 w-20 object-cover" />
                    </button>
                    <span v-else class="text-slate-500">{{ vehicle.car }}</span>
                  </td>
                  <td class="px-3 py-2 text-slate-500">{{ vehicle.real_car }}</td>
                  <td class="px-3 py-2 font-semibold text-slate-900">{{ vehicle.plate }}</td>
                  <td class="px-3 py-2 text-slate-600">{{ vehicle.confidence.toFixed(3) }}</td>
                  <td class="px-3 py-2 text-slate-600">{{ vehicle.distance_m }} m</td>
                  <td class="px-3 py-2 text-slate-600">{{ vehicle.leg }}</td>
                  <td class="px-3 py-2 text-xs text-slate-500">{{ vehicle.note || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="rounded-[24px] border border-white bg-white/90 p-4 shadow-[0_12px_40px_-20px_rgba(79,70,229,0.18)]">
          <div class="flex items-center justify-between">
            <h2 class="text-base font-semibold text-slate-900">违停判定</h2>
            <span class="text-xs text-slate-500">最小余量为负即越界</span>
          </div>
          <div class="mt-3 overflow-x-auto">
            <table class="min-w-full text-sm">
              <thead>
                <tr class="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th class="px-3 py-2 font-medium">车辆</th>
                  <th class="px-3 py-2 font-medium">车位</th>
                  <th class="px-3 py-2 font-medium">横向偏移</th>
                  <th class="px-3 py-2 font-medium">纵向偏移</th>
                  <th class="px-3 py-2 font-medium">最小余量</th>
                  <th class="px-3 py-2 font-medium">形状误差</th>
                  <th class="px-3 py-2 font-medium">判定</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in violations" :key="row.car" class="border-b border-slate-100 last:border-0">
                  <td class="px-3 py-2 font-medium text-slate-900">{{ row.car }}</td>
                  <td class="px-3 py-2 text-slate-600">{{ row.slot }}</td>
                  <td class="px-3 py-2 text-slate-600">{{ row.lateral_m.toFixed(3) }} m</td>
                  <td class="px-3 py-2 text-slate-600">{{ row.longitudinal_m.toFixed(3) }} m</td>
                  <td class="px-3 py-2 font-medium" :class="row.margin_m < 0 ? 'text-rose-600' : 'text-emerald-600'">
                    {{ row.margin_m.toFixed(3) }} m
                  </td>
                  <td class="px-3 py-2 text-slate-600">{{ row.shape_error_m.toFixed(3) }} m</td>
                  <td class="px-3 py-2">
                    <span
                      class="rounded-full px-2.5 py-1 text-xs font-medium"
                      :class="row.margin_m < 0
                        ? 'bg-rose-50 text-rose-700 ring-1 ring-rose-200'
                        : 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200'"
                    >
                      {{ row.verdict }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="mt-3 text-xs leading-relaxed text-slate-500">
            最小余量 = 标准半尺寸 −（车心偏移 + 车体投影半尺寸），负值即越界。形状误差是车牌四点反算的车体四角与真实四角之差。
          </p>
        </section>

        <section class="rounded-[24px] border border-indigo-100 bg-indigo-50/60 p-4">
          <div class="flex items-start gap-3">
            <Sparkles :size="18" class="mt-0.5 shrink-0 text-indigo-500" />
            <div class="text-xs leading-relaxed text-indigo-900">
              <p class="font-semibold">这批结果怎么来的</p>
              <p class="mt-1">
                {{ acceptance.retry.触发 }}，系统按轮次补拍 {{ acceptance.retry.补拍 }}，结果 {{ acceptance.retry.结果 }}。
                同一套流程另有 {{ acceptance.reruns.length }} 轮连续通过，判定口径一致。
              </p>
            </div>
          </div>
        </section>
      </template>
    </main>

    <!-- 过程回放 -->
    <main
      v-else-if="activeTab === 'replay'"
      class="relative z-10 grid grid-cols-1 gap-4 px-4 pb-6 pt-2 md:px-6 xl:grid-cols-[minmax(0,1fr)_340px]"
    >
      <section class="rounded-[24px] border border-white bg-white/90 p-4 shadow-[0_12px_40px_-20px_rgba(79,70,229,0.24)]">
        <div v-if="loadingReplay" class="py-24 text-center text-slate-500">正在载入回放…</div>
        <div v-else-if="!replay" class="py-24 text-center text-slate-500">
          {{ replayError || '没有可用的回放数据。' }}
        </div>
        <template v-else>
          <div class="flex flex-wrap items-start justify-between gap-2 pb-3">
            <div>
              <p class="text-xs uppercase tracking-[0.3em] text-indigo-400">MISSION REPLAY</p>
              <h2 class="mt-1 text-lg font-semibold text-slate-900">{{ replay.mission.scenario }}</h2>
            </div>
            <div class="text-right text-xs leading-relaxed text-slate-500">
              <p class="font-mono text-[11px] text-slate-600">{{ replay.mission.run }}</p>
              <p>{{ replay.mission.started_at }} 起</p>
              <p>{{ replay.mission.platform }} · {{ replay.mission.barrier }}</p>
              <p
                v-if="batchMismatch"
                class="mt-1 inline-block rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700 ring-1 ring-amber-200"
                :title="`巡检结果批次 ${acceptanceRun}，过程回放批次 ${replayRun}，两者不是同一跑次`"
              >
                回放批次 ≠ 巡检结果批次（{{ acceptanceRun }}）
              </p>
            </div>
          </div>

          <div class="overflow-hidden rounded-2xl bg-slate-900">
            <video
              ref="videoEl"
              :src="replay.video.src"
              :poster="replay.video.poster"
              controls
              playsinline
              preload="metadata"
              class="aspect-video w-full bg-slate-900"
              @timeupdate="onVideoTime"
            />
          </div>

          <div class="mt-4">
            <div class="mb-2 flex flex-wrap items-baseline justify-between gap-2">
              <h3 class="text-sm font-semibold text-slate-800">阶段时间轴（点一下跳到该阶段）</h3>
              <span class="font-mono text-xs text-slate-500">
                {{ fmtTime(videoTime) }} / {{ fmtTime(replay.video.seconds) }}
                · 录屏比任务晚 {{ replay.video.offset_s }} s
              </span>
            </div>
            <div class="flex gap-1">
              <button
                v-for="(ph, i) in replay.phases"
                :key="ph.key"
                class="group relative h-20 min-w-[74px] overflow-hidden rounded-xl border text-left transition"
                :class="i === phaseCursor
                  ? 'border-indigo-400 ring-2 ring-indigo-300'
                  : 'border-slate-200 hover:border-indigo-300'"
                :style="{ flexGrow: ph.seconds }"
                @click="seekToPhase(ph)"
              >
                <img :src="ph.cover" :alt="ph.label" class="absolute inset-0 h-full w-full object-cover opacity-70" />
                <span class="absolute inset-0 bg-gradient-to-t from-slate-900/85 via-slate-900/25 to-transparent" />
                <span class="relative flex h-full flex-col justify-end p-2">
                  <span class="text-[11px] font-semibold leading-tight text-white">{{ ph.label }}</span>
                  <span class="text-[10px] text-white/75">{{ fmtTime(ph.t0) }} · {{ ph.seconds }} s</span>
                </span>
              </button>
            </div>
            <p class="mt-2 text-[11px] leading-relaxed text-slate-500">
              录屏是固定监控机位俯视（场地内侧上空 19 m），不是机载视角；无人机在画面里只是个移动的小点。
              时间轴按墙钟切段，点段首会跳转，但前 {{ replay.video.offset_s }} s 任务已经起飞、录屏还没开始。
            </p>
          </div>
        </template>
      </section>

      <aside class="space-y-3">
        <section
          v-if="replay"
          class="rounded-[24px] border border-white bg-white/90 p-4 shadow-[0_12px_40px_-20px_rgba(79,70,229,0.18)]"
        >
          <h3 class="text-sm font-semibold text-slate-800">任务结果</h3>
          <dl class="mt-3 space-y-2 text-sm">
            <div class="flex justify-between">
              <dt class="text-slate-500">终态</dt>
              <dd class="font-semibold text-emerald-600">{{ replay.kpi.final }} · {{ replay.kpi.note }}</dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-slate-500">清单 / 拍成</dt>
              <dd class="font-mono text-slate-800">{{ replay.kpi.n_cars }} / {{ replay.kpi.n_captured }}</dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-slate-500">INSPECT 轮次</dt>
              <dd class="font-mono text-slate-800">{{ replay.kpi.inspect_round }}</dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-slate-500">墙钟 / 预算</dt>
              <dd class="font-mono text-slate-800">{{ replay.budget.wall_clock_s }} / {{ replay.budget.budget_s }} s</dd>
            </div>
          </dl>
          <div class="mt-3">
            <div class="h-2 overflow-hidden rounded-full bg-slate-200">
              <div class="h-full rounded-full bg-indigo-500" :style="{ width: budgetUsedPct + '%' }" />
            </div>
            <p class="mt-1 text-[11px] text-slate-500">用掉预算的 {{ budgetUsedPct }}%</p>
          </div>
          <div class="mt-3 space-y-1 border-t border-slate-100 pt-2 text-[11px] text-slate-500">
            <p v-for="(rd, i) in replay.kpi.rounds" :key="i">
              第 {{ i + 1 }} 轮：拍成 {{ rd.captured }} / {{ rd.cars }} 辆，rc={{ rd.rc }}
            </p>
          </div>
        </section>

        <section
          v-if="replay"
          class="rounded-[24px] border border-white bg-white/90 p-4 shadow-[0_12px_40px_-20px_rgba(79,70,229,0.18)]"
        >
          <h3 class="text-sm font-semibold text-slate-800">关键事件</h3>
          <ul class="mt-2 max-h-[300px] space-y-1.5 overflow-auto pr-1 text-[11px] leading-snug">
            <li v-for="(ev, i) in replay.events" :key="i" class="flex gap-2">
              <span class="w-10 shrink-0 font-mono text-slate-400">{{ fmtTime(ev.t) }}</span>
              <span :class="ev.kind === 'fsm' ? 'text-indigo-600' : 'text-slate-600'">{{ ev.text }}</span>
            </li>
          </ul>
        </section>
      </aside>
    </main>

    <!-- 覆盖质量 -->
    <main
      v-else-if="activeTab === 'coverage'"
      class="relative z-10 grid grid-cols-1 gap-4 px-4 pb-6 pt-2 md:px-6 xl:grid-cols-[minmax(0,1fr)_340px]"
    >
      <section class="rounded-[24px] border border-white bg-white/90 p-4 shadow-[0_12px_40px_-20px_rgba(79,70,229,0.24)]">
        <div v-if="loadingCoverage" class="py-24 text-center text-slate-500">正在载入覆盖质量…</div>
        <div v-else-if="!coverage" class="py-24 text-center text-slate-500">没有可用的覆盖质量数据。</div>
        <template v-else>
          <div class="flex flex-wrap items-baseline justify-between gap-2 pb-3">
            <div>
              <p class="text-xs uppercase tracking-[0.3em] text-indigo-400">L4 COVERAGE</p>
              <h2 class="mt-1 text-lg font-semibold text-slate-900">可观测区覆盖质量</h2>
            </div>
            <p class="text-xs text-slate-500">
              栅格 {{ coverage.source.cell_m }} m · 观测 {{ coverage.source.frames_used }} 帧 · {{ coverage.source.grid[0] }}×{{ coverage.source.grid[1] }}
            </p>
          </div>
          <img :src="coverage.image" alt="L4 覆盖质量热力图" class="w-full rounded-2xl border border-slate-200" />
          <p class="mt-2 text-[11px] leading-relaxed text-slate-500">{{ coverage.source.note }}。</p>
        </template>
      </section>

      <aside class="space-y-3">
        <section
          v-if="coverage"
          class="rounded-[24px] border border-white bg-white/90 p-4 shadow-[0_12px_40px_-20px_rgba(79,70,229,0.18)]"
        >
          <h3 class="text-sm font-semibold text-slate-800">分级占比</h3>
          <p class="mt-1 text-[11px] text-slate-500">
            分母 {{ coverage.area.observable_cells }} 格 = 场地 {{ coverage.area.site_cells }} − 车体 {{ coverage.area.car_cells }}
          </p>
          <div v-for="tier in coverage.coverage" :key="tier.min_frames" class="mt-2.5">
            <div class="flex justify-between text-xs">
              <span class="text-slate-600">{{ tier.min_frames }} 帧以上</span>
              <span class="font-mono text-slate-800">{{ tier.ratio }}%</span>
            </div>
            <div class="mt-1 h-2 overflow-hidden rounded-full bg-slate-200">
              <div class="h-full rounded-full bg-indigo-500" :style="{ width: tier.ratio + '%' }" />
            </div>
          </div>
          <div class="mt-3 grid grid-cols-2 gap-2 border-t border-slate-100 pt-2 text-[11px] text-slate-500">
            <p>中位观测 {{ coverage.depth.frames_p50 }} 帧</p>
            <p>P95 {{ coverage.depth.frames_p95 }} 帧</p>
            <p>最近距离中位 {{ coverage.depth.dist_p50 }} m</p>
            <p>P95 {{ coverage.depth.dist_p95 }} m</p>
          </div>
        </section>

        <section
          v-if="coverage"
          class="rounded-[24px] border border-white bg-white/90 p-4 shadow-[0_12px_40px_-20px_rgba(79,70,229,0.18)]"
        >
          <h3 class="text-sm font-semibold text-slate-800">分排质量</h3>
          <table class="mt-2 w-full text-xs">
            <thead class="text-slate-500">
              <tr>
                <th class="py-1 text-left font-medium">排</th>
                <th class="py-1 text-right font-medium">中位帧</th>
                <th class="py-1 text-right font-medium">3 帧以上</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in coverageRows" :key="row.label" class="border-t border-slate-100">
                <td class="py-1 text-slate-700">{{ row.label }}</td>
                <td class="py-1 text-right font-mono text-slate-700">{{ row.median_frames }}</td>
                <td class="py-1 text-right font-mono text-slate-700">{{ row.ge3 }}%</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section
          v-if="coverage"
          class="rounded-[24px] border border-white bg-white/90 p-4 shadow-[0_12px_40px_-20px_rgba(79,70,229,0.18)]"
        >
          <h3 class="text-sm font-semibold text-slate-800">车位处质量</h3>
          <div class="mt-2 max-h-[240px] overflow-auto">
            <table class="w-full text-[11px]">
              <thead class="sticky top-0 bg-white text-slate-500">
                <tr>
                  <th class="py-1 text-left font-medium">车位</th>
                  <th class="py-1 text-right font-medium">帧</th>
                  <th class="py-1 text-right font-medium">点</th>
                  <th class="py-1 text-right font-medium">最近 m</th>
                </tr>
              </thead>
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
      </aside>
    </main>

    <div
      v-if="previewCard"
      class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 p-6"
      @click="previewCard = ''"
    >
      <img :src="previewCard" alt="识别结果卡" class="max-h-full max-w-4xl rounded-xl shadow-2xl" />
    </div>
  </div>
</template>
