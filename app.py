import streamlit as st
import pandas as pd
import asyncio
import aiohttp
import sqlite3
import os
import nest_asyncio
import io
from datetime import datetime

# Local Modular Imports
from config import (
    DEFAULT_POOL_KEYWORDS, DEFAULT_COMMERCIAL_KEYWORDS, 
    DEFAULT_OWNER_TITLES, DEFAULT_GENERAL_TITLES, 
    DEFAULT_BUSINESS_ENTITIES, DEFAULT_EXCLUSIONS
)
from database import (
    init_scraper_db, clear_scraper_cache, SCRAPER_DB,
    init_filter_db, save_filter_run, load_latest_filter_run
)
from utils import safe_read_csv, smart_find_column
from engines import ScoringEngine, crawl_site_coordinator

try:
    from playwright.async_api import async_playwright
except ImportError:
    pass

nest_asyncio.apply()

# ==========================================
# 1. UI SETUP & STYLING
# ==========================================
st.set_page_config(page_title="Social Meta Suite Pro", page_icon="🎯", layout="wide")

def inject_styles():
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap');
        html, body, [class*="css"] { font-family: 'Outfit', sans-serif; }
        .main-hero {
            padding: 2.5rem; text-align: center; border-radius: 20px; color: white;
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            box-shadow: 0 10px 25px -5px rgba(0,0,0,0.5);
            border: 1px solid rgba(255,255,255,0.1); margin-bottom: 2rem;
        }
        .metric-card {
            background: rgba(15, 23, 42, 0.6); padding: 20px; border-radius: 15px;
            text-align: center; border: 1px solid rgba(255,255,255,0.05); margin-bottom: 1rem;
        }
        div[data-testid="stSidebar"] {
            background-color: rgba(15, 23, 42, 0.95);
            backdrop-filter: blur(10px);
        }
        </style>
    """, unsafe_allow_html=True)

# ==========================================
# 2. VIEW: LEAD EXTRACTION (SCRAPER)
# ==========================================
async def run_scraper_master(businesses, max_depth, concurrency):
    results = []
    st.markdown("### 📡 Live Extraction Feed")
    m_cols = st.columns(4)
    m_tot, m_fb, m_ig, m_byp = m_cols[0].empty(), m_cols[1].empty(), m_cols[2].empty(), m_cols[3].empty()
    pbar = st.progress(0)
    log_c = st.empty()
    table_p = st.empty()

    def update_ui():
        fbc = sum(1 for r in results if r.get('Facebook'))
        igc = sum(1 for r in results if r.get('Instagram'))
        bypc = sum(1 for r in results if r.get('Tier Used') == 'Deep (Playwright)')
        m_tot.metric("Processed", f"{len(results)} / {len(businesses)}")
        m_fb.metric("Facebook Hits", fbc)
        m_ig.metric("Instagram Hits", igc)
        m_byp.metric("Bot Bypassed", bypc)
        if results:
            df_l = pd.DataFrame(results)
            cols = ['Business Name', 'Website', 'Facebook', 'Instagram', 'Tier Used']
            present = [c for c in cols if c in df_l.columns]
            df_disp = df_l[present].copy()
            for c in ['Facebook', 'Instagram']:
                if c in df_disp.columns: df_disp[c] = df_disp[c].apply(lambda x: "✅ Found" if x else "❌")
            table_p.dataframe(df_disp, use_container_width=True)
            
    update_ui()
    conn_tcp = aiohttp.TCPConnector(limit=concurrency * 2, ssl=False)
    async with aiohttp.ClientSession(connector=conn_tcp, cookie_jar=aiohttp.DummyCookieJar()) as session:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            sem = asyncio.Semaphore(concurrency)
            async def bounded_crawl(b_name, b_url, tot):
                async with sem:
                    try:
                        res = await crawl_site_coordinator(session, browser, b_name, b_url, max_depth)
                        results.append(res)
                        pbar.progress(len(results) / tot)
                        t_icon = "🚀" if res['Tier Used'] == 'Fast (aiohttp)' else ("🛡️" if res['Tier Used'] == 'Deep (Playwright)' else "🗄️")
                        log_c.info(f"{t_icon} **Live Action:** `{b_name}` via **{res['Tier Used']}**")
                        update_ui()
                    except Exception as e:
                        results.append({"Business Name": b_name, "Website": b_url, "Status": f"Error: {str(e)[:20]}", "Tier Used": "Failed"})
                        update_ui()
            
            tasks = [asyncio.create_task(bounded_crawl(n, u, len(businesses))) for n, u in businesses]
            await asyncio.gather(*tasks)
            await browser.close()
    return results

def render_scraper_view(concurrency, max_depth):
    init_scraper_db()
    st.markdown("<div class='main-hero'><h1>⚡ Ultimate Social Scraper</h1><p>Hybrid Engine: Lightning Fast + Deep Rendering Anti-Bot Bypasses</p></div>", unsafe_allow_html=True)
    
    t_hub, t_cfg, t_db = st.tabs(["🎯 Extraction Hub", "⚙️ Settings", "🗄️ Cache Database"])
    
    with t_cfg:
        st.info("💡 Adjust scraper performance in the sidebar.")
        if st.button("🗑️ Purge Scraper Cache"):
            clear_scraper_cache()
            st.success("Cache cleared.")

    with t_db:
        try:
            conn = sqlite3.connect(SCRAPER_DB)
            df_c = pd.read_sql_query("SELECT * FROM leads", conn)
            conn.close()
            st.dataframe(df_c, use_container_width=True)
        except: st.warning("No cache table found.")

    with t_hub:
        src = st.radio("List Source:", ["CSV Upload", "Manual Entry"], horizontal=True)
        targets = []
        if src == "Manual Entry":
            c1, c2 = st.columns(2)
            n_raw = c1.text_area("Names")
            u_raw = c2.text_area("URLs")
            if n_raw and u_raw:
                nl, ul = [x.strip() for x in n_raw.split('\n')], [x.strip() for x in u_raw.split('\n')]
                if len(nl) == len(ul): targets = list(zip(nl, ul))
        else:
            up = st.file_uploader("Upload CSV", type=['csv'], key="sc_up")
            if up:
                has_header = st.checkbox("CSV has a header row", value=True, key="sc_has_header")
                df = pd.read_csv(up, header=0 if has_header else None)
                if not has_header:
                    df.columns = [f"Column {i+1}" for i in range(len(df.columns))]
                st.dataframe(df.head(3))
                ncol, ucol = None, None
                for c in df.columns:
                    if any(x in str(c).lower() for x in ['name', 'company']) and not ncol: ncol = c
                    if any(x in str(c).lower() for x in ['url', 'web', 'site']) and not ucol: ucol = c
                sel_n = st.selectbox("Name Col:", df.columns, index=list(df.columns).index(ncol) if ncol else 0)
                sel_u = st.selectbox("URL Col:", df.columns, index=list(df.columns).index(ucol) if ucol else 0)
                if st.button("Prepare List"):
                    vld = df[df[sel_u].notna()]
                    st.session_state.sc_list = list(zip(vld[sel_n].astype(str), vld[sel_u].astype(str)))
                    st.success(f"Prepared {len(st.session_state.sc_list)} targets.")
                if 'sc_list' in st.session_state: targets = st.session_state.sc_list

            if st.button("🚀 IGNITE HUNTER ENGINE", type="primary", use_container_width=True):
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    st.session_state.sc_results = loop.run_until_complete(run_scraper_master(targets, max_depth, concurrency))
                    
                    # Auto Save to Exports Folder
                    if st.session_state.sc_results:
                        if not os.path.exists("exports"):
                            os.makedirs("exports")
                        rdf_save = pd.DataFrame(st.session_state.sc_results)
                        sv_name = f"exports/leads_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                        rdf_save.to_csv(sv_name, index=False)
                        st.session_state.last_save = sv_name
                finally:
                    loop.close()
                st.rerun()

    if 'sc_results' in st.session_state and st.session_state.sc_results:
        st.divider()
        st.subheader("🎯 Scrape Results")
        res_df = pd.DataFrame(st.session_state.sc_results)
        
        # Original Scraper Metrics
        success_count = res_df[(res_df['Facebook'] != '') | (res_df['Instagram'] != '')].shape[0]
        playwright_count = res_df[res_df['Tier Used'] == 'Deep (Playwright)'].shape[0]
        cache_count = res_df[res_df['Tier Used'] == 'Cache'].shape[0]
        
        m1, m2, m3, m4 = st.columns(4)
        m1.markdown(f"<div class='metric-card'><h4>Total Run</h4><h2>{len(res_df)}</h2></div>", unsafe_allow_html=True)
        m2.markdown(f"<div class='metric-card'><h4>Links Found</h4><h2 style='color:#10b981;'>{success_count}</h2></div>", unsafe_allow_html=True)
        m3.markdown(f"<div class='metric-card'><h4>Anti-Bot Bypassed</h4><h2 style='color:#f59e0b;'>{playwright_count}</h2></div>", unsafe_allow_html=True)
        m4.markdown(f"<div class='metric-card'><h4>Cache Hits</h4><h2 style='color:#3b82f6;'>{cache_count}</h2></div>", unsafe_allow_html=True)
        
        if 'last_save' in st.session_state:
            st.success(f"✅ Data automatically saved to your workspace as `{st.session_state.last_save}`")

        # Display Table with LinkColumns
        cols_to_show = ['Business Name', 'Website', 'Facebook', 'Instagram', 'Tier Used', 'Status']
        present = [c for c in cols_to_show if c in res_df.columns]
        st.dataframe(
            res_df[present], 
            use_container_width=True,
            column_config={
                "Website": st.column_config.LinkColumn(),
                "Facebook": st.column_config.LinkColumn(),
                "Instagram": st.column_config.LinkColumn()
            }
        )
        
        # Export Actions
        c_exp1, c_exp2 = st.columns(2)
        c_exp1.download_button("📥 Download Raw CSV", res_df.to_csv(index=False), f"ultimate_leads_{datetime.now().strftime('%Y%m%d')}.csv", "text/csv")
        
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
            res_df.to_excel(writer, index=False)
        c_exp2.download_button("📊 Download Excel Format", buffer.getvalue(), f"ultimate_leads_{datetime.now().strftime('%Y%m%d')}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ==========================================
# 3. VIEW: LEAD FILTERING (NLP REGEX)
# ==========================================

def render_filter_view():
    init_filter_db()
    st.markdown("<div class='main-hero'><h1>🏊 Ultimate Pool Lead Filter v3</h1><p>Modular Intelligence Scoring & Commercial Intent Detection</p></div>", unsafe_allow_html=True)
    
    # Auto-Restore History
    if 'filter_results' not in st.session_state:
        history = load_latest_filter_run()
        if history:
            st.session_state.filter_results = history
            st.toast("📜 Previous analysis restored.")
    
    with st.sidebar:
        st.header("⚙️ Filter Rules")
        min_s = st.slider("Sensitivity", 0, 100, 25)
        dedup = st.checkbox("Deduplicate Usernames", value=True)
        with st.expander("Edit Keywords"):
            p_kw = st.text_area("Pool Keywords", ", ".join(DEFAULT_POOL_KEYWORDS))
            c_kw = st.text_area("Comm Keywords", ", ".join(DEFAULT_COMMERCIAL_KEYWORDS))
            o_kw = st.text_area("Owner Titles", ", ".join(DEFAULT_OWNER_TITLES))
            g_kw = st.text_area("Staff Titles", ", ".join(DEFAULT_GENERAL_TITLES))
            b_kw = st.text_area("Biz Entities", ", ".join(DEFAULT_BUSINESS_ENTITIES))
            e_kw = st.text_area("Exclusions", ", ".join(DEFAULT_EXCLUSIONS))

    def pk(t): return [x.strip() for x in t.split(',') if x.strip()]
    fcfg = {'pool': pk(p_kw), 'commercial': pk(c_kw), 'owner': pk(o_kw), 'general': pk(g_kw), 'business': pk(b_kw), 'exclusion': pk(e_kw)}

    fls = st.file_uploader("Upload Scraped CSVs", type=['csv'], accept_multiple_files=True)
    if fls:
        has_header = st.checkbox("CSVs have a header row", value=True, key="fs_has_header")
        sm, _ = safe_read_csv(fls[0], has_header)
        if sm is not None:
            cols = sm.columns.tolist()
            ucol = st.selectbox("Username Col", cols, index=smart_find_column(cols, "username"))
            bcol = st.selectbox("Bio Col", cols, index=smart_find_column(cols, "bio"))
            
            if st.button("🚀 Process Filtering", type="primary"):
                engine = ScoringEngine(fcfg)
                apth, afail, stats = [], [], []
                pb = st.progress(0)
                for i, f in enumerate(fls):
                    df, _ = safe_read_csv(f, has_header)
                    if df is not None:
                        df = df.apply(lambda r: engine.process_row(r, ucol, bcol), axis=1)
                        msk = df['smart_score'] >= min_s
                        p, fl = df[msk].copy(), df[~msk].copy()
                        p['source_file'], fl['source_file'] = f.name, f.name
                        apth.append(p); afail.append(fl)
                        stats.append({
                            "File Name": f.name,
                            "Total Rows": len(df),
                            "Qualified Leads": len(p),
                            "Filtered Out": len(fl)
                        })
                    pb.progress((i+1)/len(fls))
                if apth:
                    mp = pd.concat(apth, ignore_index=True)
                    if dedup: mp = mp.sort_values('smart_score', ascending=False).drop_duplicates(subset=[ucol], keep='first')
                    st.session_state.filter_results = {
                        "passed": mp, 
                        "failed": pd.concat(afail, ignore_index=True), 
                        "stats": stats,
                        "u_col": ucol, 
                        "b_col": bcol
                    }
                    save_filter_run(st.session_state.filter_results)
                    st.rerun()

    if 'filter_results' in st.session_state:
        res = st.session_state.filter_results
        passed = res['passed']
        failed = res['failed']
        
        st.divider()
        m1, m2, m3 = st.columns(3)
        m1.metric("✅ Qualified Leads", len(passed))
        m2.metric("❌ Filtered Out", len(failed))
        m3.metric("📊 Files Scanned", len(res['stats']))
        
        # --- MASTER EXCEL EXPORT ---
        try:
            import io
            import pandas as pd
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                if not passed.empty:
                    passed.to_excel(writer, sheet_name='All Qualified Leads', index=False)
                    for val in passed['Lead Type'].unique():
                        safe_val = str(val).replace(':', '').replace('/', '-').replace('🏢', '').replace('👔', '').replace('👷', '').strip()
                        if not safe_val: safe_val = "Sheet"
                        passed[passed['Lead Type'] == val].to_excel(writer, sheet_name=safe_val[:31], index=False)
                if not failed.empty:
                    failed.to_excel(writer, sheet_name='Filtered Out', index=False)
            
            st.download_button(
                label="📥 Download Master Excel (All Tabs & Data)",
                data=output.getvalue(),
                file_name="master_leads_export.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
                use_container_width=True
            )
        except Exception as e:
            st.error(f"Excel export unavailable (please install openpyxl): {e}")
        st.markdown("<br>", unsafe_allow_html=True)
        # ---------------------------
        
        tab1, tab2, tab3 = st.tabs(["🎯 Qualified Leads", "📁 File Stats", "🗑️ Filtered Out"])
        
        with tab1:
            sub_tabs = st.tabs(["👔 Owners", "🏢 Businesses", "👷 Staff/Pros", "All Leads"])
            categories = [
                ("👔 Owner / Decision Maker", sub_tabs[0]),
                ("🏢 Business Page", sub_tabs[1]),
                ("👷 General Pro / Staff", sub_tabs[2])
            ]
            
            def render_lead_table(df, tab, name):
                with tab:
                    if df.empty:
                        st.info(f"No leads in {name}.")
                    else:
                        extra_cols = [c for c in df.columns if c not in [res['u_col'], res['b_col'], 'smart_score', 'source_file', 'Lead Type', 'fail_reason']]
                        
                        disp_cols = [res['u_col'], res['b_col']] + extra_cols + ['smart_score', 'source_file']
                        disp_cols = [c for c in disp_cols if c in df.columns]
                        
                        st.dataframe(
                            df[disp_cols],
                            use_container_width=True,
                            column_config={"smart_score": st.column_config.ProgressColumn("Score", format="%d", min_value=0, max_value=100)}
                        )
                        
                        st.markdown("<br>", unsafe_allow_html=True)
                        col_exp, col_copy = st.columns(2)
                        
                        with col_exp:
                            st.markdown("##### 📋 Export CSV Options")
                            st.download_button(f"📥 Export Full Data", df.to_csv(index=False).encode('utf-8'), f"{name}_full.csv", mime="text/csv", key=f"csv_f_{name}")
                            if res['u_col'] in df.columns:
                                st.download_button(f"📥 Export Usernames", df[[res['u_col']]].to_csv(index=False).encode('utf-8'), f"{name}_usernames.csv", mime="text/csv", key=f"csv_u_{name}")
                            if res['b_col'] in df.columns:
                                st.download_button(f"📥 Export Bios", df[[res['b_col']]].to_csv(index=False).encode('utf-8'), f"{name}_bios.csv", mime="text/csv", key=f"csv_b_{name}")
                        
                        with col_copy:
                            st.markdown("##### 📋 Copy to Clipboard")
                            if st.button(f"Get Usernames", key=f"btn_u_{name}"):
                                st.text_area("All Usernames (Ctrl+A to Copy)", "\n".join(df[res['u_col']].astype(str)), height=150)
                            
                            if st.button(f"Get All Bios", key=f"btn_b_{name}"):
                                st.text_area("All Bios (Ctrl+A to Copy)", "\n".join(df[res['b_col']].astype(str)), height=150)
                                
                            if st.button(f"Get Google Sheets Format (TSV)", key=f"btn_tsv_{name}"):
                                st.text_area("Full Data (Ctrl+A, Ctrl+C, then Paste into Google Sheets)", df.to_csv(index=False, sep='\t'), height=150)
            
            for val, target_tab in categories:
                render_lead_table(passed[passed['Lead Type'] == val], target_tab, val)
            render_lead_table(passed, sub_tabs[3], "All Leads")

        with tab2: st.dataframe(pd.DataFrame(res['stats']), use_container_width=True)
        with tab3:
            if not failed.empty:
                extra_cols_failed = [c for c in failed.columns if c not in [res['u_col'], res['b_col'], 'smart_score', 'source_file', 'Lead Type', 'fail_reason']]
                disp_cols_failed = [res['u_col'], res['b_col']] + extra_cols_failed + ['fail_reason', 'smart_score', 'source_file']
                disp_cols_failed = [c for c in disp_cols_failed if c in failed.columns]
                
                st.dataframe(failed[disp_cols_failed], use_container_width=True)
                
                st.markdown("<br>", unsafe_allow_html=True)
                cf_exp, cf_copy = st.columns(2)
                
                with cf_exp:
                    st.markdown("##### 📋 Export CSV")
                    st.download_button("📥 Export Rejected (CSV)", failed.to_csv(index=False).encode('utf-8'), "rejected.csv", mime='text/csv')
                
                with cf_copy:
                    st.markdown("##### 📋 Copy to Clipboard")
                    if st.button("Get Google Sheets Format (TSV)", key="btn_tsv_rejected"):
                        st.text_area("Full Data (Ctrl+A, Ctrl+C, then Paste into Google Sheets)", failed.to_csv(index=False, sep='\t'), height=150)

# ==========================================
# 4. MAIN NAVIGATION
# ==========================================
def main():
    inject_styles()
    with st.sidebar:
        st.title("🎯 Social Meta Suite")
        nav = st.radio("Navigation", ["⚡ Lead Extraction Hub", "🏊 Pool Lead Filter Suite"])
        st.divider()
        st.header("⚙️ Scraper Settings")
        concurrency = st.slider("Concurrent Connects", 1, 20, 5)
        max_depth = st.slider("Max Internal Pages", 1, 10, 3)
        st.divider()
        st.info("System Ready.")

    if nav == "⚡ Lead Extraction Hub":
        render_scraper_view(concurrency, max_depth)
    else:
        render_filter_view()

if __name__ == "__main__":
    main()
