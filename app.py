import json
import subprocess
import sys
import threading
from pathlib import Path

import pandas as pd
import streamlit as st

from jobagent import (answers, ats, config, db, docgen, export, jobpage, llm, pipeline,
                      resume_parser, tailor)

ROOT = Path(__file__).parent

st.set_page_config(page_title="JobAgent", page_icon="🎯", layout="wide")
config.ensure_dirs()
S = config.load()
if "warmed" not in st.session_state:  # load the model in the background while you read the page
    st.session_state["warmed"] = True
    threading.Thread(target=llm.warm_up, daemon=True).start()


def lines(text):
    return [l.strip() for l in text.splitlines() if l.strip()]


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("⚙️ Settings")
    models = llm.available_models()
    if models:
        st.success(f"Ollama connected ({len(models)} models)")
        S.chat_model = st.selectbox("Chat model", models,
                                    index=models.index(S.chat_model) if S.chat_model in models else 0)
    else:
        st.error("Ollama not reachable. Start it with `ollama serve`.")
        S.chat_model = st.text_input("Chat model", S.chat_model)
    if models:
        fast_opts = ["(same as chat model)"] + models
        cur = S.fast_model if S.fast_model in models else "(same as chat model)"
        pick = st.selectbox("Fast model (keywords)", fast_opts, index=fast_opts.index(cur),
                            help="Small model for quick tasks. Install: ollama pull llama3.2:3b")
        S.fast_model = "" if pick.startswith("(") else pick
    S.ollama_host = st.text_input("Ollama host", S.ollama_host)
    S.embed_model = st.text_input("Embedding model", S.embed_model)
    S.min_match = st.slider("Minimum match score", 0, 100, S.min_match)
    with st.expander("Adzuna API (optional job aggregator)"):
        S.adzuna_app_id = st.text_input("App ID", S.adzuna_app_id)
        S.adzuna_app_key = st.text_input("App key", S.adzuna_app_key, type="password")
        S.adzuna_country = st.text_input("Country code", S.adzuna_country)
    with st.expander("Aggregator APIs (LinkedIn/Naukri/Indeed via Google Jobs)"):
        S.jsearch_mode = st.selectbox(
            "JSearch provider", ["rapidapi", "openwebninja"],
            index=["rapidapi", "openwebninja"].index(S.jsearch_mode)
            if S.jsearch_mode in ("rapidapi", "openwebninja") else 0,
            help="rapidapi = key from rapidapi.com. openwebninja = key from openwebninja.com "
                 "(direct, newer).")
        S.jsearch_key = st.text_input("JSearch API key", S.jsearch_key, type="password")
        S.serpapi_key = st.text_input("SerpAPI key", S.serpapi_key, type="password")
        S.max_api_queries = st.number_input("Max API queries per run", 1, 30, S.max_api_queries)
    if st.button("Save settings"):
        config.save(S)
        st.toast("Saved")
    st.caption(f"Data folder: {config.paths()['home']}")

st.title("🎯 JobAgent")
tab_profile, tab_find, tab_add, tab_matches, tab_apply, tab_track = st.tabs(
    ["1 · Profile", "2 · Find jobs", "＋ Add a job", "3 · Matches & tailor", "4 · Apply",
     "5 · Tracker"])


def _export():
    export.safe_export(lambda *_: None)

# ------------------------------------------------------------------ profile
with tab_profile:
    up = st.file_uploader("Upload your resume (PDF, DOCX or TXT)", type=["pdf", "docx", "txt"])
    if up and st.button("Parse resume with local AI", type="primary"):
        with st.spinner("Reading your resume…"):
            try:
                data = up.getvalue()
                text = resume_parser.extract_text(up.name, data)
                profile = resume_parser.parse_profile(text)
                db.save_profile(profile)
                (config.paths()["master"] / f"original_{up.name}").write_bytes(data)
                docgen.build_docx(profile, docgen.master_path(profile))
                if not S.target_titles:
                    S.target_titles = profile.get("target_titles", [])
                    config.save(S)
                st.success("Profile saved. Review it below and fix anything the AI got wrong.")
            except Exception as e:
                st.error(str(e))

    profile = db.get_profile()
    if profile:
        editable = {k: v for k, v in profile.items() if k != "raw_text"}
        edited = st.text_area("Your parsed profile (editable JSON)",
                              json.dumps(editable, indent=2, ensure_ascii=False), height=450)
        if st.button("Save profile edits"):
            try:
                new = json.loads(edited)
                new["raw_text"] = profile.get("raw_text", "")
                db.save_profile(new)
                docgen.build_docx(new, docgen.master_path(new))
                st.success("Saved.")
            except json.JSONDecodeError as e:
                st.error(f"Invalid JSON: {e}")
    else:
        st.info("Upload your resume to get started.")

# ------------------------------------------------------------------ find jobs
with tab_find:
    c1, c2 = st.columns(2)
    with c1:
        S.target_titles = lines(st.text_area("Target job titles (one per line)",
                                             "\n".join(S.target_titles), height=120))
        S.locations = lines(st.text_area("Locations (one per line; remote is always kept)",
                                         "\n".join(S.locations), height=90))
        S.exclude_keywords = lines(st.text_area("Exclude if these words appear (one per line)",
                                                "\n".join(S.exclude_keywords), height=90))
    with c2:
        st.caption("Company career pages: enter the slug from the careers URL, one per line.")
        S.greenhouse_boards = lines(st.text_area(
            "Greenhouse (boards.greenhouse.io/<slug>)", "\n".join(S.greenhouse_boards), height=90))
        S.lever_companies = lines(st.text_area(
            "Lever (jobs.lever.co/<slug>)", "\n".join(S.lever_companies), height=90))
        S.ashby_boards = lines(st.text_area(
            "Ashby (jobs.ashbyhq.com/<slug>)", "\n".join(S.ashby_boards), height=90))
    st.divider()
    st.subheader("A · Career pages + aggregator APIs")
    if st.button("🔎 Fetch jobs and score them", type="primary"):
        config.save(S)
        with st.spinner("Collecting and scoring jobs (embeddings run locally)…"):
            try:
                res = pipeline.fetch_and_score(log=st.warning)
                st.success(f"{res['fetched']} relevant jobs found, {res['new']} new, "
                           f"{res['scored']} scored.")
                for e in res["errors"]:
                    st.warning(e)
            except Exception as e:
                st.error(str(e))

    st.divider()
    st.subheader("B · Email alerts (Naukri / LinkedIn / Indeed…)")
    st.caption("Create saved-search alerts on the portals (daily emails). The app reads those "
               "emails read-only and imports the jobs. Gmail: use an App Password, not your "
               "normal password.")
    e1, e2 = st.columns(2)
    S.imap_host = e1.text_input("IMAP host", S.imap_host)
    S.imap_user = e2.text_input("Email address", S.imap_user)
    S.imap_password = e1.text_input("App password", S.imap_password, type="password")
    S.email_days = e2.number_input("Look back (days)", 1, 30, S.email_days)
    if st.button("📧 Scan alert emails"):
        config.save(S)
        with st.spinner("Reading alert emails and fetching job pages…"):
            try:
                r = pipeline.scan_email_and_score(log=st.warning)
                st.success(f"{r['emails']} alert emails, {r['links']} job links, {r['new']} new "
                           f"jobs added, {r['already_known']} already known.")
            except Exception as e:
                st.error(str(e))

    st.divider()
    st.subheader("C · Browser scan (your logged-in Naukri / LinkedIn)")
    st.warning("Automated browsing breaks both sites' terms. LinkedIn can restrict accounts. "
               "Limits are built in (one scan per ~20 h, ~40 jobs per portal, human-like delays, "
               "auto-stop on captcha/security check), but the risk is yours. Naukri is the safer "
               "of the two.")
    portals = st.multiselect("Portals", ["naukri", "linkedin"], default=["naukri"])
    S.browser_max_jobs = st.number_input("Max jobs per portal per run", 5, 100, S.browser_max_jobs)
    force = st.checkbox("Ignore the once-per-20h limit (not recommended)")
    b1, b2 = st.columns(2)
    if b1.button("1️⃣ Open browser to log in (one-time)"):
        subprocess.Popen([sys.executable, "-m", "jobagent.browser_scan", "login"], cwd=ROOT)
        st.info("A browser window opened. Log in, then close the window.")
    if b2.button("2️⃣ Run browser scan") and portals:
        config.save(S)
        cmd = [sys.executable, "-m", "jobagent.browser_scan", "scan", "--portals", *portals]
        if force:
            cmd.append("--force")
        with st.spinner("Scanning slowly like a human would — this takes several minutes…"):
            out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        st.code((out.stdout + out.stderr).strip() or "(no output)")

# ------------------------------------------------------------------ add a job
with tab_add:
    st.caption("Found a posting yourself? Paste the link or the text and it gets scored and "
               "can be tailored like any other job.")
    url = st.text_input("Job URL (optional)", key="add_url")
    if st.button("Fetch details from URL"):
        try:
            got = jobpage.fetch_job(url)
            if got:
                st.session_state.update(add_title=got["title"], add_company=got["company"],
                                        add_loc=got["location"], add_desc=got["description"])
                st.success("Fetched. Check the fields below.")
            else:
                st.warning("The site needs a login or blocked the request (common for LinkedIn "
                           "and Naukri). Open the job in your browser and paste the text below.")
        except Exception as e:
            st.error(str(e))
    t1, t2, t3 = st.columns(3)
    a_title = t1.text_input("Job title", key="add_title")
    a_company = t2.text_input("Company", key="add_company")
    a_loc = t3.text_input("Location", key="add_loc")
    a_desc = st.text_area("Job description", key="add_desc", height=260)
    if st.button("Add & score", type="primary"):
        if not (a_title and a_company and a_desc):
            st.error("Title, company and description are required.")
        else:
            try:
                canon = jobpage.canonical(url) if url else None
                job = {"title": a_title, "company": a_company, "location": a_loc,
                       "description": a_desc, "url": canon[1] if canon else url,
                       "source": canon[0] if canon else "manual", "posted": ""}
                is_new, row = pipeline.add_manual(job)
                if is_new and row:
                    st.success(f"Added. Match score: {row['match_score']}. "
                               f"Find it in the Matches tab.")
                else:
                    st.info("That job is already in your list.")
            except Exception as e:
                st.error(str(e))

# ------------------------------------------------------------------ matches
with tab_matches:
    jobs = db.list_jobs(S.min_match, ["new", "shortlisted", "tailored"])
    if not jobs:
        st.info("No jobs above your minimum score yet. Fetch jobs first or lower the threshold.")
    else:
        df = pd.DataFrame(jobs)[["id", "match_score", "title", "company", "location",
                                 "source", "posted", "status"]]
        event = st.dataframe(df, hide_index=True, width="stretch",
                             on_select="rerun", selection_mode="single-row")
        rows = event.selection.rows
        if rows:
            job = db.get_job(int(df.iloc[rows[0]]["id"]))
            profile = db.get_profile()
            st.subheader(f"{job['title']} — {job['company']}")
            st.caption(f"{job['location']} · {job['source']} · match {job['match_score']}")
            if job["url"]:
                st.link_button("Open job posting", job["url"])
            with st.expander("Job description"):
                st.text(job["description"])

            if st.button("Analyse ATS fit"):
                with st.spinner("Extracting keywords…"):
                    kws = ats.jd_keywords(job["description"])
                    db.update_job(job["id"], keywords=json.dumps(kws))
                job = db.get_job(job["id"])

            if job["keywords"]:
                kws = json.loads(job["keywords"])
                before = ats.score_resume(profile, kws)
                a, b = st.columns(2)
                a.metric("ATS score (current resume)", f"{before['score']}/100")
                b.metric("Keyword coverage", f"{before['coverage']}%")
                st.write("**Matched:** " + (", ".join(before["matched"]) or "–"))
                st.write("**Missing:** " + (", ".join(before["missing"]) or "–"))
                original_text = resume_parser.profile_to_text(profile) + profile.get("raw_text", "")
                gaps = [k for k in before["missing"]
                        if not ats.has_term(original_text, k)]
                confirmed = st.multiselect(
                    "Missing keywords you GENUINELY have (they'll be added to Skills):", gaps,
                    help="Anything not selected stays out of your resume.")
                if st.button("✍️ Tailor resume for this job", type="primary"):
                    with st.spinner("Tailoring with your local model…"):
                        try:
                            new, rep = tailor.tailor_profile(profile, job["description"], kws, confirmed)
                            after = ats.score_resume(new, kws)
                            existing = next((a["resume_path"] for a in db.list_applications()
                                             if a["job_id"] == job["id"]), None)
                            path = docgen.resume_path(new, job["company"], job["id"], existing)
                            docgen.build_docx(new, path)
                            (config.paths()["jds"] /
                             f"{docgen.safe(job['company'])}_{job['id']}.txt").write_text(
                                f"{job['title']}\n{job['url']}\n\n{job['description']}",
                                encoding="utf-8")
                            db.upsert_application(job["id"], str(path), before["score"],
                                                  after["score"], "tailored")
                            _export()
                            st.session_state["last_result"] = (str(path), before["score"],
                                                               after["score"], rep, new["summary"])
                        except Exception as e:
                            st.error(str(e))
                res = st.session_state.get("last_result")
                if res:
                    path, b4, af, rep, summ = res
                    st.success(f"Saved: {path}")
                    st.metric("ATS score", f"{af}/100", delta=af - b4)
                    st.write(f"**New summary:** {summ}")
                    st.write(f"Bullets rephrased: {rep['bullets_changed']}")
                    if rep["gaps"]:
                        st.warning("Not added (not in your resume): " + ", ".join(rep["gaps"]))
                    if rep["rejected"]:
                        st.info("Model output rejected by safety checks: " + "; ".join(rep["rejected"]))
                    with open(path, "rb") as f:
                        st.download_button("Download resume", f.read(), file_name=Path(path).name)

            c1, c2, c3 = st.columns(3)
            if c1.button("⭐ Shortlist"):
                db.update_job(job["id"], status="shortlisted"); _export(); st.rerun()
            if c2.button("✅ Mark applied"):
                db.upsert_application(job["id"], status="applied"); _export(); st.rerun()
            if c3.button("🚫 Skip"):
                db.update_job(job["id"], status="skipped"); _export(); st.rerun()

# ------------------------------------------------------------------ apply
def _show_report(jid):
    rp = config.paths()["apply_logs"] / f"job_{jid}.json"
    if not rp.exists():
        st.info("No report yet for this job. Run 'Read the form' or 'Open form and pre-fill'.")
        return
    rep = json.loads(rp.read_text(encoding="utf-8"))
    sm = rep["summary"]
    st.caption(f"{rep['mode']} · {rep['when']} · {rep['url']}")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Fields found", sm["fields"])
    m2.metric("Filled", sm["filled"])
    m3.metric("Required, not filled", sm["required_missing"])
    m4.metric("To review", sm["needs_review"])
    if sm.get("captcha"):
        st.warning("A captcha was detected: you'll have to solve it yourself.")
    if sm.get("needs_account"):
        st.warning("This portal asks you to create an account/password: do that step yourself.")
    st.dataframe(pd.DataFrame(rep["fields"])[["label", "required", "status", "value", "source",
                                              "note"]], hide_index=True, width="stretch")


with tab_apply:
    st.caption("Applies on COMPANY career pages (Greenhouse, Lever, Ashby and most plain forms). "
               "LinkedIn/Naukri postings are never automated: use 'Open job posting' there. "
               "Workday-style portals that need an account must be finished by hand.")
    with st.expander("Your standard answers (notice period, CTC, years of experience…)",
                     expanded=False):
        st.caption(f"Saved in {answers.path()}. Empty answers are never guessed: the field is "
                   "left blank and flagged. Personal/EEO questions are always left to you.")
        txt = st.text_area("answers.json", json.dumps(answers.load(), indent=2, ensure_ascii=False),
                           height=330)
        if st.button("Save answers"):
            try:
                answers.save(json.loads(txt))
                st.success("Saved.")
            except json.JSONDecodeError as e:
                st.error(f"Invalid JSON: {e}")

    cands = db.list_jobs(0, ["shortlisted", "tailored", "prefilled"])
    if not cands:
        st.info("Shortlist a job or tailor a resume first (Matches & tailor tab).")
    else:
        jid = st.selectbox(
            "Job to apply for", [j["id"] for j in cands],
            format_func=lambda i: next(f"{j['match_score']} · {j['title']} — {j['company']} "
                                       f"({j['status']})" for j in cands if j["id"] == i))
        job = db.get_job(jid)
        app_row = next((a for a in db.list_applications() if a["job_id"] == jid), None)
        st.write(f"**Resume that will be uploaded:** "
                 f"{(app_row or {}).get('resume_path') or 'your master resume (not tailored yet)'}")
        if job["url"]:
            st.link_button("Open job posting", job["url"])
        if any(h in (job["url"] or "") for h in ("linkedin.com", "naukri.com")):
            st.warning("This is a LinkedIn/Naukri link: automated applying is blocked here. "
                       "If it has a 'company website' apply link, add that job via ＋ Add a job.")
        base = [sys.executable, "-m", "jobagent.applier", str(jid)]
        c1, c2 = st.columns(2)
        if c1.button("🔍 Read the form (fills nothing)"):
            with st.spinner("Opening the page and reading the form…"):
                out = subprocess.run(base + ["--parse-only"], cwd=ROOT, capture_output=True, text=True)
            if out.returncode:
                st.code((out.stdout + out.stderr)[-1500:])
        if c2.button("🧾 Open form and pre-fill (I review and submit)", type="primary"):
            subprocess.Popen(base, cwd=ROOT)
            st.info("A browser window is opening. Red = still needed, orange = please review. "
                    "Click Submit yourself, then close the window. After you submit, the app "
                    "marks it 'applied' automatically when the thank-you page appears.")
        with st.expander("⚡ Auto-submit (advanced)"):
            st.warning(
                f"Submits for you ONLY if: match score ≥ {S.auto_submit_min_match}, every required "
                "field was filled from your profile/answers, nothing needs review (no AI-drafted or "
                "skill-specific answers), no captcha, resume uploaded, and fewer than "
                f"{S.apply_daily_cap} auto-submits today. Wrong answers can't be undone, so try "
                "the review mode on ~10 applications first.")
            if st.checkbox("I understand and want to allow auto-submit for this job") and \
                    st.button("⚡ Pre-fill and auto-submit if everything is confident"):
                subprocess.Popen(base + ["--auto-submit"], cwd=ROOT)
                st.info("Running. If any safety condition fails it stops and waits for you.")
        st.divider()
        st.subheader("Last report for this job")
        if st.button("🔄 Refresh report"):
            st.rerun()
        _show_report(jid)

# ------------------------------------------------------------------ tracker
with tab_track:
    ex1, ex2 = st.columns([1, 3])
    if ex1.button("📊 Export to Excel now"):
        paths = export.safe_export(st.warning)
        if paths:
            st.success(f"Saved {paths[0]} and {paths[1]}")
    ex2.caption(f"Excel files are written automatically after every fetch/scan, one per day: "
                f"{config.paths()['exports']}")
    apps = db.list_applications()
    if not apps:
        st.info("Nothing tracked yet. Tailor a resume or mark a job as applied.")
    else:
        st.dataframe(pd.DataFrame(apps)[["job_id", "company", "title", "status", "ats_before",
                                         "ats_after", "resume_path", "updated_at"]],
                     hide_index=True, width="stretch")
        with st.form("upd"):
            jid = st.selectbox("Job", [a["job_id"] for a in apps],
                               format_func=lambda i: next(f"{a['company']} – {a['title']}"
                                                          for a in apps if a["job_id"] == i))
            status = st.selectbox("Status", db.STATUSES, index=db.STATUSES.index("applied"))
            notes = st.text_input("Notes")
            if st.form_submit_button("Update"):
                db.upsert_application(jid, status=status, notes=notes or None)
                st.rerun()
