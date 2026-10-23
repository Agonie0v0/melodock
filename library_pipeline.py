"""Persistent, recoverable local music processing in the existing application."""
import base64
import copy
import hashlib
import json
import os
import re
import shutil
import string
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator
from typing import Literal

import local_library
from metadata_scraper import MetadataScraper, SOURCES, clean, pick, rank
from navidrome import Navidrome, NavidromeSettings

INTERNAL_DIRS = {'.partial', '.processing', '.originals', '.musicdl-history'}
ACTIVE = {'queued', 'identifying', 'tagging', 'organizing', 'indexing', 'restoring'}
TEMPLATE_FIELDS = {*local_library.TAG_FIELDS, 'ext'}


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
    if not value or len(value) > 300 or value.startswith(('/', '\\')) or '..' in re.split(r'[/\\]', value):
        raise ValueError('整理模板应为音乐库内的相对路径')
    try:
        for _, field, spec, conversion in string.Formatter().parse(value):
            if field is not None and (field not in TEMPLATE_FIELDS or spec or conversion):
                raise ValueError('模板只支持显示的标签变量，不支持格式表达式')
    except (KeyError, ValueError):
        raise ValueError('模板格式无效或包含不支持的变量') from None
    return value.replace('\\', '/')


class LibrarySettings(BaseModel):
    auto_scrape: bool = False
    auto_organize: bool = False
    library_dir: str = Field(default='library', min_length=1, max_length=1000)
    folder_template: str = '{album_artist}/{album}'
    filename_template: str = '{track_number} - {title}'
    sources: list[Literal['netease', 'qq']] = Field(default_factory=lambda: ['netease', 'qq'], max_length=2)
    overwrite: bool = False
    lyrics_mode: Literal['both', 'embed', 'lrc', 'none'] = 'both'
    cover_mode: Literal['both', 'embed', 'file', 'none'] = 'both'
    fields: list[str] = Field(default_factory=lambda: [*local_library.TAG_FIELDS], max_length=len(local_library.TAG_FIELDS))
    backup_days: int = Field(default=7, ge=1, le=365)

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
        if '/' in value:
            raise ValueError('文件名模板不能包含目录分隔符')
        return value

    @field_validator('fields')
    @classmethod
    def fields_valid(cls, value):
        if any(field not in local_library.TAG_FIELDS for field in value):
            raise ValueError('不支持的标签字段')
        return list(dict.fromkeys(value))


class ProcessBody(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=1000)
    action: Literal['scrape', 'organize', 'both', 'edit', 'extract', 'clean', 'duplicates'] = 'both'
    changes: dict[str, str] = Field(default_factory=dict)
    lyrics: str | None = Field(default=None, max_length=2_000_000)
    cover_data: str | None = Field(default=None, max_length=12_000_000)
    overwrite: bool | None = None
    filename_order: Literal['title_artist', 'artist_title'] = 'title_artist'
    find: str = Field(default='', max_length=300)
    replacement: str = Field(default='', max_length=300)

    @field_validator('changes')
    @classmethod
    def changes_valid(cls, value):
        if any(k not in local_library.TAG_FIELDS or len(v) > 2000 for k, v in value.items()):
            raise ValueError('标签字段或长度无效')
        return value


class ApplyBody(BaseModel):
    choices: dict[str, str] = Field(default_factory=dict)
    skip: list[str] = Field(default_factory=list, max_length=1000)


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
        self.navidrome = Navidrome(self.nav_settings)
        with db_lock:
            db.execute('CREATE TABLE IF NOT EXISTS library_assets(id TEXT PRIMARY KEY,path TEXT NOT NULL UNIQUE,locks TEXT NOT NULL DEFAULT \'[]\',source TEXT NOT NULL DEFAULT \'{}\')')
            db.execute('CREATE TABLE IF NOT EXISTS library_paths(token TEXT PRIMARY KEY,asset_id TEXT NOT NULL)')
            db.commit()

    def settings(self):
        return LibrarySettings(**self.get('library_setting', 'config', {})).model_dump()

    def nav_settings(self):
        return {'enabled': False, 'url': '', 'username': '', 'password': '', 'api_key': '', 'auto_scan': False,
                **self.get('library_setting', 'navidrome', {})}

    def public_settings(self):
        nav = self.nav_settings()
        return {**self.settings(), 'file_root': str(self.old.FILE_ROOT),
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

    def validate_path(self, path, *, internal=False, must_exist=True):
        path = Path(path)
        resolved = path.resolve()
        if path.is_symlink() or not any(resolved.is_relative_to(root.resolve()) for root in self.roots()):
            raise HTTPException(403, '文件不在允许的音乐目录内')
        if any(part in INTERNAL_DIRS or part.startswith('.musicdl-') for part in path.parts) and not internal:
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
                folders[:] = [name for name in folders if name not in INTERNAL_DIRS and not name.startswith('.musicdl-') and not (Path(directory) / name).is_symlink()]
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
        values = {key: safe_segment(tags.get(key), '') for key in local_library.TAG_FIELDS}
        values['title'] = values['title'] or safe_segment(path.stem)
        values['artist'] = values['artist'] or '未知歌手'
        values['album_artist'] = values['album_artist'] or values['artist']
        values['album'] = values['album'] or '未知专辑'
        values['ext'] = path.suffix.lstrip('.')
        number = re.match(r'\d+', values['track_number'])
        values['track_number'] = f'{int(number[0]):02d}' if number else ''
        parts = [safe_segment(segment.format_map(values)) for segment in settings['folder_template'].split('/')]
        filename = settings['filename_template'].format_map(values).strip(' -_.')
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

    def submit(self, body, download_id=None, sources=None):
        paths = list(dict.fromkeys(body.paths))
        for token in paths:
            path = self.resolve(token)
            if path.suffix.lower() not in local_library.AUDIO_EXTENSIONS:
                raise HTTPException(400, '请选择音频文件')
        settings = self.settings()
        if body.overwrite is not None:
            settings['overwrite'] = body.overwrite
        ident = uuid.uuid4().hex
        job = {'id': ident, 'action': body.action, 'status': 'queued', 'created_at': int(time.time()),
               'updated_at': int(time.time()), 'paths': paths, 'options': body.model_dump(exclude={'paths'}),
               'settings': settings, 'items': [], 'total': len(paths), 'processed': 0, 'detail': '等待处理',
               'download_id': download_id, 'sources': sources or {}, 'warnings': []}
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

    def prepare(self, ident):
        job = self.get('library_job', ident)
        try:
            self.save(job, status='identifying', detail='读取标签与识别歌曲')
            hashes = {}
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
                    item = {'id': asset['id'], 'path': self.token(path), 'name': path.name, 'original_path': str(path),
                            'revision': revision(path), 'before': before, 'after': dict(before), 'candidates': [],
                            'chosen': None, 'status': 'ready', 'warnings': [], 'locks': asset['locks'],
                            'tagged_fields': metadata.get('tagged_fields', []), 'target': str(path)}
                    try:
                        action = job['action']
                        if action == 'duplicates':
                            value = digest(path)
                            item['hash'] = value
                            hashes.setdefault(value, []).append({'id': asset['id'], 'name': path.name, 'path': str(path)})
                        if action in {'extract', 'clean'}:
                            if action == 'extract':
                                pieces = re.split(r'\s+-\s+', path.stem, maxsplit=1)
                                if len(pieces) == 2:
                                    title, artist = pieces if job['options']['filename_order'] == 'title_artist' else pieces[::-1]
                                    item['after'].update(title=title.strip(), artist=artist.strip())
                                else:
                                    item['warnings'].append('文件名未匹配“标题 - 歌手”或“歌手 - 标题”格式')
                            else:
                                for key, value in before.items():
                                    value = re.sub(r'\s+', ' ', value).strip()
                                    if job['options']['find']:
                                        value = value.replace(job['options']['find'], job['options']['replacement'])
                                    item['after'][key] = value
                        if action in {'scrape', 'both'}:
                            candidates, warnings = [], []
                            if source.get('source_id') and clean(source.get('title')):
                                candidates.append(source)
                            if not candidates or not clean(source.get('album')) or job['settings']['overwrite']:
                                found, warnings = self.scraper.search(reference, job['settings']['sources'])
                                candidates.extend(found)
                            item['warnings'].extend(warnings)
                            item['candidates'], selected = pick(reference, candidates)
                            if selected:
                                selected, warnings = self.scraper.enrich(selected, job['settings']['lyrics_mode'] != 'none')
                                item['warnings'].extend(warnings)
                                item['candidates'] = [selected if c['id'] == selected['id'] else c for c in item['candidates']]
                                item['chosen'] = selected['id']
                                self.merge(item, selected, job['settings'])
                            else:
                                item['status'] = 'needs_review'
                                item['warnings'].append('无法可靠确定歌曲版本，请选择候选或保留现有标签')
                        if action == 'edit':
                            item['after'].update(job['options']['changes'])
                        if action in {'organize', 'both'}:
                            item['target'] = str(self.target(path, item['after'], job['settings']))
                    except Exception as error:
                        item.update(status='failed', error=self.error_message(error))
                    job['items'].append(item)
                    self.save(job, processed=len(job['items']), detail=f'已检查 {len(job["items"])}/{job["total"]} 首')
            if ident in self.cancelled:
                self.save(job, status='cancelled', detail='处理已取消，文件保持不变')
            elif job['action'] == 'duplicates':
                job['duplicates'] = [group for group in hashes.values() if len(group) > 1]
                self.save(job, status='complete', detail=f'检查完成，发现 {len(job["duplicates"])} 组完全相同的文件；未删除文件')
            elif job.get('download_id'):
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
                        lyrics = job['options'].get('lyrics')
                        if lyrics is None and candidate and job['settings']['lyrics_mode'] != 'none':
                            lyrics = clean(candidate.get('lyrics')) or None
                            if not job['settings']['overwrite']:
                                lyrics = local_library.read_lyrics(path) or lyrics
                        cover = self.manual_cover(job['options'].get('cover_data'))
                        metadata = local_library.read_metadata(str(path), path.stat().st_mtime_ns, path.stat().st_size)
                        if cover is None and candidate and not job['settings']['overwrite'] and job['settings']['cover_mode'] != 'none':
                            cover = local_library.audio_cover(local_library.mutagen.File(path))
                        if cover is None and candidate and candidate.get('cover_url') and job['settings']['cover_mode'] != 'none':
                            if job['settings']['overwrite'] or not metadata['has_cover']:
                                try:
                                    cover = self.scraper.cover(candidate['cover_url'])
                                except Exception as error:
                                    item['warnings'].append('封面未更新：' + self.error_message(error))
                        target = self.target(path, item['after'], job['settings']) if job['action'] in {'organize', 'both'} else path
                        item['target'] = str(target)
                        self.publish(job, item, path, target, lyrics, cover)
                        if job['action'] in {'edit', 'extract', 'clean'}:
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
        history = self.old.FILE_ROOT / '.musicdl-history' / job['id'] / item['id']
        if not history.resolve().is_relative_to(self.old.FILE_ROOT.resolve()):
            raise ValueError('原件备份目录超出音乐根目录')
        history.mkdir(parents=True, exist_ok=True)
        backup = history / source.name
        shutil.copy2(source, backup)
        companions = self.sidecars(source)
        for file in companions:
            shutil.copy2(file, history / file.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / ('.musicdl-publish-' + uuid.uuid4().hex + source.suffix)
        operation = {'id': job['id'] + ':' + item['id'], 'job_id': job['id'], 'asset_id': item['id'],
                     'source': str(source), 'target': str(target), 'backup': str(backup), 'stage': str(stage),
                     'companions': [], 'outputs': [], 'state': 'preparing', 'created_at': int(time.time()),
                     'original_locks': self.asset(source)['locks'],
                     'expires_at': int(time.time()) + job['settings']['backup_days'] * 86400}
        self.put('library_operation', operation['id'], operation)
        try:
            shutil.copy2(source, stage)
            changes = {key: value for key, value in item['after'].items() if value != item['before'].get(key)}
            embed_lyrics = lyrics if job['settings']['lyrics_mode'] in {'both', 'embed'} or job['action'] == 'edit' else None
            embed_cover = cover if job['settings']['cover_mode'] in {'both', 'embed'} or job['action'] == 'edit' else None
            if not job['settings']['overwrite'] and job['action'] != 'edit':
                if embed_lyrics is not None and local_library.read_lyrics(source, prefer_sidecar=False):
                    embed_lyrics = None
                if embed_cover and local_library.audio_cover(local_library.mutagen.File(source)):
                    embed_cover = None
            if changes or embed_lyrics is not None or embed_cover is not None:
                local_library.write_metadata(stage, changes, lyrics=embed_lyrics, cover=embed_cover)
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
                                             'stage': str(dest.with_name('.musicdl-sidecar-' + uuid.uuid4().hex)),
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

    def rollback(self, operation):
        source, target, backup = (Path(operation[key]) for key in ('source', 'target', 'backup'))
        self.validate_path(source, internal=True, must_exist=False)
        self.validate_path(target, internal=True, must_exist=False)
        if not backup.resolve().is_relative_to((self.old.FILE_ROOT / '.musicdl-history').resolve()) or not backup.is_file():
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
        temporary = source.with_name('.musicdl-restore-' + uuid.uuid4().hex + source.suffix)
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

    def restore(self, ident):
        job = self.get('library_job', ident)
        if not job or job['status'] in ACTIVE:
            raise HTTPException(409, '任务不存在或仍在处理')
        self.save(job, status='restoring', detail='正在恢复原文件')
        def run():
            try:
                for item in reversed(job['items']):
                    operation = self.get('library_operation', item.get('operation_id', ''))
                    if not operation or operation['state'] != 'complete':
                        continue
                    target = Path(operation['target'])
                    with self.lock(target):
                        if not target.exists() or revision(target) != operation['output_revision']:
                            raise ValueError('文件在整理后已被修改，无法自动恢复；请先处理后续修改')
                        self.rollback(operation)
                        item['status'] = 'restored'
                self.save(job, status='restored', detail='已恢复原文件、标签和目录')
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
                backup_dir = Path(operation['backup']).parent
                history = (self.old.FILE_ROOT / '.musicdl-history').resolve()
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

    def close(self):
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
            self.put('library_setting', 'config', body.model_dump())
            return self.public_settings()

        @router.put('/api/library/navidrome')
        def save_navidrome(body: NavidromeSettings):
            value = body.model_dump()
            previous = self.nav_settings()
            for key in ('password', 'api_key'):
                if value[key] is None:
                    value[key] = previous.get(key, '')
            if value['enabled'] and (not value['url'] or not (value.get('api_key') or value.get('username') and value.get('password'))):
                raise HTTPException(400, '启用 Navidrome 需要服务地址和有效的认证配置')
            self.put('library_setting', 'navidrome', value)
            return self.public_settings()['navidrome']

        @router.get('/api/library/jobs')
        def jobs(offset: int = 0, size: int = 30):
            if offset < 0 or not 1 <= size <= 100:
                raise HTTPException(400, '分页参数无效')
            all_jobs = self.values('library_job')
            return {'jobs': [{k: v for k, v in job.items() if k not in {'items', 'sources', 'options', 'settings', 'paths'}}
                             for job in all_jobs[offset:offset + size]], 'has_more': len(all_jobs) > offset + size}

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
                        candidate, warnings = self.scraper.enrich(candidate, job['settings']['lyrics_mode'] != 'none')
                        item['warnings'].extend(warnings)
                        item['candidates'] = [candidate if c['id'] == candidate['id'] else c for c in item['candidates']]
                        self.merge(item, candidate, job['settings'])
                    if job['action'] in {'organize', 'both'}:
                        item['target'] = str(self.target(self.resolve(item['path']), item['after'], job['settings']))
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
        def restore(ident: str):
            with self.guard:
                return self.restore(ident)

        @router.delete('/api/library/files/locks')
        def unlock(path: str):
            asset = self.asset(self.resolve(path))
            with self.db_lock:
                self.db.execute('UPDATE library_assets SET locks=\'[]\' WHERE id=?', (asset['id'],))
                self.db.commit()
            return {'unlocked': True}
