"""Fix native request collisions and lossless fallback selection without copying URLs."""
import ast
import copy
import functools
import inspect
import json
import textwrap
import time


def audio_rank(song):
    from musicdl.musicdl import MusicClient
    return (str(song.ext).lower() in MusicClient.LOSSLESS_QUALITY_DEFINITIONS,
            int(song.file_size_bytes or 0))


class RequestKeywords(ast.NodeTransformer):
    def visit_Call(self, node):
        self.generic_visit(node)
        if (isinstance(node.func, ast.Attribute)
                and node.func.attr in {'get', 'post', 'head', 'request'}
                and any(k.arg for k in node.keywords)
                and any(k.arg is None and isinstance(k.value, ast.Name)
                        and k.value.id == 'request_overrides' for k in node.keywords)):
            node.keywords = [ast.keyword(arg=None, value=ast.Dict(
                keys=[ast.Constant(k.arg) if k.arg else None for k in node.keywords],
                values=[k.value for k in node.keywords]))]
        return node


PRIORITY_PARSERS = {
    'QQMusicClient': (
        '[self._parsewithvkeysapi, self._parsewithhaitangwserverapi, '
        'self._parsewithcocodownloaderapi, self._parsewithqqovoapi, '
        'self._parsewithxcvtsapi, self._parsewithchkszapi, '
        'self._parsewithlzmhhhapi, self._parsewithyuafengapi, '
        'self._parsewithxunhuisiapi]'
    ),
    'NeteaseMusicClient': (
        '[self._parsewithjfjtapi, self._parsewithhaitangwserverapi, '
        'self._parsewithyutangxiaowuapi, self._parsewithxcvtsapi, '
        'self._parsewithgdstudioapi, self._parsewithbileizhenapi, '
        'self._parsewithcunyuapi, self._parsewithqqovoapi, '
        'self._parsewithbyfunsapi, self._parsewithcocodownloaderapi, '
        'self._parsewithffapi, self._parsewithxiaotapi, '
        'self._parsewithhaitangwapi, self._parsewithchkszapi, '
        'self._parsewithlzmhhhapi]'
    ),
    'KugouMusicClient': (
        '[self._parsewithxianyuwapi, self._parsewithqqovoapi, '
        'self._parsewith90svipapi, self._parsewithtomapi, '
        'self._parsewithhaitangwapi, self._parsewithchkszapi, '
        'self._parsewithcocodownloaderapi, self._parsewithlzmhhhapi]'
    ),
    'KuwoMusicClient': (
        '[self._parsewithhaitangwapi, self._parsewithhaitangwserverapi, '
        'self._parsewithnxinxzapi, self._parsewithxcloudvapi]'
    ),
}


def prefer_lossless(tree, *, source=None):
    function = tree.body[0]
    loop = next(n for n in function.body if isinstance(n, ast.For)
                and isinstance(n.target, ast.Name) and n.target.id == 'parser_func')
    # Retain the native empty-song metadata and account/cookie gates.
    empty = copy.deepcopy(loop.body[0])
    replacement = ast.parse('''
for parser_func in parsers:
    candidate = None
    with suppress(Exception):
        candidate = parser_func(search_result, request_overrides)
    if candidate is not None and candidate.with_valid_download_url and candidate.ext in AudioLinkTester.VALID_AUDIO_EXTS:
        if not song_info_flac.with_valid_download_url or _melokeep_audio_rank(candidate) > _melokeep_audio_rank(song_info_flac):
            song_info_flac = candidate
        if _melokeep_audio_rank(candidate)[0]:
            break
''').body[0]
    ast.increment_lineno(replacement, loop.lineno - replacement.lineno)
    if source in PRIORITY_PARSERS:
        replacement.iter = ast.parse(PRIORITY_PARSERS[source]).body[0].value
    else:
        replacement.iter = loop.iter
    position = function.body.index(loop)
    function.body[position:position + 1] = [empty, replacement]


def qq_is_trial(download_url, file_size_bytes, duration_s, min_bps=250000):
    if 'RS02' in str(download_url or ''):
        return True
    if duration_s and duration_s > 60 and (file_size_bytes or 0) * 8 < min_bps * duration_s:
        return True
    return False


def qq_song_info(provider, search_result, download_result, download_url_status, request_overrides=None, lyric=None):
    from contextlib import suppress
    from musicdl.modules import SongInfo, SongInfoUtils
    from musicdl.modules.sources.qq import legalizestring, safeextractfromdict
    song_id = search_result.get('mid') or search_result.get('songmid')
    if song_id and not (safeextractfromdict(search_result, ['album', 'title'], None) or search_result.get('albumname')):
        with suppress(Exception):
            search_result.update(provider._getsongmetainfo(song_id=song_id, request_overrides=request_overrides or {}))
    duration_s = int(float(search_result.get('interval', 0) or 0))
    album_mid = safeextractfromdict(search_result, ['album', 'mid'], '') or search_result.get('albummid') or ''
    return SongInfo(
        raw_data={'search': search_result, 'download': download_result, 'lyric': {}},
        source=provider.source,
        song_name=legalizestring(search_result.get('title') or search_result.get('songname')),
        singers=legalizestring(', '.join([
            singer.get('name') for singer in (search_result.get('singer', []) or [])
            if isinstance(singer, dict) and singer.get('name')
        ])),
        album=legalizestring(safeextractfromdict(search_result, ['album', 'title'], None) or search_result.get('albumname')),
        ext=download_url_status['ext'],
        file_size_bytes=download_url_status['file_size_bytes'],
        file_size=download_url_status['file_size'],
        identifier=str(song_id),
        duration_s=duration_s,
        duration=SongInfoUtils.seconds2hms(duration_s),
        lyric=lyric,
        cover_url=f'https://y.gtimg.cn/music/photo_new/T002R800x800M000{album_mid}.jpg',
        download_url=download_url_status['download_url'],
        download_url_status=download_url_status,
    )


def netease_song_info(provider, search_result, download_result, download_url_status, quality='lossless', request_overrides=None):
    from contextlib import suppress
    from musicdl.modules import SongInfo, SongInfoUtils
    from musicdl.modules.sources.netease import legalizestring, safeextractfromdict
    song_id = search_result.get('id')
    if song_id and not search_result.get('name'):
        with suppress(Exception):
            search_result.update(provider._getsongmetainfo(song_id=song_id, request_overrides=request_overrides or {}))
    duration_s = int(float((search_result.get('dt') or search_result.get('duration') or 0)) / 1000)
    artists = search_result.get('ar') or search_result.get('artists') or []
    album = search_result.get('al') or search_result.get('album') or {}
    return SongInfo(
        raw_data={'search': search_result, 'download': download_result, 'lyric': {}, 'quality': quality},
        source=provider.source,
        song_name=legalizestring(search_result.get('name') or search_result.get('songname')),
        singers=legalizestring(', '.join([
            a.get('name') for a in artists if isinstance(a, dict) and a.get('name')
        ])),
        album=legalizestring(album.get('name') if isinstance(album, dict) else str(album or '')),
        ext=download_url_status['ext'],
        file_size_bytes=download_url_status['file_size_bytes'],
        file_size=download_url_status['file_size'],
        identifier=str(song_id),
        duration_s=duration_s,
        duration=SongInfoUtils.seconds2hms(duration_s),
        lyric=None,
        cover_url=album.get('picUrl') if isinstance(album, dict) else None,
        download_url=download_url_status['download_url'],
        download_url_status=download_url_status,
    )


def kuwo_song_info(provider, search_result, download_result, download_url_status, request_overrides=None):
    from contextlib import suppress
    from musicdl.modules import SongInfo, SongInfoUtils
    from musicdl.modules.sources.kuwo import legalizestring
    song_id = str(search_result.get('MUSICRID') or search_result.get('musicrid') or search_result.get('rid') or search_result.get('id') or '').removeprefix('MUSIC_')
    if song_id and not (search_result.get('SONGNAME') or search_result.get('name') or search_result.get('songName')):
        with suppress(Exception):
            search_result.update(provider._getsongmetainfo(song_id=song_id, request_overrides=request_overrides or {}))
    duration_s = int(float(search_result.get('DURATION') or search_result.get('duration') or 0))
    return SongInfo(
        raw_data={'search': search_result, 'download': download_result, 'lyric': {}},
        source=provider.source,
        song_name=legalizestring(search_result.get('SONGNAME') or search_result.get('name') or search_result.get('songName')),
        singers=legalizestring(search_result.get('ARTIST') or search_result.get('artist')),
        album=legalizestring(search_result.get('ALBUM') or search_result.get('album')),
        ext=download_url_status['ext'],
        file_size_bytes=download_url_status['file_size_bytes'],
        file_size=download_url_status['file_size'],
        identifier=song_id,
        duration_s=duration_s,
        duration=SongInfoUtils.seconds2hms(duration_s),
        lyric=None,
        cover_url=search_result.get('hts_MVPIC') or search_result.get('albumpic') or search_result.get('pic'),
        download_url=download_url_status['download_url'],
        download_url_status=download_url_status,
    )


def _parsewithhaitangwserverapi(self, search_result: dict, request_overrides: dict = None):
    import requests
    from musicdl.modules import AudioLinkTester, SongInfo
    from musicdl.modules.sources.qq import resp2json, safeextractfromdict
    request_overrides = request_overrides or {}
    if self.source == 'NeteaseMusicClient':
        song_id = search_result.get('id')
        src_code = 'wy'
        qualities = ('jymaster', 'lossless', 'exhigh')
        song_info = SongInfo(source=self.source, raw_data={'quality': 'standard'})
    elif self.source == 'KuwoMusicClient':
        song_id = str(search_result.get('MUSICRID') or search_result.get('musicrid') or search_result.get('rid') or search_result.get('id') or '').removeprefix('MUSIC_')
        src_code = 'kw'
        qualities = ('lossless', 'exhigh')
        song_info = SongInfo(source=self.source)
    else:
        song_id = search_result.get('mid') or search_result.get('songmid')
        src_code = 'tx'
        qualities = ('jymaster', 'lossless', 'exhigh')
        song_info = SongInfo(source=self.source)
    if not song_id:
        return song_info
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
        'Content-Type': 'application/json',
        'Origin': 'https://music.haitangw.cc',
        'Referer': 'https://music.haitangw.cc/',
    }
    last_resp = None
    for music_quality in qualities:
        resp = requests.post(
            'https://musicserver.haitangw.cc/v1/music/resolve-url',
            headers=headers,
            json={'source': src_code, 'rid': str(song_id), 'level': music_quality},
            timeout=10,
            **request_overrides,
        )
        last_resp = resp
        if resp.status_code >= 400:
            continue
        download_result = resp2json(resp=resp)
        download_url = (safeextractfromdict(download_result, ['data', 'url'], None)
                        or safeextractfromdict(download_result, ['url'], None))
        if not download_url or not str(download_url).startswith('http') or 'RS02' in str(download_url):
            continue
        download_url_status = self.audio_link_tester.test(url=download_url, request_overrides=request_overrides, renew_session=True)
        if self.source == 'NeteaseMusicClient':
            candidate = netease_song_info(self, search_result, download_result, download_url_status, quality=music_quality, request_overrides=request_overrides)
        elif self.source == 'KuwoMusicClient':
            candidate = kuwo_song_info(self, search_result, download_result, download_url_status, request_overrides=request_overrides)
        else:
            candidate = qq_song_info(self, search_result, download_result, download_url_status, request_overrides=request_overrides)
        if (candidate.with_valid_download_url and candidate.ext in AudioLinkTester.VALID_AUDIO_EXTS
                and not qq_is_trial(download_url, candidate.file_size_bytes, candidate.duration_s, 250000)):
            return candidate
    if last_resp is not None and last_resp.status_code >= 400:
        last_resp.raise_for_status()
    return song_info


def _parsewithqqovoapi_netease(self, search_result: dict, request_overrides: dict = None):
    import base64
    import hashlib
    import hmac
    import uuid
    from urllib.parse import parse_qsl, urlparse
    import requests
    from musicdl.modules import AudioLinkTester, SongInfo
    from musicdl.modules.sources.qq import resp2json, safeextractfromdict
    request_overrides = request_overrides or {}
    song_id = search_result.get('id')
    song_info = SongInfo(source=self.source, raw_data={'quality': 'standard'})
    if not song_id:
        return song_info
    headers = {
        'Accept': '*/*',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36',
        'Referer': 'https://qqovo.top/room/4SVWQK',
        'Origin': 'https://qqovo.top',
    }
    qqovo_session = requests.Session()
    resp = qqovo_session.post(
        'https://qqovo.top/api/session/bootstrap',
        headers={**headers, 'Content-Type': 'application/json'},
        data=json.dumps({'deviceId': str(uuid.uuid4())}, separators=(',', ':')),
        timeout=10,
        **request_overrides,
    )
    resp.raise_for_status()
    api_sign_key = safeextractfromdict(resp2json(resp=resp), ['apiSignKey'], '')
    track_url = f'https://qqovo.top/api/meting?server=netease&type=url&id={song_id}&quality=lossless'
    parsed = urlparse(track_url)
    timestamp, nonce = str(int(time.time())), str(uuid.uuid4())
    query = '&'.join(f'{k}={v}' for k, v in sorted(parse_qsl(parsed.query, keep_blank_values=True), key=lambda x: x[0]))
    payload = '\n'.join(['GET', parsed.path, query, '', timestamp, nonce])
    sign = base64.urlsafe_b64encode(hmac.new(api_sign_key.encode(), payload.encode(), hashlib.sha256).digest()).decode().rstrip('=')
    resp = qqovo_session.get(
        track_url,
        headers={**headers, 'X-OM-Ts': timestamp, 'X-OM-Nonce': nonce, 'X-OM-Sign': sign},
        timeout=10,
        **request_overrides,
    )
    resp.raise_for_status()
    download_result = resp2json(resp=resp)
    download_url = safeextractfromdict(download_result, ['url'], None)
    if not download_url or not str(download_url).startswith('http'):
        return song_info
    download_url_status = self.audio_link_tester.test(url=download_url, request_overrides=request_overrides, renew_session=True)
    candidate = netease_song_info(self, search_result, download_result, download_url_status, quality='lossless', request_overrides=request_overrides)
    if (candidate.with_valid_download_url and candidate.ext in AudioLinkTester.VALID_AUDIO_EXTS
            and not qq_is_trial(download_url, candidate.file_size_bytes, candidate.duration_s, 250000)):
        return candidate
    return song_info


def _parsewithcocodownloaderapi(self, search_result: dict, request_overrides: dict = None):
    import requests
    from musicdl.modules import AudioLinkTester, SongInfo
    from musicdl.modules.sources.qq import resp2json, safeextractfromdict
    request_overrides = request_overrides or {}
    song_id = search_result.get('mid') or search_result.get('songmid')
    song_info = SongInfo(source=self.source)
    if not song_id:
        return song_info
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
        'Referer': 'https://cocodownloader.markqq.com/',
    }
    resp = requests.get(
        f'https://cocodownloader.markqq.com/api/url?id={song_id}&provider=qq',
        headers=headers,
        timeout=10,
        **request_overrides,
    )
    resp.raise_for_status()
    download_result = resp2json(resp=resp)
    download_url = (safeextractfromdict(download_result, ['url'], None)
                    or safeextractfromdict(download_result, ['data', 'url'], None))
    if not download_url or not str(download_url).startswith('http') or 'RS02' in str(download_url):
        return song_info
    download_url_status = self.audio_link_tester.test(url=download_url, request_overrides=request_overrides, renew_session=True)
    candidate = qq_song_info(self, search_result, download_result, download_url_status, request_overrides=request_overrides)
    if (candidate.with_valid_download_url and candidate.ext in AudioLinkTester.VALID_AUDIO_EXTS
            and not qq_is_trial(download_url, candidate.file_size_bytes, candidate.duration_s, 250000)):
        return candidate
    return song_info


def _parsewithyuafengapi(self, search_result: dict, request_overrides: dict = None):
    from urllib.parse import quote
    import requests
    from musicdl.modules import AudioLinkTester, SongInfo
    from musicdl.modules.sources.qq import cleanlrc, resp2json, safeextractfromdict
    request_overrides = request_overrides or {}
    song_id = search_result.get('mid') or search_result.get('songmid')
    song_info = SongInfo(source=self.source)
    if not song_id:
        return song_info
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
    }
    apikey = '3ff23523e47465224a3f48579acf41f241540ce04b6cc0b94164f37a5b6299d5'
    for music_quality in ('母带', 'SQ', 'HQ'):
        resp = requests.get(
            f'https://api-v2.yuafeng.cn/API/qqmusic.php?type={quote(music_quality)}&mid={song_id}&apikey={apikey}',
            headers=headers,
            timeout=10,
            **request_overrides,
        )
        resp.raise_for_status()
        download_result = resp2json(resp=resp)
        download_url = (safeextractfromdict(download_result, ['data', 'music'], None)
                        or safeextractfromdict(download_result, ['data', 'url'], None))
        if not download_url or not str(download_url).startswith('http') or 'RS02' in str(download_url):
            continue
        download_url_status = self.audio_link_tester.test(url=download_url, request_overrides=request_overrides, renew_session=True)
        raw_lyric = cleanlrc(safeextractfromdict(download_result, ['data', 'lyric'], ''))
        lyric = raw_lyric if raw_lyric and raw_lyric not in {'NULL'} else None
        candidate = qq_song_info(self, search_result, download_result, download_url_status, request_overrides=request_overrides, lyric=lyric)
        if (candidate.with_valid_download_url and candidate.ext in AudioLinkTester.VALID_AUDIO_EXTS
                and not qq_is_trial(download_url, candidate.file_size_bytes, candidate.duration_s, 48000)):
            return candidate
    return song_info


def qq_search_results(provider, response, search_meta, request_overrides, page_no, *, log):
    from musicdl.modules.sources.qq import QQMusicClientUtils, resp2json
    key = 'music.search.SearchCgiService.DoSearchForQQMusicMobile'

    def read(response, endpoint):
        response.raise_for_status()
        data = resp2json(resp=response)
        block = data.get(key) or {}
        songs = (block.get('data') or {}).get('body', {}).get('item_song') or []
        codes = (data.get('code'), block.get('code'))
        log('info', f'QQMusicClient {endpoint}搜索响应：第 {page_no} 页，状态码 {codes}，原始曲目 {len(songs)} 条', category='search')
        return songs, codes

    songs, codes = read(response, '签名' if provider.use_encrypted_endpoint else '普通')
    if songs:
        return songs
    # Reuse the native payload and signing implementation; leave account,
    # proxy, pagination and audio parsing settings intact.
    signed = not provider.use_encrypted_endpoint
    endpoint = '签名' if signed else '普通'
    log('warning', f'QQMusicClient 搜索接口未返回曲目，尝试原引擎{endpoint}接口', category='search')
    options = {**search_meta, **(request_overrides or {})}
    params = {**(search_meta.get('params') or {}), **(options.get('params') or {})}
    if signed:
        params['sign'] = QQMusicClientUtils.sign(json.loads(search_meta['data']))
    else:
        params.pop('sign', None)
    options['params'] = params
    response = provider.post(QQMusicClientUtils.enc_endpoint if signed else QQMusicClientUtils.endpoint, **options)
    songs, codes = read(response, endpoint)
    if not songs and any(code not in (None, 0) for code in codes):
        raise RuntimeError(f'QQ 搜索接口拒绝请求，状态码 {codes}')
    return songs


def qq_quality_missing(provider, response_data, quality, *, parser, log):
    data = response_data if isinstance(response_data, dict) else {}
    reason = data.get('message') or data.get('msg') or '未返回音频地址'
    if parser == '_parsewithvkeysapi':
        label = {14: '臻品母带 2.0', 13: '臻品空间音频', 12: '杜比全景声',
                 11: 'Hi-Res', 10: 'SQ 无损', 9: 'HQ 增强'}.get(quality, str(quality))
        quality = f'{label}（{quality}）'
    log('warning', f'{provider.source} 第三方解析接口 {parser} 音质 {quality} 不可用：'
                  f'接口错误码 {data.get("code", "未知")}，{str(reason)[:200]}；'
                  '继续尝试其他音质或解析接口。', category='search')


def recover_qq_quality_loop(tree):
    function = tree.body[0]
    loop = next((node for node in function.body if isinstance(node, ast.For)
                 and isinstance(node.target, ast.Name) and node.target.id == 'music_quality'), None)
    if loop is None:
        return
    function.body.insert(0, ast.parse('song_info = SongInfo(source=self.source)').body[0])
    function.body.insert(function.body.index(loop) + 1, ast.parse('''
if not song_info.with_valid_download_url:
    return song_info
''').body[0])
    for node in ast.walk(function):
        if (isinstance(node, ast.If) and len(node.body) == 1 and isinstance(node.body[0], ast.Break)
                and any(isinstance(part, ast.NamedExpr) and isinstance(part.target, ast.Name)
                        and part.target.id == 'download_url' for part in ast.walk(node.test))):
            # Missing master audio must not hide the following lossless qualities.
            node.body = ast.parse('_melokeep_qq_quality_missing(self, download_result, music_quality)\ncontinue').body


def candidate_rows(provider, rows, songs):
    """Return native rows normally; candidate searches skip all audio parsers."""
    if not getattr(provider, '_melokeep_candidates', False):
        return rows
    from musicdl.modules import SongInfo
    for row in rows:
        qq = provider.source == 'QQMusicClient'
        album = row.get('album') or row.get('al') or {}
        artists = row.get('singer' if qq else 'artists') or row.get('ar') or []
        identifier = row.get('mid') or row.get('songmid') if qq else row.get('id')
        title = row.get('title') or row.get('songname') or row.get('name')
        if not identifier or not title:
            continue
        song = SongInfo(source=provider.source, identifier=str(identifier), song_name=title,
                        singers=', '.join(a.get('name', '') for a in artists if isinstance(a, dict)),
                        album=album.get('title') or album.get('name') or row.get('albumname') or '',
                        duration_s=int(row.get('interval') or 0) if qq else int((row.get('duration') or row.get('dt') or 0) / 1000),
                        cover_url=album.get('picUrl') or '',
                        raw_data={'search': copy.deepcopy(row), '_melokeep_candidate': True,
                                  '_melokeep_config': getattr(provider, '_melokeep_config', ''),
                                  '_melokeep_refresh': getattr(provider, '_melokeep_refresh', False),
                                  '_melokeep_started': getattr(provider, '_melokeep_started', time.time())})
        song.work_dir = provider.work_dir
        songs.append(song)
        if len(songs) >= provider.search_size_per_page:
            break
    return []


def lazy_search_methods(tree, namespace):
    """Compile the native per-track body as a resolver, keeping parser policy intact."""
    function = tree.body[0]
    loop = next(node for node in ast.walk(function) if isinstance(node, ast.For)
                and isinstance(node.target, ast.Tuple)
                and [getattr(n, 'id', '') for n in node.target.elts] == ['search_result_idx', 'search_result'])
    resolver = ast.parse('def _resolve_candidate(self, search_result, request_overrides=None):\n    pass').body[0]
    # QQ and Netease initialize the cookie-dependent lossless policy here.
    init = next(node for node in function.body if isinstance(node, ast.Assign)
                and 'lossless_quality_is_sufficient' in ast.unparse(node.targets[0]))
    body = [copy.deepcopy(node) for node in loop.body
            if not any(isinstance(n, ast.Break) or (isinstance(n, ast.Name) and n.id == 'progress')
                       for n in ast.walk(node))]
    resolver.body = [copy.deepcopy(init), *ast.parse('song_infos = []').body, *body,
                     *ast.parse('return song_infos').body]
    resolver.decorator_list = copy.deepcopy(function.decorator_list)
    tree.body.append(resolver)
    loop.iter.args[0] = ast.Call(func=ast.Name(id='_melokeep_candidate_rows', ctx=ast.Load()),
                                args=[ast.Name(id='self', ctx=ast.Load()), loop.iter.args[0],
                                      ast.Name(id='song_infos', ctx=ast.Load())], keywords=[])
    namespace['_melokeep_candidate_rows'] = candidate_rows


def compile_native(native, *, dispatcher=False, source=None, qq_search_log=None, qq_quality_log=None, lazy_search=False, target_name=None):
    native = inspect.unwrap(native)
    lines, start = inspect.getsourcelines(native)
    tree = ast.parse(textwrap.dedent(''.join(lines)))
    if target_name:
        tree.body[0].name = target_name
    tree = RequestKeywords().visit(tree)
    if qq_quality_log is not None:
        recover_qq_quality_loop(tree)
    if dispatcher:
        prefer_lossless(tree, source=source)
    namespace = dict(native.__globals__, _melokeep_audio_rank=audio_rank)
    if qq_quality_log is not None:
        namespace['_melokeep_qq_quality_missing'] = functools.partial(qq_quality_missing, parser=target_name or native.__name__, log=qq_quality_log)
    if qq_search_log is not None:
        loop = next(n for n in ast.walk(tree) if isinstance(n, ast.For)
                    and isinstance(n.iter, ast.Call) and isinstance(n.iter.func, ast.Name)
                    and n.iter.func.id == 'enumerate' and 'item_song' in ast.unparse(n.iter))
        loop.iter.args[0] = ast.Call(func=ast.Name(id='_melokeep_qq_search_results', ctx=ast.Load()),
                                    args=[ast.Name(id=name, ctx=ast.Load()) for name in
                                          ('self', 'resp', 'search_meta', 'request_overrides', 'page_no')], keywords=[])
        namespace['_melokeep_qq_search_results'] = functools.partial(qq_search_results, log=qq_search_log)
    if lazy_search:
        lazy_search_methods(tree, namespace)
    tree = ast.increment_lineno(ast.fix_missing_locations(tree), start - 1)
    exec(compile(tree, inspect.getsourcefile(native), 'exec'), namespace)
    fn_name = target_name or native.__name__
    if lazy_search:
        return namespace[fn_name], namespace['_resolve_candidate']
    return namespace[fn_name]


def keep_quality_variants(self, song_infos=None):
    unique, seen = [], set()
    for song in song_infos or []:
        # An earlier MP3 must not hide a later FLAC with the same platform ID.
        key = (song.identifier, str(song.ext).lower(), song.file_size_bytes)
        if key not in seen:
            seen.add(key)
            unique.append(song)
    return unique


def observe(method, source, label, log):
    @functools.wraps(method)
    def parser(self, *args, **kwargs):
        try:
            song = method(self, *args, **kwargs)
        except Exception as error:
            log('warning', f'{source} 解析接口 {label} 失败：{type(error).__name__}: {error}', category='search')
            raise
        if song.with_valid_download_url:
            log('info', f'{source} 解析接口 {label} 返回音频：{song.ext}，{song.file_size_bytes} 字节', category='search')
        else:
            log('warning', f'{source} 解析接口 {label} 未返回可用音频地址', category='search')
        return song
    return parser


def install(log):
    from musicdl.modules.sources import kugou, kuwo, qq, netease
    status = {}
    for cls in (kugou.KugouMusicClient, kuwo.KuwoMusicClient,
                qq.QQMusicClient, netease.NeteaseMusicClient):
        try:
            if getattr(cls, '_melokeep_audio_compat', False):
                status[cls.source] = 'ok'
                continue
            # Compile first: changed upstream code cannot leave a half-patched source.
            methods = {}
            for name in vars(cls):
                if not (name.startswith('_parsewith') and name.endswith('api')):
                    continue
                methods[name] = observe(compile_native(getattr(cls, name), qq_quality_log=log), cls.source, name, log)
            if cls is qq.QQMusicClient:
                for backup in (_parsewithhaitangwserverapi, _parsewithcocodownloaderapi, _parsewithyuafengapi):
                    methods[backup.__name__] = observe(compile_native(backup), cls.source, backup.__name__, log)
            elif cls is netease.NeteaseMusicClient:
                methods['_parsewithhaitangwserverapi'] = observe(
                    compile_native(_parsewithhaitangwserverapi, target_name='_parsewithhaitangwserverapi'),
                    cls.source, '_parsewithhaitangwserverapi', log)
                methods['_parsewithqqovoapi'] = observe(
                    compile_native(_parsewithqqovoapi_netease, target_name='_parsewithqqovoapi'),
                    cls.source, '_parsewithqqovoapi', log)
            elif cls is kuwo.KuwoMusicClient:
                methods['_parsewithhaitangwserverapi'] = observe(
                    compile_native(_parsewithhaitangwserverapi, target_name='_parsewithhaitangwserverapi'),
                    cls.source, '_parsewithhaitangwserverapi', log)
            methods['_parsewiththirdpartapis'] = compile_native(
                cls._parsewiththirdpartapis, dispatcher=True, source=cls.source)
            if cls in (qq.QQMusicClient, netease.NeteaseMusicClient):
                methods['_search'], methods['_resolve_candidate'] = compile_native(
                    cls._search, qq_search_log=log if cls is qq.QQMusicClient else None, lazy_search=True)
            methods['_removeduplicates'] = keep_quality_variants
            for name, method in methods.items():
                setattr(cls, name, method)
            cls._melokeep_audio_compat = True
            status[cls.source] = 'ok'
        except Exception as error:
            status[cls.source] = f'skip: {type(error).__name__}'
            log('error', f'{cls.source} 音质兼容修复未生效：{type(error).__name__}', category='search')
    return status
