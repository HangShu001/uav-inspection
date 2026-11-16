from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from plateapp.detector import plate_detector
from plateapp.recognizer import plate_recognizer
from deployment_paths import backend_path
from uav_url_prefix import prefixed

router = APIRouter()

# 数据落点遵循平台约定：<数据根>/uav-inspection-backend/<domain>data/。
# 早期版本把 data 放在包目录里，会跟着 source 一起打进镜像层，容器重建（--force-recreate）
# 后运行期写入的 timeline/coverage 全丢，且与 deployment_readiness 的判定口径打架。
DATA_DIR = backend_path('platedata')
ACCEPTANCE_PATH = DATA_DIR / 'acceptance.json'
CARDS_DIR = DATA_DIR / 'cards'

# 过程回放与覆盖质量（2026-11-15 加）。timeline/coverage 是离线脚本产出的 JSON，
# 媒体（回放视频、阶段封面、热力图）走 /api/v1/plate/media 静态挂载。
TIMELINE_PATH = DATA_DIR / 'timeline.json'
COVERAGE_PATH = DATA_DIR / 'coverage.json'
MEDIA_DIR = DATA_DIR / 'media'


def _media_versioned(url: str) -> str:
    """给媒体 URL 追加内容戳，防止换批次后客户端继续播旧文件。

    静态挂载不带 Cache-Control，浏览器对同 URL 的 mp4 会强缓存。实测把 p9 的回放
    换成 p10 后，页面仍显示旧的 21:44（1304 s）而不是新的 20:12（1212 s），
    普通刷新和 F5 都无效，必须硬清缓存。加上 ?v=<mtime> 后 URL 变了，自然重新拉取。
    """
    name = url.rsplit('/', 1)[-1].split('?', 1)[0]
    try:
        return '%s?v=%d' % (url, int((MEDIA_DIR / name).stat().st_mtime))
    except OSError:
        return url

# 视频检测是同步执行的，必须有明确上限，否则一个大文件就能把工作进程占满。
MAX_VIDEO_FRAMES = 40
MAX_VIDEO_SECONDS = 60.0


class PlateDetectRequest(BaseModel):
    image: str
    conf: float | None = None
    iou: float | None = None
    recognize: bool = True


class PlateConfigRequest(BaseModel):
    confidence: float | None = None
    iou: float | None = None
    max_plates: int | None = None


def _load_acceptance() -> dict[str, Any] | None:
    if not ACCEPTANCE_PATH.is_file():
        return None
    try:
        return json.loads(ACCEPTANCE_PATH.read_text(encoding='utf-8'))
    except Exception:
        return None


def _load_json_file(path: Path) -> dict[str, Any] | None:
    """读离线脚本产出的 JSON；坏文件按「没有」处理，不让页面 500。"""
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


@router.get('/health')
async def plate_health() -> dict[str, object]:
    """只报告服务是否在跑，不去加载模型——加模型可能耗时数秒。"""
    status = plate_recognizer.status()
    try:
        available = plate_detector.model is not None
    except Exception:
        available = False
    return {
        'code': 200,
        'message': 'success' if available else '基础服务正常，检测模型尚未加载',
        'data': {
            'status': 'ready' if available else 'idle',
            'service_status': 'running',
            'detector_loaded': available,
            'recognizer_available': status['available'],
            'acceptance_available': ACCEPTANCE_PATH.is_file(),
        },
    }


@router.get('/info')
async def plate_info() -> dict[str, object]:
    try:
        return {'code': 200, 'message': 'success', 'data': plate_detector.get_info()}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get('/config')
async def plate_config() -> dict[str, object]:
    return {'code': 200, 'message': 'success', 'data': plate_detector.get_config()}


@router.post('/config')
async def plate_update_config(payload: PlateConfigRequest) -> dict[str, object]:
    return {
        'code': 200,
        'message': 'success',
        'data': plate_detector.update_config(
            confidence=payload.confidence, iou=payload.iou, max_plates=payload.max_plates),
    }


@router.post('/detect')
async def plate_detect(payload: PlateDetectRequest) -> JSONResponse:
    try:
        result = plate_detector.detect_base64(
            payload.image, conf_threshold=payload.conf,
            iou_threshold=payload.iou, recognize=payload.recognize)
        return JSONResponse({'code': 200, 'message': 'success', 'data': result})
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post('/detect/upload')
async def plate_detect_upload(
    image: UploadFile = File(...),
    conf: float | None = None,
    recognize: bool = True,
) -> JSONResponse:
    """页面直接传文件时用这个，省掉前端转 base64 的开销。"""
    raw = await image.read()
    if not raw:
        raise HTTPException(status_code=400, detail='上传的文件是空的')
    frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=400, detail='无法解码图片，请确认上传的是 JPG/PNG')
    try:
        result = plate_detector.detect(frame, conf_threshold=conf, recognize=recognize)
        return JSONResponse({'code': 200, 'message': 'success', 'data': result})
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post('/detect/video')
async def plate_detect_video(
    video: UploadFile = File(...),
    sample_step: int = 15,
    conf: float | None = None,
    recognize: bool = True,
) -> JSONResponse:
    """按固定间隔抽帧检测，汇总去重后的车牌清单。

    同步执行且有硬上限（MAX_VIDEO_FRAMES / MAX_VIDEO_SECONDS），超出的部分
    直接截断并在响应里说明，避免长视频把工作进程占满。
    """
    suffix = Path(video.filename or 'clip.mp4').suffix or '.mp4'
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            while chunk := await video.read(1024 * 1024):
                tmp.write(chunk)
            temp_path = Path(tmp.name)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f'视频写入失败：{exc}') from exc

    try:
        capture = cv2.VideoCapture(str(temp_path))
        if not capture.isOpened():
            raise HTTPException(status_code=400, detail='无法打开视频，请确认格式是 MP4/AVI/MOV')

        fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        step = max(1, int(sample_step))
        limit_frames = int(min(total_frames or 0, MAX_VIDEO_SECONDS * fps)) or None

        plates: dict[str, dict[str, Any]] = {}
        colors: dict[str, int] = {}
        frames: list[dict[str, Any]] = []
        processed = 0
        best: dict[str, Any] | None = None
        index = 0

        while len(frames) < MAX_VIDEO_FRAMES:
            ok, frame = capture.read()
            if not ok:
                break
            if limit_frames and index >= limit_frames:
                break
            if index % step == 0:
                try:
                    result = plate_detector.detect(frame, conf_threshold=conf, recognize=recognize)
                except FileNotFoundError as exc:
                    raise HTTPException(status_code=503, detail=str(exc)) from exc
                processed += 1
                second = round(index / fps, 2)
                kept = []
                for detection in result['detections']:
                    colors[detection['color']] = colors.get(detection['color'], 0) + 1
                    text = detection['text']
                    if text:
                        record = plates.setdefault(text, {
                            'text': text, 'count': 0, 'best_conf': 0.0,
                            'color': detection['color'], 'color_cn': detection['color_cn'],
                            'first_seen_s': second,
                        })
                        record['count'] += 1
                        if detection['conf'] > record['best_conf']:
                            record['best_conf'] = detection['conf']
                    kept.append({
                        'bbox': detection['bbox'], 'conf': detection['conf'],
                        'text': text, 'color': detection['color'],
                    })
                if kept:
                    frames.append({'frame': index, 'second': second, 'plates': kept})
                    if best is None or len(kept) > len(best['plates']):
                        best = {'frame': index, 'second': second,
                                'image': result['annotated_image'], 'plates': kept}
            index += 1
        capture.release()

        truncated = bool(limit_frames and index >= limit_frames) or len(frames) >= MAX_VIDEO_FRAMES
        return JSONResponse({'code': 200, 'message': 'success', 'data': {
            'fps': round(float(fps), 2),
            'total_frames': total_frames,
            'sampled_frames': processed,
            'hits': len(frames),
            'truncated': truncated,
            'plates': sorted(plates.values(), key=lambda item: (-item['count'], item['text'])),
            'unique_count': len(plates),
            'color_stats': colors,
            'frames': frames[:12],
            'best_frame': best,
            'recognizer': plate_recognizer.status(),
            'limits': {'max_sampled_frames': MAX_VIDEO_FRAMES,
                       'max_seconds': MAX_VIDEO_SECONDS,
                       'sample_step': step},
        }})
    finally:
        temp_path.unlink(missing_ok=True)


# response_model=None：返回值可能是 dict 也可能是 JSONResponse（缺数据显示 404），
# 不关掉自动响应模型的话 FastAPI 会在导入期就报「Invalid args for response field」。
@router.get('/acceptance', response_model=None)
async def plate_acceptance() -> dict[str, object] | JSONResponse:
    """离线验收结果回放：没有模型权重时，页面仍有可展示的真实数据。"""
    payload = _load_acceptance()
    if payload is None:
        # 缺数据既要让页面看得懂（体内 code），也要让网关/监控判得对（HTTP 404）。
        return JSONResponse(status_code=404, content={
            'code': 404, 'message': '未找到验收回放数据', 'data': {'available': False}})
    for vehicle in payload.get('vehicles', []):
        card = vehicle.get('card')
        vehicle['card_url'] = prefixed(f'/api/v1/plate/cards/{card}') if card else None
    return {'code': 200, 'message': 'success', 'data': payload}


@router.get('/replay', response_model=None)
async def plate_replay() -> dict[str, object] | JSONResponse:
    """任务过程回放：阶段时间轴 + 回放视频地址 + 关键事件。

    数据由 ai/analysis/v4e_timeline_20261115.py 从 driver.log 与 fsm.json 解析，
    视频是 watch_raw.mp4 压到 854x480 / CRF 32（200 MB → 2.6 MB）。
    """
    payload = _load_json_file(TIMELINE_PATH)
    if payload is None:
        return JSONResponse(status_code=404, content={
            'code': 404, 'message': '未找到回放数据', 'data': {'available': False}})

    video = payload.get('video') or {}
    for key in ('src', 'poster'):
        if video.get(key):
            video[key] = _media_versioned(prefixed(str(video[key])))
    payload['video'] = video

    for phase in payload.get('phases') or []:
        if phase.get('cover'):
            phase['cover'] = _media_versioned(prefixed(str(phase['cover'])))

    return {'code': 200, 'message': 'success', 'data': payload}


@router.get('/coverage', response_model=None)
async def plate_coverage() -> dict[str, object] | JSONResponse:
    """L4 覆盖质量：可观测区格数、各帧数门限占比、分排统计、15 车位质量。

    分母口径：贴墙矩形（x±13.7 / y±9.2）再扣掉 7 辆车体遮挡区。
    不扣车体会把物理上必然看不到的车底格算进分母，把覆盖率压低约 3 个点。
    """
    payload = _load_json_file(COVERAGE_PATH)
    if payload is None:
        return JSONResponse(status_code=404, content={
            'code': 404, 'message': '未找到覆盖质量数据', 'data': {'available': False}})

    if payload.get('image'):
        payload['image'] = _media_versioned(prefixed(str(payload['image'])))
    # RViz 全流程录屏（2026-11-16 加）：同样要带内容戳，否则换批后浏览器放旧片
    rviz = payload.get('rviz')
    if isinstance(rviz, dict):
        for key in ('src', 'poster'):
            if rviz.get(key):
                rviz[key] = _media_versioned(prefixed(str(rviz[key])))
    return {'code': 200, 'message': 'success', 'data': payload}
