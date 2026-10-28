"""Install the unchanged pinned engine with a compatible, patched crypto dependency.

The upstream wheel pins cryptography<47. Only its dependency metadata is changed;
source files stay byte-for-byte identical, and the input SHA256 is checked first.
"""
import base64
import csv
import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ENGINE_URL = ('https://files.pythonhosted.org/packages/2b/66/'
              'aa7c4be8e808a422a05ced4e22e6f3b379eef7aac35cbb6d5d6602e73c71/'
              'musicdl-2.14.0-py3-none-any.whl')
ENGINE_SHA256 = '0e4732331deebb02c7ec61379df83f8ef7556ad15d45429704a594ef3dd688c1'
ENGINE_VERSION = '2.14.0+melokeep.1'


def prepare_wheel(data, directory):
    if hashlib.sha256(data).hexdigest() != ENGINE_SHA256:
        raise ValueError('musicdl wheel SHA256 mismatch')
    old, new = 'musicdl-2.14.0.dist-info/', f'musicdl-{ENGINE_VERSION}.dist-info/'
    records, files = [], {}
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        for name in source.namelist():
            if name.endswith('/RECORD') or name.endswith('/'):
                continue
            content = source.read(name)
            name = name.replace(old, new)
            if name == new + 'METADATA':
                text = content.decode('utf-8').replace('\r\n', '\n')
                expected = 'Requires-Dist: cryptography<47,>=46.0.5'
                if text.count(expected) != 1:
                    raise ValueError('Unexpected musicdl dependency metadata')
                text = text.replace('Version: 2.14.0\n', f'Version: {ENGINE_VERSION}\n', 1)
                content = text.replace(expected, 'Requires-Dist: cryptography<51,>=50.0.0').encode('utf-8')
            files[name] = content
            digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b'=').decode()
            records.append((name, 'sha256=' + digest, str(len(content))))
    record = new + 'RECORD'
    rows = io.StringIO(newline='')
    csv.writer(rows, lineterminator='\n').writerows([*records, (record, '', '')])
    files[record] = rows.getvalue().encode()
    target = Path(directory) / f'musicdl-{ENGINE_VERSION}-py3-none-any.whl'
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as wheel:
        for name, content in files.items():
            wheel.writestr(name, content)
    return target


def main():
    root = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix='melokeep-dependencies-') as directory:
        with urllib.request.urlopen(ENGINE_URL, timeout=60) as response:
            wheel = prepare_wheel(response.read(8 * 1024 * 1024), directory)
        # pip otherwise treats 2.14.0 as satisfying a local 2.14.0+... wheel.
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--force-reinstall',
                        '--no-deps', str(wheel)], check=True)
        subprocess.run([sys.executable, '-m', 'pip', 'install', str(wheel),
                        '-r', str(root / 'requirements.txt'), *sys.argv[1:]], check=True)
    subprocess.run([sys.executable, '-m', 'pip', 'check'], check=True)


if __name__ == '__main__':
    main()
