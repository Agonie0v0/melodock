"""Real sockets exercise both provider backends without touching real LAN services."""
import io
from contextlib import closing
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
import wave

import pytest
import requests

import public_http
from resumable_download import transfer


@pytest.fixture
def server(monkeypatch):
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            seen.append((self.path, requests.structures.CaseInsensitiveDict(self.headers)))
            body = b'audio'
            if self.path == '/playlist.m3u8':
                body = b'#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nsegment.aac\n#EXT-X-ENDLIST\n'
            self.send_response(302 if self.path.startswith('/redirect') else 200)
            if self.path == '/redirect-private':
                self.send_header('Location', f'http://127.0.0.1:{self.server.server_port}/secret')
            elif self.path == '/redirect-cross':
                self.send_header('Location', f'http://other.example:{self.server.server_port}/audio')
            elif self.path == '/redirect-same':
                self.send_header('Location', '/audio')
                self.send_header('Set-Cookie', 'fresh=ok; Path=/')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_POST(self):
            seen.append((self.path, requests.structures.CaseInsensitiveDict(self.headers)))
            self.send_response(307)
            self.send_header('Location', f'http://other.example:{self.server.server_port}/audio')
            self.send_header('Content-Length', '0')
            self.end_headers()
    value = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=value.serve_forever, daemon=True)
    thread.start()
    resolve = public_http.public_url
    def fixture_url(url):
        parsed = public_http.urlsplit(url)
        if parsed.hostname in {'audio.example', 'other.example'}:
            return parsed, ['127.0.0.1']
        return resolve(url)
    # Only these fixture hostnames may dial our temporary listener.
    monkeypatch.setattr(public_http, 'public_url', fixture_url)
    try:
        yield f'http://audio.example:{value.server_port}', seen
    finally:
        value.shutdown()
        value.server_close()
        thread.join(timeout=5)


@pytest.fixture(params=['requests', 'curl'])
def session(request):
    if request.param == 'curl':
        from curl_cffi.requests import Session
    else:
        Session = requests.Session
    with Session() as value:
        yield public_http.protect_session(value)


@pytest.mark.parametrize('url', ['http://127.0.0.1/x', 'http://[::1]/x',
    'http://169.254.169.254/x', 'http://224.0.0.1/x', 'file:///etc/passwd',
    'https://user:pass@audio.example/x'])
def test_reject_private_and_non_http_destinations(url):
    with pytest.raises(ValueError):
        public_http.public_url(url)


def test_mixed_dns_answers_are_rejected(monkeypatch):
    monkeypatch.setattr(public_http.socket, 'getaddrinfo', lambda *a, **k: [
        (None, None, None, None, (ip, 80)) for ip in ['93.184.216.34', '10.0.0.1']])
    with pytest.raises(ValueError):
        public_http.public_url('http://audio.example/file')


def test_real_transport_pins_dns_and_preserves_range_and_cookies(server, session):
    base, seen = server
    session.cookies.set('scoped', 'keep', domain='audio.example', path='/')
    with closing(session.get(base + '/audio', headers={'Range': 'bytes=0-', 'Host': 'attacker.invalid'},
                             cookies={'provider': 'keep'}, stream=True)) as response:
        assert response.status_code == 200 and b''.join(response.iter_content()) == b'audio'
        assert response.url == base + '/audio'
    assert seen[0][1]['Host'] == base.removeprefix('http://')
    assert seen[0][1]['Range'] == 'bytes=0-'
    assert 'scoped=keep' in seen[0][1]['Cookie'] and 'provider=keep' in seen[0][1]['Cookie']


def test_redirects_cannot_reach_private_services(server, session):
    base, seen = server
    with pytest.raises(ValueError, match='公网'):
        session.get(base + '/redirect-private')
    assert len(seen) == 1


def test_unreachable_ipv6_uses_next_validated_address(server, session, monkeypatch):
    base, seen = server
    original = public_http.public_url
    def addresses(url):
        parsed, ips = original(url)
        return parsed, ['::1', *ips]
    monkeypatch.setattr(public_http, 'public_url', addresses)
    with closing(session.get(base + '/audio')) as response:
        assert response.content == b'audio'
    assert len(seen) == 1


def test_explicit_http_proxy_receives_numeric_destination(server):
    import select
    import socket
    from curl_cffi.requests import Session
    from contextlib import closing
    base, seen = server
    tunnels = []
    class Proxy(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_CONNECT(self):
            tunnels.append(self.path)
            host, port = self.path.rsplit(':', 1)
            assert host == '127.0.0.1' and port == base.rsplit(':', 1)[1]
            with socket.create_connection((host, int(port))) as upstream:
                self.send_response(200)
                self.end_headers()
                while True:
                    readers, _, _ = select.select([self.connection, upstream], [], [], 5)
                    if not readers: return
                    for reader in readers:
                        data = reader.recv(65536)
                        if not data: return
                        (upstream if reader is self.connection else self.connection).sendall(data)
    proxy = ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
    proxy.daemon_threads = True
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    try:
        with Session() as client:
            with closing(public_http.request(client, 'GET', base + '/audio',
                         proxies={'http': f'http://127.0.0.1:{proxy.server_port}'})) as response:
                assert response.content == b'audio'
        assert tunnels == [f'127.0.0.1:{base.rsplit(":", 1)[1]}'] and len(seen) == 1
    finally:
        proxy.shutdown()
        proxy.server_close()
        thread.join(timeout=5)


def test_cross_origin_redirect_drops_credentials(server, session):
    base, seen = server
    session.headers['Authorization'] = 'Bearer fake'
    session.cookies.set('session_default', 'fake')
    with closing(session.get(base + '/redirect-cross', headers={'Cookie': 'header=fake'},
                             cookies={'account': 'fake'}, auth=('fake', 'fake'))) as response:
        assert response.content == b'audio'
    assert seen[0][1].get('Authorization')
    assert 'Authorization' not in seen[1][1] and 'Cookie' not in seen[1][1]


def test_same_origin_redirect_keeps_provider_credentials_and_response_cookie(server, session):
    base, seen = server
    with closing(session.get(base + '/redirect-same', cookies={'account': 'keep'})) as response:
        assert response.content == b'audio'
    assert 'account=keep' in seen[1][1]['Cookie'] and 'fresh=ok' in seen[1][1]['Cookie']


def test_redirect_cannot_replay_posted_credentials_to_another_origin(server, session):
    base, seen = server
    with pytest.raises(ValueError, match='跨站'):
        session.post(base + '/login', json={'password': 'fake-test-only'})
    assert len(seen) == 1


def test_no_automatic_tls_downgrade_or_explicit_disable(server, session, tmp_path):
    base, seen = server
    with pytest.raises(ValueError, match='TLS'):
        session.get(base + '/audio', verify=False)
    assert not seen
    attempts = []
    def fail(url, **kwargs):
        attempts.append(kwargs)
        raise requests.exceptions.SSLError('untrusted test certificate')
    song = SimpleNamespace(save_path=str(tmp_path / 'audio.flac'), download_url=base + '/audio',
                           default_download_headers={}, default_download_cookies={'account': 'fake'}, chunk_size=4)
    provider = SimpleNamespace(default_headers={}, get=fail)
    with pytest.raises(requests.exceptions.SSLError):
        transfer(provider, song, {'verify': True}, SimpleNamespace(update=lambda *a, **k: None), 0)
    assert len(attempts) == 1 and attempts[0]['verify'] is True
    assert not Path(song.save_path).exists()


def test_native_cover_rejects_local_files_and_private_urls(monkeypatch, tmp_path):
    from musicdl.modules.utils import SongInfoUtils
    public_http.install(lambda: {})
    sentinel = tmp_path / 'secret.txt'
    sentinel.write_text('must-not-be-embedded')
    monkeypatch.setattr(requests.Session, 'get', lambda *a, **k: pytest.fail('unsafe cover made a request'))
    for value in (str(sentinel), sentinel.as_uri(), 'http://127.0.0.1/secret'):
        with pytest.raises(ValueError):
            SongInfoUtils.loadimagebytesandmime(value)


def test_native_download_and_hls_and_link_probes_use_guarded_sessions(tmp_path):
    from musicdl.modules.sources.base import BaseMusicClient
    from musicdl.modules.utils.hls import HLSDownloader
    public_http.install(lambda: {})
    provider = BaseMusicClient(work_dir=str(tmp_path), disable_print=True, max_retries=1)
    assert provider.session._melokeep_public
    assert HLSDownloader(output_dir=str(tmp_path)).getsession()._melokeep_public
    with pytest.raises(ValueError):
        provider.audio_link_tester.request('GET', 'http://127.0.0.1/secret')
    assert provider.get('http://127.0.0.1/secret') is None


def test_hls_can_download_public_playlist_and_blocks_private_key_redirect(server, tmp_path):
    from musicdl.modules.utils.hls import HLSDownloader
    public_http.install(lambda: {})
    base, seen = server
    downloader = HLSDownloader(output_dir=str(tmp_path), concurrency=1, max_retries=1, backoff_base=0,
                               headers={'Referer': 'https://provider.example/'}, cookies={'account': 'keep'})
    from rich.progress import Progress
    with Progress(disable=True) as progress:
        task = progress.add_task('fixture', total=1)
        result = downloader.download(base + '/playlist.m3u8', str(tmp_path / 'result.aac'),
                                     remux=False, progress=progress, progress_id=task)
    assert Path(result.final_path).read_bytes() == b'audio'
    assert [path for path, _ in seen] == ['/playlist.m3u8', '/segment.aac']
    assert all(headers['Referer'] == 'https://provider.example/' and 'account=keep' in headers['Cookie']
               for _, headers in seen)
    with pytest.raises(RuntimeError):
        downloader.getkeybytes(base + '/redirect-private')
    assert seen[-1][0] == '/redirect-private' and not any(path == '/secret' for path, _ in seen)


def test_native_direct_helper_requests_are_public_only(tmp_path):
    from musicdl.modules.utils import songinfoutils
    public_http.install(lambda: {})
    with pytest.raises(ValueError):
        songinfoutils.requests.get('http://127.0.0.1/secret')


def test_native_preloaded_download_does_not_embed_local_secrets(tmp_path):
    from musicdl.modules import SongInfo
    from musicdl.modules.sources.base import BaseMusicClient
    from mutagen.wave import WAVE
    public_http.install(lambda: {})
    contents = io.BytesIO()
    with wave.open(contents, 'wb') as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(8000)
        writer.writeframes(b'\0\0' * 8000)
    secret = tmp_path / 'secret.txt'
    secret.write_bytes(b'PRIVATE_SECRET_SENTINEL')
    song = SongInfo(source='BaseMusicClient', song_name='safe', identifier='safe', ext='wav',
                    work_dir=str(tmp_path), downloaded_contents=contents.getvalue(), cover_url=str(secret))
    provider = BaseMusicClient(work_dir=str(tmp_path), disable_print=True)
    result = provider.download([song])
    assert len(result) == 1 and WAVE(result[0].save_path).info.length == 1
    assert b'PRIVATE_SECRET_SENTINEL' not in Path(result[0].save_path).read_bytes()
