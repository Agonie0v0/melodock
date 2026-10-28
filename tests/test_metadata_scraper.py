"""Metadata adapters must preserve release identity and never guess a version."""
import requests
import pytest

from metadata_scraper import MetadataScraper, pick, rank

RELEASE = '12345678-1234-1234-1234-123456789012'
RECORDING = '87654321-1234-1234-1234-123456789012'


@pytest.mark.parametrize('url,addresses', [
    ('http://127.0.0.1/cover', ['127.0.0.1']),
    ('http://[::1]/cover', ['::1']),
    ('http://cover.example/cover', ['93.184.216.34', '10.0.0.1']),
    ('http://169.254.169.254/cover', ['169.254.169.254']),
    ('http://224.0.0.1/cover', ['224.0.0.1']),
    ('file:///etc/passwd', []),
    ('https://user:password@cover.example/cover', []),
])
def test_cover_rejects_unsafe_destinations_before_request(monkeypatch, url, addresses):
    monkeypatch.setattr('metadata_scraper.socket.getaddrinfo', lambda *a, **k: [(None, None, None, None, (ip, 80)) for ip in addresses])
    monkeypatch.setattr(requests.Session, 'get', lambda *a, **k: pytest.fail('unsafe cover must not send a request'))
    with pytest.raises(ValueError):
        MetadataScraper(lambda: {}).cover(url)


def test_cover_pins_addresses_and_validates_every_redirect(monkeypatch):
    from metadata_scraper import _CoverHTTPSAdapter
    lookups, calls, adapters = [], [], []
    def resolve(host, port, **kwargs):
        lookups.append(host)
        ip = '127.0.0.1' if host == 'private.example' else '93.184.216.34'
        return [(None, None, None, None, (ip, port))]
    class Response:
        def __init__(self, redirect=None):
            self.is_redirect = redirect is not None
            self.headers = {'Location': redirect} if redirect else {}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_content(self, size): return iter([b'\x89PNG\r\n\x1a\nfixture'])
    class Session:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def mount(self, scheme, adapter): adapters.append(adapter)
        def get(self, url, **kwargs):
            calls.append((url, kwargs, self.trust_env))
            return responses.pop(0)
    monkeypatch.setattr('metadata_scraper.socket.getaddrinfo', resolve)
    monkeypatch.setattr('metadata_scraper.requests.Session', Session)
    responses = [Response('/final'), Response()]
    scraper = MetadataScraper(lambda: {'proxy_scope': 'all', 'proxy_url': 'http://proxy:8080'})
    assert scraper.cover('https://cover.example/start')[1] == 'image/png'
    assert lookups == ['cover.example', 'cover.example']
    assert [call[0] for call in calls] == ['https://93.184.216.34:443/start', 'https://93.184.216.34:443/final']
    assert all(call[1]['headers']['Host'] == 'cover.example' and not call[1]['allow_redirects'] and not call[2] for call in calls)
    assert calls[0][1]['proxies']['https'] == 'http://proxy:8080'
    assert all(isinstance(adapter, _CoverHTTPSAdapter) and adapter.poolmanager.connection_pool_kw['assert_hostname'] == 'cover.example'
               and adapter.poolmanager.connection_pool_kw['server_hostname'] == 'cover.example' for adapter in adapters)
    for redirect in ['http://private.example/cover', 'http://127.0.0.1/private', 'http://[::1]/private']:
        responses = [Response(redirect)]
        calls.clear()
        with pytest.raises(ValueError): scraper.cover('https://cover.example/start')
        assert len(calls) == 1
    responses = [Response('/loop') for _ in range(6)]
    with pytest.raises(ValueError, match='跳转次数'):
        scraper.cover('https://cover.example/start')
    # An unreachable IPv6 address must still fall back to the validated IPv4 address.
    monkeypatch.setattr('metadata_scraper.socket.getaddrinfo', lambda *a, **k: [
        (None, None, None, None, (ip, 443)) for ip in ['2606:4700:4700::1111', '93.184.216.34']])
    def fail_first(self, url, **kwargs):
        calls.append((url, kwargs, self.trust_env))
        if '[' in url: raise requests.ConnectionError('IPv6 unavailable')
        return Response()
    monkeypatch.setattr(Session, 'get', fail_first)
    calls.clear()
    assert scraper.cover('https://cover.example/image')[1] == 'image/png'
    assert [call[0] for call in calls] == ['https://[2606:4700:4700::1111]:443/image', 'https://93.184.216.34:443/image']


@pytest.mark.parametrize('via_proxy', [False, True])
def test_cover_pinned_https_preserves_certificate_validation(monkeypatch, tmp_path, via_proxy):
    import datetime
    import ssl
    import select
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    import urllib3.util.connection
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, 'cover.example')])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('cover.example')]), critical=False)
            .sign(key, hashes.SHA256()))
    cert_file, key_file = tmp_path / 'cert.pem', tmp_path / 'key.pem'
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def handle(self):
            try: super().handle()
            except ConnectionResetError: pass  # Rejected TLS peers may reset their connection on Windows.
        def do_GET(self):
            seen.append(self.headers['Host'])
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'\x89PNG\r\n\x1a\nfixture')
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert_file, key_file)
    sni = []
    tls.set_servername_callback(lambda sock, hostname, ctx: sni.append(hostname))
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    real_session, real_resolve = requests.Session, __import__('socket').getaddrinfo
    real_connect = urllib3.util.connection.create_connection
    tunnels = []
    class Proxy(BaseHTTPRequestHandler):
        def do_CONNECT(self):
            tunnels.append(self.path)
            with real_connect(('127.0.0.1', server.server_port)) as upstream:
                self.send_response(200)
                self.end_headers()
                while True:
                    readers, _, _ = select.select([self.connection, upstream], [], [], 5)
                    if not readers: return
                    for reader in readers:
                        data = reader.recv(65536)
                        if not data: return
                        (upstream if reader is self.connection else self.connection).sendall(data)
        def log_message(self, *args): pass
    proxy = ThreadingHTTPServer(('127.0.0.1', 0), Proxy) if via_proxy else None
    if proxy:
        proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
        proxy_thread.start()
    def session():
        value = real_session()
        value.verify = str(cert_file)
        return value
    def resolve(host, port, *args, **kwargs):
        if host.endswith('.example'):
            return [(None, None, None, None, ('93.184.216.34', port))]
        return real_resolve(host, port, *args, **kwargs)
    def connect(address, *args, **kwargs):
        if address[0] == '93.184.216.34':
            address = ('127.0.0.1', server.server_port)
        else:
            assert proxy and address == ('127.0.0.1', proxy.server_port)
        return real_connect(address, *args, **kwargs)
    monkeypatch.setattr('metadata_scraper.requests.Session', session)
    monkeypatch.setattr('metadata_scraper.socket.getaddrinfo', resolve)
    monkeypatch.setattr(urllib3.util.connection, 'create_connection', connect)
    try:
        scraper = MetadataScraper(lambda: {'proxy_scope': 'all', 'proxy_url': f'http://127.0.0.1:{proxy.server_port}'} if proxy else {})
        assert scraper.cover('https://cover.example/image')[1] == 'image/png'
        assert seen == ['cover.example'] and sni == ['cover.example']
        if proxy: assert tunnels == ['93.184.216.34:443']
        with pytest.raises(requests.exceptions.SSLError):
            scraper.cover('https://wrong.example/image')
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        if proxy:
            proxy.shutdown()
            proxy.server_close()
            proxy_thread.join(timeout=5)


def test_musicbrainz_search_and_release_enrichment(monkeypatch):
    scraper = MetadataScraper(lambda: {})
    calls = []
    def query(path, params):
        calls.append((path, params))
        if path == 'recording':
            return {'recordings': [{'id': RECORDING, 'title': 'Song', 'length': 200000,
                                   'artist-credit': [{'name': 'Artist'}],
                                   'releases': [{'id': RELEASE, 'title': 'Album', 'date': '2020'}]}]}
        return {'title': 'Album', 'date': '2020-02-03', 'artist-credit': [{'name': 'Album Artist'}],
                'cover-art-archive': {'front': True},
                'media': [{'position': 2, 'tracks': [{'position': 3, 'recording': {'id': RECORDING}}]}]}
    monkeypatch.setattr(scraper, 'musicbrainz', query)
    candidates = scraper.search_musicbrainz({'title': 'Song', 'artist': 'Artist'})
    assert candidates[0]['duration'] == 200
    result, warnings = scraper.enrich(candidates[0], want_lyrics=False)
    assert not warnings and result['album_artist'] == 'Album Artist'
    assert result['date'] == '2020-02-03' and result['track_number'] == '3' and result['disc_number'] == '2'
    assert result['cover_url'] == f'https://coverartarchive.org/release/{RELEASE}/front-500'
    assert calls[0][1]['query'] == 'recording:"Song" AND artist:"Artist"'
    assert calls[1][0] == f'release/{RELEASE}'


def test_release_ambiguity_and_live_versions_require_review():
    ref = {'title': 'Song', 'artist': 'Artist', 'album': 'Album', 'duration': 200}
    candidate = {**ref, 'source': 'musicbrainz', 'source_id': RECORDING, 'release_id': RELEASE}
    other = {**candidate, 'release_id': '00000000-1234-1234-1234-123456789012'}
    ranked, selected = pick(ref, [candidate, other])
    assert len(ranked) == 2 and selected is None
    assert pick(ref, [{**candidate, 'version': 'live'}])[1] is None
    assert pick(ref, [{**candidate, 'album': 'Greatest Hits'}])[1] is None
    assert pick(ref, [candidate])[1]


def test_repeated_recording_in_release_does_not_guess_track_number(monkeypatch):
    scraper = MetadataScraper(lambda: {})
    monkeypatch.setattr(scraper, 'musicbrainz', lambda *a: {'media': [{'position': 1, 'tracks': [
        {'position': position, 'recording': {'id': RECORDING}} for position in [1, 5]]}]})
    result, warnings = scraper.enrich({'source': 'musicbrainz', 'source_id': RECORDING, 'release_id': RELEASE})
    assert 'track_number' not in result and 'cover_url' not in result
    assert any('不提供歌词' in warning for warning in warnings)


def test_source_failure_does_not_discard_other_candidates(monkeypatch):
    scraper = MetadataScraper(lambda: {})
    monkeypatch.setattr(scraper, 'provider', lambda source: (_ for _ in ()).throw(requests.Timeout()))
    monkeypatch.setattr(scraper, 'search_musicbrainz', lambda ref: [{'title': 'Song', 'source': 'musicbrainz'}])
    candidates, warnings = scraper.search({'title': 'Song'}, ['netease', 'musicbrainz'])
    assert len(candidates) == 1 and '网易云查询失败' in warnings[0]


def test_musicbrainz_request_identification_proxy_and_rate_limit(monkeypatch):
    scraper = MetadataScraper(lambda: {'proxy_scope': 'all', 'proxy_url': 'http://proxy:8080'})
    calls, sleeps = [], []
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {'recordings': []}
    monkeypatch.setattr('metadata_scraper.requests.get', lambda url, **kw: calls.append((url, kw)) or Response())
    monkeypatch.setattr('metadata_scraper.time.monotonic', lambda: 10)
    monkeypatch.setattr('metadata_scraper.time.sleep', sleeps.append)
    scraper.musicbrainz('recording', {'query': 'Song'})
    scraper.musicbrainz('recording', {'query': 'Other'})
    assert sleeps == pytest.approx([0, 1.1])
    assert 'MeloKeep/3.0' in calls[0][1]['headers']['User-Agent']
    assert 'github.com/Agonie0v0/melokeep' in calls[0][1]['headers']['User-Agent']
    assert calls[0][1]['proxies']['https'] == 'http://proxy:8080'
    assert calls[0][1]['params']['fmt'] == 'json'


def test_missing_fields_use_only_confident_same_album_fallback(monkeypatch):
    scraper = MetadataScraper(lambda: {})
    reference = {'source': 'migu', 'source_id': 'original', 'title': 'Song', 'artist': 'Artist', 'album': 'Album', 'duration': 200}
    primary = rank(reference, reference)
    alternate = rank(reference, {**reference, 'source': 'qq', 'source_id': 'qq-id'})
    calls = []
    def enrich(candidate, lyrics):
        calls.append(candidate['source'])
        return ({**candidate, 'lyrics': '[00:01]lyrics', 'date': '2020'} if candidate['source'] == 'qq' else candidate), []
    monkeypatch.setattr(scraper, '_enrich', enrich)
    result, warnings = scraper.enrich(primary, True, [primary, alternate])
    assert result['source'] == 'migu' and result['lyrics'] == '[00:01]lyrics'
    assert result['field_sources'] == {'date': 'qq', 'lyrics': 'qq'} and not warnings
    for other in [{**alternate, 'album': 'Compilation'}, {**alternate, 'duration': 220}, {**alternate, 'title': 'Song (Live)'}]:
        calls.clear()
        result, _ = scraper.enrich(primary, True, [primary, other])
        assert 'lyrics' not in result and calls == ['migu']
    live = {**primary, 'version': 'live'}
    assert 'lyrics' not in scraper.enrich(live, True, [alternate])[0]
    release = {**primary, 'release_id': RELEASE}
    assert 'lyrics' not in scraper.enrich(release, True, [{**alternate, 'release_id': '00000000-1234-1234-1234-123456789012'}])[0]
