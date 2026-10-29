"""Optional application robots; outgoing download webhooks remain independent."""
import asyncio
import base64
import hashlib
import hmac
import json
import re
import time
from urllib.parse import quote, urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import HTTPException, Request

import public_http


CHANNELS = ('feishu', 'dingtalk', 'discord')
DEFAULTS = {key: value for channel in CHANNELS for key, value in (
    (channel + '_bot_enabled', False), (channel + '_ai_enabled', False), (channel + '_allowed_users', ''))}
DEFAULTS.update(feishu_app_id='', feishu_app_secret='', feishu_verification_token='', feishu_encrypt_key='',
                feishu_region='feishu', dingtalk_client_id='', dingtalk_client_secret='', dingtalk_robot_code='',
                discord_application_id='', discord_public_key='', discord_bot_token='')
SECRETS = {'feishu_app_secret', 'feishu_verification_token', 'feishu_encrypt_key',
           'dingtalk_client_secret', 'discord_bot_token'}


class ChannelBots:
    def __init__(self, bot, test_channel=None):
        self.bot, self.config = bot, bot.config
        self.tokens, self.dm_channels = {}, {}
        cfg = self.config
        if cfg['feishu_region'] not in {'feishu', 'lark'}:
            raise ValueError('飞书区域须为 feishu 或 lark')
        for channel in CHANNELS:
            if test_channel or not cfg[channel + '_bot_enabled']:
                continue
            if not cfg['public_url'] or not cfg[channel + '_allowed_users'].strip():
                raise ValueError(f'{channel} 对话机器人需要公网访问地址和用户白名单')
            if 'downloads' in {u.strip() for u in cfg[channel + '_allowed_users'].split(',')}:
                raise ValueError('downloads 是通知队列保留标识，不能作为对话用户')
            required = {'feishu': ('feishu_app_id', 'feishu_app_secret', 'feishu_verification_token', 'feishu_encrypt_key'),
                        'dingtalk': ('dingtalk_client_id', 'dingtalk_client_secret', 'dingtalk_robot_code'),
                        'discord': ('discord_application_id', 'discord_public_key', 'discord_bot_token')}[channel]
            if any(not cfg[key].strip() for key in required):
                raise ValueError(f'{channel} 对话机器人凭据不完整')
            if channel == 'discord':
                if not cfg['discord_application_id'].isdigit() or not re.fullmatch(r'[0-9a-fA-F]{64}', cfg['discord_public_key']):
                    raise ValueError('Discord 需要数字 Application ID 和 64 位十六进制 Public Key')
                if any(not user.strip().isdigit() for user in cfg['discord_allowed_users'].split(',')):
                    raise ValueError('Discord 白名单需要数字用户 ID，逗号分隔')

    def allowed(self, channel, user):
        return bool(self.config[channel + '_bot_enabled'] and user and user in {
            x.strip() for x in self.config[channel + '_allowed_users'].split(',') if x.strip()})

    @property
    def feishu_origin(self):
        return 'https://open.larksuite.com' if self.config['feishu_region'] == 'lark' else 'https://open.feishu.cn'

    def api(self, method, url, **kwargs):
        response = self.bot.wecom_http.request(method, url, timeout=(10, 20), allow_redirects=False, **kwargs)
        if response.status_code == 401:
            self.tokens.clear()
        response.raise_for_status()
        data = response.json()
        if data.get('code', 0) or data.get('errcode', 0):
            self.tokens.clear()
            raise RuntimeError('机器人接口返回错误：' + str(data.get('code') or data.get('errcode')))
        return data

    def token(self, channel):
        cached, until = self.tokens.get(channel, ('', 0))
        if cached and until > time.time():
            return cached
        cfg = self.config
        if channel == 'feishu':
            data = self.api('POST', self.feishu_origin + '/open-apis/auth/v3/tenant_access_token/internal',
                            json={'app_id': cfg['feishu_app_id'], 'app_secret': cfg['feishu_app_secret']})
            token, expires = data['tenant_access_token'], data.get('expire', 7200)
        else:
            data = self.api('POST', 'https://api.dingtalk.com/v1.0/oauth2/accessToken',
                            json={'appKey': cfg['dingtalk_client_id'], 'appSecret': cfg['dingtalk_client_secret']})
            token, expires = data['accessToken'], data.get('expireIn', 7200)
        self.tokens[channel] = token, time.time() + max(1, int(expires) - 120)
        return token

    def send(self, item):
        channel, user = item['channel'], item['user']
        text = item['text'] + ('\n' + item['url'] if item.get('url') else '')
        if channel == 'feishu':
            try:
                return self.api('POST', self.feishu_origin + '/open-apis/im/v1/messages',
                    params={'receive_id_type': 'open_id'}, headers={'Authorization': 'Bearer ' + self.token(channel)},
                    json={'receive_id': user, 'msg_type': 'text', 'content': json.dumps({'text': text}),
                          'uuid': item['id']})
            except Exception:
                self.tokens.pop(channel, None)
                raise
        if channel == 'dingtalk':
            try:
                data = self.api('POST', 'https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend',
                    headers={'x-acs-dingtalk-access-token': self.token(channel)},
                    json={'robotCode': self.config['dingtalk_robot_code'], 'userIds': [user],
                          'msgKey': 'sampleText', 'msgParam': json.dumps({'content': text})})
                if data.get('invalidStaffIdList') or data.get('flowControlledStaffIdList'):
                    raise RuntimeError('钉钉用户不可达或发送受到限流')
                return data
            except Exception:
                self.tokens.pop(channel, None)
                raise
        headers = {'Authorization': 'Bot ' + self.config['discord_bot_token']}
        if user not in self.dm_channels:
            data = self.api('POST', 'https://discord.com/api/v10/users/@me/channels', headers=headers,
                            json={'recipient_id': user})
            self.dm_channels[user] = data['id']
        return self.api('POST', 'https://discord.com/api/v10/channels/' + quote(self.dm_channels[user], safe='') + '/messages',
                        headers=headers, json={'content': text, 'allowed_mentions': {'parse': []},
                                               'nonce': item['id'][:24], 'enforce_nonce': True})

    def image(self, message):
        media, channel = message['image'], message['channel']
        if media.get('size', 0) > 5 * 1024 * 1024:
            raise HTTPException(400, '图片超过 5 MB')
        if channel == 'feishu':
            url = (self.feishu_origin + '/open-apis/im/v1/messages/' + quote(media['message_id'], safe='') +
                   '/resources/' + quote(media['id'], safe=''))
            response = self.bot.wecom_http.get(url, params={'type': 'image'},
                headers={'Authorization': 'Bearer ' + self.token(channel)},
                timeout=(10, 30), stream=True, allow_redirects=False)
        else:
            if channel == 'dingtalk':
                data = self.api('POST', 'https://api.dingtalk.com/v1.0/robot/messageFiles/download',
                    headers={'x-acs-dingtalk-access-token': self.token(channel)},
                    json={'robotCode': self.config['dingtalk_robot_code'], 'downloadCode': media['id']})
                url = data['downloadUrl']
            else:
                url = media['id']
                parsed = urlsplit(url)
                if parsed.hostname not in {'cdn.discordapp.com', 'media.discordapp.net'} or not parsed.path.startswith('/attachments/'):
                    raise HTTPException(400, 'Discord 图片地址无效')
            if urlsplit(url).scheme != 'https':
                raise HTTPException(400, '图片下载地址必须为 HTTPS')
            # Platform-issued temporary URLs still cross a trust boundary: pin public DNS and disable redirects.
            response = public_http.request(self.bot.wecom_http, 'GET', url, timeout=(10, 30), stream=True, allow_redirects=False)
        with response:
            if response.status_code != 200:
                raise HTTPException(502, '图片已失效或无法获取，请重新发送')
            data = bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data) > 5 * 1024 * 1024:
                    raise HTTPException(400, '图片超过 5 MB')
        return self.bot.image_data(data)

    def register_discord(self):
        """Explicit user action; saving notification settings never changes platform commands."""
        return self.api('POST', 'https://discord.com/api/v10/applications/' + self.config['discord_application_id'] + '/commands',
            headers={'Authorization': 'Bot ' + self.config['discord_bot_token']}, json={
                'name': 'melokeep', 'description': '搜索音乐或使用 MeloKeep AI 助手，结果通过机器人私信发送',
                'type': 1, 'options': [
                    {'name': 'text', 'description': '歌名、/search、/status 或 /ai 你的需求', 'type': 3, 'max_length': 8000},
                    {'name': 'image', 'description': '歌单图片（需启用 AI，最大 5 MB）', 'type': 11}]})


def fresh(timestamp, milliseconds=False):
    if abs(int(timestamp) / (1000 if milliseconds else 1) - time.time()) > 600:
        raise ValueError('expired callback')


async def body_bytes(request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 65536:
            raise HTTPException(413, '消息过大')
    return bytes(raw)


def install(router, current):
    @router.post('/bot/feishu')
    async def feishu(request: Request):
        bot = current()
        cfg = bot.config
        if not cfg['feishu_bot_enabled']:
            raise HTTPException(404, '飞书对话机器人未启用')
        raw = await body_bytes(request)
        try:
            data = json.loads(raw)
            if 'encrypt' in data:
                encrypted = base64.b64decode(data['encrypt'], validate=True)
                key = hashlib.sha256(cfg['feishu_encrypt_key'].encode()).digest()
                decryptor = Cipher(algorithms.AES(key), modes.CBC(encrypted[:16])).decryptor()
                unpad = padding.PKCS7(128).unpadder()
                plain = decryptor.update(encrypted[16:]) + decryptor.finalize()
                data = json.loads(unpad.update(plain) + unpad.finalize())
            header = data.get('header', {})
            if not hmac.compare_digest(data.get('token', header.get('token', '')), cfg['feishu_verification_token']):
                raise ValueError('bad token')
            # URL verification can carry only a token; normal events must verify the signed raw body.
            if data.get('type') == 'url_verification':
                return {'challenge': data['challenge']}
            timestamp = request.headers.get('X-Lark-Request-Timestamp', '')
            fresh(timestamp)
            signature = hashlib.sha256((timestamp + request.headers.get('X-Lark-Request-Nonce', '') + cfg['feishu_encrypt_key']).encode() + raw).hexdigest()
            if not hmac.compare_digest(signature, request.headers.get('X-Lark-Signature', '')) or header.get('app_id') != cfg['feishu_app_id']:
                raise ValueError('bad application/signature')
            if header.get('event_type') != 'im.message.receive_v1':
                return {'code': 0}
            event = data['event']
            sender, message = event['sender'], event['message']
            if sender.get('sender_type') != 'user' or message.get('chat_type') != 'p2p':
                return {'code': 0}
            user, ident = sender['sender_id']['open_id'], message['message_id']
            content = json.loads(message['content'])
            image = None
            if message['message_type'] == 'image':
                image = {'id': content['image_key'], 'message_id': ident}
            elif message['message_type'] != 'text':
                return {'code': 0}
            bot.accept('feishu', user, ident, content.get('text', ''), image=image)
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            raise HTTPException(403, '飞书回调验证失败') from None
        return {'code': 0}

    @router.post('/bot/dingtalk')
    async def dingtalk(request: Request):
        bot = current()
        cfg = bot.config
        if not cfg['dingtalk_bot_enabled']:
            raise HTTPException(404, '钉钉对话机器人未启用')
        raw = await body_bytes(request)
        try:
            timestamp = request.headers.get('timestamp', '')
            fresh(timestamp, milliseconds=True)
            secret = cfg['dingtalk_client_secret']
            signature = base64.b64encode(hmac.new(secret.encode(), (timestamp + '\n' + secret).encode(), hashlib.sha256).digest()).decode()
            if not hmac.compare_digest(signature, request.headers.get('sign', '')):
                raise ValueError('bad signature')
            data = json.loads(raw)
            if data.get('robotCode') != cfg['dingtalk_robot_code']:
                raise ValueError('wrong robot')
            if str(data.get('conversationType')) != '1':
                return {'errcode': 0, 'errmsg': 'ok'}
            image = None
            if data['msgtype'] == 'picture':
                image = {'id': data['content']['downloadCode']}
            elif data['msgtype'] != 'text':
                return {'errcode': 0, 'errmsg': 'ok'}
            bot.accept('dingtalk', data['senderStaffId'], data['msgId'], data.get('text', {}).get('content', ''), image=image)
        except (ValueError, KeyError, TypeError, AttributeError):
            raise HTTPException(403, '钉钉回调验证失败') from None
        return {'errcode': 0, 'errmsg': 'ok'}

    @router.post('/bot/discord')
    async def discord(request: Request):
        bot = current()
        cfg = bot.config
        if not cfg['discord_bot_enabled']:
            raise HTTPException(404, 'Discord 对话机器人未启用')
        raw = await body_bytes(request)
        try:
            timestamp = request.headers.get('X-Signature-Timestamp', '')
            fresh(timestamp)
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(cfg['discord_public_key'])).verify(
                bytes.fromhex(request.headers.get('X-Signature-Ed25519', '')), timestamp.encode() + raw)
            data = json.loads(raw)
            if data.get('application_id') != cfg['discord_application_id']:
                raise ValueError('wrong application')
            if data['type'] == 1:
                return {'type': 1}
            if data['type'] != 2 or data['data'].get('name') != 'melokeep':
                raise ValueError('unsupported interaction')
            user = (data.get('member', {}).get('user') or data.get('user', {}))['id']
            if not bot.allowed('discord', user):
                return {'type': 4, 'data': {'content': '该用户不在 MeloKeep 机器人白名单中。', 'flags': 64}}
            options = {o['name']: o['value'] for o in data['data'].get('options', [])}
            image = None
            if 'image' in options:
                attachment = data['data']['resolved']['attachments'][str(options['image'])]
                if not attachment.get('content_type', '').startswith('image/'):
                    raise ValueError('not an image')
                image = {'id': attachment['url'], 'size': attachment['size']}
            bot.accept('discord', user, data['id'], options.get('text', '') or ('' if image else '/help'), image=image)
        except (ValueError, KeyError, TypeError, InvalidSignature, AttributeError):
            raise HTTPException(401, 'Discord 回调验证失败') from None
        return {'type': 4, 'data': {'content': '已收到，结果将通过 MeloKeep 机器人私信发送。请允许机器人发送私信。',
                                   'flags': 64, 'allowed_mentions': {'parse': []}}}

    @router.post('/api/bots/discord/commands')
    async def register_discord():
        bot = current()
        if not bot.config['discord_bot_enabled']:
            raise HTTPException(400, '请先保存并启用 Discord 对话机器人')
        try:
            await asyncio.to_thread(bot.channels.register_discord)
        except Exception as error:
            bot.log('error', 'Discord 命令注册失败：' + bot.error_detail(error), category='bot')
            raise HTTPException(502, 'Discord 命令注册失败，请检查凭据、权限和运行日志') from None
        return {'detail': '已注册 /melokeep 命令；全局命令可能需要稍后才显示。'}
