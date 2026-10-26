from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient

from navidrome import Navidrome


def test_remote_playlists_and_paged_songs_are_playable_without_exposing_credentials():
    settings = {'enabled': True, 'url': 'https://nav.example', 'password': 'secret'}
    nav = Navidrome(lambda: settings)
    calls, remembered = [], []
    song = {'id': 's/1', 'title': '歌曲', 'artist': '歌手', 'coverArt': 'c/1', 'suffix': 'flac'}
    playlist = {'id': 'p:1', 'name': '远程歌单', 'songCount': 1, 'created': '2026-01-01T00:00:00Z'}

    def request(endpoint, **params):
        calls.append((endpoint, params))
        if endpoint == 'getPlaylists':
            return {'playlists': {'playlist': [playlist]}}
        if endpoint == 'getPlaylist':
            return {'playlist': {**playlist, 'entry': [song, song]}}
        if endpoint == 'search3':
            return {'searchResult3': {'song': [song, dict(song, id='second'), dict(song, id='third')]}}
        raise AssertionError(endpoint)

    nav.request = request
    app = FastAPI()
    nav.install(app, remembered.append)
    with TestClient(app) as client:
        summary = client.get('/api/navidrome/playlists').json()[0]
        assert summary['id'] == 'navidrome:p:1' and summary['read_only'] is True
        detail = client.get('/api/navidrome/playlists/p:1').json()
        assert len(detail['tracks']) == 2  # Preserve intentional duplicates and server order.
        assert detail['tracks'][0]['playback']['url'] == '/api/navidrome/stream/s%2F1'
        assert remembered[0]['id'] == 'navidrome-s/1'
        assert 'secret' not in str(detail) and 'nav.example' not in str(detail)
        page = client.get('/api/navidrome/songs?offset=50&size=2').json()
        assert len(page['tracks']) == 2 and page['has_more'] is True
        assert calls[-1] == ('search3', {'query': '', 'songCount': 3, 'songOffset': 50, 'albumCount': 0, 'artistCount': 0})
        assert client.get('/api/navidrome/songs?offset=-1').status_code == 400
        assert client.get('/api/navidrome/songs?size=101').status_code == 400
        settings['enabled'] = False
        before = len(calls)
        assert client.get('/api/navidrome/playlists').json() == [] and len(calls) == before


def test_empty_or_missing_remote_data_does_not_invent_songs():
    nav = Navidrome(lambda: {'enabled': True})
    nav.request = lambda *args, **kwargs: {}
    app = FastAPI()
    nav.install(app, lambda track: None)
    with TestClient(app) as client:
        assert client.get('/api/navidrome/playlists').json() == []
        assert client.get('/api/navidrome/playlists/missing').status_code == 404
        assert client.get('/api/navidrome/songs').json() == {'tracks': [], 'has_more': False}


def test_lyrics_prefer_song_specific_timing_and_preserve_milliseconds():
    nav = Navidrome(lambda: {})
    calls = []
    def request(endpoint, **params):
        calls.append((endpoint, params))
        return {'lyricsList': {'structuredLyrics': [
            {'synced': False, 'line': [{'value': '无时间歌词'}]},
            {'synced': True, 'offset': 100, 'line': [
                {'start': 0, 'value': '第一句'}, {'start': 2350, 'value': '第二句'},
                {'start': 65001, 'value': '第三句'}, {'start': 'bad', 'value': '损坏的时间'},
            ]},
        ]}}
    nav.request = request
    assert nav.lyrics('song-id', artist='同名歌手', title='同名歌曲') == (
        '[00:00.000]第一句\n[00:02.250]第二句\n[01:04.901]第三句')
    assert calls == [('getLyricsBySongId', {'id': 'song-id'})]


def test_lyrics_plain_missing_and_unsupported_servers_fall_back_without_fake_timing():
    nav = Navidrome(lambda: {})
    nav.request = lambda *a, **kw: {'lyricsList': {'structuredLyrics': [
        {'synced': True, 'line': [{'value': '缺少时间的歌词'}]},
    ]}}
    assert nav.lyrics('song') == '缺少时间的歌词'
    calls = []
    def legacy(endpoint, **params):
        calls.append(endpoint)
        if endpoint == 'getLyricsBySongId':
            raise HTTPException(502, 'unsupported')
        assert params == {'artist': 'artist', 'title': 'title'}
        return {'lyrics': {'value': '[00:01]旧接口歌词'}}
    nav.request = legacy
    assert nav.lyrics('song', artist='artist', title='title') == '[00:01]旧接口歌词'
    assert calls == ['getLyricsBySongId', 'getLyrics']
    nav.request = lambda *a, **kw: {}
    assert nav.lyrics('missing') == ''
    def unavailable(*a, **kw):
        raise HTTPException(502, 'offline')
    nav.request = unavailable
    assert nav.lyrics('offline') == ''
