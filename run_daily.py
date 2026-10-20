"""Headless daily run for a scheduler: python run_daily.py
Fetches career pages + aggregator APIs, reads alert emails (if configured), scores everything,
and writes today's Excel file to ~/JobAgent/exports/. The browser scan stays manual (it opens
a visible window): python -m jobagent.browser_scan scan"""
from jobagent import config, db, export, pipeline

if __name__ == "__main__":
    s = config.load()
    print("== career pages + APIs ==")
    try:
        print(pipeline.fetch_and_score())
    except Exception as e:
        print("skipped:", e)
    if s.imap_user and s.imap_password:
        print("== email alerts ==")
        try:
            print(pipeline.scan_email_and_score())
        except Exception as e:
            print("skipped:", e)
    paths = export.safe_export()
    top = db.list_jobs(s.min_match, ["new"])[:10]
    print(f"\nTop new matches (>= {s.min_match}):")
    for j in top:
        print(f"  {j['match_score']:5.1f}  {j['title']} @ {j['company']}  {j['url']}")
