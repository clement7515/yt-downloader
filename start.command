#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "========================================"
echo "  YouTube 下載器 - macOS 啟動腳本"
echo "========================================"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[錯誤] 找不到 python3，請先安裝 Python 3："
  echo "  https://www.python.org/downloads/ 或 brew install python"
  read -r -p "按 Enter 鍵結束..."
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1 && [ ! -x /opt/homebrew/bin/ffmpeg ] && [ ! -x /usr/local/bin/ffmpeg ]; then
  echo "[提醒] 尚未偵測到 ffmpeg（下載 1080p 以上高畫質或轉 MP3 會需要它）。"
  echo "      建議稍後安裝：brew install ffmpeg"
  echo ""
fi

if [ ! -d ".venv" ]; then
  echo "[1/3] 首次啟動，正在建立虛擬環境..."
  python3 -m venv .venv
  echo "[2/3] 正在安裝相依套件..."
  .venv/bin/pip install --upgrade pip -q
  .venv/bin/pip install -r requirements.txt
else
  echo "[1/2] 正在檢查並更新 yt-dlp..."
  .venv/bin/pip install -U yt-dlp -q || echo "[提醒] 無法自動更新 yt-dlp，將使用現有版本繼續。"
fi

echo "[啟動] 正在開啟伺服器與瀏覽器..."
.venv/bin/python3 run.py
