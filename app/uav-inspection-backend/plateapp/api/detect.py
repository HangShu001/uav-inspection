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
from uav_url_prefix import prefixed

router = APIRouter()

DATA_DIR = Path(__file__).resolve().parent.parent / 'data'
ACCEPTANCE_PATH = DATA_DIR / 'acceptance.json'
CARDS_DIR = DATA_DIR / 'cards'

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


@router.get('/acceptance')
async def plate_acceptance() -> dict[str, object]:
    """离线验收结果回放：没有模型权重时，页面仍有可展示的真实数据。"""
    payload = _load_acceptance()
    if payload is None:
        return {'code': 404, 'message': '未找到验收回放数据', 'data': {'available': False}}
    for vehicle in payload.get('vehicles', []):
        card = vehicle.get('card')
        vehicle['card_url'] = prefixed(f'/api/v1/plate/cards/{card}') if card else None
    return {'code': 200, 'message': 'success', 'data': payload}
