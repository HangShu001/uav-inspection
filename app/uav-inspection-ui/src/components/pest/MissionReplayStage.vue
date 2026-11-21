<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Play, Pause, Battery, Gauge, MapPin, Clock3 } from 'lucide-vue-next'
import type { PlantObservation, Position3, SimulationSample } from '../../utils/pestSimulation'

const props = defineProps<{
  samples: SimulationSample[]
  routePoints: Position3[]
  observations: PlantObservation[]
  viewpoints: { position: Position3; target?: number }[]
  targets: readonly { name: string; point: Position3 }[]
  plants: readonly string[]
  totalSeconds: number
}>()

const cursor = ref(0)
const playing = ref(false)
let timer = 0

const flown = computed(() => props.samples.at(-1)?.second ?? 0)
const end = computed(() => Math.max(flown.value, 0.1))
const trail = computed(() => props.samples.filter(s => s.second <= cursor.value + 1e-6))
const current = computed<SimulationSample | null>(() => {
  if (!props.samples.length) return null
  let last: SimulationSample | null = null
  for (const s of props.samples) { if (s.second <= cursor.value + 1e-6) last = s; else break }
  // 首条采样落在 1 s 之后：拖到 0 s 时不要让读数变「--」，退回第一条
  return last ?? props.samples[0]!
})
const clock = (v: number) => `${String(Math.floor(v / 60)).padStart(2, '0')}:${String(Math.floor(v % 60)).padStart(2, '0')}`

// 场景坐标 → 视图坐标（x ∈ [-30,30]，z ∈ [-26,36]，北向上）
const sx = (x: number) => ((x + 30) / 60) * 320
const sy = (z: number) => ((36 - z) / 62) * 340
const poly = (list: Position3[]) => list.map(p => `${sx(p[0]).toFixed(1)},${sy(p[2]).toFixed(1)}`).join(' ')
const trailPoly = computed(() => poly(trail.value.map(s => [s.x, s.altitude, s.z] as Position3)))
const routePoly = computed(() => poly(props.routePoints))
const planted = computed(() => props.targets.map((t, i) => ({ ...t, index: i, state: props.plants[i] ?? 'pending' })))
const seen = (target: number) => props.observations.filter(o => o.target === target && o.visible >= .5).length
const stateColor = (state: string) => state === 'reviewed' ? '#34d399' : ['queued', 'inspecting', 'needs-review'].includes(state) ? '#fbbf24' : state === 'surveyed' ? '#60a5fa' : '#64748b'

function stop() { playing.value = false; if (timer) { window.clearInterval(timer); timer = 0 } }
function toggle() {
  if (playing.value) return stop()
  if (cursor.value >= end.value) cursor.value = 0
  playing.value = true
  timer = window.setInterval(() => {
    cursor.value = Math.min(end.value, cursor.value + .2)
    if (cursor.value >= end.value) stop()
  }, 100)
}
watch(() => props.samples.length, () => { if (!playing.value) cursor.value = Math.min(cursor.value, end.value) })
onBeforeUnmount(stop)
</script>

<template>
  <div class="replay-stage">
    <div class="replay-body">
      <div class="replay-map">
        <svg viewBox="0 0 320 340" preserveAspectRatio="xMidYMid meet" role="img" aria-label="巡检航迹俯视图">
          <defs>
            <pattern id="replayGrid" width="32" height="34" patternUnits="userSpaceOnUse">
              <path d="M32 0H0V34" fill="none" stroke="#1e293b" stroke-width="1" />
            </pattern>
          </defs>
          <rect width="320" height="340" fill="#0b1220" />
          <rect width="320" height="340" fill="url(#replayGrid)" opacity=".7" />
          <polyline v-if="routePoly" :points="routePoly" fill="none" stroke="#334155" stroke-width="1.6" stroke-dasharray="5 5" />
          <polyline v-if="trailPoly" :points="trailPoly" fill="none" stroke="#36d5bc" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" />
          <g v-for="p in viewpoints" :key="`v-${p.position.join(',')}`">
            <rect :x="sx(p.position[0]) - 3" :y="sy(p.position[2]) - 3" width="6" height="6" fill="#a78bfa" />
          </g>
          <g v-for="t in planted" :key="t.index">
            <circle :cx="sx(t.point[0])" :cy="sy(t.point[2])" r="5.4" :fill="stateColor(t.state)" opacity=".9" />
            <text :x="sx(t.point[0])" :y="sy(t.point[2]) - 9" fill="#cbd5e1" font-size="9" text-anchor="middle">{{ t.name.split(' · ')[0] }}</text>
          </g>
          <circle v-if="current" :cx="sx(current.x)" :cy="sy(current.z)" r="4.6" fill="#f8fafc" stroke="#36d5bc" stroke-width="2.2" />
        </svg>
        <span class="replay-legend"><i class="lg-route"></i>规划航线<i class="lg-trail"></i>已飞航迹<i class="lg-plant"></i>观察植株<i class="lg-view"></i>采样视点</span>
      </div>

      <div class="replay-side">
        <div class="replay-meter"><span><Clock3 :size="12" />回放时刻</span><strong>{{ clock(cursor) }}<small>/ {{ clock(end) }}</small></strong></div>
        <div class="replay-meter"><span><Gauge :size="12" />飞行高度</span><strong>{{ current ? current.altitude.toFixed(1) : '--' }}<small>m</small></strong></div>
        <div class="replay-meter"><span><Battery :size="12" />剩余电量</span><strong>{{ current ? current.battery.toFixed(0) : '--' }}<small>%</small></strong></div>
        <div class="replay-meter"><span><MapPin :size="12" />已采视点</span><strong>{{ viewpoints.length }}<small>次</small></strong></div>
        <div class="replay-plants">
          <div v-for="t in planted" :key="`s-${t.index}`">
            <i :style="{ background: stateColor(t.state) }"></i>
            <span>{{ t.name.split(' · ')[0] }}</span>
            <b>{{ seen(t.index) }}/3</b>
          </div>
        </div>
      </div>
    </div>

    <div class="replay-foot">
      <button class="replay-play" :aria-label="playing ? '暂停回放' : '播放回放'" @click="toggle"><Pause v-if="playing" :size="14" /><Play v-else :size="14" /></button>
      <span class="replay-time">{{ clock(cursor) }}</span>
      <input v-model.number="cursor" class="replay-range" type="range" min="0" :max="end" step="0.2" aria-label="回放进度" :disabled="!samples.length" />
      <span class="replay-time end">{{ clock(end) }}</span>
    </div>
    <p v-if="!samples.length" class="replay-empty">尚无飞行记录 —— 开始巡检并飞行后，这里会生成可拖动回放的过程视图。</p>
  </div>
</template>

<style scoped>
.replay-stage{display:flex;flex-direction:column;height:100%;min-height:0;overflow:hidden;color:#e2e8f0}
.replay-body{display:flex;gap:12px;flex:1;min-height:0;padding:12px 14px}
.replay-map{position:relative;flex:1;min-width:0;display:flex;align-items:center;justify-content:center;border-radius:8px;background:#0b1220;border:1px solid #172033}
.replay-map svg{width:100%;height:100%;max-height:100%}
.replay-legend{position:absolute;left:10px;bottom:8px;display:flex;align-items:center;gap:5px;font-size:9px;color:#7c8ba1;background:#0b1220cc;padding:4px 7px;border-radius:5px}
.replay-legend i{width:10px;height:2px;border-radius:1px;margin-left:6px}
.replay-legend i:first-child{margin-left:0}
.lg-route{background:#64748b}.lg-trail{background:#36d5bc}.lg-plant{background:#34d399;height:6px!important;width:6px!important;border-radius:50%!important}.lg-view{background:#a78bfa;height:6px!important;width:6px!important}
.replay-side{width:186px;flex-shrink:0;display:flex;flex-direction:column;gap:7px;min-height:0;overflow:auto;scrollbar-width:thin}
.replay-meter{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 10px;border:1px solid #1e293b;border-radius:7px;background:#111c2e}
.replay-meter>span{display:flex;align-items:center;gap:5px;font-size:10px;color:#94a3b8}
.replay-meter strong{font-size:14px;font-weight:600;color:#f1f5f9;font-variant-numeric:tabular-nums}
.replay-meter small{font-size:9px;color:#64748b;margin-left:3px;font-weight:400}
.replay-plants{margin-top:2px;border:1px solid #1e293b;border-radius:7px;background:#111c2e;padding:8px 10px;display:flex;flex-direction:column;gap:6px}
.replay-plants>div{display:flex;align-items:center;gap:6px;font-size:10px;color:#94a3b8}
.replay-plants i{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.replay-plants b{margin-left:auto;color:#e2e8f0;font-weight:600;font-variant-numeric:tabular-nums}
.replay-foot{display:flex;align-items:center;gap:9px;padding:9px 14px;border-top:1px solid #1e293b;background:#0d1728}
.replay-play{display:grid;place-items:center;width:28px;height:28px;border-radius:6px;border:1px solid #334155;background:#16233a;color:#e2e8f0;flex-shrink:0}
.replay-play:hover{background:#1e2f4d}
.replay-time{font-size:10px;color:#94a3b8;font-variant-numeric:tabular-nums;width:38px;text-align:center;flex-shrink:0}
.replay-time.end{color:#64748b}
.replay-range{flex:1;min-width:0;height:3px;-webkit-appearance:none;appearance:none;background:#334155;border-radius:2px;outline:none}
.replay-range::-webkit-slider-thumb{-webkit-appearance:none;width:11px;height:11px;border-radius:50%;background:#36d5bc;cursor:pointer;box-shadow:0 0 0 3px #36d5bc33}
.replay-range::-moz-range-thumb{width:11px;height:11px;border:0;border-radius:50%;background:#36d5bc;cursor:pointer}
.replay-range:disabled{opacity:.4}
.replay-empty{margin:0;padding:0 14px 12px;font-size:10px;color:#64748b;line-height:1.6}
@media(max-width:1150px){.replay-side{width:160px}}
@media(max-width:760px){.replay-body{flex-direction:column}.replay-side{width:auto;flex-direction:row;flex-wrap:wrap}.replay-plants{flex:1 1 100%}}
</style>
