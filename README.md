# ATS Job Search Script

A Python tool that searches niche Applicant Tracking System (ATS) platforms for job postings, cross-references results against major job boards to surface roles that haven't yet been widely syndicated, and delivers personalized HTML email reports to multiple recipients with a linked Google Sheets tracker.

Built for a small group of senior-level job seekers across healthcare communications, marketing, and civil engineering.

---

## What It Does

Most job search tools surface the same postings everyone else sees — roles that have been indexed by LinkedIn, Indeed, and Glassdoor and are already receiving hundreds of applications. This tool takes a different approach:

1. **Searches ATS platforms directly** using targeted Google queries (`site:greenhouse.io "communications" "director"`), reaching postings before or instead of major aggregators
2. **Cross-references each result** against LinkedIn, Indeed, and Glassdoor — jobs not found on major boards are flagged as Hidden Gems
3. **Scores each posting** by relevance using a weighted model (title match 80%, seniority 15%, location 13%)
4. **Fetches full job pages** for Strong and Good matches to extract salary, location, and posting date from structured JSON-LD data
5. **Delivers a personalized HTML email** per recipient with results organized into four sections
6. **Maintains a Google Sheets tracker** per person that rewrites on each run while preserving user-entered data (pins, notes, application dates, stage)

---

## Architecture

```
job_search.py          # Main script
.env                   # Credentials (not committed)
google_credentials.json  # Google service account key (not committed)
history/
  history_andy.csv     # Per-person search history (3-week TTL)
  rejected_urls_andy.csv  # Per-person reject list (90-day TTL)
```

### Run Sequence (per profile)

1. Search 14 ATS platforms × N keyword combos via Serper.dev API
2. Apply pre-filters: exclusion keywords, strict location filter
3. Score all jobs by relevance
4. Cross-reference Strong/Good new jobs against LinkedIn/Indeed/Glassdoor
5. Fetch full job page for Strong/Good jobs (JSON-LD parsing → text regex fallback)
6. Demote jobs below salary minimum to Possible
7. Apply age-based section logic (fresh ≤7 days → Sec 1/2, older → Sec 3)
8. Rewrite Google Sheet with preserved user data
9. Send personalized HTML email

---

## Email Sections

| Section | Definition |
|---|---|
| 🟢 Hidden Gems | New, not on major boards, within 7 days of first seen |
| 🔵 Open Market Picks | New, on major boards, ranked by relevance |
| 🟡 Still Circulating | Older than 7 days or seen in a previous run |
| ⚪ Other Matches | Possible matches (sheet only, not in email) |
| ✅ Applied & Waiting | Marked as applied by user |
| 📌 Pinned | User-starred jobs, always at top |

---

## Google Sheets Tracker

Each person has their own Google Sheet that the script rewrites on every run. Key behaviors:

- **User data is always preserved** — notes, pins, application dates, stage dropdown are read before rewrite and restored
- **Pinned jobs stay at top** — checking the ⭐ column moves a job to Section 0 permanently
- **Reject suppression** — checking the ❌ column adds the URL to a 90-day reject list; the job disappears on the next run
- **Applied auto-routing** — checking Applied! or filling Date Applied moves the job to Section 5
- **Row grouping** — top 20 rows visible per section; overflow collapsed with a + toggle
- **Filter views** — one-click filters for Pinned, Strong Matches, New This Run, Applied

An Apps Script macro ("⭐ Job Search → Open Pinned Jobs") opens a modal with clickable links to all pinned jobs.

---

## Relevance Scoring

Each job receives a score out of 30:

| Signal | Weight | Max Points |
|---|---|---|
| Title keyword match | 80% | 24 pts |
| Seniority level in title | 7% | 2.1 pts |
| Location / remote match | 13% | 3.9 pts |

**Labels:** 🟢 Strong (≥20) · 🟡 Good (≥10) · 🔵 Possible (<10)

---

## ATS Platforms Searched

Ashby · Lever · Greenhouse · Workable · BambooHR · Paylocity · iCIMS · Jobvite · Workday · SmartRecruiters · Recruitee · ApplyToJob · Jazz · Breezy

---

## API Usage & Cost

- **Serper.dev** (Google Search wrapper): ~700–800 credits per profile per run after optimizations
- Cross-reference and page fetch only run on Strong/Good new jobs
- Returning jobs skip cross-reference entirely
- Estimated cost at $1/1,000 credits: ~$0.70–$0.80 per profile per run

---

## Setup

### Requirements

```bash
pip3 install requests python-dotenv google-auth google-auth-httplib2 google-api-python-client
```

### Credentials (.env)

```
SERPER_API_KEY=your_key_here
SENDER_EMAIL=your.gmail@gmail.com
SENDER_APP_PASSWORD=xxxx xxxx xxxx xxxx
BCC_EMAIL=your.monitor@gmail.com
SHEET_ID_ANDY=your_sheet_id
SHEET_ID_VANESSA=your_sheet_id
SHEET_ID_MARYJANE=your_sheet_id
SHEET_ID_DAVID=your_sheet_id
GOOGLE_CREDENTIALS_FILE=google_credentials.json
```

### Google Sheets

1. Create a Google Cloud project and enable the Sheets API
2. Create a service account and download the JSON key as `google_credentials.json`
3. Create one blank Google Sheet per person
4. Share each sheet with the service account email (Editor access)
5. Paste each Sheet ID into `.env`

### Running

```bash
# Test mode — emails route to sender only, single profile
python3 job_search.py

# Live run — set in script:
# TEST_MODE = False
# TEST_PROFILE_ONLY = False
```

---

## Profiles

Each profile configures:
- Target role keywords (multiple combos searched)
- Industry filter terms
- Salary minimum (jobs below threshold demoted to Possible)
- Location preference and ok cities
- Priority title keywords for scoring

Current profiles: Andy (healthcare communications), Vanessa (CCO-level healthcare), Maryjane (healthcare marketing director), David (civil engineering / river hydraulics).

---

## Design Decisions

**Why search ATS platforms directly instead of scraping LinkedIn?**
LinkedIn aggressively blocks scraping and requires authentication. Searching ATS platforms via Google's index is reliable, respectful of robots.txt, and reaches postings that haven't been syndicated yet — which is the whole point.

**Why Serper.dev instead of Google's official Custom Search API?**
Google's free tier is 100 queries/day. Serper provides 2,500 free queries/month and the same result quality at a fraction of the cost for this use case.

**Why rewrite the entire Google Sheet instead of appending?**
Appending accumulates stale rows and makes it impossible to re-sort by relevance or move jobs between sections as their status changes. A full rewrite with preserved user data gives a clean, always-current view while keeping everything the user has entered.

**Why age-based section logic instead of seen_before?**
A job first seen yesterday should stay in Hidden Gems even if it appeared in yesterday's email. Age is a better proxy for freshness than whether a run has occurred.

---

## Version History

See [CHANGELOG.md](CHANGELOG.md) for full version history from v1 through current.
