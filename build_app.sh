#!/bin/bash
set -e

cd "$(dirname "$0")"
export PYINSTALLER_CONFIG_DIR="$PWD/.pyinstaller_cache"

.venv/bin/pyinstaller \
  --name "YouTubeDownloader" \
  --windowed \
  --noconfirm \
  --add-data "static:static" \
  --collect-all imageio_ffmpeg \
  --collect-submodules yt_dlp \
  --hidden-import uvicorn.logging \
  --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.protocols.http.auto \
  --hidden-import uvicorn.lifespan.on \
  run.py

echo "打包完成：dist/YouTubeDownloader.app"
