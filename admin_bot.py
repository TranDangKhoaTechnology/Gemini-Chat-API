import os
import telebot
import asyncio
import json
import re
import html
import time
import database as db
from gemini_client.core import AsyncChatbot
from gemini_client.enums import Model

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ADMIN_ID = os.environ.get("ADMIN_ID") # Your personal Telegram User ID
DATA_DIR = "data" # Ensure this matches your persistent storage path
SESSION_FILE = os.path.join(DATA_DIR, "telegram_sessions.json")

# Ensure the data directory exists
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

chat_sessions = {}
active_session_names = {} # Tracks the name of the currently loaded/saved session for auto-saving
user_models = {} # Tracks which model each admin is currently using
user_msg_map = {} # Maps admin's message ID back to source chat_id for relaying replies

# Initialize bot globally so the alert function can be exported and used by api.py
bot = telebot.TeleBot(BOT_TOKEN) if BOT_TOKEN else None

def send_admin_alert(error_context: str):
    """
    Globally accessible alert function. 
    Can be imported and called by api.py like: `from admin_bot import send_admin_alert`
    """
    if not bot or not ADMIN_ID: return
    
    alert_text = (
        "🚨 <b>GEMINI API DISCONNECTED</b> 🚨\n\n"
        "An error occurred while contacting Google Gemini. Your session cookies have likely expired.\n\n"
        f"<b>Error Log:</b>\n<code>{html.escape(str(error_context))}</code>\n\n"
        "<i>Type /setcookies to instantly trigger the update workflow.</i>"
    )
    
    try:
        bot.send_message(ADMIN_ID, alert_text, parse_mode="HTML")
    except Exception as e:
        print(f"Failed to send admin alert: {e}")

def normalize_content(content):
    if isinstance(content, list):
        def flatten(item):
            if isinstance(item, str): return item
            if isinstance(item, list): return "".join(flatten(x) for x in item if x is not None)
            return str(item)
        return flatten(content)
    if isinstance(content, dict): return str(content)
    return str(content)

def format_to_tg_html(text, is_live=False):
    """
    Transforms Gemini's markdown into strict, bulletproof Telegram HTML.
    This guarantees beautiful, unbreakable code blocks and completely prevents 
    the "Can't parse entities" crashing error by safely isolating tags.
    """
    if not text:
        return ""
        
    # 1. Temporarily close unbalanced tags for live previews
    if is_live:
        if text.count("```") % 2 != 0:
            text += "\n```"
        if text.count("`") % 2 != 0:
            text += "`"
        if text.count("**") % 2 != 0:
            text += "**"

    # 2. Safely extract Code Blocks before escaping HTML characters
    blocks = []
    def repl_block(m):
        lang = m.group(1).strip() if m.group(1) else ""
        code = m.group(2) or ""
        code = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        blocks.append(f'<pre><code class="language-{lang}">{code}</code></pre>')
        return f"@@BLOCK_{len(blocks)-1}@@"

    text = re.sub(r'```([^\n]*)\n(.*?)```', repl_block, text, flags=re.DOTALL)
    text = re.sub(r'```(.*?)```', repl_block, text, flags=re.DOTALL) 

    # 3. Safely extract Inline Code
    inline = []
    def repl_inline(m):
        code = m.group(1) or ""
        code = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        inline.append(f'<code>{code}</code>')
        return f"@@INLINE_{len(inline)-1}@@"

    text = re.sub(r'`([^`]+)`', repl_inline, text)

    # 4. Safely extract Markdown Links
    links = []
    def repl_link(m):
        txt = m.group(1).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        url = m.group(2).replace('&', '&amp;').replace('"', '%22').replace('<', '&lt;').replace('>', '&gt;')
        links.append(f'<a href="{url}">{txt}</a>')
        return f"@@LINK_{len(links)-1}@@"
    
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', repl_link, text)

    # 4b. Protect raw URLs
    raw_urls = []
    def repl_raw_url(m):
        url = m.group(0)
        safe_url = url.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        raw_urls.append(f'<a href="{safe_url}">{safe_url}</a>')
        return f"@@RAWURL_{len(raw_urls)-1}@@"
        
    text = re.sub(r'https?://[^\s<>"\'\])]+', repl_raw_url, text)

    # 5. Escape all remaining raw text
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    # 6. Apply basic typography seamlessly
    text = re.sub(r'(?m)^#{1,6}\s+(.*)$', r'<b>\1</b>', text)
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text, flags=re.DOTALL)
    text = re.sub(r'__(.*?)__', r'<u>\1</u>', text, flags=re.DOTALL)
    text = re.sub(r'~~(.*?)~~', r'<s>\1</s>', text, flags=re.DOTALL)
    text = re.sub(r'(?m)^(\s*)[*+-]\s+', r'\1• ', text)
    text = re.sub(r'(?<!\w)\*(?!\s)(.*?)(?<!\s)\*(?!\w)', r'<i>\1</i>', text, flags=re.DOTALL)
    text = re.sub(r'(?<!\w)_(?!\s)(.*?)(?<!\s)_(?!\w)', r'<i>\1</i>', text, flags=re.DOTALL)

    # 7. Restore formatting
    for i, c in enumerate(inline):
        text = text.replace(f"@@INLINE_{i}@@", c)
    for i, l in enumerate(links):
        text = text.replace(f"@@LINK_{i}@@", l)
    for i, r in enumerate(raw_urls):
        text = text.replace(f"@@RAWURL_{i}@@", r)
    for i, b in enumerate(blocks):
        text = text.replace(f"@@BLOCK_{i}@@", b)

    return text

def smart_split(text, max_length=3900):
    chunks = []
    while len(text) > max_length:
        split_at = text.rfind('\n\n', 0, max_length)
        if split_at == -1: split_at = text.rfind('\n', 0, max_length)
        if split_at == -1: split_at = text.rfind(' ', 0, max_length)
        if split_at == -1: split_at = max_length
            
        chunks.append(text[:split_at])
        text = text[split_at:]
        
    if text:
        chunks.append(text)
        
    fixed_chunks = []
    in_code = False
    lang = ""
    
    for chunk in chunks:
        if in_code:
            chunk = f"```{lang}\n" + chunk
            
        blocks = chunk.split("```")
        if len(blocks) % 2 == 0:
            in_code = not in_code
            if in_code:
                lang = blocks[-1].split('\n')[0].strip()
            chunk += "\n```"
            
        fixed_chunks.append(chunk)
        
    return fixed_chunks

if bot:
    def is_admin(message):
        return str(message.from_user.id) == str(ADMIN_ID)

    @bot.message_handler(commands=['upload'])
    def upload_instructions(message):
        if not is_admin(message): return
        bot.reply_to(message, "Please send me the <code>database.db</code> or <code>telegram_sessions.json</code> file directly to update the system.", parse_mode="HTML")

    @bot.message_handler(commands=['backup', 'download'])
    def download_backup_files(message):
        if not is_admin(message): return
        
        db_path = os.path.join(DATA_DIR, "database.db")
        session_path = SESSION_FILE
        
        bot.send_message(message.chat.id, "📦 <b>Preparing your backup...</b>", parse_mode="HTML")
        
        files_sent = 0
        
        # Send Database
        if os.path.exists(db_path):
            with open(db_path, 'rb') as f:
                bot.send_document(message.chat.id, f, caption="🗄 <b>database.db</b> Backup", parse_mode="HTML")
            files_sent += 1
        else:
            bot.send_message(message.chat.id, "⚠️ <code>database.db</code> not found.", parse_mode="HTML")
            
        # Send Sessions
        if os.path.exists(session_path):
            with open(session_path, 'rb') as f:
                bot.send_document(message.chat.id, f, caption="💬 <b>telegram_sessions.json</b> Backup", parse_mode="HTML")
            files_sent += 1
        else:
            bot.send_message(message.chat.id, "⚠️ <code>telegram_sessions.json</code> not found.", parse_mode="HTML")
            
        if files_sent > 0:
            bot.send_message(message.chat.id, "✅ <b>Backup complete!</b>", parse_mode="HTML")

    @bot.message_handler(content_types=['document'])
    def handle_file_upload(message):
        if not is_admin(message): return
        
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        filename = message.document.file_name
        target_path = os.path.join(DATA_DIR, filename)

        if filename in ["database.db", "telegram_sessions.json"]:
            try:
                with open(target_path, 'wb') as new_file:
                    new_file.write(downloaded_file)
                bot.reply_to(message, f"✅ Successfully updated <code>{filename}</code>. Please restart the bot if necessary.", parse_mode="HTML")
            except Exception as e:
                bot.reply_to(message, f"❌ Error saving file: {e}")
        else:
            bot.reply_to(message, "❌ Invalid file. Only <code>database.db</code> and <code>telegram_sessions.json</code> are accepted.", parse_mode="HTML")

    @bot.message_handler(commands=['start', 'help'])
    def send_welcome(message):
        if not is_admin(message): return
        welcome_msg = (
            "💠 <b>Gemini Nexus System</b> 💠\n\n"
            "Welcome, Admin. Use the following commands to interact with the neural network:\n\n"
            "💬 <b>Chat & Interaction</b>\n"
            "• /chat - Start a new chat session\n"
            "• /end - End the current chat\n\n"
            "📂 <b>Session Management</b>\n"
            "• /save &lt;name&gt; - Save current session\n"
            "• /sessions - View saved sessions\n"
            "• /load &lt;name&gt; - Resume a session\n"
            "• /upload - Upload db or session files\n"
            "• /backup - Download database and session files\n"
            "• /settimeout &lt;key&gt; &lt;hours&gt; - Set session expiry time\n\n"
            "🧠 <b>Model Configuration</b>\n"
            "• /models - View available AI models\n"
            "• /setmodel &lt;name&gt; - Change active model\n\n"
            "🔑 <b>API & Security</b>\n"
            "• /newadminkey [name] - Generate an Admin API key\n"
            "• /newkey [name] - Generate a Standard API key\n"
            "• /listkeys - View all API keys\n"
            "• /revoke &lt;key&gt; - Revoke an API key\n"
            "• /setcookies - Update auth cookies\n"
            "• /ratelimit &lt;key&gt; &lt;rpm&gt; - Set specific API rate limit\n"
            "• /globalratelimit &lt;rpm&gt; - Set default rate limit for new keys\n\n"
            "📡 <b>System Status</b>\n"
            "• /health - Check connection health"
        )
        bot.reply_to(message, welcome_msg, parse_mode="HTML")

    @bot.message_handler(commands=['save'])
    def save_session_command(message):
        if not is_admin(message): return
        if message.from_user.id not in chat_sessions:
            bot.reply_to(message, "❌ You must be in an active <code>/chat</code> to save a session.", parse_mode="HTML")
            return
        
        args = message.text.split()[1:]
        if not args:
            bot.reply_to(message, "Usage: <code>/save &lt;session_name&gt;</code>", parse_mode="HTML")
            return
            
        name = " ".join(args)
        state = chat_sessions[message.from_user.id]
        
        try:
            with open(SESSION_FILE, "r") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
            
        data[name] = state
        with open(SESSION_FILE, "w") as f:
            json.dump(data, f)
            
        active_session_names[message.from_user.id] = name
        bot.reply_to(message, f"✅ Chat session saved as: <b>{name}</b>\n<i>Subsequent messages will auto-save to this session.</i>", parse_mode="HTML")

    @bot.message_handler(commands=['sessions'])
    def list_sessions_command(message):
        if not is_admin(message): return
        try:
            with open(SESSION_FILE, "r") as f:
                data = json.load(f)
            if not data: raise FileNotFoundError
            
            text = "📜 <b>Saved Chat Sessions:</b>\n\n"
            for name in data.keys():
                text += f"• <code>{name}</code>\n"
            text += "\nUse <code>/load &lt;name&gt;</code> to resume a session."
            bot.send_message(message.chat.id, text, parse_mode="HTML")
        except (FileNotFoundError, json.JSONDecodeError):
            bot.send_message(message.chat.id, "No saved sessions found.", parse_mode="HTML")

    @bot.message_handler(commands=['load'])
    def load_session_command(message):
        if not is_admin(message): return
        args = message.text.split()[1:]
        if not args:
            bot.reply_to(message, "Usage: <code>/load &lt;session_name&gt;</code>", parse_mode="HTML")
            return
            
        name = " ".join(args)
        try:
            with open(SESSION_FILE, "r") as f:
                data = json.load(f)
            
            if name in data:
                chat_sessions[message.from_user.id] = data[name]
                active_session_names[message.from_user.id] = name
                bot.reply_to(message, f"📂 <b>Session loaded:</b> <code>{name}</code>\n\nYou are now in chat mode. Anything you type will continue this conversation and will <b>auto-save</b> to this session.", parse_mode="HTML")
            else:
                bot.reply_to(message, f"❌ Session <code>{name}</code> not found.", parse_mode="HTML")
        except (FileNotFoundError, json.JSONDecodeError):
            bot.reply_to(message, "No saved sessions found.")

    @bot.message_handler(commands=['models'])
    def list_models_command(message):
        if not is_admin(message): return
        text = "🧠 <b>Available Gemini Models:</b>\n\n"
        for m in Model:
            if m == Model.UNSPECIFIED: continue
            text += f"• <code>{m.model_name}</code>\n"
        text += "\nUse <code>/setmodel &lt;model_name&gt;</code> to change your active chat model."
        bot.send_message(message.chat.id, text, parse_mode="HTML")

    @bot.message_handler(commands=['setmodel'])
    def set_model_command(message):
        if not is_admin(message): return
        args = message.text.split()[1:]
        if not args:
            bot.reply_to(message, "Usage: <code>/setmodel &lt;model_name&gt;</code>", parse_mode="HTML")
            return
        
        model_name = args[0]
        try:
            selected_model = Model.from_name(model_name)
            user_models[message.from_user.id] = selected_model
            bot.reply_to(message, f"✅ Active model set to: <b>{model_name}</b>", parse_mode="HTML")
        except ValueError:
            bot.reply_to(message, f"❌ Unknown model: <code>{model_name}</code>.", parse_mode="HTML")

    @bot.message_handler(commands=['chat'])
    def start_chat(message):
        if not is_admin(message): return
        chat_sessions[message.from_user.id] = {'cid': '', 'rid': '', 'chid': ''}
        active_session_names.pop(message.from_user.id, None)
        current_model = user_models.get(message.from_user.id, Model.G_3_1_FLASH_LITE).model_name
        
        bot.send_message(message.chat.id, f"💬 <b>Chat session started!</b>\n\nStreaming from: <code>{current_model}</code>\n\nType /end to exit chat mode.", parse_mode="HTML")

    @bot.message_handler(commands=['end'])
    def end_chat(message):
        if not is_admin(message): return
        if message.from_user.id in chat_sessions:
            del chat_sessions[message.from_user.id]
            active_session_names.pop(message.from_user.id, None)
            bot.send_message(message.chat.id, "🛑 <b>Chat session ended.</b> You are back to normal admin mode.", parse_mode="HTML")
        else:
            bot.send_message(message.chat.id, "You are not currently in an active chat session.", parse_mode="HTML")

    @bot.message_handler(func=lambda m: is_admin(m) and m.from_user.id in chat_sessions and not m.text.startswith('/'))
    def handle_chat_message(message):
        cookies = db.get_cookies()
        if not cookies or not cookies[0]:
            bot.reply_to(message, "❌ Cookies not set.", parse_mode="HTML")
            return

        session_state = chat_sessions[message.from_user.id]
        current_model = user_models.get(message.from_user.id, Model.G_3_1_FLASH_LITE)
        
        sent_msg = bot.reply_to(message, "⏳ <i>Processing...</i>", parse_mode="HTML")

        async def stream_gemini():
            chatbot = await AsyncChatbot.create(cookies[0], cookies[1], model=current_model)
            
            if session_state['cid']:
                chatbot.conversation_id = session_state['cid']
                chatbot.response_id = session_state['rid']
                chatbot.choice_id = session_state['chid']
            
            try:
                active_msg_ids = [sent_msg.message_id]
                last_text = ""
                last_images = []
                last_sources = [] # NEW: Array to collect web sources
                update_counter = 0
                
                async for chunk in chatbot.ask_stream(message.text):
                    if chunk.get("error"):
                        error_msg = chunk.get('content', 'Unknown Error')
                        bot.edit_message_text(f"❌ <b>Error:</b> {html.escape(error_msg)}", chat_id=message.chat.id, message_id=active_msg_ids[-1], parse_mode="HTML")
                        
                        if any(kw in error_msg.lower() for kw in ["cookie", "snlm0e", "auth", "permission", "status: 40", "status: 50"]):
                            send_admin_alert(error_msg)
                        return

                    if chunk.get("images"):
                        last_images = chunk["images"]

                    if chunk.get("sources"):
                        last_sources = chunk["sources"]

                    raw_content = chunk.get("content", "")
                    reply_text = normalize_content(raw_content)
                    
                    if reply_text and reply_text != last_text:
                        update_counter += 1
                        
                        if update_counter % 5 == 0:
                            chunks = smart_split(reply_text)
                            
                            while len(chunks) > len(active_msg_ids):
                                prev_idx = len(active_msg_ids) - 1
                                final_prev_text = format_to_tg_html(chunks[prev_idx], is_live=False)
                                try:
                                    bot.edit_message_text(final_prev_text, chat_id=message.chat.id, message_id=active_msg_ids[prev_idx], parse_mode="HTML")
                                except Exception:
                                    pass
                                
                                new_msg = bot.send_message(message.chat.id, "⏳ <i>Continuing generation...</i>", parse_mode="HTML")
                                active_msg_ids.append(new_msg.message_id)
                                
                            last_idx = len(chunks) - 1
                            display_text = format_to_tg_html(chunks[last_idx], is_live=True)
                            
                            try:
                                bot.edit_message_text(display_text, chat_id=message.chat.id, message_id=active_msg_ids[last_idx], parse_mode="HTML")
                            except Exception:
                                pass
                                
                        last_text = reply_text

                session_state['cid'] = chatbot.conversation_id
                session_state['rid'] = chatbot.response_id
                session_state['chid'] = chatbot.choice_id
                
                active_name = active_session_names.get(message.from_user.id)
                if active_name:
                    try:
                        with open(SESSION_FILE, "r") as f:
                            data = json.load(f)
                    except (FileNotFoundError, json.JSONDecodeError):
                        data = {}
                    data[active_name] = session_state
                    with open(SESSION_FILE, "w") as f:
                        json.dump(data, f)
                
                final_text = last_text if last_text else "No content returned."
                
                # --- RENDER WEB SOURCES (NEW) ---
                if last_sources:
                    sources_html = "\n\n🔗 <b>Sources:</b>\n"
                    seen_urls = set()
                    count = 0
                    for src in last_sources:
                        url = src.get("url", "")
                        title = src.get("title", url)
                        if url not in seen_urls:
                            seen_urls.add(url)
                            sources_html += f"• <a href='{url}'>{html.escape(title)}</a>\n"
                            count += 1
                            if count >= 6: break # Prevent massive text blocks
                    final_text += sources_html
                    
                chunks = smart_split(final_text)
                
                while len(chunks) > len(active_msg_ids):
                    new_msg = bot.send_message(message.chat.id, "⏳...", parse_mode="HTML")
                    active_msg_ids.append(new_msg.message_id)
                    
                for i, chunk in enumerate(chunks):
                    display_chunk = format_to_tg_html(chunk, is_live=False)
                    try:
                        bot.edit_message_text(display_chunk, chat_id=message.chat.id, message_id=active_msg_ids[i], parse_mode="HTML")
                    except Exception as e:
                        try:
                            safe_fallback = chunk.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                            bot.edit_message_text(safe_fallback, chat_id=message.chat.id, message_id=active_msg_ids[i], parse_mode="HTML")
                        except Exception:
                            pass
                
                # =======================================================
                # ASYNC HIGH-SPEED IMAGE RENDERER
                # =======================================================
                if last_images:
                    bot.send_chat_action(message.chat.id, 'upload_photo')
                    for img in last_images:
                        try:
                            img_url = img.url if hasattr(img, 'url') else img.get('url')
                            img_title = img.title if hasattr(img, 'title') else img.get('title', 'Generated Image')
                            
                            img_resp = await chatbot.session.get(img_url, timeout=20)
                            
                            if img_resp.status_code == 200:
                                bot.send_photo(message.chat.id, photo=img_resp.content, caption=f"✨ {img_title}")
                            else:
                                bot.send_message(message.chat.id, f"<a href='{img_url}'>🖼 {img_title}</a>", parse_mode="HTML")
                                
                        except Exception:
                            try:
                                fallback_url = img.url if hasattr(img, 'url') else img.get('url')
                                fallback_title = img.title if hasattr(img, 'title') else img.get('title', 'Image')
                                bot.send_message(message.chat.id, f"<a href='{fallback_url}'>🖼 {fallback_title}</a>", parse_mode="HTML")
                            except Exception:
                                pass

            finally:
                await chatbot.session.close()

        asyncio.run(stream_gemini())

    @bot.message_handler(commands=['newadminkey'])
    def generate_admin_key_command(message):
        if not is_admin(message): return
        args = message.text.split()[1:]
        name = args[0] if args else "Chrome-Extension-Admin"
        
        new_key = db.generate_api_key(name, "all", role="admin")
        bot.reply_to(message, f"🛡 <b>ADMIN API Key Generated:</b> {name}\n\n<code>{new_key}</code>\n\n<i>Provide this to your Chrome Extension for secure auto-sync access. Do not share this key with normal API users.</i>", parse_mode="HTML")

    @bot.message_handler(commands=['newkey'])
    def generate_key_start(message):
        if not is_admin(message): return
        args = message.text.split()[1:]
        name = args[0] if args else "Default"
        
        msg = bot.reply_to(message, "🛠 <b>API Key Configuration</b>\n\nWhat models should this API key have access to?\n\n• Type <code>all</code> for full access.\n• Or type a comma-separated list like:\n<code>gemini-3.5-flash,gemini-3.1-pro</code>", parse_mode="HTML")
        bot.register_next_step_handler(msg, process_newkey_models, name)

    def process_newkey_models(message, name):
        if not is_admin(message): return
        if message.text.startswith('/'):
            bot.reply_to(message, "❌ Key generation cancelled.", parse_mode="HTML")
            return
            
        allowed_models = message.text.strip().lower()
        msg = bot.reply_to(message, "⏳ <b>Set Expiry Time</b>\n\nEnter the duration until this key expires. You can use formats like:\n\n• <code>1 week</code>, <code>1 month</code>, <code>2 days</code>, or <code>12 hours</code>.\n• Type <code>0</code> or <code>permanent</code> for a <b>Permanent</b> key.", parse_mode="HTML")
        bot.register_next_step_handler(msg, process_newkey_expiry, name, allowed_models)

    def process_newkey_expiry(message, name, allowed_models):
        if not is_admin(message): return
        if message.text.startswith('/'):
            bot.reply_to(message, "❌ Key generation cancelled.", parse_mode="HTML")
            return
            
        text = message.text.strip().lower()
        expires_in_hours = 0.0
        
        try:
            if text in ['0', 'permanent', 'none', 'never']:
                expires_in_hours = 0.0
            else:
                match = re.match(r'^([\d.]+)\s*([a-z]+)?$', text)
                if match:
                    val = float(match.group(1))
                    unit = match.group(2)
                    
                    if not unit or unit.startswith('h'): # hours
                        expires_in_hours = val
                    elif unit.startswith('d'): # days
                        expires_in_hours = val * 24
                    elif unit.startswith('w'): # weeks
                        expires_in_hours = val * 24 * 7
                    elif unit.startswith('m'): # months (approx 30 days)
                        expires_in_hours = val * 24 * 30
                    elif unit.startswith('y'): # years
                        expires_in_hours = val * 24 * 365
                    else:
                        raise ValueError()
                else:
                    raise ValueError()
        except ValueError:
            bot.reply_to(message, "❌ Invalid time format. Please use digits like '1 day', '12 hours', or '1 month'. Key generation cancelled.", parse_mode="HTML")
            return

        new_key = db.generate_api_key(name, allowed_models, role="user", expires_in_hours=expires_in_hours)
        
        if expires_in_hours <= 0:
            expiry_text = "Permanent"
        elif expires_in_hours >= 720:
            expiry_text = f"{round(expires_in_hours / 720, 1)} month(s)"
        elif expires_in_hours >= 168:
            expiry_text = f"{round(expires_in_hours / 168, 1)} week(s)"
        elif expires_in_hours >= 24:
            expiry_text = f"{round(expires_in_hours / 24, 1)} day(s)"
        else:
            expiry_text = f"{expires_in_hours} hour(s)"
            
        bot.reply_to(message, f"✅ <b>Standard API Key Generated for:</b> {name}\n\n<code>{new_key}</code>\n\n<b>Allowed Models:</b> <code>{allowed_models}</code>\n<b>Expiry:</b> <code>{expiry_text}</code>", parse_mode="HTML")

    @bot.message_handler(commands=['listkeys'])
    def list_keys(message):
        if not is_admin(message): return
        keys = db.list_api_keys()
        if not keys:
            bot.reply_to(message, "No keys found.")
            return
        text = "🔑 <b>API Keys:</b>\n\n"
        for k, name, active, allowed_models, timeout, role, rpm, expires_at in keys:
            status = "🟢 Active" if active else "🔴 Revoked"
            
            if active and expires_at > 0:
                if time.time() > expires_at:
                    status = "🔴 Expired"
                else:
                    # Convert the timestamp into a human-readable live time string
                    live_time_str = time.strftime('%b %d, %Y %I:%M %p', time.localtime(expires_at))
                    hours_left = round((expires_at - time.time()) / 3600, 1)
                    
                    if hours_left > 720:
                        status += f" (Expires: {live_time_str} | {round(hours_left/720, 1)}mo left)"
                    elif hours_left > 168:
                        status += f" (Expires: {live_time_str} | {round(hours_left/168, 1)}w left)"
                    elif hours_left > 24:
                        status += f" (Expires: {live_time_str} | {round(hours_left/24, 1)}d left)"
                    else:
                        status += f" (Expires: {live_time_str} | {hours_left}h left)"
            elif active:
                status += " (Permanent)"
                
            role_icon = "🛡" if role == 'admin' else "👤"
            text += f"{role_icon} <b>{name}</b> ({role.upper()}) - {status}\n<code>{k}</code>\nModels: <code>{allowed_models}</code>\nSession Timeout: <code>{timeout} hours</code>\nRate Limit: <code>{rpm} RPM</code>\n\n"
        bot.reply_to(message, text, parse_mode="HTML")


    @bot.message_handler(commands=['ratelimit'])
    def set_key_ratelimit(message):
        if not is_admin(message): return
        args = message.text.split()[1:]
        
        if len(args) < 2:
            bot.reply_to(message, "Usage: <code>/ratelimit &lt;key_name&gt; &lt;requests_per_min&gt;</code>\nExample: <code>/ratelimit Default 30</code>", parse_mode="HTML")
            return
            
        name = args[0]
        try:
            rpm = int(args[1])
        except ValueError:
            bot.reply_to(message, "❌ Requests per minute must be a valid number (e.g. 60).", parse_mode="HTML")
            return
            
        success = db.set_key_rate_limit(name, rpm)
        if success:
            bot.reply_to(message, f"✅ Rate limit for <b>{name}</b> updated to <b>{rpm} requests per minute</b>.", parse_mode="HTML")
        else:
            bot.reply_to(message, f"❌ Key name <b>{name}</b> not found.", parse_mode="HTML")

    @bot.message_handler(commands=['globalratelimit'])
    def set_global_ratelimit(message):
        if not is_admin(message): return
        args = message.text.split()[1:]
        
        if len(args) < 1:
            current = db.get_global_rate_limit()
            bot.reply_to(message, f"Usage: <code>/globalratelimit &lt;requests_per_min&gt;</code>\nCurrent Global Limit: <b>{current} RPM</b>", parse_mode="HTML")
            return
            
        try:
            rpm = int(args[0])
        except ValueError:
            bot.reply_to(message, "❌ Requests per minute must be a valid integer.", parse_mode="HTML")
            return
            
        db.set_global_rate_limit(rpm)
        bot.reply_to(message, f"✅ Global default rate limit updated to <b>{rpm} requests per minute</b>. This will apply to all newly generated API keys.", parse_mode="HTML")

    @bot.message_handler(commands=['settimeout'])
    def set_key_timeout(message):
        if not is_admin(message): return
        args = message.text.split()[1:]
        
        if len(args) < 2:
            bot.reply_to(message, "Usage: <code>/settimeout &lt;key_name&gt; &lt;hours&gt;</code>\nExample: <code>/settimeout Default 24</code>", parse_mode="HTML")
            return
            
        name = args[0]
        try:
            hours = float(args[1])
        except ValueError:
            bot.reply_to(message, "❌ Hours must be a valid number (e.g. 1, 24, 72).", parse_mode="HTML")
            return
            
        success = db.set_key_timeout(name, hours)
        if success:
            bot.reply_to(message, f"✅ Session timeout for <b>{name}</b> updated to <b>{hours} hours</b>.", parse_mode="HTML")
        else:
            bot.reply_to(message, f"❌ Key name <b>{name}</b> not found.", parse_mode="HTML")

    @bot.message_handler(commands=['revoke'])
    def revoke_key(message):
        if not is_admin(message): return
        args = message.text.split()[1:]
        if not args:
            bot.reply_to(message, "Provide a key to revoke: <code>/revoke sk-...</code>", parse_mode="HTML")
            return
        success = db.revoke_api_key(args[0])
        bot.reply_to(message, "✅ Key revoked." if success else "❌ Key not found.", parse_mode="HTML")

    @bot.message_handler(commands=['setcookies'])
    def set_cookies_start(message):
        if not is_admin(message): return
        
        args = message.text.split()[1:]
        if len(args) == 2:
            db.update_cookies(args[0], args[1])
            bot.reply_to(message, "✅ Cookies updated successfully in database.", parse_mode="HTML")
            return
            
        msg = bot.reply_to(message, "🍪 <b>Let's update your Gemini cookies.</b>\n\nPlease send me your <code>__Secure-1PSID</code> cookie value:", parse_mode="HTML")
        bot.register_next_step_handler(msg, process_1psid_step)

    def process_1psid_step(message):
        if not is_admin(message): return
        
        if message.text.startswith('/'):
            bot.reply_to(message, "❌ Cookie update cancelled.", parse_mode="HTML")
            return
            
        first_cookie = message.text.strip()
        msg = bot.reply_to(message, "Great! ✅\n\nNow send me your <code>__Secure-1PSIDTS</code> cookie value\n<i>(Or type <code>none</code> if you don't have one)</i>:", parse_mode="HTML")
        bot.register_next_step_handler(msg, process_1psidts_step, first_cookie)

    def process_1psidts_step(message, first_cookie):
        if not is_admin(message): return
        
        if message.text.startswith('/') and message.text.lower() != '/none':
            bot.reply_to(message, "❌ Cookie update cancelled.", parse_mode="HTML")
            return
            
        second_cookie = message.text.strip()
        if second_cookie.lower() == 'none':
            second_cookie = ""
            
        db.update_cookies(first_cookie, second_cookie)
        bot.reply_to(message, "✅ <b>Cookies updated successfully!</b>\nYour Gemini connection is now ready.", parse_mode="HTML")

    @bot.message_handler(commands=['health'])
    def check_health(message):
        if not is_admin(message): return
        current_model = user_models.get(message.from_user.id, Model.G_3_1_FLASH_LITE)
        bot.send_message(message.chat.id, f"🔄 Testing connection to <code>{current_model.model_name}</code>...", parse_mode="HTML")
        
        cookies = db.get_cookies()
        if not cookies or not cookies[0]:
            bot.send_message(message.chat.id, "❌ Cookies not set.", parse_mode="HTML")
            return
        
        try:
            async def test_bot():
                chatbot = await AsyncChatbot.create(cookies[0], cookies[1], model=current_model)
                await chatbot.session.close()
            asyncio.run(test_bot())
            bot.send_message(message.chat.id, "✅ Health Check Passed! Gemini is reachable.", parse_mode="HTML")
        except Exception as e:
            error_str = str(e)
            bot.send_message(message.chat.id, f"❌ Health Check Failed:\n\n<code>{html.escape(error_str)}</code>", parse_mode="HTML")
            
            # Trigger smart admin alert for connection issues
            if any(kw in error_str.lower() for kw in ["cookie", "snlm0e", "auth", "permission", "status: 40", "status: 50"]):
                send_admin_alert(error_str)

    # ==========================================
    # RELAY / BROADCAST SYSTEM (Bot as a Proxy)
    # ==========================================
    @bot.message_handler(func=lambda m: not is_admin(m) and m.chat.type == "private")
    def handle_user_message(message):
        """Forwards any message sent by a non-admin (in DMs) to the admin"""
        sender_info = f"{message.from_user.first_name} (@{message.from_user.username})" if message.from_user.username else f"{message.from_user.first_name}"
        msg_text = message.text or "[Media / Non-text message]"
        
        fwd_msg = bot.send_message(
            ADMIN_ID, 
            f"📩 <b>New Message from {sender_info}</b>\nUser ID: <code>{message.chat.id}</code>\n\n{html.escape(msg_text)}\n\n<i>Reply to this message to send a response back.</i>", 
            parse_mode="HTML"
        )
        user_msg_map[fwd_msg.message_id] = message.chat.id

    @bot.message_handler(func=lambda m: is_admin(m) and m.reply_to_message and m.reply_to_message.message_id in user_msg_map)
    def reply_to_forwarded_user(message):
        """Admin replies directly to the forwarded message in Telegram"""
        target_chat_id = user_msg_map[message.reply_to_message.message_id]
        try:
            bot.send_message(target_chat_id, f"👨‍💻 <b>Admin Reply:</b>\n\n{message.text}", parse_mode="HTML")
            bot.reply_to(message, f"✅ <b>Reply successfully sent to user ID {target_chat_id}!</b>", parse_mode="HTML")
        except Exception as e:
            bot.reply_to(message, f"❌ <b>Failed to send reply:</b>\n<code>{e}</code>", parse_mode="HTML")

    @bot.message_handler(commands=['send'])
    def send_to_chat(message):
        """Send a message manually to any chat ID"""
        if not is_admin(message): return
        args = message.text.split(" ", 2)
        if len(args) < 3:
            bot.reply_to(message, "Usage: <code>/send &lt;chat_id&gt; &lt;message&gt;</code>", parse_mode="HTML")
            return
            
        chat_id = args[1]
        msg_text = args[2]
        
        try:
            bot.send_message(chat_id, f"👨‍💻 <b>Admin Message:</b>\n\n{msg_text}", parse_mode="HTML")
            bot.reply_to(message, f"✅ <b>Message successfully sent to {chat_id}!</b>", parse_mode="HTML")
        except Exception as e:
            bot.reply_to(message, f"❌ <b>Failed to send message:</b>\n<code>{e}</code>", parse_mode="HTML")

def run_bot():
    if not bot:
        print("⚠️ TELEGRAM_BOT_TOKEN not found in environment variables. Telegram Bot is disabled.")
        return
    print("Starting Telegram Admin Bot...")
    bot.infinity_polling()