import sqlite3
import os
import json
import io
import logging
import pandas as pd
from datetime import datetime, timedelta

SCRAPER_DB = "scraper_cache.db"
FILTER_DB = "filter_history.db"

# ==========================================
# 1. SCRAPER PERSISTENCE
# ==========================================
def init_scraper_db():
    conn = sqlite3.connect(SCRAPER_DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS leads (
                    website TEXT PRIMARY KEY,
                    business_name TEXT,
                    Facebook TEXT,
                    Instagram TEXT,
                    Twitter TEXT,
                    LinkedIn TEXT,
                    YouTube TEXT,
                    TikTok TEXT,
                    Pinterest TEXT,
                    status TEXT,
                    scraped_at TIMESTAMP
                 )''')
    conn.commit()
    conn.close()

def get_cached_result(website, max_age_days=7):
    try:
        conn = sqlite3.connect(SCRAPER_DB)
        c = conn.cursor()
        c.execute("SELECT * FROM leads WHERE website=?", (website,))
        row = c.fetchone()
        conn.close()
        
        if row:
            columns = [
                'website', 'business_name', 'Facebook', 'Instagram', 'Twitter', 
                'LinkedIn', 'YouTube', 'TikTok', 'Pinterest', 'status', 'scraped_at'
            ]
            data = dict(zip(columns, row))
            scraped_at = datetime.fromisoformat(data['scraped_at'])
            if datetime.now() - scraped_at < timedelta(days=max_age_days):
                return data
    except Exception as e:
        logging.error(f"Scraper DB Error: {e}")
    return None

def save_to_cache(data):
    try:
        conn = sqlite3.connect(SCRAPER_DB)
        c = conn.cursor()
        now = datetime.now().isoformat()
        c.execute('''INSERT OR REPLACE INTO leads 
                     (website, business_name, Facebook, Instagram, Twitter, LinkedIn, YouTube, TikTok, Pinterest, status, scraped_at) 
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                  (data['Website'], data['Business Name'], 
                   data.get('Facebook', ''), data.get('Instagram', ''), 
                   data.get('Twitter', ''), data.get('LinkedIn', ''),
                   data.get('YouTube', ''), data.get('TikTok', ''),
                   data.get('Pinterest', ''), data['Status'], now))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Scraper DB Save Error: {e}")

def clear_scraper_cache():
    if os.path.exists(SCRAPER_DB):
        os.remove(SCRAPER_DB)
    init_scraper_db()

# ==========================================
# 2. FILTER PERSISTENCE (Auto-Reload Support)
# ==========================================
def init_filter_db():
    """Initializes the filter history database."""
    conn = sqlite3.connect(FILTER_DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS filter_runs (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    passed_json TEXT,
                    failed_json TEXT,
                    stats_json TEXT,
                    u_col TEXT,
                    b_col TEXT,
                    updated_at TIMESTAMP
                 )''')
    conn.commit()
    conn.close()

def save_filter_run(results):
    """Saves the current filter state to the database."""
    try:
        init_filter_db() # Ensure table exists
        conn = sqlite3.connect(FILTER_DB)
        c = conn.cursor()
        
        # Convert DataFrames to JSON for storage
        passed_json = results['passed'].to_json(orient='records')
        failed_json = results['failed'].to_json(orient='records')
        stats_json = json.dumps(results['stats'])
        now = datetime.now().isoformat()
        
        c.execute('''INSERT OR REPLACE INTO filter_runs 
                     (id, passed_json, failed_json, stats_json, u_col, b_col, updated_at) 
                     VALUES (1, ?, ?, ?, ?, ?, ?)''', 
                  (passed_json, failed_json, stats_json, results['u_col'], results['b_col'], now))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Filter DB Save Error: {e}")

def load_latest_filter_run():
    """Loads the latest filter results if they exist."""
    try:
        if not os.path.exists(FILTER_DB): return None
        conn = sqlite3.connect(FILTER_DB)
        c = conn.cursor()
        c.execute("SELECT passed_json, failed_json, stats_json, u_col, b_col FROM filter_runs WHERE id=1")
        row = c.fetchone()
        conn.close()
        
        if row:
            return {
                "passed": pd.read_json(io.StringIO(row[0])),
                "failed": pd.read_json(io.StringIO(row[1])),
                "stats": json.loads(row[2]),
                "u_col": row[3],
                "b_col": row[4]
            }
    except Exception as e:
        logging.error(f"Filter DB Load Error: {e}")
    return None

