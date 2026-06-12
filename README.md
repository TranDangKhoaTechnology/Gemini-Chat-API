<div align="center">

<img src="https://img.shields.io/badge/Gemini_Nexus-AI_Platform-6366f1?style=for-the-badge&logo=google&logoColor=white" alt="Gemini Nexus">

# 💠 Gemini Nexus

**Nền tảng AI thế hệ mới — OpenAI-compatible API proxy cho Gemini**  
*Developed by [TranDangKhoaTechnology](https://github.com/TranDangKhoaTechnology)*

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)
[![SQLite](https://img.shields.io/badge/SQLite-Database-003B57?style=flat-square&logo=sqlite&logoColor=white)](https://sqlite.org)
[![Telegram](https://img.shields.io/badge/Telegram-Admin_Bot-26A5E4?style=flat-square&logo=telegram&logoColor=white)](https://telegram.org)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)
[![Deploy on Render](https://img.shields.io/badge/Deploy_on-Render-46E3B7?style=flat-square&logo=render&logoColor=white)](https://render.com)

</div>

---

## 📖 Mục lục

- [Tổng quan](#-tổng-quan)
- [Tính năng nổi bật](#-tính-năng-nổi-bật)
- [Giao diện](#-giao-diện)
- [Kiến trúc hệ thống](#-kiến-trúc-hệ-thống)
- [Các mô hình được hỗ trợ](#-các-mô-hình-được-hỗ-trợ)
- [Hướng dẫn cài đặt](#-hướng-dẫn-cài-đặt)
- [Cấu hình môi trường](#-cấu-hình-môi-trường)
- [Lấy Google Cookies](#-lấy-google-cookies)
- [Deploy lên Render](#-deploy-lên-render)
- [Deploy bằng Docker](#-deploy-bằng-docker)
- [API Reference](#-api-reference)
- [Quản lý qua Telegram Bot](#-quản-lý-qua-telegram-bot)
- [Admin Dashboard](#-admin-dashboard)
- [Chat UI](#-chat-ui)
- [Workspace (Canvas Mode)](#-workspace-canvas-mode)
- [Định dạng file được hỗ trợ](#-định-dạng-file-được-hỗ-trợ)
- [Cấu trúc dự án](#-cấu-trúc-dự-án)
- [Lưu ý quan trọng](#-lưu-ý-quan-trọng)

---

## ✨ Tổng quan

**Gemini Nexus** là một API server mạnh mẽ chuyển đổi Gemini Web thành một API hoàn toàn tương thích với OpenAI. Bạn có thể sử dụng nó với bất kỳ ứng dụng nào hỗ trợ OpenAI API — không cần thay đổi code.

Hệ thống bao gồm:

- 🔌 **API Server** — Tương thích OpenAI `/v1/chat/completions`
- 🖥️ **Chat UI** — Giao diện chat đẹp, hiện đại
- 📊 **Admin Dashboard** — Quản lý API keys, cookies, người dùng
- 🤖 **Telegram Bot** — Điều khiển từ xa qua Telegram

> ⚠️ **Lưu ý**: Dự án này là unofficial, không liên kết với Google hay OpenAI. Cần có tài khoản Google hợp lệ.

---

## 🚀 Tính năng nổi bật

| Tính năng | Mô tả |
|-----------|--------|
| 🔄 **OpenAI-compatible** | Dùng được với OpenAI SDK, LangChain, và mọi client tương thích |
| ⚡ **Streaming SSE** | Phản hồi theo từng chunk thời gian thực |
| 🖼️ **Đa phương tiện** | Hỗ trợ ảnh, video, PDF, code files, và nhiều hơn |
| 🔐 **Quản lý API Key** | Phân quyền theo user, giới hạn model, rate limiting |
| 📊 **Admin Dashboard** | Web UI quản lý keys, cookies, sessions |
| 🤖 **Telegram Admin** | Điều khiển server từ Telegram |
| 🎨 **Canvas/Workspace** | Chế độ IDE với code generation thông minh |
| 📄 **PDF Generator** | Xuất kết quả dạng PDF trực tiếp |
| 🍪 **Cookie Auto-sync** | Tự động load cookies từ file khi khởi động |
| 🔒 **Rate Limiting** | Giới hạn request/phút theo từng key |
| 💬 **Multi-session** | Mỗi API key có conversation context riêng |
| 🐳 **Docker Ready** | Deploy dễ dàng với Docker |

---

## 🎨 Giao diện

### Chat UI (`/chat`)

Giao diện chat hiện đại với dark theme, hỗ trợ markdown đầy đủ:

- Sidebar quản lý lịch sử hội thoại
- Dropdown chọn model AI
- Hỗ trợ upload file, ảnh, PDF
- Chế độ Workspace (Canvas) cho lập trình
- Chế độ PDF Generator
- Nhận diện giọng nói (Speech-to-text)
- Export/Import lịch sử chat

### Admin Dashboard (`/`)

Bảng điều khiển quản trị đầy đủ:

- Xem và quản lý tất cả API keys
- Cập nhật Google Cookies
- Theo dõi trạng thái hệ thống
- Tạo/thu hồi keys với quyền hạn tùy chỉnh

---

## 🏗️ Kiến trúc hệ thống

```
┌─────────────────────────────────────────────┐
│          Client Applications                 │
│  (OpenAI SDK / Chat UI / Your App)           │
└──────────────┬──────────────────────────────┘
               │ HTTP / SSE
               ▼
┌─────────────────────────────────────────────┐
│              FastAPI Server                  │
│                                             │
│  GET  /v1/models                            │
│  POST /v1/chat/completions                  │
│  POST /v1/messages  (Anthropic-compat)      │
│  GET  /v1/admin/dashboard_data              │
│  POST /v1/admin/cookies                     │
│  GET  /v1/key_info                          │
│  GET  /chat  →  Chat Web UI                 │
│  GET  /      →  Admin Dashboard             │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│           AsyncChatbot Core                  │
│  (curl_cffi browser impersonation)           │
│                                             │
│  • Fetch SNlM0e bootstrap token             │
│  • Send prompt with session cookies         │
│  • Stream response chunks                   │
│  • Process images / files                   │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│           Gemini Web API                     │
│  (bard.google.com / gemini.google.com)       │
└─────────────────────────────────────────────┘
               │
    ┌──────────┴──────────┐
    ▼                     ▼
┌─────────┐         ┌──────────────┐
│ SQLite  │         │ Telegram Bot │
│ (keys,  │         │ (admin cmds) │
│ cookies,│         └──────────────┘
│ sessions│
└─────────┘
```

---

## 🧠 Các mô hình được hỗ trợ

| Model ID | Mô tả |
|----------|--------|
| `gemini-3.5-flash` | Mô hình mạnh nhất, phản hồi chi tiết |
| `gemini-3.1-pro` | Mô hình Pro, chất lượng cao |
| `gemini-3.1-flash-lite` | Nhanh nhất, tiết kiệm |
| `gemini-3.0-flash` | Ổn định, đa dụng |
| `gemini-3.0-flash-thinking` | Chế độ suy luận sâu (thinking mode) |

> Model list được lấy tự động qua `GET /v1/models`

---

## 🛠️ Hướng dẫn cài đặt

### Yêu cầu

- Python 3.10+
- Tài khoản Google (để lấy cookies)
- (Tuỳ chọn) Telegram Bot Token để dùng admin bot

### Bước 1: Clone dự án

```bash
git clone https://github.com/TranDangKhoaTechnology/Gemini-Chat-API.git
cd Gemini-Chat-API
```

### Bước 2: Tạo môi trường ảo và cài dependencies

```bash
# Tạo virtual environment
python -m venv .venv

# Kích hoạt (Linux/macOS)
source .venv/bin/activate

# Kích hoạt (Windows)
.venv\Scripts\activate

# Cài đặt packages
pip install -r requirements.txt
```

### Bước 3: Tạo file `.env`

```bash
cp .env.example .env
# Hoặc tạo mới:
```

```env
# Telegram Bot (tuỳ chọn nhưng khuyến nghị)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
ADMIN_ID=your_telegram_user_id_here

# Admin API Key mặc định (đổi ngay sau khi deploy!)
ADMIN_API_KEY=your-strong-admin-key-here

# Port server
PORT=8000
```

### Bước 4: Thêm Google Cookies

Xem hướng dẫn [Lấy Google Cookies](#-lấy-google-cookies) bên dưới.

### Bước 5: Chạy server

```bash
python main.py
```

Server sẽ khởi động tại: `http://localhost:8000`

---

## ⚙️ Cấu hình môi trường

| Biến | Bắt buộc | Mô tả |
|------|----------|--------|
| `TELEGRAM_BOT_TOKEN` | Không | Token của Telegram Bot |
| `ADMIN_ID` | Không | Telegram User ID của admin |
| `ADMIN_API_KEY` | Không | Key admin mặc định (default: `123456789`) |
| `PORT` | Không | Port server (default: `8000`) |

> ⚠️ **Bảo mật**: Đổi `ADMIN_API_KEY` ngay sau khi deploy! Key mặc định `123456789` chỉ dùng để setup ban đầu.

---

## 🍪 Lấy Google Cookies

Gemini Nexus cần 2 cookie từ phiên đăng nhập Google của bạn:

- `__Secure-1PSID`
- `__Secure-1PSIDTS`

### Cách 1: Dùng trình duyệt (Khuyến nghị)

1. Mở [https://gemini.google.com](https://gemini.google.com) và đăng nhập
2. Mở DevTools (`F12`) → Tab **Application** → **Cookies** → `https://gemini.google.com`
3. Tìm và copy giá trị của:
   - `__Secure-1PSID`
   - `__Secure-1PSIDTS`

### Cách 2: Qua Admin Dashboard (Sau khi deploy)

1. Truy cập `http://your-domain/` (Admin Dashboard)
2. Đăng nhập bằng Admin API Key
3. Tìm phần **"Đồng bộ hoá Google Cookies"**
4. Dán giá trị 2 cookies vào và bấm **Cập nhật**

Hoặc dán **chuỗi cookie text** dạng:
```
__Secure-1PSID=xxxx; __Secure-1PSIDTS=yyyy
```

Dashboard sẽ tự động tách ra 2 giá trị.

### Cách 3: Qua file `cookies.json`

Tạo file `cookies.json` ở thư mục gốc:

```json
[
  {
    "name": "__Secure-1PSID",
    "value": "your_psid_value_here"
  },
  {
    "name": "__Secure-1PSIDTS",
    "value": "your_psidts_value_here"
  }
]
```

Server sẽ tự load file này mỗi khi khởi động.

### Cách 4: Qua Telegram Bot

Gửi lệnh `/setcookies` cho Telegram Bot và làm theo hướng dẫn.

> ⚠️ **Cookie thường hết hạn sau 1-7 ngày**. Khi đó, cần cập nhật lại. Admin Dashboard sẽ hiển thị banner cảnh báo đỏ khi cookie hết hạn.

---

## 🚀 Deploy lên Render

Render là nền tảng cloud miễn phí phù hợp để deploy Gemini Nexus.

### Bước 1: Fork repo

Fork repo này về tài khoản GitHub của bạn.

### Bước 2: Tạo Web Service trên Render

1. Đăng nhập [render.com](https://render.com)
2. Chọn **New** → **Web Service**
3. Kết nối với GitHub repo vừa fork
4. Cấu hình:

| Trường | Giá trị |
|--------|---------|
| **Name** | `gemini-nexus` |
| **Runtime** | `Python 3` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `python main.py` |
| **Plan** | Free |

### Bước 3: Thêm Environment Variables

Trong tab **Environment** của Render service:

```
TELEGRAM_BOT_TOKEN = your_token
ADMIN_ID           = your_telegram_id
ADMIN_API_KEY      = your-strong-key
PORT               = 10000
```

> Render dùng PORT=10000 theo mặc định

### Bước 4: Deploy

Nhấn **Deploy**. Render sẽ tự build và deploy. Sau ~2-3 phút, service sẽ online.

### Bước 5: Cập nhật Cookies

Truy cập `https://your-service.onrender.com/` và đăng nhập bằng Admin Key để thêm Google cookies.

---

## 🐳 Deploy bằng Docker

### Chạy nhanh

```bash
docker build -t gemini-nexus .

docker run -d \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  --env-file .env \
  --name gemini-nexus \
  gemini-nexus
```

### Docker Compose

```yaml
version: '3.8'
services:
  gemini-nexus:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
      - ./cookies.json:/app/cookies.json
    env_file:
      - .env
    restart: unless-stopped
```

```bash
docker compose up -d
```

---

## 📡 API Reference

### Authentication

Mọi request cần header:

```http
Authorization: Bearer YOUR_API_KEY
```

---

### `GET /v1/models`

Lấy danh sách model khả dụng cho API key của bạn.

**Request:**
```bash
curl http://localhost:8000/v1/models \
  -H "Authorization: Bearer YOUR_API_KEY"
```

**Response:**
```json
{
  "object": "list",
  "data": [
    {
      "id": "gemini-3.5-flash",
      "object": "model",
      "created": 1710000000,
      "owned_by": "google"
    }
  ]
}
```

---

### `POST /v1/chat/completions`

Endpoint chat chính, tương thích OpenAI.

#### Chat đơn giản

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "model": "gemini-3.5-flash",
    "messages": [
      {"role": "user", "content": "Xin chào! Bạn có thể giúp gì cho tôi?"}
    ]
  }'
```

#### Với System Prompt

```json
{
  "model": "gemini-3.5-flash",
  "messages": [
    {
      "role": "system",
      "content": "Bạn là Gemini Nexus, một trợ lý AI thông minh do TranDangKhoaTechnology phát triển."
    },
    {
      "role": "user",
      "content": "Bạn là ai?"
    }
  ]
}
```

#### Streaming

```json
{
  "model": "gemini-3.5-flash",
  "messages": [{"role": "user", "content": "Kể một câu chuyện ngắn"}],
  "stream": true
}
```

Response dạng SSE:
```
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"delta":{"content":"Ngày xưa"}}]}
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"delta":{"content":", có một"}}]}
data: [DONE]
```

#### Với ảnh (Multimodal)

```json
{
  "model": "gemini-3.5-flash",
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "Mô tả ảnh này cho tôi"},
        {
          "type": "image_url",
          "image_url": {"url": "data:image/png;base64,iVBORw0KGgo..."}
        }
      ]
    }
  ]
}
```

---

### `GET /v1/key_info`

Xem thông tin API key hiện tại.

```bash
curl http://localhost:8000/v1/key_info \
  -H "Authorization: Bearer YOUR_API_KEY"
```

**Response:**
```json
{
  "key": "sk-xxxxxxxxx",
  "name": "My Key",
  "role": "user",
  "allowed_models": "all",
  "active": true,
  "expires_at": null
}
```

---

### Admin Endpoints

> Chỉ dùng được với Admin API Key.

#### `GET /v1/admin/dashboard_data`

Lấy toàn bộ dữ liệu dashboard.

#### `POST /v1/admin/cookies`

Cập nhật Google cookies.

```bash
curl -X POST http://localhost:8000/v1/admin/cookies \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ADMIN_KEY" \
  -d '{
    "psid": "__Secure-1PSID_value",
    "psidts": "__Secure-1PSIDTS_value"
  }'
```

#### `POST /v1/admin/keys/create`

Tạo API key mới.

```bash
curl -X POST http://localhost:8000/v1/admin/keys/create \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ADMIN_KEY" \
  -d '{
    "name": "user-john",
    "role": "user",
    "allowed_models": "all",
    "req_per_min": 30
  }'
```

#### `POST /v1/admin/keys/revoke`

Thu hồi API key.

#### `POST /v1/admin/change_key`

Đổi Admin API Key.

---

## 🤖 Quản lý qua Telegram Bot

Sau khi cấu hình `TELEGRAM_BOT_TOKEN` và `ADMIN_ID`, bạn có thể quản lý server qua Telegram:

| Lệnh | Mô tả |
|------|--------|
| `/start` | Hiển thị menu chính |
| `/newkey [tên]` | Tạo API key mới cho user |
| `/newadminkey [tên]` | Tạo Admin API key |
| `/listkeys` | Xem tất cả API keys |
| `/revokekey [tên]` | Thu hồi API key |
| `/settimeout [tên] [giờ]` | Đặt thời gian hết hạn session |
| `/setcookies` | Cập nhật Google Cookies |
| `/cookiestatus` | Kiểm tra trạng thái cookies |
| `/health` | Kiểm tra kết nối Gemini |
| `/backup` | Tải backup database |
| `/changekey` | Đổi Admin API Key |
| `/setlimit [key] [rpm]` | Đặt rate limit (req/phút) |
| `/stats` | Xem thống kê sử dụng |

---

## 📊 Admin Dashboard

Truy cập tại: `http://your-domain/`

Đăng nhập bằng Admin API Key để vào dashboard.

### Tính năng:

**Quản lý API Keys**
- Tạo key mới với tên, quyền hạn, model được phép
- Xem danh sách keys với thông tin đầy đủ
- Thu hồi / kích hoạt keys
- Sao chép key vào clipboard

**Quản lý Cookies**
- Xem trạng thái cookie hiện tại
- Dán cookie text / chuỗi cURL để tự động tách giá trị
- Cảnh báo khi cookie hết hạn

**Thông tin hệ thống**
- Trạng thái server
- Tổng số keys đang hoạt động
- Cookie status

---

## 💬 Chat UI

Truy cập tại: `http://your-domain/chat`

### Cài đặt ban đầu:

1. Mở phần **Cấu hình API** trong sidebar bên trái
2. Chọn API Key từ dropdown (hoặc nhập thủ công)
3. Nhấn nút refresh (🔄) để load danh sách model
4. Chọn model từ dropdown ở giữa header
5. Bắt đầu chat!

### Tính năng Chat UI:

**Sidebar trái:**
- 📁 Lịch sử hội thoại (lưu local)
- ⚙️ Cấu hình API (API Key, System Prompt, Stream toggle)
- 🌐 Chuyển đổi ngôn ngữ VI/EN

**Input area:**
- 📎 Đính kèm file (ảnh, PDF, code...)
- 🎤 Nhận diện giọng nói
- ✏️ Chỉnh sửa message đã gửi
- 🔄 Regenerate response

**Message actions:**
- 📋 Copy nội dung
- ↩️ Reply to message
- 🔄 Regenerate

**Special modes:**
- 🎨 **Workspace Mode** — IDE cho lập trình với code generation
- 📄 **PDF Mode** — Xuất kết quả dạng PDF

---

## 🎨 Workspace (Canvas Mode)

Chế độ Workspace biến Chat UI thành một IDE nhỏ gọn.

Kích hoạt bằng nút **Workspace** trong input area.

### Tính năng:
- AI tự động tạo file code trong workspace
- Xem preview HTML/CSS/JS trực tiếp
- Chỉnh sửa code với AI hỗ trợ (dùng `code_patch` thay vì ghi lại toàn bộ file)
- Quản lý nhiều file cùng lúc
- Download toàn bộ workspace

### AI sẽ tự động:
- Dùng `<code_container filename="...">` để tạo file mới
- Dùng `<code_patch filename="...">` để chỉnh sửa từng phần (tiết kiệm tokens)

---

## 💻 Ví dụ tích hợp

### Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-your-api-key",
    base_url="http://localhost:8000/v1"
)

response = client.chat.completions.create(
    model="gemini-3.5-flash",
    messages=[
        {"role": "system", "content": "Bạn là trợ lý lập trình chuyên nghiệp."},
        {"role": "user", "content": "Viết hàm Fibonacci bằng Python"}
    ]
)

print(response.choices[0].message.content)
```

### Python Streaming

```python
stream = client.chat.completions.create(
    model="gemini-3.5-flash",
    messages=[{"role": "user", "content": "Giải thích về AI"}],
    stream=True
)

for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

### JavaScript / Node.js

```javascript
import OpenAI from "openai";

const client = new OpenAI({
  apiKey: "sk-your-api-key",
  baseURL: "http://localhost:8000/v1",
});

const stream = await client.chat.completions.create({
  model: "gemini-3.5-flash",
  messages: [{ role: "user", content: "Hello!" }],
  stream: true,
});

for await (const chunk of stream) {
  process.stdout.write(chunk.choices[0]?.delta?.content || "");
}
```

### cURL

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-api-key" \
  -d '{
    "model": "gemini-3.5-flash",
    "messages": [{"role": "user", "content": "Xin chào!"}],
    "stream": false
  }'
```

---

## 📁 Định dạng file được hỗ trợ

| Loại | Định dạng |
|------|-----------|
| 🖼️ **Ảnh** | `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.bmp`, `.svg`, `.heic`, `.avif` |
| 🎥 **Video** | `.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`, `.m4v` |
| 🎵 **Audio** | `.mp3`, `.wav`, `.ogg`, `.flac`, `.m4a`, `.aac` |
| 📄 **Text** | `.txt`, `.log`, `.ini`, `.cfg`, `.md` |
| 📊 **Spreadsheet** | `.xls`, `.xlsx`, `.csv`, `.ods` |
| 📘 **Word** | `.doc`, `.docx`, `.odt`, `.rtf` |
| 📕 **PDF** | `.pdf` |
| 📽️ **Presentation** | `.ppt`, `.pptx`, `.odp` |
| 💻 **Code** | `.py`, `.js`, `.ts`, `.jsx`, `.tsx`, `.java`, `.go`, `.rs`, `.php`, `.html`, `.css`, `.json`, `.yaml`, `.sql` |
| 📦 **Archive** | `.zip`, `.tar`, `.gz`, `.7z`, `.rar` |

---

## 📂 Cấu trúc dự án

```
Gemini-Chat-API/
├── 📄 main.py              # Entry point: khởi động server + bot
├── 📄 api.py               # FastAPI routes và xử lý request
├── 📄 database.py          # SQLite CRUD: keys, cookies, sessions
├── 📄 admin_bot.py         # Telegram admin bot
├── 📄 index.html           # Chat UI (single-file SPA)
├── 📄 requirements.txt     # Python dependencies
├── 📄 Dockerfile           # Container config
├── 📄 .env                 # Environment variables (không commit!)
├── 📄 cookies.json         # Google cookies (không commit!)
│
├── 📁 static/
│   └── 📄 dashboard.html   # Admin Dashboard UI
│
├── 📁 gemini_client/       # Gemini API client
│   ├── 📄 core.py          # AsyncChatbot: kết nối và chat
│   ├── 📄 enums.py         # Model definitions
│   ├── 📄 constants.py     # API endpoints, headers
│   ├── 📄 images.py        # Image processing
│   ├── 📄 cookie_manager.py# Cookie utilities
│   └── 📄 utils.py         # Helper functions
│
└── 📁 data/
    └── 📄 database.db      # SQLite database (auto-generated)
```

---

## 🔒 Bảo mật

- **Không commit** file `.env` và `cookies.json` lên GitHub
- **Đổi Admin Key** mặc định (`123456789`) ngay sau khi setup
- **Rotate cookies** định kỳ (1-7 ngày)
- **Giới hạn rate** theo API key để tránh lạm dụng
- **HTTPS** khi deploy production (Render tự động có SSL)

File `.gitignore` đã bao gồm:
```
.env
cookies.json
data/
*.db
```

---

## ⚠️ Lưu ý quan trọng

1. **Cookie hết hạn**: Google cookies thường hết hạn sau vài ngày. Cần cập nhật thường xuyên. Admin Dashboard sẽ hiển thị banner cảnh báo đỏ khi cần.

2. **Rate Limiting của Google**: Google có thể giới hạn số request. Khuyến nghị không dùng quá nhiều trong thời gian ngắn.

3. **Unofficial project**: Đây không phải API chính thức của Google. Gemini có thể thay đổi backend bất kỳ lúc nào.

4. **Chỉ dùng cá nhân**: Không nên dùng cho production scale lớn.

5. **Cookie là nhạy cảm**: Không chia sẻ cookie của bạn với người khác. Cookie cung cấp quyền truy cập vào tài khoản Google của bạn.

---

## 🔧 Troubleshooting

### Server khởi động nhưng không chat được
→ Kiểm tra cookies: Vào Admin Dashboard, xem trạng thái cookie

### Lỗi `SNlM0e not found`  
→ Cookie đã hết hạn. Cần cập nhật `__Secure-1PSID` và `__Secure-1PSIDTS`

### Model dropdown trống
→ Nhập API Key và nhấn nút refresh (🔄) trong header

### Chat gửi nhưng không có response
→ Kiểm tra API Key có đúng không, kiểm tra console browser (F12)

### Telegram Bot không phản hồi
→ Kiểm tra `TELEGRAM_BOT_TOKEN` và `ADMIN_ID` trong `.env`

---

## 📜 License

MIT License — Xem file [LICENSE](LICENSE) để biết thêm chi tiết.

---

<div align="center">

Made with ❤️ by **[TranDangKhoaTechnology](https://github.com/TranDangKhoaTechnology)**

*Gemini Nexus — AI thế hệ mới, không giới hạn*

</div>
