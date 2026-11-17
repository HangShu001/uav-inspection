<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import WallLiveDetection from './WallLiveDetection.vue'
import WallLocationMap from './WallLocationMap.vue'
import { request } from '../../utils/request'

interface Device { id: string; name: string; url: string }
interface Telemetry { latitude: number | null; longitude: number | null; elevation: number | null; horizontal_speed: number | null; stale: boolean }
const devices = ref<Device[]>([])
const deviceId = ref('')
const video = ref<HTMLVideoElement | null>(null)
const status = ref('选择要查看的无人机。')
const connected = ref(false)
const running = ref(false)
const position = ref<Telemetry | null>(null)
const point = ref<{ latitude: number; longitude: number } | null>(null)
let peer: RTCPeerConnection | null = null
let session: string | null = null
let retry: number | undefined
let poll: number | undefined
let generation = 0

async function refreshTelemetry(id: string, active: number) {
  try {
    const result = await request<Telemetry | null>({ url: '/wall/workflow/live/' + id + '/telemetry' })
    if (active !== generation) return
    position.value = result.data
    const t = result.data
    point.value = t && !t.stale && t.latitude !== null && t.longitude !== null ? { latitude: t.latitude, longitude: t.longitude } : null
  } catch {
    if (active === generation) { position.value = null; point.value = null }
  }
}

function closePeer() {
  if (peer) {
    peer.onconnectionstatechange = null
    peer.close()
    peer = null
  }
  if (video.value) video.value.srcObject = null
  if (session) {
    void fetch(session, { method: 'DELETE', keepalive: true }).catch(() => {})
    session = null
  }
}

function stop() {
  generation++
  running.value = false
  connected.value = false
  clearInterval(poll)
  clearTimeout(retry)
  closePeer()
  position.value = null
  point.value = null
  status.value = '直播已断开。'
}
function gathered(pc: RTCPeerConnection) {
  if (pc.iceGatheringState === 'complete') return Promise.resolve()
  return new Promise<void>(resolve => {
    const finish = () => {
      pc.removeEventListener('icegatheringstatechange', change)
      clearTimeout(timer)
      resolve()
    }
    const change = () => { if (pc.iceGatheringState === 'complete') finish() }
    const timer = window.setTimeout(finish, 2500)
    pc.addEventListener('icegatheringstatechange', change)
  })
}

async function play(device: Device, active: number) {
  if (active !== generation) return
  status.value = '正在连接直播画面…'
  closePeer()
  const reconnect = () => {
    if (active !== generation) return
    connected.value = false
    status.value = '暂时没有直播画面，正在重连。'
    clearTimeout(retry)
    retry = window.setTimeout(() => { void play(device, active) }, 3500)
  }
  try {
    const pc = new RTCPeerConnection()
    peer = pc
    pc.addTransceiver('video', { direction: 'recvonly' })
    pc.ontrack = event => {
      if (active === generation && video.value) video.value.srcObject = new MediaStream([event.track])
    }
    pc.onconnectionstatechange = () => {
      if (peer !== pc || active !== generation) return
      if (pc.connectionState === 'connected') {
        clearTimeout(retry)
        connected.value = true
        status.value = '直播中'
      }
      if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') reconnect()
    }
    await pc.setLocalDescription(await pc.createOffer())
    await gathered(pc)
    if (active !== generation || !pc.localDescription) return
    const response = await fetch(device.url, { method: 'POST', body: pc.localDescription.sdp,
      headers: { 'Content-Type': 'application/sdp' }, signal: AbortSignal.timeout(10000) })
    if (!response.ok) throw new Error()
    const location = response.headers.get('Location')
    if (active !== generation) {
      if (location) void fetch(location, { method: 'DELETE' }).catch(() => {})
      return
    }
    session = location
    await pc.setRemoteDescription({ type: 'answer', sdp: await response.text() })
    retry = window.setTimeout(() => { if (pc.connectionState !== 'connected') reconnect() }, 8000)
  } catch {
    reconnect()
  }
}

function start() {
  const device = devices.value.find(item => item.id === deviceId.value)
  if (!device) return
  stop()
  running.value = true
  const active = generation
  void play(device, active)
  void refreshTelemetry(device.id, active)
  poll = window.setInterval(() => { void refreshTelemetry(device.id, active) }, 1000)
}

onMounted(async () => {
  try {
    const result = await request<Device[]>({ url: '/wall/workflow/live/devices' })
    devices.value = result.data
    deviceId.value = result.data[0]?.id || ''
    if (!deviceId.value) status.value = '暂无已配置的直播设备。'
  } catch {
    status.value = '暂时无法读取设备列表。'
  }
})
onUnmounted(stop)
</script>

<template>
  <section class="rounded-lg border border-slate-200 bg-white p-4">
    <div class="flex flex-wrap items-end gap-2">
      <label class="text-sm font-medium">直播设备
        <select v-model="deviceId" :disabled="running || !devices.length" class="mt-1 block rounded border border-slate-300 px-3 py-2">
          <option value="" disabled>请选择设备</option><option v-for="item in devices" :key="item.id" :value="item.id">{{ item.name }}</option>
        </select>
      </label>
      <button v-if="running" class="rounded border border-slate-300 px-3 py-2 text-sm" @click="stop">断开直播</button>
      <button v-else :disabled="!deviceId" class="rounded bg-teal-700 px-3 py-2 text-sm text-white disabled:opacity-50" @click="start">连接直播</button>
    </div>
    <p class="mt-3 text-sm" role="status">{{ status }}</p>
    <div v-show="running" class="mt-3 grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(260px,1fr)]">
      <div>
        <div class="relative">
          <video ref="video" autoplay muted playsinline controls class="aspect-video w-full rounded bg-slate-950 object-contain" />
        </div>
        <WallLiveDetection v-if="running" :video="video" :device-id="deviceId" :connected="connected" />
      </div>
      <div>
        <h3 class="font-semibold">飞行数据</h3>
        <p v-if="!position || position.stale" class="mt-2 text-sm text-slate-600">{{ position?.stale ? '飞行数据暂未更新。' : '飞行数据未接入。' }}</p>
        <dl v-else class="mt-2 space-y-2 text-sm">
          <div v-if="point"><dt>拍摄位置 · 经纬度</dt><dd class="font-mono">{{ point.longitude.toFixed(6) }}, {{ point.latitude.toFixed(6) }}</dd></div>
          <div><dt>相对起飞点高度</dt><dd>{{ position.elevation === null ? '—' : position.elevation.toFixed(1) + ' 米' }}</dd></div>
          <div><dt>飞行速度</dt><dd>{{ position.horizontal_speed === null ? '—' : position.horizontal_speed.toFixed(1) + ' 米/秒' }}</dd></div>
        </dl>
        <div v-if="point" class="mt-3 overflow-hidden rounded"><WallLocationMap :points="[]" :current="point" compact /></div>
      </div>
    </div>
  </section>
</template>
