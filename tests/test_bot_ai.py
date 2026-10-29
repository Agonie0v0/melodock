"""Channel messages use the real agent with isolated histories and durable replies."""
import asyncio
import base64
import json
import threading
import time
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import ai_agent
from bot_notifications import WecomCrypt
from test_bot_notifications import setup_bot, encrypt_callback


@pytest.fixture
def channel_agent(setup_bot):
    app, bot, store, _, track = setup_bot
    store.put('agent_settings', 'main', {'enabled': True, 'base_url': 'https://ai.example.test/v1', 'model': 'vision', 'api_key': 'private-ai-key'})
    async def search(keyword):
        return {'tracks': [track], 'detail': '找到歌曲'}
    async def download(track_ids, organize=False):
        ident = 'd' * 32
        store.put('download', ident, {'id': ident, 'status': 'queued', 'track': track})
        return {'downloads': [{'id': ident, 'status': 'queued', 'created': True}], 'detail': '已入队'}
    agent = ai_agent.install(app, get=store.get, put=store.put, values=store.values, remove=store.remove,
                             operations={'search_music': search, 'download_music': download})
    bot.ai_agent = agent
    bot.config.update(tg_ai_enabled=True, wecom_ai_enabled=True, bot_ai_allow_actions=True)
    bot.corp, bot.agent, bot.wecom_users = 'corp123', '100001', {'alice'}
    bot.crypt = WecomCrypt('verify-token', base64.b64encode(b'k' * 32).decode().rstrip('='), bot.corp)
    return bot, agent, store, app, track


def incoming(text, ident='a', user='123', channel='tg', **extra):
    return {'id': ident * 64, 'channel': channel, 'user': user, 'text': text, **extra}


async def finish(agent):
    await asyncio.gather(*(task for task, _ in list(agent.running.values())))


def call(name, args):
    return {'role': 'assistant', 'content': '', 'tool_calls': [{'id': name, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}]}


def test_text_channels_isolate_history_and_durable_results(channel_agent, monkeypatch):
    bot, agent, store, _, _ = channel_agent
    contexts = []
    def complete(settings, messages, tools):
        contexts.append(messages)
        return {'role': 'assistant', 'content': '回复：' + messages[-1]['content']}
    monkeypatch.setattr(ai_agent, 'completion', complete)
    async def scenario():
        for message in [incoming('甲用户第一条'), incoming('乙用户独立消息', 'b', '456'), incoming('企业微信消息', 'c', 'alice', 'wecom'), incoming('甲用户后续消息', 'e')]:
            await bot.command(message)
            await finish(agent)
        assert len(store.values('bot_ai_session')) == 3
        assert '甲用户第一条' in json.dumps(contexts[-1], ensure_ascii=False)
        assert '乙用户独立消息' not in json.dumps(contexts[-1], ensure_ascii=False)
        bot.queue_agent_notifications()
        replies = [item for item in store.values('bot_outbox') if item['text'].startswith('AI 助手')]
        assert len(replies) == 4
        assert '后续消息' not in next(item['text'] for item in replies if '回复：甲用户第一条' in item['text'])
        assert next(item for item in replies if '回复：企业微信消息' in item['text'])['user'] == 'alice'
        before = len(contexts)
        await bot.command(incoming('甲用户第一条'))
        bot.queue_agent_notifications()
        assert len(contexts) == before and len([i for i in store.values('bot_outbox') if i['text'].startswith('AI 助手')]) == 4
        with pytest.raises(HTTPException):
            await bot.command(incoming('/ai 窃取', 'f', 'outsider'))
    asyncio.run(scenario())


def test_agent_download_registers_owner_and_never_steals_another_task(channel_agent, monkeypatch):
    bot, agent, store, _, track = channel_agent
    responses = iter([call('search_music', {'keyword': '测试音乐'}), call('download_music', {'track_ids': [track['id']], 'organize': True}),
                      {'role': 'assistant', 'content': '歌曲已加入下载队列'}])
    monkeypatch.setattr(ai_agent, 'completion', lambda *args: next(responses))
    async def scenario():
        await bot.command(incoming('/ai 搜索并下载整理'))
        await finish(agent)
        bot.queue_agent_notifications()
        owned = store.get('bot_task', 'd' * 32)
        assert owned['owner'] == 'tg:123' and owned['notified'] is None
        assert owned['channel'] == 'tg'
        store.put('bot_task', 'd' * 32, {**owned, 'owner': 'tg:456', 'user': '456'})
        turn = store.values('bot_ai_turn')[0]
        store.put('bot_ai_turn', turn['id'], {**turn, 'notified': False})
        bot.queue_agent_notifications()
        assert store.get('bot_task', 'd' * 32)['owner'] == 'tg:456'
    asyncio.run(scenario())


@pytest.mark.parametrize('readonly', [True, False])
def test_readonly_and_global_permissions_enforced(channel_agent, monkeypatch, readonly):
    bot, agent, store, _, track = channel_agent
    advertised = []
    responses = iter([call('download_music', {'track_ids': [track['id']]}), {'role': 'assistant', 'content': '本轮仅查询'}])
    def complete(settings, messages, tools):
        advertised.extend(t['function']['name'] for t in tools)
        return next(responses)
    monkeypatch.setattr(ai_agent, 'completion', complete)
    async def scenario():
        if readonly:
            await bot.command(incoming('/ai_readonly', 'b'))
        else:
            bot.config['bot_ai_allow_actions'] = False
            await bot.command(incoming('/ai_write', 'b'))
        await bot.command(incoming('帮我下载'))
        await finish(agent)
        assert 'download_music' not in advertised
        assert not store.values('download')
        session = agent.session(store.get('bot_ai_session', 'tg:123')['session_id'])
        assert session['events'][0]['status'] == 'failed'
    asyncio.run(scenario())


def test_stop_and_new_session_do_not_block_other_commands(channel_agent, monkeypatch):
    bot, agent, store, _, _ = channel_agent
    entered, release = threading.Event(), threading.Event()
    def complete(*args):
        entered.set()
        release.wait(5)
        return call('search_music', {'keyword': '不得执行'})
    monkeypatch.setattr(ai_agent, 'completion', complete)
    async def scenario():
        await bot.command(incoming('开始任务'))
        assert await asyncio.to_thread(entered.wait, 2)
        ident = store.get('bot_ai_session', 'tg:123')['session_id']
        with pytest.raises(HTTPException) as error:
            await bot.command(incoming('另一条消息', 'b'))
        assert error.value.status_code == 409
        await bot.command(incoming('/ai_stop', 'c'))
        release.set()
        await finish(agent)
        assert agent.session(ident)['status'] == 'stopped'
        bot.queue_agent_notifications()
        await bot.command(incoming('/ai_new', 'e'))
        assert store.get('bot_ai_session', 'tg:123')['session_id'] != ident
        assert not agent.session(ident)['events']
    asyncio.run(scenario())


def test_picture_forwarded_in_memory_and_signed_wecom_callback(channel_agent, monkeypatch):
    bot, agent, store, app, _ = channel_agent
    image = 'data:image/png;base64,iVBORw0KGgo='
    bot.agent_image = Mock(return_value=image)
    seen = []
    def complete(settings, messages, tools):
        seen.append(messages[-1]['content'])
        return {'role': 'assistant', 'content': '识别出晴天和周杰伦'}
    monkeypatch.setattr(ai_agent, 'completion', complete)
    fields = b'<xml><ToUserName>corp123</ToUserName><FromUserName>alice</FromUserName><AgentID>100001</AgentID><MsgType>image</MsgType><MsgId>photo1</MsgId><MediaId>media-id</MediaId><PicUrl>http://127.0.0.1/private</PicUrl></xml>'
    encrypted, query = encrypt_callback(bot, fields)
    client = TestClient(app)
    for _ in range(2):
        assert client.post('/bot/wecom', params=query, content=f'<xml><Encrypt>{encrypted}</Encrypt></xml>').status_code == 200
    assert bot.pending.qsize() == 1
    pending = store.values('bot_inbox')[0]
    assert pending['image'] == {'id': 'media-id'}
    async def scenario():
        await bot.command(pending)
        await finish(agent)
        bot.queue_agent_notifications()
        assert seen[0][1]['image_url']['url'] == image
        assert image not in json.dumps(list(store.records.values()), default=str)
    asyncio.run(scenario())


def test_telegram_photo_intake_rejects_groups_and_unknown_users(channel_agent):
    bot, _, store, _, _ = channel_agent
    def photo(ident, user, chat_type='private'):
        return {'update_id': ident, 'message': {'from': {'id': user}, 'chat': {'id': user, 'type': chat_type}, 'caption': '加入截图收藏',
            'photo': [{'file_id': 'small', 'file_size': 100}, {'file_id': 'large', 'file_size': 1000}]}}
    bot.telegram = Mock(side_effect=[[photo(1, 999), photo(2, 123, 'group'), photo(3, 123)], *([[]] * 1000)])
    async def scenario():
        task = asyncio.create_task(bot.poll_telegram())
        for _ in range(100):
            if store.get('bot_setting', 'tg_offset') == 4:
                break
            await asyncio.sleep(.01)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        messages = store.values('bot_inbox')
        assert len(messages) == 1 and messages[0]['image'] == {'id': 'large', 'size': 1000}
        assert messages[0]['text'] == '加入截图收藏'
    asyncio.run(scenario())


def test_media_download_limits_and_platform_endpoints(channel_agent):
    bot, _, _, _, _ = channel_agent
    png = b'\x89PNG\r\n\x1a\n'
    response = Mock(status_code=200)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.iter_content.return_value = [png]
    bot.telegram = Mock(return_value={'file_path': 'photos/file.png', 'file_size': len(png)})
    bot.tg_http.get = Mock(return_value=response)
    result = bot.agent_image(incoming('', image={'id': 'file-id'}))
    assert result.startswith('data:image/png;base64,')
    assert bot.tg_http.get.call_args.args[0] == 'https://api.telegram.org/file/bottest-token/photos/file.png'
    assert bot.tg_http.get.call_args.kwargs['allow_redirects'] is False
    bot.wecom_access = Mock(return_value='access')
    bot.wecom_http.get = Mock(return_value=response)
    assert bot.agent_image(incoming('', user='alice', channel='wecom', image={'id': 'wecom-media'})) == result
    assert bot.wecom_http.get.call_args.kwargs['params']['media_id'] == 'wecom-media'
    response.iter_content.return_value = [b'x' * (5 * 1024 * 1024 + 1)]
    with pytest.raises(HTTPException) as error:
        bot.agent_image(incoming('', image={'id': 'large'}))
    assert error.value.status_code == 400
    bot.telegram.return_value = {'file_path': '../secret.png'}
    with pytest.raises(HTTPException):
        bot.agent_image(incoming('', image={'id': 'evil'}))


def test_local_api_picture_paths_stay_inside_cache(channel_agent, tmp_path, monkeypatch):
    bot, _, _, _, _ = channel_agent
    monkeypatch.setenv('MELOKEEP_DATA_DIR', str(tmp_path))
    root = tmp_path / 'telegram-bot-api'
    root.mkdir()
    picture = root / 'photo.png'
    picture.write_bytes(b'\x89PNG\r\n\x1a\n')
    bot.config['tg_local_enabled'] = True
    bot.telegram = Mock(return_value={'file_path': str(picture)})
    assert bot.agent_image(incoming('', image={'id': 'local'})).startswith('data:image/png;')
    outside = tmp_path / 'secret.png'
    outside.write_bytes(picture.read_bytes())
    bot.telegram.return_value = {'file_path': str(outside)}
    with pytest.raises(HTTPException):
        bot.agent_image(incoming('', image={'id': 'outside'}))


def test_replay_after_another_turn_and_restart_never_runs_tools_twice(channel_agent, monkeypatch):
    bot, agent, store, _, _ = channel_agent
    complete = Mock(return_value={'role': 'assistant', 'content': '已完成'})
    monkeypatch.setattr(ai_agent, 'completion', complete)
    async def scenario():
        await bot.command(incoming('/ai 第一轮'))
        await finish(agent)
        await bot.command(incoming('/ai 第二轮', 'b'))
        await finish(agent)
        # Simulate the crash window after starting work but before writing bot routing metadata.
        store.remove('bot_ai_turn', 'a' * 64)
        await bot.command(incoming('/ai 第一轮'))
        await finish(agent)
        assert complete.call_count == 2
        ident = store.get('bot_ai_session', 'tg:123')['session_id']
        session = agent.session(ident)
        session.update(status='interrupted', request_id='c' * 64)
        agent.save(session)
        store.put('agent_result', 'c' * 64, {'id': 'c' * 64, 'status': 'running'})
        await bot.command(incoming('/ai 第三轮', 'c'))
        await finish(agent)
        assert complete.call_count == 2
        bot.queue_agent_notifications()
        assert any('已中断' in item['text'] for item in store.values('bot_outbox'))
    asyncio.run(scenario())


def test_ai_is_opt_in_and_explicit_search_keeps_original_behavior(channel_agent):
    bot, agent, store, _, _ = channel_agent
    async def scenario():
        await bot.command(incoming('/search 纯搜索'))
        assert not store.values('bot_ai_session') and not agent.running
        bot.config['tg_ai_enabled'] = False
        with pytest.raises(HTTPException) as error:
            await bot.command(incoming('/ai 请下载'))
        assert error.value.status_code == 400
        assert not store.values('bot_ai_session')
    asyncio.run(scenario())
