"""End-to-end checks of batch rules, watched imports, media tools and recovery."""
import base64
import copy
import json
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import audio_tools
import library_rules
import local_library
from library_pipeline import LibrarySettings, ProcessBody, ApplyBody, digest
from metadata_scraper import MetadataScraper, from_row, pick
from test_library_pipeline import library, wav, preview, wait, apply


def metadata(path):
    info = path.stat()
    return local_library.read_metadata(str(path), info.st_mtime_ns, info.st_size)


def test_safe_v2_templates_preserve_values_and_reject_code():
    values = library_rules.variables(Path('a/b/c.wav'), {'title': '{artist}', 'artist': '劉德華 / 合作', 'track_number': '1', 'date': '1997-01-01'})
    assert library_rules.render('${tracknumber.zfill(2) + ". " if tracknumber else ""}${title} - ${artist.split("/")[0].strip()}', values) == '01. {artist} - 劉德華'
    assert library_rules.render('${year}/${first_artist_letter}/${counter}', values) == '1997/L/1'
    assert library_rules.render('${artist or albumartist or "未知"}', {}) == '未知'
    assert library_rules.render('${str(int(tracknumber)).zfill(2)}', values) == '01'
    LibrarySettings(filename_template='${artist.split("/")[0]} - ${title}')
    for expression in ('__import__("os")', 'title.__class__', 'open("x")', 'title.replace("a", "b" * 100000000)', 'title.zfill(999999999)', '[x for x in title]'):
        with pytest.raises(ValueError):
            library_rules.render('${' + expression + '}', values)


def test_batch_variables_extended_tags_rename_and_restore(library):
    path = wav(library.old.FILE_ROOT / 'incoming' / 'original.wav')
    local_library.write_metadata(path, {'title': '原曲', 'artist': '歌手', 'track_number': '2'})
    original = path.read_bytes()
    job = preview(library, path, 'edit', changes={'title': '${title} (${counter})', 'lyricist': '作词者', 'language': 'zho', 'isrc': 'CN1234567890'})
    assert job['items'][0]['after']['title'] == '原曲 (1)'
    assert path.read_bytes() == original
    assert apply(library, job)['status'] == 'complete'
    assert metadata(path)['lyricist'] == '作词者'
    token = library.token(path)
    renamed = apply(library, preview(library, path, 'rename', filename_template='${tracknumber.zfill(2)} - ${title}'))
    target = library.resolve(token)
    assert target.name == '02 - 原曲 (1).wav' and target.parent == path.parent
    library.restore(renamed['id'])
    assert wait(library, renamed['id'])['status'] == 'restored' and path.is_file()
    library.restore(job['id'])
    assert wait(library, job['id'])['status'] == 'restored' and path.read_bytes() == original


def test_custom_filename_extract_and_chinese_cleanup(library):
    path = wav(library.old.FILE_ROOT / '02 - 劉德華 - 愛你.wav')
    job = apply(library, preview(library, path, 'extract', extract_template='{track_number} - {artist} - {title}'))
    assert job['status'] == 'complete' and metadata(path)['artist'] == '劉德華'
    job = apply(library, preview(library, path, 'clean', chinese='simplified', find='你', replacement='妳'))
    assert job['status'] == 'complete' and metadata(path)['artist'] == '刘德华'
    assert metadata(path)['title'] == '爱妳'
    assert library_rules.transform('FranÃ§ais', repair=True) == 'Français'
    with pytest.raises(ValueError):
        library_rules.extract('{title}{artist}', 'ambiguous')
    assert library_rules.extract('{title} ({artist})', '歌 (歌手)') == {'title': '歌', 'artist': '歌手'}


def test_lyrics_cover_import_export_clear_and_undo(library):
    path = wav(library.old.FILE_ROOT / 'song.wav')
    png = b'\x89PNG\r\n\x1a\n'
    local_library.write_metadata(path, {'title': '标签'}, lyrics='[00:00]原歌词', cover=(png, 'image/png'))
    from mutagen.id3 import TXXX
    audio = local_library.mutagen.File(path)
    audio.tags.add(TXXX(encoding=3, desc='custom', text=['自定义标签']))
    audio.save()
    assert apply(library, preview(library, path, 'export_lyrics'))['status'] == 'complete'
    assert path.with_suffix('.lrc').read_text('utf-8') == '[00:00]原歌词'
    assert apply(library, preview(library, path, 'export_cover'))['status'] == 'complete'
    assert path.with_suffix('.png').read_bytes() == png
    path.with_suffix('.lrc').write_text('[00:00]新歌词', encoding='utf-8')
    assert apply(library, preview(library, path, 'import_lyrics'))['status'] == 'complete'
    assert local_library.read_lyrics(path, prefer_sidecar=False) == '[00:00]新歌词'
    assert apply(library, preview(library, path, 'import_cover'))['status'] == 'complete'
    job = apply(library, preview(library, path, 'clear'))
    assert job['status'] == 'complete' and not metadata(path)['has_cover']
    assert 'title' not in metadata(path)['tagged_fields']
    assert local_library.read_lyrics(path, prefer_sidecar=False) == ''
    assert not local_library.mutagen.File(path).tags.getall('TXXX')
    library.restore(job['id'])
    assert wait(library, job['id'])['status'] == 'restored'
    assert metadata(path)['title'] == '标签' and metadata(path)['has_cover']


def test_audio_duplicates_ignore_tags_and_integrity_report(library):
    first = wav(library.old.FILE_ROOT / 'a.wav')
    second = wav(library.old.FILE_ROOT / 'b.wav')
    local_library.write_metadata(first, {'title': '甲'})
    local_library.write_metadata(second, {'title': '乙'})
    tokens = [library.token(first), library.token(second)]
    job = wait(library, library.submit(ProcessBody(paths=tokens, action='duplicates', duplicate_mode='file'))['id'])
    assert job['duplicates'] == []
    job = wait(library, library.submit(ProcessBody(paths=tokens, action='duplicates', duplicate_mode='audio'))['id'])
    assert len(job['duplicates']) == 1 and job['status'] == 'complete'
    quality = preview(library, first, 'quality')
    assert quality['items'][0]['quality']['sample_rate'] == 8000
    with pytest.raises(HTTPException): library.apply(quality['id'], ApplyBody())
    assert first.is_file() and second.is_file()


def test_real_conversion_retains_original_and_restores_outputs(library):
    source = wav(library.old.FILE_ROOT / 'a.wav')
    local_library.write_metadata(source, {'title': '音轨', 'lyricist': '作词者'}, lyrics='歌词')
    original = source.read_bytes()
    job = preview(library, source, 'convert', output_format='flac', sample_rate=44100)
    output = Path(job['items'][0]['outputs'][0]['path'])
    assert not output.exists()
    assert apply(library, job)['status'] == 'complete'
    assert metadata(output)['title'] == '音轨' and metadata(output)['lyricist'] == '作词者'
    assert metadata(output)['sample_rate'] == 44100 and source.read_bytes() == original
    assert local_library.read_lyrics(output) == '歌词'
    library.restore(job['id'])
    assert wait(library, job['id'])['status'] == 'restored' and not output.exists()
    assert source.read_bytes() == original


def test_cue_split_boundaries_and_partial_failure_rollback(library, monkeypatch):
    source = wav(library.old.FILE_ROOT / 'album.wav')
    cue = 'PERFORMER "歌手"\nTITLE "专辑"\nFILE "album.wav" WAVE\n TRACK 01 AUDIO\n TITLE "第一首"\n INDEX 01 00:00:00\n TRACK 02 AUDIO\n TITLE "第二首"\n INDEX 01 00:00:30'
    job = preview(library, source, 'split', cue=cue, output_format='flac')
    assert len(job['items'][0]['outputs']) == 2, job
    completed = apply(library, job)
    assert completed['status'] == 'complete', completed
    outputs = [Path(o['path']) for o in job['items'][0]['outputs']]
    assert metadata(outputs[0])['duration'] == pytest.approx(.4, abs=.02)
    assert metadata(outputs[1])['duration'] == pytest.approx(.6, abs=.02)
    assert metadata(outputs[1])['track_number'] == '2' and metadata(outputs[1])['album'] == '专辑'
    library.restore(job['id']); wait(library, job['id'])
    real = audio_tools.convert
    def fail_second(src, target, options, **kwargs):
        if kwargs.get('start'): raise ValueError('模拟第二轨失败')
        return real(src, target, options, **kwargs)
    monkeypatch.setattr(audio_tools, 'convert', fail_second)
    failed = apply(library, preview(library, source, 'split', cue=cue))
    assert failed['status'] == 'failed' and source.exists()
    assert not any(outputs[0].parent.glob('*.flac'))


def test_derived_restore_protects_later_edits(library):
    source = wav(library.old.FILE_ROOT / 'original.wav')
    job = apply(library, preview(library, source, 'convert'))
    output = Path(job['items'][0]['outputs'][0]['path'])
    local_library.write_metadata(output, {'title': '后续编辑'})
    library.restore(job['id'])
    assert wait(library, job['id'])['status'] == 'partial' and output.exists() and source.exists()


def test_watcher_stability_restart_dedup_review_and_root_boundary(library):
    source = wav(library.old.FILE_ROOT / 'incoming' / 'a.wav')
    settings = LibrarySettings(watch_enabled=True, watch_stable_seconds=2, watch_apply=False).model_dump()
    library.put('library_setting', 'config', settings)
    assert library.watch_scan()['queued'] == 0
    token = library.token(source)
    signature, observed = library.watch_seen[token]
    library.watch_seen[token] = (signature, observed - 3)
    assert library.watch_scan()['queued'] == 1
    state = library.get('library_watch', token)
    job = wait(library, state['job_id'])
    assert job['watch'] and job['status'] == 'needs_review' and source.is_file()
    library.watch_seen.clear()
    assert library.watch_scan()['queued'] == 0
    settings.update(watch_dirs=['.'])
    with pytest.raises(HTTPException): library.watch_roots(settings)


def test_scope_report_credentials_and_versions_api(library):
    first = wav(library.old.FILE_ROOT / 'incoming' / '=a.wav')
    wav(library.old.FILE_ROOT / 'other' / 'outside.wav')
    job = wait(library, library.submit(ProcessBody(scope_dir='incoming', action='edit', changes={'title': '${filename}'}))['id'])
    assert job['total'] == 1
    completed = apply(library, job)
    app = FastAPI(); library.install(app)
    with TestClient(app) as client:
        response = client.get(f'/api/library/jobs/{job["id"]}/report')
        assert response.status_code == 200 and "'=a.wav" in response.content.decode('utf-8-sig')
        assert client.put('/api/library/credentials', json={'acoustid_key': 'private-test-key'}).status_code == 200
        assert 'private-test-key' not in client.get('/api/library/settings').text
        assert 'private-test-key' not in client.get(f'/api/library/jobs/{job["id"]}').text
        versions = client.get('/api/library/versions', params={'path': library.token(first)}).json()['versions']
        assert versions[0]['restorable'] and versions[0]['job_id'] == job['id']
        assert client.get('/api/library/jobs?status=ready').json()['jobs'] == []


def test_watcher_routes_unmatched_files_with_reversible_journal(library):
    source = wav(library.old.FILE_ROOT / 'incoming' / 'unknown.wav')
    original = source.read_bytes()
    settings = LibrarySettings(watch_enabled=True, watch_stable_seconds=2, watch_failure_dir='review').model_dump()
    library.put('library_setting', 'config', settings)
    library.watch_scan()
    token = library.token(source)
    signature, observed = library.watch_seen[token]
    library.watch_seen[token] = (signature, observed - 3)
    library.watch_scan()
    job = wait(library, library.get('library_watch', token)['job_id'])
    target = library.resolve(token)
    assert job['status'] == 'needs_review' and target.parent.name == 'review'
    assert not source.exists() and target.read_bytes() == original
    route_id = job['items'][0]['routed_by']
    library.restore(route_id)
    assert wait(library, route_id)['status'] == 'restored' and source.read_bytes() == original
    assert library.watch_scan()['queued'] == 0


@pytest.mark.parametrize('fmt', ['mp3', 'm4a', 'flac', 'opus', 'wav'])
def test_extended_tags_roundtrip_in_converted_containers(library, fmt):
    source = wav(library.old.FILE_ROOT / 'source.wav')
    tags = {'title': '歌曲', 'lyricist': '词作者', 'language': 'zho', 'copyright': '版权所有', 'publisher': '唱片公司',
            'grouping': '分组', 'bpm': '123', 'isrc': 'CN1234567890'}
    local_library.write_metadata(source, tags)
    job = apply(library, preview(library, source, 'convert', output_format=fmt))
    assert job['status'] == 'complete', job
    actual = metadata(Path(job['items'][0]['outputs'][0]['path']))
    assert all(actual[key] == value for key, value in tags.items()), actual


def test_single_song_saves_are_recoverable_versions(library):
    source = wav(library.old.FILE_ROOT / 'single.wav')
    original = source.read_bytes()
    library.edit_tags(source, {'title': '单曲保存'})
    job = library.values('library_job')[0]
    assert job['status'] == 'complete' and job['items'][0]['operation_id']
    library.restore(job['id'])
    assert wait(library, job['id'])['status'] == 'restored' and source.read_bytes() == original


def test_new_metadata_normalization_and_fingerprint_candidates():
    row = from_row('kugou', {'FileHash': 'HASH', 'SongName': '<em>冰雨</em>', 'SingerName': '刘德华', 'AlbumName': '专辑', 'Duration': 240})
    assert row['title'] == '冰雨' and row['source_id'] == 'HASH' and row['duration'] == 240
    row = from_row('kuwo', {'MUSICRID': 'MUSIC_123', 'SONGNAME': '冰雨', 'ARTIST': '刘德华', 'DURATION': '04:00'})
    assert row['source_id'] == '123' and row['duration'] == 240
    row = from_row('migu', {'copyrightId': '456', 'songName': '冰雨', 'singers': [{'name': '刘德华'}], 'albums': [{'name': '专辑'}]})
    assert row['artist'] == '刘德华' and row['album'] == '专辑'
    candidates = [{ 'source': 'acoustid', 'source_id': 'recording', 'title': '真正标题', 'artist': '歌手', 'album': album,
                    'release_id': album, 'duration': 240, 'fingerprint_score': .99} for album in ['发行一', '发行二']]
    ranked, chosen = pick({'title': 'track01', 'duration': 240}, candidates)
    assert chosen is None and all(c['score'] == 98 for c in ranked)


def test_fingerprint_lookup_sends_only_fingerprint_and_seeds_other_sources(monkeypatch):
    scraper = MetadataScraper(lambda: {'proxy_scope': 'all', 'proxy_url': 'http://proxy.example:8080'})
    scraper.credentials = lambda: {'acoustid_key': 'test-key'}
    monkeypatch.setattr(audio_tools, 'fingerprint', lambda path: {'duration': 240, 'fingerprint': 'fp-value'})
    posted, searches = [], []
    class Reply:
        def raise_for_status(self): pass
        def json(self): return {'status': 'ok', 'results': [{'score': .99, 'recordings': [
            {'id': 'recording', 'title': '识别标题', 'artists': [{'name': '歌手'}], 'releases': [{'id': 'release', 'title': '专辑'}]}]}]}
    def post(url, **kwargs):
        posted.append(kwargs)
        return Reply()
    monkeypatch.setattr('metadata_scraper.requests.post', post)
    monkeypatch.setattr(scraper, 'search_platform', lambda source, query: searches.append((source, query)) or [])
    candidates, warnings = scraper.search({'title': 'track01', '_path': 'local.wav'}, ['migu', 'acoustid'])
    assert candidates[0]['source'] == 'acoustid' and searches == [('migu', '识别标题 歌手')]
    assert posted[0]['data']['fingerprint'] == 'fp-value' and 'files' not in posted[0]
    assert posted[0]['proxies']['https'] == 'http://proxy.example:8080'


@pytest.mark.parametrize('source,payload', [
    ('migu', {'songResultData': {'result': [{'copyrightId': 'm', 'name': '歌曲'}]}}),
    ('kugou', {'data': {'lists': [{'FileHash': 'k', 'SongName': '歌曲'}]}}),
    ('kuwo', {'abslist': [{'MUSICRID': 'MUSIC_1', 'SONGNAME': '歌曲'}]}),
])
def test_added_platforms_query_only_metadata(monkeypatch, source, payload):
    from types import SimpleNamespace
    scraper = MetadataScraper(lambda: {})
    calls = []
    class Reply:
        def raise_for_status(self): pass
        def json(self): return payload
    provider = SimpleNamespace(_constructsearchurls=lambda q: ['https://source.example/search'],
                               get=lambda url, **kwargs: calls.append(url) or Reply())
    monkeypatch.setattr(scraper, 'provider', lambda s: ({}, provider, {}))
    monkeypatch.setattr('engine_worker.search', lambda *a: pytest.fail('不能进入音频解析器'))
    found, warnings = scraper.search({'title': '歌曲'}, [source])
    assert len(found) == 1 and warnings == [] and calls == ['https://source.example/search']


def test_candidate_search_keeps_original_version_and_requires_choice(library, monkeypatch):
    path = wav(library.old.FILE_ROOT / 'wrong-name.wav')
    job = preview(library, path, 'scrape')
    candidate = {'source': 'qq', 'source_id': 'correct', 'title': '找到的歌', 'artist': '歌手', 'album': '专辑'}
    monkeypatch.setattr(library.scraper, 'search', lambda ref, sources: ([candidate] if ref.get('_query') == '真正的歌名' else [], []))
    monkeypatch.setattr(library.scraper, 'enrich', lambda item, *args: (item, []))
    app = FastAPI(); library.install(app)
    with TestClient(app) as client:
        response = client.post(f'/api/library/jobs/{job["id"]}/search', json={'item': job['items'][0]['id'], 'query': '真正的歌名'})
        updated = response.json()
        assert response.status_code == 200 and updated['items'][0]['chosen'] is None
        assert updated['items'][0]['before'] == job['items'][0]['before'] and updated['status'] == 'needs_review'
        choice = updated['items'][0]['candidates'][0]['id']
        response = client.post(f'/api/library/jobs/{job["id"]}/preview', json={'choices': {job['items'][0]['id']: choice}})
        assert response.status_code == 200 and response.json()['items'][0]['status'] == 'ready'


def test_archive_expression_sees_raw_artist_but_cannot_inject_paths(library):
    path = wav(library.old.FILE_ROOT / 'file.wav')
    settings = LibrarySettings(folder_template='${artist.split("/")[0]}/${album}', filename_template='${title.replace("/", "-")}').model_dump()
    target = library.target(path, {'artist': '主唱/合作', 'album': '../outside', 'title': '一/二', 'track_number': ''}, settings)
    assert target.is_relative_to(library.library_root()) and target.parent.parent.name == '主唱'
    assert target.name == '一-二.wav'


def test_batch_collision_paths_are_reserved_in_preview(library):
    first = wav(library.old.FILE_ROOT / 'a.wav')
    second = wav(library.old.FILE_ROOT / 'b.wav')
    for path in (first, second): local_library.write_metadata(path, {'title': '同名', 'artist': '歌手', 'album': '专辑'})
    job = wait(library, library.submit(ProcessBody(paths=[library.token(first), library.token(second)], action='organize'))['id'])
    targets = [item['target'] for item in job['items']]
    assert len(set(targets)) == 2
    completed = apply(library, job)
    assert completed['status'] == 'complete' and [item['target'] for item in completed['items']] == targets


@pytest.mark.parametrize('action', ['import_lyrics', 'import_cover'])
def test_media_import_snapshot_detects_sidecar_edits_without_storing_copies(library, action):
    path = wav(library.old.FILE_ROOT / 'song.wav')
    sidecar = path.with_suffix('.lrc' if action == 'import_lyrics' else '.png')
    sidecar.write_bytes(b'[00:00]lyrics' if action == 'import_lyrics' else b'\x89PNG\r\n\x1a\n')
    original = path.read_bytes()
    job = preview(library, path, action)
    item = job['items'][0]
    assert 'media_cover' not in item and 'media_lyrics' not in item
    assert 'lyrics_snapshot' in item or 'cover_snapshot' in item
    sidecar.write_bytes(sidecar.read_bytes() + b'changed')
    assert apply(library, job)['status'] == 'failed'
    assert path.read_bytes() == original


def test_artist_artwork_preview_dedup_and_undo(library, monkeypatch):
    source = wav(library.old.FILE_ROOT / 'song.wav')
    local_library.write_metadata(source, {'artist': '艺术家'})
    monkeypatch.setattr(library.scraper, 'artist_artwork', lambda artist: 'https://example.com/artist.jpg')
    monkeypatch.setattr(library.scraper, 'cover', lambda url: (b'\xff\xd8\xffartwork', 'image/jpeg'))
    job = preview(library, source, 'artist_artwork')
    target = library.old.FILE_ROOT / 'library' / '艺术家' / 'artist.jpg'
    assert not target.exists()
    assert apply(library, job)['status'] == 'complete' and target.exists()
    assert preview(library, source, 'artist_artwork')['items'][0]['status'] == 'skipped'
    library.restore(job['id'])
    assert wait(library, job['id'])['status'] == 'restored' and not target.exists() and source.exists()
