"""可选的第二级车牌字符识别。

设计原则：识别权重与推理后端都是可选的。缺任一环时 `available` 为 False，
`read()` 返回 (None, 0.0)，检测段照常给出车牌框——模块不会因为缺一个二级
模型就整体不可用。

目录约定（`plateapp/recognizer/`）：

    model.onnx | model.pt   二选一，onnxruntime 优先
    charset.txt             每行一个字符，行号 + 1 即类别下标（blank 隐式为第 0 类）
    meta.json               可选，覆盖下面这些默认值

`meta.json` 字段：

    mode          "ctc"（默认）CTC 序列解码；"class" 逐位分类
    input_width   默认 120
    input_height  默认 32
    normalize     默认 "pm1"，即 x/127.5 - 1；另有 "unit"（x/255）与 "raw"
    mean/std      可选，作用在归一化之后的结果上

以上默认值不是猜的，是与 CCPD 车牌模型实测对齐的结果：32×120 输入、
`x/127.5-1` 归一化、输出 (T, 67) 且 blank 在第 0 位。三个容易踩的点：

1. **字符表顺序**必须与训练时逐字一致。省份那 31 个字的排列顺序错了，只有
   第一位会错、后面全对，看起来像「模型把皖认成京」，实际是索引对不上。
2. **通道顺序**。训练用 PIL 读图（RGB），调用方按 OpenCV 惯例给 BGR，中间必须
   转一次。不转不会报错，只会让置信度掉到 0.1 量级、字符大面积出错。
3. **四点定角**。车牌接近 45° 旋转时，用角点求和/差分来分左右会把左右判反，
   字形被拉斜后 CTC 会丢步。

解码策略：CTC 贪心会把相邻时间步的字符吞掉一位（该项目实测 1123 张错图里
836 张是位数不符，其中 468 张比真值少一位）。所以默认先走长度约束的 prefix
beam search，按 8 位与 7 位各解一次取总概率高者——8 位即新能源绿牌、7 位即
普通蓝牌，长度本身就能反推车牌类型。两段都解不出才回退贪心。
"""
from __future__ import annotations

import json
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
    'mode': 'ctc',
    'input_width': 120,
    'input_height': 32,
    'normalize': 'pm1',
}

# 中国车牌非 blank 字符数：8 位新能源、7 位普通。长度约束解码按这两个试。
PLATE_LENGTHS = (8, 7)


# ---- 几何 --------------------------------------------------------------

def _order_quad(points: np.ndarray) -> np.ndarray:
    """四点整理成 (左上, 左下, 右下, 右上)，与 PIL QUAD 的 data 顺序一致。

    用「按 y 分成上下两组、各组内按 x 排序」定角，而不是角点求和/差分。
    """
    pts = np.asarray(points, dtype=np.float64).reshape(4, 2)
    order = np.argsort(pts[:, 1])
    top_two, bottom_two = pts[order[:2]], pts[order[2:]]
    top_left, top_right = top_two[np.argsort(top_two[:, 0])]
    bottom_left, bottom_right = bottom_two[np.argsort(bottom_two[:, 0])]
    return np.array([top_left, bottom_left, bottom_right, top_right], dtype=np.float32)


def _crop_plate(image: np.ndarray, quad: Any, width: int, height: int) -> np.ndarray:
    pts = _order_quad(np.array(quad))
    target = np.array([[0, 0], [0, height - 1], [width - 1, height - 1], [width - 1, 0]],
                      dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(pts, target)
    return cv2.warpPerspective(image, matrix, (width, height), flags=cv2.INTER_CUBIC)


def _normalize(crop: np.ndarray, meta: dict[str, Any]) -> np.ndarray:
    """三种归一化：pm1（x/127.5-1，LPRNet 标准）、unit（x/255）、raw（原样）。"""
    tensor = crop.astype(np.float32)
    mode = str(meta.get('normalize', 'pm1'))
    if mode == 'pm1':
        tensor = tensor / 127.5 - 1.0
    elif mode == 'unit':
        tensor = tensor / 255.0
    mean = meta.get('mean')
    std = meta.get('std')
    if isinstance(mean, list) and len(mean) == 3:
        tensor = (tensor - np.array(mean, dtype=np.float32)) / (
            np.array(std, dtype=np.float32) if std else 1.0)
    return tensor


def _color_hint(patch_bgr: np.ndarray) -> str | None:
    """看牌面底色判车牌类型：绿底 → green（8 位），蓝底 → blue（7 位）。

    为什么需要它：光靠「8 位和 7 位哪个概率高」会判错。实测近拍腿的绿牌
    经常解出置信度 0.99 的 7 位结果（模型确实少输出了一位），而远拍腿反而
    解出正确的 8 位。用底色把长度锁死，比让模型自己选可靠。
    """
    hsv = cv2.cvtColor(patch_bgr, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    mask = (sat > 70) & (val > 50)
    count = int(mask.sum())
    if count < 80:
        return None
    hue_values = hue[mask]
    green = int(((hue_values >= 40) & (hue_values <= 95)).sum())
    blue = int(((hue_values >= 100) & (hue_values <= 140)).sum())
    if green / count > 0.30 and green > blue * 1.5:
        return 'green'
    if blue / count > 0.30 and blue > green * 1.5:
        return 'blue'
    return None


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=1, keepdims=True)


# ---- 解码 --------------------------------------------------------------

def _greedy_ctc(probs: np.ndarray, charset: list[str]) -> tuple[str, float]:
    """CTC 贪心解码：取每帧最大类别，合并重复、去 blank。"""
    best = probs.argmax(axis=1)
    picked: list[int] = []
    previous = -1
    for index in best:
        index = int(index)
        if index != previous and index != 0:
            picked.append(index)
        previous = index
    text = ''.join(charset[i - 1] for i in picked if 1 <= i <= len(charset))
    scores = [float(probs[step, i]) for step, i in enumerate(picked)]
    return text, (sum(scores) / len(scores) if scores else 0.0)


def _beam_decode(probs: np.ndarray, target_len: int, topk: int = 8,
                 beam_width: int = 16, blank: int = 0) -> tuple[list[int], list[float], float] | None:
    """CTC prefix beam search，约束非 blank 输出恰好 target_len 个字符。

    移植自本项目 ccpd_code/ctc_len_decode.py（原实现另带位置白名单，这里只留
    纯长度约束——本模块不预设车牌格式，白名单会把非标准牌直接判死）。
    返回 (字符 id 列表, 每字符概率, 路径总概率)，解不出返回 None。
    """
    total_time, classes = probs.shape
    if target_len <= 0 or target_len > total_time:
        return None

    beams: dict[tuple[int, ...], list[Any]] = {(): [1.0, 0.0, ()]}
    for step in range(total_time):
        frame = probs[step]
        if topk < classes:
            top = np.argpartition(-frame, topk - 1)[:topk]
            candidates = [(int(c), float(frame[c])) for c in top]
            if blank not in {c for c, _ in candidates}:
                candidates.append((blank, float(frame[blank])))
        else:
            candidates = [(c, float(frame[c])) for c in range(classes)]

        updated: dict[tuple[int, ...], list[Any]] = {}
        for prefix, (p_blank, p_nonblank, confs) in beams.items():
            p_total = p_blank + p_nonblank
            if p_total <= 0:
                continue
            pos = len(prefix)
            for char_id, p_char in candidates:
                if p_char <= 1e-12:
                    continue
                if char_id == blank:
                    slot = updated.get(prefix)
                    if slot is None:
                        slot = updated[prefix] = [0.0, 0.0, confs]
                    slot[0] += p_total * p_char
                    continue

                last = prefix[-1] if prefix else None
                if char_id == last:
                    # 同一字符重复：前缀不变（CTC 折叠规则）
                    slot = updated.get(prefix)
                    if slot is None:
                        slot = updated[prefix] = [0.0, 0.0, confs]
                    slot[1] += p_nonblank * p_char
                    # 经 blank 分隔后再次出现，算新的一位
                    if pos < target_len:
                        extended = prefix + (char_id,)
                        slot2 = updated.get(extended)
                        if slot2 is None:
                            slot2 = updated[extended] = [0.0, 0.0, confs + (p_char,)]
                        slot2[1] += p_blank * p_char
                elif pos < target_len:
                    extended = prefix + (char_id,)
                    slot2 = updated.get(extended)
                    if slot2 is None:
                        slot2 = updated[extended] = [0.0, 0.0, confs + (p_char,)]
                    slot2[1] += p_total * p_char

        if not updated:
            return None
        beams = dict(sorted(updated.items(),
                            key=lambda kv: -(kv[1][0] + kv[1][1]))[:beam_width])

    best = None
    for prefix, (p_blank, p_nonblank, confs) in beams.items():
        if len(prefix) != target_len:
            continue
        score = p_blank + p_nonblank
        if best is None or score > best[0]:
            best = (score, prefix, confs)
    if best is None:
        return None
    return list(best[1]), list(best[2]), float(best[0])


def _per_position(probs: np.ndarray, charset: list[str]) -> tuple[str, float]:
    """逐位分类：每个时间步独立取最大类别，没有 blank。"""
    best = probs.argmax(axis=1)
    text = ''.join(charset[int(i)] for i in best if 0 <= int(i) < len(charset))
    scores = [float(probs[step, int(i)]) for step, i in enumerate(best)]
    return text, (sum(scores) / len(scores) if scores else 0.0)


# ---- 识别器 ------------------------------------------------------------

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
        if self._loaded:
            return
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

                self.session = onnxruntime.InferenceSession(
                    str(ONNX_PATH), providers=['CPUExecutionProvider'])
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
            'mode': self.meta.get('mode', 'ctc'),
            'charset_size': len(self.charset),
            'decoder': 'beam-search-len' if str(self.meta.get('mode', 'ctc')) == 'ctc' else 'per-position',
            'input_size': [int(self.meta.get('input_width', 120)), int(self.meta.get('input_height', 32))],
            'note': note,
        }

    # ---- 推理 ----------------------------------------------------------

    def read(self, image: np.ndarray, quad: Any) -> tuple[str | None, float]:
        """从 BGR 图与车牌四点读出号码。

        调用方按 OpenCV 惯例传 BGR；识别模型是在 RGB 上训练的（PIL 读图），
        这里必须转一次——不转的话通道顺序反了，置信度会掉到 0.1 量级、
        字符大面积出错，而不是直接报错。
        """
        if not self.available or self.session is None:
            return None, 0.0
        width = int(self.meta.get('input_width', 120))
        height = int(self.meta.get('input_height', 32))
        try:
            crop_bgr = _crop_plate(image, quad, width, height)
            crop = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
        except Exception:
            return None, 0.0

        tensor = _normalize(crop, self.meta).transpose(2, 0, 1)[None, ...]
        try:
            logits = self._forward(tensor)
        except Exception:
            return None, 0.0
        if logits.ndim == 3:
            logits = logits[0]
        if logits.ndim != 2:
            return None, 0.0

        probs = _softmax(logits)
        if str(self.meta.get('mode', 'ctc')) != 'ctc':
            return _per_position(probs, self.charset)

        # 先按底色锁定长度，再退回到「两种都试、取概率高者」。
        # 注意这里必须传 BGR 原图：_color_hint 按 BGR2HSV 算色相。
        tint = _color_hint(crop_bgr)
        if tint == 'green':
            targets = (8,)
        elif tint == 'blue':
            targets = (7,)
        else:
            targets = PLATE_LENGTHS

        best: tuple[float, list[int], list[float]] | None = None
        for target in targets:
            got = _beam_decode(probs, target)
            if got is None:
                continue
            ids, confs, score = got
            if best is None or score > best[0]:
                best = (score, ids, confs)
        if best is not None:
            _, ids, confs = best
            text = ''.join(self.charset[i - 1] for i in ids if 1 <= i <= len(self.charset))
            if text:
                return text, (sum(confs) / len(confs) if confs else 0.0)
        return _greedy_ctc(probs, self.charset)

    def _forward(self, tensor: np.ndarray) -> np.ndarray:
        if self.backend == 'onnx':
            name = self.session.get_inputs()[0].name
            return np.asarray(self.session.run(None, {name: tensor})[0])
        import torch

        with torch.no_grad():
            output = self.session(torch.from_numpy(tensor))
        return output.cpu().numpy() if hasattr(output, 'cpu') else np.asarray(output)


plate_recognizer = PlateRecognizer()
