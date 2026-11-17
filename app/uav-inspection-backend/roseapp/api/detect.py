"""玫瑰检测 API 路由"""
import os
import shutil
import re
from pathlib import Path
from browser_video import store_video
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field, ConfigDict
from roseapp.detector import rose_detector
from deployment_paths import backend_path
from uav_url_prefix import prefixed

router = APIRouter()

# 任务文件存储目录
ROSE_TASKS_DIR = str(backend_path("rose-tasks"))
os.makedirs(ROSE_TASKS_DIR, exist_ok=True)


class DetectRequest(BaseModel):
    image: str  # Base64 编码的图片
    conf: float = 0.6  # 置信度阈值
    iou: float = 0.45  # NMS IoU 阈值


class DetectionItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    class_: int = Field(alias="class")
    name: str
    cn: str
    bbox: list
    conf: float


class DetectResponse(BaseModel):
    detections: list
    count: int
    class_counts: dict


class TaskUploadResponse(BaseModel):
    task_id: str
    video_path: str
    srt_path: str


@router.post("/detect", response_model=DetectResponse)
def detect_roses(req: DetectRequest):
    """对单帧图片进行玫瑰检测"""
    try:
        result = rose_detector.detect_base64(req.image, req.conf, req.iou)
        return DetectResponse(**result)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/upload", response_model=TaskUploadResponse)
def upload_task(
    task_id: str = Form(...),
    task_name: str = Form(""),
    video: UploadFile = File(...),
    srt: UploadFile | None = File(None),
):
    """上传任务文件：视频 + SRT 字幕"""
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', task_id):
        raise HTTPException(422, '任务编号只能包含字母、数字、下划线和短横线')
    task_dir = os.path.join(ROSE_TASKS_DIR, task_id)
    if os.path.exists(task_dir):
        raise HTTPException(409, '任务编号已存在，请新建任务')
    original_name = (video.filename or 'video.mp4').replace('\\', '/').rsplit('/', 1)[-1]
    video_name = Path(original_name).stem + '.mp4'
    srt_name = (srt.filename or 'subtitle.srt').replace('\\', '/').rsplit('/', 1)[-1] if srt else ''
    if srt and Path(srt_name).suffix.lower() != '.srt':
        raise HTTPException(422, '请选择 SRT 字幕文件')
    os.makedirs(task_dir, exist_ok=True)

    # 保存视频
    video_path = Path(task_dir) / video_name
    try:
        store_video(video.file, video_path, original_name)
    except Exception:
        shutil.rmtree(task_dir, ignore_errors=True)
        raise

    # 保存 SRT
    srt_path = os.path.join(task_dir, srt_name)
    if srt:
        with open(srt_path, "wb") as f:
            shutil.copyfileobj(srt.file, f)

    # 保存任务元信息
    meta_path = os.path.join(task_dir, "meta.txt")
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write(f"name={task_name}\n")
        f.write(f"video={video_name}\n")
        f.write(f"srt={srt_name}\n")

    return TaskUploadResponse(
        task_id=task_id,
        video_path=prefixed(f"/api/v1/rose/tasks/{task_id}/{video_name}"),
        srt_path=prefixed(f"/api/v1/rose/tasks/{task_id}/{srt_name}") if srt_name else '',
    )


@router.get("/tasks/list")
async def list_existing_tasks():
    """扫描 rose-tasks 目录，返回所有已存在的任务"""
    tasks = []
    if not os.path.isdir(ROSE_TASKS_DIR):
        return {"tasks": tasks}

    for task_id in os.listdir(ROSE_TASKS_DIR):
        task_dir = os.path.join(ROSE_TASKS_DIR, task_id)
        if not os.path.isdir(task_dir):
            continue
        meta_file = os.path.join(task_dir, "meta.txt")
        task_info = {"task_id": task_id, "name": task_id, "video_name": "", "srt_name": ""}
        if os.path.isfile(meta_file):
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("name="):
                            task_info["name"] = line[5:]
                        elif line.startswith("video="):
                            task_info["video_name"] = line[6:]
                        elif line.startswith("srt="):
                            task_info["srt_name"] = line[4:]
            except Exception:
                pass
        # 自动探测目录中的文件
        if not task_info["video_name"]:
            for fname in os.listdir(task_dir):
                if fname.lower().endswith((".mp4", ".avi", ".mov", ".mkv")):
                    task_info["video_name"] = fname
                    break
        if not task_info["srt_name"]:
            for fname in os.listdir(task_dir):
                if fname.lower().endswith(".srt"):
                    task_info["srt_name"] = fname
                    break
        task_info["video_url"] = prefixed(f"/api/v1/rose/tasks/{task_id}/{task_info['video_name']}")
        tasks.append(task_info)

    return {"tasks": tasks}


@router.get("/health")
def health_check():
    """检查模型是否已加载"""
    try:
        rose_detector.load_model()
        return {"status": "ready", "service_status": "running", "inference_available": True, **rose_detector.get_info()}
    except Exception as e:
        return {"status": "not_ready", "service_status": "running", "inference_available": False, "error": str(e), **rose_detector.get_info()}
