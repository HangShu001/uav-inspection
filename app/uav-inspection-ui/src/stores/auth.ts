import { reactive } from 'vue'
import { webPath } from '../utils/webroot'

export interface AccountUser { id: number; username: string }
// authEnabled 由后端 /api/v1/auth/policy 给：挂进不带账号体系的上游平台时是 false，
// 此时不弹登录门、路由守卫直接放行，页面表现与平台其它模块一致。
export const account = reactive<{user: AccountUser | null; ready: boolean; authEnabled: boolean}>({user:null,ready:false,authEnabled:true})
let pendingSession: Promise<void> | null = null
let revision = 0
let policyLoaded = false

async function authRequest(path: string, data?: {username:string;password:string}) {
  let response: Response
  try { response=await fetch(webPath(`/api/v1/auth/${path}`),{method:path==='me'?'GET':'POST',credentials:'same-origin',cache:'no-store',headers:data?{'Content-Type':'application/json'}:undefined,body:data?JSON.stringify(data):undefined}) }
  catch { throw new Error('暂时无法连接账号服务，请稍后重试。') }
  let payload
  try { payload=await response.json() } catch { throw new Error('账号服务暂不可用，请稍后重试。') }
  if(!response.ok){const detail=typeof payload.detail==='string'?payload.detail:'请检查用户名和密码格式';const error=new Error(detail);Object.assign(error,{status:response.status});throw error}
  return payload
}

/** 只在首次进站问一次；取不到就按「需要登录」兜底，避免鉴权因网络抖动被静默关掉。 */
async function loadAuthPolicy() {
  if (policyLoaded) return
  try {
    const response = await fetch(webPath('/api/v1/auth/policy'), { credentials: 'same-origin', cache: 'no-store' })
    if (!response.ok) return
    const payload = await response.json()
    account.authEnabled = payload?.data?.auth_enabled !== false
    policyLoaded = true
  } catch { /* 保持默认 true */ }
}

export function loadAccount() {
  if(pendingSession)return pendingSession
  const requestRevision=revision
  pendingSession=(async()=>{
    try {
      await loadAuthPolicy()
      if(!account.authEnabled){if(requestRevision===revision)account.user=null;return}
      const result=await authRequest('me');if(requestRevision===revision)account.user=result.data
    } catch(error) {
      if(requestRevision!==revision)return
      if((error as {status?:number}).status!==401)throw error
      account.user=null
    } finally { account.ready=true }
  })().finally(()=>{pendingSession=null})
  return pendingSession
}
export async function signIn(username:string,password:string,register=false){const requestRevision=++revision;const result=await authRequest(register?'register':'login',{username,password});if(requestRevision===revision){account.user=result.data;account.ready=true}}
export async function signOut(){const requestRevision=++revision;await authRequest('logout');if(requestRevision===revision){account.user=null;account.ready=true}}
