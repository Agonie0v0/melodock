"""Server-side OpenSubsonic client. Credentials never appear in browser media URLs."""
import hashlib
import math
import json
import secrets
from datetime import datetime
from urllib.parse import quote, urlsplit

import requests
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from typing import Annotated


class NavidromeSettings(BaseModel):
    enabled: bool = False
    url: str = Field(default='', max_length=2048)
    username: str = Field(default='', max_length=200)
    password: str | None = Field(default=None, max_length=1000)
    api_key: str | None = Field(default=None, max_length=1000)
    auto_scan: bool = False
    delete_enabled: bool = False
    music_root: str = Field(default='', max_length=2048)
    server_music_root: str = Field(default='', max_length=2048)

    @field_validator('url')
    @classmethod
    def valid_url(cls, value):
        value = value.strip().rstrip('/')
        if value:
            parsed = urlsplit(value)
            if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError('Navidrome 地址应为不含账号、参数的 HTTP / HTTPS 地址')
        return value


class PlaylistName(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator('name')
    @classmethod
    def valid_name(cls, value):
        if not value.strip():
            raise ValueError('请输入歌单名称')
        return value.strip()


class PlaylistSongs(BaseModel):
    song_ids: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(min_length=1, max_length=3000)


class PlaylistCreate(PlaylistName):
    song_ids: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(default_factory=list, max_length=3000)


class PlaylistRemove(BaseModel):
    indexes: list[Annotated[int, Field(ge=0, strict=True)]] = Field(min_length=1, max_length=3000)
    revision: str = Field(min_length=64, max_length=64)


class Navidrome:
    def __init__(self, settings):
        self.settings = settings

    def params(self):
        cfg = self.settings()
        if not cfg.get('enabled') or not cfg.get('url'):
            raise HTTPException(409, '请先在设置中配置并启用 Navidrome')
        params = {'v': '1.16.1', 'c': 'melokeep', 'f': 'json'}
        if cfg.get('api_key'):
            params['apiKey'] = cfg['api_key']
        else:
            if not cfg.get('username') or not cfg.get('password'):
                raise HTTPException(409, '请填写 Navidrome 用户名和密码，或 API Key')
            salt = secrets.token_hex(12)
            params.update(u=cfg['username'], s=salt, t=hashlib.md5((cfg['password'] + salt).encode()).hexdigest())
        return params

    def request(self, endpoint, *, stream=False, headers=None, method='GET', **params):
        auth = self.params()
        url = self.settings()['url'] + '/rest/' + endpoint + '.view'
        try:
            options = {'headers': headers or {}, 'timeout': (5, 30), 'stream': stream, 'allow_redirects': False}
            response = (requests.post(url, data={**params, **auth}, **options) if method == 'POST'
                        else requests.get(url, params={**params, **auth}, **options))
            if response.status_code not in {200, 206, 416}:
                response.close()
                raise HTTPException(502, 'Navidrome 请求失败，请检查服务地址、账号权限和网络')
            if not stream:
                with response:
                    data = response.json().get('subsonic-response', {})
                if data.get('status') != 'ok':
                    code = (data.get('error') or {}).get('code')
                    if code == 50:
                        raise HTTPException(403, '当前 Navidrome 账号没有此操作权限')
                    if code == 70:
                        raise HTTPException(404, 'Navidrome 歌单或歌曲不存在，请刷新后重试')
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

    def lyrics(self, ident, *, artist='', title=''):
        """Prefer song-specific timing over the legacy artist/title text lookup."""
        try:
            data = self.request('getLyricsBySongId', id=ident)
        except HTTPException:
            data = {}
        plain = ''
        for entry in (data.get('lyricsList') or {}).get('structuredLyrics') or []:
            if not isinstance(entry, dict):
                continue
            rows = [row for row in entry.get('line') or [] if isinstance(row, dict) and isinstance(row.get('value'), str)]
            text = '\n'.join(row['value'] for row in rows).strip()
            if not text:
                continue
            plain = plain or text
            if entry.get('synced') is not True:
                continue
            offset = entry.get('offset') or 0
            if not isinstance(offset, (int, float)) or not math.isfinite(offset):
                offset = 0
            timed = []
            for row in rows:
                start = row.get('start')
                if not isinstance(start, (int, float)) or isinstance(start, bool) or not math.isfinite(start) or start < 0:
                    continue
                # OpenSubsonic offset is milliseconds: positive means earlier.
                milliseconds = max(0, round(start - offset))
                minutes, remainder = divmod(milliseconds, 60000)
                seconds, fraction = divmod(remainder, 1000)
                timed.append(f'[{minutes:02}:{seconds:02}.{fraction:03}]{row["value"]}')
            if timed:
                return '\n'.join(timed)
        if plain:
            return plain
        try:
            return (self.request('getLyrics', artist=artist, title=title).get('lyrics') or {}).get('value') or ''
        except HTTPException:
            return ''

    @staticmethod
    def album(item):
        cover_id = str(item.get('coverArt') or '')
        return {'id': str(item['id']), 'name': item.get('name') or item.get('title') or '未知专辑',
                'artist': item.get('artist') or '', 'year': item.get('year'), 'song_count': item.get('songCount', 0),
                'cover': '/api/navidrome/cover/' + quote(cover_id, safe='') if cover_id else None}

    def playlist(self, item):
        cover_id = str(item.get('coverArt') or '')
        try:
            created = int(datetime.fromisoformat(item.get('created') or '').timestamp())
        except (ValueError, TypeError, OverflowError):
            created = 0
        owner, username = item.get('owner') or '', self.settings().get('username') or ''
        can_manage = not owner or not username or owner.casefold() == username.casefold()
        return {'id': 'navidrome:' + str(item['id']), 'name': item.get('name') or '未命名歌单',
                'source': 'navidrome', 'source_url': '', 'created_at': created,
                'track_count': item.get('songCount', 0), 'issue_count': 0,
                'cover': '/api/navidrome/cover/' + quote(cover_id, safe='') if cover_id else None,
                'read_only': item.get('readonly') is True or not can_manage, 'can_manage': can_manage,
                'owner': owner, 'task_id': '', 'detail': '与 Navidrome 同步，修改直接保存到服务器。'}

    @staticmethod
    def playlist_revision(item):
        value = [str(item['id']), item.get('changed'), [str(song['id']) for song in item.get('entry') or []]]
        return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()

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
        @router.get('/api/navidrome/playlists')
        def playlists():
            if not self.settings().get('enabled'):
                return []
            items = (self.request('getPlaylists').get('playlists') or {}).get('playlist') or []
            return [self.playlist(item) for item in items]

        @router.get('/api/navidrome/playlists/{ident}')
        def playlist(ident: str):
            item = self.request('getPlaylist', id=ident).get('playlist') or {}
            if not item.get('id'):
                raise HTTPException(404, 'Navidrome 歌单不存在或无权访问')
            tracks = [{**self.track(song), 'playlist_index': index} for index, song in enumerate(item.get('entry') or [])]
            for track in tracks:
                remember(track)
            return {**self.playlist(item), 'revision': self.playlist_revision(item), 'tracks': tracks, 'issues': []}

        @router.post('/api/navidrome/playlists')
        def create_playlist(body: PlaylistCreate):
            item = self.request('createPlaylist', method='POST', name=body.name, songId=body.song_ids).get('playlist') or {}
            if not item.get('id'):
                raise HTTPException(502, 'Navidrome 未返回新歌单，请同步歌单确认结果后再试')
            return playlist(str(item['id']))

        @router.patch('/api/navidrome/playlists/{ident}')
        def rename_playlist(ident: str, body: PlaylistName):
            current = playlist(ident)
            if not current['can_manage']:
                raise HTTPException(403, '只能修改自己拥有的 Navidrome 歌单')
            self.request('updatePlaylist', method='POST', playlistId=ident, name=body.name)
            return playlist(ident)

        @router.delete('/api/navidrome/playlists/{ident}')
        def delete_playlist(ident: str):
            if not playlist(ident)['can_manage']:
                raise HTTPException(403, '只能删除自己拥有的 Navidrome 歌单')
            self.request('deletePlaylist', method='POST', id=ident)
            return {'success': True}

        @router.post('/api/navidrome/playlists/{ident}/tracks')
        def add_songs(ident: str, body: PlaylistSongs):
            if playlist(ident)['read_only']:
                raise HTTPException(403, '此 Navidrome 歌单为只读或当前账号无编辑权限')
            self.request('updatePlaylist', method='POST', playlistId=ident, songIdToAdd=body.song_ids)
            return playlist(ident)

        @router.post('/api/navidrome/playlists/{ident}/tracks/remove')
        def remove_songs(ident: str, body: PlaylistRemove):
            current = playlist(ident)
            if current['read_only']:
                raise HTTPException(403, '此 Navidrome 歌单为只读或当前账号无编辑权限')
            if current['revision'] != body.revision:
                raise HTTPException(409, 'Navidrome 歌单已变化，请同步歌单后重新选择要移除的歌曲')
            if any(index >= len(current['tracks']) for index in body.indexes):
                raise HTTPException(400, '歌单歌曲位置无效，请同步歌单后重试')
            self.request('updatePlaylist', method='POST', playlistId=ident,
                         songIndexToRemove=sorted(set(body.indexes), reverse=True))
            return playlist(ident)

        @router.get('/api/navidrome/songs')
        def songs(offset: int = 0, size: int = 50):
            if offset < 0 or not 1 <= size <= 100:
                raise HTTPException(400, '歌曲分页参数无效')
            items = (self.request('search3', query='', songCount=size + 1, songOffset=offset,
                                  albumCount=0, artistCount=0).get('searchResult3') or {}).get('song') or []
            tracks = [self.track(song) for song in items[:size]]
            for track in tracks:
                remember(track)
            return {'tracks': tracks, 'has_more': len(items) > size}

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
