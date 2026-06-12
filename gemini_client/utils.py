# -*- coding: utf-8 -*-
import json
import mimetypes
from pathlib import Path
from typing import Dict, Tuple, Union, Optional

from curl_cffi import CurlError
from curl_cffi.requests import AsyncSession
from requests.exceptions import RequestException, HTTPError, Timeout

from rich.console import Console

# Assuming Endpoint and Headers enums are in 'enums.py' within the same package
from .enums import Endpoint, Headers

console = Console() # Instantiate console for logging

async def upload_file(
    file: Union[bytes, str, Path],
    proxy: Optional[Union[str, Dict[str, str]]] = None,
    impersonate: str = "chrome110"
) -> str:
    """
    Uploads a file to Google's Gemini server using curl_cffi (Resumable Upload) and returns its identifier.

    Args:
        file (bytes | str | Path): File data in bytes or path to the file to be uploaded.
        proxy (str | dict, optional): Proxy URL or dictionary for the request.
        impersonate (str, optional): Browser profile for curl_cffi to impersonate. Defaults to "chrome110".

    Returns:
        str: Identifier of the uploaded file.
    """
    # Handle file input dynamically
    if not isinstance(file, bytes):
        file_path = Path(file)
        if not file_path.is_file():
            raise FileNotFoundError(f"File not found at path: {file}")

        filename = file_path.name
        mime_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"

        with open(file_path, "rb") as f:
            file_content = f.read()
    else:
        filename = "upload.bin"
        mime_type = "application/octet-stream"
        file_content = file

    file_size = len(file_content)
    proxies_dict = None

    if isinstance(proxy, str):
        proxies_dict = {"http": proxy, "https": proxy}
    elif isinstance(proxy, dict):
        proxies_dict = proxy

    try:
        async with AsyncSession(
            proxies=proxies_dict,
            impersonate=impersonate,
        ) as client:

            # 1. Start Resumable Session
            start_headers = {
                **Headers.UPLOAD.value,
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(file_size),
                "X-Goog-Upload-Header-Content-Type": mime_type,
            }

            start_response = await client.post(
                url=Endpoint.UPLOAD.value + "/",
                headers=start_headers,
                data="",
            )
            start_response.raise_for_status()

            upload_url = (
                start_response.headers.get("X-Goog-Upload-URL")
                or start_response.headers.get("X-Goog-Upload-Control-URL")
            )

            if not upload_url:
                raise Exception("Failed to obtain upload URL")

            console.log("[green]Upload session started[/green]")

            # 2. Upload and Finalize
            upload_headers = {
                **Headers.UPLOAD.value,
                "X-Goog-Upload-Command": "upload, finalize",
                "X-Goog-Upload-Offset": "0",
            }

            upload_response = await client.post(
                url=upload_url,
                headers=upload_headers,
                data=file_content,
            )
            upload_response.raise_for_status()

            response_text = upload_response.text.strip()

            console.log("[green]Upload successful[/green]")
            console.log(f"[cyan]Upload response:[/cyan] {response_text}")

            return response_text

    except HTTPError as e:
        console.log(f"[red]HTTP upload error:[/red] {e}")
        raise
    except Timeout as e:
        console.log(f"[red]Upload timeout:[/red] {e}")
        raise
    except (RequestException, CurlError) as e:
        console.log(f"[red]Network upload error:[/red] {e}")
        raise
    except Exception as e:
        console.log(f"[red]Unexpected upload error:[/red] {e}")
        raise

def load_cookies(cookie_path: str) -> Tuple[str, str]:
    """
    Loads authentication cookies from a JSON file.

    Args:
        cookie_path (str): Path to the JSON file containing cookies.

    Returns:
        tuple[str, str]: Tuple containing __Secure-1PSID and __Secure-1PSIDTS cookie values.
    """
    try:
        with open(cookie_path, 'r', encoding='utf-8') as file:
            cookies = json.load(file)
            
        session_auth1 = next((item['value'] for item in cookies if item['name'].upper() == '__SECURE-1PSID'), None)
        session_auth2 = next((item['value'] for item in cookies if item['name'].upper() == '__SECURE-1PSIDTS'), None)

        if not session_auth1 or not session_auth2:
             raise StopIteration("Required cookies (__Secure-1PSID or __Secure-1PSIDTS) not found.")

        return session_auth1, session_auth2
    except FileNotFoundError:
        raise Exception(f"Cookie file not found at path: {cookie_path}")
    except json.JSONDecodeError:
        raise Exception("Invalid JSON format in the cookie file.")
    except StopIteration as e:
        raise Exception(f"{e} Check the cookie file format and content.")
    except Exception as e: 
        raise Exception(f"An unexpected error occurred while loading cookies: {e}")