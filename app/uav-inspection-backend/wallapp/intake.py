"""Resumable, account-bound uploads for inspection source files."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import NamedTemporaryFile
from threading import Lock

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from authapp.api import require_account
from wallapp.workflow import ROOT, database, new_id, now, task_for

router = APIRouter()
CHUNK = 8 * 1024 * 1024
VIDEO_SUFFIXES = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}
SUBTITLE_LIMIT = 64 * 1024 * 1024
FINALIZE_LOCKS = tuple(Lock() for _ in range(32))


class UploadRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0, le=32 * 1024 ** 3)
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    task_name: str = Field(min_length=1, max_length=120)
    building: str = Field(min_length=1, max_length=100)
    facade: str = Field(min_length=1, max_length=60)


def write_atomic(path, data):
    with NamedTemporaryFile(dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(data)
            output.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def upload_meta(upload_id, user):
    if not re.fullmatch('[0-9a-f]{32}', upload_id):
        raise HTTPException(404, '上传记录不存在')
    folder = ROOT / 'uploads' / upload_id
    try:
        data = json.loads((folder / 'upload.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise HTTPException(404, '上传记录不存在') from None
    if data['owner'] != user:
        raise HTTPException(404, '上传记录不存在')
    return folder, data


def upload_status_data(folder, data):
    parts = sorted(int(p.stem) for p in folder.glob('*.part'))
    return {'id': folder.name, 'chunk_size': CHUNK, 'received': parts, 'parts': data['parts']}


@router.post('/uploads')
def initialize(payload: UploadRequest, account=Depends(require_account)):
    name = payload.name.replace('\\', '/').rsplit('/', 1)[-1]
    if Path(name).suffix.lower() not in VIDEO_SUFFIXES:
        raise HTTPException(422, '请选择 MP4、MOV、AVI、MKV 或 WebM 视频')
    limit = int(os.getenv('UAV_WALL_MAX_VIDEO_BYTES', str(8 * 1024 ** 3)))
    if payload.size > limit:
        raise HTTPException(413, '视频超过当前上传上限')
    user = account['username']
    fields = payload.model_dump()
    for key in ('task_name', 'building', 'facade'):
        fields[key] = fields[key].strip()
        if not fields[key]:
            raise HTTPException(422, '请填写任务名、楼栋和立面')
    upload_id = hashlib.sha256(json.dumps([user, fields], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:32]
    folder = ROOT / 'uploads' / upload_id
    folder.mkdir(parents=True, exist_ok=True)
    data = {**fields, 'name': name, 'owner': user, 'parts': (payload.size + CHUNK - 1) // CHUNK}
    write_atomic(folder / 'upload.json', json.dumps(data, ensure_ascii=False).encode())
    return {'data': upload_status_data(folder, data)}


@router.put('/uploads/{upload_id}/parts/{index}')
def upload_part(upload_id: str, index: int, file: UploadFile = File(...), account=Depends(require_account)):
    folder, meta = upload_meta(upload_id, account['username'])
    if not 0 <= index < meta['parts']:
        raise HTTPException(422, '分片编号不正确')
    expected = min(CHUNK, meta['size'] - index * CHUNK)
    data = file.file.read(expected + 1)
    if len(data) != expected:
        raise HTTPException(422, '分片大小不正确，请重新上传')
    write_atomic(folder / f'{index}.part', data)
    return {'code': 200, 'data': {'index': index}}


def inspect_video(path):
    ffprobe = os.getenv('UAV_WALL_FFPROBE', 'ffprobe')
    try:
        result = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                 'stream=codec_name:format=duration', '-of', 'json', str(path)],
                                capture_output=True, text=True, check=True, timeout=30)
        data = json.loads(result.stdout)
        duration = float(data['format']['duration'])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('invalid duration')
        return duration, data['streams'][0]['codec_name']
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError):
        # Local installations can verify basic video readability with the existing runtime.
        import cv2
        capture = cv2.VideoCapture(str(path))
        try:
            fps, count = capture.get(cv2.CAP_PROP_FPS), capture.get(cv2.CAP_PROP_FRAME_COUNT)
            if not capture.read()[0] or fps <= 0 or count <= 0:
                raise HTTPException(422, '无法读取该视频，请检查文件后重试') from None
            return count / fps, None
        finally:
            capture.release()


def make_playback(original, target, codec):
    if original.suffix.lower() == '.mp4' and codec in {'h264', None}:
        return
    ffmpeg = os.getenv('UAV_WALL_FFMPEG', 'ffmpeg')
    with NamedTemporaryFile(dir=target.parent, suffix='.mp4', delete=False) as output:
        temp = Path(output.name)
        output.close()
        try:
            subprocess.run([ffmpeg, '-nostdin', '-loglevel', 'error', '-y', '-i', str(original),
                            '-map', '0:v:0', '-an', '-c:v', 'libx264', '-preset', 'veryfast',
                            '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', '-pix_fmt', 'yuv420p',
                            '-movflags', '+faststart', str(temp)], capture_output=True, check=True, timeout=1800)
            temp.replace(target)
        except (OSError, subprocess.SubprocessError):
            # Preserve the source for detection even if a preview cannot be produced.
            return
        finally:
            temp.unlink(missing_ok=True)


@router.post('/uploads/{upload_id}/complete')
def complete(upload_id: str, account=Depends(require_account)):
    folder, meta = upload_meta(upload_id, account['username'])
    # Keep large video I/O outside SQLite's write transaction.
    with FINALIZE_LOCKS[int(upload_id[:2], 16) % len(FINALIZE_LOCKS)]:
        with database() as conn:
            existing = conn.execute('SELECT id FROM tasks WHERE id=?', (upload_id,)).fetchone()
        if existing:
            return {'data': {'id': upload_id}}
        parts = [folder / f'{i}.part' for i in range(meta['parts'])]
        if any(not part.is_file() for part in parts):
            raise HTTPException(409, '还有分片未上传，请继续上传')
        target_dir = ROOT / 'media' / upload_id
        target_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(meta['name']).suffix.lower()
        destination = target_dir / ('original' + suffix)
        with NamedTemporaryFile(dir=target_dir, suffix=suffix, delete=False) as output:
            temporary = Path(output.name)
            digest = hashlib.sha256()
            try:
                for part in parts:
                    with part.open('rb') as source:
                        while chunk := source.read(1024 * 1024):
                            output.write(chunk)
                            digest.update(chunk)
                size = output.tell()
                output.close()
                if size != meta['size'] or digest.hexdigest() != meta['fingerprint']:
                    for part in parts:
                        part.unlink(missing_ok=True)
                    raise HTTPException(409, '视频校验失败，请重新上传')
                duration, codec = inspect_video(temporary)
                temporary.replace(destination)
                make_playback(destination, target_dir / 'playback.mp4', codec)
                with database(write=True) as conn:
                    conn.execute(
                        'INSERT INTO tasks(id,owner,name,building,facade,video,duration,created_at) VALUES(?,?,?,?,?,?,?,?)',
                        (upload_id, meta['owner'], meta['task_name'], meta['building'], meta['facade'],
                         destination.name, duration, now()),
                    )
            finally:
                temporary.unlink(missing_ok=True)
        for part in parts:
            part.unlink(missing_ok=True)
    return {'data': {'id': upload_id}}


@router.put('/tasks/{task_id}/subtitle')
def attach_subtitle(task_id: str, file: UploadFile = File(...), account=Depends(require_account)):
    if Path(file.filename or '').suffix.lower() != '.srt':
        raise HTTPException(422, '请选择 SRT 字幕文件')
    data = file.file.read(SUBTITLE_LIMIT + 1)
    if not data or len(data) > SUBTITLE_LIMIT:
        raise HTTPException(422, '字幕为空或超过 64 MB')
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError:
        try:
            text = data.decode('gb18030')
        except UnicodeDecodeError:
            raise HTTPException(422, '无法读取字幕编码') from None
    if not re.search(r'\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->', text):
        raise HTTPException(422, '没有找到有效的字幕时间')
    with database(write=True) as conn:
        task_for(conn, task_id, account['username'], write=True)
        path = ROOT / 'media' / task_id / 'flight.srt'
        write_atomic(path, text.encode('utf-8'))
        conn.execute('UPDATE tasks SET subtitle=? WHERE id=?', (path.name, task_id))
    return {'data': {'saved': True}}
