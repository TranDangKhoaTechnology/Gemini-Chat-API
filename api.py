from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Union, Dict, Any
import time
import uuid
import base64
import json
import os

import database as db
from gemini_client.core import AsyncChatbot
from gemini_client.enums import Model, Headers

app = FastAPI(title="Gemini-to-OpenAI API")
security = HTTPBearer()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Message(BaseModel):
    role: str
    # IMPORTANT: List[Any] MUST come before str so Pydantic doesn't cast arrays into strings!
    content: Optional[Union[List[Any], str]] = None
    name: Optional[str] = None
    
    class Config:
        extra = "ignore"  # Prevents 422 errors from unexpected fields

class ChatCompletionRequest(BaseModel):
    model: str 
    messages: List[Message]
    temperature: Optional[float] = 1.0
    top_p: Optional[float] = 1.0
    n: Optional[int] = 1
    stream: Optional[bool] = False
    stop: Optional[Union[str, List[str]]] = None
    max_tokens: Optional[int] = None
    max_completion_tokens: Optional[int] = None
    presence_penalty: Optional[float] = 0.0
    frequency_penalty: Optional[float] = 0.0
    logit_bias: Optional[Dict[str, float]] = None
    user: Optional[str] = None
    seed: Optional[int] = None
    response_format: Optional[Dict[str, str]] = None
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    canvas_mode: Optional[bool] = False
    pdf_mode: Optional[bool] = False # NEW FIELD: Toggle for the PDF Tool

    class Config:
        extra = "ignore"  # Strongly prevents 422 errors

class CookieUpdateRequest(BaseModel):
    psid: str
    psidts: str

class AnthropicMessage(BaseModel):
    role: str
    content: Union[str, List[Any]]

class AnthropicMessagesRequest(BaseModel):
    model: str
    messages: List[AnthropicMessage]
    system: Optional[Union[str, List[Any]]] = None
    max_tokens: Optional[int] = 1024
    metadata: Optional[Dict[str, Any]] = None
    stop_sequences: Optional[List[str]] = None
    stream: Optional[bool] = False
    temperature: Optional[float] = 1.0
    top_p: Optional[float] = 1.0
    top_k: Optional[int] = None
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Dict[str, Any]] = None

    class Config:
        extra = "ignore"

def get_api_key_from_request(request: Request) -> str:
    # 1. Check x-api-key header (Anthropic standard)
    x_key = request.headers.get("x-api-key")
    if x_key:
        return x_key
    
    # 2. Check Authorization Bearer header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ")[1]
        
    # 3. Check api-key header
    api_key = request.headers.get("api-key")
    if api_key:
        return api_key
        
    raise HTTPException(status_code=401, detail="API Key missing from headers (Authorization Bearer or x-api-key)")

def verify_api_key(request: Request):
    key = get_api_key_from_request(request)
    details = db.get_api_key_details(key)
    if not details or not details[0]: 
        raise HTTPException(status_code=401, detail="Invalid or deactivated API Key")
        
    # EXPIRE CHECK
    if details[3] > 0 and time.time() > details[3]:
        raise HTTPException(status_code=401, detail="API Key has expired")

    # ENFORCE RATE LIMITS
    if not db.check_rate_limit(key):
        raise HTTPException(
            status_code=429, 
            detail="Rate limit exceeded. Please wait before making more requests."
        )
    return {"key": key, "allowed_models": details[1], "role": details[2]}

def verify_admin_key(request: Request):
    key = get_api_key_from_request(request)
    details = db.get_api_key_details(key)
    if not details or not details[0]: 
        raise HTTPException(status_code=401, detail="Invalid or deactivated API Key")
        
    # EXPIRE CHECK
    if details[3] > 0 and time.time() > details[3]:
        raise HTTPException(status_code=401, detail="API Key has expired")

    if details[2] != 'admin':
        raise HTTPException(status_code=403, detail="API Key lacks 'admin' permissions required for this endpoint")
    return {"key": key}

# ==========================================
# SECURE EXTENSION AUTO-HEALER ENDPOINTS
# ==========================================
@app.get("/v1/admin/cookie_status")
async def check_cookie_status(admin_auth = Depends(verify_admin_key)):
    """Extension securely polls this to see if intervention is needed."""
    return {"needs_update": db.get_needs_update()}

@app.post("/v1/admin/cookies")
async def update_cookies_api(request: CookieUpdateRequest, admin_auth = Depends(verify_admin_key)):
    """Extension pushes JSON Secure data packet here to fix cookies."""
    db.update_cookies(request.psid, request.psidts)
    db.set_needs_update(False) # Turn off the distress signal
    
    from admin_bot import bot, ADMIN_ID
    if bot and ADMIN_ID:
        try:
            bot.send_message(ADMIN_ID, "✅ <b>Auto-Heal Complete:</b> The Chrome Extension securely intercepted the error and updated the database with fresh cookies!", parse_mode="HTML")
        except: pass
        
    return {"status": "success", "message": "Secure payload accepted. Cookies updated."}

@app.get("/v1/models")
async def list_models(auth_data: dict = Depends(verify_api_key)):
    allowed_models_str = auth_data["allowed_models"]
    allowed_list = [m.strip() for m in allowed_models_str.split(",")] if allowed_models_str != "all" else None
    
    models_data = []
    for m in Model:
        if m == Model.UNSPECIFIED:
            continue
        if allowed_list and m.model_name not in allowed_list:
            continue
            
        models_data.append({
            "id": m.model_name,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "google",
            "permission": [],
            "root": m.model_name,
            "parent": None,
        })
        
    return {"object": "list", "data": models_data}

@app.get("/v1/download")
async def proxy_download(request: Request, url: str, view: bool = False, token: Optional[str] = None):
    """Proxies file downloads using the backend's active Gemini cookies. Supports inline viewing."""
    import re
    import urllib.parse
    
    # 1. Flexible Authentication: Check Header first, then query param for browsers/iframes
    auth_header = request.headers.get("Authorization")
    api_key = None
    if auth_header and auth_header.startswith("Bearer "):
        api_key = auth_header.split(" ")[1]
    elif token:
        api_key = token
        
    if not api_key:
        raise HTTPException(status_code=401, detail="Not authenticated")
        
    details = db.get_api_key_details(api_key)
    if not details or not details[0]: 
        raise HTTPException(status_code=401, detail="Invalid or deactivated API Key")
    
    # Check expiry
    if details[3] > 0 and time.time() > details[3]:
        raise HTTPException(status_code=401, detail="API Key has expired")
        
    # 2. Security check to prevent open proxy abuse
    if not url.startswith("https://contribution.usercontent.google.com") and not url.startswith("https://drive.google.com"):
        raise HTTPException(status_code=403, detail="Only authorized Google domains are allowed for proxying.")

    cookies = db.get_cookies()
    if not cookies or not cookies[0]:
        raise HTTPException(status_code=500, detail="Gemini Cookies not set.")
    
    cookie_dict = {"__Secure-1PSID": cookies[0]}
    if cookies[1]:
        cookie_dict["__Secure-1PSIDTS"] = cookies[1]

    # Use curl_cffi to bypass detection just like core.py
    from curl_cffi.requests import AsyncSession
    
    # Extract filename for headers
    match = re.search(r'filename=([^&]+)', url)
    filename = urllib.parse.unquote(match.group(1)) if match else "document.pdf"
    
    async def fetch_file():
        # NOTE: Purposely omitting Headers.GEMINI here because Google blocks it on this specific endpoint
        async with AsyncSession(cookies=cookie_dict, impersonate="chrome110") as session:
            response = await session.get(url, stream=True)
            if response.status_code != 200:
                yield f"Error: Failed to download from Google. Status {response.status_code}".encode()
                return
            async for chunk in response.aiter_content():
                yield chunk

    # If view=true, display in browser. If view=false, force download.
    disposition = "inline" if view else "attachment"
    headers = {"Content-Disposition": f"{disposition}; filename=\"{filename}\""}

    return StreamingResponse(fetch_file(), media_type="application/pdf", headers=headers)

async def url_to_base64(url: str, cookies_dict: dict) -> str:
    from curl_cffi.requests import AsyncSession, Cookies
    jar = Cookies()
    for name, val in cookies_dict.items():
        if val:
            jar.set(name, val, domain=".google.com")
    try:
        async with AsyncSession(cookies=jar, impersonate="chrome110") as session:
            r = await session.get(url, allow_redirects=True)
            if r.status_code == 200:
                content_type = r.headers.get("content-type", "image/png")
                b64_data = base64.b64encode(r.content).decode("utf-8")
                return f"data:{content_type};base64,{b64_data}"
            else:
                print(f"Failed to download image for base64 conversion: status {r.status_code}")
                return url
    except Exception as e:
        print(f"Error converting image url to base64: {e}")
        return url

@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest, auth_data: dict = Depends(verify_api_key)):
    cookies = db.get_cookies()
    if not cookies or not cookies[0]:
        raise HTTPException(status_code=500, detail="Gemini Cookies not set. Admin must set them via Telegram.")
    
    allowed_models_str = auth_data["allowed_models"]
    allowed_list = [m.strip() for m in allowed_models_str.split(",")] if allowed_models_str != "all" else None
    
    if allowed_list and request.model not in allowed_list:
        raise HTTPException(status_code=403, detail=f"Your API key does not have access to model: {request.model}.")

    # --- SYSTEM PROMPT LOGIC ---
    system_prompts = []
    user_messages = []
    
    for m in request.messages:
        if m.role == "system":
            if isinstance(m.content, list):
                text_parts = [item.get("text", "") for item in m.content if isinstance(item, dict) and item.get("type") == "text"]
                system_prompts.append("\n".join(text_parts))
            elif isinstance(m.content, str):
                system_prompts.append(m.content)
        else:
            user_messages.append(m)

    # 1. Canvas / Workspace Tool
    if request.canvas_mode:
        CANVAS_INSTRUCTION_PROMPT = """[SYSTEM: ADVANCED IDE WORKSPACE MODE]
You are operating within a strict, production-grade IDE environment. Your primary directive is EFFICIENCY and TOKEN CONSERVATION. 

CRITICAL DIRECTIVE: NEVER REGENERATE COMPLETE FILES FOR MINOR EDITS OR UPGRADES.

You have two exclusive operational modes. You MUST evaluate the user's request and choose the appropriate one:

MODE 1: MODIFY EXISTING FILE (MANDATORY FOR EDITS/UPGRADES)
If the user requests an upgrade, tweak, bug fix, or addition to existing code, you MUST use the `<code_patch>` XML format. Do not output the full file.
Format:
<code_patch filename="example.html">
<search>
Exact lines to find in the original file. MUST MATCH PERFECTLY, including indentation. Include enough context lines to ensure the search string is unique.
</search>
<replace>
The new updated code lines that will replace the exact search block.
</replace>
</code_patch>
* You can use multiple <code_patch> blocks sequentially if you need to edit multiple different parts of the same file.

MODE 2: CREATE OR REWRITE ENTIRE FILE (ONLY FOR NEW CREATIONS)
ONLY use this if the user asks for a completely new file, or explicitly demands a full rewrite.
Format:
<code_container filename="example.html">
<!-- Complete, runnable code goes here -->
</code_container>

STRICT ENFORCEMENT RULES:
1. NEVER use standard markdown code blocks (e.g., ```python, ```html). YOU MUST use the XML tags above.
2. NEVER output <code_container> if the user asks for a small change. You will be penalized for wasting tokens. Use <code_patch>.
3. For <code_patch>, the text inside <search> MUST exist exactly in the user's current code. Do not use placeholders or summaries in the search block.
4. Provide all your explanations in plain text OUTSIDE the XML blocks."""
        system_prompts.append(CANVAS_INSTRUCTION_PROMPT)

    # 2. PDF Generator Tool
    if request.pdf_mode:
        PDF_INSTRUCTION_PROMPT = """[SYSTEM: PDF GENERATOR TOOL ACTIVE]
You have the 'PDF Generator' tool enabled. 
When the user asks to generate a document, report, invoice, essay, or any printable text, you MUST output it as semantic HTML inside a specific `<pdf_document>` XML tag.
Our frontend application will automatically intercept this HTML tag and compile it into a downloadable PDF for the user.

Format Template:
<pdf_document filename="professional_report.pdf">
<div style="font-family: Arial, sans-serif; color: #1f2937; padding: 20px;">
    <h1 style="color: #2563eb; border-bottom: 2px solid #e5e7eb; padding-bottom: 10px; text-align: center;">Document Title</h1>
    <p style="line-height: 1.6;">Your professional content goes here...</p>
    
    <table style="width: 100%; border-collapse: collapse; margin-top: 20px;">
        <tr style="background-color: #f3f4f6;">
            <th style="padding: 10px; border: 1px solid #d1d5db;">Header 1</th>
            <th style="padding: 10px; border: 1px solid #d1d5db;">Header 2</th>
        </tr>
        <tr>
            <td style="padding: 10px; border: 1px solid #d1d5db;">Data 1</td>
            <td style="padding: 10px; border: 1px solid #d1d5db;">Data 2</td>
        </tr>
    </table>
</div>
</pdf_document>

STRICT RULES:
1. ONLY use valid HTML5 inside the `<pdf_document>` tag. 
2. Do NOT use Markdown formatting (like **bold** or # headings) inside the HTML block. Use HTML elements like <strong> and <h1>.
3. Use inline CSS (`style="..."`) to style the document professionally. The PDF compiler engine reads inline CSS perfectly to make it look beautiful.
4. NEVER wrap the `<pdf_document>` tag inside markdown code fences (like ```html). Let it stand alone as an XML block in your response.
5. Provide standard conversational text and explanations outside the XML block."""
        system_prompts.append(PDF_INSTRUCTION_PROMPT)

    # Get the last message to process
    last_msg_content = user_messages[-1].content if user_messages else ""
    prompt_parts = []
    files_to_upload = []
    temp_files = []
    user_prompt_text = ""

    # Check for Vision/File Payload (List of Dictionaries/Objects)
    if isinstance(last_msg_content, list):
        for item in last_msg_content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    prompt_parts.append(item.get("text", ""))
                elif item.get("type") in ["image_url", "file_url"]:
                    url_obj = item.get("image_url") or item.get("file_url")
                    if not url_obj: continue
                    
                    url = url_obj.get("url", "")
                    filename = url_obj.get("name", f"upload_{len(files_to_upload)}.bin")
                    
                    if url.startswith("data:"):
                        try:
                            header, encoded = url.split(",", 1)
                            file_bytes = base64.b64decode(encoded)
                            
                            # Save to temp file to retain original extension for MIME detection
                            tmp_dir = os.path.join("data", "temp_uploads")
                            os.makedirs(tmp_dir, exist_ok=True)
                            tmp_path = os.path.join(tmp_dir, f"{uuid.uuid4().hex}_{filename}")
                            
                            with open(tmp_path, "wb") as f:
                                f.write(file_bytes)
                            
                            files_to_upload.append(tmp_path)
                            temp_files.append(tmp_path)
                        except Exception as e:
                            print(f"Failed to decode base64 file: {e}")
        user_prompt_text = "\n".join(prompt_parts).strip()
        if not user_prompt_text and files_to_upload:
            user_prompt_text = "Analyze the provided files/images."
    else:
        # Standard text message
        user_prompt_text = str(last_msg_content) if last_msg_content else ""

    # Combine System Prompts and User Prompt
    final_prompt = ""
    if system_prompts:
        combined_system = "\n\n".join(system_prompts)
        if user_prompt_text:
            final_prompt = f"[SYSTEM INSTRUCTIONS]\n{combined_system}\n[/SYSTEM INSTRUCTIONS]\n\n[USER REQUEST]\n{user_prompt_text}\n[/USER REQUEST]"
        else:
            final_prompt = f"[SYSTEM INSTRUCTIONS]\n{combined_system}\n[/SYSTEM INSTRUCTIONS]"
    else:
        final_prompt = user_prompt_text

    prompt = final_prompt
    api_key_token = auth_data["key"]

    try:
        try:
            requested_model = Model.from_name(request.model)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
                
        bot = await AsyncChatbot.create(
            secure_1psid=cookies[0],
            secure_1psidts=cookies[1],
            model=requested_model
        )
        
        session_data = db.get_api_key_session(api_key_token)
        if session_data and session_data["cid"]:
            bot.conversation_id = session_data["cid"]
            bot.response_id = session_data["rid"] or ""
            bot.choice_id = session_data["chid"] or ""

        if request.stream:
            async def stream_generator():
                try:
                    cid, rid, chid = None, None, None
                    has_content = False
                    
                    try:
                        async for result in bot.ask_stream(prompt, files=files_to_upload):
                            # Catch potential API/cookie errors returned elegantly during stream
                            if result.get("error"):
                                # RESET SESSION: Clear invalid conversation bindings on error
                                db.update_api_key_session(api_key_token, None, None, None)
                                cid = None # Prevent the final block from re-saving a bad session
                                
                                error_msg = result.get("content", "Unknown error")
                                error_chunk = {
                                    "id": f"chatcmpl-{uuid.uuid4().hex}",
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": request.model,
                                    "choices": [{"index": 0, "delta": {"content": f"\n\n[Error: {error_msg}]"}, "finish_reason": "stop"}]
                                }
                                yield f"data: {json.dumps(error_chunk)}\n\n"
                                break
                            
                            chunk_text = result.get("chunk", "")
                            cid = result.get("conversation_id")
                            rid = result.get("response_id")
                            chid = result.get("choice_id")
                            
                            # Extract and format images securely for JSON serialization
                            raw_imgs = result.get("images", [])
                            safe_imgs = []
                            if raw_imgs:
                                c_dict = {"__Secure-1PSID": cookies[0]}
                                if cookies[1]:
                                    c_dict["__Secure-1PSIDTS"] = cookies[1]
                                for img in raw_imgs:
                                    img_url = img.url if hasattr(img, 'url') else (img.get('url', '') if isinstance(img, dict) else '')
                                    img_title = getattr(img, 'title', 'Image') if hasattr(img, 'title') else (img.get('title', 'Image') if isinstance(img, dict) else 'Image')
                                    if img_url:
                                        if img_url.startswith("http"):
                                            b64_url = await url_to_base64(img_url, c_dict)
                                        else:
                                            b64_url = img_url
                                        safe_imgs.append({"url": b64_url, "title": img_title})
                            
                            safe_vids = result.get("videos", [])
                            safe_sources = result.get("sources", [])
                            safe_files = result.get("files", []) # EXPOSE EXTRACTED FILES TO STREAM
                            
                            # Emit the live text chunk, images, videos, sources, AND files
                            if chunk_text or safe_imgs or safe_vids or safe_sources or safe_files:
                                has_content = True
                                delta_data = {}
                                if chunk_text:
                                    delta_data["content"] = chunk_text
                                if safe_imgs:
                                    delta_data["images"] = safe_imgs
                                if safe_vids:
                                    delta_data["videos"] = safe_vids
                                if safe_sources:
                                    delta_data["sources"] = safe_sources
                                if safe_files:
                                    delta_data["files"] = safe_files # INJECT FILES HERE

                                chunk_json = {
                                    "id": f"chatcmpl-{uuid.uuid4().hex}",
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": request.model,
                                    "choices": [{"index": 0, "delta": delta_data, "finish_reason": None}]
                                }
                                yield f"data: {json.dumps(chunk_json)}\n\n"
                                
                    except Exception as stream_e:
                        # Catch exceptions that occur INSIDE the async generator and bypass the outer try/except
                        db.update_api_key_session(api_key_token, None, None, None)
                        cid = None
                        error_str = str(stream_e)
                        
                        # SMART AUTO-HEALER TRIGGER inside the generator
                        if any(kw in error_str.lower() for kw in ["cookie", "snlm0e", "auth", "permission", "status: 40", "status: 50"]):
                            db.set_needs_update(True)
                            if db.check_and_set_alert_flood(cooldown_seconds=300):
                                try:
                                    from admin_bot import send_admin_alert
                                    send_admin_alert("Cookies expired! Notifying Chrome Extension Auto-Healer to execute payload...")
                                except: pass
                                
                        error_chunk = {
                            "id": f"chatcmpl-{uuid.uuid4().hex}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": request.model,
                            "choices": [{"index": 0, "delta": {"content": f"\n\n[Stream Error: {error_str}]"}, "finish_reason": "stop"}]
                        }
                        yield f"data: {json.dumps(error_chunk)}\n\n"

                    # Update persistent conversation session ONLY if we successfully got content and no errors cleared cid
                    if cid and has_content:
                        db.update_api_key_session(api_key_token, cid, rid, chid)
                    else:
                        # Blank response or error -> Reset session immediately
                        db.update_api_key_session(api_key_token, None, None, None)
                        
                    # Emit final finish_reason block
                    finish_chunk = {
                        "id": f"chatcmpl-{uuid.uuid4().hex}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": request.model,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
                    }
                    yield f"data: {json.dumps(finish_chunk)}\n\n"
                    yield "data: [DONE]\n\n"
                finally:
                    # Crucial: Close network session once streaming ends
                    await bot.session.close()
                    # Clean up temporary uploaded files
                    for p in temp_files:
                        if os.path.exists(p):
                            try:
                                os.remove(p)
                            except:
                                pass

            return StreamingResponse(stream_generator(), media_type="text/event-stream")

        else:
            # STANDARD SYNCHRONOUS REQUEST (Non-Streaming)
            response = await bot.ask(prompt, files=files_to_upload)
            
            # Clean up temporary uploaded files
            for p in temp_files:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except:
                        pass

            # RESET SESSION: Clear invalid bindings if Gemini threw an error string
            if response.get("error"):
                db.update_api_key_session(api_key_token, None, None, None)
                await bot.session.close()
                raise HTTPException(status_code=500, detail=str(response.get("content", "Unknown error occurred.")))
                
            # ROBUST TEXT EXTRACTION
            raw_content = response.get("content") or ""
            
            def extract_text(item: Any) -> str:
                if isinstance(item, str):
                    return item
                elif isinstance(item, list):
                    return "".join(extract_text(x) for x in item if x is not None)
                return str(item) if item is not None else ""
                
            final_content = extract_text(raw_content).strip()

            # Extract images for non-streaming mode
            raw_imgs = response.get("images", [])
            safe_imgs = []
            if raw_imgs:
                c_dict = {"__Secure-1PSID": cookies[0]}
                if cookies[1]:
                    c_dict["__Secure-1PSIDTS"] = cookies[1]
                for img in raw_imgs:
                    img_url = img.url if hasattr(img, 'url') else (img.get('url', '') if isinstance(img, dict) else '')
                    img_title = getattr(img, 'title', 'Image') if hasattr(img, 'title') else (img.get('title', 'Image') if isinstance(img, dict) else 'Image')
                    if img_url:
                        if img_url.startswith("http"):
                            b64_url = await url_to_base64(img_url, c_dict)
                        else:
                            b64_url = img_url
                        safe_imgs.append({"url": b64_url, "title": img_title})

            safe_vids = response.get("videos", [])
            safe_sources = response.get("sources", [])
            safe_files = response.get("files", []) # EXPOSE EXTRACTED FILES

            # RESET SESSION: If we got a completely blank response (usually signifies bad session state)
            if not final_content and not safe_imgs and not safe_vids:
                db.update_api_key_session(api_key_token, None, None, None)
            else:
                # Normal behavior: Save the active session
                db.update_api_key_session(api_key_token, bot.conversation_id, bot.response_id, bot.choice_id)

            await bot.session.close()

            return {
                "id": f"chatcmpl-{uuid.uuid4().hex}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": request.model,
                "choices": [{
                    "index": 0, 
                    "message": {
                        "role": "assistant", 
                        "content": final_content, 
                        "images": safe_imgs, 
                        "videos": safe_vids, 
                        "sources": safe_sources,
                        "files": safe_files # INJECT FILES HERE
                    }, 
                    "finish_reason": "stop"
                }]
            }

    except HTTPException:
        raise
    except Exception as e:
        error_str = str(e)
        
        # RESET SESSION: Clear session for all major backend/network crashes 
        # (Allows the next request to bypass corrupted thread history)
        db.update_api_key_session(api_key_token, None, None, None)
        
        # SMART AUTO-HEALER TRIGGER & FLOOD CONTROL
        if any(kw in error_str.lower() for kw in ["cookie", "snlm0e", "auth", "permission", "status: 40", "status: 50"]):
            # Signal the Chrome Extension
            db.set_needs_update(True)
            
            # Flood Control: Only alert Telegram once every 5 minutes
            if db.check_and_set_alert_flood(cooldown_seconds=300):
                try:
                    from admin_bot import send_admin_alert
                    send_admin_alert("Cookies expired! Notifying Chrome Extension Auto-Healer to execute payload...")
                except: pass
                
        raise HTTPException(status_code=500, detail=error_str)

@app.post("/v1/messages")
@app.post("/messages")
async def anthropic_messages(request: AnthropicMessagesRequest, auth_data: dict = Depends(verify_api_key)):
    cookies = db.get_cookies()
    if not cookies or not cookies[0]:
        raise HTTPException(status_code=500, detail="Gemini Cookies not set. Admin must set them via Telegram.")
    
    allowed_models_str = auth_data["allowed_models"]
    allowed_list = [m.strip() for m in allowed_models_str.split(",")] if allowed_models_str != "all" else None
    
    # Translate model name from Anthropic to Gemini if needed
    model_name = request.model
    if "claude" in model_name.lower():
        model_name = "gemini-3.5-flash"
            
    if allowed_list and model_name not in allowed_list:
        model_name = allowed_list[0] if allowed_list else "gemini-3.5-flash"

    # --- SYSTEM PROMPT LOGIC ---
    system_prompts = []
    if request.system:
        if isinstance(request.system, list):
            text_parts = [item.get("text", "") for item in request.system if isinstance(item, dict) and item.get("type") == "text"]
            system_prompts.append("\n".join(text_parts))
        elif isinstance(request.system, str):
            system_prompts.append(request.system)

    # Convert Anthropic messages format to simple prompt text
    user_prompt_text = ""
    if request.messages:
        last_msg = request.messages[-1]
        last_msg_content = last_msg.content
        if isinstance(last_msg_content, list):
            prompt_parts = [item.get("text", "") for item in last_msg_content if isinstance(item, dict) and item.get("type") == "text"]
            user_prompt_text = "\n".join(prompt_parts).strip()
        else:
            user_prompt_text = str(last_msg_content)

    # Combine system prompts and user prompt
    final_prompt = ""
    if system_prompts:
        combined_system = "\n\n".join(system_prompts)
        if user_prompt_text:
            final_prompt = f"[SYSTEM INSTRUCTIONS]\n{combined_system}\n[/SYSTEM INSTRUCTIONS]\n\n[USER REQUEST]\n{user_prompt_text}\n[/USER REQUEST]"
        else:
            final_prompt = f"[SYSTEM INSTRUCTIONS]\n{combined_system}\n[/SYSTEM INSTRUCTIONS]"
    else:
        final_prompt = user_prompt_text

    prompt = final_prompt
    api_key_token = auth_data["key"]

    try:
        try:
            requested_model = Model.from_name(model_name)
        except ValueError:
            requested_model = Model.G_3_5_FLASH
            
        bot = await AsyncChatbot.create(
            secure_1psid=cookies[0],
            secure_1psidts=cookies[1],
            model=requested_model
        )
        
        session_data = db.get_api_key_session(api_key_token)
        if session_data and session_data["cid"]:
            bot.conversation_id = session_data["cid"]
            bot.response_id = session_data["rid"] or ""
            bot.choice_id = session_data["chid"] or ""

        if request.stream:
            async def stream_generator():
                try:
                    cid, rid, chid = None, None, None
                    has_content = False
                    
                    # 1. message_start
                    msg_id = f"msg_{uuid.uuid4().hex}"
                    message_start_event = {
                        "type": "message_start",
                        "message": {
                            "id": msg_id,
                            "type": "message",
                            "role": "assistant",
                            "content": [],
                            "model": model_name,
                            "stop_reason": None,
                            "stop_sequence": None,
                            "usage": {"input_tokens": 0, "output_tokens": 0}
                        }
                    }
                    yield f"event: message_start\ndata: {json.dumps(message_start_event)}\n\n"

                    # 2. content_block_start
                    content_block_start_event = {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {"type": "text", "text": ""}
                    }
                    yield f"event: content_block_start\ndata: {json.dumps(content_block_start_event)}\n\n"
                    
                    try:
                        async for result in bot.ask_stream(prompt):
                            if result.get("error"):
                                db.update_api_key_session(api_key_token, None, None, None)
                                cid = None
                                error_msg = result.get("content", "Unknown error")
                                error_event = {
                                    "type": "content_block_delta",
                                    "index": 0,
                                    "delta": {"type": "text_delta", "text": f"\n\n[Error: {error_msg}]"}
                                }
                                yield f"event: content_block_delta\ndata: {json.dumps(error_event)}\n\n"
                                break
                            
                            chunk_text = result.get("chunk", "")
                            cid = result.get("conversation_id")
                            rid = result.get("response_id")
                            chid = result.get("choice_id")
                            
                            if chunk_text:
                                has_content = True
                                delta_event = {
                                    "type": "content_block_delta",
                                    "index": 0,
                                    "delta": {"type": "text_delta", "text": chunk_text}
                                }
                                yield f"event: content_block_delta\ndata: {json.dumps(delta_event)}\n\n"
                                
                    except Exception as stream_e:
                        db.update_api_key_session(api_key_token, None, None, None)
                        cid = None
                        error_str = str(stream_e)
                        
                        if any(kw in error_str.lower() for kw in ["cookie", "snlm0e", "auth", "permission", "status: 40", "status: 50"]):
                            db.set_needs_update(True)
                            if db.check_and_set_alert_flood(cooldown_seconds=300):
                                try:
                                    from admin_bot import send_admin_alert
                                    send_admin_alert("Cookies expired! Notifying Chrome Extension Auto-Healer to execute payload...")
                                except: pass
                                
                        error_event = {
                            "type": "content_block_delta",
                            "index": 0,
                            "delta": {"type": "text_delta", "text": f"\n\n[Stream Error: {error_str}]"}
                        }
                        yield f"event: content_block_delta\ndata: {json.dumps(error_event)}\n\n"

                    if cid and has_content:
                        db.update_api_key_session(api_key_token, cid, rid, chid)
                    else:
                        db.update_api_key_session(api_key_token, None, None, None)
                        
                    # 4. content_block_stop
                    content_block_stop_event = {
                        "type": "content_block_stop",
                        "index": 0
                    }
                    yield f"event: content_block_stop\ndata: {json.dumps(content_block_stop_event)}\n\n"

                    # 5. message_delta
                    message_delta_event = {
                        "type": "message_delta",
                        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                        "usage": {"output_tokens": 0}
                    }
                    yield f"event: message_delta\ndata: {json.dumps(message_delta_event)}\n\n"

                    # 6. message_stop
                    message_stop_event = {
                        "type": "message_stop"
                    }
                    yield f"event: message_stop\ndata: {json.dumps(message_stop_event)}\n\n"
                    
                finally:
                    await bot.session.close()

            return StreamingResponse(stream_generator(), media_type="text/event-stream")

        else:
            response = await bot.ask(prompt)
            
            if response.get("error"):
                db.update_api_key_session(api_key_token, None, None, None)
                await bot.session.close()
                raise HTTPException(status_code=500, detail=str(response.get("content", "Unknown error occurred.")))
                
            raw_content = response.get("content") or ""
            
            def extract_text(item: Any) -> str:
                if isinstance(item, str):
                    return item
                elif isinstance(item, list):
                    return "".join(extract_text(x) for x in item if x is not None)
                return str(item) if item is not None else ""
                
            final_content = extract_text(raw_content).strip()

            if not final_content:
                db.update_api_key_session(api_key_token, None, None, None)
            else:
                db.update_api_key_session(api_key_token, bot.conversation_id, bot.response_id, bot.choice_id)

            await bot.session.close()

            return {
                "id": f"msg_{uuid.uuid4().hex}",
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": final_content
                    }
                ],
                "model": model_name,
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {
                    "input_tokens": 0,
                    "output_tokens": 0
                }
            }

    except HTTPException:
        raise
    except Exception as e:
        error_str = str(e)
        db.update_api_key_session(api_key_token, None, None, None)
        if any(kw in error_str.lower() for kw in ["cookie", "snlm0e", "auth", "permission", "status: 40", "status: 50"]):
            db.set_needs_update(True)
            if db.check_and_set_alert_flood(cooldown_seconds=300):
                try:
                    from admin_bot import send_admin_alert
                    send_admin_alert("Cookies expired! Notifying Chrome Extension Auto-Healer to execute payload...")
                except: pass
        raise HTTPException(status_code=500, detail=error_str)

class KeyCreateRequest(BaseModel):
    name: str
    role: Optional[str] = "user"
    allowed_models: Optional[str] = "all"
    expires_in_hours: Optional[float] = 0

class KeyRevokeRequest(BaseModel):
    key: str

class ChangeAdminKeyRequest(BaseModel):
    new_key: str

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    dashboard_path = os.path.join("static", "dashboard.html")
    if not os.path.exists(dashboard_path):
        return HTMLResponse(content="<h1>Dashboard file not found</h1>", status_code=404)
    with open(dashboard_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.get("/favicon.ico")
async def serve_favicon():
    """Serve a simple inline SVG favicon to prevent 404 errors."""
    from fastapi.responses import Response
    # A simple star SVG favicon
    svg_content = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
      <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="#6366f1"/>
        <stop offset="100%" stop-color="#8b5cf6"/>
      </linearGradient></defs>
      <circle cx="50" cy="50" r="50" fill="url(#g)"/>
      <text y=".9em" font-size="60" x="18" fill="white">N</text>
    </svg>"""
    return Response(content=svg_content, media_type="image/svg+xml")

@app.get("/chat", response_class=HTMLResponse)
async def serve_chat():
    if not os.path.exists("index.html"):
        return HTMLResponse(content="<h1>Chat file not found</h1>", status_code=404)
    with open("index.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)

@app.get("/v1/admin/dashboard_data")
async def get_dashboard_data(admin_auth = Depends(verify_admin_key)):
    cookies = db.get_cookies()
    keys = db.list_api_keys()
    
    formatted_keys = []
    for k in keys:
        formatted_keys.append({
            "key": k[0],
            "name": k[1],
            "active": bool(k[2]),
            "allowed_models": k[3],
            "timeout_hours": k[4],
            "role": k[5],
            "req_per_min": k[6],
            "expires_at": k[7]
        })
        
    return {
        "status": "online",
        "cookies": {
            "psid_set": bool(cookies[0]),
            "psidts_set": bool(cookies[1]),
            "needs_update": db.get_needs_update()
        },
        "keys": formatted_keys
    }

@app.post("/v1/admin/keys/create")
async def create_key(request: KeyCreateRequest, admin_auth = Depends(verify_admin_key)):
    new_key = db.generate_api_key(
        name=request.name,
        allowed_models=request.allowed_models,
        role=request.role,
        expires_in_hours=request.expires_in_hours
    )
    return {"status": "success", "key": new_key}

@app.post("/v1/admin/keys/revoke")
async def revoke_key(request: KeyRevokeRequest, admin_auth = Depends(verify_admin_key)):
    success = db.revoke_api_key(request.key)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to revoke key or key not found")
    return {"status": "success"}

@app.post("/v1/admin/change_key")
async def change_admin_key(request: ChangeAdminKeyRequest, admin_auth = Depends(verify_admin_key)):
    old_key = admin_auth["key"]
    new_key = request.new_key.strip()
    if not new_key:
        raise HTTPException(status_code=400, detail="Khóa mới không được để trống")
    
    success, msg = db.update_admin_api_key(old_key, new_key)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}

@app.get("/v1/key_info")
async def get_key_info(auth_data: dict = Depends(verify_api_key)):
    key_name = db.get_api_key_name(auth_data["key"]) or "Unknown User"
    return {
        "key": auth_data["key"],
        "name": key_name,
        "role": auth_data["role"],
        "allowed_models": auth_data["allowed_models"]
    }