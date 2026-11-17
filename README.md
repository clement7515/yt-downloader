# YouTube Web 下載器

基於 **FastAPI + yt-dlp + ffmpeg** 的本機 Web UI 下載工具。

## 功能特色
- **網址預覽解析**：顯示縮圖、標題、頻道、片長、可用最高畫質與播放清單內容
- **畫質與編碼選擇**：支援最高畫質 / 4K / 2K / 1080p / 720p，可切換「相容性優先 (MP4: H.264 + AAC)」或「極致畫質優先 (VP9 / AV1)」
- **純音訊轉檔**：一鍵轉換 MP3 / M4A / OPUS / FLAC（可選 320 / 192 / 128 kbps）
- **字幕下載**：支援繁體中文 / 英文等多語言代碼、自動生成字幕，並可選內嵌進影片
- **播放清單支援**：可選單支影片或整個播放清單，並支援指定項目範圍（如 `1-5`、`1,3,5`）
- **即時進度推播**：透過 Server-Sent Events (SSE) 即時顯示百分比、下載速度、剩餘時間與取消控制
- **瀏覽器 Cookie 支援**：遇到 YouTube 驗證或年齡限制時可選用 Chrome / Safari 等瀏覽器 Cookie

---

## 打包成獨立執行檔（免安裝 Python / ffmpeg）

### 1. macOS（本機打包）
```bash
./build_app.sh
```
產出位於 `dist/YouTubeDownloader.app`（下載預設儲存於 `~/Downloads/YouTubeDownloader`）。

### 2. Windows（透過 GitHub Actions 雲端自動打包 `.exe`）
本專案已內建 [.github/workflows/build-windows.yml](.github/workflows/build-windows.yml)：
1. 在 GitHub 建立一個新的 Repository（公開或私人皆可）。
2. 將本專案推送至 GitHub 的 `main` 分支：
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<你的帳號>/<你的倉庫>.git
   git push -u origin main
   ```
3. 打開 GitHub Repository 頁面的 **Actions** 分頁，等待 `Build Windows EXE` 執行完成（約 2～3 分鐘）。
4. 點進該次執行紀錄，在最下方的 **Artifacts** 下載 `YouTubeDownloader-Windows` 壓縮檔，解壓即為單一執行檔 `YouTubeDownloader.exe`。
5. 對方收到後雙擊 `YouTubeDownloader.exe` 即可使用（若 Windows Defender 跳出「已保護您的電腦」，點「其他資訊 → 仍要執行」即可）。
