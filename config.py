import re

# ==========================================
# 1. SCRAPER CONSTANTS
# ==========================================
SOCIAL_DOMAINS = {
    "facebook.com": "Facebook",
    "fb.com": "Facebook",
    "instagram.com": "Instagram",
    "instagr.am": "Instagram"
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36",
]

# ==========================================
# 2. FILTER CONSTANTS & KEYWORDS
# ==========================================
FILTER_WEIGHTS = {
    "PHONE_NUMBER": 40,
    "OWNER_TITLE": 20,
    "COMMERCIAL_WORD": 20,
    "POOL_KEYWORD_USERNAME": 15,
    "POOL_KEYWORD_BIO": 15,
    "BUSINESS_ENTITY_USERNAME": 15,
    "GENERAL_TITLE_BIO": 10
}

DEFAULT_POOL_KEYWORDS = [
    'pool', 'pools', 'swimming', 'spa', 'hot tub', 'jacuzzi', 'aquatic', 
    'gunite', 'fiberglass', 'vinyl', 'plaster', 'coping', 'decking', 'tile',
    'pumps', 'heaters', 'filters', 'leak detection', 'green to clean',
    'chlorine', 'salt system', 'maintenance', 'renovation', 'construction',
    'resurfacing', 'marcite', 'diamond brite', 'shotcrete', 'pebble tec'
]

DEFAULT_COMMERCIAL_KEYWORDS = [
    'licensed', 'insured', 'free estimate', 'call now', 'dm for', 'book now', 
    'serving', 'servicing', 'family owned', 'locally owned', 'commercial', 
    'residential', 'website:', 'www.', '.com', 'call/text'
]

DEFAULT_OWNER_TITLES = [
    'owner', 'ceo', 'president', 'founder', 'co-founder', 'partner', 
    'director', 'proprietor', 'principal'
]

DEFAULT_GENERAL_TITLES = [
    'contractor', 'builder', 'technician', 'tech', 'manager', 'specialist', 
    'operator', 'repairman', 'installer', 'cleaner', 'supervisor'
]

DEFAULT_BUSINESS_ENTITIES = [
    'llc', 'inc', 'co.', 'corp', 'ltd', 'solutions', 'enterprises', 
    'pool service', 'pool care', 'company'
]

DEFAULT_EXCLUSIONS = [
    'looking for', 'seeking', 'need a', 'recommendation', 'suggestion', 
    'does anyone', 'can anyone', 'help needed', 'iso', 'in search of',
    'former', 'retired', 'coach', 'instructor', 'swim school', 
    'swimming in', 'training', 'student', 'lesson', 'club', 'member',
    'realty', 'insurance', 'wellness', 'salon', 'agent', 'clinical', 
    'medical', 'auto spares', 'photography', 'social worker', 'physiotherapy'
]

# ==========================================
# 3. REGEX ENGINE
# ==========================================
PHONE_PATTERN = re.compile(r'(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}')

def build_word_boundary_regex(keywords: list) -> re.Pattern:
    """Creates an optimized regex for word boundary matching."""
    escaped = [re.escape(k) for k in keywords]
    pattern_string = r'\b(?:' + '|'.join(escaped) + r')s?\b'
    return re.compile(pattern_string, re.IGNORECASE)

def build_pool_keyword_regex(keywords: list) -> re.Pattern:
    """Creates an optimized regex for pool keywords, allowing partial matches for specific safe words."""
    strict_parts = []
    partial_parts = []
    
    # words that are safe for partial matching (e.g. bluetechpools, pooloptics)
    partial_safe = ['pool', 'pools', 'poolside', 'poolman', 'aquatic', 'jacuzzi', 'gunite', 'shotcrete', 'fiberglass']
    
    for k in keywords:
        if k.lower() in partial_safe:
            partial_parts.append(re.escape(k))
        else:
            strict_parts.append(re.escape(k))
            
    parts = []
    if strict_parts:
        parts.append(r'\b(?:' + '|'.join(strict_parts) + r')s?\b')
    if partial_parts:
        # Use lookbehind to avoid common false positives like 'liverpool', 'deadpool', 'whirlpool'
        # but allow them if they are at the start of a word or preceded by a non-letter
        pattern = r'(?<!liver)(?<!dead)(?<!whirl)(?:' + '|'.join(partial_parts) + r')s?'
        parts.append(pattern)
        
    pattern_string = '|'.join(parts)
    return re.compile(pattern_string, re.IGNORECASE)

