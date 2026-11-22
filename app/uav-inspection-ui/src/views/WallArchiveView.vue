<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowRight, ChevronRight, ClipboardCheck, Clock3, FileDown, Film, FolderOpen, MapPin, Search, Wrench } from 'lucide-vue-next'
import { useRoute, useRouter } from 'vue-router'
import WallWorkspaceHeader from '../components/wall/WallWorkspaceHeader.vue'
import '../components/wall/wallWorkspace.css'
import { wallApi, type WallDetectionLogItem, type WallVideoItem } from '../api1/wall'
import { wallError, wallWorkflow, type Order, type Run, type Task, type TaskDetail } from '../api1/wallWorkflow'
import { webPath } from '../utils/webroot'

type ArchiveEntry = {
  key: string; id: string; name: string; location: string; date: string; video: string
  subtitle: boolean; source: 'workbench' | 'previous'; start: number
}

const route = useRoute()
const router = useRouter()
const current = ref<Task[]>([])
const previous = ref<WallVideoItem[]>([])
const loading = ref(true)
const errors = ref<string[]>([])
const query = ref('')
const source = ref<'all' | ArchiveEntry['source']>('all')
const newest = ref(true)
const detail = ref<TaskDetail>()
const logs = ref<WallDetectionLogItem[]>([])
const detailError = ref('')
const detailLoading = ref(false)
const video = ref<HTMLVideoElement>()
const preview = ref<HTMLElement>()
const mediaError = ref(false)
const evidenceId = ref('')
const initialTime = ref<number | null>(null)
const dateFormat = new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
const runLabels: Record<Run['state'], string> = {
  queued: '等待分析', running: '正在分析', completed: '分析完成', failed: '分析未完成', cancelled: '分析已停止',
}
const orderLabels: Record<Order['state'], string> = {
  draft: '草稿', assigned: '待接单', in_progress: '维修中', review: '待验收', completed: '已完成', cancelled: '已取消',
}
let selectionRequest = 0

const entries = computed<ArchiveEntry[]>(() => [
  ...current.value.map(task => ({
    key: 'task:' + task.id, id: task.id, name: task.name, location: [task.building, task.facade].filter(Boolean).join(' · '),
    date: task.created_at, video: task.video_url, subtitle: Boolean(task.subtitle_url), source: 'workbench' as const, start: 0,
  })),
  ...previous.value.map(item => ({
    key: 'previous:' + (item.id || item.url), id: item.id || '', name: item.task_name || item.name,
    location: '', date: item.created_at || '', video: item.url, subtitle: Boolean(item.subtitle_url),
    source: 'previous' as const, start: item.start_at || 0,
  })),
])
const filtered = computed(() => {
  const keyword = query.value.trim().toLocaleLowerCase()
  return entries.value.filter(item => (source.value === 'all' || item.source === source.value)
    && [item.name, item.location, formatDate(item.date)].some(field => field.toLocaleLowerCase().includes(keyword)))
    .sort((a, b) => {
      const first = dateValue(a.date)
      const second = dateValue(b.date)
      if (!first || !second) return second - first || a.name.localeCompare(b.name, 'zh-CN')
      return (newest.value ? second - first : first - second) || a.name.localeCompare(b.name, 'zh-CN')
    })
})
const selected = computed(() => entries.value.find(item => item.key === route.query.record) || filtered.value[0])
const recentRun = computed(() => detail.value?.runs[0])
const findings = computed(() => detail.value?.findings.filter(item => !['merged', 'dismissed'].includes(item.state)) || [])
const displayedEvidence = computed(() => {
  const finding = findings.value.find(item => item.id === evidenceId.value)
  if (finding) return finding.image_url
  return logs.value.find(item => item.id === evidenceId.value)?.image_url
})

function dateValue(value: string) {
  return Date.parse(value.replace(' ', 'T')) || 0
}
function formatDate(value: string) {
  const stamp = dateValue(value)
  return stamp ? dateFormat.format(stamp) : '日期未记录'
}
function timestamp(value: number) {
  return Math.floor(value / 60) + ':' + String(Math.floor(value % 60)).padStart(2, '0')
}
function entryLabel(item: ArchiveEntry) {
  return item.source === 'workbench' ? '巡检任务' : '旧版录像'
}
function seek(seconds: number, id: string) {
  evidenceId.value = id
  if (!video.value || video.value.readyState === 0) {
    initialTime.value = seconds
    return
  }
  video.value.currentTime = Math.min(seconds, video.value.duration || seconds)
}
function onMetadata() {
  if (!video.value || initialTime.value === null) return
  video.value.currentTime = Math.min(initialTime.value, video.value.duration || initialTime.value)
  initialTime.value = null
}
async function open(item: ArchiveEntry) {
  await router.replace({ query: { ...route.query, record: item.key } })
  await nextTick()
  if (window.matchMedia('(max-width: 900px)').matches) preview.value?.scrollIntoView({ block: 'start' })
}
async function load() {
  loading.value = true
  errors.value = []
  const [tasks, legacy] = await Promise.allSettled([wallWorkflow.tasks(), wallApi.getVideos()])
  if (tasks.status === 'fulfilled') current.value = tasks.value
  else errors.value.push('巡检任务暂时无法读取。')
  if (legacy.status === 'fulfilled') previous.value = legacy.value.data.videos
  else errors.value.push('旧版录像暂时无法读取。')
  loading.value = false
}
watch(selected, async item => {
  const request = ++selectionRequest
  detail.value = undefined
  logs.value = []
  detailError.value = ''
  mediaError.value = false
  evidenceId.value = ''
  initialTime.value = item?.start || null
  detailLoading.value = Boolean(item)
  if (!item) return
  try {
    if (item.source === 'workbench') {
      const result = await wallWorkflow.detail(item.id)
      if (request === selectionRequest) detail.value = result
    } else if (item.id) {
      const result = await wallApi.getTaskLogs(item.id)
      if (request === selectionRequest) logs.value = result.data.logs
    }
  } catch (error) {
    if (request === selectionRequest) detailError.value = wallError(error)
  } finally {
    if (request === selectionRequest) detailLoading.value = false
  }
}, { immediate: true })
onMounted(() => {
  // 与巡检工作台共用整页视口锁定；离开页面时摘掉，避免影响首页等其他路由
  document.body.classList.add('wall-workspace-active')
  load()
})
onBeforeUnmount(() => document.body.classList.remove('wall-workspace-active'))
</script>

<template>
  <div class="wall-shell">
    <WallWorkspaceHeader active="archive" />
    <main class="wall-main">
      <div class="wall-hero">
        <div>
          <h1>历史任务</h1>

        </div>
        <RouterLink to="/wall" class="wall-button wall-button--hero">回到工作台 <ArrowRight :size="16" /></RouterLink>
      </div>

      <div class="archive-grid">
        <section class="wall-panel archive-list" aria-label="历史任务列表">
          <header class="archive-section">
            <div class="flex items-center justify-between gap-2">
              <h2 class="wall-panel-title">任务记录</h2>
              <span class="text-sm text-slate-600" aria-live="polite">{{ loading ? '加载中' : filtered.length + ' 项' }}</span>
            </div>
            <label class="archive-search">
              <Search :size="18" /><span class="sr-only">搜索任务</span>
              <input v-model="query" type="search" placeholder="搜索任务、楼栋、立面" />
            </label>
            <div class="archive-controls">
              <label class="text-sm"><span class="sr-only">记录来源</span>
                <select v-model="source" class="wall-control">
                  <option value="all">全部来源</option>
                  <option value="workbench">巡检任务</option>
                  <option value="previous">旧版录像</option>
                </select>
              </label>
              <label class="text-sm"><span class="sr-only">日期排序</span>
                <select v-model="newest" class="wall-control"><option :value="true">最近创建</option><option :value="false">最早创建</option></select>
              </label>
            </div>
          </header>
          <div v-if="errors.length" class="archive-section text-sm text-red-800" role="alert">
            <p v-for="message in errors" :key="message">{{ message }}</p>
            <button type="button" class="mt-2 underline" @click="load">重试</button>
          </div>
          <ul v-if="filtered.length" class="archive-rows">
            <li v-for="item in filtered" :key="item.key">
              <button type="button" class="archive-row" :aria-pressed="selected?.key === item.key" @click="open(item)">
                <span class="archive-icon"><Film :size="20" /></span>
                <span class="min-w-0">
                  <strong class="block break-words">{{ item.name }}</strong>
                  <span class="mt-1 block text-xs text-slate-600">{{ item.location || entryLabel(item) }} · {{ formatDate(item.date) }}</span>
                </span>
                <ChevronRight :size="16" class="ml-auto shrink-0 text-slate-500" />
              </button>
            </li>
          </ul>
          <div v-else-if="!loading && !errors.length" class="archive-empty">
            <FolderOpen :size="30" />
            <p>{{ entries.length ? '没有符合条件的任务。' : '还没有巡检记录。' }}</p>
            <button v-if="entries.length" class="wall-button" @click="query = ''; source = 'all'">清除筛选</button>
            <RouterLink v-else to="/wall" class="wall-button wall-button--primary">打开工作台</RouterLink>
          </div>
        </section>

        <section ref="preview" class="wall-panel archive-preview" aria-label="任务详情">
          <template v-if="selected">
            <header class="archive-section">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <span class="wall-status" :data-tone="selected.source === 'workbench' ? 'blue' : undefined">{{ entryLabel(selected) }}</span>
                <span v-if="recentRun" class="wall-status" :data-tone="recentRun.state === 'completed' ? 'green' : 'amber'">{{ runLabels[recentRun.state] }}</span>
              </div>
              <h2 class="mt-2 break-words text-xl font-bold">{{ selected.name }}</h2>
              <div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-600">
                <span v-if="selected.location" class="inline-flex items-center gap-1"><MapPin :size="15" />{{ selected.location }}</span>
                <span class="inline-flex items-center gap-1"><Clock3 :size="15" />{{ formatDate(selected.date) }}</span>
                <span>{{ selected.subtitle ? '含飞行字幕' : '无飞行字幕' }}</span>
              </div>
            </header>
            <div class="archive-media">
              <video :key="selected.key" ref="video" :src="selected.video" controls playsinline preload="metadata"
                aria-label="巡检录像" @loadedmetadata="onMetadata" @error="mediaError = true" />
              <p v-if="mediaError" class="mt-2 text-sm text-red-800" role="alert">这段录像暂时无法播放，请检查视频文件。</p>
            </div>
            <div class="archive-section">
              <p v-if="detailLoading" class="text-sm text-slate-600" role="status">正在读取巡检记录…</p>
              <p v-else-if="detailError" class="text-sm text-red-800" role="alert">{{ detailError }}</p>
              <div v-if="detail?.counts" class="archive-stats">
                <div><strong>{{ detail.counts.pending }}</strong><span>待复核</span></div>
                <div><strong>{{ detail.counts.confirmed }}</strong><span>已确认</span></div>
                <div><strong>{{ detail.counts.assigned }}</strong><span>已派单</span></div>
                <div><strong>{{ detail.counts.completed }}</strong><span>已修复</span></div>
              </div>
              <div v-if="findings.length || logs.length" class="mt-4">
                <h3 class="flex items-center gap-2 font-semibold"><ClipboardCheck :size="17" /> {{ selected.source === 'previous' ? '保存的检测日志' : '巡检记录' }}</h3>
                <ul class="archive-evidence">
                  <li v-for="item in findings" :key="item.id">
                    <button :aria-pressed="evidenceId === item.id" @click="seek(item.evidence_time, item.id)">
                      <span>{{ timestamp(item.evidence_time) }} · {{ item.floor || '楼层待核实' }}</span>
                      <span>{{ item.state === 'confirmed' ? '已确认' : '待复核' }}</span>
                    </button>
                  </li>
                  <li v-for="item in logs" :key="item.id">
                    <button :aria-pressed="evidenceId === item.id" @click="seek(item.time, item.id)">
                      <span>{{ timestamp(item.time) }}</span><span>{{ item.detections.length }} 条标记</span>
                    </button>
                  </li>
                </ul>
                <img v-if="displayedEvidence" :src="displayedEvidence" alt="选中的巡检记录截图" class="mt-3 max-h-72 w-full rounded-md bg-slate-100 object-contain" />
              </div>
              <p v-else-if="!detailLoading && !detailError" class="mt-3 text-sm text-slate-600">这项任务暂无可查看的巡检记录。</p>
              <div v-if="detail?.orders.length" class="mt-4">
                <h3 class="flex items-center gap-2 font-semibold"><Wrench :size="17" /> 维修工单</h3>
                <ul class="archive-evidence">
                  <li v-for="order in detail.orders" :key="order.id">
                    <RouterLink class="archive-order"
                      :to="{ path: '/wall', query: { task: selected.id, order: order.id } }">
                      <span>工单 {{ order.id.slice(0, 8) }} · {{ order.finding_ids.length }} 处</span>
                      <span>{{ orderLabels[order.state] }}</span>
                    </RouterLink>
                  </li>
                </ul>
              </div>
              <footer class="archive-actions">
                <RouterLink v-if="selected.source === 'workbench'" :to="{ path: '/wall', query: { task: selected.id } }" class="wall-button wall-button--primary">
                  打开巡检任务 <ArrowRight :size="16" />
                </RouterLink>
                <RouterLink v-else :to="{ path: '/wall/replay/tools', query: { task: selected.id } }" class="wall-button">
                  打开旧版录像工具 <ArrowRight :size="16" />
                </RouterLink>
                <a v-if="detail?.can_manage" :href="webPath('/api/v1/wall/workflow/tasks/' + selected.id + '/report')" class="wall-button">
                  <FileDown :size="16" /> 导出报告
                </a>
              </footer>
            </div>
          </template>
          <div v-else class="archive-empty archive-empty--preview">
            <Film :size="32" /><p>选择一项任务查看录像和记录。</p>
          </div>
        </section>
      </div>
    </main>
  </div>
</template>

<style scoped>
.archive-grid { display: grid; grid-template-columns: minmax(280px, .9fr) minmax(0, 1.65fr); gap: 1rem; margin-top: 1rem; align-items: start; }
.archive-section { padding: 1rem 1.15rem; }
.archive-search { display: flex; gap: .55rem; align-items: center; margin-top: .8rem; border: 1px solid #c9d5e1; border-radius: 7px; padding-inline: .65rem; color: #526a80; }
.archive-search input { width: 100%; min-width: 0; min-height: 42px; font-size: .875rem; color: var(--wall-ink); }
.archive-search input:focus-visible { outline-offset: 0; }
.archive-controls { display: grid; grid-template-columns: 1fr 1fr; gap: .6rem; margin-top: .6rem; }
.archive-rows { max-height: min(70vh, 680px); overflow: auto; border-top: 1px solid var(--wall-line); }
.archive-rows li + li { border-top: 1px solid var(--wall-line); }
.archive-row { display: flex; align-items: center; gap: .75rem; width: 100%; min-height: 68px; border-left: 3px solid transparent; padding: .65rem 1rem; text-align: left; }
.archive-row:hover { background: #f4f8fb; }
.archive-row:focus-visible { outline-offset: -3px; }
.archive-row[aria-pressed="true"] { background: #e7f5f1; border-left-color: var(--wall-accent); }
.archive-icon { display: grid; place-items: center; flex-shrink: 0; width: 38px; height: 38px; border-radius: 8px; color: #34546c; background: #e8eff6; }
.archive-preview { min-width: 0; scroll-margin-top: 1rem; }
.archive-media { padding-inline: 1.15rem; }
.archive-media video { display: block; width: 100%; aspect-ratio: 16/9; max-height: 470px; object-fit: contain; border-radius: 8px; background: #111f30; }
.archive-empty { display: grid; justify-items: center; gap: .8rem; padding: 2rem 1rem; color: var(--wall-muted); font-size: .875rem; text-align: center; }
.archive-empty--preview { padding: 4rem 1rem; }
.archive-stats { display: grid; grid-template-columns: repeat(4, 1fr); overflow: hidden; border-radius: 8px; background: #eef4f8; }
.archive-stats div { padding: .65rem .85rem; }
.archive-stats div + div { border-left: 1px solid #dce7ef; }
.archive-stats strong { display: block; font-size: 1.15rem; font-variant-numeric: tabular-nums; }
.archive-stats span { color: var(--wall-muted); font-size: .75rem; }
.archive-evidence { max-height: 240px; overflow: auto; margin-top: .5rem; border: 1px solid var(--wall-line); border-radius: 7px; }
.archive-evidence li + li { border-top: 1px solid var(--wall-line); }
.archive-evidence button, .archive-order { display: flex; justify-content: space-between; gap: 1rem; width: 100%; padding: .65rem .75rem; text-align: left; font-size: .875rem; }
.archive-evidence button:hover, .archive-order:hover, .archive-evidence button[aria-pressed="true"] { background: #e7f5f1; }
.archive-actions { display: flex; flex-wrap: wrap; gap: .5rem; margin-top: 1rem; }
@media (max-width: 900px) { .archive-grid { grid-template-columns: minmax(0, 1fr); } .archive-rows { max-height: 310px; } }
@media (max-width: 440px) { .archive-stats div { padding-inline: .45rem; } }
</style>
