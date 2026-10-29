"""Verified application callbacks and independent notification/AI paths."""
import asyncio
import base64
import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, Mock

import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import HTTPException
from fastapi.testclient import TestClient

import ai_agent
import bot_channels
from bot_notifications import BotService
from test_bot_notifications import setup_bot, completed_job
from test_bot_ai import channel_agent, finish


@pytest.fixture
def bridge(channel_agent):
    bot, agent, store, app, track = channel_agent
    key = Ed25519PrivateKey.generate()
    bot.config.update(feishu_bot_enabled=True, feishu_ai_enabled=True, feishu_app_id='app',
        feishu_app_secret='fs-secret', feishu_verification_token='fs-verify', feishu_encrypt_key='fs-encrypt',
        feishu_allowed_users='ou_alice', dingtalk_bot_enabled=True, dingtalk_ai_enabled=True,
        dingtalk_client_id='app-ding', dingtalk_client_secret='ding-secret', dingtalk_robot_code='robot',
        dingtalk_allowed_users='alice', discord_bot_enabled=True, discord_ai_enabled=True,
        discord_application_id='100', discord_public_key=key.public_key().public_bytes_raw().hex(),
        discord_bot_token='discord-secret', discord_allowed_users='123')
    return bot, agent, store, app, key


def payload(channel, text='帮我查询歌曲', ident='event1'):
    if channel == 'feishu':
        return {'schema': '2.0', 'header': {'app_id': 'app', 'token': 'fs-verify',
                'event_type': 'im.message.receive_v1', 'event_id': ident},
                'event': {'sender': {'sender_type': 'user', 'sender_id': {'open_id': 'ou_alice'}},
                          'message': {'chat_type': 'p2p', 'message_type': 'text', 'message_id': ident,
                                      'content': json.dumps({'text': text})}}}
    if channel == 'dingtalk':
        return {'robotCode': 'robot', 'conversationType': '1', 'senderStaffId': 'alice',
                'msgId': ident, 'msgtype': 'text', 'text': {'content': text},
                'sessionWebhook': 'http://127.0.0.1/never-follow-this'}
    return {'application_id': '100', 'id': ident, 'type': 2, 'user': {'id': '123'},
            'token': 'do-not-persist-interaction-token',
            'data': {'name': 'melokeep', 'options': [{'name': 'text', 'value': text}]}}


def request(client, channel, data, key, *, stale=False, bad=False, encrypt=False):
    if encrypt:
        pad = padding.PKCS7(128).padder()
        plain = pad.update(json.dumps(data).encode()) + pad.finalize()
        iv = b'i' * 16
        cipher = Cipher(algorithms.AES(hashlib.sha256(b'fs-encrypt').digest()), modes.CBC(iv)).encryptor()
        data = {'encrypt': base64.b64encode(iv + cipher.update(plain) + cipher.finalize()).decode()}
    raw = json.dumps(data).encode()
    timestamp = str(int(time.time() - (1000 if stale else 0)))
    if channel == 'feishu':
        signature = hashlib.sha256((timestamp + 'nonce' + 'fs-encrypt').encode() + raw).hexdigest()
        headers = {'X-Lark-Request-Timestamp': timestamp, 'X-Lark-Request-Nonce': 'nonce',
                   'X-Lark-Signature': 'bad' if bad else signature}
    elif channel == 'dingtalk':
        timestamp += '000'
        signature = base64.b64encode(hmac.new(b'ding-secret', (timestamp + '\nding-secret').encode(), hashlib.sha256).digest()).decode()
        headers = {'timestamp': timestamp, 'sign': 'bad' if bad else signature}
    else:
        signature = key.sign(timestamp.encode() + raw).hex()
        headers = {'X-Signature-Timestamp': timestamp, 'X-Signature-Ed25519': '00' * 64 if bad else signature}
    return client.post('/bot/' + channel, content=raw, headers=headers)


@pytest.mark.parametrize('channel', bot_channels.CHANNELS)
def test_callbacks_run_agent_once_with_private_replies(bridge, monkeypatch, channel):
    bot, agent, store, app, key = bridge
    complete = Mock(return_value={'role': 'assistant', 'content': '查询完成'})
    monkeypatch.setattr(ai_agent, 'completion', complete)
    client = TestClient(app)
    data = payload(channel)
    assert request(client, channel, data, key, encrypt=channel == 'feishu').status_code == 200
    assert request(client, channel, data, key, encrypt=channel == 'feishu').status_code == 200
    assert len(store.values('bot_inbox')) == 1
    async def run():
        message = bot.pending.get_nowait()
        await bot.command(message)
        await finish(agent)
        bot.queue_agent_notifications()
        await bot.command(message)
        bot.queue_agent_notifications()
    asyncio.run(run())
    complete.assert_called_once()
    outbox = store.values('bot_outbox')
    assert len([i for i in outbox if '查询完成' in i['text']]) == 1
    assert all(i['channel'] == channel and i['user'] != 'downloads' for i in outbox)
    assert 'do-not-persist-interaction-token' not in json.dumps(list(store.records.values()))
    assert all('token' not in message for message in store.values('bot_inbox'))


@pytest.mark.parametrize('channel', bot_channels.CHANNELS)
@pytest.mark.parametrize('failure', ['bad', 'stale', 'outsider', 'wrong_app', 'group'])
def test_callback_trust_boundaries(bridge, channel, failure):
    bot, _, store, app, key = bridge
    data = payload(channel)
    if failure == 'outsider':
        if channel == 'feishu': data['event']['sender']['sender_id']['open_id'] = 'outsider'
        elif channel == 'dingtalk': data['senderStaffId'] = 'outsider'
        else: data['user']['id'] = '999'
    if failure == 'wrong_app':
        if channel == 'feishu': data['header']['app_id'] = 'other'
        elif channel == 'dingtalk': data['robotCode'] = 'other'
        else: data['application_id'] = '999'
    if failure == 'group':
        if channel == 'feishu': data['event']['message']['chat_type'] = 'group'
        elif channel == 'dingtalk': data['conversationType'] = '2'
        else:
            # Discord slash commands may be used in servers; reply exclusively by DM to the caller.
            data['member'] = {'user': data.pop('user')}
            data['guild_id'] = '888'
    response = request(TestClient(app), channel, data, key, stale=failure == 'stale', bad=failure == 'bad')
    if failure in {'bad', 'stale', 'wrong_app'}:
        assert response.status_code in {401, 403}
    else:
        assert response.status_code == 200
    if channel == 'discord' and failure == 'group':
        assert store.values('bot_inbox')[0]['user'] == '123'
        assert response.json()['data']['flags'] == 64
    else:
        assert not store.values('bot_inbox')


def test_platform_verification_and_disabled_callbacks(bridge):
    bot, _, store, app, key = bridge
    client = TestClient(app)
    challenge = {'type': 'url_verification', 'token': 'fs-verify', 'challenge': 'challenge'}
    assert request(client, 'feishu', challenge, key, encrypt=True).json() == {'challenge': 'challenge'}
    challenge['token'] = 'bad'
    assert request(client, 'feishu', challenge, key).status_code == 403
    assert request(client, 'discord', {'type': 1, 'application_id': '100'}, key).json() == {'type': 1}
    assert request(client, 'discord', {'type': 1, 'application_id': '100'}, key, bad=True).status_code == 401
    for channel in bot_channels.CHANNELS:
        bot.config[channel + '_bot_enabled'] = False
        assert request(client, channel, payload(channel), key).status_code == 404
    assert not store.values('bot_inbox')


@pytest.mark.parametrize('channel', bot_channels.CHANNELS)
def test_images_flow_from_verified_platform_resources(bridge, monkeypatch, channel):
    bot, agent, store, app, key = bridge
    data = payload(channel, '')
    if channel == 'feishu':
        data['event']['message'].update(message_type='image', content=json.dumps({'image_key': 'img-key'}))
    elif channel == 'dingtalk':
        data.update(msgtype='picture', content={'downloadCode': 'img-code'})
    else:
        data['data'].update(options=[{'name': 'image', 'value': '1'}], resolved={'attachments': {
            '1': {'url': 'https://cdn.discordapp.com/attachments/1/2/image.png?ex=abc', 'size': 100, 'content_type': 'image/png'}}})
    assert request(TestClient(app), channel, data, key).status_code == 200
    image = bot.pending.get_nowait()
    response = Mock(status_code=200)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.iter_content.return_value = [b'\x89PNG\r\n\x1a\n' + b'pixels']
    bot.wecom_http.get = Mock(return_value=response)
    bot.channels.token = Mock(return_value='access-token')
    bot.channels.api = Mock(return_value={'downloadUrl': 'https://media.example.com/image.png'})
    fetch = Mock(return_value=response)
    monkeypatch.setattr(bot_channels.public_http, 'request', fetch)
    captured = []
    def complete(settings, history, tools):
        captured.extend(json.loads(json.dumps(history)))
        return {'role': 'assistant', 'content': '识别完成'}
    monkeypatch.setattr(ai_agent, 'completion', complete)
    async def run():
        await bot.command(image)
        await finish(agent)
    asyncio.run(run())
    assert 'data:image/png;base64,' in json.dumps(captured)
    assert 'data:image/png;base64,' not in json.dumps(store.values('bot_inbox'))
    if channel == 'feishu':
        assert '/messages/event1/resources/img-key' in bot.wecom_http.get.call_args.args[0]
    else:
        assert fetch.call_args.kwargs['allow_redirects'] is False
        if channel == 'dingtalk':
            assert bot.channels.api.call_args.kwargs['json']['downloadCode'] == 'img-code'


@pytest.mark.parametrize('channel', bot_channels.CHANNELS)
def test_app_replies_use_app_credentials_and_download_links(bridge, channel, tmp_path):
    bot, _, store, _, _ = bridge
    bot.channels.api = Mock(side_effect=lambda method, url, **kwargs: {'id': '555'} if url.endswith('/users/@me/channels') else {})
    bot.channels.token = Mock(return_value='access')
    user = {'feishu': 'ou_alice', 'dingtalk': 'alice', 'discord': '123'}[channel]
    message = {'channel': channel, 'user': user}
    audio = tmp_path / 'song.flac'
    audio.write_bytes(b'audio')
    bot.resolve = lambda name: audio
    job = {'id': 'a' * 32, 'status': 'complete', 'track': {'title': '歌曲'}, 'file': 'song.flac'}
    store.put('download', job['id'], job)
    bot.queue_file(message, job)
    item = store.values('bot_outbox')[-1]
    assert item['url'] and not item.get('file')
    bot.webhook = Mock(side_effect=AssertionError('application replies must not use notification webhook'))
    bot.send(item)
    method, url = bot.channels.api.call_args.args
    kwargs = bot.channels.api.call_args.kwargs
    assert method == 'POST'
    assert item['url'] in json.dumps(kwargs['json'])
    if channel == 'feishu':
        assert kwargs['json']['receive_id'] == user and 'open.feishu.cn' in url
    elif channel == 'dingtalk':
        assert kwargs['json']['userIds'] == [user] and url.endswith('/robot/oToMessages/batchSend')
    else:
        assert url.endswith('/channels/555/messages') and kwargs['json']['allowed_mentions'] == {'parse': []}
        assert len(kwargs['json']['nonce']) <= 25


@pytest.mark.parametrize('channel', ('tg', 'wecom', *bot_channels.CHANNELS))
def test_no_model_preserves_original_search_and_aliases(bridge, channel):
    bot, agent, store, _, _ = bridge
    user = {'tg': '123', 'wecom': 'alice', 'feishu': 'ou_alice', 'dingtalk': 'alice', 'discord': '123'}[channel]
    message = {'channel': channel, 'user': user, 'id': 'a' * 64, 'text': '搜索 晴天'}
    bot.agent_command = AsyncMock(side_effect=AssertionError('legacy aliases must take priority'))
    async def run():
        await bot.command(message)  # Even with a working model, aliases use the legacy commands.
        assert store.values('bot_search')
        for state in (None, {'enabled': False}, {'enabled': True, 'base_url': '', 'model': ''}):
            bot.ai_agent = None if state is None else agent
            if state is not None:
                store.put('agent_settings', 'main', state)
            await bot.command({**message, 'text': '晴天 周杰伦'})
        bot.agent_command.assert_not_called()
        assert not store.values('bot_ai_turn')
    asyncio.run(run())


@pytest.mark.parametrize('channel', bot_channels.CHANNELS)
def test_webhook_notifications_independent_of_missing_agent(setup_bot, channel):
    _, bot, store, audio, track = setup_bot
    bot.ai_agent = None
    bot.config.update({channel + '_enabled': True, channel + '_ai_enabled': True,
        channel + '_webhook': {'feishu': 'https://open.feishu.cn/open-apis/bot/v2/hook/token',
        'dingtalk': 'https://oapi.dingtalk.com/robot/send?access_token=token',
        'discord': 'https://discord.com/api/webhooks/123/token'}[channel]})
    bot.wecom_http.post = Mock(return_value=Mock(json=lambda: {'errcode': 0}))
    store.put('download', 'a' * 32, completed_job(audio, track))
    bot.queue_webhook_notifications()
    item = store.values('bot_outbox')[0]
    assert item['user'] == 'downloads' and bot.allowed(channel, 'downloads')
    bot.channels.send = Mock(side_effect=AssertionError('notifications must not use AI/application API'))
    bot.send(item)
    bot.wecom_http.post.assert_called_once()
    bot.config[channel + '_enabled'] = False
    assert not bot.allowed(channel, 'downloads')


def test_config_independent_flags_masked_credentials_and_command_registration(setup_bot, monkeypatch):
    app, bot, store, _, _ = setup_bot
    monkeypatch.setattr(BotService, 'start', AsyncMock())
    monkeypatch.setattr(BotService, 'stop', AsyncMock())
    client = TestClient(app)
    assert all(not bot.config[c + '_ai_enabled'] and not bot.config[c + '_bot_enabled'] for c in bot_channels.CHANNELS)
    assert client.put('/api/bots/config', json={'feishu_bot_enabled': True}).status_code == 400
    cfg = {'tg_enabled': False, 'feishu_bot_enabled': True, 'feishu_allowed_users': 'ou_alice',
           'feishu_app_id': 'app', 'feishu_app_secret': 'secret-a', 'feishu_encrypt_key': 'secret-b',
           'feishu_verification_token': 'secret-c'}
    response = client.put('/api/bots/config', json=cfg)
    assert response.status_code == 200
    assert not response.json()['feishu_enabled'] and not response.json()['feishu_ai_enabled']
    assert app.state.bots.enabled and app.state.bots.ai_agent is None
    assert all(secret not in response.text for secret in ('secret-a', 'secret-b', 'secret-c'))
    assert response.json()['configured']['feishu_app_secret']
    assert client.put('/api/bots/config', json={'feishu_app_secret': ''}).status_code == 200
    assert store.get('bot_setting', 'config')['feishu_app_secret'] == 'secret-a'
    assert client.post('/api/bots/discord/commands').status_code == 400


def test_image_limits_and_discord_url_boundary(bridge, monkeypatch):
    bot, _, _, app, key = bridge
    with pytest.raises(HTTPException):
        bot.channels.image({'channel': 'discord', 'image': {'id': 'http://127.0.0.1/private'}})
    with pytest.raises(HTTPException):
        bot.channels.image({'channel': 'discord', 'image': {'id': 'https://cdn.discordapp.com/attachments/1/2/x', 'size': 6 * 1024 * 1024}})
    assert TestClient(app).post('/bot/feishu', content=b'x' * 65537).status_code == 413
    for channel in bot_channels.CHANNELS:
        assert request(TestClient(app), channel, [], key).status_code in {401, 403}


@pytest.mark.parametrize('channel', bot_channels.CHANNELS)
def test_original_commands_complete_without_ai(bridge, channel):
    bot, _, store, _, _ = bridge
    bot.ai_agent = None
    user = {'feishu': 'ou_alice', 'dingtalk': 'alice', 'discord': '123'}[channel]
    message = {'channel': channel, 'user': user, 'id': 'a' * 64, 'text': '搜索 晴天'}
    async def run():
        await bot.command(message)
        assert any('下载示例：下载 1' in item['text'] for item in store.values('bot_outbox'))
        await bot.command({**message, 'id': 'b' * 64, 'text': '下载 1'})
        ident = 'b' * 32
        assert store.get('bot_task', ident)['owner'] == f'{channel}:{user}'
        await bot.command({**message, 'id': 'c' * 64, 'text': '/status'})
        assert any(ident in item['text'] for item in store.values('bot_outbox'))
        await bot.command({**message, 'id': 'd' * 64, 'text': '取消 ' + ident})
        bot.control.assert_called_once_with(ident, 'cancel')
        assert not store.values('bot_ai_session')
    asyncio.run(run())


def test_application_only_delivery_retries_without_notification_flag(bridge):
    bot, _, store, _, _ = bridge
    bot.ai_agent = None
    assert not bot.config['feishu_enabled']
    bot.reply({'channel': 'feishu', 'user': 'ou_alice'}, '普通搜索结果')
    bot.send = Mock(side_effect=RuntimeError('temporary failure'))
    async def run_worker(until):
        worker = asyncio.create_task(bot.deliveries())
        try:
            for _ in range(100):
                if until(): return
                await asyncio.sleep(.01)
            raise AssertionError('delivery worker did not process the queue')
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
    async def run():
        await run_worker(lambda: store.values('bot_outbox')[0]['attempts'] == 1)
        item = store.values('bot_outbox')[0]
        item['next'] = 0
        store.put('bot_outbox', item['id'], item)
        bot.send = Mock()
        await run_worker(lambda: not store.values('bot_outbox'))
        bot.send.assert_called_once()
    asyncio.run(run())


def test_discord_registration_upserts_only_own_command(bridge):
    bot, _, _, app, _ = bridge
    bot.channels.api = Mock(return_value={'id': 'command'})
    response = TestClient(app).post('/api/bots/discord/commands')
    assert response.status_code == 200
    call = bot.channels.api.call_args
    assert call.args == ('POST', 'https://discord.com/api/v10/applications/100/commands')
    assert call.kwargs['json']['name'] == 'melokeep'
    assert [option['type'] for option in call.kwargs['json']['options']] == [3, 11]
