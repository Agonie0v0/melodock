"""New configuration names take precedence while existing state stays readable."""
import os
import pytest

from runtime_config import apply_environment_aliases, database_path


def test_new_environment_overrides_legacy_and_keeps_empty_values(monkeypatch):
    monkeypatch.setattr(os, 'environ', {'MELOKEEP_PORT': '9876', 'MUSICDL_PORT': '8765',
                                     'MELODOCK_PORT': '9000', 'MELODOCK_DATA_DIR': '/melodock',
                                     'MELODOCK_TG_TOKEN': 'previous-token',
                                     'MELOKEEP_TG_TOKEN': '', 'MUSICDL_TG_TOKEN': 'old-token',
                                     'MUSICDL_DATA_DIR': '/existing', 'MUSICDL_HOST': 'localhost',
                                     'OTHER': 'unchanged'})
    apply_environment_aliases()
    assert os.environ['MUSICDL_PORT'] == '9876'
    assert os.environ['MUSICDL_TG_TOKEN'] == ''
    assert os.environ['MUSICDL_DATA_DIR'] == '/melodock'
    assert os.environ['MUSICDL_HOST'] == 'localhost'
    assert os.environ['OTHER'] == 'unchanged'


@pytest.mark.parametrize('previous_name', ['musicdl.db', 'melodock.db'])
def test_database_upgrade_keeps_original_bytes_and_new_installs_use_new_name(tmp_path, previous_name):
    current = tmp_path / 'melokeep.db'
    previous = tmp_path / previous_name
    assert database_path(tmp_path) == current
    previous.write_bytes(b'existing-state')
    assert database_path(tmp_path) == previous
    assert previous.read_bytes() == b'existing-state' and not current.exists()
    current.write_bytes(b'new-state')
    assert database_path(tmp_path) == current


def test_database_prefers_most_recent_existing_brand(tmp_path):
    (tmp_path / 'musicdl.db').write_bytes(b'original-state')
    previous = tmp_path / 'melodock.db'
    previous.write_bytes(b'previous-state')
    assert database_path(tmp_path) == previous
