import requests
import json
import os
import sys

if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# Configuration
# Replace with the URL where your FastAPI app is running
API_URL = "http://127.0.0.1:8000/v1/chat/completions"

# Replace with an active API Key from your database
API_KEY = os.environ.get("MY_API_KEY", "sk-bb72106aad16484d9790a3569ed3af8f")

if API_KEY == "YOUR_API_KEY_HERE":
    print("⚠️ Warning: Please set your API_KEY in the script or via the MY_API_KEY environment variable.")

def test_image_generation_api():
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "gemini-3.1-flash-lite", # Change to whatever model you have enabled
        "messages": [
            {
                "role": "user",
                "content": "Generate a beautiful image of a futuristic cyberpunk city at night."
            }
        ],
        "stream": False # Set to False so we get one clean JSON response to parse
    }

    print(f"Sending POST request to {API_URL}...")
    try:
        response = requests.post(API_URL, headers=headers, json=payload)
        
        if response.status_code != 200:
            print(f"❌ API Error: {response.status_code}")
            print(response.text)
            sys.exit(1)

        data = response.json()
        
        # Parse the custom OpenAI-compatible response
        choices = data.get("choices", [])
        if not choices:
            print("❌ No choices returned in the response.")
            return

        message = choices[0].get("message", {})
        content = message.get("content", "")
        images = message.get("images", [])

        print("\n✅ API Response Received Successfully!")
        print("-" * 40)
        print("📝 Text Content:")
        print(content)
        print("-" * 40)
        
        if images:
            print(f"🖼️ Images Found: {len(images)}")
            for idx, img in enumerate(images):
                print(f"\n[Image {idx+1}]")
                print(f"Title: {img.get('title', 'N/A')}")
                
                # Check if the URL is our newly injected Base64 Data URI
                img_url = img.get('url', '')
                if img_url.startswith("data:image/"):
                    print(f"Status: ✅ Successfully intercepted and converted to Base64!")
                    # Print just the first 80 chars to avoid flooding the terminal
                    print(f"Base64 String Snippet: {img_url[:80]}...")
                else:
                    print(f"Status: ⚠️ Still a regular URL (Check core.py implementation)")
                    print(f"URL: {img_url}")
        else:
            print("❌ No images were returned by the model.")

    except requests.exceptions.ConnectionError:
        print("❌ Connection Error: Ensure your FastAPI server (api.py) is currently running on 127.0.0.1:8000")

if __name__ == "__main__":
    test_image_generation_api()