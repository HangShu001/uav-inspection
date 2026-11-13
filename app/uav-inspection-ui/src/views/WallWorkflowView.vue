<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowLeft, FileDown, MapPin, MessageCircle, Plus } from 'lucide-vue-next'
import WallLive from '../components/wall/WallLive.vue'
import WallLocationMap from '../components/wall/WallLocationMap.vue'
import WallWorkOrder from '../components/wall/WallWorkOrder.vue'
import { findTelemetry, parseSrt, type TelemetryFrame } from '../utils/srtParser'
import { webPath } from '../utils/webroot'
import { uploadInspection, wallError, wallWorkflow, type CountKey, type Finding, type FindingState,
  type ModelOption, type OrderAction, type Task, type TaskDetail } from '../api1/wallWorkflow'

const tasks = ref<Task[]>([])
const taskId = ref('')
const current = ref<TaskDetail | null>(null)
const video = ref<HTMLVideoElement | null>(null)
const videoTime = ref(0)
const frames = ref<TelemetryFrame[]>([])
const telemetryError = ref(false)
const videoError = ref(false)
const notice = ref('')
const error = ref('')
const busy = ref(false)
const loading = ref(true)
const showUpload = ref(false)
const showLive = ref(false)
const name = ref('')
const building = ref('')
const facade = ref('')
const source = ref<File>()
const initialSubtitle = ref<File>()
const progress = ref<number | null>(null)
const uploadAbort = ref<AbortController | null>(null)
let pollTimer: number | undefined
let stopped = false
let detailRequest = 0
let subtitleRequest = 0
const subtitleOffset = ref(0)
const models = ref<ModelOption[]>([])
const model = ref('')
const canUploadModel = ref(false)
const sensitivity = ref(0.75)
const iou = ref(0.45)
const mode = ref<'sample' | 'all'>('sample')
const tab = ref<'findings' | 'orders'>('findings')
const filter = ref<CountKey | 'all' | 'dismissed'>('all')
const selected = ref<string[]>([])
const findingId = ref('')
const orderId = ref('')
const floor = ref('')
const note = ref('')
const assistantOpen = ref(false)
const prompt = ref('')
const assistantReply = ref('我可以帮你找待复核记录、跳到指定时间，或说明怎样上传字幕。')
const draftPreview = ref(false)

const labels: Record<FindingState, string> = { pending: '待复核', confirmed: '已确认', dismissed: '已排除', merged: '已合并' }
const cards: { key: CountKey; label: string }[] = [
  { key: 'pending', label: '疑似待复核' }, { key: 'confirmed', label: '已确认脱落' },
  { key: 'assigned', label: '已派单' }, { key: 'completed', label: '已修复' },
]
const runStates = { queued: '等待分析', running: '正在分析', completed: '分析完成', failed: '分析未完成', cancelled: '分析已停止' }
const run = computed(() => current.value?.runs[0])
const analyzing = computed(() => run.value?.state === 'running' || run.value?.state === 'queued')
const currentFinding = computed(() => current.value?.findings.find(item => item.id === findingId.value))
const order = computed(() => current.value?.orders.find(item => item.id === orderId.value) || current.value?.orders[0])
const manager = computed(() => current.value?.can_manage ?? false)
const telemetry = computed(() => {
  const at = videoTime.value - (current.value?.task.offset || 0)
  const frame = findTelemetry(frames.value, at)
  return frame && at >= frame.time && at <= frame.endTime + 0.5 ? frame : null
})
const currentPoint = computed(() => telemetry.value && validCoordinate(telemetry.value)
  ? { latitude: telemetry.value.latitude, longitude: telemetry.value.longitude } : null)
const routePoints = computed(() => {
  const step = Math.max(1, Math.ceil(frames.value.length / 350))
  const interval = (frames.value.at(-1)?.time || 0) / 350
  const gap = Math.max(3, interval * 2.5)
  return frames.value.filter((frame, index) => index % step === 0 && validCoordinate(frame)).map(frame => ({
    id: String(frame.time), latitude: frame.latitude, longitude: frame.longitude, time: frame.time,
    label: '飞行轨迹', maxGap: gap, color: '#0f766e',
  }))
})
const visibleFindings = computed(() => {
  const detail = current.value
  if (!detail) return []
  if (filter.value === 'assigned' || filter.value === 'completed') {
    const ids = new Set(detail.orders.filter(order => filter.value === 'completed'
      ? order.state === 'completed' : ['assigned', 'in_progress', 'review'].includes(order.state)).flatMap(order => order.finding_ids))
    return detail.findings.filter(finding => ids.has(finding.id))
  }
  return detail.findings.filter(finding => filter.value === 'all' ? finding.state !== 'merged' : finding.state === filter.value)
})
const mayDraft = computed(() => selected.value.length > 0 &&
  selected.value.every(id => current.value?.findings.find(finding => finding.id === id)?.state === 'confirmed'))
const covered = computed(() => run.value && current.value?.task.duration
  ? Math.min(100, Math.round(run.value.coverage / current.value.task.duration * 100)) : null)

function validCoordinate(frame: TelemetryFrame) {
  return frame.gpsAvailable === true && Number.isFinite(frame.latitude) && Number.isFinite(frame.longitude) &&
    Math.abs(frame.latitude) <= 90 && Math.abs(frame.longitude) <= 180
}
function time(seconds: number) {
  return Math.floor(seconds / 60) + ':' + String(Math.floor(seconds % 60)).padStart(2, '0')
}
function localTime(seconds: number) {
  return seconds.toFixed(1) + ' 秒'
}
function file(event: Event) {
  return (event.target as HTMLInputElement).files?.[0]
}
async function refreshTasks(preferred?: string) {
  tasks.value = await wallWorkflow.tasks()
  if (!stopped) taskId.value = preferred || taskId.value || tasks.value[0]?.id || ''
}
async function refresh(id = taskId.value) {
  if (!id) return
  const requestId = ++detailRequest
  const data = await wallWorkflow.detail(id)
  if (!stopped && id === taskId.value && requestId === detailRequest) current.value = data
}
async function refreshModels() {
  const data = await wallWorkflow.models()
  models.value = data.models
  canUploadModel.value = data.can_upload
  if (!models.value.some(item => item.id === model.value)) model.value = models.value[0]?.id || ''
}
async function act(operation: () => Promise<void>, success?: string) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    await operation()
    if (success) notice.value = success
  } catch (failure) {
    error.value = wallError(failure)
  } finally {
    busy.value = false
  }
}
watch(taskId, async id => {
  current.value = null
  frames.value = []
  videoTime.value = 0
  videoError.value = false
  selected.value = []
  findingId.value = ''
  orderId.value = ''
  filter.value = 'all'
  tab.value = 'findings'
  draftPreview.value = false
  if (id) {
    try { await refresh(id) } catch (failure) { if (id === taskId.value) error.value = wallError(failure) }
  }
})
watch(() => current.value?.task.offset, value => { subtitleOffset.value = value || 0 })
async function loadSubtitle(url: string | null | undefined) {
  const requestId = ++subtitleRequest
  telemetryError.value = false
  frames.value = []
  if (!url) return
  try {
    const response = await fetch(url, { cache: 'no-store' })
    if (!response.ok) throw new Error()
    const parsed = parseSrt(await response.text())
    if (!stopped && requestId === subtitleRequest) frames.value = parsed
  } catch {
    if (!stopped && requestId === subtitleRequest) telemetryError.value = true
  }
}
watch(() => current.value?.task.subtitle_url, loadSubtitle)
onMounted(async () => {
  try {
    await Promise.all([refreshTasks(), refreshModels()])
  } catch (failure) {
    error.value = wallError(failure)
  } finally {
    loading.value = false
  }
  if (stopped) return
  pollTimer = window.setInterval(() => {
    if (taskId.value && !busy.value) void refresh().catch(() => {})
  }, 3000)
})
onUnmounted(() => {
  stopped = true
  clearInterval(pollTimer)
  uploadAbort.value?.abort()
})
function submitUpload() {
  const video = source.value
  if (!video || !name.value || !building.value || !facade.value) return
  void act(async () => {
    const controller = new AbortController()
    uploadAbort.value = controller
    progress.value = 0
    try {
      const id = await uploadInspection(video, name.value, building.value, facade.value,
        value => { progress.value = value }, controller.signal)
      const subtitle = initialSubtitle.value
      showUpload.value = false
      await refreshTasks(id)
      if (subtitle) {
        try { await wallWorkflow.subtitle(id, subtitle) }
        catch { error.value = '视频已保存。字幕上传失败，请从任务中重新添加。' }
      }
      await refresh(id)
      source.value = undefined
      initialSubtitle.value = undefined
      notice.value = '视频已添加，可以开始检测。'
    } catch (failure) {
      if (!controller.signal.aborted) throw failure
      notice.value = '已暂停上传。点击继续上传可接着传。'
    } finally {
      uploadAbort.value = null
    }
  })
}
function uploadSubtitle(event: Event) {
  const value = file(event)
  const id = taskId.value
  if (!value || !id) return
  void act(async () => {
    await wallWorkflow.subtitle(id, value)
    await refresh(id)
    await loadSubtitle(current.value?.task.subtitle_url)
  }, '字幕已保存。')
  ;(event.target as HTMLInputElement).value = ''
}
function uploadModel(event: Event) {
  const value = file(event)
  if (!value) return
  void act(async () => {
    const saved = await wallWorkflow.uploadModel(value)
    await refreshModels()
    model.value = saved.id
  }, '检测模型已添加。')
  ;(event.target as HTMLInputElement).value = ''
}
function saveOffset(value: number) {
  void act(async () => {
    await wallWorkflow.offset(taskId.value, value)
    await refresh()
  }, '字幕时间已调整。')
}
function seek(seconds: number) {
  if (!video.value) return
  video.value.currentTime = seconds
  videoTime.value = seconds
  video.value.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
}
function openFinding(finding: Finding) {
  findingId.value = finding.id
  floor.value = finding.floor
  note.value = finding.note
  seek(finding.evidence_time)
}
function review(finding: Finding, state: FindingState) {
  void act(async () => {
    await wallWorkflow.review(taskId.value, finding, state, floor.value, note.value)
    await refresh()
  }, '复核结果已保存。')
}
function mergeFindings() {
  const target = currentFinding.value
  if (!target || !window.confirm('把所选记录合并到当前打开的发现？')) return
  void act(async () => {
    await wallWorkflow.merge(taskId.value, target.id, selected.value)
    selected.value = []
    await refresh()
  }, '已合并所选记录。')
}
function draft() {
  void act(async () => {
    const created = await wallWorkflow.draft(taskId.value, selected.value)
    draftPreview.value = false
    orderId.value = created.id
    tab.value = 'orders'
    selected.value = []
    await refresh()
  }, '工单草稿已生成。')
}
function orderAction(action: OrderAction, data: Record<string, unknown>) {
  if (!order.value) return
  const id = order.value.id
  void act(async () => {
    await wallWorkflow.order(taskId.value, id, action, data)
    await refresh()
  }, '工单已更新。')
}
function orderPhoto(kind: 'before' | 'after', file: File) {
  if (!order.value) return
  const id = order.value.id
  void act(async () => {
    await wallWorkflow.photo(taskId.value, id, kind, file)
    await refresh()
  }, '照片已保存。')
}
function changeFilter(value: typeof filter.value) {
  filter.value = value
  tab.value = 'findings'
}
async function ask(text = prompt.value, useProvider = true): Promise<void> {
  if (!text.trim()) return
  prompt.value = ''
  if (/字幕|SRT/i.test(text) && /上传|添加|怎么|如何/.test(text)) {
    assistantReply.value = '选择一个任务，在飞行数据下方点“添加字幕”，选和视频对应的 SRT 文件。'
  } else if (/待复核|疑似/.test(text) && current.value) {
    const direction = text.match(/([北南东西])(?:立面|面)/)?.[1]
    if (direction && !current.value.task.facade.includes(direction)) {
      assistantReply.value = '当前任务是' + current.value.task.facade + '。请先在上方选择对应立面的任务。'
      return
    }
    changeFilter('pending')
    assistantReply.value = '已打开当前任务的待复核记录。'
  } else if (/工单|派单/.test(text)) {
    if (mayDraft.value) {
      tab.value = 'findings'
      draftPreview.value = true
      assistantReply.value = '已打开工单预览，请核对所选缺陷。'
    } else assistantReply.value = '先确认缺陷，再在发现列表勾选需要维修的记录，点击“生成工单”。'
  } else if (/跳|播放|定位/.test(text)) {
    const match = text.match(/(\d{1,3})[:：]([0-5]\d)|(\d+(?:\.\d+)?)\s*秒/)
    const seconds = match ? (match[3] ? Number(match[3]) : Number(match[1]) * 60 + Number(match[2])) : NaN
    if (video.value && Number.isFinite(seconds) && seconds >= 0 && seconds <= video.value.duration) {
      seek(seconds)
      assistantReply.value = '已跳到 ' + time(seconds) + '。'
    } else assistantReply.value = '请先打开任务，再输入视频中的时间，例如“跳到 02:15”。'
  } else {
    const id = taskId.value
    if (useProvider) {
      const result = await wallWorkflow.interpret(text, id || null).catch(() => null)
      if (id !== taskId.value || stopped) return
      if (result?.action === 'subtitle') return ask('怎么上传字幕', false)
      if (result?.action === 'pending' && current.value) return ask('查看待复核记录', false)
      if (result?.action === 'draft') return ask('生成工单', false)
      if (result?.action === 'seek' && result.seconds !== undefined) return ask('跳到 ' + result.seconds + ' 秒', false)
    }
    assistantReply.value = '你可以问我怎样上传字幕、查看待复核记录、跳转视频时间，或怎样生成工单。'
  }
}
</script>

<template>
  <div class="min-h-screen bg-slate-50 text-slate-900">
    <header class="border-b border-slate-200 bg-white">
      <div class="mx-auto flex max-w-[1500px] flex-wrap items-center justify-between gap-3 px-4 py-4 md:px-8">
        <div>
          <RouterLink to="/" class="mb-1 inline-flex items-center gap-1 text-sm text-slate-600"><ArrowLeft :size="15" /> 返回首页</RouterLink>
          <h1 class="text-2xl font-semibold">建筑外墙巡检</h1>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <RouterLink to="/wall/replay" class="button">历史任务</RouterLink>
          <button class="button" :aria-expanded="showLive" @click="showLive = !showLive">现场直播</button>
          <button class="button" :aria-expanded="assistantOpen" @click="assistantOpen = !assistantOpen"><MessageCircle :size="16" /> 巡检助手</button>
          <button class="primary" @click="showUpload = !showUpload"><Plus :size="17" /> 上传视频</button>
        </div>
      </div>
    </header>
    <main class="mx-auto max-w-[1500px] space-y-4 px-4 py-4 md:px-8">
      <p v-if="error" class="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">{{ error }}</p>
      <p v-if="notice" class="rounded-md bg-teal-50 p-3 text-sm text-teal-900" role="status">{{ notice }}</p>
      <WallLive v-if="showLive" />
      <section v-if="showUpload" class="panel">
        <h2 class="font-semibold">上传巡检视频</h2>
        <form class="mt-3 grid gap-3 text-sm md:grid-cols-3" @submit.prevent="submitUpload">
          <label>任务名称<input v-model.trim="name" class="field" maxlength="120" required :disabled="busy" /></label>
          <label>楼栋<input v-model.trim="building" class="field" maxlength="100" placeholder="例如 2 号楼" required :disabled="busy" /></label>
          <label>立面<input v-model.trim="facade" class="field" maxlength="60" placeholder="例如 北立面" required :disabled="busy" /></label>
          <label>视频<input type="file" accept=".mp4,.mov,.avi,.mkv,.webm" class="field" :disabled="busy" @change="source = file($event); progress = null" /></label>
          <label>对应 SRT（可稍后添加）<input type="file" accept=".srt" class="field" :disabled="busy" @change="initialSubtitle = file($event)" /></label>
          <div class="flex flex-wrap items-end gap-2">
            <button type="submit" class="primary" :disabled="busy || !source">{{ progress !== null && !busy ? '继续上传' : '开始上传' }}</button>
            <button v-if="uploadAbort" type="button" class="button" @click="uploadAbort?.abort()">暂停</button>
          </div>
          <p v-if="progress !== null" class="md:col-span-3" role="status">视频上传 {{ progress }}%{{ progress === 100 && busy ? '，正在检查视频' : '' }}</p>
        </form>
      </section>
      <section v-if="assistantOpen" class="panel" aria-label="巡检助手">
        <h2 class="font-semibold">巡检助手</h2>
        <p class="mt-2 text-sm" role="status">{{ assistantReply }}</p>
        <div class="mt-3 flex flex-wrap gap-2">
          <button v-for="question in ['怎么上传字幕', '查看待复核记录', '生成工单']" :key="question" class="button" @click="ask(question)">{{ question }}</button>
        </div>
        <form class="mt-3 flex items-end gap-2" @submit.prevent="ask()">
          <label class="flex-1 text-sm">输入问题或操作<input v-model="prompt" class="field" maxlength="250" placeholder="例如 跳到 02:15" /></label>
          <button class="primary">发送</button>
        </form>
      </section>
      <section class="panel">
        <label class="block text-sm font-medium md:max-w-md">巡检任务
          <select v-model="taskId" class="field" :disabled="busy || !tasks.length">
            <option value="" disabled>{{ loading ? '正在加载' : '请选择任务' }}</option>
            <option v-for="item in tasks" :key="item.id" :value="item.id">{{ item.name }} · {{ item.building }} {{ item.facade }}</option>
          </select>
        </label>
        <p v-if="!tasks.length && !loading" class="mt-3 text-sm text-slate-600">还没有巡检任务。上传一段外墙视频即可开始。</p>
      </section>
      <template v-if="current">
        <div class="grid items-start gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)]">
          <section class="panel space-y-3">
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div><h2 class="font-semibold">{{ current.task.name }}</h2><p class="text-sm text-slate-600">{{ current.task.building }} · {{ current.task.facade }}</p></div>
              <span v-if="run" class="text-sm font-medium text-teal-900">{{ runStates[run.state] }}</span>
            </div>
            <video :key="current.task.id" ref="video" :src="current.task.video_url" controls playsinline preload="metadata"
              class="aspect-video w-full rounded-md bg-slate-950 object-contain"
              @timeupdate="videoTime = video?.currentTime || 0" @seeked="videoTime = video?.currentTime || 0" @error="videoError = true" />
            <p v-if="videoError" class="text-sm text-red-800">浏览器无法播放这个文件。请尝试使用 MP4 格式的视频。</p>
            <div v-if="manager" class="space-y-3">
              <div v-if="run" class="text-sm text-slate-700">
                <p>{{ time(run.coverage) }} 已分析<span v-if="current.task.duration"> / {{ time(current.task.duration) }} 视频</span> · {{ run.frame_count }} 帧</p>
                <progress v-if="covered !== null" :value="covered" max="100" aria-label="已分析时长" class="mt-1 w-full" />
                <p v-if="run.error" class="mt-1 text-red-800">{{ run.error }}</p>
              </div>
              <div v-if="analyzing && run">
                <button class="button" :disabled="busy" @click="act(async () => { await wallWorkflow.cancel(taskId, run!.id); await refresh() }, '已停止分析。')">停止分析</button>
              </div>
              <details v-else class="rounded-md border border-slate-200 px-3 py-2.5">
                <summary class="cursor-pointer font-medium">检测设置</summary>
                <div class="mt-3 grid gap-3 text-sm sm:grid-cols-2">
                  <label>检测模型<select v-model="model" class="field"><option value="" disabled>请选择模型</option><option v-for="option in models" :key="option.id" :value="option.id">{{ option.name }}</option></select></label>
                  <label>检测范围<select v-model="mode" class="field"><option value="sample">快速分析</option><option value="all">逐帧分析</option></select></label>
                  <label>检测灵敏度 {{ Math.round(sensitivity * 100) }}%
                    <input v-model.number="sensitivity" type="range" min="0.05" max="0.95" step="0.01" class="mt-2 block w-full accent-teal-700" />
                    <span class="block text-slate-600">调高会标出更多疑似位置。</span>
                  </label>
                  <label>重叠框合并阈值<input v-model.number="iou" type="number" step="0.05" min="0.05" max="0.95" class="field" /></label>
                  <label v-if="canUploadModel" class="sm:col-span-2">添加模型（640×640 单类别 YOLO ONNX）<input type="file" accept=".onnx" class="field" :disabled="busy" @change="uploadModel" /></label>
                </div>
              </details>
              <button v-if="!analyzing" class="primary" :disabled="busy || !model"
                @click="act(async () => { await wallWorkflow.run(taskId, model, sensitivity, mode, iou); await refresh() }, '分析已开始，可继续查看视频。')">开始检测</button>
              <p v-if="!model" class="text-sm text-slate-600">{{ canUploadModel ? "开始检测前，请在检测设置中添加模型。" : "开始检测前，请联系管理员添加模型。" }}</p>
            </div>
          </section>
          <section class="panel">
            <h2 class="flex items-center gap-2 font-semibold"><MapPin :size="18" /> 飞行数据</h2>
            <div v-if="routePoints.length" class="mt-3 overflow-hidden rounded-md border border-slate-200">
              <WallLocationMap :points="routePoints" :current="currentPoint" compact />
            </div>
            <dl v-if="currentPoint" class="mt-3 grid grid-cols-2 gap-2 text-sm">
              <div class="col-span-2"><dt class="text-slate-600">拍摄位置 · 经纬度</dt><dd class="font-mono">{{ currentPoint.longitude.toFixed(6) }}, {{ currentPoint.latitude.toFixed(6) }}</dd></div>
              <div><dt class="text-slate-600">相对起飞点高度</dt><dd>{{ telemetry?.altitudeAvailable && Number.isFinite(telemetry.relAlt) ? telemetry.relAlt.toFixed(1) + ' 米' : '—' }}</dd></div>
              <div><dt class="text-slate-600">飞行速度</dt><dd>{{ telemetry?.speed !== undefined && Number.isFinite(telemetry.speed) ? telemetry.speed.toFixed(1) + ' 米/秒' : '—' }}</dd></div>
              <div><dt class="text-slate-600">视频时间</dt><dd>{{ time(videoTime) }}</dd></div>
            </dl>
            <p v-else class="mt-3 text-sm text-slate-600">{{ telemetryError ? '字幕暂时无法读取。' : !current.task.subtitle_url ? '暂无字幕数据。' : '当前画面没有可用的定位数据。' }}</p>
            <div v-if="manager" class="mt-4 space-y-3 text-sm">
              <label>{{ current.task.subtitle_url ? '更换字幕' : '添加字幕' }}<input type="file" accept=".srt" class="field" :disabled="busy" @change="uploadSubtitle" /></label>
              <form v-if="current.task.subtitle_url" class="flex flex-wrap items-end gap-2" @submit.prevent="saveOffset(subtitleOffset)">
                <label>字幕延后秒数<input v-model.number="subtitleOffset" type="number" step="0.1" class="field" /></label>
                <button class="button" :disabled="busy">保存</button>
                <button type="button" class="button" :disabled="busy" @click="saveOffset(0)">恢复</button>
              </form>
            </div>
          </section>
        </div>
        <section class="panel">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="flex gap-2">
              <button class="button" :aria-pressed="tab === 'findings'" @click="tab = 'findings'">巡检发现</button>
              <button class="button" :aria-pressed="tab === 'orders'" @click="tab = 'orders'">维修工单</button>
            </div>
            <div v-if="manager" class="flex flex-wrap gap-2">
              <a class="button" :href="webPath('/api/v1/wall/workflow/tasks/' + taskId + '/export')"><FileDown :size="16" /> 导出明细</a>
              <a class="button" :href="webPath('/api/v1/wall/workflow/tasks/' + taskId + '/report')"><FileDown :size="16" /> 导出报告</a>
            </div>
          </div>
          <div v-if="current.counts" class="mt-4 grid grid-cols-2 gap-2 md:grid-cols-4">
            <button v-for="card in cards" :key="card.key" class="rounded-md border border-slate-200 p-3 text-left hover:bg-teal-50"
              :aria-pressed="tab === 'findings' && filter === card.key" @click="changeFilter(card.key)">
              <span class="text-sm text-slate-700">{{ card.label }}</span>
              <span class="mt-1 block text-xl font-semibold tabular-nums">{{ current.counts[card.key] }} <span class="text-sm font-normal">处</span></span>
            </button>
          </div>
          <template v-if="tab === 'findings'">
            <div class="mt-4 flex flex-wrap items-end gap-2">
              <label class="text-sm">筛选<select v-model="filter" class="field">
                <option value="all">全部发现</option><option v-for="card in cards" :key="card.key" :value="card.key">{{ card.label }}</option><option value="dismissed">已排除</option>
              </select></label>
              <button v-if="manager" class="primary" :disabled="busy || !mayDraft" @click="draftPreview = true">生成工单</button>
              <button v-if="manager && currentFinding && selected.some(id => id !== currentFinding?.id)" class="button" :disabled="busy" @click="mergeFindings">合并到当前记录</button>
            </div>
            <div v-if="draftPreview" class="mt-3 rounded-md border border-teal-200 bg-teal-50 p-3">
              <p class="text-sm">{{ current.task.building }} {{ current.task.facade }} · 已选 {{ selected.length }} 处确认缺陷</p>
              <div class="mt-2 flex gap-2"><button class="primary" :disabled="busy || !mayDraft" @click="draft">确认生成草稿</button><button class="button" @click="draftPreview = false">返回</button></div>
            </div>
            <div class="mt-3 grid gap-4 xl:grid-cols-2">
              <ul class="divide-y divide-slate-200">
                <li v-for="finding in visibleFindings" :key="finding.id" class="flex items-center gap-3 py-2">
                  <input v-if="manager && ['pending','confirmed'].includes(finding.state)" v-model="selected" type="checkbox" :value="finding.id"
                    :aria-label="'选择 ' + time(finding.evidence_time) + ' 的发现'" class="size-4 shrink-0 accent-teal-700" />
                  <button class="flex min-w-0 flex-1 items-center gap-3 rounded-md p-1 text-left hover:bg-slate-50" @click="openFinding(finding)">
                    <img v-if="finding.image_url" :src="finding.image_url" alt="" loading="lazy" class="h-12 w-16 rounded bg-slate-100 object-cover" />
                    <span class="min-w-0 flex-1"><span class="block text-sm font-medium">{{ time(finding.evidence_time) }} · {{ finding.floor || '楼层待核实' }}</span><span class="block text-sm text-slate-600">{{ labels[finding.state] }}</span></span>
                    <span class="text-sm text-teal-800">查看</span>
                  </button>
                </li>
                <li v-if="!visibleFindings.length" class="py-4 text-sm text-slate-600">{{ !run && !current.findings.length ? '还未检测。' : run?.state === 'completed' && !current.findings.length ? '本次已检测画面未发现疑似脱落。' : '暂无符合条件的记录。' }}</li>
              </ul>
              <div v-if="currentFinding" class="rounded-md border border-slate-200 p-3">
                <img v-if="currentFinding.image_url" :src="currentFinding.image_url" alt="缺陷检测截图" class="max-h-72 w-full rounded-md bg-slate-100 object-contain" />
                <p class="mt-2 text-sm text-slate-600">视频 {{ localTime(currentFinding.evidence_time) }} · {{ labels[currentFinding.state] }}</p>
                <template v-if="manager">
                  <label class="mt-3 block text-sm">楼层<input v-model.trim="floor" class="field" maxlength="60" placeholder="例如 3 层窗下" /></label>
                  <label class="mt-2 block text-sm">位置或复核说明<textarea v-model.trim="note" class="field" maxlength="1500" rows="2" /></label>
                  <div class="mt-3 flex flex-wrap gap-2">
                    <button class="primary" :disabled="busy" @click="review(currentFinding, 'confirmed')">{{ currentFinding.state === 'confirmed' ? '保存复核' : '确认缺陷' }}</button>
                    <button class="button" :disabled="busy" @click="review(currentFinding, 'dismissed')">排除</button>
                    <button v-if="currentFinding.state === 'dismissed'" class="button" :disabled="busy" @click="review(currentFinding, 'pending')">恢复待复核</button>
                  </div>
                </template>
              </div>
            </div>
          </template>
          <template v-else>
            <label v-if="current.orders.length > 1" class="mt-3 block max-w-md text-sm">选择工单
              <select class="field" :value="order?.id" @change="orderId = ($event.target as HTMLSelectElement).value">
                <option v-for="item in current.orders" :key="item.id" :value="item.id">{{ item.id.slice(0, 8) }} · {{ item.finding_ids.length }} 处缺陷</option>
              </select>
            </label>
            <WallWorkOrder v-if="order" class="mt-3" :order="order" :findings="current.findings" :manager="manager" :busy="busy"
              @update="orderAction" @photo="orderPhoto" @seek="seek" />
            <p v-else class="mt-3 text-sm text-slate-600">暂无维修工单。</p>
          </template>
        </section>
      </template>
    </main>
  </div>
</template>

<style scoped>
.panel { border: 1px solid #e2e8f0; border-radius: .5rem; background: white; padding: 1rem; }
.field { display: block; width: 100%; margin-top: .25rem; min-height: 2.5rem; padding: .4rem .55rem; border: 1px solid #cbd5e1; border-radius: .375rem; }
.button,.primary { display: inline-flex; min-height: 2.5rem; align-items: center; justify-content: center; gap: .35rem; border: 1px solid #cbd5e1; border-radius: .375rem; padding: .4rem .8rem; font-size: .875rem; }
.button:hover,.button[aria-pressed="true"] { background: #f0fdfa; border-color: #5eead4; }
.primary { color: white; background: #0f766e; border-color: #0f766e; }
button:disabled { opacity: .5; }
:focus-visible { outline: 2px solid #0f766e; outline-offset: 2px; }
</style>
