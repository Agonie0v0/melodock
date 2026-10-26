"""Metadata-only queries using the installed musicdl providers, without audio parsing."""
import base64
import copy
import hashlib
import html
import os
import re
import threading
import time
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import urlsplit

import requests

SOURCES = {'netease': 'NeteaseMusicClient', 'qq': 'QQMusicClient', 'migu': 'MiguMusicClient',
           'kugou': 'KugouMusicClient', 'kuwo': 'KuwoMusicClient'}
SOURCE_CATALOG = [
    {'id': 'netease', 'label': '网易云', 'description': '中文歌曲、平台专辑与同步歌词',
     'fields': ['title', 'artist', 'album', 'date', 'track_number', 'disc_number', 'cover', 'lyrics'],
     'note': '复用音源 Cookie、代理与请求设置；部分歌曲资料受平台限制。', 'url': 'https://music.163.com/'},
    {'id': 'qq', 'label': 'QQ音乐', 'description': '中文歌曲、专辑资料与歌词',
     'fields': ['title', 'artist', 'album', 'date', 'track_number', 'disc_number', 'cover', 'lyrics'],
     'note': '复用音源 Cookie、代理与请求设置；并非每首歌曲都返回全部字段。', 'url': 'https://y.qq.com/'},
    {'id': 'musicbrainz', 'label': 'MusicBrainz', 'description': '国际音乐与不同发行版本的结构化资料',
     'fields': ['title', 'artist', 'album', 'album_artist', 'date', 'track_number', 'disc_number', 'cover'],
     'note': '无需账号；封面来自 Cover Art Archive，不提供歌词。社区资料可能缺失，多个发行版本需人工确认。',
     'url': 'https://musicbrainz.org/'},
]
SOURCE_CATALOG.extend([
    {'id': key, 'label': label, 'description': description,
     'fields': ['title', 'artist', 'album', 'cover', 'lyrics'],
     'note': '只查询资料，不解析下载链接；复用对应平台请求设置。平台接口可能限流或缺少字段。', 'url': url}
    for key, label, description, url in [
        ('migu', '咪咕音乐', '中文歌曲、封面与歌词', 'https://music.migu.cn/'),
        ('kugou', '酷狗音乐', '歌曲与专辑资料、同步歌词', 'https://www.kugou.com/'),
        ('kuwo', '酷我音乐', '歌曲资料、封面与逐行歌词', 'https://www.kuwo.cn/'),
    ]
])
SOURCE_CATALOG.append({'id': 'acoustid', 'label': 'AcoustID 指纹', 'description': '通过音频内容识别，适合文件名和标签缺失的歌曲',
                       'fields': ['title', 'artist', 'album', 'album_artist', 'date', 'track_number', 'disc_number', 'cover'],
                       'note': '需要 fpcalc 和 AcoustID 应用 Key；指纹查询返回 MusicBrainz 录音，发行版本仍需审核。不上传音频。',
                       'url': 'https://acoustid.org/'} )
LABELS = {source['id']: source['label'] for source in SOURCE_CATALOG}
VERSIONS = {
    'live': r'\blive\b|现场|演唱会', 'remix': r'\bremix\b|混音',
    'instrumental': r'\binstrumental\b|伴奏|纯音乐', 'cover': r'\bcover\b|翻唱',
    'acoustic': r'\bacoustic\b|不插电',
}


def clean(value):
    value = str(value or '').strip()
    return '' if value.casefold() in {'none', 'null', '未知', '未知歌手', '未知专辑'} else value


def normalized(value):
    return re.sub(r'[\W_]+', '', unicodedata.normalize('NFKC', clean(value)).casefold())


def version_flags(value):
    return {key for key, pattern in VERSIONS.items() if re.search(pattern, clean(value), re.I)}


def from_song(song):
    raw = song.raw_data.get('search') or {}
    return from_row(song.source, raw, fallback={
        'title': song.song_name, 'artist': song.singers, 'album': song.album,
        'duration': song.duration_s, 'cover_url': song.cover_url, 'lyrics': song.lyric,
        'source_id': str(song.identifier or ''),
    })


def from_row(source, row, fallback=None):
    fallback = fallback or {}
    row = row if isinstance(row, dict) else {}
    source = next((key for key, name in SOURCES.items() if source == name), source)
    if source in {'migu', 'kugou', 'kuwo'}:
        singers = row.get('singers') or row.get('singerList') or []
        albums = row.get('albums') or []
        title = row.get('songName') or row.get('SongName') or row.get('SONGNAME') or row.get('name') or row.get('songname')
        artist = row.get('SingerName') or row.get('singername') or row.get('ARTIST') or row.get('artist')
        artist = artist or ', '.join(s.get('name', '') for s in singers if isinstance(s, dict))
        album = row.get('AlbumName') or row.get('album_name') or row.get('ALBUM') or row.get('album')
        album = album if isinstance(album, str) else ''
        album = album or ', '.join(a.get('name', '') for a in albums if isinstance(a, dict))
        duration = row.get('Duration') or row.get('duration') or row.get('DURATION') or 0
        if isinstance(duration, str) and ':' in duration:
            parts = duration.split(':')
            duration = sum(float(v) * 60 ** i for i, v in enumerate(reversed(parts)))
        cover = row.get('Image') or row.get('cover_url') or row.get('pic') or row.get('hts_MVPIC')
        cover = cover or next((row.get(k) for k in ('img3', 'img2', 'img1') if row.get(k)), '')
        if not cover and row.get('imgItems'):
            cover = row['imgItems'][-1].get('img', '')
        def text(value):
            return html.unescape(re.sub('<[^>]+>', '', clean(value)))
        result = {**fallback, 'source': source,
                  'source_id': str(row.get('copyrightId') or row.get('FileHash') or row.get('hash') or row.get('MUSICRID') or row.get('id') or fallback.get('source_id') or '').removeprefix('MUSIC_'),
                  '_raw': row, 'title': text(title) or fallback.get('title', ''), 'artist': text(artist) or fallback.get('artist', ''),
                  'album': text(album) or fallback.get('album', ''), 'duration': float(duration or fallback.get('duration') or 0),
                  'cover_url': str(cover or fallback.get('cover_url') or '').replace('{size}', '800')}
        return result
    album = row.get('al') or row.get('album') or {}
    album = album if isinstance(album, dict) else {'name': str(album)}
    artists = row.get('ar') or row.get('artists') or row.get('singer') or []
    artists = artists if isinstance(artists, list) else []
    artist = ', '.join(a.get('name', '') for a in artists if isinstance(a, dict))
    cover = album.get('picUrl') or row.get('cover_url')
    if not cover and source == 'qq' and album.get('mid'):
        cover = f'https://y.gtimg.cn/music/photo_new/T002R800x800M000{album["mid"]}.jpg'
    date = row.get('time_public') or row.get('publishDate') or ''
    if not date and (stamp := row.get('publishTime')) and isinstance(stamp, (float, int)) and stamp > 0:
        try:
            date = datetime.fromtimestamp(stamp / 1000, timezone.utc).strftime('%Y-%m-%d')
        except (OverflowError, ValueError, OSError):
            pass
    result = {**fallback, 'source': source,
              'source_id': str(row.get('mid') or row.get('id') or fallback.get('source_id') or ''),
              'title': row.get('name') or row.get('title') or fallback.get('title') or '',
              'artist': artist or fallback.get('artist') or '',
              'album': album.get('name') or album.get('title') or fallback.get('album') or '',
              'cover_url': cover or fallback.get('cover_url') or '',
              'date': str(date or fallback.get('date') or ''),
              'track_number': str(row.get('no') or row.get('index_album') or fallback.get('track_number') or ''),
              'disc_number': str(row.get('cd') or row.get('index_cd') or fallback.get('disc_number') or ''),
              'duration': float(row.get('interval') or (row.get('dt') or row.get('duration') or 0) / 1000 or fallback.get('duration') or 0)}
    # Do not guess album artist from a track artist: compilations differ.
    return {key: clean(value) if isinstance(value, str) else value for key, value in result.items()}


def rank(reference, candidate):
    reasons, conflicts = [], []
    title, other = normalized(reference.get('title')), normalized(candidate.get('title'))
    similarity = SequenceMatcher(None, title, other).ratio() if title and other else 0
    score = similarity * 45
    if title and title == other:
        reasons.append('标题一致')
    elif similarity < .85:
        conflicts.append('标题不同')
    artists = normalized(reference.get('artist'))
    other_artists = normalized(candidate.get('artist'))
    artist_match = bool(artists and other_artists and (artists == other_artists or
                        SequenceMatcher(None, artists, other_artists).ratio() >= .9))
    if artist_match:
        score += 30
        reasons.append('歌手一致')
    elif artists:
        conflicts.append('歌手不同')
    album = normalized(reference.get('album'))
    other_album = normalized(candidate.get('album'))
    if album and album == other_album:
        score += 15
        reasons.append('专辑一致')
    elif album and other_album:
        conflicts.append('专辑不同')
    duration = float(reference.get('duration') or 0)
    other_duration = float(candidate.get('duration') or 0)
    if duration and other_duration:
        if abs(duration - other_duration) <= 3:
            score += 10
            reasons.append('时长接近')
        elif abs(duration - other_duration) > max(8, duration * .04):
            conflicts.append('时长差异较大')
    if version_flags(f"{reference.get('title', '')} {reference.get('version', '')}") != version_flags(f"{candidate.get('title', '')} {candidate.get('version', '')}"):
        conflicts.append('歌曲版本不同')
    trusted = (reference.get('source') == candidate.get('source') and
               bool(reference.get('source_id')) and reference['source_id'] == candidate.get('source_id'))
    if trusted and not conflicts:
        score = 100
        reasons.insert(0, '下载来源 ID 一致')
    confident = not conflicts and (trusted or (similarity >= .96 and artist_match and score >= 85))
    if candidate.get('source') == 'acoustid' and float(candidate.get('fingerprint_score') or 0) >= .9:
        conflicts = [c for c in conflicts if c in {'专辑不同', '时长差异较大'}]
        score, reasons, confident = 98, ['音频指纹高度匹配；发行版本需核对'], not conflicts
    return {**candidate, 'score': round(score), 'reasons': reasons, 'conflicts': conflicts, 'confident': confident,
            'id': hashlib.sha256(f'{candidate.get("source")}|{candidate.get("source_id")}|{candidate.get("release_id", "")}|{candidate.get("album")}'.encode()).hexdigest()[:20]}


def pick(reference, candidates):
    ranked = sorted((rank(reference, item) for item in candidates), key=lambda c: c['score'], reverse=True)
    unique = list({item['id']: item for item in reversed(ranked)}.values())
    unique.sort(key=lambda c: c['score'], reverse=True)
    chosen = unique[0] if unique and unique[0]['confident'] else None
    if chosen and len(unique) > 1 and unique[1]['confident'] and chosen['score'] - unique[1]['score'] < 5:
        if normalized(chosen.get('album')) != normalized(unique[1].get('album')) or (
                chosen.get('release_id') and unique[1].get('release_id') and chosen['release_id'] != unique[1]['release_id']):
            chosen = None
    return unique[:12], chosen


class MetadataScraper:
    def __init__(self, engine_config):
        self.engine_config = engine_config
        self.mb_lock = threading.Lock()
        self.mb_next_request = 0
        self.credentials = lambda: {}

    def search_platform(self, source, query):
        _, provider, overrides = self.provider(source)
        url = provider._constructsearchurls(query)[0]
        response = provider.get(url, **{**overrides, 'timeout': 12})
        response.raise_for_status()
        data = response.json()
        rows = (data.get('data') or {}).get('lists', []) if source == 'kugou' else data.get('abslist', []) if source == 'kuwo' else (data.get('songResultData') or {}).get('result', [])
        return [from_row(source, row) for row in rows[:8]]

    def artist_artwork(self, name):
        _, provider, overrides = self.provider('netease')
        response = provider.get('https://music.163.com/api/search/get',
                                **{**overrides, 'timeout': 12, 'params': {'s': name, 'type': 100, 'limit': 10}})
        response.raise_for_status()
        matches = [row for row in (response.json().get('result') or {}).get('artists', [])
                   if unicodedata.normalize('NFKC', clean(row.get('name'))).casefold() == unicodedata.normalize('NFKC', clean(name)).casefold() and row.get('picUrl')]
        if len(matches) != 1:
            raise ValueError('未找到唯一的同名艺术家图片，请核对歌手标签')
        return matches[0]['picUrl']

    def search_fingerprint(self, reference):
        from audio_tools import fingerprint
        key = self.credentials().get('acoustid_key') or os.getenv('MUSICDL_ACOUSTID_KEY')
        if not key:
            raise ValueError('请先配置 AcoustID 应用 Key')
        if not reference.get('_path'):
            raise ValueError('指纹识别需要本地音频')
        fp = fingerprint(reference['_path'])
        cfg = self.engine_config()
        proxy = cfg.get('proxy_url') if cfg.get('proxy_scope') == 'all' else None
        response = requests.post('https://api.acoustid.org/v2/lookup',
                                 data={'client': key, 'duration': int(fp['duration']), 'fingerprint': fp['fingerprint'],
                                       'meta': 'recordings releases'}, timeout=(5, 20), proxies={'http': proxy, 'https': proxy} if proxy else {})
        response.raise_for_status()
        data = response.json()
        if data.get('status') != 'ok':
            raise ValueError('AcoustID 查询失败，请检查应用 Key')
        candidates = []
        for match in data.get('results', [])[:3]:
            if float(match.get('score') or 0) < .7:
                continue
            for recording in match.get('recordings', [])[:4]:
                for release in (recording.get('releases') or [{}])[:5]:
                    candidates.append({'source': 'acoustid', 'source_id': recording['id'], 'release_id': release.get('id', ''),
                                       'title': recording.get('title', ''),
                                       'artist': ', '.join(a.get('name', '') for a in recording.get('artists', [])),
                                       'album': release.get('title', ''), 'duration': recording.get('duration') or fp['duration'],
                                       'fingerprint_score': float(match['score'])})
        return candidates

    def musicbrainz(self, path, params):
        cfg = self.engine_config()
        proxy = cfg.get('proxy_url') if cfg.get('proxy_scope') == 'all' else None
        # MusicBrainz permits one request per second for each application/IP.
        with self.mb_lock:
            time.sleep(max(0, self.mb_next_request - time.monotonic()))
            self.mb_next_request = time.monotonic() + 1.1
            response = requests.get(f'https://musicbrainz.org/ws/2/{path}', params={**params, 'fmt': 'json'},
                                    headers={'User-Agent': 'MeloDock/3.0 (https://github.com/Agonie0v0/melodock)'},
                                    proxies={'http': proxy, 'https': proxy} if proxy else {}, timeout=(5, 12))
            response.raise_for_status()
            return response.json()

    @staticmethod
    def artist_credit(row):
        return ''.join((credit.get('name') or (credit.get('artist') or {}).get('name') or '') + credit.get('joinphrase', '')
                       for credit in row.get('artist-credit', []) if isinstance(credit, dict)).strip()

    def search_musicbrainz(self, reference):
        def quoted(value):
            return re.sub(r'([\\"])', r'\\\1', clean(value))
        query = f'recording:"{quoted(reference.get("title"))}"'
        if clean(reference.get('artist')):
            query += f' AND artist:"{quoted(reference["artist"])}"'
        data = self.musicbrainz('recording', {'query': query, 'limit': 8})
        candidates = []
        for row in data.get('recordings', []):
            for release in row.get('releases', [])[:4]:
                candidates.append({
                    'source': 'musicbrainz', 'source_id': row['id'], 'release_id': release['id'],
                    'title': row.get('title', ''), 'artist': self.artist_credit(row),
                    'album': release.get('title', ''), 'album_artist': self.artist_credit(release),
                    'date': release.get('date', ''), 'duration': float(row.get('length') or 0) / 1000,
                    'version': row.get('disambiguation', ''),
                })
        return candidates

    def enrich_musicbrainz(self, candidate):
        result, warnings = dict(candidate), []
        release_id = candidate.get('release_id', '')
        if not re.fullmatch(r'[0-9a-fA-F-]{36}', release_id):
            return result, ['MusicBrainz 发行版本 ID 无效']
        try:
            release = self.musicbrainz(f'release/{release_id}', {'inc': 'recordings+artist-credits'})
            result.update(album=release.get('title') or result.get('album', ''),
                          album_artist=self.artist_credit(release), date=release.get('date') or result.get('date', ''))
            matches = [(medium, track) for medium in release.get('media', []) for track in medium.get('tracks', [])
                       if (track.get('recording') or {}).get('id') == candidate['source_id']]
            if len(matches) == 1:
                medium, track = matches[0]
                result.update(track_number=str(track.get('position') or ''), disc_number=str(medium.get('position') or ''))
            if (release.get('cover-art-archive') or {}).get('front'):
                result['cover_url'] = f'https://coverartarchive.org/release/{release_id}/front-500'
        except Exception as error:
            warnings.append(f'MusicBrainz 发行资料获取失败（{type(error).__name__}）')
        return result, warnings

    def provider(self, source):
        import engine_worker
        cfg = copy.deepcopy(self.engine_config())
        cfg['request_timeout'] = min(int(cfg.get('request_timeout') or 10), 12)
        cfg.setdefault('global_client_cfg', {})['search_size_per_source'] = 8
        cfg['global_client_cfg']['search_size_per_page'] = 10
        cfg['_musicdl_candidates'] = True
        client = engine_worker.client_for(cfg, SOURCES[source])
        return cfg, client.music_clients[SOURCES[source]], client.requests_overrides[SOURCES[source]]

    def search(self, reference, sources):
        import engine_worker
        candidates, warnings = [], []
        query = reference.get('_query') or ' '.join(filter(None, [clean(reference.get('title')), clean(reference.get('artist'))]))
        if not query and sources != ['acoustid']:
            return [], ['缺少标题，请先编辑标签或从文件名提取']
        for source in sorted(sources, key=lambda source: source != 'acoustid'):
            try:
                if source == 'musicbrainz':
                    found = self.search_musicbrainz(reference)
                elif source == 'acoustid':
                    found = self.search_fingerprint(reference)
                    reliable = [row for row in found if row.get('fingerprint_score', 0) >= .9]
                    if not reference.get('_query') and reliable and len({row['source_id'] for row in reliable}) == 1:
                        query = ' '.join(filter(None, [reliable[0].get('title'), reliable[0].get('artist')]))
                elif source in {'migu', 'kugou', 'kuwo'}:
                    found = self.search_platform(source, query)
                else:
                    cfg, _, _ = self.provider(source)
                    found = [from_song(song) for song in engine_worker.search(cfg, SOURCES[source], query)]
                candidates.extend(found)
                if not found:
                    warnings.append(f'{LABELS.get(source, source)}未找到候选')
            except Exception as error:
                warnings.append(f'{LABELS.get(source, source)}查询失败：{str(error)[:150] if isinstance(error, ValueError) else type(error).__name__}')
        return candidates, warnings

    def enrich(self, candidate, want_lyrics=True, alternatives=()):
        result, warnings = self._enrich(dict(candidate), want_lyrics)
        # Only borrow missing fields from an independently confident, unambiguous match.
        # Never combine different albums or different live/remix versions.
        _, fallback = pick(candidate, [c for c in alternatives
                                      if c.get('id') != candidate.get('id') and c.get('source') in LABELS
                                      and clean(candidate.get('album'))
                                      and not (candidate.get('release_id') and c.get('release_id') and candidate['release_id'] != c['release_id'])
                                      and normalized(c.get('album')) == normalized(candidate.get('album'))])
        fields = ['album_artist', 'date', 'track_number', 'disc_number', 'cover_url']
        if want_lyrics:
            fields.append('lyrics')
        if fallback:
            supported = next(source['fields'] for source in SOURCE_CATALOG if source['id'] == fallback['source'])
            fields = [field for field in fields if ('cover' if field == 'cover_url' else field) in supported]
        if fallback and any(not clean(result.get(field)) for field in fields):
            extra, extra_warnings = self._enrich(fallback, want_lyrics and not clean(result.get('lyrics')))
            warnings.extend(extra_warnings)
            provenance = dict(result.get('field_sources') or {})
            for field in fields:
                if not clean(result.get(field)) and clean(extra.get(field)):
                    result[field] = extra[field]
                    provenance[field] = fallback['source']
            if provenance:
                result['field_sources'] = provenance
            if clean(result.get('lyrics')):
                warnings = [w for w in warnings if not w.startswith('MusicBrainz 不提供歌词')]
        return result, warnings

    def _enrich(self, candidate, want_lyrics=True):
        source = candidate.get('source')
        if source in {'musicbrainz', 'acoustid'}:
            result, warnings = self.enrich_musicbrainz(candidate)
            if want_lyrics:
                warnings.append('MusicBrainz 不提供歌词；可选择其他平台候选补全歌词')
            return result, warnings
        if source not in SOURCES:
            return candidate, []
        warnings = []
        result = dict(candidate)
        try:
            _, provider, overrides = self.provider(source)
            options = {**overrides, 'timeout': 12}
        except Exception as error:
            return result, [f'补充来源不可用（{type(error).__name__}）']
        try:
            row = provider._getsongmetainfo(candidate['source_id'], options) if source != 'migu' else candidate.get('_raw')
            if row:
                result = from_row(source, row, result)
        except Exception as error:
            warnings.append(f'补充详情失败（{type(error).__name__}）')
        if want_lyrics and not clean(result.get('lyrics')):
            try:
                if source == 'netease':
                    response = provider.get('https://music.163.com/api/song/lyric',
                                            **{**options, 'params': {'id': candidate['source_id'], 'lv': -1, 'kv': -1, 'tv': -1}})
                    response.raise_for_status()
                    data = response.json()
                    result['lyrics'] = (data.get('lrc') or {}).get('lyric', '')
                elif source == 'qq':
                    response = provider.get('https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg',
                                            **{**options, 'params': {'songmid': candidate['source_id'], 'format': 'json', 'nobase64': 1},
                                               'headers': {**options.get('headers', {}), 'Referer': 'https://y.qq.com/'}})
                    response.raise_for_status()
                    data = response.json()
                    lyric = data.get('lyric') or ''
                    if lyric and '[' not in lyric and '\n' not in lyric:
                        lyric = base64.b64decode(lyric).decode('utf-8')
                    result['lyrics'] = html.unescape(lyric)
                elif source == 'kuwo':
                    response = provider.get('https://m.kuwo.cn/newh5/singles/songinfoandlrc',
                                            **{**options, 'params': {'musicId': candidate['source_id']}})
                    response.raise_for_status()
                    lines = (response.json().get('data') or {}).get('lrclist') or []
                    result['lyrics'] = '\n'.join(f'[{int(float(l.get("time") or 0)) // 60:02d}:{float(l.get("time") or 0) % 60:05.2f}]{l.get("lineLyric", "")}' for l in lines)
                elif source == 'kugou':
                    response = provider.get('https://lyrics.kugou.com/search', **{**options, 'params': {
                        'ver': 1, 'man': 'yes', 'client': 'pc', 'hash': candidate['source_id'],
                        'keyword': result.get('title', ''), 'duration': int(float(result.get('duration') or 0) * 1000)}})
                    response.raise_for_status()
                    choices = response.json().get('candidates') or []
                    if choices:
                        response = provider.get('https://lyrics.kugou.com/download', **{**options, 'params': {
                            'ver': 1, 'client': 'pc', 'id': choices[0]['id'], 'accesskey': choices[0]['accesskey'], 'fmt': 'lrc', 'charset': 'utf8'}})
                        response.raise_for_status()
                        result['lyrics'] = base64.b64decode(response.json().get('content') or '').decode('utf-8')
                elif source == 'migu':
                    url = (candidate.get('_raw') or {}).get('lrcUrl') or (candidate.get('_raw') or {}).get('lyricUrl')
                    if url:
                        response = provider.get(url, **options)
                        response.raise_for_status()
                        result['lyrics'] = response.content.decode('utf-8-sig')[:2_000_000]
                if not clean(result.get('lyrics')):
                    warnings.append('来源未提供歌词')
            except Exception as error:
                warnings.append(f'歌词获取失败（{type(error).__name__}）')
        return result, warnings

    def cover(self, url):
        parsed = urlsplit(url)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username:
            raise ValueError('封面地址无效')
        cfg = self.engine_config()
        proxy = cfg.get('proxy_url') if cfg.get('proxy_scope') == 'all' else None
        with requests.get(url, stream=True, timeout=(5, 15), proxies={'http': proxy, 'https': proxy} if proxy else {},
                          headers={'User-Agent': 'MeloDock/3.0'}, allow_redirects=True) as response:
            response.raise_for_status()
            chunks, length = [], 0
            for chunk in response.iter_content(65536):
                length += len(chunk)
                if length > 8 * 1024 * 1024:
                    raise ValueError('封面超过 8 MB')
                chunks.append(chunk)
        data = b''.join(chunks)
        mime = 'image/png' if data.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if data.startswith(b'\xff\xd8\xff') else ''
        if not mime:
            raise ValueError('封面不是有效的 PNG/JPEG 图片')
        return data, mime
