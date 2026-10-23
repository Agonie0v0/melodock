"""Metadata-only queries using the installed musicdl providers, without audio parsing."""
import base64
import copy
import hashlib
import html
import re
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import urlsplit

import requests

SOURCES = {'netease': 'NeteaseMusicClient', 'qq': 'QQMusicClient'}
LABELS = {'netease': '网易云', 'qq': 'QQ音乐'}
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
    if album and album == normalized(candidate.get('album')):
        score += 15
        reasons.append('专辑一致')
    duration = float(reference.get('duration') or 0)
    other_duration = float(candidate.get('duration') or 0)
    if duration and other_duration:
        if abs(duration - other_duration) <= 3:
            score += 10
            reasons.append('时长接近')
        elif abs(duration - other_duration) > max(8, duration * .04):
            conflicts.append('时长差异较大')
    if version_flags(reference.get('title')) != version_flags(candidate.get('title')):
        conflicts.append('歌曲版本不同')
    trusted = (reference.get('source') == candidate.get('source') and
               bool(reference.get('source_id')) and reference['source_id'] == candidate.get('source_id'))
    if trusted and not conflicts:
        score = 100
        reasons.insert(0, '下载来源 ID 一致')
    confident = not conflicts and (trusted or (similarity >= .96 and artist_match and score >= 85))
    return {**candidate, 'score': round(score), 'reasons': reasons, 'conflicts': conflicts, 'confident': confident,
            'id': hashlib.sha256(f'{candidate.get("source")}|{candidate.get("source_id")}|{candidate.get("album")}'.encode()).hexdigest()[:20]}


def pick(reference, candidates):
    ranked = sorted((rank(reference, item) for item in candidates), key=lambda c: c['score'], reverse=True)
    unique = list({item['id']: item for item in reversed(ranked)}.values())
    unique.sort(key=lambda c: c['score'], reverse=True)
    chosen = unique[0] if unique and unique[0]['confident'] else None
    if chosen and len(unique) > 1 and unique[1]['confident'] and chosen['score'] - unique[1]['score'] < 5:
        if normalized(chosen.get('album')) != normalized(unique[1].get('album')):
            chosen = None
    return unique[:12], chosen


class MetadataScraper:
    def __init__(self, engine_config):
        self.engine_config = engine_config

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
        query = ' '.join(filter(None, [clean(reference.get('title')), clean(reference.get('artist'))]))
        if not query:
            return [], ['缺少标题，请先编辑标签或从文件名提取']
        for source in sources:
            try:
                cfg, _, _ = self.provider(source)
                candidates.extend(from_song(song) for song in engine_worker.search(cfg, SOURCES[source], query))
            except Exception as error:
                warnings.append(f'{LABELS.get(source, source)}查询失败（{type(error).__name__}）')
        return candidates, warnings

    def enrich(self, candidate, want_lyrics=True):
        source = candidate.get('source')
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
            row = provider._getsongmetainfo(candidate['source_id'], options)
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
                else:
                    response = provider.get('https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg',
                                            **{**options, 'params': {'songmid': candidate['source_id'], 'format': 'json', 'nobase64': 1},
                                               'headers': {**options.get('headers', {}), 'Referer': 'https://y.qq.com/'}})
                    response.raise_for_status()
                    data = response.json()
                    lyric = data.get('lyric') or ''
                    if lyric and '[' not in lyric and '\n' not in lyric:
                        lyric = base64.b64decode(lyric).decode('utf-8')
                    result['lyrics'] = html.unescape(lyric)
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
                          headers={'User-Agent': 'MusicDL/1.0'}, allow_redirects=True) as response:
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
