from dotenv import load_dotenv
load_dotenv()

import threading
import uvicorn
import os
import sys
import asyncio
import database as db
from api import app
from admin_bot import run_bot

# 1. FIX WINDOWS ASYNCIO WARNING FOR CURL_CFFI
if sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

if __name__ == "__main__":
    # 2. Initialize the SQLite Database
    print("Initializing Database...")
    db.init_db()

    # 3. Always synchronize cookies from cookies.json into the DB on startup if it exists!
    # This ensures that whenever test.py works, main.py will immediately use the exact same cookies.
    if os.path.exists("cookies.json"):
        try:
            import json
            with open("cookies.json", "r", encoding="utf-8") as f:
                cookie_data = json.load(f)
            c1 = next((item['value'] for item in cookie_data if item['name'].upper() == '__SECURE-1PSID'), None)
            c2 = next((item['value'] for item in cookie_data if item['name'].upper() == '__SECURE-1PSIDTS'), None)
            if c1:
                db.update_cookies(c1, c2 or "")
                print("✅ Synchronized and updated cookies from cookies.json into the database!")
        except Exception as e:
            print(f"⚠️ Could not auto-load cookies.json: {e}")
    else:
        # Fallback check if cookies.json doesn't exist
        cookies = db.get_cookies()
        if not cookies or not cookies[0]:
            print("⚠️ Warning: No cookies found in database and cookies.json is missing.")

    # 4. Start the Telegram Bot in a background thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    # 5. Start the FastAPI Web Server on the main thread
    port = int(os.environ.get("PORT", 8000))
    print(f"Starting API Server on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)