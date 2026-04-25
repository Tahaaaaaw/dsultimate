import pandas as pd
import random
from typing import List, Tuple, Optional
from urllib.parse import urlparse
from config import USER_AGENTS, SOCIAL_DOMAINS

def get_random_headers():
    """Generates random browser headers to avoid detection."""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
        "Referer": "https://www.google.com/"
    }

# ==========================================
# 1. URL & PLATFORM HELPERS
# ==========================================
def clean_social_url(url):
    """Sanitizes raw social URLs found in HTML."""
    url = url.strip().strip('"').strip("'").strip('\\')
    if url.startswith('//'): url = 'https:' + url
    elif not url.startswith('http'): url = 'https://' + url
    if '?' in url and 'profile.php' not in url:
        url = url.split('?')[0]
    return url.rstrip('/')

def identify_platform(url):
    """Categorizes a URL into a social platform if it matches."""
    try:
        url_lower = url.lower()
        # Common non-profile paths to ignore
        blocklist = ["sharer", "share.php", "login", "/p/", "/reel/", "/stories/", "intent/tweet", "dialog/feed", "developer", "policy"]
        if any(x in url_lower for x in blocklist): return None
            
        parsed = urlparse(url_lower)
        domain = parsed.netloc.replace("www.", "")
        path = parsed.path
        
        for p_domain, platform in SOCIAL_DOMAINS.items():
            if p_domain in domain:
                if path in ["", "/"]: return None 
                return platform
    except:
        pass
    return None

# ==========================================
# 2. CSV PARSING & COLUMN DETECTION
# ==========================================
def safe_read_csv(file_obj) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """Tries multiple encodings and handles bad lines gracefully."""
    encodings = ['utf-8', 'latin-1', 'iso-8859-1', 'cp1252']
    for enc in encodings:
        try:
            file_obj.seek(0)
            df = pd.read_csv(file_obj, encoding=enc, on_bad_lines='skip')
            if len(df.columns) > 1:
                return df, None
        except Exception:
            continue
    return None, "All read attempts failed. Check if file is corrupted or not a CSV."

def smart_find_column(columns: List[str], target_type: str) -> int:
    """Intelligently guesses the correct column index for Filtering."""
    cols_lower = [str(c).lower().strip() for c in columns]
    
    if target_type == "username":
        primary = ['username', 'profile', 'x1i10hfl', 'full name']
        secondary = ['name', 'user']
        for pt in primary:
            for idx, col in enumerate(cols_lower):
                if pt == col: return idx
        for st in secondary:
             for idx, col in enumerate(cols_lower):
                if st == col: return idx
        for pt in primary + secondary:
             for idx, col in enumerate(cols_lower):
                if pt in col: return idx
        return 0
        
    if target_type == "bio":
        targets = ['bio', 'desc', 'work', 'summary', 'about', 'description']
        for pt in targets:
            for idx, col in enumerate(cols_lower):
                if pt == col: return idx
        for pt in targets:
            for idx, col in enumerate(cols_lower):
                if pt in col: return idx
        return max(1, min(1, len(cols_lower)-1))
        
    return 0
