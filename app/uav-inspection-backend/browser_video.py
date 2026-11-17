"""Store uploaded videos atomically in a browser-playable MP4 format."""
import shutil
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile

import cv2
from fastapi import HTTPException


def store_video(source, destination: Path, original_name: str):
    if Path(original_name).suffix.lower() not in {'.mp4', '.mov', '.avi', '.mkv', '.webm'}:
        raise HTTPException(422, '请选择 MP4、MOV、AVI、MKV 或 WEBM 视频')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=destination.parent, suffix=Path(original_name).suffix, delete=False) as raw:
        original = Path(raw.name)
        converted = original.with_name(original.stem + '.playback.mp4')
        try:
            shutil.copyfileobj(source, raw)
            raw.close()
            capture = cv2.VideoCapture(str(original))
            try:
                valid, frame = capture.read()
                fourcc = int(capture.get(cv2.CAP_PROP_FOURCC))
                codec = ''.join(chr((fourcc >> (8 * i)) & 255) for i in range(4)).lower()
            finally:
                capture.release()
            if not valid or frame is None:
                raise HTTPException(422, '视频无法解码，请检查文件是否完整')
            # Re-encode to normalize pixel format as well as container/codec.
            if not shutil.which('ffmpeg'):
                if original.suffix.lower() == '.mp4' and codec in {'h264', 'avc1'}:
                    original.replace(destination)
                    return
                raise HTTPException(503, '此视频需要转码，请在服务器安装 ffmpeg，或上传 H.264 编码的 MP4 视频')
            result = subprocess.run([
                'ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(original),
                '-map', '0:v:0', '-an', '-c:v', 'libx264', '-preset', 'veryfast',
                '-crf', '23', '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2',
                '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(converted),
            ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=600)
            if result.returncode or not converted.is_file() or converted.stat().st_size == 0:
                raise HTTPException(422, '视频转码失败，请尝试导出 H.264 编码的 MP4 视频后重新上传')
            converted.replace(destination)
        except subprocess.TimeoutExpired:
            raise HTTPException(422, '视频转码超过 10 分钟，请压缩或分段后重试') from None
        finally:
            original.unlink(missing_ok=True)
            converted.unlink(missing_ok=True)
