@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   YouTube 下載器 - Windows 啟動腳本
echo ========================================

where python >nul 2>nul
if errorlevel 1 (
  echo [錯誤] 找不到 Python，請先前往以下網址安裝 Python 3（安裝時請勾選 Add Python to PATH）：
  echo   https://www.python.org/downloads/
  pause
  exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [提醒] 尚未偵測到 ffmpeg（下載 1080p 以上高畫質或轉 MP3 會需要它）。
  echo        可用指令安裝：winget install Gyan.FFmpeg
  echo.
)

if not exist ".venv" (
  echo [1/3] 首次啟動，正在建立虛擬環境...
  python -m venv .venv
  echo [2/3] 正在安裝相依套件...
  .venv\Scripts\python.exe -m pip install --upgrade pip -q
  .venv\Scripts\pip.exe install -r requirements.txt
) else (
  echo [1/2] 正在檢查並更新 yt-dlp...
  .venv\Scripts\pip.exe install -U yt-dlp -q || echo [提醒] 無法自動更新 yt-dlp，將使用現有版本繼續。
)

echo [啟動] 正在開啟伺服器與瀏覽器...
.venv\Scripts\python.exe run.py
pause
