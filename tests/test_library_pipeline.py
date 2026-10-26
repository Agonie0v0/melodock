"""Exercise real tag writes, file publication, rollback and remote library boundaries."""
import copy
import hashlib
import io
import json
import sqlite3
import subprocess
import threading
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import local_library
from library_pipeline import LibraryPipeline, LibrarySettings, ProcessBody, ApplyBody, digest
from metadata_scraper import pick, from_row
from navidrome import Navidrome


def wav(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as audio:
        audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\x10\0' * 8000)
    return path


def test_embedded_synchronized_lyrics_and_sidecar_priority(tmp_path):
    from mutagen.id3 import SYLT
    path = wav(tmp_path / 'synced.wav')
    local_library.write_metadata(path, {}, lyrics='纯文本歌词')
    audio = local_library.mutagen.File(path)
    audio.tags.add(SYLT(encoding=3, lang='zho', format=2, type=1,
                        text=[('第一句', 1250), ('第二句', 65001)]))
    audio.save()
    assert local_library.read_lyrics(path) == '[00:01.250]第一句\n[01:05.001]第二句'
    path.with_suffix('.lrc').write_text('[00:02]外置歌词', encoding='utf-8-sig')
    assert local_library.read_lyrics(path) == '[00:02]外置歌词'
    assert local_library.read_lyrics(path, prefer_sidecar=False).startswith('[00:01.250]')
    local_library.write_metadata(path, {}, lyrics='[00:03]替换歌词')
    assert local_library.read_lyrics(path, prefer_sidecar=False) == '[00:03]替换歌词'
    assert not local_library.mutagen.File(path).tags.getall('SYLT')


@pytest.fixture
def library(tmp_path, monkeypatch):
    root = tmp_path / 'music'
    root.mkdir()
    db = sqlite3.connect(':memory:', check_same_thread=False)
    data, guard = {}, threading.RLock()
    def get(kind, key, default=None):
        with guard:
            return copy.deepcopy(data.get((kind, key), default))
    def put(kind, key, value):
        with guard:
            data[kind, key] = copy.deepcopy(value)
    def values(kind):
        with guard:
            return [copy.deepcopy(value) for (k, _), value in data.items() if k == kind]
    old = SimpleNamespace(FILE_ROOT=root, manager=SimpleNamespace(workdirs=lambda: [root], config={}), pushlog=lambda *a, **kw: None)
    pipeline = LibraryPipeline(old, db, threading.RLock(), get, put, values, lambda k, i: data.pop((k, i), None))
    monkeypatch.setattr(pipeline.scraper, 'search', lambda *args: ([], []))
    def index(token):
        path = pipeline.resolve(token)
        info = path.stat()
        tags = local_library.read_metadata(str(path), info.st_mtime_ns, info.st_size)
        return {'path': token, 'track': {'id': token[6:], **tags}}
    pipeline.index_file = index
    yield pipeline
    pipeline.close()
    db.close()


def wait(pipeline, ident):
    pipeline.futures[ident].result(timeout=15)
    return pipeline.get('library_job', ident)


def preview(pipeline, path, action='organize', **options):
    job = pipeline.submit(ProcessBody(paths=[pipeline.token(path)], action=action, **options))
    return wait(pipeline, job['id'])


def apply(pipeline, job):
    pipeline.apply(job['id'], ApplyBody())
    return wait(pipeline, job['id'])


def test_preview_apply_move_restore_preserves_audio_and_legacy_links(library):
    source = wav(library.old.FILE_ROOT / 'incoming' / 'old.wav')
    local_library.write_metadata(source, {'title': '歌曲', 'artist': '歌手', 'album': '专辑', 'track_number': '3/12'})
    source.with_suffix('.lrc').write_text('[00:00]歌词', encoding='utf-8')
    original = source.read_bytes()
    legacy = library.legacy_token(source)
    token = library.token(source)
    ident = token[6:]
    library.put('download', 'd', {'id': 'd', 'file': legacy})
    library.put('favorite', ident, {'id': ident})
    library.put('collection', 'c', {'id': 'c', 'tracks': [{'id': ident}]})
    job = preview(library, source)
    assert job['status'] == 'ready' and source.read_bytes() == original
    assert not Path(job['items'][0]['target']).exists()
    completed = apply(library, job)
    assert completed['status'] == 'complete', completed
    target = library.resolve(token)
    assert target.name == '03 - 歌曲.wav' and not source.exists()
    assert library.resolve(legacy) == target and target.read_bytes() == original
    assert target.with_suffix('.lrc').read_text(encoding='utf-8') == '[00:00]歌词'
    assert library.get('download', 'd')['file'] == token
    assert library.get('favorite', ident)['title'] == '歌曲'
    assert library.get('collection', 'c')['tracks'][0]['album'] == '专辑'
    library.restore(job['id'])
    restored = wait(library, job['id'])
    assert restored['status'] == 'restored', restored
    assert source.read_bytes() == original and not target.exists()
    assert library.resolve(token) == source


def test_manual_edit_lyrics_cover_locks_and_restore(library):
    path = wav(library.old.FILE_ROOT / 'song.wav')
    original = path.read_bytes()
    job = preview(library, path, 'edit', changes={'title': '编辑', 'comment': '备注'}, lyrics='[00:00]歌词',
                  cover_data='data:image/png;base64,iVBORw0KGgo=')
    job = apply(library, job)
    assert job['status'] == 'complete', job
    tags = local_library.read_metadata(str(path), path.stat().st_mtime_ns, path.stat().st_size)
    assert tags['title'] == '编辑' and tags['comment'] == '备注' and tags['has_cover']
    assert local_library.read_lyrics(path) == '[00:00]歌词'
    assert library.asset(path)['locks'] == ['comment', 'title']
    with wave.open(str(path)) as audio:
        assert audio.readframes(8000) == b'\x10\0' * 8000
    library.restore(job['id'])
    assert wait(library, job['id'])['status'] == 'restored'
    assert path.read_bytes() == original and not path.with_suffix('.lrc').exists()
    assert library.asset(path)['locks'] == []


def test_stale_preview_and_later_sidecar_changes_are_rejected(library):
    path = wav(library.old.FILE_ROOT / 'song.wav')
    job = preview(library, path, 'edit', changes={'artist': '歌手'})
    local_library.write_metadata(path, {'title': '新的人工修改'})
    changed = path.read_bytes()
    assert apply(library, job)['status'] == 'failed'
    assert path.read_bytes() == changed
    job = apply(library, preview(library, path, 'edit', lyrics='原歌词'))
    path.with_suffix('.lrc').write_text('后续编辑', encoding='utf-8')
    library.restore(job['id'])
    assert wait(library, job['id'])['status'] == 'partial'
    assert path.with_suffix('.lrc').read_text(encoding='utf-8') == '后续编辑'


def test_collision_preserves_both_and_failed_publish_never_deletes_target(library, monkeypatch):
    path = wav(library.old.FILE_ROOT / 'song.wav')
    job = preview(library, path)
    target = Path(job['items'][0]['target'])
    target.parent.mkdir(parents=True)
    target.write_bytes(b'unrelated audio')
    job = apply(library, job)
    assert job['status'] == 'complete'
    assert target.read_bytes() == b'unrelated audio'
    assert library.resolve(library.token(Path(job['items'][0]['target']))).name.endswith('(1).wav')
    other = wav(library.old.FILE_ROOT / 'other.wav')
    failed = preview(library, other)
    original = other.read_bytes()
    def conflict(src, dest):
        Path(dest).write_bytes(b'concurrent writer')
        raise FileExistsError()
    monkeypatch.setattr('library_pipeline.os.link', conflict)
    failed = apply(library, failed)
    assert failed['status'] == 'failed'
    assert other.read_bytes() == original
    assert Path(failed['items'][0]['target']).read_bytes() == b'concurrent writer'


@pytest.mark.parametrize('failure_point', ['index', 'journal'])
def test_publish_failure_rolls_back_audio_sidecars_and_identity(library, monkeypatch, failure_point):
    source = wav(library.old.FILE_ROOT / 'in.wav')
    source.with_suffix('.lrc').write_text('原歌词', encoding='utf-8')
    original = source.read_bytes()
    token = library.token(source)
    job = preview(library, source)
    index, put = library.index_file, library.put
    once = [False]
    def fail_index(value):
        if not once[0]:
            once[0] = True
            raise OSError('simulated crash')
        return index(value)
    def fail_put(kind, key, value):
        if kind == 'library_operation' and value.get('state') == 'complete' and not once[0]:
            once[0] = True
            raise OSError('simulated database failure')
        return put(kind, key, value)
    monkeypatch.setattr(library, 'index_file' if failure_point == 'index' else 'put', fail_index if failure_point == 'index' else fail_put)
    assert apply(library, job)['status'] == 'failed'
    assert source.read_bytes() == original and library.resolve(token) == source
    assert source.with_suffix('.lrc').read_text(encoding='utf-8') == '原歌词'
    assert not Path(job['items'][0]['target']).exists()


def test_automatic_processing_and_ambiguity(library, monkeypatch):
    path = wav(library.old.FILE_ROOT / 'download.wav')
    source = {'source': 'netease', 'source_id': '1', 'title': '歌曲', 'artist': '歌手', 'album': '专辑', 'duration': 1, 'lyrics': '歌词'}
    monkeypatch.setattr(library.scraper, 'enrich', lambda c, *args: (c, []))
    token = library.token(path)
    library.asset(path, source)
    library.put('download', 'd', {'id': 'd', 'file': token, 'status': 'complete'})
    job = library.submit(ProcessBody(paths=[token], action='both'), 'd', {token: source})
    result = wait(library, job['id'])
    assert result['status'] == 'complete', result
    assert library.get('download', 'd')['processing']['status'] == 'complete'
    assert library.resolve(token).name == '歌曲.wav'
    assert local_library.read_lyrics(library.resolve(token)) == '歌词'
    unknown = wav(library.old.FILE_ROOT / 'unknown.wav')
    monkeypatch.setattr(library.scraper, 'search', lambda *args: ([], ['不可用']))
    token = library.token(unknown)
    result = wait(library, library.submit(ProcessBody(paths=[token]), 'd')['id'])
    assert result['status'] == 'needs_review' and unknown.is_file()


def test_both_mode_fills_sidecars_without_overwriting_embedded_values(library, monkeypatch):
    path = wav(library.old.FILE_ROOT / 'both.wav')
    image = b'\x89PNG\r\n\x1a\n'
    local_library.write_metadata(path, {}, lyrics='原内嵌歌词', cover=(image, 'image/png'))
    token = library.token(path)
    source = {'source': 'qq', 'source_id': 's', 'title': '歌曲', 'artist': '歌手', 'album': '专辑', 'duration': 1, 'lyrics': '来源歌词'}
    library.asset(path, source)
    monkeypatch.setattr(library.scraper, 'enrich', lambda c, *args: (c, []))
    job = wait(library, library.submit(ProcessBody(paths=[token], action='scrape'))['id'])
    assert apply(library, job)['status'] == 'complete'
    assert path.with_suffix('.lrc').read_text(encoding='utf-8') == '原内嵌歌词'
    assert path.with_suffix('.png').read_bytes() == image
    path.with_suffix('.lrc').write_text('原外置歌词', encoding='utf-8')
    job = wait(library, library.submit(ProcessBody(paths=[token], action='scrape'))['id'])
    assert apply(library, job)['status'] == 'complete'
    assert local_library.read_lyrics(path, prefer_sidecar=False) == '原内嵌歌词'
    assert local_library.read_lyrics(path) == '原外置歌词'


def test_matching_rejects_versions_and_ambiguous_albums():
    ref = {'title': '歌曲', 'artist': '歌手', 'duration': 200}
    base = {**ref, 'source': 'qq', 'source_id': '1', 'album': '专辑'}
    assert pick(ref, [base])[1]
    assert pick(ref, [{**base, 'title': '歌曲 Live'}])[1] is None
    assert pick(ref, [base, {**base, 'source_id': '2', 'album': '精选'}])[1] is None
    row = from_row('netease', {'id': 1, 'name': '歌', 'ar': [{'name': '人'}], 'al': {'name': '辑'}, 'dt': 123000, 'no': 2})
    assert row['duration'] == 123 and row['track_number'] == '2'


def test_manual_scrape_searches_selected_sources_and_snapshots_rules(library, monkeypatch):
    path = wav(library.old.FILE_ROOT / 'known.wav')
    token = library.token(path)
    library.asset(path, {'source': 'qq', 'source_id': '1', 'title': '歌曲', 'artist': '歌手', 'album': '专辑'})
    calls = []
    monkeypatch.setattr(library.scraper, 'search', lambda ref, sources: (calls.append(sources) or [], ['MusicBrainz未找到候选']))
    monkeypatch.setattr(library.scraper, 'enrich', lambda c, *a: (c, []))
    job = preview(library, path, 'scrape', sources=['musicbrainz'], overwrite=True)
    assert calls == [['musicbrainz']]
    assert job['settings']['sources'] == ['musicbrainz'] and job['settings']['overwrite']
    assert library.settings()['sources'] == ['netease', 'qq'] and not library.settings()['overwrite']
    assert 'MusicBrainz未找到候选' in job['items'][0]['warnings']
    assert {'musicbrainz', 'migu', 'kugou', 'kuwo', 'acoustid'} <= {source['id'] for source in library.public_settings()['metadata_sources']}


def test_scrape_without_sources_is_rejected_before_creating_job(library):
    path = wav(library.old.FILE_ROOT / 'unknown.wav')
    library.put('library_setting', 'config', {'sources': []})
    with pytest.raises(HTTPException, match='请选择至少一个刮削来源'):
        preview(library, path, 'scrape')
    assert not library.values('library_job')
    assert preview(library, path, 'organize')['status'] == 'ready'


def test_automatic_download_from_other_provider_checks_metadata_sources(library, monkeypatch):
    path = wav(library.old.FILE_ROOT / 'migu.wav')
    token = library.token(path)
    source = {'source': 'MiguMusicClient', 'source_id': '1', 'title': '歌曲', 'artist': '歌手', 'album': '专辑', 'duration': 1}
    library.asset(path, source)
    calls = []
    monkeypatch.setattr(library.scraper, 'search', lambda ref, sources: (calls.append(sources) or [], []))
    result = wait(library, library.submit(ProcessBody(paths=[token], action='scrape'), 'download')['id'])
    assert result['status'] == 'complete' and calls == [['netease', 'qq']]


def test_current_tags_override_stale_download_identity(library, monkeypatch):
    path = wav(library.old.FILE_ROOT / 'retagged.wav')
    local_library.write_metadata(path, {'title': '新歌', 'artist': '新歌手', 'album': '新专辑'})
    library.asset(path, {'source': 'qq', 'source_id': 'old', 'title': '旧歌', 'artist': '旧歌手', 'album': '旧专辑'})
    queries = []
    def search(reference, sources):
        queries.append(reference)
        return [{**reference, 'source_id': 'new'}], []
    monkeypatch.setattr(library.scraper, 'search', search)
    monkeypatch.setattr(library.scraper, 'enrich', lambda candidate, *args: (candidate, []))
    job = preview(library, path, 'scrape')
    assert queries[0]['title'] == '新歌' and queries[0]['album'] == '新专辑'
    chosen = next(c for c in job['items'][0]['candidates'] if c['id'] == job['items'][0]['chosen'])
    assert chosen['source_id'] == 'new'
    assert '标题不同' in next(c for c in job['items'][0]['candidates'] if c['source_id'] == 'old')['conflicts']


def test_boundaries_hidden_files_and_duplicate_report(library):
    root = library.old.FILE_ROOT
    path = wav(root / 'a.wav')
    (root / 'b.wav').write_bytes(path.read_bytes())
    wav(root / '.processing' / 'hidden.wav')
    assert {p.name for p in library.scan()} == {'a.wav', 'b.wav'}
    with pytest.raises(HTTPException):
        library.resolve('../outside.wav')
    with pytest.raises(HTTPException):
        library.resolve('.processing/hidden.wav')
    with pytest.raises(ValueError):
        LibrarySettings(folder_template='../{title}')
    body = ProcessBody(paths=[library.token(root / 'a.wav'), library.token(root / 'b.wav')], action='duplicates')
    job = wait(library, library.submit(body)['id'])
    assert len(job['duplicates']) == 1 and path.is_file() and (root / 'b.wav').is_file()


def test_restart_marks_active_jobs_paused(library):
    library.put('library_job', 'interrupted', {'id': 'interrupted', 'status': 'tagging'})
    library.recover()
    assert library.get('library_job', 'interrupted')['status'] == 'paused'


def test_startup_recovers_interrupted_publication(library, monkeypatch):
    source = wav(library.old.FILE_ROOT / 'crash.wav')
    original = source.read_bytes()
    token = library.token(source)
    job = preview(library, source)
    index = library.index_file
    monkeypatch.setattr(library, 'index_file', lambda *a: (_ for _ in ()).throw(SystemExit('crash')))
    library.apply(job['id'], ApplyBody())
    with pytest.raises(SystemExit):
        wait(library, job['id'])
    assert Path(job['items'][0]['target']).is_file()
    monkeypatch.setattr(library, 'index_file', index)
    library.recover()
    assert source.read_bytes() == original and library.resolve(token) == source
    assert not Path(job['items'][0]['target']).exists()
    assert library.get('library_job', job['id'])['status'] == 'paused'


def test_startup_recovers_download_handoff_gap(library):
    path = wav(library.old.FILE_ROOT / '.processing' / 'd' / 'song.wav')
    token = library.token(path)
    library.put('download', 'd', {'id': 'd', 'status': 'complete', 'file': token,
                                'processing': {'status': 'queued'}, 'processing_action': 'organize', 'processing_paths': [token]})
    library.recover()
    jobs = library.values('library_job')
    assert len(jobs) == 1 and wait(library, jobs[0]['id'])['status'] == 'complete'
    assert library.resolve(token).is_relative_to(library.library_root())


def test_cancel_at_automatic_handoff_keeps_original(library):
    path = wav(library.old.FILE_ROOT / 'cancel.wav')
    original = path.read_bytes()
    job = preview(library, path)
    library.cancelled.add(job['id'])
    library.apply(job['id'], ApplyBody(), automatic=True)
    assert library.get('library_job', job['id'])['status'] == 'cancelled'
    assert path.read_bytes() == original and not Path(job['items'][0]['target']).exists()


def test_settings_redact_and_retain_secrets_and_candidate_preview(library, monkeypatch):
    app = FastAPI()
    library.install(app)
    client = TestClient(app)
    cfg = {'enabled': True, 'url': 'http://navidrome:4533', 'username': 'u', 'password': 'private', 'api_key': 'key'}
    result = client.put('/api/library/navidrome', json=cfg)
    assert result.status_code == 200 and result.json()['has_password']
    assert 'private' not in result.text and '"key"' not in result.text
    client.put('/api/library/navidrome', json={**cfg, 'password': None, 'api_key': None})
    assert library.nav_settings()['password'] == 'private'
    assert 'private' not in client.get('/api/library/settings').text
    path = wav(library.old.FILE_ROOT / 'song.wav')
    monkeypatch.setattr(library.scraper, 'search', lambda *a: ([{'source': 'qq', 'source_id': 's', 'title': '候选', 'artist': '歌手', 'album': '专辑'}], []))
    monkeypatch.setattr(library.scraper, 'enrich', lambda c, *args: ({**c, 'date': '2020'}, []))
    job = preview(library, path, 'scrape')
    assert job['status'] == 'needs_review'
    item = job['items'][0]
    candidate = item['candidates'][0]
    result = client.post(f'/api/library/jobs/{job["id"]}/preview', json={'choices': {item['id']: candidate['id']}})
    assert result.status_code == 200 and result.json()['items'][0]['after']['date'] == '2020'
    assert path.name == 'song.wav'
    result = apply(library, result.json())
    assert result['status'] == 'complete'
    assert result['items'][0]['after']['date'] == '2020'


@pytest.mark.parametrize('extension', ['mp3', 'flac', 'm4a', 'ogg', 'opus', 'wma'])
def test_real_formats_preserve_decoded_audio(tmp_path, extension):
    imageio_ffmpeg = pytest.importorskip('imageio_ffmpeg')
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    original = wav(tmp_path / 'source.wav')
    path = tmp_path / ('encoded.' + extension)
    subprocess.run([ffmpeg, '-v', 'error', '-i', str(original), '-y', str(path)], check=True, capture_output=True)
    def pcm():
        return subprocess.run([ffmpeg, '-v', 'error', '-i', str(path), '-f', 's16le', '-'], capture_output=True, check=True).stdout
    before = pcm()
    local_library.write_metadata(path, {'title': '音乐', 'artist': '歌手', 'album_artist': '专辑歌手', 'comment': '备注', 'track_number': '2/9'},
                                 lyrics='内嵌歌词', cover=(b'\x89PNG\r\n\x1a\n', 'image/png'))
    tags = local_library.read_metadata(str(path), path.stat().st_mtime_ns, path.stat().st_size)
    assert tags['title'] == '音乐' and tags['comment'] == '备注' and tags['has_cover']
    assert local_library.read_lyrics(path) == '内嵌歌词'
    assert before == pcm()


def test_navidrome_authenticated_server_proxy(tmp_path):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlsplit, parse_qs
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)
            assert query['t'][0] == hashlib.md5(('private-password' + query['s'][0]).encode()).hexdigest()
            assert 'p' not in query
            seen.append((urlsplit(self.path).path, query, self.headers.get('Range')))
            if '/stream.' in self.path:
                self.send_response(206)
                self.send_header('Content-Type', 'audio/mpeg')
                self.send_header('Content-Range', 'bytes 2-4/10')
                self.end_headers()
                self.wfile.write(b'234')
                return
            data = {'status': 'ok', 'version': '1.16.1', 'album': {'id': 'a', 'name': '专辑', 'song': [
                {'id': 's', 'title': '歌曲', 'artist': '歌手', 'suffix': 'mp3', 'coverArt': 'a'}]},
                'scanStatus': {'scanning': True, 'count': 1}}
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'subsonic-response': data}).encode())
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    nav = Navidrome(lambda: {'enabled': True, 'url': f'http://127.0.0.1:{server.server_port}', 'username': 'user', 'password': 'private-password'})
    app = FastAPI()
    remembered = []
    nav.install(app, remembered.append)
    try:
        with TestClient(app) as client:
            assert client.post('/api/navidrome/test').json()['ok']
            result = client.get('/api/navidrome/albums/a').json()
            assert result['tracks'][0]['playback']['url'] == '/api/navidrome/stream/s'
            assert 'private-password' not in json.dumps(result) and remembered[0]['id'] == 'navidrome-s'
            media = client.get('/api/navidrome/stream/s', headers={'Range': 'bytes=2-4'})
            assert media.status_code == 206 and media.content == b'234'
            assert media.headers['content-range'] == 'bytes 2-4/10' and seen[-1][2] == 'bytes=2-4'
            assert client.post('/api/navidrome/scan').json()['scanning']
    finally:
        server.shutdown()
        server.server_close()


def test_optional_navidrome_delete_mapping_requires_real_paths_and_matching_files(library, monkeypatch):
    root = library.old.FILE_ROOT / 'shared'
    audio = wav(root / 'artist' / 'song.wav')
    cfg = {'enabled': True, 'delete_enabled': True, 'music_root': str(root), 'server_music_root': '/nav/music'}
    library.put('library_setting', 'navidrome', cfg)
    song = {'id': 's', 'path': '/nav/music/artist/song.wav', 'size': audio.stat().st_size}
    monkeypatch.setattr(library.navidrome, 'request', lambda *a, **kw: {'song': song})
    target, preview = library.nav_delete_preview('s')
    assert target == audio and preview['path'] == str(audio) and len(preview['revision']) == 64
    audio.write_bytes(audio.read_bytes() + b'x')
    with pytest.raises(HTTPException) as error:
        library.nav_delete_preview('s')
    assert error.value.status_code == 409
    song['size'] = audio.stat().st_size
    assert library.nav_delete_preview('s')[1]['revision'] != preview['revision']
    for invalid in ['artist/song.wav', '/nav/music/../shared/artist/song.wav', '/nav/music2/artist/song.wav', '/nav/music/artist/..\\song.wav']:
        song['path'] = invalid
        with pytest.raises(HTTPException):
            library.nav_delete_preview('s')
    song['path'] = '/nav/music/artist/song.wav'
    cfg['delete_enabled'] = False
    library.put('library_setting', 'navidrome', cfg)
    with pytest.raises(HTTPException) as error:
        library.nav_delete_preview('s')
    assert error.value.status_code == 409 and audio.exists()
    cfg.update(delete_enabled=True, music_root=str(root.parent.parent))
    library.put('library_setting', 'navidrome', cfg)
    with pytest.raises(HTTPException):
        library.nav_delete_preview('s')
    cfg['music_root'] = str(root)
    library.put('library_setting', 'navidrome', cfg)
    monkeypatch.setattr('library_pipeline.os.access', lambda *a: False)
    with pytest.raises(HTTPException) as error:
        library.nav_delete_preview('s')
    assert error.value.status_code == 403


def test_navidrome_delete_rejects_symlink_components(library):
    root = library.old.FILE_ROOT / 'shared'
    audio = wav(root / 'real' / 'song.wav')
    link = root / 'alias'
    try:
        link.symlink_to(audio.parent, target_is_directory=True)
    except OSError:
        pytest.skip('Symlink creation requires platform permission')
    library.put('library_setting', 'navidrome', {'enabled': True, 'delete_enabled': True,
                'music_root': str(root), 'server_music_root': '/music'})
    library.navidrome.request = lambda *a, **kw: {'song': {'id': 's', 'path': '/music/alias/song.wav', 'size': audio.stat().st_size}}
    with pytest.raises(HTTPException) as error:
        library.nav_delete_preview('s')
    assert error.value.status_code == 403 and audio.exists()


def test_navidrome_delete_settings_are_optional_and_validate_mount_when_enabled(library):
    app = FastAPI()
    library.install(app)
    client = TestClient(app)
    cfg = {'enabled': True, 'url': 'https://nav.example', 'username': 'u', 'password': 'p'}
    response = client.put('/api/library/navidrome', json=cfg)
    assert response.status_code == 200 and response.json()['delete_enabled'] is False
    cfg.update(delete_enabled=True, music_root=str(library.old.FILE_ROOT / 'unmounted'), server_music_root='/music')
    assert client.put('/api/library/navidrome', json=cfg).status_code == 400
    assert library.nav_settings()['delete_enabled'] is False
    root = library.old.FILE_ROOT / 'mounted'
    root.mkdir()
    cfg['music_root'] = str(root)
    assert client.put('/api/library/navidrome', json=cfg).status_code == 200
    root.rmdir()
    # Disabling is always possible even after the mount disappears.
    cfg['delete_enabled'] = False
    assert client.put('/api/library/navidrome', json=cfg).status_code == 200
