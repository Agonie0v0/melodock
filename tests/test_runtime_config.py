"""A deployment migrates once and runs with canonical state on every restart."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import pickle
from types import SimpleNamespace

import pytest
from dotenv import dotenv_values

from runtime_config import initialize_environment, database_path, migrate_library_state


def test_environment_and_dotenv_migrate_once_with_new_values_winning(tmp_path, monkeypatch):
    data = tmp_path / 'data'
    monkeypatch.setattr(os, 'environ', {'MUSICDL_DATA_DIR': str(data), 'MUSICDL_PORT': '8765',
                                     'MELODOCK_PORT': '9000', 'MELOKEEP_PORT': '9876',
                                     'MELOKEEP_TG_TOKEN': '', 'MUSICDL_TG_TOKEN': 'old-token',
                                     'MUSICDL_PASS': "a'b\\c", 'OTHER': 'unchanged'})
    env_file = tmp_path / '.env'
    env_file.write_text("MUSICDL_HOST=localhost\nMELODOCK_HOST=127.0.0.2\nMELOKEEP_HOST=127.0.0.1\nMUSICDL_USER=admin\n", encoding='utf-8')
    initialize_environment(tmp_path)
    assert os.environ['MELOKEEP_PORT'] == '9876'
    assert os.environ['MELOKEEP_TG_TOKEN'] == ''
    assert os.environ['MELOKEEP_PASS'] == "a'b\\c"
    assert os.environ['MELOKEEP_HOST'] == '127.0.0.1'
    assert os.environ['OTHER'] == 'unchanged'
    assert not any(key.startswith(('MUSICDL_', 'MELODOCK_')) for key in os.environ)
    assert dotenv_values(env_file) == {'MELOKEEP_HOST': '127.0.0.1', 'MELOKEEP_USER': 'admin'}
    saved = json.loads((data / 'melokeep-runtime.json').read_text(encoding='utf-8'))
    assert saved['environment']['MELOKEEP_PASS'] == "a'b\\c"
    # A recreated container still supplies its original variables. Ignore them;
    # the first import is persisted and explicit current settings still win.
    monkeypatch.setattr(os, 'environ', {'MUSICDL_DATA_DIR': str(data), 'MUSICDL_PASS': 'changed-old',
                                     'MUSICDL_TG_TOKEN': 'revived', 'MELOKEEP_PORT': '9999'})
    initialize_environment(tmp_path)
    assert os.environ['MELOKEEP_PASS'] == "a'b\\c"
    assert os.environ['MELOKEEP_PORT'] == '9999'
    assert 'MELOKEEP_TG_TOKEN' not in os.environ
    assert not any(key.startswith(('MUSICDL_', 'MELODOCK_')) for key in os.environ)


def test_default_directory_config_and_quoted_values_are_migrated(tmp_path, monkeypatch):
    old = tmp_path / 'musicdl_outputs'
    old.mkdir()
    (old / 'song.flac').write_bytes(b'original music')
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'global_client_cfg': {'work_dir': str(old)},
                                  'cookies': {'QQ': 'musicdl_outputs is a credential'}}), encoding='utf-8')
    env_file = tmp_path / '.env'
    env_file.write_text("MUSICDL_PASS=\"a'b\\\\c\"\nMUSICDL_WORKDIR=musicdl_outputs\n", encoding='utf-8')
    monkeypatch.setattr(os, 'environ', {})
    initialize_environment(tmp_path)
    current = tmp_path / 'melokeep_outputs'
    assert not old.exists() and (current / 'song.flac').read_bytes() == b'original music'
    assert os.environ['MELOKEEP_WORKDIR'] == 'melokeep_outputs'
    assert dotenv_values(env_file)['MELOKEEP_PASS'] == os.environ['MELOKEEP_PASS']
    migrated = json.loads(config.read_text(encoding='utf-8'))
    assert migrated['global_client_cfg']['work_dir'] == str(current)
    assert migrated['cookies']['QQ'] == 'musicdl_outputs is a credential'
    initialize_environment(tmp_path)
    assert dotenv_values(env_file)['MELOKEEP_WORKDIR'] == 'melokeep_outputs'


@pytest.mark.parametrize('prefix', ['MELOKEEP_', 'MUSICDL_'])
def test_container_defaults_preserve_deployment_storage_and_credentials(tmp_path, monkeypatch, prefix):
    data = tmp_path / 'storage'
    music = tmp_path / 'music'
    monkeypatch.setattr(os, 'environ', {'MELOKEEP_CONTAINER': '1', prefix + 'DATA_DIR': str(data),
                                     prefix + 'FILE_ROOT': str(music), prefix + 'USER': 'admin',
                                     prefix + 'PASS': 'original-password'})
    initialize_environment(tmp_path)
    assert os.environ['MELOKEEP_BIND'] == '0.0.0.0'
    assert os.environ['MELOKEEP_FILE_ROOT'] == str(music)
    assert os.environ['MELOKEEP_CONFIG'] == str(data / 'config.json')
    assert os.environ['MELOKEEP_PASS'] == 'original-password'
    initialize_environment(tmp_path)
    assert os.environ['MELOKEEP_DATA_DIR'] == str(data)
    assert not any(key.startswith(('MUSICDL_', 'MELODOCK_')) for key in os.environ)


@pytest.mark.parametrize('previous_name', ['musicdl.db', 'melodock.db'])
def test_database_moves_committed_wal_data_and_uses_only_new_name(tmp_path, previous_name):
    current = tmp_path / 'melokeep.db'
    assert database_path(tmp_path) == current
    previous = tmp_path / previous_name
    subprocess.run([sys.executable, '-c', '''
import os, sqlite3, sys
db = sqlite3.connect(sys.argv[1])
db.execute('PRAGMA journal_mode=WAL')
db.execute('CREATE TABLE saved(value TEXT)')
db.execute("INSERT INTO saved VALUES ('playlist, settings and history')")
db.commit()
os._exit(0)
''', str(previous)], check=True)
    assert Path(str(previous) + '-wal').stat().st_size > 0
    assert database_path(tmp_path) == current
    assert not previous.exists()
    with sqlite3.connect(current) as db:
        assert db.execute('SELECT value FROM saved').fetchone() == ('playlist, settings and history',)
    assert database_path(tmp_path) == current
    assert not list(tmp_path.glob(previous_name + '*'))


def test_multiple_databases_never_silently_overwrite_data(tmp_path):
    for name in ('musicdl.db', 'melodock.db'):
        (tmp_path / name).write_bytes(name.encode())
    with pytest.raises(RuntimeError, match='多份数据库'):
        database_path(tmp_path)
    assert (tmp_path / 'musicdl.db').read_bytes() == b'musicdl.db'
    assert not (tmp_path / 'melokeep.db').exists()


def test_history_assets_and_recovery_paths_migrate_once_without_touching_tags(tmp_path):
    root = tmp_path / 'melokeep_outputs'
    history = root / '.musicdl-history' / 'job' / 'operation'
    history.mkdir(parents=True)
    (history / 'song.flac').write_bytes(b'restorable original')
    stage = root / '.musicdl-publish-123.flac'
    stage.write_bytes(b'in progress')
    old_root = tmp_path / 'musicdl_outputs'
    old_token = json.dumps([str(old_root), 'song.flac'])
    engine = tmp_path / 'data' / 'engine'
    engine.mkdir(parents=True)
    cache = engine / 'track.song'
    cache.write_bytes(pickle.dumps(SimpleNamespace(raw_data={'_musicdl_candidate': True, 'title': 'original'},
                                                  work_dir=str(old_root), _save_path=None)))
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE records(kind TEXT,id TEXT,body TEXT,PRIMARY KEY(kind,id))')
        db.execute('CREATE TABLE library_assets(id TEXT,path TEXT UNIQUE)')
        db.execute('CREATE TABLE library_paths(token TEXT PRIMARY KEY,asset_id TEXT)')
        db.execute('INSERT INTO library_assets VALUES (?,?)', ('stable-id', str(old_root / 'song.flac')))
        db.execute('INSERT INTO library_paths VALUES (?,?)', (old_token, 'stable-id'))
        operation = {'backup': str(old_root / '.musicdl-history/job/operation/song.flac'),
                     'stage': str(old_root / stage.name), 'local_path': old_token,
                     'title': '.musicdl-history', 'password': 'musicdl_outputs'}
        db.execute('INSERT INTO records VALUES (?,?,?)', ('library_operation', 'op', json.dumps(operation)))
        migrate_library_state(db, root, tmp_path, engine)
        migrated = json.loads(db.execute("SELECT body FROM records WHERE id='op'").fetchone()[0])
        assert Path(migrated['backup']).read_bytes() == b'restorable original'
        assert Path(migrated['stage']).read_bytes() == b'in progress'
        assert not (root / '.musicdl-history').exists() and not stage.exists()
        assert migrated['title'] == '.musicdl-history' and migrated['password'] == 'musicdl_outputs'
        assert json.loads(migrated['local_path']) == [str(root), 'song.flac']
        assert db.execute('SELECT id,path FROM library_assets').fetchone() == ('stable-id', str(root / 'song.flac'))
        assert db.execute('SELECT asset_id FROM library_paths').fetchone() == ('stable-id',)
        song = pickle.loads(cache.read_bytes())
        assert song.raw_data == {'_melokeep_candidate': True, 'title': 'original'}
        assert song.work_dir == str(root)
        before = db.total_changes
        migrate_library_state(db, root, tmp_path)
        assert db.total_changes == before
