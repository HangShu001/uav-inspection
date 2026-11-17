"""Load the optional AI runtime only when an inference operation needs it."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from importlib.util import find_spec
from functools import wraps
from threading import RLock, Lock

_lock_creation = Lock()


def serialized_inference(method):
    """Keep a singleton's reload and prediction from mutating the same model concurrently."""
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with _lock_creation:
            if not hasattr(self, '_inference_lock'):
                self._inference_lock = RLock()
        with self._inference_lock:
            return method(self, *args, **kwargs)
    return guarded


class InferenceUnavailableError(FileNotFoundError):
    """An optional model/runtime is absent; existing API handlers return HTTP 503."""


def inference_dependencies_available() -> bool:
    try:
        return all(find_spec(name) is not None for name in ("torch", "ultralytics"))
    except (ImportError, ValueError):
        return False


def load_yolo_model(path: Path | str) -> Any:
    model_path = Path(path)
    if not model_path.is_file():
        raise InferenceUnavailableError(
            f"未安装可选模型 {model_path.name}。请在素材上传中心选择对应模块的模型分类，"
            "保留指定文件名且子目录留空；也可安装 02-data 数据包或设置 UAV_DATA_DIR。"
            "页面浏览和文件上传不受影响。"
        )
    try:
        from ultralytics import YOLO
    except Exception as exc:
        raise InferenceUnavailableError(
            "AI 推理依赖未安装或不可用。请安装 requirements-inference.txt，"
            "然后重新启动服务；页面浏览和文件上传不受影响。"
        ) from exc
    try:
        model = YOLO(str(model_path))
        if model.task not in {'detect', 'segment'}:
            raise ValueError('需要 YOLO 目标检测或实例分割权重，当前模型任务为 ' + str(model.task))
        return model
    except Exception as exc:
        raise InferenceUnavailableError(
            f"可选模型 {model_path.name} 无法加载，请检查数据包和 AI 推理依赖：{exc}"
        ) from exc


def inference_device() -> str:
    try:
        import torch
        return "cuda:0" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def model_signature(path):
    """Detect atomically replaced weights, including changes made outside the upload UI."""
    try:
        stat = path.stat()
        return (str(path.resolve()), stat.st_ino, stat.st_size, stat.st_mtime_ns)
    except FileNotFoundError:
        return (str(path), None)


def class_mapping(model, english, chinese):
    """Resolve training class order by label, retaining explicitly generic legacy labels."""
    import re
    names = getattr(model, 'names', None)
    if isinstance(names, list):
        names = dict(enumerate(names))
    if not isinstance(names, dict):
        return {key: key for key in english}
    normalize = lambda text: re.sub(r'[\W_]+', '', str(text)).casefold()
    aliases = {normalize(label): key for labels in (english, chinese) for key, label in labels.items()}
    aliases.update({normalize(label): key for key, label in english.items()})
    result = {int(key): aliases[normalize(value)] for key, value in names.items() if normalize(value) in aliases}
    if result:
        return result
    if all(re.fullmatch(r'(class)?\d+', normalize(value)) for value in names.values()):
        legacy = {key: key for key in english if key in names}
        if legacy:
            return legacy
    raise ValueError('权重类别与当前模块不匹配。需要类别：' + '、'.join(english.values()))
