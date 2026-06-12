# -*- coding: utf-8 -*-
#########################################
# Code Modified to use curl_cffi & robust text extraction with Delta Streaming
# Upgraded with Dynamic File Upload Support (Multiple Files + Auto Type Detection)
# FIXED: Increased timeout to 120s to support slow/heavy Pro models in Canvas Mode
# UPGRADED: Robust Heuristic Thought Extraction for Gemini Thinking Models
# FIXED: UnboundLocalError for 're' module by fixing import scoping
# UPGRADED: Added Generated File/PDF extraction support
#########################################
import asyncio
import json
import os
import random
import re
import string
import mimetypes
import base64
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
            # Fallback for generic text files (like .py, .txt)
            try:
                file_input.decode('utf-8')
                mime_type, filename = "text/plain", "document.txt"
            except UnicodeDecodeError:
                mime_type, filename = "application/octet-stream", "file.bin"
    
    # Analyze file paths
    else:
        filepath = Path(file_input)
        filename = filepath.name
        guessed_mime, _ = mimetypes.guess_type(str(filepath))
        
        if guessed_mime:
            mime_type = guessed_mime
        else:
            # Fallbacks for specific extensions not always caught by standard mimetypes
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
            
    # Assign correct Gemini Attachment ID (Flag) dynamically based on reverse-engineered IDs
    if mime_type.startswith("image/"):
        gemini_type_id = 1
    elif mime_type.startswith("video/"):
        gemini_type_id = 2
    elif mime_type == "text/plain":
        gemini_type_id = 3
    elif mime_type in ["application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "text/csv"]:
        gemini_type_id = 7
    elif mime_type in ["application/zip", "application/x-tar", "application/gzip", "application/x-bzip2"]:
        gemini_type_id = 9
    elif mime_type == "application/pdf":
        gemini_type_id = 11
    elif mime_type.startswith("text/") or mime_type in ["application/json", "application/typescript", "application/xml"]:
        gemini_type_id = 16
    else:
        # Default for unmapped/binary files
        gemini_type_id = 0 
        
    return mime_type, gemini_type_id, filename

class Chatbot:
    """
    Synchronous wrapper for the AsyncChatbot class.
    """
    def __init__(
        self,
        cookie_path: str,
        auto_cookie: bool = False,
        proxy: Optional[Union[str, Dict[str, str]]] = None,
        timeout: int = 120, 
        model: Model = Model.UNSPECIFIED,
        impersonate: str = "chrome110"
    ):
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
        if auto_cookie:
            extractor = CookieExtractor()
            cookie_data = extractor.extract_cookies(save_to_disk=False)
            self.secure_1psid , self.secure_1psidts = cookie_data['__Secure-1PSID'], cookie_data['__Secure-1PSIDTS']
        else:
            self.secure_1psid, self.secure_1psidts = load_cookies(cookie_path)
            
        self.async_chatbot = self.loop.run_until_complete(
            AsyncChatbot.create(self.secure_1psid, self.secure_1psidts, proxy, timeout, model, impersonate)
        )

    def save_conversation(self, file_path: str, conversation_name: str):
        return self.loop.run_until_complete(
            self.async_chatbot.save_conversation(file_path, conversation_name)
        )

    def load_conversations(self, file_path: str) -> List[Dict]:
        return self.loop.run_until_complete(
            self.async_chatbot.load_conversations(file_path)
        )

    def load_conversation(self, file_path: str, conversation_name: str) -> bool:
        return self.loop.run_until_complete(
            self.async_chatbot.load_conversation(file_path, conversation_name)
        )

    def ask(self, message: str, files: Optional[List[Union[bytes, str, Path]]] = None, attachment: Optional[Union[bytes, str, Path]] = None, image: Optional[Union[bytes, str, Path]] = None) -> dict: 
        return self.loop.run_until_complete(self.async_chatbot.ask(message, files=files, attachment=attachment, image=image))

    def ask_stream(self, message: str, files: Optional[List[Union[bytes, str, Path]]] = None, attachment: Optional[Union[bytes, str, Path]] = None, image: Optional[Union[bytes, str, Path]] = None):
        """Synchronous wrapper to consume the async generator for streaming chunks."""
        gen = self.async_chatbot.ask_stream(message, files=files, attachment=attachment, image=image)
        while True:
            try:
                yield self.loop.run_until_complete(gen.__anext__())
            except StopAsyncIteration:
                break


class AsyncChatbot:
    """
    Asynchronous chatbot client for interacting with Google Gemini using curl_cffi.
    """
    __slots__ = [
        "headers",
        "_reqid",
        "SNlM0e",
        "PI9WOb",
        "conversation_id",
        "response_id",
        "choice_id",
        "proxy", 
        "proxies_dict", 
        "secure_1psidts",
        "secure_1psid",
        "session",
        "timeout",
        "model",
        "impersonate",
    ]

    def __init__(
        self,
        secure_1psid: str,
        secure_1psidts: str,
        proxy: Optional[Union[str, Dict[str, str]]] = None,
        timeout: int = 120, 
        model: Model = Model.UNSPECIFIED,
        impersonate: str = "chrome110",
    ):
        headers = Headers.GEMINI.value.copy()
        if model != Model.UNSPECIFIED:
            headers.update(model.model_header)

        self._reqid = int("".join(random.choices(string.digits, k=7))) 
        self.proxy = proxy 
        self.impersonate = impersonate 

        self.proxies_dict = None
        if isinstance(proxy, str):
            self.proxies_dict = {"http": proxy, "https": proxy}
        elif isinstance(proxy, dict):
            self.proxies_dict = proxy 

        self.conversation_id = ""
        self.response_id = ""
        self.choice_id = ""
        self.secure_1psid = secure_1psid
        self.secure_1psidts = secure_1psidts

        cookie_dict = {"__Secure-1PSID": secure_1psid}
        if secure_1psidts:
            cookie_dict["__Secure-1PSIDTS"] = secure_1psidts

        self.session = AsyncSession(
            headers=headers,
            cookies=cookie_dict,
            proxies=self.proxies_dict,
            timeout=timeout,
            impersonate=self.impersonate
        )

        self.timeout = timeout 
        self.model = model
        self.SNlM0e = None 
        self.PI9WOb = None

    @classmethod
    async def create(
        cls,
        secure_1psid: str,
        secure_1psidts: str,
        proxy: Optional[Union[str, Dict[str, str]]] = None,
        timeout: int = 120, 
        model: Model = Model.UNSPECIFIED,
        impersonate: str = "chrome110",
    ) -> "AsyncChatbot":
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
            "conversation_name": conversation_name,
            "_reqid": self._reqid,
            "conversation_id": self.conversation_id,
            "response_id": self.response_id,
            "choice_id": self.choice_id,
            "SNlM0e": self.SNlM0e,
            "model_name": self.model.model_name, 
            "timestamp": datetime.now().isoformat(), 
        }

        found = False
        for i, conv in enumerate(conversations):
            if conv.get("conversation_name") == conversation_name:
                conversations[i] = conversation_data 
                found = True
                break
        if not found:
            conversations.append(conversation_data) 

        try:
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(conversations, f, indent=4, ensure_ascii=False)
        except IOError as e:
            console.log(f"[red]Error saving conversation to {file_path}: {e}[/red]")
            raise

    async def load_conversations(self, file_path: str) -> List[Dict]:
        if not os.path.isfile(file_path):
            return []
        try:
            with open(file_path, 'r', encoding="utf-8") as f:
                return json.load(f)
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
                         except ValueError as e:
                              console.log(f"[yellow]Warning: Model '{conversation['model_name']}' from saved conversation not found. Using current model '{self.model.model_name}'. Error: {e}[/yellow]")

                    console.log(f"Loaded conversation '{conversation_name}'")
                    return True
                except KeyError as e:
                    console.log(f"[red]Error loading conversation '{conversation_name}': Missing key {e}[/red]")
                    return False
        console.log(f"[yellow]Conversation '{conversation_name}' not found in {file_path}[/yellow]")
        return False

    async def __get_snlm0e(self):
        if not self.secure_1psid:
            raise ValueError("__Secure-1PSID cookie is required.")

        try:
            resp = await self.session.get(
                Endpoint.INIT.value,
                timeout=self.timeout
            )
            resp.raise_for_status() 

            if "Sign in to continue" in resp.text or "accounts.google.com" in str(resp.url):
                raise PermissionError("Authentication failed. Cookies might be invalid or expired. Please update them.")

            snlm0e_match = re.search(r"""["']SNlM0e["']\s*:\s*["'](.*?)["']""", resp.text)
            pi9wob_match = re.search(r'"PI9WOb":"(.*?)"', resp.text)

            if not pi9wob_match:
                raise ValueError("PI9WOb token not found")
            self.PI9WOb = pi9wob_match.group(1)

            if not snlm0e_match:
                error_message = "SNlM0e value not found in response."
                if resp.status_code == 429:
                    error_message += " Rate limit likely exceeded."
                else:
                    error_message += f" Response status: {resp.status_code}. Check cookie validity and network."
                raise ValueError(error_message)

            if not self.secure_1psidts and "PSIDTS" not in self.session.cookies:
                try:
                    await self.__rotate_cookies()
                except Exception as e:
                    console.log(f"[yellow]Warning: Could not refresh PSIDTS cookie: {e}[/yellow]")

            return snlm0e_match.group(1)

        except Timeout as e: 
            raise TimeoutError(f"Request timed out while fetching SNlM0e: {e}") from e
        except (RequestException, CurlError) as e: 
            raise ConnectionError(f"Network error while fetching SNlM0e: {e}") from e
        except HTTPError as e: 
            if e.response.status_code in [401, 403]:
                raise PermissionError(f"Authentication failed (status {e.response.status_code}). Check cookies. {e}") from e
            else:
                raise Exception(f"HTTP error {e.response.status_code} while fetching SNlM0e: {e}") from e

    async def __rotate_cookies(self):
        try:
            response = await self.session.post(
                Endpoint.ROTATE_COOKIES.value,
                headers=Headers.ROTATE_COOKIES.value,
                data='[000,"-0000000000000000000"]',
                timeout=self.timeout
            )
            response.raise_for_status()

            if new_1psidts := response.cookies.get("__Secure-1PSIDTS"):
                self.secure_1psidts = new_1psidts
                self.session.cookies.set("__Secure-1PSIDTS", new_1psidts)
                return new_1psidts
        except Exception as e:
            console.log(f"[yellow]Cookie rotation failed: {e}[/yellow]")
            raise

    async def ask_stream(self, message: str, files: Optional[List[Union[bytes, str, Path]]] = None, attachment: Optional[Union[bytes, str, Path]] = None, image: Optional[Union[bytes, str, Path]] = None) -> AsyncGenerator[dict, None]:
        if self.SNlM0e is None:
            raise RuntimeError("AsyncChatbot not properly initialized. Call AsyncChatbot.create()")

        params = {
            "bl": "boq_assistant-bard-web-server_20240625.13_p0",
            "_reqid": str(self._reqid),
            "rt": "c",
        }

        # Combine all files into a unified array (backward compatible with older kwargs)
        all_files = []
        if files:
            if isinstance(files, list):
                all_files.extend(files)
            else:
                all_files.append(files)
        if attachment:
            all_files.append(attachment)
        if image:
            all_files.append(image)

        uploaded_files_array = []
        
        # Upload loop dynamically constructs the file metadata array
        if all_files:
            for file_input in all_files:
                try:
                    upload_id = await upload_file(file_input, proxy=self.proxies_dict, impersonate=self.impersonate)
                    mime_type, gemini_type_id, filename = detect_attachment_info(file_input)
                    
                    # Appending to array based on the exact reverse-engineered structure
                    uploaded_files_array.append([
                        [upload_id, gemini_type_id, None, mime_type],
                        filename
                    ])
                except Exception as e:
                    yield {"content": f"Error uploading file '{file_input}': {e}", "chunk": f"Error uploading file: {e}", "error": True}
                    return

        # Prepare Conversation State Array (Relaxed check)
        if self.conversation_id:
            conversation_state = [
                self.conversation_id,
                self.response_id or "",
                self.choice_id or "",
                None, None, None, None, None, None, ""
            ]
        else:
            conversation_state = ["", "", "", None, None, None, None, None, None, ""]

        # Safely inject the new attachments array
        if uploaded_files_array:
            message_struct = [message, 0, None, uploaded_files_array, None, None, 0]
        else:
            message_struct = [message, 0, None, None, None, None, 0]

        request_payload = [
            message_struct,
            ["en"],
            conversation_state,
            self.PI9WOb
        ]

        data = {
            "f.req": json.dumps(
                [None, json.dumps(request_payload, separators=(",", ":"))],
                separators=(",", ":")
            ),
            "at": self.SNlM0e,
        }

        try:
            resp = await self.session.post(
                Endpoint.GENERATE.value,
                params=params,
                data=data,
                timeout=self.timeout,
                stream=True,
            )
            resp.raise_for_status()

            # State Trackers for delta yielding and thoughts
            prev_content_length = 0
            previous_thought = ""
            thought_started = False
            thought_ended = False
            full_streamed_text = ""

            def iter_all_strings(obj):
                if isinstance(obj, str): yield obj
                elif isinstance(obj, list):
                    for item in obj: yield from iter_all_strings(item)
                elif isinstance(obj, dict):
                    for item in obj.values(): yield from iter_all_strings(item)

            async for line in resp.aiter_lines():
                if isinstance(line, bytes):
                    line = line.decode('utf-8', errors='ignore')

                if not line or line == ")]}'":
                    continue
                if line.startswith(")]}"):
                    line = line[4:].strip()
                if not line.startswith("["):
                    continue

                try:
                    response_json = json.loads(line)
                    for part_index, part in enumerate(response_json):
                        if isinstance(part, list) and len(part) > 2 and part[0] == "wrb.fr":
                            inner_json_str = part[2]
                            if isinstance(inner_json_str, str):
                                main_part = json.loads(inner_json_str)
                                if main_part and len(main_part) > 4 and main_part[4]:
                                    body = main_part

                                    content = ""
                                    if len(body) > 4 and len(body[4]) > 0 and len(body[4][0]) > 1:
                                        raw_content = body[4][0][1]
                                        # ROBUST TEXT EXTRACTION LOGIC
                                        def extract_text(item):
                                            if isinstance(item, str): return item
                                            if isinstance(item, list): return "".join(extract_text(x) for x in item if x is not None)
                                            return str(item) if item is not None else ""
                                        
                                        content = extract_text(raw_content)

                                    # --- UPGRADED: ROBUST THOUGHT PROCESS EXTRACTION ---
                                    current_thought = ""
                                    
                                    # 1. Targeted Search (Fast Path): Look in known Gemini thinking indices (added 37)
                                    try:
                                        for idx in [34, 37, 131, 136, 137]:
                                            candidates = [body]
                                            if len(body) > 4 and isinstance(body[4], list): candidates.append(body[4][0] if len(body[4]) > 0 and isinstance(body[4][0], list) else body[4])
                                            if len(body) > 0 and isinstance(body[0], list): candidates.append(body[0])
                                            
                                            for cand in candidates:
                                                if len(cand) > idx and cand[idx]:
                                                    val = cand[idx]
                                                    if isinstance(val, list):
                                                        if isinstance(val[0], str): current_thought = val[0]
                                                        elif isinstance(val[0], list) and isinstance(val[0][0], str): current_thought = val[0][0]
                                                        elif len(val) > 6 and isinstance(val[6], list) and isinstance(val[6][0], str): current_thought = val[6][0]
                                                    if current_thought: break
                                            if current_thought: break
                                    except Exception: pass
                                    
                                    # 2. Heuristic Search (Robust Fallback): Find large growing text blocks
                                    if not current_thought:
                                        all_strs = list(iter_all_strings(body))
                                        all_strs.sort(key=len, reverse=True)
                                        for s in all_strs:
                                            # Thoughts are large text blocks, distinct from the main text and IDs
                                            if len(s) > 30 and " " in s and not s.startswith("c_") and not s.startswith("r_") and not s.startswith("rc_"):
                                                # Ensure it's not just a duplicate of the main response
                                                if s != content and s != content + "\n":
                                                    current_thought = s
                                                    break
                                                    
                                    # 3. Base64 Protobuf Search (Extreme Fallback)
                                    if not current_thought:
                                        for item in iter_all_strings(body):
                                            if item.startswith("!O"):
                                                try:
                                                    b64 = item[1:] + "=" * (-len(item[1:]) % 4)
                                                    dec = base64.urlsafe_b64decode(b64)
                                                    strs = re.findall(b'[\x20-\x7e\n\r]{30,}', dec)
                                                    if strs: 
                                                        current_thought = "\n".join([s.decode('utf-8', errors='ignore') for s in strs])
                                                        break
                                                except: pass

                                    images = []
                                    def extract_image_urls(obj, urls=None):
                                        if urls is None: urls = []
                                        if isinstance(obj, list):
                                            for item in obj: extract_image_urls(item, urls)
                                        elif isinstance(obj, dict):
                                            for val in obj.values(): extract_image_urls(val, urls)
                                        elif isinstance(obj, str):
                                            if (obj.startswith("https://lh3.googleusercontent.com/") or obj.startswith("https://encrypted-tbn")) and obj not in urls:
                                                urls.append(obj)
                                        return urls
                                        
                                    found_urls = extract_image_urls(body)
                                    for i, url in enumerate(found_urls):
                                        img_obj = Image(
                                            url=url, 
                                            title=f"Image {i+1}",
                                            alt="",
                                            proxy=self.proxies_dict,
                                            impersonate=self.impersonate
                                        )
                                        images.append(img_obj)

                                    videos = []
                                    def extract_youtube_videos(obj, vids=None, seen=None):
                                        if vids is None: vids = []
                                        if seen is None: seen = set()
                                        if isinstance(obj, list):
                                            for item in obj: extract_youtube_videos(item, vids, seen)
                                        elif isinstance(obj, dict):
                                            url = obj.get("url") or obj.get("uri") or obj.get("link")
                                            if isinstance(url, str) and ("youtube.com/watch" in url or "youtu.be/" in url):
                                                match = re.search(r'(?:v=|youtu\.be/)([\w-]+)', url)
                                                if match:
                                                    vid_id = match.group(1)
                                                    if vid_id not in seen:
                                                        seen.add(vid_id)
                                                        vids.append({
                                                            "video_id": vid_id,
                                                            "title": obj.get("title", "YouTube Video"),
                                                            "channel": obj.get("author") or obj.get("channel", "YouTube"),
                                                            "thumbnail": f"https://img.youtube.com/vi/{vid_id}/maxresdefault.jpg",
                                                            "url": url
                                                        })
                                            for val in obj.values(): extract_youtube_videos(val, vids, seen)
                                        return vids
                                        
                                    videos = extract_youtube_videos(body)

                                    # EXTRACT GROUNDING / WEB SOURCES (NEW)
                                    sources = []
                                    def extract_web_sources(obj, srcs=None, seen=None):
                                        if srcs is None: srcs = []
                                        if seen is None: seen = set()
                                        
                                        if isinstance(obj, list):
                                            # Signature of a web link with internal text mapping
                                            if len(obj) >= 5 and isinstance(obj[0], str) and obj[0].startswith("http"):
                                                url = obj[0]
                                                if not any(x in url for x in ["googleusercontent.com", "youtube.com", "youtu.be", "gstatic.com"]):
                                                    title = obj[3] if isinstance(obj[3], str) else url
                                                    snippet = ""
                                                    try:
                                                        if isinstance(obj[4], list) and len(obj[4]) > 0 and isinstance(obj[4][0], list) and len(obj[4][0]) > 0 and isinstance(obj[4][0][0], str):
                                                            snippet = obj[4][0][0]
                                                    except:
                                                        pass
                                                        
                                                    if url not in seen or snippet:
                                                        seen.add(url)
                                                        srcs.append({"url": url, "title": title, "snippet": snippet})
                                            
                                            # Signature of a simple web link fallback
                                            elif len(obj) >= 2 and isinstance(obj[0], str) and isinstance(obj[1], str):
                                                url = obj[0]
                                                title = obj[1]
                                                if url.startswith("http") and not any(x in url for x in ["googleusercontent.com", "youtube.com", "youtu.be", "gstatic.com"]):
                                                    if url not in seen:
                                                        seen.add(url)
                                                        srcs.append({"url": url, "title": title if title else url, "snippet": ""})
                                                        
                                            for item in obj:
                                                extract_web_sources(item, srcs, seen)
                                        elif isinstance(obj, dict):
                                            for val in obj.values():
                                                extract_web_sources(val, srcs, seen)
                                        return srcs
                                    
                                    sources = extract_web_sources(body)

                                    # EXTRACT GENERATED FILES / PDFS (NEW)
                                    generated_files = []
                                    def extract_generated_docs(obj, files=None, seen=None):
                                        if files is None: files = []
                                        if seen is None: seen = set()
                                        
                                        if isinstance(obj, list):
                                            for item in obj:
                                                if isinstance(item, str) and "contribution.usercontent.google.com/download" in item:
                                                    if item not in seen:
                                                        seen.add(item)
                                                        match = re.search(r'filename=([^&]+)', item)
                                                        filename = urllib.parse.unquote(match.group(1)) if match else "generated_document.pdf"
                                                        files.append({
                                                            "filename": filename,
                                                            "download_url": item
                                                        })
                                                extract_generated_docs(item, files, seen)
                                        elif isinstance(obj, dict):
                                            for val in obj.values():
                                                extract_generated_docs(val, files, seen)
                                        return files
                                    
                                    generated_files = extract_generated_docs(body)

                                    content = re.sub(r'!?\[[^\]]*\]\((?:https?://)?(?:[^)]*?)googleusercontent\.com/youtube_content/[^)]+\)', '', content)
                                    content = re.sub(r'(?:https?://)?(?:[^)\s]*?)googleusercontent\.com/youtube_content/\S+', '', content)    

                                    content = re.sub(r'!?\[[^\]]*\]\((?:https?://)?(?:[^)]*?)googleusercontent\.com/image_(?:collection|generation_content)/[^)]+\)', '', content)
                                    content = re.sub(r'(?:https?://)?(?:[^)\s]*?)googleusercontent\.com/image_(?:collection|generation_content)/\S+', '', content)

                                    conversation_id = body[1][0] if len(body) > 1 and len(body[1]) > 0 else self.conversation_id
                                    response_id = body[1][1] if len(body) > 1 and len(body[1]) > 1 else self.response_id

                                    choices = []
                                    if len(body) > 4:
                                        for candidate in body[4]:
                                            if len(candidate) > 1 and isinstance(candidate[1], list) and len(candidate[1]) > 0:
                                                choices.append({"id": candidate[0], "content": candidate[1][0]})
                                    choice_id = choices[0]["id"] if choices else self.choice_id

                                    self.conversation_id = conversation_id
                                    self.response_id = response_id
                                    self.choice_id = choice_id

                                    # DELTA CHUNKING LOGIC FOR LIVE STREAMING
                                    chunk_to_yield = ""
                                    
                                    # Handle thought chunk building
                                    if current_thought and current_thought != previous_thought:
                                        if current_thought.startswith(previous_thought):
                                            thought_diff = current_thought[len(previous_thought):]
                                        else:
                                            thought_diff = current_thought
                                            
                                        previous_thought = current_thought
                                        
                                        if not thought_started:
                                            chunk_to_yield += "<think>\n"
                                            thought_started = True
                                            
                                        chunk_to_yield += thought_diff

                                    # Handle main content chunk building
                                    chunk_delta = content[prev_content_length:]
                                    prev_content_length = len(content)

                                    if chunk_delta:
                                        # Close the think tag immediately when the main text starts generating
                                        if thought_started and not thought_ended:
                                            chunk_to_yield += "\n</think>\n\n"
                                            thought_ended = True
                                        chunk_to_yield += chunk_delta
                                        
                                    full_streamed_text += chunk_to_yield

                                    if chunk_to_yield or images or sources or generated_files:  # Only yield if there's new data
                                        yield {
                                            "content": full_streamed_text, 
                                            "chunk": chunk_to_yield,       
                                            "conversation_id": conversation_id,
                                            "response_id": response_id,
                                            "choice_id": choice_id,
                                            "images": images,
                                            "videos": videos,
                                            "sources": sources,
                                            "files": generated_files,
                                            "error": False,
                                        }
                except json.JSONDecodeError:
                    continue

            self._reqid += random.randint(1000, 9000)

        except Exception as e:
            yield {"content": f"Streaming error: {e}", "chunk": f"Streaming error: {e}", "error": True}

    async def ask(self, message: str, files: Optional[List[Union[bytes, str, Path]]] = None, attachment: Optional[Union[bytes, str, Path]] = None, image: Optional[Union[bytes, str, Path]] = None) -> dict:
        if self.SNlM0e is None:
            raise RuntimeError("AsyncChatbot not properly initialized. Call AsyncChatbot.create()")

        params = {
            "bl": "boq_assistant-bard-web-server_20240625.13_p0",
            "_reqid": str(self._reqid),
            "rt": "c",
        }

        all_files = []
        if files:
            if isinstance(files, list):
                all_files.extend(files)
            else:
                all_files.append(files)
        if attachment:
            all_files.append(attachment)
        if image:
            all_files.append(image)

        uploaded_files_array = []
        
        if all_files:
            for file_input in all_files:
                try:
                    upload_id = await upload_file(file_input, proxy=self.proxies_dict, impersonate=self.impersonate)
                    mime_type, gemini_type_id, filename = detect_attachment_info(file_input)
                    
                    uploaded_files_array.append([
                        [upload_id, gemini_type_id, None, mime_type],
                        filename
                    ])
                    console.log(f"Attachment '{filename}' uploaded successfully. ID: {upload_id}")
                except Exception as e:
                    console.log(f"[red]Error uploading attachment '{file_input}': {e}[/red]")
                    return {"content": f"Error uploading attachment: {e}", "error": True}

        # Prepare Conversation State Array (Relaxed check)
        if self.conversation_id:
            conversation_state = [
                self.conversation_id,
                self.response_id or "",
                self.choice_id or "",
                None, None, None, None, None, None, ""
            ]
        else:
            conversation_state = ["", "", "", None, None, None, None, None, None, ""]

        if uploaded_files_array:
            message_struct = [message, 0, None, uploaded_files_array, None, None, 0]
        else:
            message_struct = [message, 0, None, None, None, None, 0]

        request_payload = [
            message_struct,
            ["en"],
            conversation_state,
            self.PI9WOb
        ]

        data = {
            "f.req": json.dumps(
                [None, json.dumps(request_payload, separators=(",", ":"))],
                separators=(",", ":")
            ),
            "at": self.SNlM0e,
        }

        try:
            resp = await self.session.post(
                Endpoint.GENERATE.value,
                params=params,
                data=data,
                timeout=self.timeout,
            )
            resp.raise_for_status()

            lines = resp.text.splitlines()
            if len(lines) < 3:
                raise ValueError(f"Unexpected response format. Status: {resp.status_code}. Content: {resp.text[:200]}...")

            body = None
            body_index = 0
            
            for line in lines:
                if not line or line == ")]}'":
                    continue
                if line.startswith(")]}"):
                    line = line[4:].strip()
                if not line.startswith("["):
                    continue
                
                try:
                    response_json = json.loads(line)
                    for part_index, part in enumerate(response_json):
                        try:
                            if isinstance(part, list) and len(part) > 2 and part[0] == "wrb.fr":
                                inner_json_str = part[2]
                                if isinstance(inner_json_str, str):
                                    main_part = json.loads(inner_json_str)
                                    if main_part and len(main_part) > 4 and main_part[4]:
                                        body = main_part
                                        body_index = part_index
                        except (IndexError, TypeError, json.JSONDecodeError):
                            continue
                except json.JSONDecodeError:
                    continue

            if not body:
                return {"content": "Failed to parse response body. No valid data found.", "error": True}

            try:
                def iter_all_strings(obj):
                    if isinstance(obj, str): yield obj
                    elif isinstance(obj, list):
                        for item in obj: yield from iter_all_strings(item)
                    elif isinstance(obj, dict):
                        for item in obj.values(): yield from iter_all_strings(item)

                content = ""
                if len(body) > 4 and len(body[4]) > 0 and len(body[4][0]) > 1:
                    raw_content = body[4][0][1]
                    
                    # ROBUST TEXT EXTRACTION LOGIC 
                    def extract_text(item):
                        if isinstance(item, str): 
                            return item
                        if isinstance(item, list): 
                            return "".join(extract_text(x) for x in item if x is not None)
                        return str(item) if item is not None else ""
                        
                    content = extract_text(raw_content)

                # --- UPGRADED: ROBUST THOUGHT PROCESS EXTRACTION (FOR NON-STREAMING) ---
                current_thought = ""
                
                try:
                    for idx in [34, 37, 131, 136, 137]:
                        candidates = [body]
                        if len(body) > 4 and isinstance(body[4], list): candidates.append(body[4][0] if len(body[4]) > 0 and isinstance(body[4][0], list) else body[4])
                        if len(body) > 0 and isinstance(body[0], list): candidates.append(body[0])
                        
                        for cand in candidates:
                            if len(cand) > idx and cand[idx]:
                                val = cand[idx]
                                if isinstance(val, list):
                                    if isinstance(val[0], str): current_thought = val[0]
                                    elif isinstance(val[0], list) and isinstance(val[0][0], str): current_thought = val[0][0]
                                    elif len(val) > 6 and isinstance(val[6], list) and isinstance(val[6][0], str): current_thought = val[6][0]
                                if current_thought: break
                        if current_thought: break
                except Exception: pass
                
                if not current_thought:
                    all_strs = list(iter_all_strings(body))
                    all_strs.sort(key=len, reverse=True)
                    for s in all_strs:
                        if len(s) > 30 and " " in s and not s.startswith("c_") and not s.startswith("r_") and not s.startswith("rc_"):
                            if s != content and s != content + "\n":
                                current_thought = s
                                break
                                
                if not current_thought:
                    for item in iter_all_strings(body):
                        if item.startswith("!O"):
                            try:
                                b64 = item[1:] + "=" * (-len(item[1:]) % 4)
                                dec = base64.urlsafe_b64decode(b64)
                                strs = re.findall(b'[\x20-\x7e\n\r]{30,}', dec)
                                if strs: 
                                    current_thought = "\n".join([s.decode('utf-8', errors='ignore') for s in strs])
                                    break
                            except: pass

                # Combine thought tags around the extracted thought for the final block
                final_content = ""
                if current_thought:
                    final_content += f"<think>\n{current_thought}\n</think>\n\n"
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

                images = []
                def extract_image_urls(obj, urls=None):
                    if urls is None: urls = []
                    if isinstance(obj, list):
                        for item in obj: extract_image_urls(item, urls)
                    elif isinstance(obj, dict):
                        for val in obj.values(): extract_image_urls(val, urls)
                    elif isinstance(obj, str):
                        if (obj.startswith("https://lh3.googleusercontent.com/") or obj.startswith("https://encrypted-tbn")) and obj not in urls:
                            urls.append(obj)
                    return urls
                    
                found_urls = extract_image_urls(body)
                for i, url in enumerate(found_urls):
                    img_obj = Image(
                        url=url, 
                        title=f"Image {i+1}", 
                        alt="",
                        proxy=self.proxies_dict,
                        impersonate=self.impersonate
                    )
                    images.append(img_obj)

                videos = []
                def extract_youtube_videos(obj, vids=None, seen=None):
                    if vids is None: vids = []
                    if seen is None: seen = set()
                    if isinstance(obj, list):
                        for item in obj: extract_youtube_videos(item, vids, seen)
                    elif isinstance(obj, dict):
                        url = obj.get("url") or obj.get("uri") or obj.get("link")
                        if isinstance(url, str) and ("youtube.com/watch" in url or "youtu.be/" in url):
                            match = re.search(r'(?:v=|youtu\.be/)([\w-]+)', url)
                            if match:
                                vid_id = match.group(1)
                                if vid_id not in seen:
                                    seen.add(vid_id)
                                    vids.append({
                                        "video_id": vid_id,
                                        "title": obj.get("title", "YouTube Video"),
                                        "channel": obj.get("author") or obj.get("channel", "YouTube"),
                                        "thumbnail": f"https://img.youtube.com/vi/{vid_id}/maxresdefault.jpg",
                                        "url": url
                                    })
                        for val in obj.values(): extract_youtube_videos(val, vids, seen)
                    return vids
                    
                videos = extract_youtube_videos(body)
                
                # EXTRACT GROUNDING / WEB SOURCES (NEW)
                sources = []
                def extract_web_sources(obj, srcs=None, seen=None):
                    if srcs is None: srcs = []
                    if seen is None: seen = set()
                    
                    if isinstance(obj, list):
                        # Signature of a web link with text mapping
                        if len(obj) >= 5 and isinstance(obj[0], str) and obj[0].startswith("http"):
                            url = obj[0]
                            if not any(x in url for x in ["googleusercontent.com", "youtube.com", "youtu.be", "gstatic.com"]):
                                title = obj[3] if isinstance(obj[3], str) else url
                                snippet = ""
                                try:
                                    if isinstance(obj[4], list) and len(obj[4]) > 0 and isinstance(obj[4][0], list) and len(obj[4][0]) > 0 and isinstance(obj[4][0][0], str):
                                        snippet = obj[4][0][0]
                                except:
                                    pass
                                    
                                if url not in seen or snippet:
                                    seen.add(url)
                                    srcs.append({"url": url, "title": title, "snippet": snippet})
                        
                        # Signature of a simple web link fallback
                        elif len(obj) >= 2 and isinstance(obj[0], str) and isinstance(obj[1], str):
                            url = obj[0]
                            title = obj[1]
                            if url.startswith("http") and not any(x in url for x in ["googleusercontent.com", "youtube.com", "youtu.be", "gstatic.com"]):
                                if url not in seen:
                                    seen.add(url)
                                    srcs.append({"url": url, "title": title if title else url, "snippet": ""})
                                    
                        for item in obj:
                            extract_web_sources(item, srcs, seen)
                    elif isinstance(obj, dict):
                        for val in obj.values():
                            extract_web_sources(val, srcs, seen)
                    return srcs
                
                sources = extract_web_sources(body)

                # EXTRACT GENERATED FILES / PDFS (NEW)
                generated_files = []
                def extract_generated_docs(obj, files=None, seen=None):
                    if files is None: files = []
                    if seen is None: seen = set()
                    
                    if isinstance(obj, list):
                        for item in obj:
                            if isinstance(item, str) and "contribution.usercontent.google.com/download" in item:
                                if item not in seen:
                                    seen.add(item)
                                    match = re.search(r'filename=([^&]+)', item)
                                    filename = urllib.parse.unquote(match.group(1)) if match else "generated_document.pdf"
                                    files.append({
                                        "filename": filename,
                                        "download_url": item
                                    })
                            extract_generated_docs(item, files, seen)
                    elif isinstance(obj, dict):
                        for val in obj.values():
                            extract_generated_docs(val, files, seen)
                    return files
                
                generated_files = extract_generated_docs(body)

                if not images and content:
                    try:
                        urls = re.findall(r'(https?://[^\s]+\.(?:jpg|jpeg|png|gif|webp))', content.lower())
                        for i, url in enumerate(urls):
                            img_obj = Image(
                                url=url, 
                                title=f"Image in Content {i+1}", 
                                alt="",
                                proxy=self.proxies_dict,
                                impersonate=self.impersonate
                            )
                            images.append(img_obj)
                    except Exception:
                        pass
                
                content = re.sub(r'!?\[[^\]]*\]\((?:https?://)?(?:[^)]*?)googleusercontent\.com/image_(?:collection|generation_content)/[^)]+\)', '', content)
                content = re.sub(r'(?:https?://)?(?:[^)\s]*?)googleusercontent\.com/image_(?:collection|generation_content)/\S+', '', content)

                content = re.sub(r'!?\[[^\]]*\]\((?:https?://)?(?:[^)]*?)googleusercontent\.com/youtube_content/[^)]+\)', '', content)
                content = re.sub(r'(?:https?://)?(?:[^)\s]*?)googleusercontent\.com/youtube_content/\S+', '', content)

                results = {
                    "content": final_content,
                    "conversation_id": conversation_id,
                    "response_id": response_id,
                    "choice_id": choice_id,
                    "factualityQueries": factualityQueries,
                    "textQuery": textQuery,
                    "choices": choices,
                    "images": images,
                    "videos": videos,
                    "sources": sources,
                    "files": generated_files, # Add file extraction to standard yield
                    "error": False,
                }

                self.conversation_id = conversation_id
                self.response_id = response_id
                self.choice_id = choice_id
                self._reqid += random.randint(1000, 9000)

                return results

            except (IndexError, TypeError) as e:
                console.log(f"[red]Error extracting data from response: {e}[/red]")
                return {"content": f"Error extracting data from response: {e}", "error": True}

        except json.JSONDecodeError as e:
            console.log(f"[red]Error parsing JSON response: {e}[/red]")
            return {"content": f"Error parsing JSON response: {e}. Response: {resp.text[:200]}...", "error": True}
        except Timeout as e:
            console.log(f"[red]Request timed out: {e}[/red]")
            return {"content": f"Request timed out: {e}", "error": True}
        except (RequestException, CurlError) as e:
            console.log(f"[red]Network error: {e}[/red]")
            return {"content": f"Network error: {e}", "error": True}
        except HTTPError as e:
            console.log(f"[red]HTTP error {e.response.status_code}: {e}[/red]")
            return {"content": f"HTTP error {e.response.status_code}: {e}", "error": True}
        except Exception as e:
            console.log(f"[red]An unexpected error occurred during ask: {e}[/red]", style="bold red")
            return {"content": f"An unexpected error occurred: {e}", "error": True}