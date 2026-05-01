import asyncio
import aiohttp
import json
import re
import logging
import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from typing import Dict, List, Tuple, Optional

# Playwright check
try:
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth
except ImportError:
    st.error("Playwright missing. Install: pip install playwright && playwright install chromium")

from config import (
    FILTER_WEIGHTS, build_word_boundary_regex, build_pool_keyword_regex, PHONE_PATTERN,
    SOCIAL_DOMAINS
)
from utils import get_random_headers, clean_social_url, identify_platform
from database import get_cached_result, save_to_cache

# ==========================================
# 1. FILTER ENGINE (Scoring Logic)
# ==========================================
class ScoringEngine:
    def __init__(self, config_data: Dict[str, list]):
        self.re_pool = build_pool_keyword_regex(config_data.get('pool', []))
        self.re_commercial = build_word_boundary_regex(config_data.get('commercial', []))
        self.re_owner = build_word_boundary_regex(config_data.get('owner', []))
        self.re_general = build_word_boundary_regex(config_data.get('general', []))
        self.re_business = build_word_boundary_regex(config_data.get('business', []))
        self.re_exclusion = build_word_boundary_regex(config_data.get('exclusion', []))

    def _has_match(self, pattern, text: str) -> bool:
        if pd.isna(text): return False
        return bool(pattern.search(str(text)))

    def extract_phone(self, text: str) -> bool:
        if pd.isna(text): return False
        return bool(PHONE_PATTERN.search(str(text)))

    def calculate_score(self, username: str, bio: str) -> int:
        score = 0
        if self._has_match(self.re_exclusion, bio) or self._has_match(self.re_exclusion, username):
            return -1
        
        # 1. Base Signals
        has_phone = self.extract_phone(bio)
        has_industry = self._has_match(self.re_pool, bio) or self._has_match(self.re_pool, username)
        
        # 2. Scoring Logic
        if has_phone: score += FILTER_WEIGHTS["PHONE_NUMBER"]
        if self._has_match(self.re_owner, bio): score += FILTER_WEIGHTS["OWNER_TITLE"]
        if self._has_match(self.re_commercial, bio): score += FILTER_WEIGHTS["COMMERCIAL_WORD"]
        if self._has_match(self.re_pool, username): score += FILTER_WEIGHTS["POOL_KEYWORD_USERNAME"]
        if self._has_match(self.re_pool, bio): score += FILTER_WEIGHTS["POOL_KEYWORD_BIO"]
        if self._has_match(self.re_business, username): score += FILTER_WEIGHTS["BUSINESS_ENTITY_USERNAME"]
        if self._has_match(self.re_general, bio): score += FILTER_WEIGHTS["GENERAL_TITLE_BIO"]
        
        # 3. ABSOLUTE PENALTY: No Industry Signal && No Phone = JUNK (-50)
        if not has_industry and not has_phone:
            score -= 50
            
        return score

    def categorize(self, username: str, bio: str) -> str:
        if self._has_match(self.re_business, username): return "🏢 Business Page"
        if self._has_match(self.re_pool, username) and not self._has_match(self.re_owner, username) and not self._has_match(self.re_general, username):
            return "🏢 Business Page"
        if self._has_match(self.re_owner, bio) or self._has_match(self.re_owner, username):
            return "👔 Owner / Decision Maker"
        return "👷 General Pro / Staff"

    def determine_failure_reason(self, username: str, bio: str) -> str:
        if self._has_match(self.re_exclusion, bio) or self._has_match(self.re_exclusion, username):
            return "Excluded (Keywords matched)"
        reasons = []
        if not self._has_match(self.re_pool, bio) and not self._has_match(self.re_pool, username):
            reasons.append("No 'Pool' Keywords")
        if not self.extract_phone(bio) and not self._has_match(self.re_commercial, bio):
            reasons.append("No Commercial Intent")
        return ", ".join(reasons) if reasons else "Score too low (Generic Profile)"

    def process_row(self, row: pd.Series, u_col: str, b_col: str) -> pd.Series:
        uname = str(row[u_col]).lower() if not pd.isna(row[u_col]) else ""
        bio_t = str(row[b_col]).lower() if not pd.isna(row[b_col]) else ""
        score = self.calculate_score(uname, bio_t)
        row['smart_score'] = score
        if score >= 0:
            row['Lead Type'] = self.categorize(uname, bio_t)
            row['fail_reason'] = ""
        else:
            row['fail_reason'] = self.determine_failure_reason(uname, bio_t)
        return row

# ==========================================
# 2. SCRAPER ENGINE (Hybrid Extraction)
# ==========================================
def extract_links_from_html(html, base_url):
    """Parses HTML for social links using soup, JSON-LD, and Regex."""
    found = set()
    soup = BeautifulSoup(html, "html.parser")
    # 1. A-Tags
    for a in soup.find_all("a", href=True):
        found.add(urljoin(base_url, a["href"].strip()))
    # 2. JSON-LD
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict) and 'sameAs' in data:
                s_as = data['sameAs']
                if isinstance(s_as, str): found.add(s_as)
                elif isinstance(s_as, list): found.update(s_as)
            elif isinstance(data, list):
                for item in data:
                    if 'sameAs' in item:
                        s_as = item['sameAs']
                        if isinstance(s_as, str): found.add(s_as)
                        elif isinstance(s_as, list): found.update(s_as)
        except Exception as e:
            logging.debug(f"JSON-LD parse error: {e}")
            pass
    # 3. Aggressive Regex
    raw = re.findall(r'(?:https?:)?//(?:www\.)?(?:facebook\.com|fb\.com|instagram\.com|instagr\.am|youtube\.com)/[^"\'\s<>,;]+', html, re.IGNORECASE)
    found.update(raw)
    
    # Filter & Categorize
    socials = {p: [] for p in set(SOCIAL_DOMAINS.values())}
    internals = set()
    b_dom = urlparse(base_url).netloc
    
    for r_link in found:
        link = clean_social_url(r_link)
        plat = identify_platform(link)
        if plat:
            if link not in socials[plat]: socials[plat].append(link)
        else:
            try:
                if b_dom in urlparse(link).netloc: internals.add(link)
            except: pass
            
    return socials, internals

async def fetch_fast(session, url):
    """Tier 1: Fast HTTP request."""
    for attempt in range(2):
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with session.get(url, headers=get_random_headers(), timeout=timeout, ssl=False, allow_redirects=True) as resp:
                if resp.status == 200: return await resp.text(errors='replace'), resp.status, None
                if resp.status in [403, 406, 503]: return "", resp.status, "Blocked"
        except Exception as e:
            if attempt == 1: 
                logging.warning(f"Fast fetch failed for {url}: {e}")
                break
            await asyncio.sleep(1)
    return "", 0, "Failed"

async def fetch_deep(browser, url):
    """Tier 2: Browser rendering fallback."""
    ctx = await browser.new_context(user_agent=get_random_headers()["User-Agent"], ignore_https_errors=True)
    page = await ctx.new_page()
    await Stealth().apply_stealth_async(page)
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        if resp and resp.status == 200:
            await asyncio.sleep(1.5) # Wait for JS scripts
            return await page.content(), resp.status, None
        return "", (resp.status if resp else 0), "Playwright Status Non-200"
    except Exception as e:
        return "", 0, f"Playwright Error: {str(e)[:50]}"
    finally:
        await ctx.close()

async def crawl_site_coordinator(session, browser, biz_name, base_url, max_depth):
    """Coordinates the multi-page crawl for a single site."""
    if not base_url.startswith(('http://', 'https://')): base_url = 'https://' + base_url.strip()
    
    # Cache Check
    cached = get_cached_result(base_url)
    if cached:
        return {**cached, "Business Name": biz_name, "Website": base_url, "Status": "Success (Cache)", "Tier Used": "Cache"}

    final_s = {p: "" for p in set(SOCIAL_DOMAINS.values())}
    visited, queue = set(), [base_url]
    for p in ['/contact', '/about']: queue.append(urljoin(base_url, p))
    
    tier_u, p_crawl, status = "Fast (aiohttp)", 0, 0
    while queue and p_crawl < max_depth:
        curr = queue.pop(0)
        if curr in visited: continue
        visited.add(curr)
        p_crawl += 1
        
        html, status, err = await fetch_fast(session, curr)
        if status in [403, 406, 500, 503] or not html:
            if browser:
                tier_u = "Deep (Playwright)"
                html, status, err = await fetch_deep(browser, curr)
                
        if not html: continue
        socials, internals = extract_links_from_html(html, curr)
        for plt, lnks in socials.items():
            if lnks and not final_s[plt]: final_s[plt] = lnks[0]
            
        if final_s["Facebook"] and final_s["Instagram"]: break
        for l in internals:
            if l not in visited and len(queue) < 15:
                if any(x in l.lower() for x in ['contact', 'about', 'connect', 'footer']): queue.insert(0, l)

    res = {
        "Business Name": biz_name, "Website": base_url, 
        "Facebook": final_s.get("Facebook", ""), "Instagram": final_s.get("Instagram", ""), 
        "YouTube": final_s.get("YouTube", ""), "Status": "Blocked" if status in [403, 406, 503] else "Success", 
        "Tier Used": tier_u
    }
    save_to_cache(res)
    return res
