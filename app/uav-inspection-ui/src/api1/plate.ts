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
  }
  summary: Array<{ label: string; value: string; note: string }>
  vehicles: AcceptanceVehicle[]
  violations: AcceptanceViolation[]
  reruns: Array<{ 启动: string; 墙钟_s: number; 建图: number }>
  retry: { 轮次: number; 触发: string; 补拍: string; 结果: string }
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
}
