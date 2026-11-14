"""可选的第二级车牌字符识别。

设计原则：识别权重与推理后端都是可选的。缺任一环时 `available` 为 False，
`read()` 返回 (None, 0.0)，检测段照常给出车牌框与颜色——模块不会因为
缺一个二级模型就整体不可用。

目录约定（`plateapp/recognizer/`）：

    model.onnx | model.pt   二选一，onnxruntime 优先
    charset.txt             每行一个字符，行号即类别下标
    meta.json               可选，覆盖下面这些默认值

`meta.json` 字段：

    mode          "class"（默认）逐位分类，输出 (T, C) 且 C == 字符表长度
                  "ctc"  输出 (T, C)，C == 字符表长度 + 1，第 0 位是 blank
    input_width   默认 168
    input_height  默认 48
    normalize     默认 "unit"，把像素除以 255；"none" 则原样送入
    mean/std      可选，形如 [0.5,0.5,0.5]，与 normalize 同时生效时先除再减除

导出时必须遵守以上输入输出约定，否则识别结果会是乱码而不是报错——这是
二级模型的固有风险，页面对识别文本始终附带 `text_score`。
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from deployment_paths import backend_path

RECOGNIZER_DIR = backend_path('plateapp', 'recognizer')
ONNX_PATH = RECOGNIZER_DIR / 'model.onnx'
TORCH_PATH = RECOGNIZER_DIR / 'model.pt'
CHARSET_PATH = RECOGNIZER_DIR / 'charset.txt'
META_PATH = RECOGNIZER_DIR / 'meta.json'

DEFAULT_META = {
    'mode': 'class',
    'input_width': 168,
    'input_height': 48,
    'normalize': 'unit',
}


def _order_quad(points: np.ndarray) -> np.ndarray:
    """把四个角点整理成「左上、右上、右下、左下」顺序，供透视校正使用。"""
    pts = np.asarray(points, dtype=np.float32).reshape(4, 2)
    ordered = np.zeros((4, 2), dtype=np.float32)
    sums = pts.sum(axis=1)
    diffs = np.diff(pts, axis=1).reshape(-1)
    ordered[0] = pts[int(np.argmin(sums))]
    ordered[2] = pts[int(np.argmax(sums))]
    ordered[1] = pts[int(np.argmin(diffs))]
    ordered[3] = pts[int(np.argmax(diffs))]
    return ordered


def _crop_plate(image: np.ndarray, quad: Any, width: int, height: int) -> np.ndarray:
    pts = _order_quad(np.array(quad))
    target = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(pts, target)
    return cv2.warpPerspective(image, matrix, (width, height))


def _greedy_ctc(logits: np.ndarray, charset: list[str]) -> tuple[str, float]:
    """CTC 贪心解码：取每帧最大类别，合并重复、去 blank。"""
    best = logits.argmax(axis=1)
    picked: list[int] = []
    previous = -1
    for index in best:
        index = int(index)
        if index != previous and index != 0:
            picked.append(index - 1)
        previous = index
    text = ''.join(charset[i] for i in picked if 0 <= i < len(charset))
    return text, _mean_confidence(logits, picked, offset=1)


def _per_position(logits: np.ndarray, charset: list[str]) -> tuple[str, float]:
    """逐位分类：每个时间步独立取最大类别，没有 blank。"""
    best = logits.argmax(axis=1)
    text = ''.join(charset[int(i)] for i in best if 0 <= int(i) < len(charset))
    return text, _mean_confidence(logits, [int(i) for i in best], offset=0)


def _mean_confidence(logits: np.ndarray, indices: list[int], offset: int) -> float:
    if not indices:
        return 0.0
    shifted = logits - logits.max(axis=1, keepdims=True)
    exp = np.exp(shifted)
    probs = exp / exp.sum(axis=1, keepdims=True)
    scores = [float(probs[step, min(index + offset, probs.shape[1] - 1)])
              for step, index in enumerate(indices)]
    return float(sum(scores) / len(scores)) if scores else 0.0


class PlateRecognizer:
    _instance: 'PlateRecognizer | None' = None

    def __new__(cls) -> 'PlateRecognizer':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, '_initialized', False):
            return
        self._initialized = True
        self.backend: str | None = None
        self.session: Any | None = None
        self.charset: list[str] = []
        self.meta: dict[str, Any] = dict(DEFAULT_META)

    # ---- 状态 ----------------------------------------------------------

    @property
    def available(self) -> bool:
        if not self._loaded:
            self._load()
        return self.backend is not None and bool(self.charset)

    def _load(self) -> None:
        self._loaded = True
        if not RECOGNIZER_DIR.is_dir():
            return
        if META_PATH.is_file():
            try:
                self.meta.update(json.loads(META_PATH.read_text(encoding='utf-8')))
            except Exception:
                pass
        if CHARSET_PATH.is_file():
            self.charset = [line for line in CHARSET_PATH.read_text(encoding='utf-8').splitlines() if line]
        if not self.charset:
            return

        if ONNX_PATH.is_file():
            try:
                import onnxruntime

                self.session = onnxruntime.InferenceSession(str(ONNX_PATH), providers=['CPUExecutionProvider'])
                self.backend = 'onnx'
                return
            except Exception:
                self.session = None
        if TORCH_PATH.is_file():
            try:
                import torch

                self.session = torch.jit.load(str(TORCH_PATH), map_location='cpu').eval()
                self.backend = 'torch'
                return
            except Exception:
                self.session = None

    def status(self) -> dict[str, Any]:
        available = self.available
        note = ''
        if not RECOGNIZER_DIR.is_dir():
            note = '未安装识别模型。检测与颜色分类照常可用；需要车牌号请在素材上传中心选择「车牌识别模型」分类。'
        elif not CHARSET_PATH.is_file():
            note = '识别模型目录存在但缺少 charset.txt，无法映射字符，按未安装处理。'
        elif not available:
            note = '识别模型文件存在但推理后端不可用（需要 torch 或 onnxruntime），按未安装处理。'
        return {
            'available': available,
            'backend': self.backend,
            'model': (ONNX_PATH if self.backend == 'onnx' else TORCH_PATH).name if available else None,
            'mode': self.meta.get('mode', 'class'),
            'charset_size': len(self.charset),
            'note': note,
        }

    # ---- 推理 ----------------------------------------------------------

    def read(self, image: np.ndarray, quad: Any) -> tuple[str | None, float]:
        if not self.available or self.session is None:
            return None, 0.0
        width = int(self.meta.get('input_width', 168))
        height = int(self.meta.get('input_height', 48))
        try:
            crop = _crop_plate(image, quad, width, height)
        except Exception:
            return None, 0.0

        tensor = crop.astype(np.float32)
        if str(self.meta.get('normalize', 'unit')) == 'unit':
            tensor = tensor / 255.0
        mean = self.meta.get('mean')
        std = self.meta.get('std')
        if isinstance(mean, list) and len(mean) == 3:
            tensor = (tensor - np.array(mean, dtype=np.float32)) / (np.array(std, dtype=np.float32) if std else 1.0)
        tensor = tensor.transpose(2, 0, 1)[None, ...]

        try:
            logits = self._forward(tensor)
        except Exception:
            return None, 0.0
        if logits.ndim == 3:
            logits = logits[0]
        if logits.ndim != 2:
            return None, 0.0

        mode = str(self.meta.get('mode', 'class'))
        if mode == 'ctc':
            return _greedy_ctc(logits, self.charset)
        return _per_position(logits, self.charset)

    def _forward(self, tensor: np.ndarray) -> np.ndarray:
        if self.backend == 'onnx':
            name = self.session.get_inputs()[0].name
            return np.asarray(self.session.run(None, {name: tensor})[0])
        import torch

        with torch.no_grad():
            output = self.session(torch.from_numpy(tensor))
        return output.cpu().numpy() if hasattr(output, 'cpu') else np.asarray(output)


plate_recognizer = PlateRecognizer()
