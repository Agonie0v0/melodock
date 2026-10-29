"""Agent protocol, real route behavior, multimodal input and action boundaries."""
import copy
import json
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ai_agent


@pytest.fixture
def agent():
    records = {}
    def get(kind, key, default=None):
        return copy.deepcopy(records.get((kind, key), default))
    def put(kind, key, value):
        records[kind, key] = copy.deepcopy(value)
    def values(kind):
        return [copy.deepcopy(v) for (k, _), v in records.items() if k == kind]
    calls = []
    async def search(keyword):
        calls.append(('search', keyword))
        return {'tracks': [{'id': 'song-1', 'title': '晴天', 'artist': '周杰伦'}], 'detail': '找到歌曲'}
    def add(playlist_id, track_ids):
        calls.append(('add', playlist_id, track_ids))
        return {'id': playlist_id, 'detail': '已加入歌单'}
    app = FastAPI()
    service = ai_agent.install(app, get=get, put=put, values=values, remove=lambda k, i: records.pop((k, i), None),
                               operations={'search_music': search, 'add_to_playlist': add, 'get_status': lambda: {'detail': '无下载'}})
    with TestClient(app) as client:
        client.put('/api/agent/settings', json={'enabled': True, 'base_url': 'https://example.test/v1', 'model': 'vision-model', 'api_key': 'test-secret'})
        yield SimpleNamespace(client=client, service=service, records=records, calls=calls)


def tool(name, arguments, ident='call-1'):
    return {'id': ident, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}}


def message(*calls, content=''):
    result = {'role': 'assistant', 'content': content}
    if calls:
        result['tool_calls'] = list(calls)
    return result


def run(agent, body, ident=None):
    client = agent.client
    ident = ident or client.post('/api/agent/sessions').json()['id']
    result = client.post(f'/api/agent/sessions/{ident}/messages', json=body)
    assert result.status_code == 200, result.text
    for _ in range(400):
        result = client.get(f'/api/agent/sessions/{ident}').json()
        if result['status'] not in {'running', 'stopping'}:
            return result
        time.sleep(.01)
    pytest.fail('agent did not finish')


def test_screenshot_search_add_and_followup(agent, monkeypatch):
    requests = []
    responses = iter([message(tool('search_music', {'keyword': '晴天 周杰伦'})),
                      message(tool('add_to_playlist', {'playlist_id': 'playlist-1', 'track_ids': ['song-1']})),
                      message(content='已加入歌单'), message(content='上一轮已加入晴天')])
    def complete(settings, messages, tools):
        requests.append(copy.deepcopy(messages))
        return next(responses)
    monkeypatch.setattr(ai_agent, 'completion', complete)
    image = 'data:image/png;base64,iVBORw0KGgo='
    result = run(agent, {'message': '把图片上的歌曲加入歌单', 'image': image})
    assert result['status'] == 'complete'
    assert agent.calls == [('search', '晴天 周杰伦'), ('add', 'playlist-1', ['song-1'])]
    assert requests[0][-1]['content'][1]['image_url']['url'] == image
    assert [m['role'] for m in requests[2]] == ['system', 'user', 'assistant', 'tool', 'assistant', 'tool']
    assert len(result['events']) == 2 and 'history' not in result
    saved = agent.records['agent_session', result['id']]
    assert image not in json.dumps(saved)
    assert all(e['status'] == 'complete' for e in result['events'])
    followup = run(agent, {'message': '刚才加了什么？'}, result['id'])
    assert followup['messages'][-1]['content'] == '上一轮已加入晴天'


@pytest.mark.parametrize('call,allow,expected', [
    (tool('add_to_playlist', {'playlist_id': 'p', 'track_ids': ['invented']}), True, '歌曲 ID'),
    (tool('add_to_playlist', {'playlist_id': 'p', 'track_ids': ['song-1']}), False, '未允许'),
    (tool('execute_shell', {'cmd': 'whoami'}), True, '未允许'),
    (tool('search_music', {'keyword': 'a', 'extra': 'oops'}), True, '参数无效'),
])
def test_tool_boundaries(agent, monkeypatch, call, allow, expected):
    responses = iter([message(call), message(content='无法执行')])
    monkeypatch.setattr(ai_agent, 'completion', lambda *args: next(responses))
    result = run(agent, {'message': '操作', 'allow_actions': allow})
    assert result['events'][0]['status'] == 'failed'
    assert expected in result['events'][0]['detail']
    assert not agent.calls


def test_secret_retention_clear_and_endpoint_validation(agent):
    client = agent.client
    assert 'test-secret' not in client.get('/api/agent/settings').text
    update = {'enabled': True, 'base_url': 'http://localhost:1234/v1/', 'model': 'local', 'api_key': ''}
    assert client.put('/api/agent/settings', json=update).json()['key_configured']
    assert agent.service.settings()['api_key'] == 'test-secret'
    assert agent.service.settings()['base_url'] == 'http://localhost:1234/v1'
    assert not client.put('/api/agent/settings', json={**update, 'clear_key': True}).json()['key_configured']
    for url in ['file:///private', 'https://user:password@example.test', 'https://example.test/v1?key=x']:
        assert client.put('/api/agent/settings', json={**update, 'base_url': url}).status_code == 422


def test_invalid_image_and_empty_turn(agent):
    ident = agent.client.post('/api/agent/sessions').json()['id']
    for image in ['https://example.test/image.png', 'data:image/png;base64,bm90LXBuZw==', 'data:image/svg+xml;base64,YQ==']:
        assert agent.client.post(f'/api/agent/sessions/{ident}/messages', json={'image': image}).status_code == 422
    assert agent.client.post(f'/api/agent/sessions/{ident}/messages', json={}).status_code == 400


def test_stop_preserves_completed_operations_and_excludes_overlap(agent, monkeypatch):
    import threading
    entered, release = threading.Event(), threading.Event()
    def complete(*args):
        entered.set()
        release.wait(5)
        return message(tool('search_music', {'keyword': 'do not run'}))
    monkeypatch.setattr(ai_agent, 'completion', complete)
    client = agent.client
    ident = client.post('/api/agent/sessions').json()['id']
    assert client.post(f'/api/agent/sessions/{ident}/messages', json={'message': '搜索'}).status_code == 200
    assert entered.wait(2)
    assert client.post(f'/api/agent/sessions/{ident}/messages', json={'message': '重试'}).status_code == 409
    assert client.delete(f'/api/agent/sessions/{ident}').status_code == 409
    assert client.post(f'/api/agent/sessions/{ident}/stop').json()['status'] == 'stopping'
    release.set()
    for _ in range(200):
        result = client.get(f'/api/agent/sessions/{ident}').json()
        if result['status'] == 'stopped':
            break
        time.sleep(.01)
    assert result['status'] == 'stopped' and not agent.calls
    assert client.delete(f'/api/agent/sessions/{ident}').status_code == 200


def test_provider_failure_is_visible_and_no_credentials_leak(agent, monkeypatch):
    def complete(*args):
        raise ai_agent.HTTPException(502, 'AI 接口返回 HTTP 401')
    monkeypatch.setattr(ai_agent, 'completion', complete)
    result = run(agent, {'message': '搜索'})
    assert result['status'] == 'failed' and '401' in result['detail']
    assert 'test-secret' not in json.dumps(result)


def test_http_protocol_sanitization_and_error_redaction(monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.status_code = 200
    response.iter_content.return_value = [json.dumps({'choices': [{'message': {**message(tool('get_status', {})), 'reasoning_content': 'private'}}]}).encode()]
    post = Mock(return_value=response)
    monkeypatch.setattr(ai_agent.requests, 'post', post)
    settings = {'base_url': 'https://example.test/v1', 'api_key': 'secret', 'model': 'model'}
    result = ai_agent.completion(settings, [{'role': 'user', 'content': 'hi'}], [])
    assert result['tool_calls'][0]['function']['name'] == 'get_status'
    assert 'reasoning_content' not in result
    assert post.call_args.args[0] == 'https://example.test/v1/chat/completions'
    assert post.call_args.kwargs['allow_redirects'] is False
    response.iter_content.return_value = [json.dumps({'choices': [{'message': {'content': '连接成功', 'tool_calls': None}}]}).encode()]
    assert ai_agent.completion(settings, [], []) == {'role': 'assistant', 'content': '连接成功'}
    response.status_code = 401
    with pytest.raises(ai_agent.HTTPException, match='401'):
        ai_agent.completion(settings, [], [])
