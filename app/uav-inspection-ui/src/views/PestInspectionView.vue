<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ArrowLeft, Maximize2, RotateCcw } from 'lucide-vue-next'
import { webPath } from '../utils/webroot'

const sceneUrl = webPath('/maize/index.html')
const frame = ref<HTMLIFrameElement | null>(null)
const workspace = ref<HTMLElement | null>(null)
const state = ref<'loading' | 'ready' | 'error'>('loading')
const errorMessage = ref('')
const revision = ref(0)
let timeout: ReturnType<typeof setTimeout> | undefined

function stopTimeout() { clearTimeout(timeout) }
function fail(message: string) {
  stopTimeout()
  state.value = 'error'
  errorMessage.value = message
}
function startTimeout() {
  stopTimeout()
  timeout = setTimeout(() => fail('场景加载时间较长，请检查网络后重试，或在新窗口打开。'), 120_000)
}
function receiveStatus(event: MessageEvent) {
  if (event.origin !== window.location.origin || event.source !== frame.value?.contentWindow) return
  if (event.data?.type === 'maize-inspection:ready') {
    stopTimeout()
    state.value = 'ready'
  } else if (event.data?.type === 'maize-inspection:error') {
    fail('三维场景未能启动，请使用新版 Chrome 或 Edge，并开启图形加速后重试。')
  }
}
function frameLoaded() {
  // A proxy's HTML fallback also fires load; it is not a successful scene load.
  if (!frame.value?.contentDocument?.getElementById('loader')) {
    fail('玉米巡检资源缺失，请确认部署包含 maize 目录的全部文件。')
  }
}
function retry() {
  state.value = 'loading'
  errorMessage.value = ''
  revision.value++
  startTimeout()
}
async function fullscreen() {
  try {
    if (document.fullscreenElement) await document.exitFullscreen()
    else await workspace.value?.requestFullscreen()
  } catch { /* The workbench remains usable when fullscreen is unavailable. */ }
}
onMounted(() => { window.addEventListener('message', receiveStatus); startTimeout() })
onBeforeUnmount(() => { window.removeEventListener('message', receiveStatus); stopTimeout() })
</script>

<template>
  <section ref="workspace" class="maize-workspace">
    <nav class="platform-bar" aria-label="巡检平台导航">
      <RouterLink to="/" class="back-link"><ArrowLeft :size="16" />返回平台</RouterLink>
      <span class="module-name">病虫害巡检 <span>· 玉米单株与密植</span></span>
      <div class="platform-actions">
        <span class="replay-label">仿真记录回放</span>
        <button type="button" @click="fullscreen"><Maximize2 :size="15" /><span>全屏</span></button>
      </div>
    </nav>
    <div class="scene-container" :aria-busy="state === 'loading'">
      <iframe
        :key="revision"
        ref="frame"
        :src="sceneUrl"
        title="玉米病害巡检：单株与密植交互回放"
        allow="fullscreen"
        @load="frameLoaded"
        @error="fail('玉米巡检页面加载失败，请检查网络后重试。')"
      ></iframe>
      <div v-if="state !== 'ready'" class="scene-status" role="status" aria-live="polite">
        <template v-if="state === 'loading'">
          <span class="spinner" aria-hidden="true"></span>
          <strong>正在准备玉米巡检场景</strong>
          <p>首次加载约 71 MB 的图片与三维素材，请稍候。</p>
        </template>
        <template v-else>
          <strong>玉米巡检暂未就绪</strong>
          <p>{{ errorMessage }}</p>
          <button type="button" @click="retry"><RotateCcw :size="15" />重新加载</button>
        </template>
        <a :href="sceneUrl" target="_blank" rel="noopener">在新窗口打开玉米巡检</a>
      </div>
    </div>
  </section>
</template>

<style scoped>
.maize-workspace { height: 100vh; height: 100dvh; min-height: 400px; display: flex; flex-direction: column; background: #f3f6f1; }
.platform-bar { flex: none; min-height: 48px; display: flex; align-items: center; gap: 20px; padding: 8px 24px; border-bottom: 1px solid #dfe7dc; background: #fff; color: #223d35; font-size: 13px; }
.back-link, .platform-actions button, .scene-status button { display: inline-flex; align-items: center; justify-content: center; gap: 7px; }
.back-link { color: #247b58; text-decoration: none; white-space: nowrap; }
.module-name { font-weight: 600; }
.module-name span { color: #75877c; font-weight: 400; }
.platform-actions { display: flex; align-items: center; gap: 18px; margin-left: auto; }
.replay-label { color: #75877c; font-size: 12px; }
.platform-actions button { padding: 5px 8px; border: 1px solid #dfe7dc; border-radius: 5px; cursor: pointer; }
.scene-container { position: relative; flex: 1; min-height: 0; }
iframe { display: block; width: 100%; height: 100%; border: 0; }
.scene-status { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 18px; padding: 24px; background: #f3f6f1; color: #223d35; text-align: center; }
.scene-status strong { font-size: 18px; font-weight: 600; }
.scene-status p { max-width: 500px; color: #75877c; font-size: 13px; line-height: 1.8; }
.scene-status a { color: #247b58; font-size: 12px; text-decoration: underline; }
.scene-status button { padding: 10px 18px; border-radius: 7px; background: #247b58; color: white; cursor: pointer; }
.spinner { width: 34px; height: 34px; border: 2px solid #dce8d2; border-top-color: #247b58; border-radius: 50%; animation: spin 1s linear infinite; }
button:focus-visible, a:focus-visible { outline: 3px solid #79b59b; outline-offset: 3px; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 640px) {
  .platform-bar { padding: 8px 12px; gap: 12px; font-size: 12px; }
  .module-name span, .replay-label, .platform-actions button span { display: none; }
}
</style>
