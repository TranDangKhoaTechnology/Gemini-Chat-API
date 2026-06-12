from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import List, Optional, Union, Dict, Any
import time
import uuid
import base64
import json
import os

import database as db
from gemini_client.core import AsyncChatbot
from gemini_client.enums import Model

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

def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)):
    details = db.get_api_key_details(credentials.credentials)
    if not details or not details[0]: 
        raise HTTPException(status_code=401, detail="Invalid or deactivated API Key")
        
    # EXPIRE CHECK
    if details[3] > 0 and time.time() > details[3]:
        raise HTTPException(status_code=401, detail="API Key has expired")

    # ENFORCE RATE LIMITS
    if not db.check_rate_limit(credentials.credentials):
        raise HTTPException(
            status_code=429, 
            detail="Rate limit exceeded. Please wait before making more requests."
        )
    return {"key": credentials.credentials, "allowed_models": details[1], "role": details[2]}

def verify_admin_key(credentials: HTTPAuthorizationCredentials = Depends(security)):
    details = db.get_api_key_details(credentials.credentials)
    if not details or not details[0]: 
        raise HTTPException(status_code=401, detail="Invalid or deactivated API Key")
        
    # EXPIRE CHECK
    if details[3] > 0 and time.time() > details[3]:
        raise HTTPException(status_code=401, detail="API Key has expired")

    if details[2] != 'admin':
        raise HTTPException(status_code=403, detail="API Key lacks 'admin' permissions required for this endpoint")
    return {"key": credentials.credentials}

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
                            for img in raw_imgs:
                                if hasattr(img, 'url'):
                                    safe_imgs.append({"url": img.url, "title": getattr(img, 'title', 'Image')})
                                elif isinstance(img, dict) and 'url' in img:
                                    safe_imgs.append({"url": img['url'], "title": img.get('title', 'Image')})
                            
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
            for img in raw_imgs:
                if hasattr(img, 'url'):
                    safe_imgs.append({"url": img.url, "title": getattr(img, 'title', 'Image')})
                elif isinstance(img, dict) and 'url' in img:
                    safe_imgs.append({"url": img['url'], "title": img.get('title', 'Image')})

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