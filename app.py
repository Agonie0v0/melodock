"""MeloKeep application with a provider-based music search and download engine."""
import os
from pathlib import Path
from runtime_config import initialize_environment

ROOT = Path(__file__).resolve().parent
initialize_environment(ROOT)
os.environ.setdefault('MELOKEEP_PROJECT_DIR', str(ROOT))
os.environ.setdefault('MELOKEEP_HOST', os.environ.get('MELOKEEP_BIND', '127.0.0.1'))
if os.environ.get('MELOKEEP_DOWNLOAD_DIR'):
    os.environ.setdefault('MELOKEEP_FILE_ROOT', os.environ['MELOKEEP_DOWNLOAD_DIR'])

from legacy import app as original
from engine_api import install

app = original.app
app.title = 'MeloKeep'
# Spawned playlist workers must not reopen the API database or recover downloads.
if __name__ != '__mp_main__':
    install(original, ROOT)

if __name__ == '__main__':
    import multiprocessing
    import uvicorn
    multiprocessing.freeze_support()
    uvicorn.run(app, host=original.SERVER_HOST, port=int(os.environ.get('MELOKEEP_PORT', '8765')))
