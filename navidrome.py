"""Server-side OpenSubsonic client. Credentials never appear in browser media URLs."""
import hashlib
import secrets
from urllib.parse import quote, urlsplit

import requests
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator


class NavidromeSettings(BaseModel):
    enabled: bool = False
    url: str = Field(default='', max_length=2048)
    username: str = Field(default='', max_length=200)
    password: str | None = Field(default=None, max_length=1000)
    api_key: str | None = Field(default=None, max_length=1000)
    auto_scan: bool = False

    @field_validator('url')
    @classmethod
    def valid_url(cls, value):
        value = value.strip().rstrip('/')
        if value:
            parsed = urlsplit(value)
            if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError('Navidrome 地址应为不含账号、参数的 HTTP / HTTPS 地址')
        return value


class Navidrome:
    def __init__(self, settings):
        self.settings = settings

    def params(self):
        cfg = self.settings()
        if not cfg.get('enabled') or not cfg.get('url'):
            raise HTTPException(409, '请先在设置中配置并启用 Navidrome')
        params = {'v': '1.16.1', 'c': 'musicdl', 'f': 'json'}
        if cfg.get('api_key'):
            params['apiKey'] = cfg['api_key']
        else:
            if not cfg.get('username') or not cfg.get('password'):
                raise HTTPException(409, '请填写 Navidrome 用户名和密码，或 API Key')
            salt = secrets.token_hex(12)
            params.update(u=cfg['username'], s=salt, t=hashlib.md5((cfg['password'] + salt).encode()).hexdigest())
        return params

    def request(self, endpoint, *, stream=False, headers=None, **params):
        auth = self.params()
        url = self.settings()['url'] + '/rest/' + endpoint + '.view'
        try:
            response = requests.get(url, params={**params, **auth}, headers=headers or {},
                                    timeout=(5, 30), stream=stream, allow_redirects=False)
            if response.status_code not in {200, 206, 416}:
                response.close()
                raise HTTPException(502, 'Navidrome 请求失败，请检查服务地址、账号权限和网络')
            if not stream:
                with response:
                    data = response.json().get('subsonic-response', {})
                if data.get('status') != 'ok':
                    code = (data.get('error') or {}).get('code')
                    raise HTTPException(502, f'Navidrome 接口拒绝请求（错误码 {code}），请检查认证与权限')
                return data
            if 'json' in response.headers.get('Content-Type', '') or 'xml' in response.headers.get('Content-Type', ''):
                response.close()
                raise HTTPException(502, 'Navidrome 未返回可用媒体，请检查文件和账号权限')
            return response
        except (requests.RequestException, ValueError):
            raise HTTPException(502, '无法连接 Navidrome 或响应无效，请检查服务地址和网络') from None

    @staticmethod
    def track(song):
        ident = str(song['id'])
        cover_id = str(song.get('coverArt') or '')
        codec = str(song.get('suffix') or '')
        return {'id': 'navidrome-' + ident, 'source': 'navidrome', 'source_id': ident,
                'title': song.get('title') or '未知歌曲', 'artist': song.get('artist') or '',
                'album': song.get('album') or '', 'duration': float(song.get('duration') or 0),
                'cover': '/api/navidrome/cover/' + quote(cover_id, safe='') if cover_id else None,
                'size_bytes': song.get('size'), 'qualities': [],
                'playback': {'state': 'ready', 'url': '/api/navidrome/stream/' + quote(ident, safe=''),
                             'codec': codec, 'bitrate': song.get('bitRate'), 'detail': 'Navidrome 音乐库', 'preview_only': False}}

    @staticmethod
    def album(item):
        cover_id = str(item.get('coverArt') or '')
        return {'id': str(item['id']), 'name': item.get('name') or item.get('title') or '未知专辑',
                'artist': item.get('artist') or '', 'year': item.get('year'), 'song_count': item.get('songCount', 0),
                'cover': '/api/navidrome/cover/' + quote(cover_id, safe='') if cover_id else None}

    def media(self, endpoint, ident, request=None):
        headers = {}
        if request and request.headers.get('range'):
            headers['Range'] = request.headers['range']
        response = self.request(endpoint, stream=True, headers=headers, id=ident,
                                **({'format': 'raw'} if endpoint == 'stream' else {'size': 600}))
        allowed = {key: value for key, value in response.headers.items()
                   if key.lower() in {'content-length', 'content-range', 'accept-ranges', 'content-type'}}
        # Always close the upstream socket, including on client disconnect.
        def chunks():
            try:
                yield from response.iter_content(65536)
            finally:
                response.close()
        return StreamingResponse(chunks(), status_code=response.status_code, headers=allowed)

    def install(self, router, remember):
        @router.get('/api/navidrome/albums')
        def albums(offset: int = 0, size: int = 48, sort: str = 'newest'):
            if offset < 0 or not 1 <= size <= 100 or sort not in {'newest', 'alphabeticalByName', 'alphabeticalByArtist', 'recent', 'starred'}:
                raise HTTPException(400, '专辑分页或排序参数无效')
            data = self.request('getAlbumList2', type=sort, size=size, offset=offset)
            items = (data.get('albumList2') or {}).get('album') or []
            return {'albums': [self.album(item) for item in items], 'has_more': len(items) == size}

        @router.get('/api/navidrome/albums/{ident}')
        def album(ident: str):
            value = self.request('getAlbum', id=ident).get('album') or {}
            tracks = [self.track(song) for song in value.get('song') or []]
            for track in tracks:
                remember(track)
            return {**self.album(value), 'tracks': tracks}

        @router.get('/api/navidrome/artists')
        def artists():
            groups = (self.request('getArtists').get('artists') or {}).get('index') or []
            return [{'id': str(a['id']), 'name': a['name'], 'album_count': a.get('albumCount', 0)}
                    for group in groups for a in group.get('artist') or []]

        @router.get('/api/navidrome/artists/{ident}')
        def artist(ident: str):
            value = self.request('getArtist', id=ident).get('artist') or {}
            return {'name': value.get('name', ''), 'albums': [self.album(a) for a in value.get('album') or []]}

        @router.get('/api/navidrome/search')
        def search(query: str, offset: int = 0):
            if not query.strip() or len(query) > 200 or offset < 0:
                raise HTTPException(400, '请输入有效的搜索内容')
            data = self.request('search3', query=query.strip(), songCount=50, songOffset=offset,
                                albumCount=50, albumOffset=offset, artistCount=0).get('searchResult3') or {}
            tracks = [self.track(song) for song in data.get('song') or []]
            for track in tracks:
                remember(track)
            albums = [self.album(a) for a in data.get('album') or []]
            return {'tracks': tracks, 'albums': albums, 'has_more': len(tracks) == 50 or len(albums) == 50}

        @router.get('/api/navidrome/cover/{ident}')
        def cover(ident: str):
            return self.media('getCoverArt', ident)

        @router.get('/api/navidrome/stream/{ident}')
        def stream(ident: str, request: Request):
            return self.media('stream', ident, request)

        @router.post('/api/navidrome/test')
        def test():
            result = self.request('ping')
            return {'ok': True, 'version': result.get('serverVersion') or result.get('version')}

        @router.get('/api/navidrome/scan')
        def scan_status():
            return self.request('getScanStatus').get('scanStatus') or {}

        @router.post('/api/navidrome/scan')
        def scan():
            return self.request('startScan').get('scanStatus') or {}
