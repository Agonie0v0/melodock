"""Metadata adapters must preserve release identity and never guess a version."""
import requests
import pytest

from metadata_scraper import MetadataScraper, pick, rank

RELEASE = '12345678-1234-1234-1234-123456789012'
RECORDING = '87654321-1234-1234-1234-123456789012'


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
