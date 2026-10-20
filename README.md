# JobAgent (personal, local-first)

Upload your resume → find matching jobs → see your ATS score → get a truthfully tailored
resume saved as `YourName_Resume_Company.docx` → track every application. Everything
(AI included) runs on your machine.

## Setup
1. Install Python 3.10+ and [Ollama](https://ollama.com).
2. Pull models (a stronger chat model gives better parsing/rewriting):
   ```
   ollama pull llama3.1:8b
   ollama pull nomic-embed-text
   ```
3. Install and run:
   ```
   pip install -r requirements.txt
   streamlit run app.py
   ```
4. In the app: **Profile** → upload resume → check the parsed JSON. **Find jobs** → add target
   titles, locations and company career-page slugs → Fetch. **Matches** → pick a job →
   Analyse ATS → tick keywords you genuinely have → Tailor.

## Where things are saved (default `~/JobAgent`, override with env `JOBAGENT_HOME`)
```
data/jobagent.db            all jobs, scores, applications (SQLite: the source of truth)
exports/jobs_YYYY-MM-DD.xlsx   ONE EXCEL FILE PER DAY (new today / open matches / applications)
exports/jobs_master.xlsx    everything, all days
master/                     your original upload + Name_Resume_Master.docx
resumes/                    Name_Resume_Company.docx (one per tailored job)
job_descriptions/           JD saved for every tailored application
apply_logs/job_<id>.json    what the form parser found/filled for each application
answers.json                your standard answers (notice period, CTC...)
config.json                 your settings and keys
```
Excel files are rewritten automatically after every fetch, email scan, browser scan, tailoring and
status change. If a file is open in Excel, a side copy (`..._HHMMSS.xlsx`) is written instead.

## Daily automation (Windows)
`python run_daily.py` fetches career pages + APIs, reads alert emails, scores everything and writes
today's Excel file. To run it every morning at 8:30, edit `PYTHON` in `run_daily.bat` to the full
path from `where python`, then run once in PowerShell:
```
schtasks /create /tn "JobAgent Daily" /tr "D:\kunal\JobAgent\run_daily.bat" /sc daily /st 08:30
```
(Output goes to `logs\run_daily.log`. The browser scan stays manual because it opens a visible window.)

## Applying on company career pages (tab 4 · Apply)
1. Fill `answers.json` once (notice period, current/expected CTC, years of experience...).
2. Shortlist or tailor a job, open **Apply**, pick it.
3. **Read the form** shows every field found and what would go in it, without touching anything.
4. **Open form and pre-fill** opens the page, finds the form (clicks "Apply" if needed, works inside
   iframes), uploads your tailored resume, fills what it can. **Red = still needed, orange = review.**
   You click Submit. When the thank-you page appears the job is marked *applied* automatically.
5. **Auto-submit** (optional, advanced) submits only if everything is confident: score >= 60,
   all required fields filled from your profile/answers, nothing AI-drafted or needing review,
   no captcha, resume uploaded, under 10 auto-submits that day.

Always left to you: passwords/account creation, gender/race/disability and other personal
questions, consent/terms boxes (unless `auto_accept_consent` is true), captchas, other uploads.
Never automated: LinkedIn and Naukri. Free-text questions get an AI draft from your profile only,
always highlighted for review.

## How tailoring stays honest
The model may only reword your summary/bullets and reorder skills. Code then rejects any
new numbers, new skills that aren't in your original resume, and any change to employers,
titles, dates or education. Missing keywords are shown as gaps; they are added only if you
tick that you genuinely have them.

## Job sources (use as many as you like; duplicates across sources are skipped)
| Source | Covers | Risk | Setup |
|---|---|---|---|
| **Career-page APIs** (Greenhouse, Lever, Ashby) | Company career portals | None | Add slugs in *Find jobs* |
| **Aggregator APIs** (JSearch, SerpAPI, Adzuna) | LinkedIn / Naukri / Indeed / Monster listings via Google Jobs data | None | API key in sidebar (free tiers are small: `Max API queries` protects them) |
| **Email alerts** | Exactly what your saved searches on Naukri/LinkedIn/Indeed email you | None (read-only IMAP) | Create daily job alerts on the portals; Gmail App Password in *Find jobs* |
| **Browser scan** | Full Naukri/LinkedIn search results, using your own logged-in browser | **Against both sites' terms; LinkedIn may restrict accounts** | `pip install playwright && playwright install chromium`, then *Log in* once, then *Run scan* |
| **Add a job** | Anything you find manually (paste link or text) | None | - |

### Browser scan safety limits (built in)
One scan per ~20 h, max ~40 jobs per portal, random 3-15 s pauses, human-like scrolling,
read-only (never clicks Apply or messages anyone), and it stops immediately on a captcha,
login or security-check page. Start with Naukri only. It runs as a separate visible browser
window; your login lives in `~/JobAgent/browser_profile`. Page layouts change, so expect to
adjust selectors in `jobagent/browser_scan.py` occasionally.

### Privacy
`config.json` holds your API keys and email app password in plain text (permissions set to
owner-only). Delete them from the app when you no longer need them.

## Scoring notes
Match score = local embeddings (40/30/30 with skills + title overlap; keyword/title only if
embeddings are unavailable). ATS score = keyword coverage 70, sections 10, contact 5,
length 10, format 5. Both are transparent heuristics, not what any real ATS computes.

## Roadmap
- Phase 3: Playwright form-filling for Greenhouse/Lever/Workday with an approve-before-submit step
- Cover letters, screening-answer bank, follow-up reminders, interview prep per job
