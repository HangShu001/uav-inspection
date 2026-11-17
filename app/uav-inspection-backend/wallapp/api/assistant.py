"""Optional natural language intent provider. The browser executes an allowlisted action."""
import json
import os
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from authapp.api import require_account
from wallapp.workflow import database, task_for

router = APIRouter()


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=250)
    task_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args):
        return None


@router.post('/assistant')
def interpret(payload: Question, account=Depends(require_account)):
    endpoint = os.getenv('UAV_WALL_ASSISTANT_URL', '')
    model = os.getenv('UAV_WALL_ASSISTANT_MODEL', '')
    if not model or urlsplit(endpoint).scheme not in {'http', 'https'}:
        return {'code': 200, 'data': None}
    if payload.task_id:
        with database() as conn:
            task_for(conn, payload.task_id, account['username'])
    messages = [
        {'role': 'system', 'content': (
            '将巡检员的问题转成 JSON，不要输出额外内容。action 仅可为 subtitle、pending、seek、draft、unknown。'
            'subtitle 是询问如何上传字幕，pending 是查看当前任务待复核，'
            'seek 是跳转视频且 seconds 为从开头起算的非负秒数，draft 是预览工单草稿。'
            '遇到指定其他楼栋、立面、日期或具体缺陷编号，返回 unknown。'
        )},
        {'role': 'user', 'content': payload.question},
    ]
    body = json.dumps({'model': model, 'messages': messages, 'temperature': 0, 'max_tokens': 80}).encode()
    headers = {'Content-Type': 'application/json'}
    key = os.getenv('UAV_WALL_ASSISTANT_KEY', '')
    if key:
        headers['Authorization'] = 'Bearer ' + key
    try:
        req = Request(endpoint, data=body, headers=headers, method='POST')
        with build_opener(NoRedirect()).open(req, timeout=4) as response:
            data = json.loads(response.read(32 * 1024))
        value = json.loads(data['choices'][0]['message']['content'])
        action = value.get('action')
        if action in ('subtitle', 'pending', 'draft'):
            return {'code': 200, 'data': {'action': action}}
        if action == 'seek':
            seconds = value.get('seconds')
            if isinstance(seconds, (float, int)) and not isinstance(seconds, bool) and 0 <= seconds <= 172800:
                return {'code': 200, 'data': {'action': 'seek', 'seconds': seconds}}
    except (URLError, TimeoutError, ValueError, KeyError, IndexError, TypeError, AttributeError):
        pass
    return {'code': 200, 'data': None}
