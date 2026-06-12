import requests
import json
import urllib.parse
import os
import webbrowser

# --- Configuration ---
API_BASE_URL = "http://localhost:8000/v1"
API_KEY = "sk-bb72106aad16484d9790a3569ed3af8f" # Replace with a valid key from your DB
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

def get_models():
    """Fetches and displays available models from the API."""
    print("🔄 Fetching available models...")
    response = requests.get(f"{API_BASE_URL}/models", headers=HEADERS)
    
    if response.status_code != 200:
        print(f"❌ Failed to fetch models: {response.text}")
        return None

    models = response.json().get("data", [])
    print(f"✅ Found {len(models)} models:")
    for i, model in enumerate(models):
        print(f"  [{i+1}] {model['id']}")
    
    return models

def download_file(proxy_url, filename):
    """Downloads a file through our backend proxy and saves it locally."""
    print(f"\n📥 Downloading '{filename}' via proxy...")
    try:
        response = requests.get(proxy_url, headers=HEADERS, stream=True)
        response.raise_for_status()
        
        save_path = os.path.join(os.getcwd(), filename)
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                
        print(f"🎉 Success! File saved locally to: {save_path}")
    except Exception as e:
        print(f"❌ Download failed: {e}")

def create_and_open_viewer(view_url, download_url, filename):
    """Creates a temporary HTML file to demonstrate the UI viewing experience."""
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>PDF Viewer Test</title>
        <style>
            body {{ font-family: sans-serif; background: #f0f0f0; margin: 0; padding: 20px; display: flex; flex-direction: column; height: 100vh; box-sizing: border-box; }}
            .header {{ display: flex; justify-content: space-between; align-items: center; background: white; padding: 15px 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }}
            h2 {{ margin: 0; color: #333; }}
            .download-btn {{ background: #0b57d0; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; font-weight: bold; }}
            .download-btn:hover {{ background: #0842a0; }}
            .viewer-container {{ flex-grow: 1; background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); overflow: hidden; }}
            iframe {{ width: 100%; height: 100%; border: none; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h2>📄 {filename}</h2>
            <a href="{download_url}" class="download-btn" download>⬇️ Download PDF</a>
        </div>
        <div class="viewer-container">
            <iframe src="{view_url}"></iframe>
        </div>
    </body>
    </html>
    """
    
    viewer_path = os.path.join(os.getcwd(), "viewer.html")
    with open(viewer_path, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    print(f"\n👀 Opening the PDF Viewer UI in your browser...")
    file_uri = f"file:///{viewer_path.replace(os.sep, '/')}"
    try:
        webbrowser.open(file_uri)
    except Exception as e:
        print(f"⚠️ Could not automatically open browser. Open this file manually: {viewer_path}")

def request_pdf_generation(model_id):
    """Sends a request to the AI asking it to generate a PDF."""
    prompt = "Please generate a 2-page PDF document summarizing the history of the Apollo 11 moon landing."
    
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False
    }
    
    print(f"\n🚀 Sending request to model '{model_id}'...")
    print(f"📝 Prompt: \"{prompt}\"")
    
    response = requests.post(f"{API_BASE_URL}/chat/completions", headers=HEADERS, json=payload)
    
    if response.status_code != 200:
        print(f"❌ Request failed: {response.status_code} - {response.text}")
        return

    data = response.json()
    message = data['choices'][0]['message']
    
    # 1. Print the text response from the AI
    print("\n🤖 AI Response:")
    print("-" * 40)
    print(message.get('content', 'No text content returned.'))
    print("-" * 40)
    
    # 2. Check for the dynamically extracted files!
    files = message.get("files", [])
    
    if files:
        print(f"\n📂 The AI generated {len(files)} file(s)!")
        for file_info in files:
            print(f"  📄 Name: {file_info['filename']}")
            raw_url = file_info['download_url']
            
            # Create proxy URLs
            encoded_url = urllib.parse.quote(raw_url)
            
            # This URL forces a download (attachment)
            # FIXED: Added the token parameter here so the browser download button works!
            proxy_download_url = f"{API_BASE_URL}/download?url={encoded_url}&view=false&token={API_KEY}"
            
            # This URL forces inline viewing (for iframes). 
            # We pass the token in the URL because iframes cannot send the Authorization header!
            proxy_view_url = f"{API_BASE_URL}/download?url={encoded_url}&view=true&token={API_KEY}"
            
            # Action 1: Physically download the file via Python
            download_file(proxy_download_url, file_info['filename'])

            # Action 2: Trigger the HTML UI test
            create_and_open_viewer(proxy_view_url, proxy_download_url, file_info['filename'])

    else:
        print("\n⚠️ No files were detected in the response. The AI might not have generated a PDF.")

if __name__ == "__main__":
    models = get_models()
    if models:
        selected_model = models[0]['id'] 
        request_pdf_generation(selected_model)