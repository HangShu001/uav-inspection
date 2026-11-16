import { http, request } from '../utils/request'

export interface PlateDetection {
  class: number
  name: string
  color: string
  color_cn: string
  bbox: [number, number, number, number]
  quad: [number, number][]
  conf: number
  text: string | null
  text_score: number | null
}

export interface RecognizerStatus {
  available: boolean
  backend: string | null
  model: string | null
  mode: string
  charset_size: number
  note: string
}

export interface PlateDetectResult {
  detections: PlateDetection[]
  count: number
  stats: Record<string, number>
  plates: string[]
  recognizer: RecognizerStatus
  annotated_image: string
  image_size: [number, number]
  inference_ms: number
}

export interface PlateInfoResult {
  system: {
    cuda_available: boolean
    device: string
  }
  model: {
    name: string
    classes: string[]
    task: string
  }
  recognizer: RecognizerStatus
  config: {
    confidence: number
    iou: number
    max_plates: number
  }
  capabilities: {
    single_frame_detection: boolean
    oriented_boxes: boolean
    plate_text: boolean
  }
}

export interface PlateVideoHit {
  text: string
  count: number
  best_conf: number
  color: string
  color_cn: string
  first_seen_s: number
}

export interface PlateVideoResult {
  fps: number
  total_frames: number
  sampled_frames: number
  hits: number
  truncated: boolean
  plates: PlateVideoHit[]
  unique_count: number
  color_stats: Record<string, number>
  frames: Array<{
    frame: number
    second: number
    plates: Array<{ bbox: number[]; conf: number; text: string | null; color: string }>
  }>
  best_frame: { frame: number; second: number; image: string; plates: unknown[] } | null
  recognizer: RecognizerStatus
  limits: { max_sampled_frames: number; max_seconds: number; sample_step: number }
}

export interface AcceptanceVehicle {
  car: string
  real_car: string
  plate: string
  /** spawn 真值表里的车牌，与 plate 逐字比对后才算「认定」 */
  plate_truth?: string
  match?: boolean
  /** 真值表里的停放形态：normal / encroach / angled */
  state?: string
  confidence: number
  distance_m: number
  leg: string
  note: string
  card: string | null
  card_url: string | null
}

export interface AcceptanceViolation {
  car: string
  real_car: string
  slot: string
  lateral_m: number
  longitudinal_m: number
  margin_m: number
  shape_error_m: number
  verdict: string
  truth: string
}

export interface AcceptanceData {
  available: boolean
  batch: {
    start: string
    end: string
    fsm: string
    exit_code: number
    batch_dir: string
    mission_id?: string
    wall_clock_s?: number | null
  }
  summary: Array<{ label: string; value: string; note: string }>
  vehicles: AcceptanceVehicle[]
  violations: AcceptanceViolation[]
  /** 违停余量来自哪一轮复算（本轮只做检测/识别/覆盖时不重算几何） */
  geometry?: { batch: string; start: string; note: string }
  reruns?: Array<{ 启动: string; 墙钟_s: number; 建图: number }>
  retry: { 轮次: number; 触发: string; 补拍: string; 结果: string }
}

export interface ReplayPhase {
  key: string
  label: string
  kind: string
  t0: number
  t1: number
  seconds: number
  detail: string
  cover: string
}

export interface ReplayEvent {
  t: number
  kind: string
  text: string
}

export interface ReplayData {
  available?: boolean
  mission: {
    run: string
    id: string
    started_at: string
    scenario: string
    platform: string
    barrier: string
  }
  kpi: {
    final: string
    note: string
    c_cap: number
    n_cars: number
    n_captured: number
    missing: string[]
    inspect_round: number
    rounds: Array<{
      ok: boolean
      rc: number
      run_dir: string
      cars: number
      captured: number
      new: number
      reason: string
    }>
  }
  budget: { wall_clock_s: number; elapsed_s: number; budget_s: number }
  video: {
    src: string
    poster: string
    seconds: number
    frames: number
    fps: number
    size: string
    offset_s: number
    note: string
  }
  phases: ReplayPhase[]
  events: ReplayEvent[]
}

export interface CoverageData {
  available?: boolean
  source: {
    map_dir: string
    frames_used: number | null
    cell_m: number
    grid: number[]
    rect: number[]
    note: string
  }
  area: { site_cells: number; car_cells: number; observable_cells: number }
  coverage: Array<{ min_frames: number; cells: number; ratio: number }>
  depth: {
    frames_p50: number
    frames_p95: number
    dist_p50: number
    dist_p95: number
    pts_p50: number
  }
  rows: Array<{
    label: string
    x: number
    cells: number
    ge1: number
    ge3: number
    median_frames: number
  }>
  slots: Array<{
    name: string
    x: number
    y: number
    frames: number
    points: number
    min_dist: number
  }>
  image: string
  /** RViz 全流程录屏：点云 + 占据栅格的深度融合过程（2026-11-16 加） */
  rviz?: {
    src: string
    poster?: string
    seconds: number
    width: number
    height: number
    fps: number
    run: string
    note: string
    /** 录屏起点相对任务起跑的秒数；>0 表示前段（通常是 SURVEY）不在画面内 */
    offset_s?: number
    /** 与覆盖质量同批次时为 true；不同批次前端要显式提示 */
    same_batch: boolean
  }
}

export const plateApi = {
  getHealth() {
    return request<{
      status: string
      service_status: string
      detector_loaded: boolean
      recognizer_available: boolean
      acceptance_available: boolean
    }>({ url: '/plate/health', method: 'GET' })
  },
  getInfo() {
    return request<PlateInfoResult>({ url: '/plate/info', method: 'GET' })
  },
  getConfig() {
    return request<{ confidence: number; iou: number; max_plates: number }>({
      url: '/plate/config',
      method: 'GET',
    })
  },
  updateConfig(payload: { confidence?: number; iou?: number; max_plates?: number }) {
    return request<{ confidence: number; iou: number; max_plates: number }>({
      url: '/plate/config',
      method: 'POST',
      data: payload,
    })
  },
  detectUpload(file: File, conf?: number, recognize = true) {
    const form = new FormData()
    form.append('image', file)
    const query = new URLSearchParams()
    if (conf !== undefined) query.set('conf', String(conf))
    query.set('recognize', String(recognize))
    return http.postForm<PlateDetectResult>(`/plate/detect/upload?${query.toString()}`, form, {
      timeout: 30000,
    })
  },
  detectVideo(file: File, options: { sampleStep?: number; conf?: number; recognize?: boolean } = {}) {
    const form = new FormData()
    form.append('video', file)
    const query = new URLSearchParams()
    query.set('sample_step', String(options.sampleStep ?? 15))
    if (options.conf !== undefined) query.set('conf', String(options.conf))
    query.set('recognize', String(options.recognize ?? true))
    return http.postForm<PlateVideoResult>(`/plate/detect/video?${query.toString()}`, form, {
      timeout: 120000,
    })
  },
  getAcceptance() {
    return request<AcceptanceData>({ url: '/plate/acceptance', method: 'GET' })
  },
  getReplay() {
    return request<ReplayData>({ url: '/plate/replay', method: 'GET' })
  },
  getCoverage() {
    return request<CoverageData>({ url: '/plate/coverage', method: 'GET' })
  },
}
