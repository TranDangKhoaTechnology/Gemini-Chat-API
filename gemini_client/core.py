# -*- coding: utf-8 -*-
#########################################
# Code Modified to use curl_cffi & robust text extraction with Delta Streaming
# Upgraded with Dynamic File Upload Support (Multiple Files + Auto Type Detection)
# FIXED: Increased timeout to 120s to support slow/heavy Pro models in Canvas Mode
# UPGRADED: Highly Optimized, Lightning Fast Thought Extraction (O(1) Lookups)
# UPGRADED: Removed Recursive Loop Bottlenecks for True Real-Time Delta Streaming
# FIXED: UnboundLocalError for 're' module by fixing import scoping
# FIXED & UPGRADED: Single-Pass Iterative Media Extractor (Restores Images instantly)
#########################################
import asyncio
import json
import os
import random
import re
import string
import mimetypes
import base64
import html
import uuid
import urllib.parse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Union, Optional, AsyncGenerator

from gemini_client.enums import Endpoint, Headers, Model
from gemini_client.cookie_manager import CookieExtractor
# Use curl_cffi for requests
from curl_cffi import CurlError
from curl_cffi.requests import AsyncSession
# Import common request exceptions (curl_cffi often wraps these)
from requests.exceptions import RequestException, Timeout, HTTPError

from pydantic import BaseModel, field_validator

from rich.console import Console
from rich.markdown import Markdown

console = Console()

from gemini_client.utils import upload_file, load_cookies
from gemini_client.images import Image 

# --- PRE-COMPILED REGEXES FOR LIGHTNING FAST PARSING ---
YOUTUBE_RE_1 = re.compile(r'!?\[[^\]]*\]\((?:https?://)?(?:[^)]*?)googleusercontent\.com/youtube_content/[^)]+\)')
YOUTUBE_RE_2 = re.compile(r'(?:https?://)?(?:[^)\s]*?)googleusercontent\.com/youtube_content/\S+')
IMAGE_RE_1 = re.compile(r'!?\[[^\]]*\]\((?:https?://)?(?:[^)]*?)googleusercontent\.com/image_(?:collection|generation_content)/[^)]+\)')
IMAGE_RE_2 = re.compile(r'(?:https?://)?(?:[^)\s]*?)googleusercontent\.com/image_(?:collection|generation_content)/\S+')
VIDEO_CHIP_RE_1 = re.compile(r'!?\[[^\]]*\]\((?:https?://)?(?:[^)]*?)googleusercontent\.com/video_gen_chip/[^)]+\)')
VIDEO_CHIP_RE_2 = re.compile(r'(?:https?://)?(?:[^)\s]*?)googleusercontent\.com/video_gen_chip/\S+')
GENERATED_VIDEO_RE_1 = re.compile(r'!?\[[^\]]*\]\((?:https?://)?(?:[^)]*?)googleusercontent\.com/generated_video_content/[^)]+\)')
GENERATED_VIDEO_RE_2 = re.compile(r'(?:https?://)?(?:[^)\s]*?)googleusercontent\.com/generated_video_content/\S+')
GEMINI_DOWNLOAD_RE = re.compile(r'(?:https://(?:contribution\.usercontent\.google\.com|gemini\.google\.com))?(?:/[^\s"\'<>\\)]*)?download\?c=[^\s"\'<>\\)]+')
IMAGE_URL_RE = re.compile(r'(https?://[^\s]+\.(?:jpg|jpeg|png|gif|webp))')
B64_EXTREME_RE = re.compile(b'[\x20-\x7e\n\r]{30,}')

def detect_attachment_info(file_input: Union[bytes, str, Path], default_filename: str = "upload.txt") -> Tuple[str, int, str]:
    """
    Dynamically detects the MIME type, the proper Gemini Type ID (Flag), and the filename.
    Based on reverse-engineered Gemini frontend payloads.
    """
    mime_type = "application/octet-stream"
    filename = default_filename
    
    # Analyze raw bytes (Magic Number Guessing)
    if isinstance(file_input, bytes):
        if file_input.startswith(b'\x89PNG\r\n\x1a\n'):
            mime_type, filename = "image/png", "upload.png"
        elif file_input.startswith(b'\xff\xd8\xff'):
            mime_type, filename = "image/jpeg", "upload.jpg"
        elif file_input.startswith(b'GIF87a') or file_input.startswith(b'GIF89a'):
            mime_type, filename = "image/gif", "upload.gif"
        elif file_input.startswith(b'RIFF'):
            mime_type, filename = "image/webp", "upload.webp"
        elif file_input.startswith(b'%PDF-'):
            mime_type, filename = "application/pdf", "document.pdf"
        elif file_input.startswith(b'PK\x03\x04'):
            mime_type, filename = "application/zip", "archive.zip"
        else:
            try:
                file_input.decode('utf-8')
                mime_type, filename = "text/plain", "document.txt"
            except UnicodeDecodeError:
                mime_type, filename = "application/octet-stream", "file.bin"
    else:
        filepath = Path(file_input)
        filename = filepath.name
        guessed_mime, _ = mimetypes.guess_type(str(filepath))
        
        if guessed_mime:
            mime_type = guessed_mime
        else:
            ext = filepath.suffix.lower()
            custom_mimes = {
                '.ts': 'application/typescript',
                '.tsx': 'text/tsx',
                '.jsx': 'text/jsx',
                '.kt': 'text/x-kotlin',
                '.md': 'text/markdown',
                '.m3u': 'application/octet-stream'
            }
            mime_type = custom_mimes.get(ext, "application/octet-stream")
            
    if mime_type.startswith("image/"): gemini_type_id = 1
    elif mime_type.startswith("video/"): gemini_type_id = 2
    elif mime_type == "text/plain": gemini_type_id = 3
    elif mime_type in ["application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "text/csv"]: gemini_type_id = 7
    elif mime_type in ["application/zip", "application/x-tar", "application/gzip", "application/x-bzip2"]: gemini_type_id = 9
    elif mime_type == "application/pdf": gemini_type_id = 11
    elif mime_type.startswith("text/") or mime_type in ["application/json", "application/typescript", "application/xml"]: gemini_type_id = 16
    else: gemini_type_id = 0 
        
    return mime_type, gemini_type_id, filename

# --- HIGHLY OPTIMIZED EXTRACTION HELPERS ---
def _fast_extract_text(item):
    """O(N) Fast recursive string concatenator for the main text body."""
    if isinstance(item, str): return item
    if isinstance(item, list): return "".join(_fast_extract_text(x) for x in item if x is not None)
    return str(item) if item is not None else ""

def _fast_extract_thought(body, main_content=""):
    """O(1) to shallow O(K) lookup to instantly find the thinking block."""
    if len(body) > 4 and isinstance(body[4], list) and len(body[4]) > 0:
        cand = body[4][0]
        if isinstance(cand, list):
            for idx in (131, 136, 137, 34, 37):
                if len(cand) > idx and cand[idx]:
                    val = cand[idx]
                    if isinstance(val, list) and len(val) > 0:
                        if isinstance(val[0], str): return val[0]
                        if isinstance(val[0], list) and len(val[0]) > 0 and isinstance(val[0][0], str): return val[0][0]
                        if len(val) > 6 and isinstance(val[6], list) and len(val[6]) > 0 and isinstance(val[6][0], str): return val[6][0]

            for i, item in enumerate(cand):
                if i in (1, 2): continue 
                if isinstance(item, list) and len(item) > 0:
                    s = item[0]
                    if isinstance(s, list) and len(s) > 0: s = s[0]
                    if isinstance(s, str) and len(s) > 3: 
                        if s != main_content and s != main_content + "\n" and " " in s:
                            if not s.startswith(("c_", "r_", "rc_", "cs_")):
                                return s

    for idx in (34, 37, 131, 136, 137):
         if len(body) > idx and body[idx]:
              val = body[idx]
              if isinstance(val, list) and len(val) > 0:
                   if isinstance(val[0], str): return val[0]
                   if isinstance(val[0], list) and len(val[0]) > 0 and isinstance(val[0][0], str): return val[0][0]
    return ""

def _strip_internal_media_chips(content: str) -> str:
    """Remove Gemini's internal media chip URLs from assistant text."""
    if not content:
        return ""
    for pattern in (
        YOUTUBE_RE_1, YOUTUBE_RE_2,
        IMAGE_RE_1, IMAGE_RE_2,
        VIDEO_CHIP_RE_1, VIDEO_CHIP_RE_2,
        GENERATED_VIDEO_RE_1, GENERATED_VIDEO_RE_2,
    ):
        content = pattern.sub('', content)
    return content.strip()

def _normalize_gemini_download_url(url: str) -> str:
    if not url:
        return ""
    url = html.unescape(str(url))
    url = (
        url.replace("\\u003d", "=")
           .replace("\\u0026", "&")
           .replace("\\/", "/")
           .strip(" \t\r\n\"'<>),;")
    )
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/download?"):
        url = "https://contribution.usercontent.google.com" + url
    elif url.startswith("download?"):
        url = "https://contribution.usercontent.google.com/" + url
    return url

def _is_video_download_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)
    filenames = params.get("filename") or params.get("name") or []
    filename = filenames[0].lower() if filenames else ""
    return filename.endswith((".mp4", ".webm", ".ogg", ".mov")) or ("download?c=" in url and not filename)

def _extract_gemini_download_videos(text: str) -> List[dict]:
    videos = []
    seen = set()
    if not text:
        return videos
    normalized = _normalize_gemini_download_url(text)
    for match in GEMINI_DOWNLOAD_RE.finditer(normalized):
        url = _normalize_gemini_download_url(match.group(0))
        if not url or url in seen or not _is_video_download_url(url):
            continue
        seen.add(url)
        videos.append({
            "video_id": "gen-" + uuid.uuid5(uuid.NAMESPACE_URL, url).hex,
            "title": "Generated Video",
            "url": url,
            "is_generated": True,
        })
    return videos

def _fast_extract_media(body):
    """
    O(N) Single-pass stack-based iterative traverser.
    Extracts ALL images, videos, sources, and files in a single sweep without recursion limits.
    Extremely fast and perfectly accurate for deep JSON structures.
    """
    images_raw = []
    videos = []
    sources = []
    files = []
    
    seen_img, seen_vid, seen_src, seen_file = set(), set(), set(), set()
    stack = [body]
    
    while stack:
        curr = stack.pop()
        
        if isinstance(curr, list):
            if len(curr) >= 2 and isinstance(curr[0], str):
                url = curr[0]
                if url.startswith("http") and not any(x in url for x in ["googleusercontent.com", "youtube.com", "youtu.be", "gstatic.com"]):
                    title = curr[3] if len(curr) >= 4 and isinstance(curr[3], str) else (curr[1] if isinstance(curr[1], str) else url)
                    snippet = ""
                    if len(curr) >= 5 and isinstance(curr[4], list) and len(curr[4]) > 0 and isinstance(curr[4][0], list) and len(curr[4][0]) > 0 and isinstance(curr[4][0][0], str):
                        snippet = curr[4][0][0]
                    if url not in seen_src or snippet:
                        seen_src.add(url)
                        sources.append({"url": url, "title": title, "snippet": snippet})
            # Extend queue
            for item in reversed(curr):
                if isinstance(item, (list, dict, str)):
                    stack.append(item)
                    
        elif isinstance(curr, dict):
            url = curr.get("url") or curr.get("uri") or curr.get("link")
            if isinstance(url, str) and ("youtube.com/watch" in url or "youtu.be/" in url):
                match = re.search(r'(?:v=|youtu\.be/)([\w-]+)', url)
                if match:
                    vid_id = match.group(1)
                    if vid_id not in seen_vid:
                        seen_vid.add(vid_id)
                        videos.append({
                            "video_id": vid_id, "title": curr.get("title", "YouTube Video"),
                            "channel": curr.get("author") or curr.get("channel", "YouTube"),
                            "thumbnail": f"https://img.youtube.com/vi/{vid_id}/maxresdefault.jpg", "url": url
                        })
            for val in curr.values():
                if isinstance(val, (list, dict, str)):
                    stack.append(val)
                    
        elif isinstance(curr, str):
            if "download?c=" in curr:
                for vid in _extract_gemini_download_videos(curr):
                    vid_key = vid["url"]
                    if vid_key not in seen_vid:
                        seen_vid.add(vid_key)
                        videos.append(vid)
            if curr.startswith(("https://lh3.googleusercontent.com/", "https://encrypted-tbn")):
                if curr not in seen_img:
                    seen_img.add(curr)
                    images_raw.append(curr)
            elif "contribution.usercontent.google.com/download" in curr:
                url = _normalize_gemini_download_url(curr)
                if _is_video_download_url(url):
                    if url not in seen_vid:
                        seen_vid.add(url)
                        videos.append({
                            "video_id": "gen-" + uuid.uuid5(uuid.NAMESPACE_URL, url).hex,
                            "title": "Generated Video",
                            "url": url,
                            "is_generated": True,
                        })
                elif url not in seen_file:
                    seen_file.add(url)
                    match = re.search(r'filename=([^&]+)', url)
                    filename = urllib.parse.unquote(match.group(1)) if match else "generated_document.pdf"
                    files.append({"filename": filename, "download_url": url})

    return images_raw, videos, sources, files

class Chatbot:
    """Synchronous wrapper for the AsyncChatbot class."""
    def __init__(
        self, cookie_path: str, auto_cookie: bool = False, proxy: Optional[Union[str, Dict[str, str]]] = None,
        timeout: int = 120, model: Model = Model.UNSPECIFIED, impersonate: str = "chrome110"
    ):
        try: self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
        if auto_cookie:
            extractor = CookieExtractor()
            cookie_data = extractor.extract_cookies(save_to_disk=False)
            self.secure_1psid , self.secure_1psidts = cookie_data['__Secure-1PSID'], cookie_data['__Secure-1PSIDTS']
        else:
            self.secure_1psid, self.secure_1psidts = load_cookies(cookie_path)
            
        self.async_chatbot = self.loop.run_until_complete(AsyncChatbot.create(self.secure_1psid, self.secure_1psidts, proxy, timeout, model, impersonate))

    def save_conversation(self, file_path: str, conversation_name: str):
        return self.loop.run_until_complete(self.async_chatbot.save_conversation(file_path, conversation_name))

    def load_conversations(self, file_path: str) -> List[Dict]:
        return self.loop.run_until_complete(self.async_chatbot.load_conversations(file_path))

    def load_conversation(self, file_path: str, conversation_name: str) -> bool:
        return self.loop.run_until_complete(self.async_chatbot.load_conversation(file_path, conversation_name))

    def ask(self, message: str, files: Optional[List[Union[bytes, str, Path]]] = None, attachment: Optional[Union[bytes, str, Path]] = None, image: Optional[Union[bytes, str, Path]] = None) -> dict: 
        return self.loop.run_until_complete(self.async_chatbot.ask(message, files=files, attachment=attachment, image=image))

    def ask_stream(self, message: str, files: Optional[List[Union[bytes, str, Path]]] = None, attachment: Optional[Union[bytes, str, Path]] = None, image: Optional[Union[bytes, str, Path]] = None):
        gen = self.async_chatbot.ask_stream(message, files=files, attachment=attachment, image=image)
        while True:
            try: yield self.loop.run_until_complete(gen.__anext__())
            except StopAsyncIteration: break

class AsyncChatbot:
    """Asynchronous chatbot client for interacting with Google Gemini using curl_cffi."""
    __slots__ = [
        "headers", "_reqid", "SNlM0e", "PI9WOb", "conversation_id", "response_id",
        "choice_id", "proxy", "proxies_dict", "secure_1psidts", "secure_1psid",
        "session", "timeout", "model", "impersonate",
    ]

    def __init__(
        self, secure_1psid: str, secure_1psidts: str, proxy: Optional[Union[str, Dict[str, str]]] = None,
        timeout: int = 120, model: Model = Model.UNSPECIFIED, impersonate: str = "chrome110",
    ):
        headers = Headers.GEMINI.value.copy()
        if model != Model.UNSPECIFIED: headers.update(model.model_header)

        self._reqid = int("".join(random.choices(string.digits, k=7))) 
        self.proxy = proxy 
        self.impersonate = impersonate 

        self.proxies_dict = None
        if isinstance(proxy, str): self.proxies_dict = {"http": proxy, "https": proxy}
        elif isinstance(proxy, dict): self.proxies_dict = proxy 

        self.conversation_id, self.response_id, self.choice_id = "", "", ""
        self.secure_1psid, self.secure_1psidts = secure_1psid, secure_1psidts

        cookie_dict = {"__Secure-1PSID": secure_1psid}
        if secure_1psidts: cookie_dict["__Secure-1PSIDTS"] = secure_1psidts

        self.session = AsyncSession(headers=headers, cookies=cookie_dict, proxies=self.proxies_dict, timeout=timeout, impersonate=self.impersonate)
        self.timeout, self.model = timeout, model
        self.SNlM0e, self.PI9WOb = None, None

    @classmethod
    async def create(cls, secure_1psid: str, secure_1psidts: str, proxy: Optional[Union[str, Dict[str, str]]] = None, timeout: int = 120, model: Model = Model.UNSPECIFIED, impersonate: str = "chrome110") -> "AsyncChatbot":
        instance = cls(secure_1psid, secure_1psidts, proxy, timeout, model, impersonate)
        try:
            instance.SNlM0e = await instance.__get_snlm0e()
        except Exception as e:
             console.log(f"[red]Error during AsyncChatbot initialization: {e}[/red]", style="bold red")
             await instance.session.close() 
             raise 
        return instance

    async def save_conversation(self, file_path: str, conversation_name: str) -> None:
        conversations = await self.load_conversations(file_path)
        conversation_data = {
            "conversation_name": conversation_name, "_reqid": self._reqid, "conversation_id": self.conversation_id,
            "response_id": self.response_id, "choice_id": self.choice_id, "SNlM0e": self.SNlM0e,
            "model_name": self.model.model_name, "timestamp": datetime.now().isoformat(), 
        }

        found = False
        for i, conv in enumerate(conversations):
            if conv.get("conversation_name") == conversation_name:
                conversations[i] = conversation_data 
                found = True
                break
        if not found: conversations.append(conversation_data) 

        try:
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(conversations, f, indent=4, ensure_ascii=False)
        except IOError as e:
            console.log(f"[red]Error saving conversation to {file_path}: {e}[/red]")
            raise

    async def load_conversations(self, file_path: str) -> List[Dict]:
        if not os.path.isfile(file_path): return []
        try:
            with open(file_path, 'r', encoding="utf-8") as f: return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            console.log(f"[red]Error loading conversations from {file_path}: {e}[/red]")
            return []

    async def load_conversation(self, file_path: str, conversation_name: str) -> bool:
        conversations = await self.load_conversations(file_path)
        for conversation in conversations:
            if conversation.get("conversation_name") == conversation_name:
                try:
                    self._reqid = conversation["_reqid"]
                    self.conversation_id = conversation["conversation_id"]
                    self.response_id = conversation["response_id"]
                    self.choice_id = conversation["choice_id"]
                    self.SNlM0e = conversation["SNlM0e"]
                    if "model_name" in conversation:
                         try:
                              self.model = Model.from_name(conversation["model_name"])
                              self.session.headers.update(self.model.model_header)
                         except ValueError as e: pass
                    console.log(f"Loaded conversation '{conversation_name}'")
                    return True
                except KeyError as e: return False
        return False

    async def __get_snlm0e(self):
        if not self.secure_1psid: raise ValueError("__Secure-1PSID cookie is required.")

        try:
            resp = await self.session.get(Endpoint.INIT.value, timeout=self.timeout)
            resp.raise_for_status() 

            if "Sign in to continue" in resp.text or "accounts.google.com" in str(resp.url):
                raise PermissionError("Authentication failed. Cookies might be invalid or expired.")

            snlm0e_match = (
                re.search(r"""["']SNlM0e["']\s*:\s*["'](.*?)["']""", resp.text)
                or re.search(r"""SNlM0e\\?"?\s*:\s*\\?"([^"\\]+)""", resp.text)
            )
            pi9wob_match = (
                re.search(r"""["']PI9WOb["']\s*:\s*["'](.*?)["']""", resp.text)
                or re.search(r"""PI9WOb\\?"?\s*:\s*\\?"([^"\\]+)""", resp.text)
            )

            if not pi9wob_match: raise ValueError("PI9WOb token not found")
            self.PI9WOb = pi9wob_match.group(1)

            if not snlm0e_match:
                raise ValueError("SNlM0e value not found in response. Check cookie validity and network.")

            if not self.secure_1psidts and "PSIDTS" not in self.session.cookies:
                try: await self.__rotate_cookies()
                except Exception: pass

            return snlm0e_match.group(1)

        except Timeout as e: raise TimeoutError(f"Request timed out while fetching SNlM0e: {e}") from e
        except (RequestException, CurlError) as e: raise ConnectionError(f"Network error while fetching SNlM0e: {e}") from e
        except HTTPError as e: 
            if e.response.status_code in [401, 403]: raise PermissionError(f"Authentication failed (status {e.response.status_code}). Check cookies. {e}") from e
            else: raise Exception(f"HTTP error {e.response.status_code} while fetching SNlM0e: {e}") from e

    async def __rotate_cookies(self):
        try:
            response = await self.session.post(Endpoint.ROTATE_COOKIES.value, headers=Headers.ROTATE_COOKIES.value, data='[000,"-0000000000000000000"]', timeout=self.timeout)
            response.raise_for_status()

            if new_1psidts := response.cookies.get("__Secure-1PSIDTS"):
                self.secure_1psidts = new_1psidts
                self.session.cookies.set("__Secure-1PSIDTS", new_1psidts)
                return new_1psidts
        except Exception: raise

    async def ask_stream(self, message: str, files: Optional[List[Union[bytes, str, Path]]] = None, attachment: Optional[Union[bytes, str, Path]] = None, image: Optional[Union[bytes, str, Path]] = None) -> AsyncGenerator[dict, None]:
        if self.SNlM0e is None: raise RuntimeError("AsyncChatbot not properly initialized. Call AsyncChatbot.create()")

        params = {"bl": "boq_assistant-bard-web-server_20240625.13_p0", "_reqid": str(self._reqid), "rt": "c"}

        all_files = []
        if files:
            if isinstance(files, list): all_files.extend(files)
            else: all_files.append(files)
        if attachment: all_files.append(attachment)
        if image: all_files.append(image)

        uploaded_files_array = []
        if all_files:
            for file_input in all_files:
                try:
                    upload_id = await upload_file(file_input, proxy=self.proxies_dict, impersonate=self.impersonate)
                    mime_type, gemini_type_id, filename = detect_attachment_info(file_input)
                    uploaded_files_array.append([[upload_id, gemini_type_id, None, mime_type], filename])
                except Exception as e:
                    yield {"content": f"Error uploading file: {e}", "chunk": f"Error uploading file: {e}", "error": True}
                    return

        conversation_state = [self.conversation_id or "", self.response_id or "", self.choice_id or "", None, None, None, None, None, None, ""]
        message_struct = [message, 0, None, uploaded_files_array if uploaded_files_array else None, None, None, 0]
        request_payload = [message_struct, ["en"], conversation_state, self.PI9WOb]
        data = {"f.req": json.dumps([None, json.dumps(request_payload, separators=(",", ":"))], separators=(",", ":")), "at": self.SNlM0e}

        try:
            resp = await self.session.post(Endpoint.GENERATE.value, params=params, data=data, timeout=self.timeout, stream=True)
            resp.raise_for_status()

            prev_content_length = 0
            previous_thought = ""
            thought_started = False
            thought_ended = False
            full_streamed_text = ""

            async for line in resp.aiter_lines():
                if isinstance(line, bytes): line = line.decode('utf-8', errors='ignore')

                if not line or line == ")]}'": continue
                if line.startswith(")]}"): line = line[4:].strip()
                if not line.startswith("["): continue

                try:
                    response_json = json.loads(line)
                    for part in response_json:
                        if isinstance(part, list) and len(part) > 2 and part[0] == "wrb.fr":
                            inner_json_str = part[2]
                            if isinstance(inner_json_str, str):
                                body = json.loads(inner_json_str)
                                if body and len(body) > 4 and body[4]:
                                    
                                    content = ""
                                    if len(body[4]) > 0 and len(body[4][0]) > 1:
                                        content = _fast_extract_text(body[4][0][1])

                                    current_thought = _fast_extract_thought(body, content)

                                    # Fast Media Extraction (Single-Pass O(N))
                                    images_raw, videos, sources, ext_files = _fast_extract_media(body)
                                    images = [Image(url=u, title=f"Image {i+1}", alt="", proxy=self.proxies_dict, impersonate=self.impersonate) for i, u in enumerate(images_raw)]

                                    content = _strip_internal_media_chips(content)
                                    
                                    if not images and content:
                                        for i, url in enumerate(IMAGE_URL_RE.findall(content.lower())):
                                             images.append(Image(url=url, title=f"Image in Content {i+1}", alt="", proxy=self.proxies_dict, impersonate=self.impersonate))

                                    conversation_id = body[1][0] if len(body) > 1 and len(body[1]) > 0 else self.conversation_id
                                    response_id = body[1][1] if len(body) > 1 and len(body[1]) > 1 else self.response_id
                                    
                                    choices = []
                                    if len(body) > 4:
                                        for candidate in body[4]:
                                            if len(candidate) > 1 and isinstance(candidate[1], list) and len(candidate[1]) > 0:
                                                choices.append({"id": candidate[0], "content": candidate[1][0]})
                                    choice_id = choices[0]["id"] if choices else self.choice_id

                                    self.conversation_id, self.response_id, self.choice_id = conversation_id, response_id, choice_id

                                    chunk_to_yield = ""
                                    
                                    if current_thought and current_thought != previous_thought:
                                        if current_thought.startswith(previous_thought): thought_diff = current_thought[len(previous_thought):]
                                        else: thought_diff = current_thought
                                        previous_thought = current_thought
                                        if not thought_started:
                                            chunk_to_yield += "<think>\n"
                                            thought_started = True
                                        chunk_to_yield += thought_diff

                                    chunk_delta = content[prev_content_length:]
                                    prev_content_length = len(content)

                                    if chunk_delta:
                                        if thought_started and not thought_ended:
                                            chunk_to_yield += "\n</think>\n\n"
                                            thought_ended = True
                                        chunk_to_yield += chunk_delta
                                        
                                    full_streamed_text += chunk_to_yield

                                    if chunk_to_yield or images or videos or sources or ext_files:
                                        yield {
                                            "content": full_streamed_text, "chunk": chunk_to_yield,       
                                            "conversation_id": conversation_id, "response_id": response_id, "choice_id": choice_id,
                                            "images": images, "videos": videos, "sources": sources, "files": ext_files, "error": False,
                                        }
                except json.JSONDecodeError: continue

            self._reqid += random.randint(1000, 9000)

        except Exception as e:
            yield {"content": f"Streaming error: {e}", "chunk": f"Streaming error: {e}", "error": True}

    async def wait_for_generated_videos(
        self,
        timeout_seconds: int = 240,
        poll_interval: int = 5,
        exclude_urls: Optional[set] = None,
    ) -> List[dict]:
        if not self.conversation_id:
            return []
        seen = set(exclude_urls or set())
        deadline = asyncio.get_running_loop().time() + timeout_seconds

        while asyncio.get_running_loop().time() < deadline:
            videos = await self.list_conversation_generated_videos()
            fresh = [v for v in videos if v.get("url") and v.get("url") not in seen]
            if fresh:
                return fresh
            await asyncio.sleep(poll_interval)
        return []

    async def list_conversation_generated_videos(self) -> List[dict]:
        if not self.conversation_id:
            return []

        conv_id = self.conversation_id
        app_id = conv_id[2:] if conv_id.startswith("c_") else conv_id
        rpc_id = "hNvQHb"
        payload = [f"c_{app_id}", 20, None]
        data = {
            "f.req": json.dumps(
                [[[rpc_id, json.dumps(payload, separators=(",", ":")), None, "generic"]]],
                separators=(",", ":"),
            ),
            "at": self.SNlM0e,
        }
        params = {
            "rpcids": rpc_id,
            "source-path": f"/app/{app_id}",
            "bl": "boq_assistant-bard-web-server_20240625.13_p0",
            "_reqid": str(self._reqid),
            "rt": "c",
        }

        resp = await self.session.post(
            "https://gemini.google.com/_/BardChatUi/data/batchexecute",
            params=params,
            data=data,
            timeout=min(self.timeout, 30),
        )
        resp.raise_for_status()

        videos = []
        seen = set()

        def add_video(video: dict):
            url = _normalize_gemini_download_url(video.get("url", ""))
            if not url or url in seen or not _is_video_download_url(url):
                return
            seen.add(url)
            videos.append({
                "video_id": video.get("video_id") or ("gen-" + uuid.uuid5(uuid.NAMESPACE_URL, url).hex),
                "title": video.get("title") or "Generated Video",
                "url": url,
                "is_generated": True,
            })

        for video in _extract_gemini_download_videos(resp.text):
            add_video(video)

        for line in resp.text.splitlines():
            if not line or line == ")]}'" or not line.startswith("["):
                continue
            try:
                response_json = json.loads(line)
            except json.JSONDecodeError:
                continue

            for part in response_json:
                if isinstance(part, list) and len(part) > 2 and part[0] == "wrb.fr" and isinstance(part[2], str):
                    try:
                        body = json.loads(part[2])
                    except json.JSONDecodeError:
                        continue
                    _, nested_videos, _, _ = _fast_extract_media(body)
                    for video in nested_videos:
                        if video.get("is_generated"):
                            add_video(video)

        return videos

    async def ask(self, message: str, files: Optional[List[Union[bytes, str, Path]]] = None, attachment: Optional[Union[bytes, str, Path]] = None, image: Optional[Union[bytes, str, Path]] = None) -> dict:
        if self.SNlM0e is None: raise RuntimeError("AsyncChatbot not properly initialized. Call AsyncChatbot.create()")

        params = {"bl": "boq_assistant-bard-web-server_20240625.13_p0", "_reqid": str(self._reqid), "rt": "c"}

        all_files = []
        if files:
            if isinstance(files, list): all_files.extend(files)
            else: all_files.append(files)
        if attachment: all_files.append(attachment)
        if image: all_files.append(image)

        uploaded_files_array = []
        if all_files:
            for file_input in all_files:
                try:
                    upload_id = await upload_file(file_input, proxy=self.proxies_dict, impersonate=self.impersonate)
                    mime_type, gemini_type_id, filename = detect_attachment_info(file_input)
                    uploaded_files_array.append([[upload_id, gemini_type_id, None, mime_type], filename])
                except Exception as e: return {"content": f"Error uploading attachment: {e}", "error": True}

        conversation_state = [self.conversation_id or "", self.response_id or "", self.choice_id or "", None, None, None, None, None, None, ""]
        message_struct = [message, 0, None, uploaded_files_array if uploaded_files_array else None, None, None, 0]
        request_payload = [message_struct, ["en"], conversation_state, self.PI9WOb]
        data = {"f.req": json.dumps([None, json.dumps(request_payload, separators=(",", ":"))], separators=(",", ":")), "at": self.SNlM0e}

        try:
            resp = await self.session.post(Endpoint.GENERATE.value, params=params, data=data, timeout=self.timeout)
            resp.raise_for_status()

            lines = resp.text.splitlines()
            body = None
            inner_json_str = ""
            
            for line in lines:
                if not line or line == ")]}'": continue
                if line.startswith(")]}"): line = line[4:].strip()
                if not line.startswith("["): continue
                
                try:
                    response_json = json.loads(line)
                    for part in response_json:
                        if isinstance(part, list) and len(part) > 2 and part[0] == "wrb.fr":
                            inner_json_str = part[2]
                            if isinstance(inner_json_str, str):
                                main_part = json.loads(inner_json_str)
                                if main_part and len(main_part) > 4 and main_part[4]: body = main_part
                except json.JSONDecodeError: continue

            if not body: return {"content": "Failed to parse response body. No valid data found.", "error": True}

            try:
                content = ""
                if len(body) > 4 and len(body[4]) > 0 and len(body[4][0]) > 1:
                    content = _fast_extract_text(body[4][0][1])

                current_thought = _fast_extract_thought(body, content)

                if not current_thought:
                    for match in B64_EXTREME_RE.finditer(inner_json_str.encode()):
                        try:
                            s = match.group()
                            if s.startswith(b'!O'):
                                b64 = s[2:] + b"=" * (-len(s[2:]) % 4)
                                dec = base64.urlsafe_b64decode(b64)
                                strs = re.findall(b'[\x20-\x7e\n\r]{30,}', dec)
                                if strs: 
                                    current_thought = "\n".join([x.decode('utf-8', errors='ignore') for x in strs])
                                    break
                        except: pass

                final_content = ""
                if current_thought: final_content += f"<think>\n{current_thought}\n</think>\n\n"
                
                content = _strip_internal_media_chips(content)
                final_content += content

                conversation_id = body[1][0] if len(body) > 1 and len(body[1]) > 0 else self.conversation_id
                response_id = body[1][1] if len(body) > 1 and len(body[1]) > 1 else self.response_id
                factualityQueries = body[3] if len(body) > 3 else None
                textQuery = body[2][0] if len(body) > 2 and body[2] else ""

                choices = []
                if len(body) > 4:
                    for candidate in body[4]:
                        if len(candidate) > 1 and isinstance(candidate[1], list) and len(candidate[1]) > 0:
                            choices.append({"id": candidate[0], "content": candidate[1][0]})
                choice_id = choices[0]["id"] if choices else self.choice_id

                # Single-Pass Media Extraction (Replaces 4 slow iterations)
                images_raw, videos, sources, ext_files = _fast_extract_media(body)
                images = [Image(url=u, title=f"Image {i+1}", alt="", proxy=self.proxies_dict, impersonate=self.impersonate) for i, u in enumerate(images_raw)]
                
                if not images and content:
                    for i, url in enumerate(IMAGE_URL_RE.findall(content.lower())):
                        images.append(Image(url=url, title=f"Image in Content {i+1}", alt="", proxy=self.proxies_dict, impersonate=self.impersonate))

                results = {
                    "content": final_content, "conversation_id": conversation_id, "response_id": response_id,
                    "choice_id": choice_id, "factualityQueries": factualityQueries, "textQuery": textQuery, "choices": choices,
                    "images": images, "videos": videos, "sources": sources, "files": ext_files, "error": False,
                }

                self.conversation_id, self.response_id, self.choice_id = conversation_id, response_id, choice_id
                self._reqid += random.randint(1000, 9000)
                return results

            except (IndexError, TypeError) as e: return {"content": f"Error extracting data from response: {e}", "error": True}
        except json.JSONDecodeError as e: return {"content": f"Error parsing JSON response: {e}", "error": True}
        except Timeout as e: return {"content": f"Request timed out: {e}", "error": True}
        except (RequestException, CurlError) as e: return {"content": f"Network error: {e}", "error": True}
        except HTTPError as e: return {"content": f"HTTP error {e.response.status_code}: {e}", "error": True}
        except Exception as e: return {"content": f"An unexpected error occurred: {e}", "error": True}
