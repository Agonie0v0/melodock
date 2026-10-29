"""Discover and invoke MeloKeep's existing JSON APIs from authenticated AI turns."""
import asyncio
import copy
import json
import re
from urllib.parse import urlencode, urlsplit

from fastapi import FastAPI, HTTPException
from fastapi.openapi.utils import get_openapi
from fastapi.routing import APIRoute


HIDDEN = '[已隐藏]'
# Media transfers and event streams are consumed by the browser, not the model.
MEDIA = {
    '/api/file', '/api/files/audio', '/api/files/cover', '/api/files/content',
    '/api/stream/{sid}', '/api/navidrome/cover/{ident}', '/api/navidrome/stream/{ident}',
    '/api/search/jobs/{ident}/events', '/api/library/jobs/{ident}/report',
}
DOMAINS = {
    'playlists': '歌单', 'playlist': '播放队列与歌单导入', 'favorites': '收藏',
    'downloads': '下载任务', 'files': '本地音乐文件与标签', 'library': '音乐库刮削整理归档监控设置',
    'navidrome': 'Navidrome 曲库歌单扫描', 'engine': '音源引擎配置更新',
    'config': '音源代理下载配置', 'bots': '通知渠道与机器人配置', 'logs': '运行日志',
    'cache': '缓存清理', 'restart': '重启服务', 'agent': 'AI 助手配置',
}
CONFIG_READERS = {
    '/api/engine/config': ('GET /api/engine/config', None),
    '/api/config': ('GET /api/config', None),
    '/api/library/settings': ('GET /api/library/settings', None),
    '/api/library/navidrome': ('GET /api/library/settings', 'navidrome'),
}


def redact(value):
    if isinstance(value, dict):
        return {key: HIDDEN if not isinstance(item, bool) and re.search(r'password|passwd|secret|token|(^|_)key$|cookie|authorization|credentials|headers', key, re.I)
                and not key.endswith(('_configured', '_enabled')) and key not in {'key_configured', 'configured'}
                else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str) and '://' in value:
        def safe_url(match):
            try:
                parsed = urlsplit(match[0])
                if parsed.username or parsed.password or parsed.query and re.search(r'key|token|secret|password|auth', parsed.query, re.I):
                    return HIDDEN
            except ValueError:
                return HIDDEN
            return match[0]
        return re.sub(r'https?://[^\s<>\'\"]+', safe_url, value)
    return value


def merge_config(previous, patch):
    """Preserve fields hidden from the model when it edits an existing config."""
    value = copy.deepcopy(previous)
    for key, item in patch.items():
        if item == HIDDEN:
            continue
        value[key] = merge_config(value.get(key, {}), item) if isinstance(item, dict) and item and isinstance(value.get(key, {}), dict) else item
    return value


class ProjectOperations:
    def __init__(self, app):
        self.app = app

    def routes(self):
        result = {}
        def flatten(routes):
            for route in routes:
                if isinstance(route, APIRoute):
                    yield route
                elif hasattr(route, 'original_router'):
                    # Newer FastAPI versions retain included routers as branches.
                    yield from flatten(route.original_router.routes)
        # First route wins, just as it does in the public application router.
        for route in flatten(self.app.routes):
            if not route.path.startswith('/api/') or route.path.startswith('/api/auth/'):
                continue
            if route.path.startswith('/api/agent/') and not route.path.startswith('/api/agent/settings'):
                continue
            for method in sorted(route.methods & {'GET', 'POST', 'PUT', 'PATCH', 'DELETE'}):
                if method == 'GET' and route.path in MEDIA:
                    continue
                result.setdefault(f'{method} {route.path}', route)
        return result

    def discover(self, keyword='', operation=''):
        routes = self.routes()
        if operation:
            route = routes.get(operation)
            if route is None:
                raise HTTPException(404, '项目操作不存在，请先查询操作列表')
            schema = get_openapi(title='MeloKeep operation', version='1', routes=[route])
            method, path = operation.split(' ', 1)
            return {'operation': operation, 'schema': schema['paths'][path][method.lower()],
                    'components': schema.get('components', {}), 'detail': '请按参数定义调用；修改设置前先读取现有配置。'}
        items = []
        for name, route in routes.items():
            domain = DOMAINS.get(route.path.split('/')[2], '')
            description = f'{domain} · {route.summary or route.name}'
            if keyword and keyword.casefold() not in (name + ' ' + description).casefold():
                continue
            items.append({'operation': name, 'description': description, 'write': not name.startswith('GET ')})
        return {'operations': items, 'detail': '先用 operation 查询具体参数，再调用查询或执行工具。文件删除、应用整理和配置修改等按用户明确要求执行。'}

    async def query(self, **arguments):
        return await self.call(False, **arguments)

    async def execute(self, **arguments):
        return await self.call(True, **arguments)

    async def call(self, write, operation, path_params=None, query=None, body=None):
        route = self.routes().get(operation)
        if route is None:
            raise HTTPException(404, '项目操作不存在，请先查询操作列表')
        method, path = operation.split(' ', 1)
        if write != (method != 'GET'):
            raise HTTPException(403, '查询工具只允许 GET，修改操作必须使用执行工具并开启本轮操作权限')
        path_params, query = path_params or {}, query or {}
        if set(path_params) != set(route.param_convertors):
            raise HTTPException(400, '路径参数与接口定义不符')
        for key, value in path_params.items():
            if not isinstance(value, str) or not re.fullmatch(r'[^/\\?#%\x00-\x20]+', value) or value in {'.', '..'}:
                raise HTTPException(400, '路径参数无效')
            path = path.replace('{' + key + '}', value)
        if any(not isinstance(item, (str, int, float, bool, list)) for item in query.values()):
            raise HTTPException(400, '查询参数必须为文本、数值、布尔值或列表')
        query = {key: str(item).lower() if isinstance(item, bool) else item for key, item in query.items()}
        if method == 'PUT' and route.path in CONFIG_READERS and isinstance(body, dict):
            read_operation, field = CONFIG_READERS[route.path]
            previous = await asyncio.to_thread(self.routes()[read_operation].endpoint)
            body = merge_config(previous[field] if field else previous, body)
        # Only selected registered routes are reachable. No network, arbitrary URLs,
        # public auth bypass header, or model-supplied session credentials exist here.
        # The caller is already authorized by the AI API or channel allowlist.
        internal = FastAPI(routes=[route], openapi_url=None, docs_url=None, redoc_url=None)
        internal.state = self.app.state
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else b''
        scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
                 'method': method, 'scheme': 'http', 'path': path, 'raw_path': path.encode(),
                 'root_path': '', 'query_string': urlencode(query, doseq=True).encode(),
                 'headers': [(b'content-type', b'application/json'), (b'x-melokeep-request', b'1')],
                 'server': ('melokeep.internal', 80), 'client': ('127.0.0.1', 0)}
        status, chunks, size = 200, [], 0
        received = False

        async def receive():
            nonlocal received
            if not received:
                received = True
                return {'type': 'http.request', 'body': data, 'more_body': False}
            await asyncio.Future()

        async def send(message):
            nonlocal status, size
            if message['type'] == 'http.response.start':
                status = message['status']
            elif message['type'] == 'http.response.body':
                chunk = message.get('body', b'')
                size += len(chunk)
                if size <= 2_000_000:
                    chunks.append(chunk)

        try:
            await internal(scope, receive, send)
            if size > 2_000_000:
                raise HTTPException(502, '项目结果过大，请使用分页或缩小查询范围；已执行的操作不会回滚，请核对状态')
            result = redact(json.loads(b''.join(chunks))) if chunks else None
        except (ValueError, UnicodeError):
            raise HTTPException(502, '项目接口未返回 JSON，请通过网页查看该结果') from None
        if status >= 400:
            detail = result.get('detail', '项目接口拒绝操作') if isinstance(result, dict) else '项目接口拒绝操作'
            raise HTTPException(status, f'HTTP {status}: {detail}')
        return {'operation': operation, 'data': result, 'detail': '项目接口执行完成；后台任务是否完成请继续查询状态。'}
