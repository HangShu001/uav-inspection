"""Receive-only playback through a configured, private WHEP gateway."""
import hmac
import json
import math
import os
import re
from threading import Lock
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request as GatewayRequest, build_opener

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from authapp.api import require_account
from uav_url_prefix import prefixed
from wallapp.workflow import admin, new_id

router = APIRouter()
live_lock = Lock()
sessions = {}
telemetry = {}


def devices():
    raw = os.getenv('UAV_WALL_LIVE_DEVICES', '{}')
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def device(device_id, user):
    config = devices().get(device_id)
    if not config or (not admin(user) and user.casefold() not in {u.casefold() for u in config.get('users', [])}):
        raise HTTPException(404, '设备不存在或无权查看')
    return config


@router.get('/live/devices')
def list_devices(account=Depends(require_account)):
    user = account['username']
    items = []
    for key, config in devices().items():
        if re.fullmatch('[a-zA-Z0-9_-]{1,48}', key) and (
            admin(user) or user.casefold() in {u.casefold() for u in config.get('users', [])}
        ):
            items.append({'id': key, 'name': config.get('name', key),
                          'url': prefixed(f'/api/v1/wall/workflow/live/{key}/whep')})
    return {'code': 200, 'message': 'success', 'data': items}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args):
        return None


def upstream(url, method, config, data=None):
    headers = {'Content-Type': 'application/sdp'} if data is not None else {}
    if config.get('authorization'):
        headers['Authorization'] = config['authorization']
    try:
        with build_opener(NoRedirect()).open(GatewayRequest(url, data=data, headers=headers, method=method), timeout=8) as result:
            return result.read(128 * 1024), result.headers.get('Location')
    except (HTTPError, URLError, TimeoutError, ValueError):
        raise HTTPException(503, '暂时没有直播画面，请确认无人机正在推流') from None


@router.post('/live/{device_id}/whep')
async def connect(device_id: str, request: Request, account=Depends(require_account)):
    from fastapi.concurrency import run_in_threadpool

    user = account['username']
    config = device(device_id, user)
    offer = bytearray()
    async for part in request.stream():
        offer.extend(part)
        if len(offer) > 65536:
            raise HTTPException(413, '直播连接请求过大')
    if not offer.startswith(b'v=0'):
        raise HTTPException(422, '直播连接请求格式不正确')
    target = config.get('whep', '')
    parts = urlsplit(target)
    if parts.scheme not in {'http', 'https'} or not parts.hostname:
        raise HTTPException(503, '设备直播地址尚未配置')
    answer, location = await run_in_threadpool(upstream, target, 'POST', config, bytes(offer))
    headers = {}
    if location:
        destination = urljoin(target, location)
        parsed = urlsplit(destination)
        if (parsed.scheme, parsed.netloc) == (parts.scheme, parts.netloc):
            handle = new_id()
            with live_lock:
                for key, value in list(sessions.items()):
                    if value[3] < time.monotonic() - 86400:
                        del sessions[key]
                sessions[handle] = (device_id, user, destination, time.monotonic())
            headers['Location'] = prefixed(f'/api/v1/wall/workflow/live/{device_id}/whep/{handle}')
    return Response(answer, media_type='application/sdp', status_code=201, headers=headers)


@router.delete('/live/{device_id}/whep/{handle}', status_code=204)
def disconnect(device_id: str, handle: str, account=Depends(require_account)):
    user = account['username']
    config = device(device_id, user)
    with live_lock:
        item = sessions.get(handle)
        if not item or item[:2] != (device_id, user):
            return Response(status_code=204)
        sessions.pop(handle)
    upstream(item[2], 'DELETE', config)
    return Response(status_code=204)


class Telemetry(BaseModel):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    elevation: float | None = None
    horizontal_speed: float | None = Field(default=None, ge=0)
    timestamp: int | None = Field(default=None, gt=0)


@router.put('/live/{device_id}/telemetry', status_code=204)
def publish_telemetry(device_id: str, payload: Telemetry, x_wall_telemetry_key: str = Header(default='')):
    # Intended for a trusted Pilot 2 MQTT bridge on the deployment network.
    token = os.getenv('UAV_WALL_TELEMETRY_KEY', '')
    if not token or not hmac.compare_digest(x_wall_telemetry_key.encode(), token.encode()):
        raise HTTPException(401, '设备数据未授权')
    if device_id not in devices():
        raise HTTPException(404, '未配置该设备')
    values = payload.model_dump()
    if any(isinstance(value, float) and not math.isfinite(value) for value in values.values()):
        raise HTTPException(422, '飞行数据无效')
    with live_lock:
        previous = telemetry.get(device_id)
        if previous and payload.timestamp and previous[0]['timestamp'] and payload.timestamp < previous[0]['timestamp']:
            return Response(status_code=204)
        telemetry[device_id] = (values, time.monotonic())
    return Response(status_code=204)


@router.get('/live/{device_id}/telemetry')
def read_telemetry(device_id: str, account=Depends(require_account)):
    device(device_id, account['username'])
    with live_lock:
        sample = telemetry.get(device_id)
    value = None if sample is None else {**sample[0], 'stale': time.monotonic() - sample[1] > 5}
    return {'code': 200, 'message': 'success', 'data': value}
