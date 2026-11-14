"""车牌检测与识别。

两段式：检测段用 YOLO 定位车牌（普通框与 OBB 旋转框都支持），识别段是
可插拔的第二级模型（见 recognizer.py）。任一段权重缺失时模块照常提供
页面与素材上传，检测接口返回 503 并给出上传指引——与其他模块的降级口径一致。
"""
from __future__ import annotations

import base64
import time
from typing import Any

import cv2
import numpy as np

from deployment_paths import backend_path
from optional_inference import load_yolo_model
from plateapp.recognizer import plate_recognizer

MODEL_PATH = backend_path('plateapp', 'plate-det-best.pt')

# 类别名到车牌颜色的映射。模型导出的 names 只要含下列关键词就能认出颜色，
# 不要求固定为某一个训练集；认不出的类别原样保留，不强行归类。
COLOR_ALIASES = {
    'green': ('green', 'new_energy', 'newenergy', 'nev', '绿'),
    'blue': ('blue', '蓝'),
    'yellow': ('yellow', '黄'),
    'white': ('white', '白'),
    'black': ('black', '黑'),
}

COLOR_CN = {
    'green': '新能源绿牌',
    'blue': '蓝牌',
    'yellow': '黄牌',
    'white': '白牌',
    'black': '黑牌',
    'unknown': '未分类',
}

COLOR_BGR = {
    'green': (96, 200, 64),
    'blue': (208, 132, 32),
    'yellow': (48, 200, 240),
    'white': (232, 232, 232),
    'black': (72, 72, 72),
    'unknown': (160, 160, 160),
}


def resolve_color(class_name: str) -> str:
    """把模型的类别名映射到统一的车牌颜色键；认不出返回 unknown。"""
    lowered = (class_name or '').strip().lower()
    for color, aliases in COLOR_ALIASES.items():
        if any(alias in lowered for alias in aliases):
            return color
    return 'unknown'


class PlateDetector:
    _instance: 'PlateDetector | None' = None

    def __new__(cls) -> 'PlateDetector':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self.model: Any | None = None
        self.conf_threshold = 0.35
        self.iou_threshold = 0.45
        self.max_plates = 30
        self._initialized = True

    def load_model(self) -> None:
        if self.model is not None:
            return
        self.model = load_yolo_model(MODEL_PATH)
        try:
            self.model.fuse()
        except Exception:
            pass

    # ---- 推理 ----------------------------------------------------------

    def detect(
        self,
        image_bgr: np.ndarray,
        conf_threshold: float | None = None,
        iou_threshold: float | None = None,
        recognize: bool = True,
    ) -> dict[str, Any]:
        self.load_model()
        assert self.model is not None

        conf = self.conf_threshold if conf_threshold is None else conf_threshold
        iou = self.iou_threshold if iou_threshold is None else iou_threshold
        started_at = time.perf_counter()

        results = self.model(image_bgr, conf=conf, iou=iou, verbose=False)
        detections: list[dict[str, Any]] = []
        stats = {key: 0 for key in COLOR_CN}
        annotated = image_bgr.copy()

        for result in results:
            for item in self._iter_plates(result):
                color = resolve_color(item['class_name'])
                stats[color] = stats.get(color, 0) + 1

                text, text_score = None, 0.0
                if recognize and plate_recognizer.available:
                    text, text_score = plate_recognizer.read(image_bgr, item['quad'])

                detection = {
                    'class': item['class_id'],
                    'name': item['class_name'],
                    'color': color,
                    'color_cn': COLOR_CN.get(color, COLOR_CN['unknown']),
                    'bbox': item['bbox'],
                    'quad': item['quad'],
                    'conf': round(item['conf'], 3),
                    'text': text,
                    'text_score': round(text_score, 3) if text else None,
                }
                detections.append(detection)
                self._draw_plate(annotated, detection)

        _, buffer = cv2.imencode('.jpg', annotated)
        annotated_base64 = base64.b64encode(buffer).decode('utf-8')
        inference_ms = round((time.perf_counter() - started_at) * 1000, 2)

        return {
            'detections': detections,
            'count': len(detections),
            'stats': stats,
            'plates': [d['text'] for d in detections if d['text']],
            'recognizer': plate_recognizer.status(),
            'annotated_image': annotated_base64,
            'image_size': [int(image_bgr.shape[1]), int(image_bgr.shape[0])],
            'inference_ms': inference_ms,
        }

    @staticmethod
    def _iter_plates(result: Any):
        """统一 OBB 与普通检测框两条分支，逐块吐出车牌几何。"""
        obb = getattr(result, 'obb', None)
        if obb is not None and len(obb) > 0:
            names = getattr(result, 'names', {}) or {}
            polygons = obb.xyxyxyxy.cpu().numpy()
            for index in range(len(obb)):
                class_id = int(obb.cls[index].item())
                polygon = polygons[index].reshape(4, 2)
                x1, y1 = polygon[:, 0].min(), polygon[:, 1].min()
                x2, y2 = polygon[:, 0].max(), polygon[:, 1].max()
                yield {
                    'class_id': class_id,
                    'class_name': str(names.get(class_id, class_id)),
                    'conf': float(obb.conf[index].item()),
                    'bbox': [round(float(x1), 1), round(float(y1), 1),
                             round(float(x2), 1), round(float(y2), 1)],
                    'quad': [[round(float(x), 1), round(float(y), 1)] for x, y in polygon],
                }
            return

        boxes = getattr(result, 'boxes', None)
        if boxes is None or len(boxes) == 0:
            return
        names = getattr(result, 'names', {}) or {}
        for index in range(len(boxes)):
            class_id = int(boxes.cls[index].item())
            x1, y1, x2, y2 = [float(v) for v in boxes.xyxy[index].tolist()]
            yield {
                'class_id': class_id,
                'class_name': str(names.get(class_id, class_id)),
                'conf': float(boxes.conf[index].item()),
                'bbox': [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                'quad': [[round(x1, 1), round(y1, 1)], [round(x2, 1), round(y1, 1)],
                         [round(x2, 1), round(y2, 1)], [round(x1, 1), round(y2, 1)]],
            }

    def detect_base64(
        self,
        image_base64: str,
        conf_threshold: float | None = None,
        iou_threshold: float | None = None,
        recognize: bool = True,
    ) -> dict[str, Any]:
        payload = image_base64.split(',', 1)[-1] if image_base64.startswith('data:') else image_base64
        image_bytes = base64.b64decode(payload)
        np_arr = np.frombuffer(image_bytes, np.uint8)
        image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError('无法解码图片，请确认上传的是 JPG/PNG')
        return self.detect(image, conf_threshold=conf_threshold,
                           iou_threshold=iou_threshold, recognize=recognize)

    # ---- 配置与自述 ----------------------------------------------------

    def update_config(
        self,
        confidence: float | None = None,
        iou: float | None = None,
        max_plates: int | None = None,
    ) -> dict[str, Any]:
        if confidence is not None:
            self.conf_threshold = max(0.05, min(0.95, float(confidence)))
        if iou is not None:
            self.iou_threshold = max(0.05, min(0.95, float(iou)))
        if max_plates is not None:
            self.max_plates = max(1, min(100, int(max_plates)))
        return self.get_config()

    def get_config(self) -> dict[str, Any]:
        return {
            'confidence': self.conf_threshold,
            'iou': self.iou_threshold,
            'max_plates': self.max_plates,
        }

    def get_info(self) -> dict[str, Any]:
        self.load_model()
        names = getattr(self.model, 'names', {}) or {}
        return {
            'system': {
                'cuda_available': bool(
                    getattr(getattr(self.model, 'predictor', None), 'device', None)
                    and 'cuda' in str(self.model.predictor.device).lower()
                ),
                'device': str(getattr(getattr(self.model, 'predictor', None), 'device', 'cpu')),
            },
            'model': {
                'name': MODEL_PATH.name,
                'classes': [str(names.get(key, key)) for key in sorted(names)],
                'task': str(getattr(self.model, 'task', 'detect')),
            },
            'recognizer': plate_recognizer.status(),
            'config': self.get_config(),
            'capabilities': {
                'single_frame_detection': True,
                'oriented_boxes': str(getattr(self.model, 'task', '')) == 'obb',
                'plate_text': plate_recognizer.available,
            },
        }

    # ---- 绘制 ----------------------------------------------------------

    @staticmethod
    def _draw_plate(image: np.ndarray, detection: dict[str, Any]) -> None:
        color = COLOR_BGR.get(detection['color'], COLOR_BGR['unknown'])
        polygon = np.array(detection['quad'], dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(image, [polygon], True, color, 2)

        label = detection['text'] or detection['color_cn']
        caption = f'{label} {detection["conf"]:.2f}'
        x1, y1 = int(detection['bbox'][0]), int(detection['bbox'][1])
        font = cv2.FONT_HERSHEY_SIMPLEX
        text_size, _ = cv2.getTextSize(caption, font, 0.6, 2)
        text_w, text_h = text_size
        top = max(0, y1 - text_h - 10)
        cv2.rectangle(image, (x1, top), (x1 + text_w + 8, y1), color, -1)
        cv2.putText(image, caption, (x1 + 4, y1 - 6), font, 0.6, (255, 255, 255), 2, cv2.LINE_AA)


plate_detector = PlateDetector()
