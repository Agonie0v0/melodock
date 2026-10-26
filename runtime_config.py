"""Canonical MeloKeep configuration and one-time deployment migration."""
import json
import os
from pathlib import Path
import pickle
import re
import sqlite3
import tempfile

from dotenv import load_dotenv, dotenv_values

# These names are read only by the migration, never by the application runtime.
PREVIOUS_NAMES = ('musicdl', 'melodock')


def canonical_environment(values):
    result = {key: value for key, value in values.items()
              if not any(key.startswith(name.upper() + '_') for name in PREVIOUS_NAMES)}
    for name in reversed(PREVIOUS_NAMES):
        for key, value in values.items():
            if key.startswith(name.upper() + '_'):
                result.setdefault('MELOKEEP_' + key[len(name) + 1:], value)
    return result


def write_private(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.melokeep-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def move_directory(source, target):
    if not source.exists():
        return
    if source.is_symlink() or target.is_symlink():
        raise RuntimeError('命名迁移需要真实目录，不能使用符号链接')
    if not target.exists():
        source.rename(target)
        return
    for child in source.iterdir():
        destination = target / child.name
        if child.is_dir() and destination.is_dir():
            move_directory(child, destination)
        elif destination.exists():
            raise RuntimeError(f'命名迁移遇到同名文件，请保留两份数据并检查：{destination}')
        else:
            child.rename(destination)
    source.rmdir()


def migrated_path(value, project, *, internal=True):
    if not isinstance(value, str):
        return value
    # Change path components only; song titles, credentials and URLs stay intact.
    for name in PREVIOUS_NAMES:
        old_root = project / (name + '_outputs')
        candidate = Path(value)
        if candidate.is_absolute() and candidate.is_relative_to(old_root):
            value = str(project / 'melokeep_outputs' / candidate.relative_to(old_root))
        if value == name + '_outputs' or value.startswith((name + '_outputs/', name + '_outputs\\')):
            value = 'melokeep_outputs' + value[len(name + '_outputs'):]
        if internal:
            value = re.sub(r'(^|[/\\])\.' + name + r'-(?=(history|publish|sidecar|audio|restore|tags)(?:-|[/\\]|$))',
                           r'\1.melokeep-', value)
    return value


PATH_FIELDS = {'path', 'paths', '_path', 'local_path', 'original_path', 'file', 'file_path',
               'work_dir', 'file_root', 'source', 'target', 'backup', 'stage', 'scope_dir',
               'watch_dirs', 'watch_failure_dir', 'library_dir', 'directory'}


def migrate_paths(value, project, field=''):
    if isinstance(value, dict):
        return {key: migrate_paths(item, project, key) for key, item in value.items()}
    if isinstance(value, list):
        return [migrate_paths(item, project, field) for item in value]
    if field in PATH_FIELDS and isinstance(value, str):
        if value.startswith('['):
            try:
                token = json.loads(value)
                if isinstance(token, list) and len(token) == 2 and all(isinstance(part, str) for part in token):
                    return json.dumps([migrated_path(part, project) for part in token], ensure_ascii=False)
            except ValueError:
                pass
        return migrated_path(value, project)
    return value


def initialize_environment(project):
    """Import a deployment once, then use persisted canonical settings only."""
    project = Path(project).resolve()
    env_file = project / '.env'
    load_dotenv(env_file)
    data = os.environ.get('MELOKEEP_DATA_DIR')
    if not data:
        data = next((os.environ[name.upper() + '_DATA_DIR'] for name in reversed(PREVIOUS_NAMES)
                     if os.environ.get(name.upper() + '_DATA_DIR')),
                    '/data' if os.environ.get('MELOKEEP_CONTAINER') == '1' else str(project / 'data'))
    state = Path(data) / 'melokeep-runtime.json'
    if state.exists():
        saved = json.loads(state.read_text(encoding='utf-8'))
    else:
        canonical = canonical_environment(dict(os.environ))
        imported = {key: value for key, value in canonical.items()
                    if key.startswith('MELOKEEP_') and key not in os.environ}
        for key in ('MELOKEEP_FILE_ROOT', 'MELOKEEP_DOWNLOAD_DIR', 'MELOKEEP_WORKDIR'):
            if canonical.get(key):
                canonical[key] = migrated_path(canonical[key], project)
                if canonical[key] != os.environ.get(key):
                    imported[key] = canonical[key]
        for name in PREVIOUS_NAMES:
            move_directory(project / (name + '_outputs'), project / 'melokeep_outputs')
        default_config = Path(data) / 'config.json' if os.environ.get('MELOKEEP_CONTAINER') == '1' else project / 'config.json'
        config = Path(canonical.get('MELOKEEP_CONFIG', default_config))
        if config.exists():
            content = json.loads(config.read_text(encoding='utf-8'))
            migrated = migrate_paths(content, project)
            if migrated != content:
                write_private(config, json.dumps(migrated, ensure_ascii=False, indent=2) + '\n')
        if env_file.exists():
            values = dotenv_values(env_file, interpolate=False)
            migrated = canonical_environment(values)
            if values != migrated:
                lines = []
                for key, value in migrated.items():
                    if value is None:
                        lines.append(key)
                        continue
                    value = re.sub(r'\$\{(' + '|'.join(name.upper() for name in PREVIOUS_NAMES) + r')_', '${MELOKEEP_', value)
                    if key in ('MELOKEEP_FILE_ROOT', 'MELOKEEP_DOWNLOAD_DIR', 'MELOKEEP_WORKDIR'):
                        value = migrated_path(value, project)
                    lines.append(key + "='" + value.replace('\\', '\\\\').replace("'", "\\'") + "'")
                write_private(env_file, '\n'.join(lines) + '\n')
        saved = {'version': 1, 'environment': imported}
        write_private(state, json.dumps(saved, ensure_ascii=False, indent=2) + '\n')
        for key, value in canonical.items():
            if key.startswith('MELOKEEP_'):
                os.environ[key] = value
    for key, value in saved['environment'].items():
        os.environ.setdefault(key, value)
    for name in list(os.environ):
        if any(name.startswith(prefix.upper() + '_') for prefix in PREVIOUS_NAMES):
            del os.environ[name]
    if os.environ.get('MELOKEEP_CONTAINER') == '1':
        defaults = {'MELOKEEP_BIND': '0.0.0.0', 'MELOKEEP_DOWNLOAD_DIR': '/music',
                    'MELOKEEP_DATA_DIR': data, 'MELOKEEP_CONFIG': str(Path(data) / 'config.json'),
                    'MELOKEEP_COOKIE_SECURE': '0'}
        for key, value in defaults.items():
            os.environ.setdefault(key, value)


def database_path(directory):
    current = directory / 'melokeep.db'
    if current.exists():
        return current
    previous = [directory / (name + '.db') for name in PREVIOUS_NAMES if (directory / (name + '.db')).exists()]
    if len(previous) + int(current.exists()) > 1:
        raise RuntimeError('发现多份数据库，无法自动确定使用哪份；请保留数据并选择要迁移的数据库')
    if previous:
        source = previous[0]
        if source.is_symlink():
            raise RuntimeError('数据库命名迁移不支持符号链接')
        db = sqlite3.connect(source)
        try:
            if db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]:
                raise RuntimeError('数据库仍被其他进程使用，请停止其他实例后再迁移')
        finally:
            db.close()
        source.rename(current)
    return current


def migrate_library_state(db, file_root, project, engine_directory=None):
    if db.execute("SELECT 1 FROM records WHERE kind='runtime_setting' AND id='naming_version'").fetchone():
        return
    for name in PREVIOUS_NAMES:
        move_directory(file_root / ('.' + name + '-history'), file_root / '.melokeep-history')

    def move_stages(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'stage' and isinstance(item, str):
                    # The download root may already have moved in the environment phase.
                    source = Path(migrated_path(item, project, internal=False))
                    target = Path(migrated_path(item, project))
                    if source != target and source.exists() and source.resolve().is_relative_to(file_root.resolve()):
                        if target.exists() or source.is_symlink():
                            raise RuntimeError('处理临时文件迁移遇到冲突，请保留数据并检查音乐目录')
                        source.rename(target)
                else:
                    move_stages(item)
        elif isinstance(value, list):
            for item in value:
                move_stages(item)

    for kind, key, body in db.execute('SELECT kind,id,body FROM records').fetchall():
        value = json.loads(body)
        move_stages(value)
        migrated = migrate_paths(value, project)
        if migrated != value:
            db.execute('UPDATE records SET body=? WHERE kind=? AND id=?',
                       (json.dumps(migrated, ensure_ascii=False), kind, key))
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'library_assets' in tables:
        for key, path in db.execute('SELECT id,path FROM library_assets').fetchall():
            db.execute('UPDATE library_assets SET path=? WHERE id=?', (migrated_path(path, project), key))
    if 'library_paths' in tables:
        for token, key in db.execute('SELECT token,asset_id FROM library_paths').fetchall():
            updated = migrate_paths(token, project, 'path')
            if updated != token:
                db.execute('UPDATE library_paths SET token=? WHERE token=?', (updated, token))
    if engine_directory:
        for path in engine_directory.glob('*.song'):
            if path.is_symlink():
                raise RuntimeError('歌曲缓存迁移不支持符号链接')
            song = pickle.loads(path.read_bytes())
            changed = False
            for key in list(song.raw_data):
                for name in PREVIOUS_NAMES:
                    if key.startswith('_' + name + '_'):
                        song.raw_data['_melokeep_' + key[len(name) + 2:]] = song.raw_data.pop(key)
                        changed = True
            for field in ('work_dir', '_save_path'):
                value = getattr(song, field, None)
                updated = migrated_path(value, project)
                if value != updated:
                    setattr(song, field, updated)
                    changed = True
            if changed:
                content = pickle.dumps(song, protocol=pickle.HIGHEST_PROTOCOL)
                fd, temporary = tempfile.mkstemp(prefix='.melokeep-', dir=engine_directory)
                try:
                    with os.fdopen(fd, 'wb') as handle:
                        handle.write(content)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, path)
                finally:
                    Path(temporary).unlink(missing_ok=True)
    db.execute("INSERT INTO records(kind,id,body) VALUES ('runtime_setting','naming_version','1')")
    db.commit()
