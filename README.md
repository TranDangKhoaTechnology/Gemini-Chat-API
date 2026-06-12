# 💠 Gemini Nexus System

<div align="center">

# The Gemini-to-OpenAI API Proxy

### OpenAI-compatible Gemini backend with streaming, image input, API keys, and Telegram admin tools

![Python](https://img.shields.io/badge/Python-3.10+-blue?style=for-the-badge&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-API%20Server-009688?style=for-the-badge&logo=fastapi)
![Docker](https://img.shields.io/badge/Docker-Supported-2496ED?style=for-the-badge&logo=docker)
![SQLite](https://img.shields.io/badge/SQLite-Integrated-4D7A97?style=for-the-badge&logo=sqlite)
![Telegram](https://img.shields.io/badge/Telegram-Admin%20Bot-26A5E4?style=for-the-badge&logo=telegram)
![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)

</div>

---

## ✨ Overview

Gemini Nexus turns the Gemini web experience into a clean OpenAI-style API server.

It gives you:

- `/v1/models` for model discovery
- `/v1/chat/completions` for normal and streaming chat
- image input through OpenAI-style multimodal messages
- API key access control with per-key model limits
- Telegram-based admin tools for keys, cookies, and health checks
- browser cookie extraction for quick local setup
- a dark web UI for testing requests from the browser

---

## 🚀 Key Features

| Feature | What it does |
|---|---|
| 🔄 OpenAI-compatible API | Uses OpenAI request/response shapes |
| ⚡ Streaming | Returns SSE chunks with partial assistant text |
| 🖼️ Image support | Accepts `image_url` content blocks |
| 🔐 API keys | Simple bearer-token access control |
| 🧠 Model filtering | Keys can be limited to selected models |
| 🍪 Cookie sync | Loads `__Secure-1PSID` and `__Secure-1PSIDTS` |
| 🤖 Telegram admin bot | Manage keys, cookies, and sessions remotely |
| 🐳 Docker ready | Easy container deployment |
| 📁 SQLite storage | Stores cookies, keys, and session state |

---

## 🧠 How it works

```text
OpenAI Client / Web UI / Your App
            │
            ▼
      FastAPI server
  /v1/models
  /v1/chat/completions
  /v1/admin/cookie_status
  /v1/admin/cookies
            │
            ▼
      AsyncChatbot core
   cookies + tokens + model
            │
            ▼
     Gemini web endpoints
```

The backend uses `curl_cffi` with browser impersonation, so requests look like a real browser session instead of a plain Python HTTP client. The Gemini client pulls the required bootstrapping tokens from the Gemini app page before sending chat requests. fileciteturn4file14turn4file6

---

## 🧩 Supported Models

The model list is defined in `gemini_client.enums.Model`. The currently shipped model names include:

- `gemini-3.1-flash-lite`
- `gemini-3.5-flash`
- `gemini-3.1-pro`
- `gemini-3.0-flash`
- `gemini-3.0-flash-thinking` fileciteturn4file0

---

## 📂 Supported File Formats

Gemini Nexus supports dynamic multimodal file uploads using the same attachment structure used internally by the Gemini web frontend.

The backend automatically detects:

* MIME type
* Gemini attachment category
* internal upload flag
* processing pipeline

No manual extension mapping is required for most formats.

---

# 🧠 Gemini Attachment System

Each uploaded file is internally sent as:

```json
{
  "upload_id": "...",
  "mime": "...",
  "flag": ...
}
```

Where:

| Field  | Purpose                             |
| ------ | ----------------------------------- |
| `mime` | Real MIME type of the file          |
| `flag` | Internal Gemini processing category |

---

# 📦 Supported File Categories

| Category                  | Supported Extensions                                                                                                                                                                           | MIME Type                                                                                                    | Gemini Flag |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | ----------- |
| 🖼️ Images                | `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.bmp`, `.svg`, `.ico`, `.heic`, `.heif`, `.tiff`, `.avif`                                                                                           | `image/*`                                                                                                    | `1`         |
| 🎥 Videos                 | `.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`, `.m4v`                                                                                                                                                | `video/*`                                                                                                    | `2`         |
| 🎵 Audio                  | `.mp3`, `.wav`, `.ogg`, `.flac`, `.m4a`, `.aac`                                                                                                                                                | `audio/*`                                                                                                    | `3`         |
| 📄 Plain Text             | `.txt`, `.log`, `.ini`, `.cfg`                                                                                                                                                                 | `text/plain`                                                                                                 | `3`         |
| 📊 Spreadsheets           | `.xls`, `.xlsx`, `.csv`, `.ods`                                                                                                                                                                | `application/vnd.ms-excel`, `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, `text/csv`  | `7`         |
| 📦 Archives               | `.zip`, `.tar`, `.gz`, `.bz2`, `.7z`, `.rar`                                                                                                                                                   | `application/zip`, `application/x-tar`, etc                                                                  | `9`         |
| 📘 Word Documents         | `.doc`, `.docx`, `.odt`, `.rtf`                                                                                                                                                                | `application/msword`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`              | `10`        |
| 📕 PDFs                   | `.pdf`                                                                                                                                                                                         | `application/pdf`                                                                                            | `11`        |
| 📽️ Presentations         | `.ppt`, `.pptx`, `.odp`                                                                                                                                                                        | `application/vnd.ms-powerpoint`, `application/vnd.openxmlformats-officedocument.presentationml.presentation` | `12`        |
| 💻 Code & Developer Files | `.py`, `.js`, `.jsx`, `.ts`, `.tsx`, `.java`, `.kt`, `.go`, `.rs`, `.php`, `.rb`, `.swift`, `.scala`, `.sh`, `.bash`, `.zsh`, `.html`, `.css`, `.xml`, `.json`, `.yaml`, `.yml`, `.md`, `.sql` | `text/*`, `application/json`, etc                                                                            | `16`        |
| 🌐 Web & Structured Data  | `.html`, `.xml`, `.json`, `.yaml`, `.yml`, `.svg`                                                                                                                                              | `text/html`, `text/xml`, `application/json`                                                                  | `16`        |
| 🧪 Unknown Binary         | unmapped extensions, `.m3u`, custom formats                                                                                                                                                    | `application/octet-stream`                                                                                   | `0`         |

---

# 🔍 Real MIME Examples

| Extension | MIME Type                                                                   |
| --------- | --------------------------------------------------------------------------- |
| `.png`    | `image/png`                                                                 |
| `.jpg`    | `image/jpeg`                                                                |
| `.mp4`    | `video/mp4`                                                                 |
| `.mp3`    | `audio/mpeg`                                                                |
| `.txt`    | `text/plain`                                                                |
| `.pdf`    | `application/pdf`                                                           |
| `.csv`    | `text/csv`                                                                  |
| `.xls`    | `application/vnd.ms-excel`                                                  |
| `.xlsx`   | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`         |
| `.docx`   | `application/vnd.openxmlformats-officedocument.wordprocessingml.document`   |
| `.pptx`   | `application/vnd.openxmlformats-officedocument.presentationml.presentation` |
| `.json`   | `application/json`                                                          |
| `.md`     | `text/markdown`                                                             |
| `.html`   | `text/html`                                                                 |
| `.xml`    | `text/xml`                                                                  |
| `.js`     | `text/javascript`                                                           |
| `.jsx`    | `text/jsx`                                                                  |
| `.ts`     | `application/typescript`                                                    |
| `.tsx`    | `text/tsx`                                                                  |
| `.kt`     | `text/x-kotlin`                                                             |
| `.py`     | `text/x-python`                                                             |
| `.zip`    | `application/zip`                                                           |
| `.m3u`    | `application/octet-stream`                                                  |

---

# ⚡ Dynamic MIME Detection

The backend automatically detects MIME types using Python:

```python
import mimetypes

mime, _ = mimetypes.guess_type(filename)
```

This means:

* future formats automatically work
* browser-compatible MIME behavior
* no hardcoded extension lists required
* Gemini-compatible upload handling

---

# 🧠 Internal Gemini Flag Routing

Different file categories activate different Gemini processing pipelines.

| Gemini Flag | Internal Category           |
| ----------- | --------------------------- |
| `0`         | Unknown binary              |
| `1`         | Images                      |
| `2`         | Videos                      |
| `3`         | Audio / Plain text          |
| `7`         | Spreadsheets                |
| `9`         | Archives                    |
| `10`        | Word documents              |
| `11`        | PDFs                        |
| `12`        | Presentations               |
| `16`        | Code / structured documents |

---

# 🚀 Multimodal Upload Support

Gemini Nexus supports:

* image analysis
* video uploads
* PDF understanding
* spreadsheet uploads
* archive uploads
* source code uploads
* markdown and structured docs
* developer project files
* unknown binary attachments

using the same upload structure used internally by Gemini Web.

---

# 🛠️ Example Attachment Payload

```json
{
  "attachments": [
    {
      "filename": "photo.png",
      "mime": "image/png",
      "flag": 1
    },
    {
      "filename": "report.pdf",
      "mime": "application/pdf",
      "flag": 11
    },
    {
      "filename": "App.tsx",
      "mime": "text/tsx",
      "flag": 16
    }
  ]
}
```

---

# 🧩 Important Notes

* Unknown files are still accepted using:

```json
{
  "mime": "application/octet-stream",
  "flag": 0
}
```

* The backend dynamically routes uploads into Gemini processing pipelines.
* Images, videos, spreadsheets, PDFs, and developer files use different internal handling.
* The upload system closely mirrors the real Gemini frontend attachment behavior.

---


## 🔐 Authentication

Every API call uses a bearer token:

```http
Authorization: Bearer sk-xxxxxxxx
```

The token is checked against the SQLite `api_keys` table. Each key can be active or revoked, and each key can also be restricted to specific model names. Admin keys use the `role = admin` flag and unlock the cookie repair endpoints. fileciteturn4file4turn3file11turn4file11

---

## 📡 API Reference

### `GET /v1/models`

Returns the model list available to the current API key.

If the key is restricted, only allowed models are returned. The response matches the OpenAI model-list pattern:

```json
{
  "object": "list",
  "data": [
    {
      "id": "gemini-3.5-flash",
      "object": "model",
      "created": 1710000000,
      "owned_by": "google",
      "permission": [],
      "root": "gemini-3.5-flash",
      "parent": null
    }
  ]
}
```

### `POST /v1/chat/completions`

This is the main chat endpoint.

It accepts a request body like:

```json
{
  "model": "gemini-3.5-flash",
  "messages": [
    { "role": "user", "content": "Hello!" }
  ],
  "stream": false
}
```

The backend reads the last message in the conversation and forwards it to Gemini. It also supports multimodal payloads where the last message `content` is an array of blocks. If a block contains `type: "text"`, it is appended to the prompt. If a block contains `type: "image_url"` with a `data:image/...;base64,...` URL, the image is decoded and sent with the request. fileciteturn4file9turn4file12turn4file18

#### Text-only request

```json
{
  "model": "gemini-3.1-flash-lite",
  "messages": [
    {
      "role": "user",
      "content": "Write a short Python function that adds two numbers."
    }
  ]
}
```

#### Image request

```json
{
  "model": "gemini-3.5-flash",
  "messages": [
    {
      "role": "user",
      "content": [
        { "type": "text", "text": "Describe this image in detail." },
        {
          "type": "image_url",
          "image_url": {
            "url": "data:image/png;base64,AAAA..."
          }
        }
      ]
    }
  ]
}
```

#### Streaming request

Set `"stream": true` to receive Server-Sent Events. The stream sends `chat.completion.chunk` objects with partial `delta.content`, and it can also include `delta.images` when images are discovered during generation. The stream finishes with a final chunk and a `[DONE]` marker. fileciteturn4file16turn4file18

### Response shape

Non-stream responses follow the OpenAI pattern:

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1710000000,
  "model": "gemini-3.5-flash",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Answer text",
        "images": []
      },
      "finish_reason": "stop"
    }
  ]
}
```

Streaming responses use:

```text
data: {"object":"chat.completion.chunk", ...}
data: [DONE]
```

---

## 🛠️ Admin endpoints

These endpoints are protected with admin API keys.

### `GET /v1/admin/cookie_status`

Used by the extension or admin tooling to check whether cookie refresh is needed.

### `POST /v1/admin/cookies`

Accepts:

```json
{
  "psid": "value",
  "psidts": "value"
}
```

It stores the new cookies in SQLite and clears the update flag. The endpoint also notifies the Telegram admin bot when a refresh succeeds. fileciteturn4file4turn4file9turn3file11

---

## 🖼️ Image input and output

The API supports image input in the request body and image metadata in the response.

On input, send a multimodal message array with `text` and `image_url` blocks. On output, the non-streaming response includes an `images` field inside `choices[0].message`, while the streaming path can emit image entries inside `choices[0].delta`. The browser UI also shows image previews and carousels. fileciteturn4file18turn4file19turn4file8

---

## 💻 Examples

### cURL

```bash
curl http://localhost:8000/v1/chat/completions   -H "Content-Type: application/json"   -H "Authorization: Bearer sk-your-api-key"   -d '{
    "model": "gemini-3.5-flash",
    "messages": [
      {
        "role": "user",
        "content": "Explain quantum computing in one paragraph."
      }
    ]
  }'
```

### Python

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-your-api-key",
    base_url="http://localhost:8000/v1"
)

response = client.chat.completions.create(
    model="gemini-3.5-flash",
    messages=[
        {"role": "user", "content": "Write a Fibonacci script."}
    ]
)

print(response.choices[0].message.content)
```

### JavaScript

```javascript
import OpenAI from "openai";

const client = new OpenAI({
  apiKey: "sk-your-api-key",
  baseURL: "http://localhost:8000/v1",
});

const response = await client.chat.completions.create({
  model: "gemini-3.5-flash",
  messages: [
    { role: "user", content: "Hello from JavaScript" }
  ]
});

console.log(response.choices[0].message.content);
```

### Python with image input

```python
response = client.chat.completions.create(
    model="gemini-3.5-flash",
    messages=[
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What is in this image?"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64,AAAA..."
                    }
                }
            ]
        }
    ]
)
```

---

## 🚀 Quick start

### 1) Install

```bash
pip install -r requirements.txt
```

### 2) Add environment variables

```env
TELEGRAM_BOT_TOKEN=your_bot_token
ADMIN_ID=your_telegram_user_id
PORT=8000
```

### 3) Run

```bash
python main.py
```

---

## 🐳 Docker

```bash
docker build -t gemini-nexus .
docker run -d   -p 8000:8000   -v $(pwd)/data:/app/data   --env-file .env   --name gemini-nexus   gemini-nexus
```

---

## 🤖 Telegram admin commands

Common admin commands include:

- `/newkey` — create a normal API key
- `/newadminkey` — create an admin key
- `/listkeys` — list stored keys
- `/settimeout` — set key timeout
- `/revoke` — revoke a key
- `/setcookies` — update the Google cookies
- `/health` — test whether Gemini is reachable
- `/backup` — download database and session backups fileciteturn4file11turn4file17

---

## 🖥️ Web UI

The included `index.html` page gives you:

- a model dropdown
- API URL and API key inputs
- a stream toggle
- image attachment
- markdown rendering
- a clean dark chat layout

It sends requests to `/v1/models` and `/v1/chat/completions` using the same OpenAI-shaped payload format as the SDK examples. fileciteturn4file1turn4file8turn3file16

---

## 📂 Project structure

```text
.
├── admin_bot.py
├── api.py
├── database.py
├── index.html
├── main.py
├── requirements.txt
├── test.py
└── gemini_client/
    ├── __init__.py
    ├── constants.py
    ├── cookie_manager.py
    ├── core.py
    ├── enums.py
    ├── images.py
    └── utils.py
```

---

## ⚠️ Notes

- This project depends on valid Google session cookies.
- The API key system is local and SQLite-backed.
- Streaming and image handling are supported in both the backend and the browser UI.
- The project is unofficial and not affiliated with Google or OpenAI.

---

## 📜 License

MIT License.



