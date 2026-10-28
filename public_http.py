"""Public provider transport: pin DNS, check redirects and keep TLS verification."""
import copy
import functools
import ipaddress
import socket
import sys
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests


def public_url(url):
    parsed = urlsplit(str(url).strip())
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
            or parsed.username or parsed.password):
        raise ValueError('远程资源仅允许不含账号密码的 HTTP/HTTPS 公网地址')
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    try:
        addresses = [str(ipaddress.ip_address(parsed.hostname))]
    except ValueError:
        addresses = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(
            parsed.hostname, port, type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(ip).is_global
                            or ipaddress.ip_address(ip).is_multicast for ip in addresses):
        raise ValueError('远程资源地址必须指向公网')
    return parsed, addresses


class PinnedHTTPSAdapter(requests.adapters.HTTPAdapter):
    def __init__(self, hostname):
        self.hostname = hostname
        super().__init__()

    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, assert_hostname=self.hostname,
                                 server_hostname=self.hostname, **kwargs)

    def proxy_manager_for(self, proxy, **kwargs):
        return super().proxy_manager_for(proxy, assert_hostname=self.hostname,
                                         server_hostname=self.hostname, **kwargs)


class _PinnedAdapter(PinnedHTTPSAdapter):
    def __init__(self, parsed, address):
        self.parsed, self.address = parsed, address
        super().__init__(parsed.hostname)

    def send(self, request, **kwargs):
        # Prepare cookies/auth against the real hostname before changing the dial URL.
        wire = copy.copy(request)
        wire.headers = request.headers.copy()
        wire.headers['Host'] = self.parsed.netloc
        host = f'[{self.address}]' if ':' in self.address else self.address
        port = self.parsed.port or (443 if self.parsed.scheme == 'https' else 80)
        wire.url = urlunsplit(urlsplit(request.url)._replace(netloc=f'{host}:{port}', fragment=''))
        response = super().send(wire, **kwargs)
        response.url, response.request = request.url, request
        return response


def _origin(parsed):
    return parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == 'https' else 80)


def request(session, method, url, **kwargs):
    """Keep provider sessions/backends, but never let them choose a second destination."""
    options = dict(kwargs)
    if options.get('verify', getattr(session, 'verify', True)) is False:
        raise ValueError('远程资源请求不能关闭 TLS 证书验证')
    follow = options.pop('allow_redirects', True)
    options.pop('max_redirects', None)
    options.setdefault('timeout', 30)
    headers = dict(getattr(session, 'headers', {}) or {})
    headers.update(options.pop('headers', {}) or {})
    cookies = options.pop('cookies', None)
    source_cookies = copy.copy(getattr(session, 'cookies', None))
    auth = options.pop('auth', getattr(session, 'auth', None))
    proxies = options.pop('proxies', getattr(session, 'proxies', {}) or {})
    previous = None
    is_curl = session.__class__.__module__.startswith('curl_cffi.')
    connection_errors = (requests.ConnectionError, requests.Timeout)
    certificate_errors = (requests.exceptions.SSLError,)
    if is_curl:
        from curl_cffi.requests import exceptions as curl_errors
        connection_errors += (curl_errors.ConnectionError, curl_errors.Timeout)
        certificate_errors += (curl_errors.SSLError,)
    for _ in range(6):
        parsed, addresses = public_url(url)
        origin = _origin(parsed)
        if previous and previous != origin:
            if previous[0] == 'https' and origin[0] != 'https':
                raise ValueError('远程资源不能从 HTTPS 跳转到 HTTP')
            if method.upper() not in {'GET', 'HEAD'} or any(options.get(key) for key in ('data', 'json', 'files', 'content')):
                raise ValueError('远程资源不能跨站重发提交内容')
            headers = {key: value for key, value in headers.items() if key.lower() not in {
                'authorization', 'cookie', 'proxy-authorization', 'host', 'referer'}}
            cookies, source_cookies, auth = None, None, None
        headers = {key: value for key, value in headers.items() if key.lower() != 'host'}
        response = None
        for index, address in enumerate(addresses):
            if is_curl:
                from curl_cffi import CurlOpt, ffi, lib
                from curl_cffi.requests import Session
                port = origin[2]
                ip = f'[{address}]' if ':' in address else address
                # CONNECT_TO also pins the target of an explicit proxy CONNECT tunnel.
                # curl_cffi exposes CONNECT_TO as a raw slist, unlike its RESOLVE helper.
                pins = lib.curl_slist_append(ffi.NULL, f'{parsed.hostname}:{port}:{ip}:{port}'.encode())
                transport = Session(trust_env=False, curl_options={
                    CurlOpt.CONNECT_TO: pins, CurlOpt.HTTPPROXYTUNNEL: 1})
                original_close = transport.close
                def close_curl(original_close=original_close, pins=pins, closed=[False]):
                    if not closed[0]:
                        closed[0] = True
                        try:
                            original_close()
                        finally:
                            lib.curl_slist_free_all(pins)
                transport.close = close_curl
            else:
                transport = requests.Session()
                transport.trust_env = False
                transport.mount(parsed.scheme + '://', _PinnedAdapter(parsed, address))
            transport.headers.update(headers)
            if source_cookies is not None:
                transport.cookies.update(source_cookies)
            transport.verify = getattr(session, 'verify', True)
            transport.cert = getattr(session, 'cert', None)
            try:
                response = transport.request(method, url, headers=headers, cookies=cookies,
                                             auth=auth, proxies=proxies, allow_redirects=False, **options)
            except Exception as error:
                transport.close()
                # Never downgrade certificate verification when another IP is tried.
                if (not isinstance(error, connection_errors)
                        or isinstance(error, certificate_errors) or index == len(addresses) - 1):
                    raise
                continue
            break
        close = response.close
        def close_response(close=close, transport=transport):
            try:
                close()
            finally:
                transport.close()
        response.close = close_response
        status = response.status_code
        location = response.headers.get('Location')
        if not follow or status not in {301, 302, 303, 307, 308} or not location:
            if getattr(session, 'cookies', None) is not None:
                session.cookies.update(transport.cookies)
            if not options.get('stream'):
                transport.close()
            return response
        # Only carry response cookies within the same origin on the next hop.
        source_cookies = copy.copy(transport.cookies)
        response.close()
        previous, url = origin, urljoin(url, location)
        options.pop('params', None)
        if ((status == 303 and method.upper() != 'HEAD')
                or (status in {301, 302} and method.upper() == 'POST')):
            method = 'GET'
            for key in ('data', 'json', 'files', 'content'):
                options.pop(key, None)
            headers = {key: value for key, value in headers.items()
                       if key.lower() not in {'content-type', 'content-length', 'transfer-encoding'}}
    raise ValueError('远程资源跳转次数过多')


def protect_session(session):
    if not getattr(session, '_melokeep_public', False):
        session.request = functools.partial(request, session)
        session.trust_env = False
        session._melokeep_public = True
    return session


class _ProviderRequests:
    """Restrict direct requests made by native helper modules, without global patches."""
    def __getattr__(self, name):
        if name == 'Session':
            return lambda *a, **k: protect_session(requests.Session(*a, **k))
        if name in {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'request'}:
            def fetch(*args, **kwargs):
                if name == 'request':
                    method, rest = (args[0], args[1:]) if args else (kwargs.pop('method'), ())
                else:
                    method, rest = name.upper(), args
                if name == 'head':
                    kwargs.setdefault('allow_redirects', False)
                url = rest[0] if rest else kwargs.pop('url')
                with requests.Session() as session:
                    return request(session, method, url, **kwargs)
            return fetch
        return getattr(requests, name)


provider_requests = _ProviderRequests()


def install(engine_config):
    """Cover native downloads, link probes and every HLS playlist/segment/key."""
    from musicdl.modules.sources.base import BaseMusicClient
    from musicdl.modules.utils import AudioLinkTester, SongInfoUtils
    from musicdl.modules.utils.hls import HLSDownloader
    if getattr(BaseMusicClient, '_melokeep_public', False):
        return
    initialize = BaseMusicClient._initsession
    @functools.wraps(initialize)
    def init_session(self):
        initialize(self)
        protect_session(self.session)
    BaseMusicClient._initsession = init_session
    probe = AudioLinkTester.request
    @functools.wraps(probe)
    def probe_request(self, *args, **kwargs):
        protect_session(self.session)
        return probe(self, *args, **kwargs)
    AudioLinkTester.request = probe_request
    get_session = HLSDownloader.getsession
    @functools.wraps(get_session)
    def hls_session(self):
        return protect_session(get_session(self))
    HLSDownloader.getsession = hls_session
    def cover_bytes(cover, *, timeout=15):
        from metadata_scraper import MetadataScraper
        return MetadataScraper(engine_config).cover(str(cover))
    SongInfoUtils.loadimagebytesandmime = staticmethod(cover_bytes)
    for name, module in list(sys.modules.items()):
        if name.startswith('musicdl.') and getattr(module, 'requests', None) is requests:
            module.requests = provider_requests
    BaseMusicClient._melokeep_public = True
