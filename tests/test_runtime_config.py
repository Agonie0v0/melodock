"""New configuration names take precedence while existing state stays readable."""
import os

from runtime_config import apply_environment_aliases, database_path


def test_new_environment_overrides_legacy_and_keeps_empty_values(monkeypatch):
    monkeypatch.setattr(os, 'environ', {'MELODOCK_PORT': '9876', 'MUSICDL_PORT': '8765',
                                     'MELODOCK_TG_TOKEN': '', 'MUSICDL_TG_TOKEN': 'old-token',
                                     'MUSICDL_DATA_DIR': '/existing', 'OTHER': 'unchanged'})
    apply_environment_aliases()
    assert os.environ['MUSICDL_PORT'] == '9876'
    assert os.environ['MUSICDL_TG_TOKEN'] == ''
    assert os.environ['MUSICDL_DATA_DIR'] == '/existing'
    assert os.environ['OTHER'] == 'unchanged'


def test_database_upgrade_keeps_original_bytes_and_new_installs_use_new_name(tmp_path):
    current = tmp_path / 'melodock.db'
    previous = tmp_path / 'musicdl.db'
    assert database_path(tmp_path) == current
    previous.write_bytes(b'existing-state')
    assert database_path(tmp_path) == previous
    assert previous.read_bytes() == b'existing-state' and not current.exists()
    current.write_bytes(b'new-state')
    assert database_path(tmp_path) == current
