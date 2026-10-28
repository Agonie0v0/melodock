#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/python install_dependencies.py
fi
if ! .venv/bin/python -c 'import requests_toolbelt; import importlib.metadata as m; assert m.version("musicdl") == "2.14.0+melokeep.1"' >/dev/null 2>&1; then
  .venv/bin/python install_dependencies.py
fi
if [ ! -f frontend/dist/index.html ]; then
  (cd frontend && npm ci && npm run build)
fi
exec .venv/bin/python app.py
