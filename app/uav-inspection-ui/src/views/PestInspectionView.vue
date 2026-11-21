<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft, Play, Pause, RotateCcw, Route, FileDown, ScanEye, Navigation, Battery, Mountain, Gauge, Camera, Send, Box, X, Clock, MoveUpRight, Maximize2, Settings2, Activity, ChevronRight, ChevronUp, Check, CirclePlay, LayoutGrid, Signal, MapPin, Radio } from 'lucide-vue-next'
import InspectionHeader from '../components/common/InspectionHeader.vue'
import PestSimulationScene from '../components/pest/PestSimulationScene.vue'
import MissionReplayStage from '../components/pest/MissionReplayStage.vue'
import { observationTargets, observationCoverage, simulationRoutes, routeLength, simulationBattery, simulationCommand, readReports, simulationReportHtml, type Position3, type SimulationReport, type ViewStrategy } from '../utils/pestSimulation'
import { advanceMission, createMission, isMissionRunning, missionPose, missionProgress, optimizeMission, pauseMission, restoreMission, returnMission, startMission, REQUIRED_VIEWS, type MissionServices } from '../utils/pestMission'

const router = useRouter(), sceneRef = ref<InstanceType<typeof PestSimulationScene> | null>(null), viewport = ref<HTMLElement | null>(null)
const ready = ref(false), sceneError = ref(''), cameraMode = ref('overview'), targetIndex = ref(0)
const speed = ref(4), timeScale = ref(1), strategy = ref<ViewStrategy>('semantic'), mission = ref(createMission())
const modal = ref<'' | 'routes' | 'models' | 'reports' | 'reset' | 'viewpoints' | 'plants'>(''), draftRoute = ref(mission.value.routeId), command = ref('')
const notice = ref('一号试验田已就绪，区域巡查完成后将自动规划重点复核视点。')
const messages = ref<{role: 'user' | 'assistant'; text: string}[]>([{role:'assistant',text:'我会按任务顺序完成区域巡查、视点规划和植株复核。无人机到达观察位置并悬停采样后，记录才会更新。您也可以调整复核顺序或重新规划当前视点。'}])
const REPORT_KEY = 'uav:pest-simulation:reports:maize:v2', MISSION_KEY = 'uav:pest-simulation:mission:maize:v3'
const reports = ref<SimulationReport[]>([])
const routeId = computed(() => mission.value.routeId), route = computed(() => simulationRoutes.find(r => r.id === routeId.value)!)
const stage = computed(() => mission.value.status), running = computed(() => isMissionRunning(mission.value)), points = computed(() => mission.value.leg)
const pose = computed(() => missionPose(mission.value)), elapsed = computed(() => mission.value.elapsed), totalDistance = computed(() => mission.value.distance)
const progress = computed(() => missionProgress(mission.value)), battery = computed(() => simulationBattery(elapsed.value)), samples = computed(() => mission.value.samples)
const observations = computed(() => mission.value.observations), viewpoints = computed(() => mission.value.plans.filter(p => p.state === 'captured'))
const lastView = computed(() => viewpoints.value.at(-1)), pendingView = computed(() => mission.value.pending)
const activeTarget = computed(() => mission.value.activeTarget), historyPath = computed<Position3[]>(() => samples.value.map(s => [s.x, s.altitude, s.z]))
const draftTarget = ref(0), draftStrategy = ref<ViewStrategy>('semantic')
function openOptimization() { draftTarget.value=activeTarget.value ?? targetIndex.value; draftStrategy.value=strategy.value; modal.value='viewpoints' }
function applyOptimization() { targetIndex.value=draftTarget.value; strategy.value=draftStrategy.value; optimize() }
const statusLabels = { idle: '待命', running: '巡航中', paused: '已暂停', returning: '返航中', completed: '已完成' }
const status = computed(() => stage.value === 'completed' && mission.value.aborted ? '已返航' : running.value && mission.value.phase === 'observe' ? '悬停采样' : running.value && mission.value.phase === 'transit' ? '飞往视点' : statusLabels[stage.value])
const statusCode = computed(() => stage.value === 'completed' ? 'DONE' : stage.value === 'paused' ? 'PAUSED' : stage.value === 'returning' ? 'RETURNING' : running.value ? 'RUNNING' : 'STANDBY')
const observedPlants = computed(() => mission.value.plants.filter(p => p === 'reviewed').length)
const remaining = computed(() => (routeLength(points.value) - mission.value.legDistance) / speed.value + (mission.value.phase === 'observe' ? mission.value.captureRemaining : 0))
const strategyName = computed(() => ({fixed:'标准观察',coverage:'覆盖优先',semantic:'重点区域优先'})[pendingView.value?.strategy ?? lastView.value?.strategy ?? strategy.value])
const logs = computed(() => mission.value.events.map(e => ({time:time(e.second),message:e.message,level:/遮挡|失败|未能|中止|超时|偏弱/.test(e.message)?'WARNING':'INFO'})))
const currentStep = computed(() => stage.value === 'completed' ? mission.value.aborted ? '中途返航 · 未完成项目保留待复核' : '巡检任务已结束 · 观察记录已归档' : !mission.value.surveyed ? '完成区域覆盖后规划观察航点' : mission.value.phase === 'return' ? mission.value.aborted ? '任务中途结束 · 安全返航' : '复核完成 · 返回起降点' : activeTarget.value !== null ? `${observationTargets[activeTarget.value]!.name} · ${Math.min(REQUIRED_VIEWS, observationCoverage(observations.value, activeTarget.value))}/${REQUIRED_VIEWS} 有效视角` : '规划下一株复核')
const operationMessage = computed(() => (stage.value === 'paused' ? '已暂停 · ' : '') + (mission.value.phase === 'observe' ? `悬停采样 · ${mission.value.captureRemaining.toFixed(1)} s` : mission.value.phase === 'transit' ? '飞往观察视点' : '等待观察任务'))
const canOptimize = computed(() => ready.value && mission.value.phase !== 'return' && stage.value !== 'completed' && !sceneError.value)
const isFullscreen = ref(false)
const viewMode = ref<'live' | 'replay'>('live')
const moduleDock = ref(false)
const clock = ref(new Date())
const clockTimer = window.setInterval(() => { clock.value = new Date() }, 1000)
const clockText = computed(() => clock.value.toTimeString().slice(0, 8))
const pitch = computed(() => Math.round(mission.value.pending?.pitch ?? -45))
const yaw = computed(() => { const h = pose.value.heading; return Math.round(((h + 180) % 360 + 360) % 360 - 180) })
// 病害分布：按植株状态归类，中心数字 = 待复核株数（真实来源 mission.plants）
const distribution = computed(() => {
  const list = mission.value.plants, n = (set: string[]) => list.filter(p => set.includes(p)).length
  const reviewed = n(['reviewed']), flagged = n(['queued', 'inspecting', 'needs-review']), surveyed = n(['surveyed']), pending = list.length - reviewed - flagged - n(['surveyed'])
  const total = Math.max(1, list.length)
  return { reviewed, flagged, surveyed, pending, total: list.length, rate: (flagged / total) * 100 }
})
const donut = computed(() => {
  const { reviewed, flagged, surveyed, total } = distribution.value
  const a = (reviewed / total) * 360, b = a + (flagged / total) * 360, c = b + (surveyed / total) * 360
  return `conic-gradient(#2563eb 0 ${a}deg, #ef4444 ${a}deg ${b}deg, #f59e0b ${b}deg ${c}deg, #e2e8f0 ${c}deg 360deg)`
})
const totalSeconds = computed(() => elapsed.value + Math.max(0, remaining.value))
const mini = computed(() => { const p = historyPath.value; if (!p.length) return ''; return p.map(v => `${(((v[0] + 30) / 60) * 96).toFixed(1)},${(((36 - v[2]) / 62) * 72).toFixed(1)}`).join(' ') })
const modules = [
  { name: '平台首页', path: '/' }, { name: '通信基站巡检', path: '/telecom' }, { name: '杆路线路巡检', path: '/power' },
  { name: '建筑屋顶巡检', path: '/roof' }, { name: '建筑外墙巡检', path: '/wall' }, { name: '病虫害巡检', path: '/pest' },
  { name: '乔木修剪检测', path: '/pruning' }, { name: '乔木高度测量', path: '/height' }, { name: '绿化面积测量', path: '/area' },
  { name: '数字玫瑰园', path: '/rose-digital' }, { name: '玫瑰花产量预测', path: '/rose-yield' }, { name: '热力客流监测', path: '/heatmap-flow' },
  { name: '粉黛花三维漫游', path: '/fendai-flower' }, { name: '车辆车牌巡检', path: '/plate' }, { name: '素材上传中心', path: '/assets' },
]
function enterReplay() { if (running.value) pause(); viewMode.value = 'replay' }
function fullscreenChanged() { isFullscreen.value = document.fullscreenElement === viewport.value }
document.addEventListener('fullscreenchange', fullscreenChanged)
function checkpoint() { try { localStorage.setItem(MISSION_KEY, JSON.stringify({mission:mission.value,speed:speed.value,timeScale:timeScale.value,strategy:strategy.value})) } catch { notice.value='当前浏览器无法保存记录，仍可执行任务并导出报告。' } }
try {
  reports.value = readReports(localStorage.getItem(REPORT_KEY))
  const saved = JSON.parse(localStorage.getItem(MISSION_KEY) || 'null'), restored = restoreMission(saved?.mission)
  if (restored) {
    mission.value=restored; speed.value=[2,4,8].includes(saved.speed)?saved.speed:4; timeScale.value=[1,2,4].includes(saved.timeScale)?saved.timeScale:1
    strategy.value=['fixed','coverage','semantic'].includes(saved.strategy)?saved.strategy:'semantic'
    if (restored.activeTarget !== null) targetIndex.value=restored.activeTarget
    notice.value=restored.status==='paused'?'已恢复任务及当前观察航段，点击“继续巡检”接着执行。':'已恢复上次任务记录。'
  }
} catch { /* Invalid old checkpoints do not affect a new mission or saved reports. */ }
const services: MissionServices = {
  plan:(target,origin,mode,history,avoided)=>sceneRef.value?.planView(target,origin,mode,history,avoided) ?? null,
  observe:(target,position)=>sceneRef.value?.observePlant(target,position) ?? 0,
}
function notify(message:string) { notice.value=message; checkpoint() }
function syncNotice() { notice.value=mission.value.events[0]?.message || notice.value; checkpoint() }
function plantState(index:number) { if (routeId.value === 'maize-orbit' && index !== 0 && !mission.value.reviewTargets.includes(index)) return '未纳入任务'; return ({pending:'待巡查',surveyed:'已巡查',queued:'待复核',inspecting:'复核中',reviewed:'复核完成','needs-review':'待复核'})[mission.value.plants[index]!] }
function openRoutes() { draftRoute.value=routeId.value; modal.value='routes' }
function resetMission() { mission.value=createMission(routeId.value); modal.value=''; cameraMode.value='overview'; viewMode.value='live'; sceneRef.value?.resetView(); notify('任务已重置，无人机回到起降点。') }
function start() {
  if (!ready.value || sceneError.value) return notify('请等待三维场景加载完成。')
  if (stage.value==='completed') resetMission()
  startMission(mission.value); syncNotice()
}
function pause() { pauseMission(mission.value); syncNotice() }
function returnHome() { returnMission(mission.value); syncNotice(); modal.value='' }
function advance(seconds:number) {
  if (!running.value) return
  const previousSecond=Math.floor(elapsed.value), previousEvent=mission.value.events[0]
  advanceMission(mission.value,Math.max(0,Math.min(.1,seconds))*timeScale.value,speed.value,strategy.value,services)
  if (previousEvent!==mission.value.events[0]) { notice.value=mission.value.events[0]?.message || notice.value; if(activeTarget.value!==null)targetIndex.value=activeTarget.value }
  if (previousEvent!==mission.value.events[0] || previousSecond!==Math.floor(elapsed.value)) checkpoint()
  if(activeTarget.value===null && cameraMode.value==='observation')cameraMode.value='overview'
}
function optimize() {
  if (!ready.value) return
  const message=optimizeMission(mission.value,targetIndex.value,strategy.value,services)
  if (modal.value==='viewpoints')modal.value=''
  notify(message)
}
function configureRoute() { if(stage.value!=='idle' && stage.value!=='completed')return notify('请先重置当前任务，再更换方案。'); mission.value=createMission(draftRoute.value); modal.value=''; cameraMode.value='overview'; sceneRef.value?.resetView(); notify(`已选择 ${route.value.name}。`) }
function saveReport() {
  if (!samples.value.length)return notify('执行巡检后即可保存任务报告。')
  const report:SimulationReport={id:mission.value.id,createdAt:new Date().toLocaleString('zh-CN'),routeName:route.value.name,status:stage.value,elapsed:elapsed.value,distance:totalDistance.value,samples:JSON.parse(JSON.stringify(samples.value)),observations:JSON.parse(JSON.stringify(observations.value)),viewpoints:JSON.parse(JSON.stringify(viewpoints.value)),plans:JSON.parse(JSON.stringify(mission.value.plans)),plants:[...mission.value.plants],outcome:mission.value.aborted?'interrupted':stage.value==='completed'?'completed':'in-progress',progress:progress.value}
  reports.value=[report,...reports.value.filter(r=>r.id!==report.id)].slice(0,5)
  try{localStorage.setItem(REPORT_KEY,JSON.stringify(reports.value));notify('巡检报告已保存。')}catch{notify('浏览器存储空间不足，仍可导出当前报告。')}
  modal.value='reports'
}
function download(report:SimulationReport,format:'html'|'json') { const blob=new Blob([format==='html'?simulationReportHtml(report):JSON.stringify({source:'simulation',disease_detection:null,...report},null,2)],{type:format==='html'?'text/html;charset=utf-8':'application/json;charset=utf-8'}); const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=`病虫害巡检报告_${report.id}.${format}`;link.click();window.setTimeout(()=>URL.revokeObjectURL(url),1000);notify(`${format.toUpperCase()} 报告已导出。`) }
function sendCommand(text=command.value) {
  const value=text.trim();if(!value)return;command.value='';messages.value.push({role:'user',text:value})
  const action=simulationCommand(value)
  if(action==='start')start();else if(action==='pause')pause();else if(action==='resume')stage.value==='paused'?start():notify('当前没有暂停的任务。');else if(action==='return')returnHome();else if(action==='optimize')optimize();else if(action==='status')notify(`当前${status.value}，任务完成度 ${progress.value.toFixed(1)}%，${currentStep.value}。`);else notify('可以发送：开始巡检、暂停、继续、返航、优化视点或任务状态。')
  messages.value.push({role:'assistant',text:notice.value});messages.value=messages.value.slice(-20)
}
async function fullscreen() { if(!viewport.value)return;try{if(document.fullscreenElement)await document.exitFullscreen();else await viewport.value.requestFullscreen()}catch{notify('浏览器未允许全屏，可在当前窗口操作。')} }
function onSceneError(message:string){sceneError.value=message;pause();notify(message)}
function suspend(){if(running.value)pause()}
function time(value:number){return `${String(Math.floor(value/60)).padStart(2,'0')}:${String(Math.floor(value%60)).padStart(2,'0')}`}
window.addEventListener('beforeunload',checkpoint)
onBeforeUnmount(()=>{pauseMission(mission.value);checkpoint();window.removeEventListener('beforeunload',checkpoint);document.removeEventListener('fullscreenchange',fullscreenChanged);window.clearInterval(clockTimer)})
</script>

<template>
  <div class="pest-workbench">
    <InspectionHeader title="病虫害低空智能巡检" :task-name="route.name" :online="!sceneError">
      <template #actions>
        <span class="demo-tag"><Box :size="13" />演示任务</span>
        <button class="button secondary" @click="router.push('/')"><ArrowLeft :size="14" />首页</button>
        <button class="button secondary" :disabled="!samples.length" @click="saveReport"><FileDown :size="14" />生成报告</button>
        <button class="button primary" :disabled="!ready || Boolean(sceneError)" @click="running ? pause() : start()"><Pause v-if="running" :size="14" /><Play v-else :size="14" />{{ running ? '暂停巡检' : stage === 'paused' ? '继续巡检' : stage === 'completed' ? '重新巡检' : '开始巡检' }}</button>
        <span class="clock-chip"><Clock :size="13" />{{ clockText }}</span>
      </template>
    </InspectionHeader>

    <main class="workbench-grid">
      <!-- 左栏：遥测 → 病害分布 → 左下角功能坞 -->
      <aside class="rail rail-left">
        <section class="card telemetry-card">
          <div class="card-title">
            <h2><Signal :size="15" />实时遥测链路</h2>
            <span class="link-badge">NAV · LINK V2.0</span>
          </div>
          <div class="metric-grid">
            <div class="metric"><span><Battery :size="12" />动力电量</span><strong data-testid="sim-battery">{{ battery.toFixed(0) }}<small>%</small></strong></div>
            <div class="metric"><span><MapPin :size="12" />采样航点</span><strong>{{ pose.waypoint + 1 }}<small>/{{ points.length }}</small></strong></div>
            <div class="metric"><span><Mountain :size="12" />相对高度</span><strong data-testid="sim-altitude">{{ pose.position[1].toFixed(1) }}<small>m</small></strong></div>
            <div class="metric"><span><Gauge :size="12" />飞行速度</span><strong>{{ running && mission.phase !== 'observe' ? speed.toFixed(1) : '0.0' }}<small>m/s</small></strong></div>
          </div>
          <div class="telemetry-foot">
            <span class="state-badge" :class="{ live: running }"><i></i>{{ status }}</span>
            <span class="coord" data-testid="sim-position">X {{ pose.position[0].toFixed(1) }} · Z {{ pose.position[2].toFixed(1) }}</span>
          </div>
        </section>

        <section class="card distribution-card">
          <div class="card-title"><h2><Activity :size="15" />病害分布占比</h2><span class="section-kicker">AI</span></div>
          <div class="donut-row">
            <div class="donut" :style="{ background: donut }"><div class="donut-hole"><strong>{{ distribution.flagged }}</strong><span>病害占比</span></div></div>
            <ul class="donut-legend">
              <li><i class="c-blue"></i>已复核<b>{{ distribution.reviewed }}</b></li>
              <li><i class="c-red"></i>待复核<b>{{ distribution.flagged }}</b></li>
              <li><i class="c-amber"></i>已巡查<b>{{ distribution.surveyed }}</b></li>
              <li><i class="c-slate"></i>未巡查<b>{{ distribution.pending }}</b></li>
            </ul>
          </div>
          <div class="distribution-foot"><span>{{ distribution.total }} 株样株 · 复核率 {{ distribution.total ? Math.round((distribution.reviewed / distribution.total) * 100) : 0 }}%</span><button @click="modal = 'plants'">查看植株<ChevronRight :size="11" /></button></div>
        </section>

        <section class="card function-dock">
          <div class="card-title"><h2><LayoutGrid :size="15" />功能</h2><span class="section-kicker">切换</span></div>
          <div class="dock-list">
            <button @click="openRoutes"><Route :size="16" /><span>航线规划</span><ChevronRight :size="12" /></button>
            <button :disabled="!canOptimize" @click="openOptimization"><ScanEye :size="16" /><span>视点优化</span><ChevronRight :size="12" /></button>
            <button @click="modal = 'reports'"><FileDown :size="16" /><span>巡检报告</span><em>{{ reports.length }}</em><ChevronRight :size="12" /></button>
            <button @click="modal = 'models'"><Settings2 :size="16" /><span>运行配置</span><ChevronRight :size="12" /></button>
          </div>
          <div class="dock-modules">
            <button class="module-toggle" :aria-expanded="moduleDock" @click="moduleDock = !moduleDock"><LayoutGrid :size="14" /><span>模块切换</span><ChevronUp :size="13" :class="{ flip: !moduleDock }" /></button>
            <div v-if="moduleDock" class="module-list">
              <button v-for="item in modules" :key="item.path" :class="{ current: item.path === '/pest' }" @click="router.push(item.path)">{{ item.name }}<Check v-if="item.path === '/pest'" :size="12" /></button>
            </div>
          </div>
        </section>
      </aside>

      <!-- 中栏：主视图 + 状态条 + 系统日志 -->
      <section class="stage-column">
        <div class="stage">
          <div class="stage-head">
            <div class="stage-title">
              <span class="live-dot" :class="{ on: running }"></span>
              <strong>{{ viewMode === 'live' ? '病虫害三维实时检测' : '过程回放' }}</strong>
              <span class="stage-sub">{{ viewMode === 'live' ? `作业区域 A-01 · ${route.name}` : '历史航迹与观察记录' }}</span>
            </div>
            <div class="stage-actions">
              <button v-if="viewMode === 'live'" class="replay-entry" @click="enterReplay"><CirclePlay :size="14" />过程回放</button>
              <button v-else class="replay-entry back" @click="viewMode = 'live'"><Radio :size="14" />返回实时视图</button>
              <button class="icon-btn" :aria-pressed="isFullscreen" @click="fullscreen"><Maximize2 :size="14" /></button>
            </div>
          </div>

          <div ref="viewport" class="stage-body">
            <template v-if="viewMode === 'live'">
              <PestSimulationScene ref="sceneRef" :points="points" :position="pose.position" :heading="pose.heading" :running="running" :camera-mode="cameraMode" :target-index="targetIndex" :active-target="activeTarget" :planned-view="pendingView" :history-path="historyPath" @advance="advance" @ready="ready = true" @error="onSceneError" @suspend="suspend" />
              <div class="hud-params"><span>PITCH <b>{{ pitch }}°</b></span><span>YAW <b>{{ yaw }}°</b></span></div>
              <div class="mini-map" aria-hidden="true">
                <span>实时航迹预览</span>
                <svg viewBox="0 0 96 72"><polyline v-if="mini" :points="mini" fill="none" stroke="#36d5bc" stroke-width="1.4" stroke-linecap="round" /><text v-else x="48" y="38" text-anchor="middle" fill="#475569" font-size="8">待起飞</text></svg>
              </div>
              <div class="camera-toolbar" aria-label="视角切换">
                <button v-for="mode in [{ id: 'overview', label: '全景' }, { id: 'follow', label: '跟随' }, { id: 'top', label: '俯视' }, { id: 'observation', label: '机载' }]" :key="mode.id" :aria-pressed="cameraMode === mode.id" :disabled="mode.id === 'observation' && activeTarget === null" @click="cameraMode = mode.id"><Camera :size="13" />{{ mode.label }}</button>
                <i></i>
                <button aria-label="重置观察视角" @click="cameraMode = 'overview'; sceneRef?.resetView()"><RotateCcw :size="14" /></button>
              </div>
              <div v-if="activeTarget !== null" class="viewpoint-hud"><ScanEye :size="14" /><div><strong>{{ observationTargets[activeTarget]!.name }}</strong><span>{{ operationMessage }} · {{ strategyName }}</span></div><button :disabled="!canOptimize" @click="targetIndex = activeTarget; optimize()">重新优化</button></div>
              <div v-if="!ready && !sceneError" class="stage-mask"><span class="spinner"></span>三维场景加载中…</div>
              <div v-if="sceneError" class="stage-mask error">{{ sceneError }}</div>
            </template>
            <MissionReplayStage v-else :samples="samples" :route-points="points" :observations="observations" :viewpoints="viewpoints" :targets="observationTargets" :plants="mission.plants" :total-seconds="totalSeconds" />
          </div>

          <div v-if="viewMode === 'live'" class="stage-foot">
            <button class="play-btn" :aria-label="running ? '暂停' : '开始'" :disabled="!ready || Boolean(sceneError)" @click="running ? pause() : start()"><Pause v-if="running" :size="13" /><Play v-else :size="13" /></button>
            <button class="play-btn ghost" aria-label="重置任务" @click="modal = 'reset'"><RotateCcw :size="13" /></button>
            <span class="foot-time">{{ time(elapsed) }}</span>
            <div class="foot-track" :title="`任务完成度 ${progress.toFixed(1)}%`"><i :style="{ width: `${progress}%` }"></i></div>
            <span class="foot-time end">{{ time(totalSeconds) }}</span>
          </div>
        </div>

        <div class="status-strip">
          <button class="strip-opt" :disabled="!canOptimize" @click="openOptimization"><ScanEye :size="13" />视点优化</button>
          <span class="strip-sep"></span>
          <span class="strip-route">{{ route.name }}</span>
          <span class="strip-metric">航点 <b>{{ pose.waypoint + 1 }} / {{ points.length }}</b></span>
          <span class="strip-notice" :title="notice">{{ notice }}</span>
          <strong class="strip-progress" data-testid="sim-progress">{{ progress.toFixed(1) }}<small>%</small></strong>
          <span class="strip-status" :class="statusCode.toLowerCase()"><i></i>STATUS: {{ statusCode }}</span>
        </div>

        <section class="card log-panel">
          <div class="card-title"><h2><Activity :size="15" />系统日志</h2><span>{{ Math.min(logs.length, 20) }} 条 · {{ time(elapsed) }}</span></div>
          <div class="log-scroll">
            <div v-for="(entry, index) in logs.slice(0, 20)" :key="index" class="log-line">
              <time>[{{ entry.time }}]</time>
              <em :class="entry.level.toLowerCase()">{{ entry.level }}</em>
              <span>{{ entry.message }}</span>
            </div>
            <div v-if="!logs.length" class="log-line"><time>[--:--:--]</time><em class="info">INFO</em><span>任务准备就绪，等待开始巡检。</span></div>
          </div>
        </section>
      </section>

      <!-- 右栏：指挥员 Agent 助手 -->
      <aside class="card rail rail-right">
        <div class="agent-head">
          <div class="agent-avatar"><Box :size="18" /></div>
          <div><h2>指挥员 Agent 助手</h2><span><i></i>任务调度与观察建议</span></div>
        </div>
        <div class="agent-state">
          <span>当前任务</span><strong>{{ route.name }}</strong>
          <div><span>{{ status }}</span><span>{{ observations.length }} 条观察记录</span><span>{{ Math.min(REQUIRED_VIEWS, activeTarget !== null ? observationCoverage(observations, activeTarget) : 0) }}/{{ REQUIRED_VIEWS }} 视角</span></div>
          <p class="agent-step">{{ currentStep }}</p>
        </div>
        <div class="chat-history" aria-live="polite">
          <div v-for="(message, index) in messages" :key="index" class="chat-message" :class="message.role"><span>{{ message.role === 'user' ? '我' : 'Agent' }}</span><p>{{ message.text }}</p></div>
          <div v-if="pendingView || lastView" class="view-summary" data-testid="optimization-result">
            <span><ScanEye :size="13" />{{ pendingView ? '观察视点执行中' : '观察记录已归档' }}</span>
            <strong>{{ pendingView ? operationMessage : `${viewpoints.length} 次` }}<small>{{ pendingView ? `V${mission.sequence}` : '已完成采样' }}</small></strong>
            <p v-if="pendingView">目标 {{ observationTargets[pendingView.target]!.name }} · 高度 {{ pendingView.position[1].toFixed(1) }} m</p>
            <p v-else-if="lastView">最近一次视野通畅率 {{ Math.round((1 - lastView.after) * 100) }}%</p>
          </div>
          <div class="chat-alert" v-if="distribution.flagged > 0">
            <span>【视觉异常告警】</span>检测到 {{ distribution.flagged }} 株待复核样株，当前任务完成度 {{ progress.toFixed(0) }}%。
          </div>
        </div>
        <div class="agent-bottom">
          <div class="quick-commands"><button @click="sendCommand('状态')">任务状态</button><button :disabled="!canOptimize" @click="targetIndex = activeTarget ?? targetIndex; sendCommand('优化视点')">优化视点</button><button @click="sendCommand('返航')">返航</button></div>
          <form class="command-form" @submit.prevent="sendCommand()"><input v-model="command" aria-label="巡检调度指令" placeholder="输入调度指令…" maxlength="120" /><button aria-label="发送指令" :disabled="!command.trim()"><Send :size="15" /></button></form>
          <button class="report-shortcut" @click="modal = 'reports'"><FileDown :size="14" />巡检报告<span>{{ reports.length }} 份</span><ChevronRight :size="12" /></button>
        </div>
      </aside>
    </main>
    <div class="task-toast" role="status"><span></span>{{ notice }}</div>

    <div v-if="modal" class="modal-backdrop" @click.self="modal = ''"><section class="workbench-modal" role="dialog" aria-modal="true" :aria-label="modal === 'routes' ? '航线规划' : modal === 'models' ? '运行配置' : modal === 'viewpoints' ? '视点优化' : modal === 'plants' ? '植株观察' : modal === 'reset' ? '重置任务' : '巡检报告'"><div class="modal-title"><div><span>病虫害低空智能巡检</span><h2>{{ modal === 'routes' ? '航线规划' : modal === 'models' ? '运行配置' : modal === 'viewpoints' ? '视点优化' : modal === 'plants' ? '植株观察' : modal === 'reset' ? '重置任务' : '巡检报告' }}</h2></div><button aria-label="关闭弹窗" @click="modal = ''"><X :size="18" /></button></div>
      <template v-if="modal === 'routes'"><p class="modal-description">根据本次作业范围选择巡检方案。</p><button v-for="(item, index) in simulationRoutes" :key="item.id" class="route-option" :aria-pressed="draftRoute === item.id" @click="draftRoute = item.id"><span class="route-icon"><Route :size="19" /></span><div><strong>{{ item.name }}</strong><span v-if="index === 0" class="recommended">推荐</span><p>{{ item.description }}</p><small>{{ item.id === 'maize-orbit' ? '单株任务' : '区域覆盖' }} <i>·</i> {{ item.id === 'maize-boundary' ? '可选重点复核' : '复核航点自动规划' }} <i>·</i> 区域段 {{ time(routeLength(item.points) / speed) }}</small></div><span class="radio-mark"><Check v-if="draftRoute === item.id" :size="12" /></span></button><p v-if="stage !== 'idle' && stage !== 'completed'" class="inline-notice">当前任务尚未结束，请先重置任务后更换方案。</p><div class="modal-footer"><button class="button secondary" @click="modal = ''">取消</button><button class="button primary" :disabled="stage !== 'idle' && stage !== 'completed'" @click="configureRoute">应用方案</button></div></template>
      <template v-if="modal === 'viewpoints'"><p class="modal-description">视点将加入无人机巡检航段。抵达并完成悬停采样后，更新植株观察记录。</p><label class="modal-field">观察植株<select v-model.number="draftTarget" aria-label="观察植株"><option v-for="(target, index) in observationTargets" :key="target.name" :value="index">{{ target.name }}</option></select></label><label class="modal-field">调度策略<select v-model="draftStrategy" aria-label="调度策略"><option value="fixed">标准观察</option><option value="coverage">覆盖优先</option><option value="semantic">重点区域优先</option></select></label><div class="strategy-description"><ScanEye :size="18" /><p>{{ draftStrategy === 'fixed' ? '按标准顺序安排尚未采集的观察方向。' : draftStrategy === 'coverage' ? '结合飞行距离和遮挡，优先前往尚未覆盖的观察方向。' : '结合植株重点、叶片遮挡和已采记录，逐次规划复核视点。' }}</p></div><div class="observation-metrics"><div><span>有效视角</span><strong>{{ Math.min(REQUIRED_VIEWS, observationCoverage(observations, draftTarget)) }} <small>/ {{ REQUIRED_VIEWS }}</small></strong></div><div><span>已完成采样</span><strong>{{ viewpoints.length }} <small>次</small></strong></div></div><div class="modal-footer"><button class="button secondary" @click="modal = ''">取消</button><button class="button primary" :disabled="!canOptimize" @click="applyOptimization"><ScanEye :size="14" />{{ stage === 'idle' || mission.phase === 'survey' || activeTarget !== draftTarget ? '加入优先复核' : '重新规划当前视点' }}</button></div></template>
      <template v-if="modal === 'plants'"><p class="modal-description">已复核 {{ observedPlants }} 株。点击植株可切换当前观察目标，用于视点优化。</p><div class="plant-grid"><button v-for="(target, index) in observationTargets" :key="target.name" class="plant-card" :aria-pressed="targetIndex === index" @click="targetIndex = index"><div><strong>{{ target.name.split(' · ')[0] }}</strong><span :class="{ observed: observationCoverage(observations, index) > 0 }">{{ plantState(index) }}</span></div><p>{{ target.name.split(' · ')[1] }}</p><div class="coverage-dots"><i v-for="sector in 8" :key="sector" :class="{ seen: observations.some(item => item.target === index && item.sector === sector - 1 && item.visible >= .5) }"></i></div><small>{{ Math.min(REQUIRED_VIEWS, observationCoverage(observations, index)) }} / {{ REQUIRED_VIEWS }} 有效视角</small></button></div><div class="modal-footer"><button class="button secondary" @click="modal = ''">关闭</button><button class="button primary" :disabled="!canOptimize" @click="openOptimization"><ScanEye :size="14" />为该株规划视点</button></div></template>
      <template v-if="modal === 'models'"><div class="config-summary"><div><span>任务环境</span><strong>三维场景演示</strong></div><div><span>场景资源</span><strong>一号玉米试验田</strong></div><div><span>记录保存</span><strong>当前浏览器 · 自动保存</strong></div></div><div class="config-controls"><label>巡航速度<select v-model.number="speed" aria-label="巡航速度" @change="checkpoint"><option :value="2">2 m/s</option><option :value="4">4 m/s</option><option :value="8">8 m/s</option></select></label><label>播放倍率<select v-model.number="timeScale" aria-label="播放倍率" @change="checkpoint"><option :value="1">1×</option><option :value="2">2×</option><option :value="4">4×</option></select></label><button class="button secondary" :disabled="stage === 'idle' || stage === 'completed' || mission.phase === 'return'" @click="returnHome"><Navigation :size="13" />安全返航</button><button class="button secondary" @click="modal = 'reset'"><RotateCcw :size="13" />重置任务</button></div><p class="modal-description">当前任务使用内置场景资源，无需上传视频。业务素材与检测模型可通过素材中心统一管理。</p><details class="model-guide"><summary>模型权重上传说明</summary><ol><li>在素材中心选择对应业务的专用模型分类。</li><li>按分类提示使用固定文件名，子目录留空后上传。</li><li>服务端需安装推理依赖；替换已加载的权重后重启服务。</li></ol><p>素材中心会自动显示当前分类要求的模型文件名。</p></details><div class="modal-footer"><button class="button secondary" @click="modal = ''">关闭</button><RouterLink class="button primary" to="/assets">打开素材中心 <MoveUpRight :size="14" /></RouterLink></div></template>
      <template v-if="modal === 'reset'"><div class="reset-icon"><RotateCcw :size="20" /></div><p class="reset-description">确定重置当前任务？</p><p class="modal-description">当前飞行轨迹和观察记录将被清空。已保存的报告会保留；如需保留本次记录，请先生成报告。</p><div class="modal-footer"><button class="button secondary" @click="modal = ''">取消</button><button class="button primary" @click="resetMission">确认重置</button></div></template>
      <template v-if="modal === 'reports'"><div class="report-intro"><FileDown :size="18" /><div><strong>任务档案</strong><p>已保存 {{ reports.length }} 份报告，保留最近 5 次任务。</p></div></div><div v-if="!reports.length" class="empty-state"><FileDown :size="30" /><strong>暂无巡检报告</strong><p>开始巡检后，点击“生成报告”保存本次任务记录。</p></div><article v-for="report in reports" :key="report.id" class="report-card"><span class="report-icon"><FileDown :size="18" /></span><div><strong>{{ report.routeName }}</strong><p>{{ report.createdAt }}</p><small>{{ time(report.elapsed) }} <i>·</i> {{ report.distance.toFixed(1) }} m <i>·</i> {{ report.outcome === 'interrupted' ? '中途返航' : statusLabels[report.status] || report.status }}</small></div><div class="report-actions"><button @click="download(report, 'html')">导出报告</button><button @click="download(report, 'json')">导出数据</button></div></article></template>
    </section></div>
  </div>
</template>

<style scoped>
/* ---------- 骨架 ---------- */
.pest-workbench{height:100vh;display:flex;flex-direction:column;gap:12px;padding:12px 14px 14px;background:#f6f7f9;color:#334155;font-family:Inter,'Microsoft YaHei',sans-serif;overflow:hidden;font-size:12px}
.pest-workbench *{box-sizing:border-box}
button,a,select,input{font-family:inherit}
button{cursor:pointer;transition:background .15s,border-color .15s,color .15s}
button:disabled{opacity:.42;cursor:not-allowed}
.card{border:1px solid #e4e8ef;border-radius:8px;background:#fff}
/* ---------- 通用按钮 ---------- */
.button{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:7px 13px;border:1px solid transparent;border-radius:6px;font-size:12px;font-weight:600;white-space:nowrap;text-decoration:none}
.button.primary{background:#e11d48;border-color:#e11d48;color:#fff}
.button.primary:hover{background:#be123c}
.button.secondary{background:#fff;border-color:#e2e8f0;color:#475569}
.button.secondary:hover{background:#f8fafc;border-color:#cbd5e1}
.demo-tag{display:flex;align-items:center;gap:4px;color:#94a3b8;font-size:10px;margin-right:2px}
.clock-chip{display:flex;align-items:center;gap:5px;margin-left:4px;padding:6px 9px;border:1px solid #e2e8f0;border-radius:6px;background:#f8fafc;color:#64748b;font-size:11px;font-variant-numeric:tabular-nums}
/* ---------- 三栏 ---------- */
.workbench-grid{display:grid;grid-template-columns:232px minmax(0,1fr) 266px;gap:12px;min-height:0;flex:1}
.rail{min-height:0;display:flex;flex-direction:column;gap:10px}
.rail-left{overflow-y:auto;overflow-x:hidden;scrollbar-width:thin}
.rail-left>.card{padding:12px;flex-shrink:0}
.rail-left>.card.function-dock{margin-top:auto}
/* ---------- 卡片标题 ---------- */
.card-title{display:flex;align-items:center;gap:8px;margin-bottom:11px}
.card-title h2{display:flex;align-items:center;gap:6px;font-size:12px;font-weight:650;color:#0f172a}
.card-title h2 svg{color:#64748b}
.card-title>span{margin-left:auto;font-size:9px;color:#94a3b8;letter-spacing:.4px}
.link-badge{display:flex;align-items:center;gap:4px;margin-left:auto;padding:2px 6px;border:1px solid #e2e8f0;border-radius:4px;background:#f8fafc;font-size:8.5px!important;color:#64748b!important;letter-spacing:.3px}
.section-kicker{letter-spacing:1px;font-size:9px!important}
/* ---------- 遥测 ---------- */
.metric-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px 8px}
.metric{display:flex;flex-direction:column;gap:2px;min-width:0}
.metric>span{display:flex;align-items:center;gap:4px;font-size:9.5px;color:#8a97a8;white-space:nowrap}
.metric>strong{font-size:19px;line-height:1.15;font-weight:650;color:#0f172a;font-variant-numeric:tabular-nums}
.metric>strong small{font-size:9px;color:#94a3b8;margin-left:2px;font-weight:500}
.metric>em{font-style:normal;font-size:8.5px;color:#b0bac7}
.telemetry-foot{display:flex;align-items:center;justify-content:space-between;gap:6px;margin-top:11px;padding-top:9px;border-top:1px solid #f1f5f9}
.state-badge{display:flex;align-items:center;gap:4px;padding:3px 7px;border-radius:4px;background:#f1f5f9;color:#64748b;font-size:9.5px}
.state-badge i{width:5px;height:5px;border-radius:50%;background:#94a3b8}
.state-badge.live{background:#ecfdf5;color:#059669}
.state-badge.live i{background:#10b981;animation:pulse 1.6s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
.coord{font-size:8.5px;color:#b0bac7;font-variant-numeric:tabular-nums;white-space:nowrap}
/* ---------- 环形图 ---------- */
.donut-row{display:flex;align-items:center;gap:12px}
.donut{width:66px;height:66px;border-radius:50%;flex-shrink:0;display:grid;place-items:center;position:relative}
.donut-hole{width:46px;height:46px;border-radius:50%;background:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;box-shadow:inset 0 0 0 1px #f1f5f9}
.donut-hole strong{font-size:15px;font-weight:650;color:#0f172a;line-height:1}
.donut-hole span{font-size:8px;color:#94a3b8;margin-top:2px}
.donut-legend{display:flex;flex-direction:column;gap:5px;min-width:0;flex:1}
.donut-legend li{display:flex;align-items:center;gap:5px;font-size:9.5px;color:#64748b}
.donut-legend i{width:6px;height:6px;border-radius:2px;flex-shrink:0}
.c-blue{background:#2563eb}.c-red{background:#ef4444}.c-amber{background:#f59e0b}.c-slate{background:#e2e8f0}
.donut-legend b{margin-left:auto;color:#334155;font-weight:600;font-variant-numeric:tabular-nums}
.distribution-foot{display:flex;align-items:center;justify-content:space-between;gap:6px;margin-top:10px;padding-top:8px;border-top:1px solid #f1f5f9;font-size:9px;color:#94a3b8}
.distribution-foot button{display:flex;align-items:center;gap:2px;border:0;background:none;color:#2563eb;font-size:9px;font-weight:600;padding:0}
/* ---------- 左下角功能坞 ---------- */
.dock-list{display:flex;flex-direction:column;gap:2px}
.dock-list button{display:flex;align-items:center;gap:8px;width:100%;padding:7px;border:0;border-radius:6px;background:none;color:#475569;font-size:11px;text-align:left}
.dock-list button:hover:not(:disabled){background:#f4f6fa;color:#0f172a}
.dock-list button>svg:first-child{color:#64748b;flex-shrink:0}
.dock-list button span{flex:1}
.dock-list button em{font-style:normal;font-size:9px;color:#94a3b8;background:#f1f5f9;border-radius:3px;padding:1px 5px}
.dock-list button>svg:last-child{color:#cbd5e1}
.dock-modules{margin-top:8px;padding-top:8px;border-top:1px solid #f1f5f9}
.module-toggle{display:flex;align-items:center;gap:7px;width:100%;padding:7px;border:1px solid #e4e8ef;border-radius:6px;background:#f8fafc;color:#475569;font-size:10.5px;font-weight:600}
.module-toggle span{flex:1;text-align:left}
.module-toggle svg:last-child{color:#94a3b8;transition:transform .18s}
.module-toggle svg.flip{transform:rotate(180deg)}
.module-list{display:grid;grid-template-columns:1fr 1fr;gap:2px;margin-top:6px;max-height:220px;overflow:auto;scrollbar-width:thin;padding-right:2px}
.module-list button{display:flex;align-items:center;justify-content:space-between;gap:4px;padding:5px 6px;border:0;border-radius:5px;background:none;color:#64748b;font-size:9.5px;text-align:left;line-height:1.3;overflow:hidden}
.module-list button span,.module-list button{white-space:nowrap;text-overflow:ellipsis}
.module-list button:hover{background:#f4f6fa;color:#0f172a}
.module-list button.current{background:#eff6ff;color:#2563eb;font-weight:600}
/* ---------- 中栏舞台 ---------- */
.stage-column{display:flex;flex-direction:column;gap:10px;min-height:0;min-width:0}
.stage{display:flex;flex-direction:column;flex:1;min-height:0;border:1px solid #e4e8ef;border-radius:8px;background:#0b1220;overflow:hidden}
.stage-head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 11px;border-bottom:1px solid #1e293b;background:#0d1728;flex-shrink:0}
.stage-title{display:flex;align-items:center;gap:7px;min-width:0}
.stage-title strong{font-size:11.5px;font-weight:600;color:#e2e8f0;white-space:nowrap}
.stage-sub{font-size:9.5px;color:#64748b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.live-dot{width:5px;height:5px;border-radius:50%;background:#475569;flex-shrink:0}
.live-dot.on{background:#10b981;box-shadow:0 0 0 3px #10b98124}
.stage-actions{display:flex;align-items:center;gap:6px;flex-shrink:0}
.replay-entry{display:flex;align-items:center;gap:5px;padding:5px 9px;border:1px solid #2dd4bf55;border-radius:5px;background:#0f2f2c;color:#5eead4;font-size:10.5px;font-weight:600}
.replay-entry:hover{background:#134e4a;border-color:#2dd4bf99}
.replay-entry.back{border-color:#334155;background:#111c2e;color:#cbd5e1}
.replay-entry.back:hover{background:#1b2942;border-color:#475569}
.replay-entry.back{border-color:#334155;background:#111c2e;color:#cbd5e1}
.replay-entry.back:hover{background:#1b2942;border-color:#475569}
.icon-btn{display:grid;place-items:center;width:26px;height:26px;border:1px solid #1e293b;border-radius:5px;background:#111c2e;color:#94a3b8}
.icon-btn:hover{background:#1b2942;color:#e2e8f0}
.stage-body{position:relative;flex:1;min-height:0;overflow:hidden;container-type:inline-size}
.stage-foot{display:flex;align-items:center;gap:8px;padding:7px 11px;border-top:1px solid #1e293b;background:#0d1728;flex-shrink:0}
.play-btn{display:grid;place-items:center;width:24px;height:24px;border:1px solid #334155;border-radius:5px;background:#16233a;color:#e2e8f0;flex-shrink:0}
.play-btn:hover:not(:disabled){background:#1e2f4d}
.play-btn.ghost{background:transparent;color:#64748b}
.foot-time{font-size:9.5px;color:#94a3b8;font-variant-numeric:tabular-nums;flex-shrink:0}
.foot-time.end{color:#64748b}
.foot-track{flex:1;height:3px;border-radius:2px;background:#1e293b;overflow:hidden;min-width:0}
.foot-track i{display:block;height:100%;background:#e11d48;border-radius:2px;transition:width .3s}
/* 舞台内浮层 */
.hud-params{position:absolute;left:10px;bottom:10px;display:flex;gap:12px;padding:4px 8px;border-radius:4px;background:#0b1220cc;border:1px solid #1e293b;font-size:8.5px;color:#64748b;pointer-events:none}
.hud-params b{color:#cbd5e1;font-weight:600;font-variant-numeric:tabular-nums}
.mini-map{position:absolute;right:10px;top:10px;width:118px;padding:5px 6px 4px;border-radius:5px;background:#0b1220d9;border:1px solid #1e293b;pointer-events:none}
.mini-map span{display:block;font-size:8px;color:#7c8ba1;margin-bottom:2px}
.mini-map svg{display:block;width:100%;height:auto;aspect-ratio:96/72;background:#08101c;border-radius:3px}
.camera-toolbar{position:absolute;left:10px;top:10px;display:flex;align-items:center;gap:3px;padding:3px;border-radius:6px;background:#0b1220cc;border:1px solid #1e293b}
.camera-toolbar button{display:flex;align-items:center;gap:3px;padding:4px 7px;border:0;border-radius:4px;background:none;color:#94a3b8;font-size:9px}
.camera-toolbar button:hover:not(:disabled){background:#1b2942;color:#e2e8f0}
.camera-toolbar button[aria-pressed="true"]{background:#1e3a5f;color:#bfdbfe}
.camera-toolbar i{width:1px;height:12px;background:#1e293b;margin:0 2px}
.viewpoint-hud{position:absolute;left:10px;right:10px;bottom:36px;max-width:calc(100% - 160px);display:flex;align-items:center;gap:8px;padding:7px 9px;border-radius:6px;background:#0b1220e6;border:1px solid #1e3a5f;color:#cbd5e1}
.viewpoint-hud>svg{color:#38bdf8;flex-shrink:0}
.viewpoint-hud>div{display:flex;flex-direction:column;gap:1px;min-width:0;flex:1}
.viewpoint-hud strong{font-size:10px;color:#e2e8f0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.viewpoint-hud span{font-size:8.5px;color:#7c8ba1}
.viewpoint-hud button{padding:4px 8px;border:1px solid #334155;border-radius:4px;background:#16233a;color:#cbd5e1;font-size:9px;flex-shrink:0}
.stage-mask{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;gap:8px;background:#0b1220cc;color:#94a3b8;font-size:11px;z-index:5}
.stage-mask.error{color:#fca5a5}
.spinner{width:14px;height:14px;border:2px solid #1e293b;border-top-color:#38bdf8;border-radius:50%;animation:spin .9s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
/* ---------- 状态条 ---------- */
.status-strip{display:flex;align-items:center;gap:8px;padding:7px 10px;border:1px solid #e4e8ef;border-radius:8px;background:#fff;flex-shrink:0;min-width:0}
.strip-opt{display:flex;align-items:center;gap:4px;padding:4px 9px;border:1px solid #dbeafe;border-radius:5px;background:#eff6ff;color:#2563eb;font-size:10px;font-weight:600;flex-shrink:0}
.strip-opt:hover:not(:disabled){background:#dbeafe}
.strip-sep{width:1px;height:14px;background:#e4e8ef;flex-shrink:0}
.strip-route{font-size:10.5px;font-weight:600;color:#334155;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:150px}
.strip-metric{font-size:9.5px;color:#94a3b8;white-space:nowrap;flex-shrink:0}
.strip-metric b{color:#475569;font-weight:600}
.strip-notice{flex:1;min-width:0;font-size:9.5px;color:#94a3b8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:right}
.strip-progress{font-size:15px;font-weight:650;color:#e11d48;font-variant-numeric:tabular-nums;flex-shrink:0;margin-left:4px}
.strip-progress small{font-size:9px;color:#f43f5e;margin-left:1px;font-weight:600}
.strip-status{display:flex;align-items:center;gap:4px;padding:3px 7px;border-radius:4px;background:#f1f5f9;color:#64748b;font-size:8.5px;letter-spacing:.3px;flex-shrink:0;font-variant-numeric:tabular-nums}
.strip-status i{width:4px;height:4px;border-radius:50%;background:#94a3b8}
.strip-status.running{background:#ecfdf5;color:#059669}.strip-status.running i{background:#10b981;animation:pulse 1.6s infinite}
.strip-status.paused{background:#fffbeb;color:#b45309}.strip-status.paused i{background:#f59e0b}
.strip-status.done{background:#eff6ff;color:#2563eb}.strip-status.done i{background:#3b82f6}
/* ---------- 日志 ---------- */
.log-panel{flex-shrink:0;height:146px;display:flex;flex-direction:column;padding:11px 12px 9px}
.log-panel .card-title{margin-bottom:8px}
.log-scroll{flex:1;min-height:0;overflow:auto;display:flex;flex-direction:column;gap:5px;scrollbar-width:thin;font-variant-numeric:tabular-nums}
.log-line{display:flex;align-items:baseline;gap:7px;font-size:9.5px;line-height:1.5}
.log-line time{color:#b0bac7;flex-shrink:0;font-size:9px}
.log-line em{flex-shrink:0;font-style:normal;font-size:8px;font-weight:700;letter-spacing:.3px;padding:1px 4px;border-radius:3px}
.log-line em.info{background:#eff6ff;color:#2563eb}
.log-line em.warning{background:#fef3c7;color:#b45309}
.log-line span{color:#64748b;min-width:0}
/* ---------- 右栏 Agent ---------- */
.rail-right{padding:12px;overflow:hidden}
.agent-head{display:flex;align-items:center;gap:9px;padding-bottom:10px;border-bottom:1px solid #f1f5f9}
.agent-avatar{display:grid;place-items:center;width:30px;height:30px;border-radius:8px;background:linear-gradient(140deg,#eff6ff,#eef2ff);border:1px solid #dbeafe;color:#3b82f6;flex-shrink:0}
.agent-head h2{font-size:12px;font-weight:650;color:#0f172a}
.agent-head span{display:flex;align-items:center;gap:4px;font-size:9px;color:#94a3b8;margin-top:2px}
.agent-head span i{width:4px;height:4px;border-radius:50%;background:#10b981}
.agent-state{margin-top:10px;padding:8px 9px;border:1px solid #e4e8ef;border-radius:6px;background:#f8fafc}
.agent-state>span{font-size:8.5px;color:#94a3b8;letter-spacing:.3px}
.agent-state>strong{display:block;font-size:11px;color:#1e293b;font-weight:600;margin-top:2px}
.agent-state>div{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}
.agent-state>div span{font-size:8.5px;color:#64748b;background:#fff;border:1px solid #e4e8ef;border-radius:3px;padding:1px 5px}
.agent-step{margin-top:6px;font-size:8.5px;color:#94a3b8;line-height:1.6;border-top:1px dashed #e4e8ef;padding-top:5px}
.chat-history{flex:1;min-height:0;overflow:auto;display:flex;flex-direction:column;gap:8px;padding:10px 0;scrollbar-width:thin}
.chat-message{display:flex;flex-direction:column;gap:3px;padding:8px 9px;border-radius:7px;font-size:10px;line-height:1.6}
.chat-message>span{font-size:8px;color:#94a3b8;font-weight:600}
.chat-message p{color:#475569}
.chat-message.assistant{background:#f8fafc;border:1px solid #eef2f7}
.chat-message.user{background:#eff6ff;border:1px solid #dbeafe;align-items:flex-end}
.chat-message.user>span{order:2}
.chat-message.user p{color:#1e40af;text-align:right}
.view-summary{margin-top:auto;padding:8px 9px;border:1px solid #dbeafe;border-radius:7px;background:#f5f9ff}
.view-summary>span{display:flex;align-items:center;gap:4px;font-size:8.5px;color:#2563eb;font-weight:600}
.view-summary strong{display:block;font-size:14px;font-weight:650;color:#0f172a;margin-top:3px}
.view-summary strong small{font-size:8.5px;color:#94a3b8;margin-left:4px;font-weight:500}
.view-summary p{font-size:9px;color:#64748b;margin-top:3px;line-height:1.5}
.chat-alert{padding:8px 9px;border:1px solid #fee2e2;border-radius:7px;background:#fff5f5;font-size:9.5px;line-height:1.65;color:#b91c1c}
.chat-alert span{font-weight:700}
.agent-bottom{border-top:1px solid #f1f5f9;padding-top:9px;display:flex;flex-direction:column;gap:7px}
.quick-commands{display:flex;gap:4px}
.quick-commands button{flex:1;padding:5px 4px;border:1px solid #e4e8ef;border-radius:5px;background:#fff;color:#64748b;font-size:9px;white-space:nowrap}
.quick-commands button:hover:not(:disabled){background:#f4f6fa;color:#334155;border-color:#cbd5e1}
.command-form{display:flex;align-items:center;gap:5px;padding:3px 3px 3px 9px;border:1px solid #e4e8ef;border-radius:6px;background:#f8fafc}
.command-form:focus-within{border-color:#93c5fd;background:#fff}
.command-form input{flex:1;min-width:0;border:0;background:none;outline:none;font-size:10px;color:#334155}
.command-form input::placeholder{color:#b0bac7}
.command-form button{display:grid;place-items:center;width:24px;height:24px;border:0;border-radius:4px;background:#2563eb;color:#fff;flex-shrink:0}
.command-form button:disabled{background:#e2e8f0;color:#94a3b8}
.report-shortcut{display:flex;align-items:center;gap:6px;padding:6px 8px;border:1px solid #e4e8ef;border-radius:5px;background:#fff;color:#475569;font-size:9.5px;font-weight:600}
.report-shortcut:hover{background:#f4f6fa}
.report-shortcut span{margin-left:auto;font-size:8.5px;color:#94a3b8;font-weight:500}
/* ---------- toast ---------- */
.task-toast{position:fixed;left:50%;bottom:16px;transform:translateX(-50%);display:flex;align-items:center;gap:7px;max-width:min(620px,88vw);padding:8px 14px;border:1px solid #e4e8ef;border-radius:20px;background:#fffffff2;color:#475569;font-size:10.5px;box-shadow:0 8px 24px -16px #0f172a66;z-index:40;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.task-toast span{width:5px;height:5px;border-radius:50%;background:#10b981;flex-shrink:0}
/* ---------- 弹窗 ---------- */
.modal-backdrop{position:fixed;inset:0;background:#0f172a4d;backdrop-filter:blur(2px);display:flex;align-items:center;justify-content:center;padding:20px;z-index:50}
.workbench-modal{width:min(520px,100%);max-height:88vh;overflow:auto;padding:20px;border:1px solid #e4e8ef;border-radius:10px;background:#fff;box-shadow:0 24px 60px -30px #0f172a66;scrollbar-width:thin}
.modal-title{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding-bottom:14px;border-bottom:1px solid #f1f5f9}
.modal-title span{font-size:9.5px;color:#94a3b8;letter-spacing:.4px}
.modal-title h2{font-size:16px;font-weight:650;color:#0f172a;margin-top:3px}
.modal-title>button{display:grid;place-items:center;width:28px;height:28px;border:0;border-radius:6px;background:#f8fafc;color:#94a3b8;flex-shrink:0}
.modal-title>button:hover{background:#f1f5f9;color:#475569}
.modal-description{font-size:10.5px;color:#94a3b8;line-height:1.75;margin-top:12px}
.modal-description+.modal-description{margin-top:8px}
.modal-field{display:flex;flex-direction:column;gap:6px;margin-top:14px;font-size:10px;color:#64748b;font-weight:600}
.modal-field select{padding:8px 10px;border:1px solid #e2e8f0;border-radius:6px;background:#fff;color:#334155;font-size:11px;outline:none}
.modal-field select:focus{border-color:#93c5fd}
.strategy-description{display:flex;gap:9px;margin-top:12px;padding:10px;border:1px solid #eff6ff;border-radius:6px;background:#f8fbff;color:#3b82f6}
.strategy-description p{font-size:10px;color:#64748b;line-height:1.7}
.observation-metrics{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:12px}
.observation-metrics>div{padding:9px 11px;border:1px solid #e4e8ef;border-radius:6px;background:#f8fafc}
.observation-metrics span{display:block;font-size:8.5px;color:#94a3b8}
.observation-metrics strong{font-size:16px;font-weight:650;color:#0f172a}
.observation-metrics small{font-size:9px;color:#94a3b8;font-weight:500}
.route-option{display:flex;align-items:center;gap:10px;width:100%;margin-top:9px;padding:11px;border:1px solid #e4e8ef;border-radius:7px;background:#fff;text-align:left;position:relative}
.route-option:hover{border-color:#cbd5e1;background:#fcfdff}
.route-option[aria-pressed="true"]{border-color:#93c5fd;background:#f5f9ff;box-shadow:0 0 0 1px #bfdbfe}
.route-icon{display:grid;place-items:center;width:34px;height:38px;border-radius:6px;background:#f1f5f9;color:#64748b;flex-shrink:0}
.route-option>div{flex:1;min-width:0}
.route-option strong{font-size:11.5px;color:#1e293b;font-weight:650}
.recommended{display:inline-block;margin-left:6px;padding:1px 5px;border-radius:3px;background:#ecfdf5;color:#059669;font-size:8px;font-weight:700;vertical-align:1px}
.route-option p{font-size:9.5px;color:#94a3b8;margin-top:3px;line-height:1.55}
.route-option small{font-size:8.5px;color:#b0bac7;margin-top:4px;display:block}
.route-option small i{margin:0 4px;font-style:normal}
.radio-mark{display:grid;place-items:center;width:16px;height:16px;border:1px solid #e2e8f0;border-radius:50%;background:#fff;color:#fff;flex-shrink:0}
.route-option[aria-pressed="true"] .radio-mark{background:#2563eb;border-color:#2563eb}
.inline-notice{margin-top:10px;font-size:9.5px;color:#b45309;background:#fffbeb;border:1px solid #fef3c7;border-radius:5px;padding:7px 9px}
.modal-footer{display:flex;justify-content:flex-end;gap:8px;margin-top:16px;padding-top:13px;border-top:1px solid #f1f5f9}
.config-summary{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px}
.config-summary>div{padding:9px 10px;border:1px solid #e4e8ef;border-radius:6px;background:#f8fafc}
.config-summary span{display:block;font-size:8.5px;color:#94a3b8}
.config-summary strong{display:block;font-size:10px;color:#334155;font-weight:600;margin-top:3px}
.config-controls{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;align-items:center}
.config-controls label{display:flex;align-items:center;gap:6px;font-size:9.5px;color:#64748b}
.config-controls select{padding:6px 8px;border:1px solid #e2e8f0;border-radius:5px;background:#fff;color:#334155;font-size:10px;outline:none}
.model-guide{margin-top:12px;border:1px solid #e4e8ef;border-radius:6px;padding:10px 11px;background:#fcfdff}
.model-guide summary{font-size:10px;color:#475569;font-weight:600;cursor:pointer}
.model-guide ol{margin:8px 0 0 16px;display:flex;flex-direction:column;gap:4px}
.model-guide li,.model-guide p{font-size:9.5px;color:#94a3b8;line-height:1.7}
.model-guide p{margin-top:7px}
.reset-icon{display:grid;place-items:center;width:40px;height:40px;margin:14px auto 0;border-radius:50%;background:#fff1f2;color:#e11d48}
.reset-description{text-align:center;font-size:13px;font-weight:650;color:#0f172a;margin-top:9px}
.report-intro{display:flex;align-items:center;gap:9px;margin-top:13px;padding:10px;border:1px solid #eff6ff;border-radius:6px;background:#f8fbff;color:#3b82f6}
.report-intro strong{font-size:10.5px;color:#1e293b}
.report-intro p{font-size:9px;color:#94a3b8;margin-top:2px}
.empty-state{display:flex;flex-direction:column;align-items:center;gap:6px;padding:26px 12px;color:#cbd5e1}
.empty-state strong{font-size:11px;color:#64748b}
.empty-state p{font-size:9.5px;color:#94a3b8;text-align:center;line-height:1.7}
.report-card{display:flex;align-items:center;gap:10px;margin-top:9px;padding:10px;border:1px solid #e4e8ef;border-radius:7px;background:#fff}
.report-icon{display:grid;place-items:center;width:32px;height:32px;border-radius:6px;background:#f1f5f9;color:#64748b;flex-shrink:0}
.report-card>div:nth-child(2){flex:1;min-width:0}
.report-card strong{font-size:10.5px;color:#1e293b;font-weight:650}
.report-card p{font-size:9px;color:#94a3b8;margin-top:2px}
.report-card small{font-size:8.5px;color:#b0bac7;display:block;margin-top:3px}
.report-card small i{margin:0 4px;font-style:normal}
.report-actions{display:flex;gap:5px;flex-shrink:0}
.report-actions button{padding:5px 8px;border:1px solid #e2e8f0;border-radius:5px;background:#fff;color:#475569;font-size:9px;font-weight:600}
.report-actions button:hover{background:#f4f6fa;border-color:#cbd5e1}
/* 植株网格（弹窗内） */
.plant-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:13px}
.plant-card{padding:10px;border:1px solid #e4e8ef;border-radius:7px;background:#fff;text-align:left;display:flex;flex-direction:column;gap:5px}
.plant-card:hover{border-color:#cbd5e1}
.plant-card[aria-pressed="true"]{border-color:#93c5fd;background:#f5f9ff;box-shadow:0 0 0 1px #bfdbfe}
.plant-card>div:first-child{display:flex;align-items:center;justify-content:space-between;gap:6px}
.plant-card strong{font-size:10.5px;color:#1e293b;font-weight:650}
.plant-card>div:first-child span{font-size:8px;padding:1px 5px;border-radius:3px;background:#f1f5f9;color:#94a3b8;white-space:nowrap}
.plant-card>div:first-child span.observed{background:#ecfdf5;color:#059669}
.plant-card p{font-size:8.5px;color:#94a3b8}
.coverage-dots{display:flex;gap:2px}
.coverage-dots i{height:4px;flex:1;border-radius:1px;background:#e9edf3}
.coverage-dots i.seen{background:#3b82f6}
.plant-card small{font-size:8.5px;color:#b0bac7}
/* ---------- 响应式 ---------- */
@media(max-width:1350px){.workbench-grid{grid-template-columns:216px minmax(0,1fr) 248px;gap:10px}.pest-workbench{padding:10px}.rail-left>.card{padding:11px}.metric>strong{font-size:17px}.strip-route{max-width:110px}.log-panel{height:132px}}
@media(max-width:1180px){.pest-workbench{height:auto;min-height:100vh;overflow:visible}.workbench-grid{grid-template-columns:210px minmax(0,1fr);flex:none;align-items:start}.rail-left{overflow:visible}.stage-column{min-height:560px}.rail-right{grid-column:1/-1;flex-direction:row;flex-wrap:wrap;max-height:none;min-height:260px}.rail-right .agent-head{flex:0 1 auto}.rail-right .agent-state{flex:0 1 420px;margin-left:auto}.rail-right .agent-step{margin-top:6px;font-size:8.5px;color:#94a3b8;line-height:1.6;border-top:1px dashed #e4e8ef;padding-top:5px}
.chat-history{flex:1 1 100%;max-height:220px}.rail-right .agent-bottom{flex:1 1 100%}.stage-column{min-height:520px}}
@media(max-width:900px){.metric-grid{grid-template-columns:1fr 1fr}.camera-toolbar button span{display:none}.mini-map{width:96px}.strip-notice{display:none}}
@media(max-width:760px){.pest-workbench{height:auto;min-height:100vh;overflow:visible;padding:9px;gap:9px}.workbench-grid{display:flex;flex-direction:column;gap:9px}.stage-column{order:-1;min-height:0}.stage-body{height:330px;flex:none}.rail-left,.rail-right{width:100%}.rail-left{overflow:visible}.rail-left>.card.function-dock{margin-top:0}.rail-right{min-height:0}.icon-btn,.replay-entry{font-size:9.5px}.foot-time{font-size:8.5px}.status-strip{flex-wrap:wrap;gap:6px}.strip-notice{display:none}.log-panel{height:150px}.modal-backdrop{padding:10px}.workbench-modal{padding:16px;max-height:92vh}.config-summary{grid-template-columns:1fr}.plant-grid{grid-template-columns:1fr}}
@media(min-height:960px){.log-panel{height:172px}}
</style>
