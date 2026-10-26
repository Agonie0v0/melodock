"""Persistent, recoverable local music processing in the existing application."""
import base64
import copy
import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
import csv
import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath, PureWindowsPath

from fastapi import HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from typing import Literal

import local_library
from metadata_scraper import MetadataScraper, SOURCE_CATALOG, LABELS, clean, pick, rank
from navidrome import Navidrome, NavidromeSettings
import audio_tools
import library_rules

INTERNAL_DIRS = {'.partial', '.processing', '.originals', '.melokeep-history'}
ACTIVE = {'queued', 'identifying', 'tagging', 'organizing', 'indexing', 'restoring'}
TEMPLATE_FIELDS = library_rules.VARIABLES
Source = Literal['netease', 'qq', 'musicbrainz', 'migu', 'kugou', 'kuwo', 'acoustid']
REPORT_ACTIONS = {'duplicates', 'quality'}
DERIVED_ACTIONS = {'convert', 'split', 'artist_artwork'}


def revision(path):
    info = path.stat()
    return f'{info.st_size}:{info.st_mtime_ns}'


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def safe_segment(value, fallback='未知'):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', '_', str(value or '')).strip(' .')
    value = value.encode('utf-8')[:160].decode('utf-8', errors='ignore').rstrip(' .') or fallback
    if re.fullmatch(r'CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]', value.split('.')[0], re.I):
        value = '_' + value
    return value


def validate_template(value):
    if not value or len(value) > 1000 or value.startswith(('/', '\\')) or '..' in re.split(r'[/\\]', value):
        raise ValueError('整理模板应为音乐库内的相对路径')
    try:
        library_rules.render(value, dict.fromkeys(TEMPLATE_FIELDS, '1'))
    except (KeyError, ValueError):
        raise ValueError('模板格式无效或包含不支持的变量') from None
    return value


class LibrarySettings(BaseModel):
    auto_scrape: bool = False
    auto_organize: bool = False
    library_dir: str = Field(default='library', min_length=1, max_length=1000)
    folder_template: str = '{album_artist}/{album}'
    filename_template: str = '{track_number} - {title}'
    sources: list[Source] = Field(default_factory=lambda: ['netease', 'qq'], max_length=7)
    overwrite: bool = False
    lyrics_mode: Literal['both', 'embed', 'lrc', 'none'] = 'both'
    cover_mode: Literal['both', 'embed', 'file', 'none'] = 'both'
    fields: list[str] = Field(default_factory=lambda: [*local_library.TAG_FIELDS], max_length=len(local_library.TAG_FIELDS))
    backup_days: int = Field(default=7, ge=1, le=365)
    chinese: Literal['none', 'simplified', 'traditional'] = 'none'
    repair_encoding: bool = False
    watch_enabled: bool = False
    watch_dirs: list[str] = Field(default_factory=lambda: ['incoming'], max_length=20)
    watch_interval: int = Field(default=180, ge=10, le=86400)
    watch_stable_seconds: int = Field(default=30, ge=2, le=3600)
    watch_action: Literal['scrape', 'organize', 'both'] = 'both'
    watch_apply: bool = True
    watch_failure_dir: str = Field(default='', max_length=1000)

    @field_validator('library_dir')
    @classmethod
    def directory(cls, value):
        if not value.strip():
            raise ValueError('请填写整理后的音乐库目录')
        return value.strip()

    @field_validator('folder_template', 'filename_template')
    @classmethod
    def template(cls, value):
        return validate_template(value)

    @field_validator('filename_template')
    @classmethod
    def filename(cls, value):
        if '/' in library_rules.render(value, dict.fromkeys(TEMPLATE_FIELDS, '1')):
            raise ValueError('文件名模板不能包含目录分隔符')
        return value

    @field_validator('fields')
    @classmethod
    def fields_valid(cls, value):
        if any(field not in local_library.TAG_FIELDS for field in value):
            raise ValueError('不支持的标签字段')
        return list(dict.fromkeys(value))


class ProcessBody(BaseModel):
    paths: list[str] = Field(default_factory=list, max_length=1000)
    scope_dir: str | None = Field(default=None, max_length=1000)
    action: Literal['scrape', 'organize', 'both', 'edit', 'extract', 'clean', 'duplicates', 'rename',
                    'export_lyrics', 'import_lyrics', 'export_cover', 'import_cover', 'clear', 'convert', 'split', 'quality', 'artist_artwork'] = 'both'
    changes: dict[str, str] = Field(default_factory=dict)
    lyrics: str | None = Field(default=None, max_length=2_000_000)
    cover_data: str | None = Field(default=None, max_length=12_000_000)
    overwrite: bool | None = None
    sources: list[Source] | None = Field(default=None, min_length=1, max_length=7)
    filename_order: Literal['title_artist', 'artist_title'] = 'title_artist'
    find: str = Field(default='', max_length=300)
    replacement: str = Field(default='', max_length=300)
    chinese: Literal['none', 'simplified', 'traditional'] | None = None
    repair_encoding: bool | None = None
    filename_template: str | None = Field(default=None, max_length=1000)
    extract_template: str = Field(default='', max_length=300)
    duplicate_mode: Literal['file', 'audio', 'identity'] = 'file'
    output_format: Literal['flac', 'mp3', 'm4a', 'opus', 'wav'] = 'flac'
    bitrate: int | None = Field(default=None, ge=32, le=512)
    sample_rate: Literal[0, 8000, 16000, 22050, 24000, 44100, 48000, 88200, 96000, 192000] = 0
    cue: str = Field(default='', max_length=1_000_000)

    @field_validator('changes')
    @classmethod
    def changes_valid(cls, value):
        if any(k not in local_library.TAG_FIELDS or len(v) > 2000 for k, v in value.items()):
            raise ValueError('标签字段或长度无效')
        return value


class ApplyBody(BaseModel):
    choices: dict[str, str] = Field(default_factory=dict)
    skip: list[str] = Field(default_factory=list, max_length=1000)


class CredentialsBody(BaseModel):
    acoustid_key: str = Field(default='', max_length=200)


class RestoreBody(BaseModel):
    items: list[str] = Field(default_factory=list, max_length=1000)


class CandidateQuery(BaseModel):
    item: str = Field(min_length=1, max_length=100)
    query: str = Field(min_length=1, max_length=200)
    sources: list[Source] | None = Field(default=None, min_length=1, max_length=7)


class LibraryPipeline:
    def __init__(self, old, db, db_lock, get, put, values, remove):
        self.old, self.db, self.db_lock = old, db, db_lock
        self.get, self.put, self.values, self.remove = get, put, values, remove
        self.guard = threading.RLock()
        self.file_locks = {}
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='music-library')
        self.futures, self.cancelled = {}, set()
        self.index_file = None
        self.scraper = MetadataScraper(lambda: self.old.manager.config)
        self.scraper.credentials = lambda: self.get('library_setting', 'credentials', {})
        self.watch_stop = threading.Event()
        self.watch_wake = threading.Event()
        self.watch_thread = None
        self.watch_guard = threading.Lock()
        self.watch_seen = {}
        self.navidrome = Navidrome(self.nav_settings)
        with db_lock:
            db.execute('CREATE TABLE IF NOT EXISTS library_assets(id TEXT PRIMARY KEY,path TEXT NOT NULL UNIQUE,locks TEXT NOT NULL DEFAULT \'[]\',source TEXT NOT NULL DEFAULT \'{}\')')
            db.execute('CREATE TABLE IF NOT EXISTS library_paths(token TEXT PRIMARY KEY,asset_id TEXT NOT NULL)')
            db.commit()

    def settings(self):
        return LibrarySettings(**self.get('library_setting', 'config', {})).model_dump()

    def nav_settings(self):
        return {'enabled': False, 'url': '', 'username': '', 'password': '', 'api_key': '', 'auto_scan': False,
                'delete_enabled': False, 'music_root': '', 'server_music_root': '',
                **self.get('library_setting', 'navidrome', {})}

    def nav_delete_root(self, cfg=None):
        cfg = cfg or self.nav_settings()
        if not cfg.get('enabled') or not cfg.get('delete_enabled'):
            raise HTTPException(409, 'Navidrome 曲库文件删除未启用')
        root = Path(cfg.get('music_root') or '')
        server = cfg.get('server_music_root') or ''
        remote = PureWindowsPath(server) if PureWindowsPath(server).drive else PurePosixPath(server)
        if not root.is_absolute() or not remote.is_absolute() or '..' in remote.parts:
            raise HTTPException(400, '请填写共享音乐目录的两个绝对路径')
        if any(p.is_symlink() or p.is_junction() for p in (root, *root.parents)):
            raise HTTPException(403, '共享目录不能使用符号链接或目录联接')
        root = root.resolve()
        if not root.is_relative_to(self.old.FILE_ROOT.resolve()) or not root.is_dir():
            raise HTTPException(400, '共享音乐目录必须已挂载到 MeloKeep 音乐根目录内')
        self.validate_path(root, must_exist=False)
        if not os.access(root, os.W_OK):
            raise HTTPException(403, '共享音乐目录没有写入权限，请检查挂载是否为只读')
        return root, remote

    def nav_delete_preview(self, ident):
        root, remote = self.nav_delete_root()
        song = self.navidrome.request('getSong', id=ident).get('song') or {}
        if str(song.get('id') or '') != ident:
            raise HTTPException(404, 'Navidrome 歌曲不存在')
        raw = song.get('path') or ''
        source = type(remote)(raw)
        # Navidrome normally reports a synthetic tag-based path. Never guess a filename.
        if not source.is_absolute() or '..' in source.parts or not source.is_relative_to(remote):
            raise HTTPException(409, '歌曲未返回映射目录内的真实绝对路径。请在 Navidrome 的播放器设置中为 melokeep 启用 Report Real Path')
        relative = source.relative_to(remote)
        if any(part in {'', '.', '..'} or '/' in part or '\\' in part or ':' in part for part in relative.parts):
            raise HTTPException(403, '歌曲文件路径无效')
        target = root.joinpath(*relative.parts)
        if any(p.is_symlink() or p.is_junction() for p in (target, *target.parents)):
            raise HTTPException(403, '不能删除符号链接或目录联接中的文件')
        if not target.resolve().is_relative_to(root):
            raise HTTPException(403, '歌曲文件超出共享目录')
        target = self.validate_path(target)
        if target.suffix.lower() not in local_library.AUDIO_EXTENSIONS:
            raise HTTPException(400, '只能删除音乐文件')
        info = target.stat()
        if type(song.get('size')) is not int or song['size'] != info.st_size:
            raise HTTPException(409, '共享文件大小与 Navidrome 记录不一致，请扫描曲库并检查目录映射')
        fingerprint = [ident, str(root), str(remote), str(target), info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]
        token = hashlib.sha256(json.dumps(fingerprint).encode()).hexdigest()
        return target, {'revision': token, 'path': str(target), 'title': song.get('title') or target.name,
                        'size_bytes': info.st_size}

    def public_settings(self):
        nav = self.nav_settings()
        return {**self.settings(), 'file_root': str(self.old.FILE_ROOT), 'metadata_sources': SOURCE_CATALOG,
                'has_acoustid_key': bool(self.scraper.credentials().get('acoustid_key') or os.getenv('MELOKEEP_ACOUSTID_KEY')),
                'tools': {tool: audio_tools.available(tool) for tool in ('ffmpeg', 'fpcalc')},
                'navidrome': {**{k: v for k, v in nav.items() if k not in {'password', 'api_key'}},
                              'has_password': bool(nav.get('password')), 'has_api_key': bool(nav.get('api_key'))}}

    def library_root(self, settings=None):
        value = (settings or self.settings())['library_dir'].strip()
        root = Path(value) if Path(value).is_absolute() else self.old.FILE_ROOT / value
        root = root.resolve()
        if not root.is_relative_to(self.old.FILE_ROOT.resolve()) or any(part in INTERNAL_DIRS for part in root.relative_to(self.old.FILE_ROOT.resolve()).parts):
            raise HTTPException(400, '整理目录必须位于挂载的音乐根目录内，且不能使用内部任务目录')
        return root

    def roots(self):
        return sorted(set([*self.old.manager.workdirs(), self.old.FILE_ROOT.resolve(), self.library_root()]), key=lambda p: len(p.parts), reverse=True)

    def scope_root(self, directory):
        root = Path(directory)
        root = (root if root.is_absolute() else self.old.FILE_ROOT / root).resolve()
        self.validate_path(root, must_exist=False)
        if root.exists() and not root.is_dir():
            raise HTTPException(400, '请选择目录')
        return root

    def validate_path(self, path, *, internal=False, must_exist=True):
        path = Path(path)
        resolved = path.resolve()
        if path.is_symlink() or not any(resolved.is_relative_to(root.resolve()) for root in self.roots()):
            raise HTTPException(403, '文件不在允许的音乐目录内')
        if any(part in INTERNAL_DIRS or part.startswith('.melokeep-') for part in path.parts) and not internal:
            raise HTTPException(403, '不能操作下载或处理中的内部文件')
        if must_exist and not resolved.is_file():
            raise HTTPException(404, '文件不存在')
        return resolved

    def legacy_token(self, path):
        path = Path(path).resolve()
        for root in self.roots():
            if path.is_relative_to(root):
                return json.dumps([str(root), str(path.relative_to(root))], ensure_ascii=False)
        raise HTTPException(403, '文件不在音乐库内')

    def asset(self, path, source=None):
        path = Path(path).resolve()
        legacy = self.legacy_token(path)
        aliases = [json.dumps([str(root), str(path.relative_to(root))], ensure_ascii=False) for root in self.roots() if path.is_relative_to(root)]
        with self.db_lock:
            row = self.db.execute('SELECT id,path,locks,source FROM library_assets WHERE path=?', (str(path),)).fetchone()
            if row is None:
                ident = 'local-' + hashlib.sha256(legacy.encode()).hexdigest()[:24]
                for alias in aliases:
                    previous_id = 'local-' + hashlib.sha256(alias.encode()).hexdigest()[:24]
                    if self.get('track', previous_id):
                        ident = previous_id
                        break
                if self.db.execute('SELECT 1 FROM library_assets WHERE id=?', (ident,)).fetchone():
                    ident = 'local-' + uuid.uuid4().hex[:24]
                self.db.execute('INSERT INTO library_assets(id,path,source) VALUES (?,?,?)', (ident, str(path), json.dumps(source or {}, ensure_ascii=False)))
                row = (ident, str(path), '[]', json.dumps(source or {}))
            elif source:
                self.db.execute('UPDATE library_assets SET source=? WHERE id=?', (json.dumps(source, ensure_ascii=False), row[0]))
                row = (*row[:3], json.dumps(source))
            self.db.executemany('INSERT OR IGNORE INTO library_paths(token,asset_id) VALUES (?,?)', [(alias, row[0]) for alias in aliases])
            self.db.commit()
        return {'id': row[0], 'path': row[1], 'locks': json.loads(row[2]), 'source': json.loads(row[3])}

    def token(self, path):
        return 'asset:' + self.asset(path)['id'] if Path(path).suffix.lower() in local_library.AUDIO_EXTENSIONS else self.legacy_token(path)

    def resolve(self, token):
        if token.startswith('asset:'):
            with self.db_lock:
                row = self.db.execute('SELECT path FROM library_assets WHERE id=?', (token[6:],)).fetchone()
            if row is None:
                raise HTTPException(404, '音乐文件不存在')
            return self.validate_path(row[0], internal=True)
        try:
            base, relative = json.loads(token)
            if not isinstance(base, str) or not isinstance(relative, str):
                raise ValueError()
        except (ValueError, TypeError):
            base, relative = str(self.old.FILE_ROOT), token
        root = Path(base).resolve()
        if root not in self.roots() and not root.is_relative_to(self.old.FILE_ROOT.resolve()):
            raise HTTPException(403, '目录不在允许范围内')
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise HTTPException(403, '非法路径')
        self.validate_path(path, must_exist=False)
        if path.is_file():
            return path
        with self.db_lock:
            row = self.db.execute('SELECT a.path FROM library_paths p JOIN library_assets a ON a.id=p.asset_id WHERE p.token=?', (token,)).fetchone()
        if row:
            return self.validate_path(row[0], internal=True)
        raise HTTPException(404, '文件不存在')

    def lock(self, path):
        ident = self.asset(path)['id']
        with self.guard:
            return self.file_locks.setdefault(ident, threading.RLock())

    def scan(self):
        seen = set()
        for root in self.roots():
            if not root.is_dir():
                continue
            for directory, folders, names in os.walk(root, followlinks=False):
                folders[:] = [name for name in folders if name not in INTERNAL_DIRS and not name.startswith('.melokeep-') and not (Path(directory) / name).is_symlink()]
                for name in names:
                    path = Path(directory) / name
                    if name.startswith('.') or path.suffix.lower() in {'.pkl', '.part'} or path.is_symlink():
                        continue
                    try:
                        resolved = self.validate_path(path)
                        if resolved not in seen:
                            seen.add(resolved)
                            yield resolved
                    except (OSError, HTTPException):
                        continue

    def lock_fields(self, path, fields):
        asset = self.asset(path)
        locked = sorted(set(asset['locks']) | set(fields))
        with self.db_lock:
            self.db.execute('UPDATE library_assets SET locks=? WHERE id=?', (json.dumps(locked), asset['id']))
            self.db.commit()

    def relocate(self, ident, path):
        token = 'asset:' + ident
        legacy = self.legacy_token(path)
        with self.db_lock:
            self.db.execute('UPDATE library_assets SET path=? WHERE id=?', (str(path), ident))
            self.db.execute('INSERT OR REPLACE INTO library_paths(token,asset_id) VALUES (?,?)', (legacy, ident))
            self.db.commit()
        if self.index_file:
            result = self.index_file(token)
            self.sync_references(ident, result)
        return token

    def sync_references(self, ident, result):
        track = result['track']
        # Keep old path-based IDs and URLs resolvable, while refreshing saved snapshots.
        with self.db_lock:
            aliases = self.db.execute('SELECT token FROM library_paths WHERE asset_id=?', (ident,)).fetchall()
        old_ids = {ident, *('local-' + hashlib.sha256(row[0].encode()).hexdigest()[:24] for row in aliases)}
        for old_id in old_ids:
            self.put('track', old_id, {'track': {**track, 'id': old_id}, 'local_path': result['path']})
            if self.get('favorite', old_id):
                self.put('favorite', old_id, {**track, 'id': old_id})
        def update_tracks(items):
            return [{**track, 'id': item['id']} if isinstance(item, dict) and item.get('id') in old_ids else item for item in items]
        saved = self.get('playlist', 'main', [])
        if any(isinstance(t, dict) and t.get('id') in old_ids for t in saved):
            self.put('playlist', 'main', update_tracks(saved))
        for collection in self.values('collection'):
            if any(t.get('id') in old_ids for t in collection.get('tracks', [])):
                collection['tracks'] = update_tracks(collection['tracks'])
                self.put('collection', collection['id'], collection)
        legacy_tokens = {row[0] for row in aliases}
        for job in self.values('download'):
            if job.get('file') in legacy_tokens or job.get('file') == result['path']:
                job['file'] = result['path']
                self.put('download', job['id'], job)
        # Existing signed links carry an immutable link ID, so their file revision can be migrated.
        info = self.resolve(result['path']).stat()
        for link in self.values('bot_link'):
            if link.get('path') in legacy_tokens or link.get('path') == result['path']:
                link.update(path=result['path'], size=info.st_size, mtime=info.st_mtime_ns)
                self.put('bot_link', link['id'], link)

    def target(self, path, tags, settings):
        values = library_rules.variables(path, tags, settings.get('_counter', 1))
        values['title'] = values['title'] or safe_segment(path.stem)
        values['artist'] = values['artist'] or '未知歌手'
        values['album_artist'] = values['album_artist'] or values['artist']
        values['album'] = values['album'] or '未知专辑'
        values['ext'] = path.suffix.lstrip('.')
        number = re.match(r'\d+', values['track_number'])
        values['track_number'] = f'{int(number[0]):02d}' if number else ''
        # Render first: expressions can contain slash literals (artist.split('/')).
        parts = [safe_segment(segment) for segment in library_rules.render(settings['folder_template'], values, lambda v: safe_segment(v, '')).replace('\\', '/').split('/')]
        filename = library_rules.render(settings['filename_template'], values, lambda v: safe_segment(v, '')).strip(' -_.')
        filename = re.sub(r'\s{2,}', ' ', filename)
        destination = self.library_root(settings).joinpath(*parts, safe_segment(filename, values['title']) + path.suffix.lower())
        if not destination.resolve().is_relative_to(self.library_root(settings)):
            raise ValueError('整理路径超出音乐库')
        siblings = [path, *self.sidecars(path)]
        candidate, count = destination, 0
        while any(candidate.with_suffix(p.suffix).exists() and candidate.with_suffix(p.suffix).resolve() != p.resolve() for p in siblings):
            count += 1
            candidate = destination.with_stem(destination.stem + f' ({count})')
        return candidate

    @staticmethod
    def sidecars(path):
        return [p for p in path.parent.iterdir() if p.stem == path.stem and p.is_file() and not p.is_symlink() and p != path
                and p.suffix.lower() in {'.lrc', '.txt', '.jpg', '.jpeg', '.png', '.cue'}]

    def item_target(self, path, item, job):
        settings = {**job['settings'], '_counter': item.get('counter', 1)}
        if job['action'] != 'rename':
            return self.target(path, item['after'], settings)
        name = library_rules.render(settings['filename_template'], library_rules.variables(path, item['after'], item.get('counter', 1)))
        target = path.with_name(safe_segment(name.strip(' -_.'), path.stem) + path.suffix.lower())
        original, count = target, 0
        while any(target.with_suffix(p.suffix).exists() and target.with_suffix(p.suffix) != p for p in [path, *self.sidecars(path)]):
            count += 1
            target = original.with_stem(original.stem + f' ({count})')
        return target

    def reserve_target(self, source, target, reserved, settings):
        suffixes = {source.suffix, *(p.suffix for p in self.sidecars(source))}
        if settings['lyrics_mode'] in {'both', 'lrc'}: suffixes.add('.lrc')
        if settings['cover_mode'] in {'both', 'file'}: suffixes.update({'.jpg', '.png'})
        allowed = {source, *self.sidecars(source)}
        original, count = target, 0
        while any(str(target.with_suffix(suffix)) in reserved or target.with_suffix(suffix).exists() and target.with_suffix(suffix) not in allowed for suffix in suffixes):
            count += 1
            target = original.with_stem(original.stem + f' ({count})')
        reserved.update(str(target.with_suffix(suffix)) for suffix in suffixes)
        return target

    def submit(self, body, download_id=None, sources=None, watch=False):
        paths = list(dict.fromkeys(body.paths))
        if body.scope_dir is not None:
            root = self.scope_root(body.scope_dir)
            paths.extend(self.token(path) for path in sorted(self.scan(), key=lambda p: str(p).casefold()) if path.suffix.lower() in local_library.AUDIO_EXTENSIONS and path.is_relative_to(root))
            paths = list(dict.fromkeys(paths))
        if not paths or len(paths) > 1000:
            raise HTTPException(400, '每次请选择 1 到 1000 首歌曲；大目录请分批处理')
        if body.action in {'convert', 'split'}:
            if body.output_format == 'opus' and body.sample_rate not in {0, 8000, 16000, 24000, 48000}:
                raise HTTPException(400, 'Opus 请选择 8/16/24/48 kHz 或自动采样率')
            if body.output_format == 'mp3' and body.sample_rate > 48000:
                raise HTTPException(400, 'MP3 采样率不能超过 48 kHz')
            if body.output_format == 'mp3' and body.bitrate and body.bitrate > 320:
                raise HTTPException(400, 'MP3 码率不能超过 320 kbps')
        for token in paths:
            path = self.resolve(token)
            if path.suffix.lower() not in local_library.AUDIO_EXTENSIONS:
                raise HTTPException(400, '请选择音频文件')
        settings = self.settings()
        if body.overwrite is not None:
            settings['overwrite'] = body.overwrite
        if body.sources is not None:
            settings['sources'] = list(dict.fromkeys(body.sources))
        for field in ('chinese', 'repair_encoding', 'filename_template'):
            if getattr(body, field) is not None:
                settings[field] = getattr(body, field)
        if body.filename_template is not None:
            validate_template(body.filename_template)
        if body.action == 'rename':
            settings['folder_template'] = '{null}'
        if body.action in {'export_lyrics', 'import_lyrics', 'export_cover', 'import_cover', 'clear'}:
            settings['overwrite'] = True
        if body.action == 'export_lyrics': settings['lyrics_mode'] = 'lrc'
        if body.action == 'import_lyrics': settings['lyrics_mode'] = 'embed'
        if body.action == 'export_cover': settings['cover_mode'] = 'file'
        if body.action == 'import_cover': settings['cover_mode'] = 'embed'
        if body.action in {'scrape', 'both'} and not settings['sources']:
            raise HTTPException(400, '请选择至少一个刮削来源')
        ident = uuid.uuid4().hex
        job = {'id': ident, 'action': body.action, 'status': 'queued', 'created_at': int(time.time()),
               'updated_at': int(time.time()), 'paths': paths, 'options': body.model_dump(exclude={'paths'}),
               'settings': settings, 'items': [], 'total': len(paths), 'processed': 0, 'detail': '等待处理',
               'download_id': download_id, 'sources': sources or {}, 'warnings': [], 'watch': watch}
        self.put('library_job', ident, job)
        self.futures[ident] = self.pool.submit(self.prepare, ident)
        return job

    def save(self, job, **changes):
        job.update(updated_at=int(time.time()), **changes)
        self.put('library_job', job['id'], job)
        if job.get('download_id'):
            download = self.get('download', job['download_id'])
            if download:
                download.update(processing={'id': job['id'], 'status': job['status'], 'detail': job['detail']})
                self.put('download', download['id'], download)

    def edit_tags(self, path, changes):
        """Single-song saves use the same version journal as batch operations."""
        with self.lock(path):
            metadata = local_library.read_metadata(str(path), path.stat().st_mtime_ns, path.stat().st_size)
            before = {key: metadata.get(key, '') for key in local_library.TAG_FIELDS}
            changes = {key: value for key, value in changes.items() if value != before.get(key, '')}
            if not changes:
                return
            ident = uuid.uuid4().hex
            item = {'id': self.asset(path)['id'], 'path': self.token(path), 'name': path.name,
                    'original_path': str(path), 'revision': revision(path), 'before': before,
                    'after': {**before, **changes}, 'candidates': [], 'chosen': None, 'status': 'ready',
                    'warnings': [], 'locks': self.asset(path)['locks'], 'target': str(path)}
            job = {'id': ident, 'action': 'edit', 'status': 'tagging', 'created_at': int(time.time()),
                   'settings': self.settings(), 'items': [item], 'total': 1, 'processed': 1,
                   'options': {'changes': changes}, 'sources': {}, 'paths': [item['path']], 'warnings': []}
            self.save(job, detail='正在保存单曲标签')
            try:
                self.publish(job, item, path, path, None, None)
                self.lock_fields(path, changes)
                item['status'] = 'complete'
                self.save(job, status='complete', detail='已保存标签及原件恢复版本')
            except Exception as error:
                item.update(status='failed', error=self.error_message(error))
                self.save(job, status='failed', detail=item['error'])
                raise

    def prepare(self, ident):
        job = self.get('library_job', ident)
        try:
            self.save(job, status='identifying', detail='读取标签与识别歌曲')
            hashes, reserved = {}, set()
            for token in job['paths']:
                if ident in self.cancelled:
                    break
                path = self.resolve(token)
                with self.lock(path):
                    asset = self.asset(path)
                    metadata = local_library.read_metadata(str(path), path.stat().st_mtime_ns, path.stat().st_size)
                    before = {key: metadata.get(key, '') for key in local_library.TAG_FIELDS}
                    source = job['sources'].get(token) or asset['source']
                    reference = {**before, 'duration': metadata.get('duration', 0),
                                 **{key: value for key, value in source.items() if value not in (None, '')}}
                    # Embedded/edited tags take precedence over stale download metadata.
                    reference.update({key: before[key] for key in {*metadata.get('tagged_fields', []), *asset['locks']} if key in before})
                    reference['duration'] = metadata.get('duration') or source.get('duration', 0)
                    reference['_path'] = str(path)
                    item = {'id': asset['id'], 'path': self.token(path), 'name': path.name, 'original_path': str(path),
                            'revision': revision(path), 'before': before, 'after': dict(before), 'candidates': [],
                            'chosen': None, 'status': 'ready', 'warnings': [], 'locks': asset['locks'],
                            'tagged_fields': metadata.get('tagged_fields', []), 'target': str(path), 'counter': len(job['items']) + 1}
                    try:
                        action = job['action']
                        options, settings = job['options'], job['settings']
                        if settings.get('chinese', 'none') != 'none' or settings.get('repair_encoding'):
                            for key, value in before.items():
                                if key not in item['locks']:
                                    item['after'][key] = library_rules.transform(value, chinese=settings.get('chinese', 'none'), repair=settings.get('repair_encoding', False))
                            reference.update({key: value for key, value in item['after'].items() if value})
                        if action == 'duplicates':
                            mode = options.get('duplicate_mode', 'file')
                            value = audio_tools.audio_hash(path, lambda: ident in self.cancelled) if mode == 'audio' else (
                                '|'.join([re.sub(r'\W', '', before['title'].casefold()), re.sub(r'\W', '', before['artist'].casefold()), str(round(metadata['duration']))])
                                if mode == 'identity' and before['artist'] and metadata['duration'] else digest(path))
                            item['hash'] = value
                            hashes.setdefault(value, []).append({'id': asset['id'], 'name': path.name, 'path': str(path),
                                                                 'bitrate': metadata.get('bitrate'), 'sample_rate': metadata.get('sample_rate'), 'size': path.stat().st_size})
                        if action == 'quality':
                            item['quality'] = audio_tools.inspect_audio(path, metadata, lambda: ident in self.cancelled)
                            item['warnings'].extend([f'缺少{key}' for key in ('artist', 'album') if not before[key]])
                        if action in {'extract', 'clean'}:
                            if action == 'extract':
                                if options.get('extract_template'):
                                    item['after'].update(library_rules.extract(options['extract_template'], path.stem))
                                elif len(pieces := re.split(r'\s+-\s+', path.stem, maxsplit=1)) == 2:
                                    title, artist = pieces if job['options']['filename_order'] == 'title_artist' else pieces[::-1]
                                    item['after'].update(title=title.strip(), artist=artist.strip())
                                else:
                                    item['warnings'].append('文件名未匹配“标题 - 歌手”或“歌手 - 标题”格式')
                            else:
                                for key, value in before.items():
                                    item['after'][key] = library_rules.transform(value, find=options['find'], replacement=options['replacement'],
                                        chinese=settings.get('chinese', 'none'), repair=settings.get('repair_encoding', False))
                        if action in {'scrape', 'both'}:
                            candidates, warnings = [], []
                            if source.get('source_id') and clean(source.get('title')):
                                candidates.append(source)
                            missing = any(not clean(reference.get(field)) for field in job['settings']['fields'] if field in {'title', 'artist', 'album'})
                            if not candidates or source.get('source') not in LABELS or missing or job['settings']['overwrite'] or not job.get('download_id'):
                                found, warnings = self.scraper.search(reference, job['settings']['sources'])
                                candidates.extend(found)
                            item['warnings'].extend(warnings)
                            item['candidates'], selected = pick(reference, candidates)
                            if selected:
                                selected, warnings = self.scraper.enrich(selected, job['settings']['lyrics_mode'] != 'none', item['candidates'])
                                item['warnings'].extend(warnings)
                                item['candidates'] = [selected if c['id'] == selected['id'] else c for c in item['candidates']]
                                item['chosen'] = selected['id']
                                self.merge(item, selected, job['settings'])
                            else:
                                item['status'] = 'needs_review'
                                item['warnings'].append('无法可靠确定歌曲版本，请选择候选或保留现有标签')
                        if action == 'edit':
                            values = library_rules.variables(path, before, item['counter'], local_library.read_lyrics(path))
                            item['after'].update({key: library_rules.render(value, values) for key, value in options['changes'].items()})
                        if action == 'clear':
                            item['after'] = dict.fromkeys(local_library.TAG_FIELDS, '')
                            item['warnings'].append('将清空全部标签（含自定义标签）、内嵌歌词与封面；同名附属文件保留')
                        if action in {'export_lyrics', 'import_lyrics'}:
                            sidecar = path.with_suffix('.lrc')
                            if action == 'import_lyrics' and (not sidecar.is_file() or sidecar.is_symlink()):
                                raise ValueError('未找到同名 LRC 文件')
                            if action == 'import_lyrics' and sidecar.stat().st_size > 8_000_000:
                                raise ValueError('LRC 文件超过 8 MB')
                            lyrics = local_library.read_lyrics(path, prefer_sidecar=action == 'import_lyrics')
                            if not lyrics or len(lyrics) > 2_000_000:
                                raise ValueError('没有可处理的歌词')
                            item['lyrics_snapshot'] = {'sidecar': action == 'import_lyrics', 'hash': hashlib.sha256(lyrics.encode('utf-8')).hexdigest()}
                        if action in {'export_cover', 'import_cover'}:
                            if action == 'export_cover':
                                picture = local_library.audio_cover(local_library.mutagen.File(path))
                            else:
                                cover_path = next((p for p in [path.with_suffix('.jpg'), path.with_suffix('.png'), path.parent / 'cover.jpg', path.parent / 'cover.png'] if p.is_file() and not p.is_symlink()), None)
                                if not cover_path:
                                    raise ValueError('未找到同名封面或目录内 cover.jpg / cover.png')
                                if cover_path.stat().st_size > 8 * 1024 * 1024:
                                    raise ValueError('封面超过 8 MB')
                                picture = (cover_path.read_bytes(), 'image/png' if cover_path.suffix.lower() == '.png' else 'image/jpeg')
                            if not picture or len(picture[0]) > 8 * 1024 * 1024:
                                raise ValueError('没有封面或封面超过 8 MB')
                            item['cover_snapshot'] = {'path': str(cover_path) if action == 'import_cover' else None,
                                                      'hash': hashlib.sha256(picture[0]).hexdigest(), 'mime': picture[1]}
                        if action in {'organize', 'both', 'rename'}:
                            item['target'] = str(self.reserve_target(path, self.item_target(path, item, job), reserved, job['settings']))
                        if action == 'artist_artwork':
                            artist = before['album_artist'] or before['artist']
                            if not artist:
                                raise ValueError('请先填写歌手或专辑歌手；图片要求完整名称的唯一匹配')
                            root = self.library_root(settings)
                            directory = next((parent for parent in path.parents if parent.is_relative_to(root) and parent.name == safe_segment(artist)), root / safe_segment(artist))
                            key = str(directory / 'artist')
                            if key in reserved or any((directory / ('artist' + ext)).exists() for ext in ('.jpg', '.png')):
                                item.update(status='skipped', outputs=[])
                                item['warnings'].append('艺术家图片已存在或已在本批次处理，保留原图')
                            else:
                                url = self.scraper.artist_artwork(artist)
                                content, mime = self.scraper.cover(url)
                                destination = directory / ('artist.png' if mime == 'image/png' else 'artist.jpg')
                                item['outputs'] = [{'path': str(destination), 'image_url': url, 'image_hash': hashlib.sha256(content).hexdigest()}]
                                item['artwork'] = {'artist': artist, 'source': '网易云音乐', 'url': url}
                                reserved.add(key)
                        if action in {'convert', 'split'}:
                            if options['output_format'] == 'opus' and metadata.get('channels') == 1 and (options.get('bitrate') or 128) > 256:
                                raise ValueError('Opus 单声道码率不能超过 256 kbps；请降低码率后重试')
                            tracks = [{}]
                            if action == 'split':
                                cue_path = path.with_suffix('.cue')
                                if not options.get('cue') and (not cue_path.is_file() or cue_path.is_symlink()):
                                    raise ValueError('请提供 CUE 文本或同名 .cue 文件')
                                text = options.get('cue')
                                if not text:
                                    if cue_path.stat().st_size > 1_000_000:
                                        raise ValueError('CUE 文件超过 1 MB')
                                    data = cue_path.read_bytes()
                                    try: text = data.decode('utf-8-sig')
                                    except UnicodeDecodeError: text = data.decode('gb18030')
                                tracks = audio_tools.cue_tracks(path, text, metadata['duration'])
                            item['outputs'] = []
                            for track in tracks:
                                tags = {**item['after'], **{k: v for k, v in track.items() if k in local_library.TAG_FIELDS and v}}
                                name = f'{int(track["track_number"]):02d} - {safe_segment(track["title"])}' if track else path.stem
                                directory = path.parent / (path.stem + (' - tracks' if track else ' - converted'))
                                destination = directory / (safe_segment(name) + '.' + options['output_format'])
                                count = 0
                                original = destination
                                while destination.exists() or str(destination) in reserved:
                                    count += 1
                                    destination = original.with_stem(original.stem + f' ({count})')
                                reserved.add(str(destination))
                                item['outputs'].append({'path': str(destination), 'tags': tags, 'start': track.get('start'), 'end': track.get('end')})
                            item['warnings'].append('将另存音频，保留原文件；转码不能提升原始音质')
                    except Exception as error:
                        item.update(status='failed', error=self.error_message(error))
                    if job.get('watch') and job['settings'].get('watch_failure_dir') and item['status'] in {'failed', 'needs_review'}:
                        try:
                            self.route_review(job, item, path)
                        except Exception as error:
                            item['warnings'].append('未转入待审核目录，原件保留：' + self.error_message(error))
                    job['items'].append(item)
                    self.save(job, processed=len(job['items']), detail=f'已检查 {len(job["items"])}/{job["total"]} 首')
            if ident in self.cancelled:
                self.save(job, status='cancelled', detail='处理已取消，文件保持不变')
            elif job['action'] in REPORT_ACTIONS:
                if job['action'] == 'duplicates':
                    job['duplicates'] = [group for group in hashes.values() if len(group) > 1]
                failures = sum(i['status'] == 'failed' for i in job['items'])
                for item in job['items']:
                    if item['status'] == 'ready': item['status'] = 'complete'
                self.save(job, status='failed' if failures == len(job['items']) else 'partial' if failures else 'complete', detail=(f'检查完成，发现 {len(job["duplicates"])} 组重复候选；未删除文件' if job['action'] == 'duplicates' else '音频解码与参数检查完成') + (f'，{failures} 首检查失败' if failures else ''))
            elif job.get('download_id') or job.get('watch') and job['settings'].get('watch_apply'):
                # Automatic jobs process confident items; ambiguous ones remain available for review.
                self.apply(ident, ApplyBody(), automatic=True)
            else:
                failures = sum(i['status'] == 'failed' for i in job['items'])
                self.save(job, status='failed' if failures == len(job['items']) else 'needs_review' if any(i['status'] == 'needs_review' for i in job['items']) else 'partial' if failures else 'ready',
                          detail='检查完成，请预览修改后应用')
        except Exception as error:
            self.save(job, status='failed', detail=self.error_message(error))

    @staticmethod
    def merge(item, candidate, settings):
        for key in settings['fields']:
            if key not in item['locks'] and clean(candidate.get(key)) and (settings['overwrite'] or not clean(item['before'].get(key)) or key == 'title' and key not in item.get('tagged_fields', [])):
                item['after'][key] = str(candidate[key])
                if settings.get('chinese', 'none') != 'none' or settings.get('repair_encoding'):
                    item['after'][key] = library_rules.transform(item['after'][key], chinese=settings.get('chinese', 'none'), repair=settings.get('repair_encoding', False))

    @staticmethod
    def error_message(error):
        if isinstance(error, HTTPException):
            return str(error.detail)
        if isinstance(error, OSError):
            return '文件操作失败，请检查空间、写入权限和文件占用情况'
        if isinstance(error, ValueError):
            return str(error)[:300]
        return f'处理失败（{type(error).__name__}），文件已保留'

    def apply(self, ident, body, automatic=False):
        job = self.get('library_job', ident)
        if not job:
            raise HTTPException(404, '整理任务不存在')
        if job['action'] in REPORT_ACTIONS:
            raise HTTPException(400, '检查报告不需要应用修改')
        if not automatic and job['status'] not in {'ready', 'needs_review', 'partial', 'failed', 'paused'}:
            raise HTTPException(409, '任务仍在运行或已完成')
        if not automatic:
            self.cancelled.discard(ident)
        self.save(job, status='tagging', detail='正在应用标签与整理文件')
        if not automatic:
            self.futures[ident] = self.pool.submit(self.execute, ident, body)
        else:
            self.execute(ident, body, automatic=True)
        return self.get('library_job', ident)

    def execute(self, ident, body, automatic=False):
        job = self.get('library_job', ident)
        try:
            for item in job['items']:
                if ident in self.cancelled:
                    break
                if item['status'] in {'complete', 'skipped'}:
                    continue
                if item['id'] in body.skip:
                    item['status'] = 'skipped'
                    self.save(job)
                    continue
                choice = body.choices.get(item['id'], item.get('chosen'))
                if item['status'] == 'needs_review' and not choice:
                    continue
                if item['status'] == 'failed' and not choice:
                    continue
                candidate = next((c for c in item['candidates'] if c['id'] == choice), None)
                if choice and choice != 'existing' and candidate is None:
                    item.update(status='failed', error='候选已变化，请重新检查')
                    continue
                try:
                    path = self.resolve(item['path'])
                    with self.lock(path):
                        if revision(path) != item['revision']:
                            raise ValueError('文件在预览后已变化，请重新创建整理任务')
                        if candidate and choice != item.get('chosen'):
                            raise ValueError('请先更新候选预览，再应用修改')
                        if choice == 'existing':
                            item['after'] = dict(item['before'])
                        if job['action'] in DERIVED_ACTIONS:
                            self.publish_derived(job, item, path)
                            item['status'] = 'complete'
                            self.save(job)
                            continue
                        lyrics = job['options'].get('lyrics')
                        if 'media_lyrics' in item: lyrics = item['media_lyrics']
                        if snapshot := item.get('lyrics_snapshot'):
                            sidecar = path.with_suffix('.lrc')
                            if snapshot['sidecar'] and (not sidecar.is_file() or sidecar.is_symlink() or sidecar.stat().st_size > 8_000_000):
                                raise ValueError('LRC 文件在预览后已变化，请重新检查')
                            lyrics = local_library.read_lyrics(path, prefer_sidecar=snapshot['sidecar'])
                            if hashlib.sha256(lyrics.encode('utf-8')).hexdigest() != snapshot['hash']:
                                raise ValueError('歌词在预览后已变化，请重新检查')
                        if job['action'] == 'clear': lyrics = ''
                        if lyrics is None and candidate and job['settings']['lyrics_mode'] != 'none':
                            lyrics = clean(candidate.get('lyrics')) or None
                            if not job['settings']['overwrite']:
                                lyrics = local_library.read_lyrics(path) or lyrics
                        cover = self.manual_cover(item.get('media_cover') or job['options'].get('cover_data'))
                        if snapshot := item.get('cover_snapshot'):
                            if snapshot['path']:
                                cover_path = self.validate_path(snapshot['path'])
                                if cover_path.stat().st_size > 8 * 1024 * 1024:
                                    raise ValueError('封面超过 8 MB')
                                cover = (cover_path.read_bytes(), snapshot['mime'])
                            else:
                                cover = local_library.audio_cover(local_library.mutagen.File(path))
                            if not cover or hashlib.sha256(cover[0]).hexdigest() != snapshot['hash']:
                                raise ValueError('封面在预览后已变化，请重新检查')
                        if job['action'] == 'clear': cover = False
                        metadata = local_library.read_metadata(str(path), path.stat().st_mtime_ns, path.stat().st_size)
                        if cover is None and candidate and not job['settings']['overwrite'] and job['settings']['cover_mode'] != 'none':
                            cover = local_library.audio_cover(local_library.mutagen.File(path))
                        if cover is None and candidate and candidate.get('cover_url') and job['settings']['cover_mode'] != 'none':
                            if job['settings']['overwrite'] or not metadata['has_cover']:
                                try:
                                    cover = self.scraper.cover(candidate['cover_url'])
                                except Exception as error:
                                    item['warnings'].append('封面未更新：' + self.error_message(error))
                        target = self.reserve_target(path, Path(item['target']), set(), job['settings']) if job['action'] in {'organize', 'both', 'rename'} else path
                        if str(target) != item['target']:
                            item['warnings'].append('目标出现同名文件，已保留双方并改存为：' + str(target))
                        item['target'] = str(target)
                        self.publish(job, item, path, target, lyrics, cover)
                        if job['action'] in {'edit', 'extract', 'clean', 'clear'}:
                            self.lock_fields(target, [key for key in local_library.TAG_FIELDS if item['after'][key] != item['before'][key]])
                        item['status'] = 'complete'
                        item.pop('error', None)
                except Exception as error:
                    item.update(status='failed', error=self.error_message(error))
                self.save(job, detail=f'已处理 {sum(i["status"] == "complete" for i in job["items"])}/{job["total"]} 首')
            completed = sum(i['status'] == 'complete' for i in job['items'])
            unresolved = any(i['status'] == 'needs_review' for i in job['items'])
            failed = any(i['status'] == 'failed' for i in job['items'])
            status = 'cancelled' if ident in self.cancelled else 'needs_review' if unresolved else 'partial' if failed and completed else 'failed' if failed else 'complete'
            if completed and self.nav_settings().get('enabled') and self.nav_settings().get('auto_scan'):
                try:
                    job['navidrome_scan'] = self.navidrome.request('startScan').get('scanStatus') or {}
                except Exception as error:
                    job['warnings'].append('本地已入库，Navidrome 扫描未启动：' + self.error_message(error))
            self.save(job, status=status, detail=f'已入库 {completed} 首' + ('，有歌曲待确认' if unresolved else '，部分文件处理失败' if failed else ''))
        except Exception as error:
            self.save(job, status='failed', detail=self.error_message(error))

    @staticmethod
    def manual_cover(value):
        if not value:
            return None
        try:
            header, encoded = value.split(',', 1)
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise ValueError('封面文件无效') from None
        if len(data) > 8 * 1024 * 1024:
            raise ValueError('封面不能超过 8 MB')
        mime = 'image/png' if data.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if data.startswith(b'\xff\xd8\xff') else ''
        if not mime:
            raise ValueError('请选择 PNG 或 JPEG 封面')
        return data, mime

    def publish(self, job, item, source, target, lyrics, cover):
        self.validate_path(target, must_exist=False)
        history = self.old.FILE_ROOT / '.melokeep-history' / job['id'] / item['id']
        if not history.resolve().is_relative_to(self.old.FILE_ROOT.resolve()):
            raise ValueError('原件备份目录超出音乐根目录')
        history.mkdir(parents=True, exist_ok=True)
        backup = history / source.name
        shutil.copy2(source, backup)
        companions = self.sidecars(source)
        for file in companions:
            shutil.copy2(file, history / file.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / ('.melokeep-publish-' + uuid.uuid4().hex + source.suffix)
        operation = {'id': job['id'] + ':' + item['id'], 'job_id': job['id'], 'asset_id': item['id'],
                     'source': str(source), 'target': str(target), 'backup': str(backup), 'stage': str(stage),
                     'companions': [], 'outputs': [], 'state': 'preparing', 'created_at': int(time.time()),
                     'original_locks': self.asset(source)['locks'],
                     'expires_at': int(time.time()) + job['settings']['backup_days'] * 86400}
        self.put('library_operation', operation['id'], operation)
        try:
            shutil.copy2(source, stage)
            changes = {key: value for key, value in item['after'].items() if value != item['before'].get(key)}
            embed_lyrics = lyrics if job['settings']['lyrics_mode'] in {'both', 'embed'} or job['action'] in {'edit', 'clear'} else None
            embed_cover = cover if job['settings']['cover_mode'] in {'both', 'embed'} or job['action'] in {'edit', 'clear'} else None
            if not job['settings']['overwrite'] and job['action'] not in {'edit', 'clear'}:
                if embed_lyrics is not None and local_library.read_lyrics(source, prefer_sidecar=False):
                    embed_lyrics = None
                if embed_cover and local_library.audio_cover(local_library.mutagen.File(source)):
                    embed_cover = None
            if changes or embed_lyrics is not None or embed_cover is not None:
                local_library.write_metadata(stage, changes, lyrics=embed_lyrics, cover=embed_cover, clear_all=job['action'] == 'clear')
            sidecar_data = {}
            for file in companions:
                destination = target.with_suffix(file.suffix)
                sidecar_data[str(destination)] = file.read_bytes()
                operation['companions'].append({'source': str(file), 'target': str(destination), 'backup': str(history / file.name)})
            preserve = not job['settings']['overwrite'] and job['action'] != 'edit'
            if lyrics is not None and job['settings']['lyrics_mode'] in {'both', 'lrc'} and not (preserve and source.with_suffix('.lrc') in companions):
                sidecar_data[str(target.with_suffix('.lrc'))] = lyrics.encode('utf-8')
            if cover and job['settings']['cover_mode'] in {'both', 'file'}:
                extension = '.png' if cover[1] == 'image/png' else '.jpg'
                if not (preserve and source.with_suffix(extension) in companions):
                    sidecar_data[str(target.with_suffix(extension))] = cover[0]
            for filename, content in sidecar_data.items():
                dest = Path(filename)
                if dest.exists() and not any(str(p) == filename for p in companions):
                    raise ValueError('附属文件重名，请重新预览整理路径')
                operation['outputs'].append({'path': filename, 'hash': hashlib.sha256(content).hexdigest(),
                                             'stage': str(dest.with_name('.melokeep-sidecar-' + uuid.uuid4().hex)),
                                             'preexisting': dest.exists()})
            operation.update(state='publishing', output_hash=digest(stage))
            self.put('library_operation', operation['id'], operation)
            if source != target and target.exists():
                raise ValueError('目标文件已存在，请重新预览整理路径')
            if source == target:
                os.replace(stage, target)
            else:
                # Exclusive creation prevents a concurrent file from being overwritten.
                os.link(stage, target)
            operation['published'] = True
            self.put('library_operation', operation['id'], operation)
            for output in operation['outputs']:
                dest, temporary = Path(output['path']), Path(output['stage'])
                try:
                    temporary.write_bytes(sidecar_data[output['path']])
                    if output['preexisting']:
                        os.replace(temporary, dest)
                    else:
                        os.link(temporary, dest)
                    output['published'] = True
                    self.put('library_operation', operation['id'], operation)
                finally:
                    if output.get('published'):
                        temporary.unlink(missing_ok=True)
            # Commit the new identity mapping before removing the old copy.
            self.relocate(item['id'], target)
            if source != target:
                source.unlink()
                for file in companions:
                    if file.exists() and file != target.with_suffix(file.suffix):
                        file.unlink()
            operation.update(state='complete', output_revision=revision(target))
            self.put('library_operation', operation['id'], operation)
            item.update(operation_id=operation['id'], revision=revision(target), path=self.token(target))
            local_library.read_metadata.cache_clear()
        except Exception:
            self.rollback(operation)
            raise
        finally:
            stage.unlink(missing_ok=True)
            for output in operation.get('outputs', []):
                Path(output['stage']).unlink(missing_ok=True)

    def publish_derived(self, job, item, source):
        operation = {'id': job['id'] + ':' + item['id'], 'job_id': job['id'], 'asset_id': item['id'],
                     'kind': 'derived', 'state': 'preparing', 'source': str(source), 'outputs': [],
                     'created_at': int(time.time()), 'expires_at': int(time.time()) + job['settings']['backup_days'] * 86400}
        self.put('library_operation', operation['id'], operation)
        try:
            lyrics = local_library.read_lyrics(source)
            picture = local_library.audio_cover(local_library.mutagen.File(source))
            for output in item['outputs']:
                target = self.validate_path(output['path'], must_exist=False)
                target.parent.mkdir(parents=True, exist_ok=True)
                stage = target.with_name('.melokeep-audio-' + uuid.uuid4().hex + target.suffix)
                record = {'path': str(target), 'stage': str(stage), 'published': False}
                operation['outputs'].append(record)
                self.put('library_operation', operation['id'], operation)
                try:
                    if job['action'] == 'artist_artwork':
                        content, _ = self.scraper.cover(output['image_url'])
                        if hashlib.sha256(content).hexdigest() != output['image_hash']:
                            raise ValueError('艺术家图片已变化，请重新生成预览')
                        stage.write_bytes(content)
                    else:
                        audio_tools.convert(source, stage, job['options'], start=output.get('start'), end=output.get('end'),
                                            cancelled=lambda: job['id'] in self.cancelled)
                        # CUE lyrics refer to the original timeline and cannot be copied unchanged.
                        local_library.write_metadata(stage, output['tags'], lyrics=lyrics if job['action'] == 'convert' else None, cover=picture)
                    record['hash'] = digest(stage)
                    operation['state'] = 'publishing'
                    self.put('library_operation', operation['id'], operation)
                    os.link(stage, target)
                    record['published'] = True
                    if job['action'] != 'artist_artwork': record['asset_id'] = self.asset(target)['id']
                    self.put('library_operation', operation['id'], operation)
                    if self.index_file and job['action'] != 'artist_artwork': self.index_file(self.token(target))
                finally:
                    stage.unlink(missing_ok=True)
            operation['state'] = 'complete'
            self.put('library_operation', operation['id'], operation)
            item['operation_id'] = operation['id']
        except Exception:
            self.rollback(operation)
            raise

    def route_review(self, job, item, source):
        root = self.scope_root(job['settings']['watch_failure_dir'])
        target, count = root / source.name, 0
        while any(target.with_suffix(p.suffix).exists() for p in [source, *self.sidecars(source)]):
            count += 1
            target = root / (source.stem + f' ({count})' + source.suffix)
        routed = {**copy.deepcopy(item), 'after': dict(item['before']), 'target': str(target), 'candidates': [],
                  'chosen': None, 'warnings': [], 'status': 'ready'}
        route_id = uuid.uuid4().hex
        route_job = {'id': route_id, 'action': 'organize', 'status': 'organizing', 'created_at': int(time.time()),
                     'settings': job['settings'], 'items': [routed], 'total': 1, 'processed': 1,
                     'options': {}, 'sources': {}, 'paths': [item['path']], 'warnings': []}
        self.save(route_job, detail='正在将监控疑难文件移入待审核目录')
        try:
            self.publish(route_job, routed, source, target, None, None)
            routed['status'] = 'complete'
            self.save(route_job, status='complete', detail='监控疑难文件已转入待审核目录；可恢复原目录')
            item.update(path=routed['path'], revision=routed['revision'], routed_by=route_id)
            item['warnings'].append('已转入待审核目录：' + str(target))
        except Exception as error:
            routed.update(status='failed', error=self.error_message(error))
            self.save(route_job, status='failed', detail=routed['error'])
            raise

    def rollback(self, operation):
        if operation.get('kind') == 'derived':
            for output in operation['outputs']:
                path = self.validate_path(output['path'], must_exist=False)
                stage = Path(output['stage'])
                owned = output.get('published') or stage.exists() and path.exists() and os.path.samefile(stage, path)
                if owned and path.exists() and digest(path) != output.get('hash'):
                    raise ValueError('生成的音频已被修改，已保留文件；请先恢复后续修改')
            for output in operation['outputs']:
                path, stage = Path(output['path']), Path(output['stage'])
                owned = output.get('published') or stage.exists() and path.exists() and os.path.samefile(stage, path)
                if owned:
                    path.unlink(missing_ok=True)
                    if output.get('asset_id'): self.remove('track', output['asset_id'])
                stage.unlink(missing_ok=True)
            operation['state'] = 'restored'
            self.put('library_operation', operation['id'], operation)
            return
        source, target, backup = (Path(operation[key]) for key in ('source', 'target', 'backup'))
        self.validate_path(source, internal=True, must_exist=False)
        self.validate_path(target, internal=True, must_exist=False)
        if not backup.resolve().is_relative_to((self.old.FILE_ROOT / '.melokeep-history').resolve()) or not backup.is_file():
            raise ValueError('原件备份不存在，已保留当前文件')
        # A failed or interrupted publish is reverted only when its output still matches.
        stage = Path(operation['stage'])
        linked = stage.exists() and target.exists() and os.path.samefile(stage, target)
        published = operation.get('published') or linked or source == target and operation.get('output_hash') and target.exists() and digest(target) == operation['output_hash']
        if published and target.exists() and operation.get('output_hash') and digest(target) != operation['output_hash']:
            raise ValueError('目标文件已被其他操作修改，已保留文件，请手动检查')
        if source != target and source.exists() and digest(source) != digest(backup):
            raise ValueError('原路径已有其他文件，无法自动恢复')
        if source == target and not published and source.exists() and digest(source) != digest(backup):
            raise ValueError('原文件已变化，无法自动恢复')
        outputs = []
        for output in operation.get('outputs', []):
            path = Path(output['path'])
            self.validate_path(path, internal=True, must_exist=False)
            temporary = Path(output.get('stage', ''))
            owned = output.get('published') or (output.get('stage') and temporary.is_file() and path.exists() and os.path.samefile(temporary, path))
            # Replacement of an original sidecar is reversible from its backup.
            owned = owned or (published and output.get('preexisting') and path.exists() and digest(path) == output['hash'])
            if owned and path.exists() and digest(path) != output['hash']:
                raise ValueError('歌词或封面在整理后已修改，已保留文件，请手动检查')
            if owned:
                outputs.append(path)
        for companion in operation.get('companions', []):
            original, saved = Path(companion['source']), Path(companion['backup'])
            if source != target and original.exists() and saved.is_file() and digest(original) != digest(saved):
                raise ValueError('原目录的歌词或封面已有其他内容，无法自动恢复')
        source.parent.mkdir(parents=True, exist_ok=True)
        temporary = source.with_name('.melokeep-restore-' + uuid.uuid4().hex + source.suffix)
        try:
            shutil.copy2(backup, temporary)
            os.replace(temporary, source)
        finally:
            temporary.unlink(missing_ok=True)
        for path in outputs:
            path.unlink(missing_ok=True)
        for companion in operation.get('companions', []):
            dest, saved = Path(companion['source']), Path(companion['backup'])
            self.validate_path(dest, internal=True, must_exist=False)
            if saved.is_file() and saved.resolve().is_relative_to(backup.parent.resolve()):
                shutil.copy2(saved, dest)
        if source != target and target.exists() and published:
            target.unlink()
        self.relocate(operation['asset_id'], source)
        with self.db_lock:
            self.db.execute('UPDATE library_assets SET locks=? WHERE id=?', (json.dumps(operation.get('original_locks', [])), operation['asset_id']))
            self.db.commit()
        operation['state'] = 'restored'
        self.put('library_operation', operation['id'], operation)
        Path(operation['stage']).unlink(missing_ok=True)
        for output in operation.get('outputs', []):
            if output.get('stage'):
                Path(output['stage']).unlink(missing_ok=True)
        local_library.read_metadata.cache_clear()

    def restore(self, ident, only=None):
        job = self.get('library_job', ident)
        if not job or job['status'] in ACTIVE:
            raise HTTPException(409, '任务不存在或仍在处理')
        if only and set(only) - {item['id'] for item in job['items']}:
            raise HTTPException(400, '所选文件不属于此任务')
        self.save(job, status='restoring', detail='正在恢复原文件')
        def run():
            try:
                for item in reversed(job['items']):
                    if only and item['id'] not in only:
                        continue
                    operation = self.get('library_operation', item.get('operation_id', ''))
                    if not operation or operation['state'] != 'complete':
                        continue
                    target = Path(operation.get('target') or operation['source'])
                    with self.lock(target):
                        if operation.get('kind') != 'derived' and (not target.exists() or revision(target) != operation['output_revision']):
                            raise ValueError('文件在整理后已被修改，无法自动恢复；请先处理后续修改')
                        self.rollback(operation)
                        item['status'] = 'restored'
                self.save(job, status='partial' if any(i['status'] == 'complete' for i in job['items']) else 'restored', detail='已恢复所选原文件、标签和目录；转码输出已撤回')
            except Exception as error:
                self.save(job, status='partial', detail=self.error_message(error))
        self.futures[ident] = self.pool.submit(run)
        return job

    def recover(self):
        for operation in self.values('library_operation'):
            if operation['state'] in {'preparing', 'publishing'}:
                try:
                    self.rollback(operation)
                except Exception as error:
                    self.old.pushlog('error', '整理中断恢复需人工处理：' + self.error_message(error), category='download')
            elif operation['state'] in {'complete', 'restored'} and operation.get('expires_at', 0) < time.time():
                if operation.get('kind') == 'derived': continue
                backup_dir = Path(operation['backup']).parent
                history = (self.old.FILE_ROOT / '.melokeep-history').resolve()
                if history.is_relative_to(self.old.FILE_ROOT.resolve()) and backup_dir.resolve().is_relative_to(history) and not backup_dir.is_symlink():
                    shutil.rmtree(backup_dir, ignore_errors=True)
        for job in self.values('library_job'):
            if job['status'] in ACTIVE:
                self.save(job, status='paused', detail='服务重启，文件已保留；请重新检查或重试')
        linked = {job.get('download_id') for job in self.values('library_job')}
        for download in self.values('download'):
            processing = download.get('processing') or {}
            if download['id'] in linked or processing.get('status') not in ACTIVE:
                continue
            # Recover the small gap between completed download and persisted library task.
            try:
                self.submit(ProcessBody(paths=download.get('processing_paths') or [download['file']],
                                        action=download.get('processing_action', 'both')), download['id'])
            except Exception as error:
                download['processing'] = {'id': '', 'status': 'failed', 'detail': self.error_message(error)}
                self.put('download', download['id'], download)
        self.start_watcher()

    def watch_roots(self, settings):
        roots = [self.scope_root(directory) for directory in settings['watch_dirs'] if directory.strip()]
        library = self.library_root(settings)
        if settings['watch_enabled'] and any(root.is_relative_to(library) or library.is_relative_to(root) for root in roots):
            raise HTTPException(400, '监控目录与整理后的音乐库必须分开，避免重复刮削')
        if settings['watch_enabled'] and not roots:
            raise HTTPException(400, '开启监控需要至少一个目录')
        if settings.get('watch_failure_dir'):
            review = self.scope_root(settings['watch_failure_dir'])
            if any(review.is_relative_to(root) or root.is_relative_to(review) for root in roots) or review.is_relative_to(library) or library.is_relative_to(review):
                raise HTTPException(400, '待审核目录须与监控目录及最终音乐库分开')
        return roots

    def watch_scan(self):
        if not self.watch_guard.acquire(blocking=False):
            return {'queued': 0, 'detail': '已有目录检查正在运行'}
        try:
            settings = self.settings()
            if not settings['watch_enabled']:
                return {'queued': 0, 'detail': '目录监控未开启'}
            roots = self.watch_roots(settings)
            now, pending, tokens = time.time(), [], set()
            for path in self.scan():
                if self.watch_stop.is_set():
                    break
                if path.suffix.lower() not in local_library.AUDIO_EXTENSIONS or not any(path.is_relative_to(root) for root in roots):
                    continue
                if any(part.endswith((' - converted', ' - tracks')) for part in path.parts):
                    continue
                token = self.token(path)
                tokens.add(token)
                signature = revision(path)
                previous = self.get('library_watch', token, {})
                if previous.get('revision') == signature:
                    continue
                old_job = self.get('library_job', previous.get('job_id', ''), {})
                if old_job.get('status') in ACTIVE:
                    continue
                if any(item.get('path') == token and item.get('revision') == signature for item in old_job.get('items', [])):
                    self.put('library_watch', token, {**previous, 'revision': signature})
                    continue
                seen = self.watch_seen.get(token)
                if seen is None or seen[0] != signature:
                    self.watch_seen[token] = (signature, now)
                    continue
                if now - seen[1] < settings['watch_stable_seconds']:
                    continue
                pending.append((token, signature))
                if len(pending) >= 1000:
                    break
            self.watch_seen = {key: value for key, value in self.watch_seen.items() if key in tokens}
            if pending and not self.watch_stop.is_set():
                job = self.submit(ProcessBody(paths=[token for token, _ in pending], action=settings['watch_action']), watch=True)
                for token, signature in pending:
                    self.put('library_watch', token, {'revision': signature, 'job_id': job['id']})
            state = {'queued': len(pending), 'checked_at': int(now), 'detail': f'已提交 {len(pending)} 首稳定文件；未匹配的歌曲在任务中等待审核'}
            self.put('library_setting', 'watch_status', state)
            return state
        finally:
            self.watch_guard.release()

    def start_watcher(self):
        if self.watch_thread and self.watch_thread.is_alive():
            return
        def run():
            while not self.watch_stop.is_set():
                try:
                    self.watch_scan()
                except Exception as error:
                    self.put('library_setting', 'watch_status', {'checked_at': int(time.time()), 'error': self.error_message(error)})
                self.watch_wake.wait(self.settings()['watch_interval'])
                self.watch_wake.clear()
        self.watch_thread = threading.Thread(target=run, name='library-watch', daemon=True)
        self.watch_thread.start()

    def close(self):
        self.watch_stop.set()
        self.watch_wake.set()
        if self.watch_thread:
            self.watch_thread.join(timeout=5)
        with self.guard:
            self.cancelled.update(self.futures)
        self.pool.shutdown(wait=True, cancel_futures=True)

    def install(self, router):
        @router.get('/api/library/settings')
        def settings():
            return self.public_settings()

        @router.put('/api/library/settings')
        def save_settings(body: LibrarySettings):
            self.library_root(body.model_dump())
            self.watch_roots(body.model_dump())
            self.put('library_setting', 'config', body.model_dump())
            self.watch_wake.set()
            return self.public_settings()

        @router.put('/api/library/credentials')
        def save_credentials(body: CredentialsBody):
            self.put('library_setting', 'credentials', body.model_dump())
            return {'has_acoustid_key': self.public_settings()['has_acoustid_key']}

        @router.get('/api/library/watch')
        def watch_status():
            return self.get('library_setting', 'watch_status', {'detail': '尚未检查目录'})

        @router.post('/api/library/watch/scan')
        def watch_scan():
            return self.watch_scan()

        @router.put('/api/library/navidrome')
        def save_navidrome(body: NavidromeSettings):
            value = body.model_dump()
            previous = self.nav_settings()
            for key in ('password', 'api_key'):
                if value[key] is None:
                    value[key] = previous.get(key, '')
            if value['enabled'] and (not value['url'] or not (value.get('api_key') or value.get('username') and value.get('password'))):
                raise HTTPException(400, '启用 Navidrome 需要服务地址和有效的认证配置')
            if value['enabled'] and value['delete_enabled']:
                try:
                    self.nav_delete_root(value)
                except OSError:
                    raise HTTPException(400, '无法读取共享目录，请检查挂载与权限')
            self.put('library_setting', 'navidrome', value)
            return self.public_settings()['navidrome']

        @router.get('/api/library/jobs')
        def jobs(offset: int = 0, size: int = 30, status: str = 'all'):
            if offset < 0 or not 1 <= size <= 100:
                raise HTTPException(400, '分页参数无效')
            all_jobs = sorted(self.values('library_job'), key=lambda job: job['created_at'], reverse=True)
            if status != 'all':
                selected = ACTIVE if status == 'active' else {'failed', 'partial', 'paused'} if status == 'failed' else {status}
                all_jobs = [job for job in all_jobs if job['status'] in selected]
            return {'jobs': [{k: v for k, v in job.items() if k not in {'items', 'sources', 'options', 'settings', 'paths'}}
                             for job in all_jobs[offset:offset + size]], 'has_more': len(all_jobs) > offset + size, 'total': len(all_jobs)}

        @router.get('/api/library/versions')
        def versions(path: str):
            asset = self.asset(self.resolve(path))
            return {'versions': [{'job_id': job['id'], 'created_at': job['created_at'], 'action': job['action'],
                                  'status': item['status'], 'before': item['before'], 'after': item['after'],
                                  'restorable': bool(item.get('operation_id') and (operation := self.get('library_operation', item['operation_id'], {})).get('state') == 'complete'
                                                     and (operation.get('kind') == 'derived' or Path(operation.get('backup', '')).is_file()))}
                                 for job in sorted(self.values('library_job'), key=lambda j: j['created_at'], reverse=True)
                                 for item in job.get('items', []) if item['id'] == asset['id'] and item.get('operation_id')]}

        @router.get('/api/library/jobs/{ident}/report')
        def report(ident: str):
            value = self.get('library_job', ident)
            if not value:
                raise HTTPException(404, '整理任务不存在')
            output = io.StringIO(newline='')
            writer = csv.writer(output)
            writer.writerow(['文件', '状态', '原路径', '目标路径', '修改前', '修改后', '警告或错误', '输出文件', '检查参数'])
            def cell(value):
                value = str(value)
                return "'" + value if value.startswith(('=', '+', '-', '@', '\t', '\r')) else value
            for item in value['items']:
                writer.writerow([cell(v) for v in [item['name'], item['status'], item['original_path'], item['target'],
                    json.dumps(item['before'], ensure_ascii=False), json.dumps(item['after'], ensure_ascii=False),
                    '；'.join([*item['warnings'], item.get('error', '')]),
                    '\n'.join(row['path'] for row in item.get('outputs', [])), json.dumps(item.get('quality', {}), ensure_ascii=False)]])
            return Response(output.getvalue().encode('utf-8-sig'), media_type='text/csv',
                            headers={'Content-Disposition': f'attachment; filename="library-report-{ident}.csv"'})

        @router.get('/api/library/jobs/{ident}')
        def job(ident: str):
            value = self.get('library_job', ident)
            if not value:
                raise HTTPException(404, '整理任务不存在')
            return {k: v for k, v in value.items() if k not in {'sources', 'options'}}

        @router.post('/api/library/jobs')
        def process(body: ProcessBody):
            return self.submit(body)

        @router.post('/api/library/jobs/{ident}/apply')
        def apply(ident: str, body: ApplyBody):
            with self.guard:
                return self.apply(ident, body)

        @router.post('/api/library/jobs/{ident}/search')
        def search_candidates(ident: str, body: CandidateQuery):
            with self.guard:
                job = self.get('library_job', ident)
                if not job or job['status'] in ACTIVE or job['action'] not in {'scrape', 'both'}:
                    raise HTTPException(409, '任务不存在或暂不能搜索候选')
                item = next((row for row in job['items'] if row['id'] == body.item and row['status'] in {'ready', 'needs_review', 'failed'}), None)
                if not item:
                    raise HTTPException(409, '文件已处理或不存在，请新建任务')
                path = self.resolve(item['path'])
                reference = {**item['before'], '_path': str(path), '_query': body.query}
                candidates, warnings = self.scraper.search(reference, body.sources or job['settings']['sources'])
                item.update(candidates=pick(reference, candidates)[0], chosen=None, after=dict(item['before']),
                            status='needs_review', warnings=warnings)
                self.save(job, status='needs_review', detail='搜索结果已更新，请选择并预览候选')
                return {k: v for k, v in job.items() if k not in {'sources', 'options'}}

        @router.post('/api/library/jobs/{ident}/preview')
        def preview(ident: str, body: ApplyBody):
            with self.guard:
                job = self.get('library_job', ident)
                if not job or job['status'] in ACTIVE or job['status'] in {'complete', 'restored'}:
                    raise HTTPException(409, '任务不存在或暂不能修改预览')
                for item in job['items']:
                    if item['id'] not in body.choices or item['status'] in {'complete', 'skipped'}:
                        continue
                    choice = body.choices[item['id']]
                    candidate = next((c for c in item['candidates'] if c['id'] == choice), None)
                    if candidate is None and choice != 'existing':
                        raise HTTPException(400, '候选不存在')
                    item['chosen'], item['after'] = choice, dict(item['before'])
                    if candidate:
                        candidate, warnings = self.scraper.enrich(candidate, job['settings']['lyrics_mode'] != 'none', item['candidates'])
                        item['warnings'].extend(warnings)
                        item['candidates'] = [candidate if c['id'] == candidate['id'] else c for c in item['candidates']]
                        self.merge(item, candidate, job['settings'])
                    if job['action'] in {'organize', 'both', 'rename'}:
                        reserved = {row['target'] for row in job['items'] if row['id'] != item['id']}
                        path = self.resolve(item['path'])
                        item['target'] = str(self.reserve_target(path, self.item_target(path, item, job), reserved, job['settings']))
                    item['status'] = 'ready'
                self.save(job, status='needs_review' if any(i['status'] == 'needs_review' for i in job['items']) else 'ready', detail='预览已更新，请确认后应用')
                return {k: v for k, v in job.items() if k not in {'sources', 'options'}}

        @router.post('/api/library/jobs/{ident}/cancel')
        def cancel(ident: str):
            value = self.get('library_job', ident)
            if not value:
                raise HTTPException(404, '整理任务不存在')
            self.cancelled.add(ident)
            if value['status'] not in ACTIVE:
                self.save(value, status='cancelled', detail='已取消，已完成的文件可从历史恢复')
            return {'cancelled': True}

        @router.post('/api/library/jobs/{ident}/retry')
        def retry(ident: str):
            job = self.get('library_job', ident)
            if not job or job['status'] in ACTIVE:
                raise HTTPException(409, '任务不存在或仍在运行')
            paths = [i['path'] for i in job.get('items', []) if i['status'] not in {'complete', 'skipped'}] or job['paths']
            return self.submit(ProcessBody(paths=paths, **job['options']))

        @router.post('/api/library/jobs/{ident}/restore')
        def restore(ident: str, body: RestoreBody | None = None):
            with self.guard:
                return self.restore(ident, body.items if body else None)

        @router.delete('/api/library/files/locks')
        def unlock(path: str):
            asset = self.asset(self.resolve(path))
            with self.db_lock:
                self.db.execute('UPDATE library_assets SET locks=\'[]\' WHERE id=?', (asset['id'],))
                self.db.commit()
            return {'unlocked': True}
