"""gemini_client/cookie_manager.py"""
import json
from pathlib import Path
from typing import Dict, List, Set, Optional
from gemini_client.constants import (
    TARGET_COOKIES,
    SUPPORTED_BROWSERS,
)

class CookieExtractor:
    """helper class to extract coookie"""
    def __init__(self, target_cookies: Optional[List[str]] = None) -> None:
        """
        Initializes the extractor with specific target cookies.
        """
        self.cookies: Dict[str, str] = {}
        # Normalize target cookies to handle underscores/hyphens and case-insensitivity
        raw_targets = target_cookies or TARGET_COOKIES
        self.filter_set: Set[str] = {
            f"__{f.replace('_', '-')}".lower() for f in raw_targets
        }
    def _get_project_root(self) -> Path:
        """Dynamically finds the project root."""
        return Path(__file__).resolve().parent

    def extract_cookies(
        self,
        domain: str = ".google.com", 
        filename: str = "cookies.json",
        save_to_disk: bool = True
    ) -> Dict[str, str]:
        """
        Extracts and filters cookies from supported browsers.
        """
        found_raw_cookies: Dict[str, str] = {}

        # 1. Iterate through browsers and attempt extraction
        for browser_fn in SUPPORTED_BROWSERS:
            try:
                cj = browser_fn(domain_name=domain)
                current_browser_cookies = {cookie.name: cookie.value for cookie in cj}
                # Heuristic: If we found a reasonable amount of cookies, use this browser
                if len(current_browser_cookies) >= 5:
                    found_raw_cookies = current_browser_cookies # type: ignore
                    break
            except Exception:
                # Silently try the next browser if one fails
                continue

        if not found_raw_cookies:
            raise RuntimeError(
                f"No cookies found for domain {domain}. Ensure you are logged into Google."
            )

        # 2. Filter cookies using Case-Insensitive logic
        self.cookies = {
            k: v for k, v in found_raw_cookies.items() 
            if k.lower() in self.filter_set
        }

        # 3. Persistence
        if save_to_disk and self.cookies:
            output_path = self._get_project_root() / filename
            formatted_cookies = [
                {"name": k, "value": v} for k, v in self.cookies.items()
            ]
            with open(output_path, "w", encoding='utf-8') as f:
                json.dump(formatted_cookies, f, indent=4)

        return self.cookies

# if __name__ == "__main__":
#     extractor = CookieExtractor()
#     try:
#         cookie_data = extractor.extract_cookies()
#         print(f"✅ Extracted {len(cookie_data)} target cookies.")
#     except Exception as err:
#         print(f"❌ Error: {err}")
