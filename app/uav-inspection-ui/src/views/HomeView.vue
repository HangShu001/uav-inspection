<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { account, loadAccount, signOut } from '../stores/auth'
import AccountDialog from '../components/common/AccountDialog.vue'
import { moduleThemes, type ModuleThemeKey } from '../config/moduleThemes'
import { plateApi } from '../api1/plate'
import {
  Antenna,
  Zap,
  Home,
  Building2,
  Bug,
  TreePine,
  ArrowUpDown,
  Maximize,
  Camera,
  LineChart,
  Users,
  Car,
  HardDriveUpload, UserRound, LogIn, UserPlus, LogOut, Film, Play,
} from 'lucide-vue-next'

const router = useRouter(), currentRoute = useRoute()
const accountMode = ref<'login'|'register'>('login'), accountOpen = ref(false), accountError = ref(''), signingOut = ref(false), pendingPath = ref('')
function openAccount(mode:'login'|'register'){accountMode.value=mode;accountOpen.value=true;accountError.value=''}
function safeDestination(value:unknown){return typeof value==='string' && value.startsWith('/') && !value.startsWith('//') && value!=='/' && router.resolve(value).matched.length ? value : ''}
function closeAccount(){accountOpen.value=false;pendingPath.value='';if(currentRoute.query.login)void router.replace({path:'/'})}
async function accountSuccess(){accountOpen.value=false;const path=pendingPath.value || safeDestination(currentRoute.query.redirect);pendingPath.value='';if(path)await router.push(path);else if(currentRoute.query.login)await router.replace({path:'/'})}
async function logout(){signingOut.value=true;accountError.value='';try{await signOut()}catch(reason){accountError.value=reason instanceof Error?reason.message:'退出失败，请重试'}finally{signingOut.value=false}}
function checkLoginQuery(){if(!account.authEnabled)return;if(currentRoute.query.login==='1'){pendingPath.value=safeDestination(currentRoute.query.redirect);openAccount('login')}}
watch(()=>currentRoute.query.login,checkLoginQuery)
// 先取账号策略再判 URL：挂进平台时 authEnabled=false，此时不该弹登录门
onMounted(async()=>{try{await loadAccount()}catch(reason){accountError.value=reason instanceof Error?reason.message:'账号服务暂不可用'}checkLoginQuery()})
const greeting = computed(()=>account.user?`欢迎回来，${account.user.username}`:'欢迎使用巡检平台')
const accountHint = computed(()=>account.user||!account.authEnabled?'选择下方业务模块，开始本次作业。':'登录或注册账号，进入巡检业务工作台。')

// 首页主入口：巡检过程回放。批次信息取不到时只显示静态说明，不阻塞首页。
const lastRun = ref<{ start: string; fsm: string; cars: number } | null>(null)
const lastRunText = computed(() => lastRun.value
  ? `${lastRun.value.start} 起 · ${lastRun.value.fsm} · ${lastRun.value.cars} 辆车受检`
  : '上一轮自主巡检的录屏、阶段时间轴与任务结果')
onMounted(async () => {
  try {
    const res = await plateApi.getAcceptance()
    const data = res.data
    if (data?.available) lastRun.value = { start: data.batch.start, fsm: data.batch.fsm, cars: data.vehicles?.length ?? 0 }
  } catch { /* 回放批次缺失不影响首页其它模块 */ }
})

const modules = [
  {
    title: '基础设施巡检',
    accent: 'bg-blue-600',
    items: [
      {
        name: '通信基站巡检',
        path: '/telecom',
        theme: 'telecom',
        icon: Antenna,
        desc: ['部件识别', '隐患排查'],
      },
      {
        name: '杆路线路巡检',
        path: '/power',
        theme: 'power',
        icon: Zap,
        desc: ['绝缘破损', '断股检测'],
      },
      {
        name: '建筑屋顶巡检',
        path: '/roof',
        theme: 'roof',
        icon: Home,
        desc: ['防水脱层', '异物检测'],
      },
      {
        name: '建筑外墙巡检',
        path: '/wall',
        theme: 'wall',
        icon: Building2,
        desc: ['裂缝标注', '渗水识别'],
      },
    ],
  },
  {
    title: '农林植保业务',
    accent: 'bg-emerald-500',
    items: [
      {
        name: '病虫害巡检',
        path: '/pest',
        theme: 'pest',
        icon: Bug,
        desc: ['智能监测', '自动告警'],
      },
      {
        name: '乔木修剪检测',
        path: '/pruning',
        theme: 'pruning',
        icon: TreePine,
        desc: ['修剪识别', '状态分析'],
      },
      {
        name: '乔木高度测量',
        path: '/height',
        theme: 'height',
        icon: ArrowUpDown,
        desc: ['点云数据', '精度测算'],
      },
      {
        name: '绿化面积测量',
        path: '/area',
        theme: 'area',
        icon: Maximize,
        desc: ['灌木草坪', '面积统计'],
      },
    ],
  },
  {
    title: '数字园区治理',
    accent: 'bg-purple-500',
    items: [
      {
        name: '数字玫瑰园',
        path: '/rose-digital',
        theme: 'roseDigital',
        icon: Camera,
        desc: ['全息要素', '数字档案'],
      },
      {
        name: '玫瑰花产量预测',
        path: '/rose-yield',
        theme: 'roseYield',
        icon: LineChart,
        desc: ['长序特征', '趋势分析'],
      },
      {
        name: '热力客流监测',
        path: '/heatmap-flow',
        theme: 'roseFlow',
        icon: Users,
        desc: ['人员分布', '聚集预警'],
      },
      {
        name: '粉黛花三维漫游',
        path: '/fendai-flower',
        theme: 'roseDigital',
        icon: Camera,
        desc: ['高斯模型', '第一人称漫游'],
      },
      {
        name: '无人机车牌巡检',
        path: '/plate?view=mission',
        theme: 'plate',
        icon: Car,
        desc: ['车牌识别', '违停判定'],
      },
    ],
  },
  {
    title: '演示素材管理',
    accent: 'bg-slate-600',
    items: [
      {
        name: '素材上传中心',
        path: '/assets',
        theme: 'roseDigital',
        icon: HardDriveUpload,
        desc: ['视频灌入', '模型上传'],
      },
    ],
  },
] as const satisfies ReadonlyArray<{
  title: string
  accent: string
  items: ReadonlyArray<{
    name: string
    path: string
    theme: ModuleThemeKey
    icon: unknown
    desc: readonly [string, string]
  }>
}>

const handleNavigation = async (path: string) => {
  accountError.value=''
  try {
    await loadAccount()
    // 无账号体系的部署（挂进平台时）直接进模块，不弹登录
    if(account.authEnabled && !account.user){pendingPath.value=path;openAccount('login');return}
    await router.push(path)
  } catch(reason) { accountError.value=reason instanceof Error?reason.message:'暂时无法进入模块，请稍后重试。' }
}
</script>

<template>
  <div class="mobile-page min-h-screen bg-[#f3f4f6] flex flex-col font-sans">
    <header class="w-full bg-gradient-to-r from-blue-700 to-indigo-800 shadow-md">
      <div class="mx-auto flex min-h-20 max-w-[1500px] flex-col items-start justify-center gap-2 px-4 py-4 sm:h-20 sm:flex-row sm:items-center sm:justify-between sm:px-8 sm:py-0">
        <h1 class="text-xl font-bold tracking-wide text-white sm:text-3xl sm:tracking-widest">低空智能巡检与决策平台</h1>
        <div class="flex items-center gap-6 text-sm font-medium text-white/90 sm:text-base">
          <span class="flex items-center gap-2"><span class="w-2.5 h-2.5 bg-emerald-400 rounded-full animate-pulse"></span> 边缘算力在线</span>
        </div>
      </div>
    </header>

    <main class="mx-auto w-full max-w-[1500px] flex-1 px-4 py-4 sm:px-8 sm:py-8">
      <section class="home-account" aria-label="平台账号">
        <div class="home-account-main"><div class="home-account-avatar"><UserRound :size="25"/></div><div class="home-account-copy"><h2>{{ greeting }}</h2><p>{{ accountHint }}</p></div><div class="home-account-actions"><template v-if="account.authEnabled"><template v-if="!account.user"><button class="home-login" @click="openAccount('login')"><LogIn :size="15"/>登录</button><button class="home-register" @click="openAccount('register')"><UserPlus :size="15"/>注册</button></template><button v-else class="home-register" :disabled="signingOut" @click="logout"><LogOut :size="15"/>{{ signingOut ? '正在退出…' : '退出登录' }}</button></template><span v-else class="home-guest">平台访客</span></div></div>
        <div class="home-account-hint">默认账号：<strong>admin</strong><span></span>默认密码：<strong>admin123</strong></div>
        <p v-if="accountError" class="home-account-error" role="alert">{{ accountError }}</p>
      </section>
      <section class="home-replay">
        <div class="home-replay-icon"><Film :size="22" /></div>
        <div class="home-replay-copy">
          <h2>巡检过程</h2>
          <p>{{ lastRunText }}</p>
        </div>
        <button class="home-replay-go" @click="router.push('/plate?view=mission')"><Play :size="14" />四路同步查看</button>
      </section>

      <div class="grid grid-cols-1 gap-4 lg:grid-cols-3 lg:gap-7">
        <section v-for="group in modules" :key="group.title" class="flex min-w-0 flex-col rounded-lg border border-slate-200 bg-white p-4 shadow-sm sm:p-7">
          <div class="mb-4 flex items-center gap-3 sm:mb-7">
            <div class="h-7 w-1.5 rounded-full sm:h-8 sm:w-2" :class="group.accent"></div>
            <h2 class="text-xl font-bold text-slate-800 sm:text-2xl">{{ group.title }}</h2>
          </div>

          <div class="flex flex-col gap-3 sm:gap-5">
            <button
              v-for="item in group.items"
              :key="item.name"
              @click="handleNavigation(item.path)"
              class="group flex min-h-28 w-full items-center rounded-lg border p-3 text-left shadow-[0_8px_24px_rgba(15,23,42,0.05)] transition-all hover:-translate-y-1 hover:shadow-lg sm:h-36 sm:p-5"
              :class="[moduleThemes[item.theme].card, moduleThemes[item.theme].hover]"
            >
              <div class="flex w-20 shrink-0 flex-col items-center justify-center sm:w-28">
                <div class="mb-2 flex h-14 w-14 items-center justify-center rounded-lg bg-white shadow-sm ring-1 sm:mb-3 sm:h-16 sm:w-16" :class="moduleThemes[item.theme].ring">
                  <component :is="item.icon" :size="42" stroke-width="1.6" class="transition-transform group-hover:scale-110" :class="moduleThemes[item.theme].icon" />
                </div>
                <span class="text-xs font-semibold text-slate-500 text-center leading-snug">{{ item.desc[0] }}<br>{{ item.desc[1] }}</span>
              </div>
              <div class="flex-1 flex flex-col justify-center items-center gap-2 min-w-0">
                <span class="text-center text-base font-extrabold tracking-wide transition-colors sm:text-xl" :class="moduleThemes[item.theme].text">{{ item.name }}</span>
                <span class="rounded-full border px-3 py-1 text-xs font-semibold" :class="moduleThemes[item.theme].badge">进入模块</span>
              </div>
            </button>
          </div>
        </section>
      </div>
    </main>
    <AccountDialog v-if="accountOpen" :mode="accountMode" @mode="accountMode=$event" @close="closeAccount" @success="accountSuccess" />
  </div>
</template>


<style scoped>
.home-replay{display:flex;align-items:center;gap:16px;margin-bottom:20px;padding:16px 20px;border:1px solid #e2e8f0;border-radius:10px;background:linear-gradient(96deg,#f7faff,#fff 58%);box-shadow:0 8px 24px -20px #0f172a45}
.home-replay-icon{display:grid;place-items:center;height:44px;width:44px;border-radius:10px;background:#eef2ff;border:1px solid #e0e7ff;color:#4f46e5;flex-shrink:0}
.home-replay-copy{flex:1;min-width:0}
.home-replay-copy h2{font-size:16px;font-weight:700;color:#1e293b}
.home-replay-copy p{margin-top:4px;font-size:12px;color:#94a3b8;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.home-replay-go{display:inline-flex;align-items:center;gap:6px;padding:10px 20px;border:1px solid transparent;border-radius:8px;background:#4f46e5;color:#fff;font-size:13px;font-weight:600;white-space:nowrap;box-shadow:0 6px 16px -10px #4f46e5}
.home-replay-go:hover{background:#4338ca}
@media(max-width:600px){.home-replay{flex-wrap:wrap;gap:12px;padding:14px}.home-replay-copy{flex:1 1 100%;order:3}.home-replay-go{width:100%;justify-content:center}}

.home-account{background:white;border:1px solid #e2e8f0;border-radius:10px;margin-bottom:25px;box-shadow:0 5px 20px -18px #0f172a40;padding:20px 24px;color:#475569}.home-account-main{display:flex;align-items:center;gap:14px}.home-account-avatar{height:48px;width:48px;display:grid;place-items:center;border:1px solid #dbeafe;background:linear-gradient(140deg,#eff6ff,#eef2ff);color:#4169d4;border-radius:12px;flex-shrink:0}.home-account-copy h2{font-size:16px;color:#1e293b;font-weight:650}.home-account-copy p{font-size:12px;color:#94a3b8;margin-top:6px}.home-account-actions{margin-left:auto;display:flex;gap:9px;align-items:center}.home-account-actions button{display:flex;align-items:center;justify-content:center;gap:6px;padding:9px 18px;font-size:12px;font-weight:600;border:1px solid transparent;border-radius:6px;white-space:nowrap}.home-login{background:#315bd2;color:white;box-shadow:0 3px 8px #315bd21a}.home-login:hover{background:#254bb7}.home-account-actions button.home-register{background:white;color:#526785;border-color:#dce3ef}.home-account-actions button.home-register:hover{background:#f8fafc}.home-account-actions button:disabled{opacity:.5;cursor:not-allowed}.home-account-hint{display:flex;align-items:center;gap:6px;font-size:12px;color:#64748b;border-top:1px solid #f1f5f9;margin-top:16px;padding-top:13px}.home-account-hint strong{font-family:ui-monospace,monospace;color:#334155;font-weight:500;font-size:13px}.home-account-hint>span{height:10px;width:1px;background:#e2e8f0;margin:0 9px}.home-account-error{font-size:12px;color:#be123c;margin-top:12px;line-height:1.7}.home-guest{display:inline-flex;align-items:center;gap:6px;padding:7px 14px;font-size:12px;font-weight:600;color:#526785;background:#f8fafc;border:1px solid #dce3ef;border-radius:6px}@media(max-width:600px){.home-account{padding:17px;margin-bottom:17px}.home-account-main{flex-wrap:wrap;gap:12px}.home-account-avatar{height:42px;width:42px}.home-account-copy h2{font-size:14px}.home-account-copy p{font-size:11px}.home-account-actions{margin-left:0;width:100%;padding-top:2px}.home-account-actions button{flex:1}.home-account-hint{gap:3px;font-size:10px}.home-account-hint strong{font-size:11px}.home-account-hint>span{margin:0 5px}}
</style>
