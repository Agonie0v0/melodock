"""The compatibility wheel changes dependency metadata, never engine code."""
import base64
from contextlib import closing
import csv
import hashlib
import io
import re
import zipfile

import pytest

import install_dependencies as installer


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_engine_wheel_is_verified_and_every_file_has_a_valid_record(tmp_path, monkeypatch, newline):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as wheel:
        wheel.writestr('musicdl/__init__.py', '__version__ = "2.14.0"\n')
        wheel.writestr('musicdl-2.14.0.dist-info/METADATA',
                       newline.join(['Version: 2.14.0', 'Requires-Dist: cryptography<47,>=46.0.5', '']))
        wheel.writestr('musicdl-2.14.0.dist-info/RECORD', '')
    data = data.getvalue()
    with pytest.raises(ValueError, match='SHA256'):
        installer.prepare_wheel(data, tmp_path)
    monkeypatch.setattr(installer, 'ENGINE_SHA256', hashlib.sha256(data).hexdigest())
    target = installer.prepare_wheel(data, tmp_path)
    with zipfile.ZipFile(target) as wheel:
        assert wheel.read('musicdl/__init__.py') == b'__version__ = "2.14.0"\n'
        info = f'musicdl-{installer.ENGINE_VERSION}.dist-info/'
        assert b'cryptography<51,>=50.0.0' in wheel.read(info + 'METADATA')
        assert f'Version: {installer.ENGINE_VERSION}\n'.encode() in wheel.read(info + 'METADATA')
        for name, digest, size in csv.reader(io.StringIO(wheel.read(info + 'RECORD').decode())):
            if name.endswith('/RECORD'): continue
            content = wheel.read(name)
            assert int(size) == len(content)
            assert digest == 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b'=').decode()


def test_curl_embedded_brotli_is_also_patched():
    from curl_cffi import Curl
    with closing(Curl()) as curl:
        embedded = re.search(rb'brotli/(\d+)\.(\d+)\.(\d+)', curl.version())
    assert embedded is None or tuple(map(int, embedded.groups())) >= (1, 2, 1)
