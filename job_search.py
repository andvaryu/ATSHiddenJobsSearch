#!/usr/bin/env python3
"""
ATS Job Search Script — v4.3
Changes from v4.2.3:
- Scoring: title 80% / seniority 7% / location 13%
- Section logic: jobs stay in Sec 1/2 for 7 days by first_seen, then move to Sec 3
- Reject column (col B): light red bg, X when checked, 90-day memory, suppresses re-surfacing
- Pinned column (col A): light green bg
- Applied! moved to col J (right of URL)
- Date Posted added (from JSON-LD datePosted field)
- Date Applied auto-assigned by script if Applied! checked but date blank
- Stage: combined dropdown (New/Reviewing/Applied/Phone Screen/Interview/Final Round/Offer/Rejected/Pass)
- Interview Stage column removed
- · barrier column removed
- Email: ATS site label removed åfrom cards, job titles underlined as links
- PythonAnywhere trigger endpoint for manual re-run from sheet
- Reject memory: rejected_urls_NAME.csv, 90-day TTL
"""

import csv
import datetime
import json
import os
import re
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Load credentials from .env
load_dotenv(Path(__file__).parent / ".env")

# =============================================================================
# ✏️  TEST MODE
# =============================================================================

TEST_MODE         = True
TEST_PROFILE_ONLY = True

# =============================================================================
# ✏️  CREDENTIALS — from .env
# =============================================================================

SENDER_EMAIL        = os.getenv("SENDER_EMAIL", "")
SENDER_APP_PASSWORD = os.getenv("SENDER_APP_PASSWORD", "")
BCC_EMAIL           = os.getenv("BCC_EMAIL", "")
SERPER_API_KEY      = os.getenv("SERPER_API_KEY", "")
SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "google_credentials.json")

SHEET_IDS = {
    "Andy":     os.getenv("SHEET_ID_ANDY", ""),
    "Vanessa":  os.getenv("SHEET_ID_VANESSA", ""),
    "Maryjane": os.getenv("SHEET_ID_MARYJANE", ""),
    "David":    os.getenv("SHEET_ID_DAVID", ""),
}

# =============================================================================
# ✏️  SEARCH CONFIG
# =============================================================================

DAYS_BACK         = 10
HISTORY_WEEKS     = 3
REJECT_DAYS       = 90
GEM_AGE_DAYS      = 7     # Jobs stay in Sec 1/2 for this many days
ROWS_VISIBLE      = 20
ATS_RESULTS_CAP   = 5
SHEETS_ENABLED    = True

# PythonAnywhere trigger endpoint (set after deploying)
# Format: "https://yourusername.pythonanywhere.com/run"
TRIGGER_ENDPOINT  = os.getenv("TRIGGER_ENDPOINT", "")
TRIGGER_SECRET    = os.getenv("TRIGGER_SECRET", "")

# =============================================================================
# ✏️  EXCLUSION FILTERS
# =============================================================================

# =============================================================================
# ✏️  EXCLUSION FILTERS
# =============================================================================

# Jobs dropped if ANY of these appear in the TITLE (case-insensitive)
EXCLUDE_TITLE_KEYWORDS = [
    "nursing", "nurse", "software engineer", "developer", "recruiter",
    "sales management", "security engineer", "event coordinator",
    "government affairs", "revenue integrity", "payment accuracy",
]

# Jobs dropped if ANY of these appear in the SNIPPET
EXCLUDE_SNIPPET_KEYWORDS = [
    "entry level", "internship", "intern ", " intern,", "new grad",
    "recent grad", "data scientist",
]

# Debug mode — writes debug_filtered_NAME.csv with every dropped job and reason
# Set to False for normal production runs
DEBUG_FILTERS = True

# =============================================================================
# ✏️  PROFILES
# =============================================================================

PROFILES = [
    {
        "name": "Andy",
        "email": "andrew@varyu.net",
        "salary_minimum": 150000,
        "priority_titles": ["director", "vp", "vice president", "chief", "head of", "senior"],
        "location_preference": "remote",
        "ok_cities": ["seattle", "redmond", "bellevue", "renton", "bothell", "kirkland"],
        "keyword_combos": [
            ["communications", "director"],
            ["director", "communications", "healthcare"],
            ["content strategy", "director"],
            ["content strategy", "senior"],
            ["content strategist", "senior"],
            ["content designer", "senior"],
            ["communications", "engagement", "director"],
            ["VP", "communications"],
            ["communications", "nonprofit"],
        ],
        "industry_filter": [
            "healthcare", "community health", "health system",
            "federally qualified", "nonprofit", "public health",
        ],
    },
    {
        "name": "Vanessa",
        "email": "vdegier@gmail.com",
        "salary_minimum": 200000,
        "priority_titles": ["chief", "vp", "vice president", "svp", "avp", "executive director"],
        "location_preference": "remote",
        "ok_cities": ["santa rosa", "san francisco", "sonoma", "napa", "oakland"],
        "keyword_combos": [
            ["chief communications officer"],
            ["VP", "communications", "healthcare"],
            ["senior vice president", "communications"],
            ["executive director", "communications", "healthcare"],
            ["AVP", "communications"],
            ["chief marketing", "communications", "healthcare"],
        ],
        "industry_filter": [
            "healthcare", "health system", "hospital", "life sciences", "nonprofit",
        ],
    },
    {
        "name": "Maryjane",
        "email": "maryjanebeth@gmail.com",
        "salary_minimum": 200000,
        "priority_titles": ["director", "senior director", "vp", "vice president", "executive director"],
        "location_preference": "remote",
        "ok_cities": ["seattle", "redmond", "bellevue", "renton", "bothell", "kirkland"],
        "keyword_combos": [
            ["senior marketing director", "healthcare"],
            ["director", "marketing", "healthcare"],
            ["executive director", "marketing", "communications"],
            ["VP", "marketing", "healthcare"],
            ["director", "consumer marketing", "health"],
            ["director", "brand", "healthcare"],
        ],
        "industry_filter": [
            "healthcare", "health system", "hospital", "health plan", "nonprofit",
        ],
    },
    {
        "name": "David",
        "email": "dvaryu@gmail.com",
        "salary_minimum": 150000,
        "priority_titles": ["senior", "lead", "principal", "staff", "manager"],
        "location_preference": "",
        "ok_cities": [],
        "keyword_combos": [
            ["civil engineer", "hydraulics"],
            ["civil engineer", "geomorphology"],
            ["civil engineer", "sedimentation"],
            ["hydraulic engineer", "river"],
            ["water resources", "engineer", "sedimentation"],
            ["sediment transport", "engineer"],
            ["dam safety", "hydraulics", "engineer"],
            ["river hydraulics", "engineer"],
        ],
        "industry_filter": [],
    },
]

ATS_SITES = [
    "ashbyhq.com", "lever.co", "greenhouse.io", "workable.com",
    "bamboohr.com", "paylocity.com", "icims.com", "jobvite.com",
    "myworkdayjobs.com", "smartrecruiters.com", "recruitee.com",
    "applytojob.com", "jazz.co", "breezy.hr",
]
SYNDICATION_SITES = ["linkedin.com", "indeed.com", "glassdoor.com"]

STAGE_OPTIONS = [
    "New", "Reviewing", "Applied", "Phone Screen",
    "Interview", "Final Round", "Offer", "Rejected", "Pass"
]

# =============================================================================
# 🔧 COLUMN DEFINITIONS
# =============================================================================

COL = {
    "pinned":          0,   # A — User (green checkbox)
    "reject":          1,   # B — User (red X checkbox)
    "title":           2,   # C — Script
    "company":         3,   # D — Script
    "match":           4,   # E — Script
    "salary":          5,   # F — Script
    "remote":          6,   # G — Script
    "location":        7,   # H — Script
    "url":             8,   # I — Script
    "applied_check":   9,   # J — User (checkbox)
    "date_posted":    10,   # K — Script
    "date_applied":   11,   # L — User/Script (auto-filled)
    "stage":          12,   # M — User (dropdown)
    "notes":          13,   # N — User (text wrap)
    "date_followed":  14,   # O — User
    "contact":        15,   # P — User
    "ats_site":       16,   # Q — Script
    "syndication":    17,   # R — Script
    "resume_version": 18,   # S — User
    "cover_letter":   19,   # T — User (text wrap)
    "first_seen":     20,   # U — Script
    "section":        21,   # V — Script
}
NUM_COLS  = 22
USER_COLS = ["pinned", "reject", "applied_check", "date_applied", "stage",
             "notes", "date_followed", "contact", "resume_version", "cover_letter"]

SHEET_HEADERS = [
    "Pin", "Reject", "Title", "Company", "Match", "Salary",
    "Remote", "Location", "URL", "Applied!", "Date Posted", "Date Applied",
    "Stage", "Notes", "Date Followed Up", "Contact", "ATS Site", "Syndication",
    "Resume Version", "Cover Letter Notes", "First Seen", "Section",
]

SECTION_LABELS = {
    0: ("📌 Pinned",            "Jobs you've starred — stay here until unpinned"),
    1: ("🟢 Hidden Gems",       "New · Not on LinkedIn/Indeed/Glassdoor · Fresh within 7 days"),
    2: ("🔵 Open Market Picks", "New · On major boards · Ranked by relevance · Fresh within 7 days"),
    3: ("🟡 Still Circulating", "Older than 7 days or seen in a previous run"),
    4: ("⚪ Other Matches",     "Possible matches below Strong/Good threshold · Sheet only"),
    5: ("✅ Applied & Waiting", "You've marked as applied"),
}

SECTION_COLORS = {
    0: {"bg": "1e3a5f", "fg": "ffffff"},
    1: {"bg": "166534", "fg": "ffffff"},
    2: {"bg": "1e40af", "fg": "ffffff"},
    3: {"bg": "92400e", "fg": "ffffff"},
    4: {"bg": "4b5563", "fg": "ffffff"},
    5: {"bg": "5b21b6", "fg": "ffffff"},
}

# =============================================================================
# 🔧 HISTORY & REJECT TRACKING
# =============================================================================

HISTORY_DIR = Path(__file__).parent / "history"
HISTORY_DIR.mkdir(exist_ok=True)


def history_path(name):
    return HISTORY_DIR / f"history_{name.lower()}.csv"


# Enriched history CSV fields — single source of truth for all job state
HISTORY_FIELDS = [
    "url", "first_seen", "title", "company", "ats_site",
    "pinned", "rejected", "applied", "stage", "salary", "location", "match"
]


def load_history(name):
    """
    Returns dict {url: {first_seen_date, title, company, pinned, rejected,
    applied, stage, salary, location, match, ats_site}}
    Pinned jobs never age out. Rejected jobs kept for 90 days.
    All others pruned after HISTORY_WEEKS.
    """
    path   = history_path(name)
    cutoff = datetime.date.today() - datetime.timedelta(days=HISTORY_WEEKS * 7)
    reject_cutoff = datetime.date.today() - datetime.timedelta(days=REJECT_DAYS)
    hist   = {}
    if not path.exists():
        return hist
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                url = row.get("url", "")
                if not url:
                    continue
                d        = datetime.date.fromisoformat(row.get("first_seen", "")[:10])
                pinned   = row.get("pinned", "").upper() in ("TRUE", "1", "YES")
                rejected = row.get("rejected", "").upper() in ("TRUE", "1", "YES")
                # Keep if: within window, OR pinned (never expire), OR rejected within 90 days
                if d >= cutoff or pinned or (rejected and d >= reject_cutoff):
                    hist[url] = {
                        "first_seen_date": d,
                        "first_seen":      d.isoformat(),
                        "title":           row.get("title", ""),
                        "company":         row.get("company", ""),
                        "ats_site":        row.get("ats_site", ""),
                        "pinned":          pinned,
                        "rejected":        rejected,
                        "applied":         row.get("applied", "").upper() in ("TRUE","1","YES"),
                        "stage":           row.get("stage", ""),
                        "salary":          row.get("salary", ""),
                        "location":        row.get("location", ""),
                        "match":           row.get("match", ""),
                    }
            except (KeyError, ValueError):
                continue
    return hist


def get_rejected_urls(history):
    """Extract set of rejected URLs from enriched history dict."""
    return {url for url, h in history.items() if h.get("rejected")}


def save_history(name, jobs, prev_user_data, new_rejected_urls=None):
    """
    Write enriched history CSV. Merges current job metadata with
    user state from the sheet (pinned, rejected, applied, stage).
    Pinned jobs never age out. Rejected kept 90 days. Others pruned after HISTORY_WEEKS.
    """
    path     = history_path(name)
    existing = load_history(name)
    today    = datetime.date.today()
    cutoff   = today - datetime.timedelta(days=HISTORY_WEEKS * 7)
    reject_cutoff = today - datetime.timedelta(days=REJECT_DAYS)

    # Mark newly rejected URLs
    if new_rejected_urls:
        for url in new_rejected_urls:
            if url in existing:
                existing[url]["rejected"] = True
            else:
                existing[url] = {
                    "first_seen_date": today,
                    "first_seen":      today.isoformat(),
                    "title": "", "company": "", "ats_site": "",
                    "pinned": False, "rejected": True, "applied": False,
                    "stage": "", "salary": "", "location": "", "match": "",
                }

    # Update existing entries with fresh metadata from this run
    for job in jobs:
        url = job.get("url", "")
        if not url:
            continue
        user     = prev_user_data.get(url, {})
        pinned   = normalize_bool(user.get("pinned", ""))
        rejected = normalize_bool(user.get("reject", ""))
        applied  = normalize_bool(user.get("applied_check", "")) or \
                   bool(user.get("date_applied", "").strip())
        stage    = user.get("stage", "")

        if url in existing:
            entry = existing[url]
            entry["pinned"]   = pinned
            entry["rejected"] = rejected or entry.get("rejected", False)
            entry["applied"]  = applied
            if stage:                  entry["stage"]    = stage
            if job.get("salary"):      entry["salary"]   = job["salary"]
            if job.get("location"):    entry["location"] = job["location"]
            if job.get("relevance_label"): entry["match"] = job["relevance_label"]
            if job.get("title"):       entry["title"]    = job["title"]
            if job.get("company"):     entry["company"]  = job["company"]
            if job.get("ats_site"):    entry["ats_site"] = job["ats_site"]
        else:
            existing[url] = {
                "first_seen_date": today,
                "first_seen":      today.isoformat(),
                "title":           job.get("title", ""),
                "company":         job.get("company", ""),
                "ats_site":        job.get("ats_site", ""),
                "pinned":          pinned,
                "rejected":        rejected,
                "applied":         applied,
                "stage":           stage,
                "salary":          job.get("salary", ""),
                "location":        job.get("location", ""),
                "match":           job.get("relevance_label", ""),
            }

    # Write back — prune based on rules
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
        writer.writeheader()
        for url, entry in existing.items():
            d = entry.get("first_seen_date", today)
            if isinstance(d, str):
                try: d = datetime.date.fromisoformat(d[:10])
                except: d = today
            pinned   = entry.get("pinned", False)
            rejected = entry.get("rejected", False)
            # Keep if: within window, pinned (never expire), or rejected within 90 days
            if d >= cutoff or pinned or (rejected and d >= reject_cutoff):
                writer.writerow({
                    "url":        url,
                    "first_seen": d.isoformat(),
                    "title":      entry.get("title", ""),
                    "company":    entry.get("company", ""),
                    "ats_site":   entry.get("ats_site", ""),
                    "pinned":     "TRUE" if pinned else "FALSE",
                    "rejected":   "TRUE" if rejected else "FALSE",
                    "applied":    "TRUE" if entry.get("applied") else "FALSE",
                    "stage":      entry.get("stage", ""),
                    "salary":     entry.get("salary", ""),
                    "location":   entry.get("location", ""),
                    "match":      entry.get("match", ""),
                })

    pinned_count = sum(1 for e in existing.values() if e.get("pinned"))
    return pinned_count


def load_rejected(name):
    """Convenience wrapper — loads rejected URLs from enriched history."""
    return get_rejected_urls(load_history(name))


def save_rejected(name, new_urls):
    """Convenience wrapper — marks URLs as rejected in enriched history."""
    # Load existing, mark as rejected, save back
    existing = load_history(name)
    today    = datetime.date.today()
    for url in new_urls:
        if url in existing:
            existing[url]["rejected"] = True
        else:
            existing[url] = {
                "first_seen_date": today, "first_seen": today.isoformat(),
                "title": "", "company": "", "ats_site": "",
                "pinned": False, "rejected": True, "applied": False,
                "stage": "", "salary": "", "location": "", "match": "",
            }
    # Write back via save_history with empty jobs list
    path = history_path(name)
    reject_cutoff = today - datetime.timedelta(days=REJECT_DAYS)
    cutoff = today - datetime.timedelta(days=HISTORY_WEEKS * 7)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
        writer.writeheader()
        for url, entry in existing.items():
            d = entry.get("first_seen_date", today)
            if isinstance(d, str):
                try: d = datetime.date.fromisoformat(d[:10])
                except: d = today
            pinned   = entry.get("pinned", False)
            rejected = entry.get("rejected", False)
            if d >= cutoff or pinned or (rejected and d >= reject_cutoff):
                writer.writerow({
                    "url": url, "first_seen": d.isoformat(),
                    "title": entry.get("title",""), "company": entry.get("company",""),
                    "ats_site": entry.get("ats_site",""),
                    "pinned":   "TRUE" if pinned else "FALSE",
                    "rejected": "TRUE" if rejected else "FALSE",
                    "applied":  "TRUE" if entry.get("applied") else "FALSE",
                    "stage": entry.get("stage",""), "salary": entry.get("salary",""),
                    "location": entry.get("location",""), "match": entry.get("match",""),
                })


# =============================================================================
# 🔧 PRE-FILTERS
# =============================================================================

# =============================================================================
# 🔧 PRE-FILTERS
# =============================================================================

# Known wrong-city signals — explicit non-remote locations not in any ok_cities list
# Only used when strict location checking is needed
WRONG_CITY_SIGNALS = [
    "new york", "chicago", "boston", "austin", "denver", "atlanta",
    "dallas", "houston", "miami", "philadelphia", "phoenix", "portland",
    "san diego", "minneapolis", "detroit", "nashville", "charlotte",
    "pittsburgh", "cleveland", "cincinnati",
]


def check_exclusion_filter(job):
    """Returns (passes: bool, reason: str)"""
    title   = job.get("title", "").lower()
    snippet = job.get("snippet", "").lower()
    for kw in EXCLUDE_TITLE_KEYWORDS:
        if kw.lower() in title:
            return False, f"title contains '{kw}'"
    for kw in EXCLUDE_SNIPPET_KEYWORDS:
        if kw.lower() in snippet:
            return False, f"snippet contains '{kw}'"
    return True, ""


def check_location_filter(job, profile):
    """
    Returns (passes: bool, reason: str)
    LENIENT: only drop if a clearly wrong city is explicitly mentioned
    AND there is no remote signal. If location is ambiguous/missing → keep.
    """
    ok_cities = profile.get("ok_cities", [])
    if not ok_cities:
        return True, ""   # David — no city filter

    text = (job.get("title", "") + " " +
            job.get("snippet", "") + " " +
            job.get("location", "")).lower()

    remote_signals = ["remote", "work from home", "wfh", "fully remote",
                      "100% remote", "anywhere", "distributed", "hybrid"]

    # Keep if any remote signal present
    if any(sig in text for sig in remote_signals):
        return True, ""

    # Keep if an ok city is mentioned
    if any(city in text for city in ok_cities):
        return True, ""

    # Drop ONLY if a clearly wrong city is explicitly mentioned
    for wrong_city in WRONG_CITY_SIGNALS:
        if wrong_city in text:
            return False, f"explicit wrong city: '{wrong_city}'"

    # Location ambiguous or not mentioned — keep (benefit of the doubt)
    return True, ""


def passes_exclusion_filter(job):
    passed, _ = check_exclusion_filter(job)
    return passed


def passes_location_filter(job, profile):
    passed, _ = check_location_filter(job, profile)
    return passed


def write_debug_filtered(name, dropped_jobs):
    """Write CSV of dropped jobs with reasons for filter debugging."""
    if not DEBUG_FILTERS or not dropped_jobs:
        return
    path = HISTORY_DIR / f"debug_filtered_{name.lower()}.csv"
    fields = ["title", "company", "url", "ats_site", "location", "snippet_preview",
              "filter_reason"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for job, reason in dropped_jobs:
            writer.writerow({
                "title":            job.get("title", "")[:80],
                "company":          job.get("company", ""),
                "url":              job.get("url", ""),
                "ats_site":         job.get("ats_site", ""),
                "location":         job.get("location", ""),
                "snippet_preview":  job.get("snippet", "")[:120],
                "filter_reason":    reason,
            })
    print(f"    🔍 Debug: {len(dropped_jobs)} filtered jobs written to {path.name}")


# =============================================================================
# 🔧 SEARCH & EXTRACTION
# =============================================================================

SERPER_URL     = "https://google.serper.dev/search"
SERPER_HEADERS = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}


def serper_search(query, num_results=10):
    try:
        r = requests.post(SERPER_URL, headers=SERPER_HEADERS,
                          json={"q": query, "num": num_results}, timeout=10)
        r.raise_for_status()
        return r.json().get("organic", [])
    except requests.exceptions.RequestException as e:
        print(f"    ⚠️  Serper: {e}")
        return []


def build_query(keywords, site, days_back, industry_terms):
    kw  = " ".join(f'"{k}"' if " " in k else k for k in keywords)
    ind = (" (" + " OR ".join(f'"{t}"' for t in industry_terms) + ")") if industry_terms else ""
    dt  = f" after:{(datetime.date.today() - datetime.timedelta(days=days_back)).isoformat()}"
    return f"site:{site} {kw}{ind}{dt}"


def extract_company(result, site, url):
    title   = result.get("title", "")
    snippet = result.get("snippet", "")
    try:
        parsed = urlparse(url)
        host   = parsed.hostname or ""
        path   = parsed.path
        if "lever.co" in host:
            parts = path.strip("/").split("/")
            if parts: return parts[0].replace("-", " ").title()
        if "greenhouse.io" in host:
            parts = path.strip("/").split("/")
            if parts: return parts[0].replace("-", " ").title()
        if "ashbyhq.com" in host:
            parts = path.strip("/").split("/")
            if parts: return parts[0].replace("-", " ").title()
        if "bamboohr.com" in host:
            subdomain = host.split(".")[0]
            if subdomain and subdomain not in ["app", "www"]:
                return subdomain.replace("-", " ").title()
        if "workable.com" in host:
            parts = path.strip("/").split("/")
            if parts: return parts[0].replace("-", " ").title()
        if "smartrecruiters.com" in host:
            parts = path.strip("/").split("/")
            if parts: return parts[0].replace("-", " ").title()
        if "myworkdayjobs.com" in host:
            subdomain = host.split(".")[0]
            if subdomain: return subdomain.replace("-", " ").title()
    except Exception:
        pass
    for sep in [" at ", " | ", " - "]:
        if sep in title:
            parts = title.split(sep)
            if len(parts) >= 2:
                candidate = parts[-1].strip()
                ats_names = ["greenhouse", "lever", "workday", "workable",
                             "bamboohr", "icims", "jobvite", "smartrecruiters"]
                if not any(a in candidate.lower() for a in ats_names):
                    return candidate[:60]
    m = re.search(r'\bat\s+([A-Z][A-Za-z\s&,\.]+?)(?:\.|,|\s-|\sin\s|$)', snippet)
    if m:
        candidate = m.group(1).strip()
        if 3 < len(candidate) < 60:
            return candidate
    return "Unknown"


def extract_salary(text):
    m = re.search(r'\$\d{1,3}(?:,\d{3})+\s*[-–to]+\s*\$\d{1,3}(?:,\d{3})+',
                  text, re.IGNORECASE)
    if m: return m.group(0).strip()
    m = re.search(r'\$\d{1,3}(?:,\d{3})+(?:\s*(?:/yr|/year|annually))?', text, re.IGNORECASE)
    if m: return m.group(0).strip()
    m = re.search(r'\$\d{2,3}[kK]\s*[-–to]+\s*\$\d{2,3}[kK]', text)
    if m: return m.group(0).strip()
    m = re.search(r'\$\d{2,3}[kK]', text)
    if m: return m.group(0).strip()
    m = re.search(r'\$\d{2,3}(?:\.\d{2})?\s*/\s*h(?:r|our)', text, re.IGNORECASE)
    if m: return m.group(0).strip()
    return ""


def extract_salary_value(salary_str):
    if not salary_str: return None
    nums = re.findall(r'\d+', salary_str.replace(",", ""))
    if not nums: return None
    try:
        val = int(nums[0])
        if val < 1000: val *= 1000
        return val
    except ValueError:
        return None


def extract_remote(text):
    tl = text.lower()
    if "fully remote" in tl or "100% remote" in tl: return "Remote"
    if "in-range" in tl or "within commuting" in tl or "commutable" in tl: return "In-range"
    if "remote" in tl and "hybrid" not in tl: return "Remote"
    if "hybrid" in tl: return "Hybrid"
    if "on-site" in tl or "onsite" in tl or "in-office" in tl: return "In-person"
    return "In-person"


def extract_location(text):
    m = re.search(r'\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?,\s*(?:[A-Z]{2}|Remote))\b', text)
    return m.group(0) if m else ""


def fetch_job_page(url):
    """
    Fetch job page. Priority: JSON-LD structured data → text regex fallback.
    Returns (salary, location, remote, date_posted).
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/120.0.0.0 Safari/537.36"}
        r    = requests.get(url, headers=headers, timeout=8)
        html = r.text

        salary      = ""
        location    = ""
        remote      = ""
        date_posted = ""

        # JSON-LD parsing
        json_ld_blocks = re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        )
        for block in json_ld_blocks:
            try:
                data  = json.loads(block.strip())
                items = data if isinstance(data, list) else [data]
                if isinstance(data, dict) and "@graph" in data:
                    items = data["@graph"]
                for item in items:
                    if not isinstance(item, dict): continue
                    job_type = item.get("@type", "")
                    if "JobPosting" not in (job_type if isinstance(job_type, str)
                                            else " ".join(job_type)):
                        continue
                    # Date posted
                    if not date_posted:
                        dp = item.get("datePosted", "")
                        if dp:
                            try:
                                d = datetime.date.fromisoformat(dp[:10])
                                date_posted = d.strftime("%b %d, %Y")
                            except ValueError:
                                date_posted = dp[:10]
                    # Location
                    if not location:
                        jl   = item.get("jobLocation", {})
                        if isinstance(jl, list): jl = jl[0] if jl else {}
                        addr = jl.get("address", {}) if isinstance(jl, dict) else {}
                        if isinstance(addr, dict):
                            city  = addr.get("addressLocality", "")
                            state = addr.get("addressRegion", "")
                            if city: location = f"{city}, {state}".strip(", ")
                    # Remote
                    if not remote:
                        wl = str(item.get("jobLocationType", "")).lower()
                        if "remote" in wl or "telecommute" in wl:
                            remote = "Remote"
                    # Salary
                    if not salary:
                        bs = item.get("baseSalary", {})
                        if isinstance(bs, dict):
                            val = bs.get("value", {})
                            if isinstance(val, dict):
                                mn     = val.get("minValue", "")
                                mx     = val.get("maxValue", "")
                                period = str(val.get("unitText", "")).upper()
                                if mn and mx:
                                    if period in ("HOUR", "HR"):
                                        salary = f"${mn}–${mx}/hr"
                                    else:
                                        try:
                                            salary = f"${int(float(mn)):,}–${int(float(mx)):,}"
                                        except (ValueError, TypeError):
                                            salary = f"${mn}–${mx}"
                                elif mn:
                                    try: salary = f"${int(float(mn)):,}+"
                                    except: salary = f"${mn}+"
                    if location and salary and date_posted: break
            except (json.JSONDecodeError, Exception):
                continue

        # Text fallback
        clean = re.sub(r'<[^>]+>', ' ', html[:12000])
        clean = re.sub(r'\s+', ' ', clean)
        if not salary:   salary   = extract_salary(clean)
        if not location: location = extract_location(clean)
        if not remote:   remote   = extract_remote(clean)

        return salary, location, remote, date_posted

    except Exception:
        return "", "", "", ""


def check_syndication(title, company):
    results     = {}
    clean_title = title.split("|")[0].split("-")[0].strip()[:60]
    clean_co    = company.strip()[:40]
    query       = f'"{clean_title}" "{clean_co}"'
    for site in SYNDICATION_SITES:
        hits          = serper_search(f"site:{site} {query}", num_results=3)
        results[site] = len(hits) > 0
        time.sleep(0.3)
    return results


# =============================================================================
# 🔧 RELEVANCE SCORING — title 80% / seniority 7% / location 13%
# Strong ≥ 20 / Good ≥ 10 / Possible < 10
# =============================================================================

def score_job(job, profile):
    title   = job["title"].lower()
    score   = 0.0
    reasons = []

    # Title — 80% = 24 pts max
    hits        = [t for t in profile["priority_titles"] if t in title]
    title_score = min(24.0, len(hits) * 9.0)
    score      += title_score
    if hits: reasons.append(f"title: {', '.join(hits[:2])}")

    # Seniority — 7% = 2.1 pts max
    sen_terms = ["director","vp","vice president","chief","svp","avp",
                 "senior","lead","principal","head of","executive"]
    sen_hits  = [t for t in sen_terms if t in title]
    score    += min(2.1, len(sen_hits) * 2.1)
    if sen_hits: reasons.append(f"level: {sen_hits[0]}")

    # Location — 13% = 3.9 pts max
    pref      = profile.get("location_preference", "").lower()
    remote    = job.get("remote", "In-person").lower()
    loc       = job.get("location", "").lower()
    ok_cities = [c.lower() for c in profile.get("ok_cities", [])]
    ls        = 0.0
    if not profile.get("ok_cities"):
        ls = 2.0
    elif "remote" in remote:
        ls = 3.9; reasons.append("remote ✓")
    elif "hybrid" in remote or "in-range" in remote:
        ls = 2.5; reasons.append(f"{remote} ✓")
    elif any(city in loc for city in ok_cities):
        ls = 3.9; reasons.append("city ✓")
    score += ls
    score  = round(score, 1)

    label = "🟢 Strong" if score >= 20 else "🟡 Good" if score >= 10 else "🔵 Possible"
    job["relevance_score"]   = score
    job["relevance_label"]   = label
    job["relevance_reasons"] = reasons
    return score


# =============================================================================
# 🔧 SECTION LOGIC — age-based (7 days) replaces seen_before for Sec 1/2
# =============================================================================

def get_job_section(job, prev_user_data):
    url        = job.get("url", "")
    prev       = prev_user_data.get(url, {})
    today      = datetime.date.today()
    first_seen = job.get("first_seen_date", today)
    age_days   = (today - first_seen).days

    # Pinned overrides everything
    if normalize_bool(prev.get("pinned", "")):
        return 0

    # Applied overrides section
    applied = normalize_bool(prev.get("applied_check", ""))
    dated   = bool(prev.get("date_applied", "").strip())
    if applied or dated:
        return 5

    label = job.get("relevance_label", "🔵 Possible")

    # Possible always goes to Section 4
    if label == "🔵 Possible":
        return 4

    # Fresh jobs (within GEM_AGE_DAYS) stay in Sec 1 or 2
    if age_days <= GEM_AGE_DAYS:
        return 1 if job.get("unsyndicated") else 2

    # Older than 7 days → Section 3
    return 3


# =============================================================================
# 🔧 MAIN SEARCH RUNNER
# =============================================================================

def search_for_profile(profile):
    name      = profile["name"]
    sal_min   = profile.get("salary_minimum", 0)
    history   = load_history(name)   # Now returns {url: rich_dict}
    rejected  = load_rejected(name)
    pinned_count = sum(1 for e in history.values() if e.get("pinned"))
    print(f"\n  👤 {name} | min ${sal_min:,} | {len(history)} history | "
          f"{pinned_count} pinned | {len(rejected)} filtered out")

    results, seen = [], set()

    for site in ATS_SITES:
        for combo in profile["keyword_combos"]:
            hits = serper_search(
                build_query(combo, site, DAYS_BACK, profile["industry_filter"]),
                num_results=ATS_RESULTS_CAP
            )
            time.sleep(0.4)
            for r in hits:
                url = r.get("link", "")
                if url in seen or url in rejected:
                    continue
                seen.add(url)
                text   = r.get("snippet", "") + " " + r.get("title", "")
                salary = extract_salary(text)
                remote = extract_remote(text)
                loc    = extract_location(text)
                hist_entry      = history.get(url, {})
                first_seen_date = hist_entry.get("first_seen_date", datetime.date.today())
                results.append({
                    "title":             r.get("title", "No title"),
                    "company":           extract_company(r, site, url),
                    "url":               url,
                    "ats_site":          site,
                    "keywords":          ", ".join(combo),
                    "snippet":           r.get("snippet", ""),
                    "salary":            salary,
                    "remote":            remote,
                    "location":          loc,
                    "date_posted":       "",
                    "seen_before":       url in history,
                    "first_seen_date":   first_seen_date,
                    "first_seen":        first_seen_date.isoformat(),
                    "on_linkedin":       False,
                    "on_indeed":         False,
                    "on_glassdoor":      False,
                    "unsyndicated":      False,
                    "relevance_score":   0.0,
                    "relevance_label":   "",
                    "relevance_reasons": [],
                })

    raw_count   = len(results)
    kept        = []
    dropped     = []   # (job, reason) tuples for debug

    for job in results:
        excl_pass, excl_reason = check_exclusion_filter(job)
        if not excl_pass:
            dropped.append((job, excl_reason)); continue
        loc_pass, loc_reason = check_location_filter(job, profile)
        if not loc_pass:
            dropped.append((job, loc_reason)); continue
        kept.append(job)

    results = kept
    print(f"    {raw_count} found → {len(results)} after filters "
          f"({len(dropped)} dropped)")

    if DEBUG_FILTERS:
        write_debug_filtered(name, dropped)

    for job in results:
        score_job(job, profile)

    strong_good = [j for j in results
                   if j["relevance_label"] in ("🟢 Strong", "🟡 Good")
                   and not j["seen_before"]]
    print(f"    {len(strong_good)} new Strong/Good to cross-ref+fetch")

    for i, job in enumerate(strong_good):
        print(f"    [{i+1}/{len(strong_good)}] {job['title'][:55]}...")
        synd = check_syndication(job["title"], job["company"])
        job["on_linkedin"]  = synd.get("linkedin.com", False)
        job["on_indeed"]    = synd.get("indeed.com", False)
        job["on_glassdoor"] = synd.get("glassdoor.com", False)
        job["unsyndicated"] = not any(synd.values())

        pg_sal, pg_loc, pg_rem, pg_date = fetch_job_page(job["url"])
        if pg_sal  and not job["salary"]:      job["salary"]      = pg_sal
        if pg_loc  and not job["location"]:    job["location"]    = pg_loc
        if pg_rem  and job["remote"] == "In-person": job["remote"] = pg_rem
        if pg_date and not job["date_posted"]: job["date_posted"] = pg_date

        sal_val = extract_salary_value(job["salary"])
        if sal_val is not None and sal_val < sal_min:
            print(f"      ↓ Demoted (salary {job['salary']} < ${sal_min:,})")
            job["relevance_label"] = "🔵 Possible"
            job["relevance_score"] = min(job["relevance_score"], 9.9)

        time.sleep(0.5)

    for job in results:
        if job["seen_before"]:
            job["unsyndicated"] = True

    # save_history called later in update_sheet after we have prev_user_data
    return results


# =============================================================================
# 🔧 GOOGLE SHEETS
# =============================================================================

def normalize_bool(val):
    if isinstance(val, bool): return val
    if isinstance(val, str):  return val.upper() in ("TRUE", "1", "YES", "✓", "X")
    return False


def get_sheets_service():
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print(f"    ⚠️  Credentials not found: {SERVICE_ACCOUNT_FILE}")
        return None
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        return build("sheets", "v4", credentials=creds)
    except Exception as e:
        print(f"    ⚠️  Sheets auth: {e}")
        return None


def read_existing_rows(service, sheet_id):
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id, range="A:V"
        ).execute()
        rows = result.get("values", [])
    except Exception as e:
        print(f"    ⚠️  Read error: {e}")
        return {}
    if len(rows) < 2:
        return {}
    url_idx  = COL["url"]
    existing = {}
    for row in rows[1:]:
        while len(row) < NUM_COLS:
            row.append("")
        url = row[url_idx]
        # Skip section header rows (no URL) and the column header row
        if not url or not url.startswith("http"):
            continue
        existing[url] = {col_name: row[idx] for col_name, idx in COL.items()}
    return existing


def job_to_row(job, section_num, prev_user_data, today):
    row  = [""] * NUM_COLS
    url  = job.get("url", "")
    prev = prev_user_data.get(url, {})

    row[COL["title"]]       = job.get("title", "")
    row[COL["company"]]     = job.get("company", "")
    row[COL["match"]]       = job.get("relevance_label", "")
    row[COL["salary"]]      = job.get("salary", "") or "n/a"
    row[COL["remote"]]      = job.get("remote", "") or "Unknown"
    row[COL["location"]]    = job.get("location", "") or "unknown"
    row[COL["url"]]         = url
    row[COL["date_posted"]] = job.get("date_posted", "")
    row[COL["section"]]     = str(section_num)
    row[COL["ats_site"]]    = job.get("ats_site", "")
    row[COL["first_seen"]]  = job.get("first_seen", today)

    flags = []
    if job.get("on_linkedin"):  flags.append("LinkedIn")
    if job.get("on_indeed"):    flags.append("Indeed")
    if job.get("on_glassdoor"): flags.append("Glassdoor")
    row[COL["syndication"]] = ", ".join(flags) if flags else "Not syndicated"

    # User columns
    for col_name in USER_COLS:
        val = prev.get(col_name, "")
        if col_name in ("pinned", "reject", "applied_check"):
            row[COL[col_name]] = normalize_bool(val)
        else:
            row[COL[col_name]] = val

    # Auto-fill date_applied if applied is checked but date is blank
    if normalize_bool(prev.get("applied_check", "")) and not prev.get("date_applied", "").strip():
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        row[COL["date_applied"]] = yesterday

    return row


def rewrite_sheet(service, sheet_id, name, all_jobs, prev_user_data):
    today    = datetime.date.today().isoformat()
    sections = {i: [] for i in range(6)}

    for job in all_jobs:
        sec = get_job_section(job, prev_user_data)
        sections[sec].append(job)

    for sec in sections:
        sections[sec].sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

    all_rows = [SHEET_HEADERS]
    row_meta = []
    blank_row = [""] * NUM_COLS
    first_section = True

    for sec in range(6):
        jobs = sections[sec]
        if not jobs:
            continue

        # Add 2 blank spacer rows before every section except the first
        if not first_section:
            for _ in range(2):
                all_rows.append(blank_row[:])
                row_meta.append({"section": sec, "is_header": False,
                                 "is_overflow": False, "is_spacer": True,
                                 "sheet_row": len(all_rows) - 1})
        first_section = False

        label, _ = SECTION_LABELS[sec]
        all_rows.append([label] + [""] * (NUM_COLS - 1))
        row_meta.append({"section": sec, "is_header": True, "is_overflow": False,
                         "is_spacer": False, "sheet_row": len(all_rows) - 1})

        for i, job in enumerate(jobs):
            # Skip ghost rows — must have both a title and a URL to be valid
            if not job.get("title", "").strip() or not job.get("url", "").startswith("http"):
                continue
            row = job_to_row(job, sec, prev_user_data, today)
            row = ["TRUE" if v is True else "FALSE" if v is False else v for v in row]
            all_rows.append(row)
            overflow = (sec != 5) and (i >= ROWS_VISIBLE)
            row_meta.append({"section": sec, "is_header": False,
                             "is_overflow": overflow, "is_spacer": False,
                             "sheet_row": len(all_rows) - 1})

    try:
        # First get current sheet dimensions to know what to delete
        sheet_meta = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        sheet_props = next(
            (s["properties"] for s in sheet_meta.get("sheets", [])
             if s["properties"]["sheetId"] == 0), {}
        )
        current_rows = sheet_props.get("gridProperties", {}).get("rowCount", 1000)
        current_cols = sheet_props.get("gridProperties", {}).get("columnCount", 26)

        # Clear all values
        service.spreadsheets().values().clear(
            spreadsheetId=sheet_id, range="A:Z"
        ).execute()

        # Write new data
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id, range="A1",
            valueInputOption="USER_ENTERED",
            body={"values": all_rows}
        ).execute()

        # Delete excess rows beyond what we wrote (eliminates ghost rows)
        rows_written = len(all_rows)
        if current_rows > rows_written + 5:
            service.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body={"requests": [{"deleteDimension": {
                    "range": {"sheetId": 0, "dimension": "ROWS",
                              "startIndex": rows_written,
                              "endIndex": current_rows}
                }}]}
            ).execute()

        # Delete excess columns beyond NUM_COLS (eliminates ghost columns)
        if current_cols > NUM_COLS + 1:
            service.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body={"requests": [{"deleteDimension": {
                    "range": {"sheetId": 0, "dimension": "COLUMNS",
                              "startIndex": NUM_COLS,
                              "endIndex": current_cols}
                }}]}
            ).execute()

        print(f"    📊 Wrote {len(all_rows)-1} rows ({len(sections[0])} pinned, "
              f"{len(sections[1])+len(sections[2])} new, "
              f"{len(sections[3])} circulating, {len(sections[4])} possible, "
              f"{len(sections[5])} applied)")
    except Exception as e:
        print(f"    ❌ Write error: {e}"); return

    apply_sheet_formatting(service, sheet_id, all_rows, row_meta)


def apply_sheet_formatting(service, sheet_id, all_rows, row_meta):
    batch = []
    gid   = 0

    # Freeze header
    batch.append({"updateSheetProperties": {
        "properties": {"sheetId": gid, "gridProperties": {"frozenRowCount": 1}},
        "fields": "gridProperties.frozenRowCount"
    }})

    # Column widths
    widths = {
        0: 30,   # Pinned (checkbox — narrow)
        1: 30,   # Reject (checkbox — narrow)
        2: 220,  # Title (wider — was 190 before Reject col was added)
        3: 160,  # Company
        4: 50,   # Match
        5: 100,  # Salary
        6: 72,   # Remote
        7: 90,   # Location
        8: 100,  # URL
        9: 55,   # Applied!
        10: 90,  # Date Posted
        11: 100, # Date Applied
        12: 140, # Stage
        13: 205, # Notes
        14: 100, # Date Followed Up
        15: 140, # Contact
        16: 110, # ATS Site
        17: 130, # Syndication
        18: 120, # Resume Version
        19: 200, # Cover Letter Notes
        20: 90,  # First Seen
        21: 50,  # Section
    }
    for col_idx, px in widths.items():
        batch.append({"updateDimensionProperties": {
            "range": {"sheetId": gid, "dimension": "COLUMNS",
                      "startIndex": col_idx, "endIndex": col_idx + 1},
            "properties": {"pixelSize": px},
            "fields": "pixelSize"
        }})

    # Header row (column header)
    batch.append({"repeatCell": {
        "range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1},
        "cell": {"userEnteredFormat": {
            "backgroundColor": {"red": 0.05, "green": 0.05, "blue": 0.05},
            "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1},
                           "bold": True, "fontSize": 10},
            "verticalAlignment": "MIDDLE"
        }},
        "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment)"
    }})

    # Rotate text UP in narrow columns A and B header cells
    for col_idx in [0, 1]:
        batch.append({"repeatCell": {
            "range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1},
            "cell": {"userEnteredFormat": {
                "textRotation": {"angle": 90}
            }},
            "fields": "userEnteredFormat.textRotation"
        }})

    # STEP 1: Clear all backgrounds on data rows first
    batch.append({"repeatCell": {
        "range": {"sheetId": gid, "startRowIndex": 1},
        "cell": {"userEnteredFormat": {
            "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}
        }},
        "fields": "userEnteredFormat.backgroundColor"
    }})

    # STEP 2: Apply column colors AFTER clearing (so they're not wiped)
    # Pinned col (A) — green bg
    batch.append({"repeatCell": {
        "range": {"sheetId": gid, "startRowIndex": 1,
                  "startColumnIndex": 0, "endColumnIndex": 1},
        "cell": {"userEnteredFormat": {
            "backgroundColor": {"red": 0.88, "green": 0.96, "blue": 0.88}
        }},
        "fields": "userEnteredFormat.backgroundColor"
    }})

    # Reject col (B) — red bg
    batch.append({"repeatCell": {
        "range": {"sheetId": gid, "startRowIndex": 1,
                  "startColumnIndex": 1, "endColumnIndex": 2},
        "cell": {"userEnteredFormat": {
            "backgroundColor": {"red": 0.99, "green": 0.88, "blue": 0.88}
        }},
        "fields": "userEnteredFormat.backgroundColor"
    }})

    # STEP 3: Apply checkboxes and dropdowns only to actual data rows (skip section headers and spacers)
    # Collect data row indices from row_meta
    data_row_indices = [i + 1 for i, m in enumerate(row_meta)
                        if not m["is_header"] and not m.get("is_spacer", False)]

    # Apply checkboxes row by row to avoid hitting section header rows
    for sr in data_row_indices:
        # Pinned checkbox
        batch.append({"repeatCell": {
            "range": {"sheetId": gid, "startRowIndex": sr, "endRowIndex": sr + 1,
                      "startColumnIndex": 0, "endColumnIndex": 1},
            "cell": {"dataValidation": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}},
            "fields": "dataValidation"
        }})
        # Reject checkbox
        batch.append({"repeatCell": {
            "range": {"sheetId": gid, "startRowIndex": sr, "endRowIndex": sr + 1,
                      "startColumnIndex": 1, "endColumnIndex": 2},
            "cell": {"dataValidation": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}},
            "fields": "dataValidation"
        }})
        # Applied! checkbox
        batch.append({"repeatCell": {
            "range": {"sheetId": gid, "startRowIndex": sr, "endRowIndex": sr + 1,
                      "startColumnIndex": 9, "endColumnIndex": 10},
            "cell": {"dataValidation": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}},
            "fields": "dataValidation"
        }})

    # Stage dropdown (col 12) — apply to all data rows in one call (dropdown in headers is harmless)
    batch.append({"repeatCell": {
        "range": {"sheetId": gid, "startRowIndex": 1,
                  "startColumnIndex": 12, "endColumnIndex": 13},
        "cell": {"dataValidation": {
            "condition": {
                "type": "ONE_OF_LIST",
                "values": [{"userEnteredValue": s} for s in STAGE_OPTIONS]
            },
            "showCustomUi": True,
            "strict": False
        }},
        "fields": "dataValidation"
    }})

    # Text wrap — Notes (col 13) and Cover Letter Notes (col 19)
    for wrap_col in [13, 19]:
        batch.append({"repeatCell": {
            "range": {"sheetId": gid, "startRowIndex": 1,
                      "startColumnIndex": wrap_col, "endColumnIndex": wrap_col + 1},
            "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
            "fields": "userEnteredFormat.wrapStrategy"
        }})

    # Section header colors — exactly one row each, applied after background clear
    for i, meta in enumerate(row_meta):
        sr = i + 1
        if meta["is_header"]:
            sec   = meta["section"]
            color = SECTION_COLORS.get(sec, {"bg": "333333"})
            bg    = color["bg"]
            r     = int(bg[0:2], 16) / 255
            g     = int(bg[2:4], 16) / 255
            b     = int(bg[4:6], 16) / 255
            batch.append({"repeatCell": {
                "range": {"sheetId": gid, "startRowIndex": sr, "endRowIndex": sr + 1},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": {"red": r, "green": g, "blue": b},
                    "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1},
                                   "bold": True, "fontSize": 10}
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat)"
            }})
        elif meta["is_overflow"]:
            batch.append({"repeatCell": {
                "range": {"sheetId": gid, "startRowIndex": sr, "endRowIndex": sr + 1},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": {"red": 0.97, "green": 0.97, "blue": 0.97}
                }},
                "fields": "userEnteredFormat.backgroundColor"
            }})

    # Build overflow ranges (skip spacer rows)
    overflow_ranges = []
    in_overflow, start_row = False, None
    for i, meta in enumerate(row_meta):
        sr = i + 1
        if meta.get("is_spacer"):
            if in_overflow:
                overflow_ranges.append((start_row, sr)); in_overflow = False
            continue
        if meta["is_overflow"] and not in_overflow:
            in_overflow = True; start_row = sr
        elif not meta["is_overflow"] and in_overflow:
            overflow_ranges.append((start_row, sr)); in_overflow = False
    if in_overflow:
        overflow_ranges.append((start_row, len(row_meta) + 1))

    # Delete existing groups (all depths)
    for depth in range(5, 0, -1):
        try:
            service.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body={"requests": [{"deleteDimensionGroup": {
                    "range": {"sheetId": gid, "dimension": "ROWS",
                              "startIndex": 1, "endIndex": 10000},
                    "depth": depth
                }}]}
            ).execute()
        except Exception:
            pass

    # Split batch into chunks of 50 to avoid 500 errors on large sheets
    def run_batch_chunks(requests, chunk_size=50):
        for i in range(0, len(requests), chunk_size):
            chunk = requests[i:i + chunk_size]
            try:
                service.spreadsheets().batchUpdate(
                    spreadsheetId=sheet_id, body={"requests": chunk}
                ).execute()
            except Exception as e:
                print(f"    ⚠️  Formatting chunk error: {e}")

    run_batch_chunks(batch)

    # Add + collapse groups one at a time
    for s, e in overflow_ranges:
        try:
            service.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body={"requests": [{"addDimensionGroup": {
                    "range": {"sheetId": gid, "dimension": "ROWS",
                              "startIndex": s, "endIndex": e}
                }}]}
            ).execute()
            service.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id,
                body={"requests": [{"updateDimensionGroup": {
                    "dimensionGroup": {
                        "range": {"sheetId": gid, "dimension": "ROWS",
                                  "startIndex": s, "endIndex": e},
                        "depth": 1, "collapsed": True
                    },
                    "fields": "collapsed"
                }}]}
            ).execute()
        except Exception as ex:
            print(f"    ⚠️  Group error ({s}:{e}): {ex}")

    print(f"    🎨 Formatting applied ({len(overflow_ranges)} groups)")
    create_filter_views(service, sheet_id, gid)


def create_filter_views(service, sheet_id, gid):
    today = datetime.date.today().isoformat()
    try:
        meta   = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        sheets = meta.get("sheets", [])
        info   = next((s for s in sheets if s["properties"]["sheetId"] == gid), None)
        if info:
            del_ids = [fv["filterViewId"] for fv in info.get("filterViews", [])
                       if fv.get("title", "").startswith("🔍")]
            if del_ids:
                service.spreadsheets().batchUpdate(
                    spreadsheetId=sheet_id,
                    body={"requests": [{"deleteFilterView": {"filterId": fid}}
                                       for fid in del_ids]}
                ).execute()
    except Exception:
        pass

    filter_views = [
        {"title": "🔍 Pinned",        "col": COL["pinned"],      "type": "CUSTOM_FORMULA",  "val": "=$A2=TRUE"},
        {"title": "🔍 Strong Matches","col": COL["match"],       "type": "TEXT_CONTAINS",   "val": "Strong"},
        {"title": "🔍 New This Run",  "col": COL["first_seen"],  "type": "TEXT_EQ",         "val": today},
        {"title": "🔍 Applied",       "col": COL["section"],     "type": "TEXT_EQ",         "val": "5"},
    ]
    requests = []
    for fv in filter_views:
        requests.append({"addFilterView": {"filter": {
            "title": fv["title"],
            "range": {"sheetId": gid, "startRowIndex": 0,
                      "startColumnIndex": 0, "endColumnIndex": NUM_COLS},
            "filterSpecs": [{"columnIndex": fv["col"], "filterCriteria": {
                "condition": {"type": fv["type"],
                              "values": [{"userEnteredValue": fv["val"]}]}
            }}]
        }}})
    try:
        service.spreadsheets().batchUpdate(
            spreadsheetId=sheet_id, body={"requests": requests}
        ).execute()
        print(f"    🔍 Filter views created")
    except Exception as e:
        print(f"    ⚠️  Filter view error: {e}")


def update_sheet(name, all_jobs, prev_user_data, new_rejected_urls):
    if not SHEETS_ENABLED: return
    sheet_id = SHEET_IDS.get(name, "")
    if not sheet_id or not sheet_id.strip():
        print(f"    ⚠️  No Sheet ID for {name}"); return
    service = get_sheets_service()
    if not service: return

    # Save newly rejected URLs
    if new_rejected_urls:
        save_rejected(name, new_rejected_urls)
        print(f"    🚫 {len(new_rejected_urls)} URLs added to reject list")

    current_urls = {j["url"] for j in all_jobs}
    rejected     = load_rejected(name)
    history      = load_history(name)

    # Resurrect pinned jobs from enriched history — the single source of truth
    for url, h in history.items():
        if url in current_urls or url in rejected:
            continue
        if not h.get("pinned"):
            continue
        # This URL was previously pinned — resurrect it
        fs = h.get("first_seen_date", datetime.date.today() - datetime.timedelta(days=8))
        revived = {
            "title":           h.get("title", ""),
            "company":         h.get("company", ""),
            "url":             url,
            "ats_site":        h.get("ats_site", ""),
            "keywords":        "",
            "snippet":         "",
            "salary":          h.get("salary", ""),
            "remote":          "",
            "location":        h.get("location", ""),
            "date_posted":     "",
            "seen_before":     True,
            "first_seen_date": fs,
            "first_seen":      fs.isoformat() if hasattr(fs, "isoformat") else str(fs),
            "on_linkedin":     False,
            "on_indeed":       False,
            "on_glassdoor":    False,
            "unsyndicated":    True,
            "relevance_score": 0.0,
            "relevance_label": h.get("match", "🔵 Possible") or "🔵 Possible",
            "relevance_reasons": [],
        }
        all_jobs.append(revived)
        current_urls.add(url)
        # Ensure pinned state is in prev_user_data
        if url not in prev_user_data:
            prev_user_data[url] = {}
        prev_user_data[url]["pinned"] = "TRUE"
        print(f"    📌 Resurrected: {h.get('title','')[:55]}")

    # Handle other dropped jobs from sheet (applied or has user data)
    for url, p in prev_user_data.items():
        if url in current_urls or url in rejected:
            continue
        is_pinned  = normalize_bool(p.get("pinned", ""))
        is_applied = normalize_bool(p.get("applied_check", "")) or bool(p.get("date_applied","").strip())
        has_data   = any(str(p.get(c, "")).strip() for c in USER_COLS
                         if c not in ("pinned", "reject", "applied_check"))
        if is_pinned or is_applied or has_data:
            label = p.get("match", "🔵 Possible") or "🔵 Possible"
            try:
                fs = datetime.date.fromisoformat(p.get("first_seen", "")[:10])
            except (ValueError, TypeError):
                fs = datetime.date.today() - datetime.timedelta(days=8)
            revived = {
                "title":           p.get("title", ""),
                "company":         p.get("company", ""),
                "url":             url,
                "ats_site":        p.get("ats_site", ""),
                "keywords":        "",
                "snippet":         "",
                "salary":          p.get("salary", ""),
                "remote":          p.get("remote", ""),
                "location":        p.get("location", ""),
                "date_posted":     "",
                "seen_before":     True,
                "first_seen_date": fs,
                "first_seen":      p.get("first_seen", ""),
                "on_linkedin":     False,
                "on_indeed":       False,
                "on_glassdoor":    False,
                "unsyndicated":    is_pinned,
                "relevance_score": float(p.get("relevance_score", 0) or 0),
                "relevance_label": label,
                "relevance_reasons": [],
            }
            all_jobs.append(revived)
            current_urls.add(url)
            if not is_pinned and not is_applied:
                prev_user_data[url]["stage"] = "Expired?"

    # Deduplicate and validate
    seen_urls = set()
    deduped   = []
    for job in all_jobs:
        url = job.get("url", "")
        if not url or not url.startswith("http") or url in seen_urls:
            continue
        seen_urls.add(url)
        if not job.get("relevance_label"):
            job["relevance_label"] = "🔵 Possible"
        # Skip jobs with no title at all (true ghost rows)
        if not job.get("title", "").strip():
            continue
        deduped.append(job)

    # Save enriched history with current user state
    pinned_saved = save_history(name, deduped, prev_user_data, new_rejected_urls)
    if pinned_saved:
        print(f"    📌 {pinned_saved} pinned jobs saved in history")

    print(f"    📋 Writing {len(deduped)} jobs to sheet")
    rewrite_sheet(service, sheet_id, name, deduped, prev_user_data)


# =============================================================================
# 🔧 EMAIL BUILDER
# =============================================================================

def build_email_html(profile, gems, open_mkt, returning):
    name        = profile["name"]
    date_str    = datetime.date.today().strftime("%B %d, %Y")
    sheet_id    = SHEET_IDS.get(name, "")
    sheet_url   = (f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
                   if sheet_id and sheet_id.strip() else "")
    total_email = len(gems) + len(open_mkt) + len(returning)
    gems_top    = gems[:ROWS_VISIBLE]
    gems_rest   = gems[ROWS_VISIBLE:]
    picks_top   = open_mkt[:ROWS_VISIBLE]
    picks_rest  = open_mkt[ROWS_VISIBLE:]
    ret_top     = returning[:ROWS_VISIBLE]
    ret_rest    = returning[ROWS_VISIBLE:]

    def rbadge(val):
        c = {"Remote":("#dcfce7","#166534"),"Hybrid":("#fef9c3","#92400e"),
             "In-range":("#eff6ff","#1e40af"),"In-person":("#fee2e2","#991b1b")}
        bg, fg = c.get(val, ("#f3f4f6","#6b7280"))
        return (f'<span style="background:{bg};color:{fg};padding:1px 7px;'
                f'border-radius:10px;font-size:11px;font-weight:600;">{val}</span>')

    def mbadge(label):
        c = {"🟢 Strong":("#dcfce7","#166534"),"🟡 Good":("#fef9c3","#92400e")}
        bg, fg = c.get(label, ("#f3f4f6","#6b7280"))
        return (f'<span style="background:{bg};color:{fg};padding:1px 8px;'
                f'border-radius:10px;font-size:11px;font-weight:700;">{label}</span>')

    def synd(job):
        flags = [s for s, k in [("LinkedIn","on_linkedin"),("Indeed","on_indeed"),
                                  ("Glassdoor","on_glassdoor")] if job.get(k)]
        return (f'<span style="color:#16a34a;font-size:11px;">&#10003; Not on major boards</span>'
                if not flags else
                f'<span style="color:#9a3412;font-size:11px;">Also on: {", ".join(flags)}</span>')

    def card(job):
        sal        = job.get("salary") or "n/a"
        loc        = job.get("location") or "unknown"
        date_p     = job.get("date_posted", "")
        date_html  = (f'<span style="font-size:11px;color:#9ca3af;margin-left:8px;">'
                      f'Posted: {date_p}</span>') if date_p else ""
        return f"""
        <div style="border:1px solid #e5e7eb;border-radius:8px;padding:14px 16px;
                    margin-bottom:10px;background:#fff;">
          <div style="margin-bottom:6px;">
            {mbadge(job['relevance_label'])}
            <span style="background:#eff6ff;color:#1e40af;padding:1px 8px;
                         border-radius:10px;font-size:12px;font-weight:600;
                         margin-right:4px;">💰 {sal}</span>
            {rbadge(job['remote'])}
            <span style="font-size:12px;color:#6b7280;margin-left:6px;">📍 {loc}</span>
            {date_html}
          </div>
          <div style="margin-bottom:5px;">
            <a href="{job['url']}"
               style="font-size:15px;font-weight:600;color:#1e3a5f;
                      text-decoration:underline;">{job['title']}</a>
          </div>
          <div style="font-size:13px;color:#374151;margin-bottom:6px;">
            🏢 {job['company']}
          </div>
          <div style="font-size:13px;color:#4b5563;line-height:1.5;
                      margin-bottom:6px;">{job['snippet']}</div>
          {synd(job)}
        </div>"""

    def grid_row(job, hdr=False):
        if hdr:
            cells = "".join(
                f"<th style='padding:8px 10px;font-size:12px;font-weight:700;"
                f"text-align:left;background:#1e3a5f;color:#fff;'>{h}</th>"
                for h in ["Company","Title","Match","Salary","Remote","Location","Link"]
            )
            return f"<tr>{cells}</tr>"
        t   = job['title'].split('|')[0].split('-')[0].strip()[:45]
        sal = job.get('salary') or '—'
        loc = job.get('location') or '—'
        return (
            f"<tr style='border-bottom:1px solid #f3f4f6;'>"
            f"<td style='padding:7px 10px;font-size:12px;'>{job['company']}</td>"
            f"<td style='padding:7px 10px;font-size:12px;'>{t}</td>"
            f"<td style='padding:7px 10px;font-size:12px;'>{job['relevance_label']}</td>"
            f"<td style='padding:7px 10px;font-size:12px;color:#1e40af;'>{sal}</td>"
            f"<td style='padding:7px 10px;font-size:12px;'>{job['remote']}</td>"
            f"<td style='padding:7px 10px;font-size:12px;color:#6b7280;'>{loc}</td>"
            f"<td style='padding:7px 10px;font-size:12px;'>"
            f"<a href='{job['url']}' style='color:#2563eb;font-weight:600;"
            f"text-decoration:underline;'>Apply →</a></td></tr>"
        )

    def grid(jobs):
        if not jobs:
            return "<p style='color:#9ca3af;font-size:13px;font-style:italic;'>None this run.</p>"
        hdr  = f"<thead>{grid_row(None, hdr=True)}</thead>"
        body = "<tbody>" + "\n".join(grid_row(j) for j in jobs) + "</tbody>"
        return (f'<table style="width:100%;border-collapse:collapse;'
                f'border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;'
                f'background:#fff;">{hdr}{body}</table>')

    def sec_hdr(sec_num):
        label, defn = SECTION_LABELS[sec_num]
        bg = f"#{SECTION_COLORS[sec_num]['bg']}"
        return (f'<div style="background:{bg};color:#fff;border-radius:8px;'
                f'padding:12px 16px;margin:24px 0 10px;">'
                f'<div style="font-size:15px;font-weight:700;">{label}</div>'
                f'<div style="font-size:12px;opacity:0.85;margin-top:3px;">{defn}</div>'
                f'</div>')

    def more_cards(jobs, color, label):
        if not jobs: return ""
        inner = "\n".join(card(j) for j in jobs)
        return (f'<details style="margin-top:8px;">'
                f'<summary style="cursor:pointer;font-size:13px;font-weight:600;'
                f'color:{color};padding:8px 0;list-style:none;">'
                f'&#9654; Show {len(jobs)} more {label}</summary>'
                f'<div style="margin-top:10px;">{inner}</div></details>')

    def more_grid(jobs, label):
        if not jobs: return ""
        return (f'<details style="margin-top:8px;">'
                f'<summary style="cursor:pointer;font-size:13px;font-weight:600;'
                f'color:#92400e;padding:8px 0;list-style:none;">'
                f'&#9654; Show {len(jobs)} more {label}</summary>'
                f'<div style="margin-top:10px;">{grid(jobs)}</div></details>')

    sheet_btn = ""
    if sheet_url:
        sheet_btn = (f'<div style="background:#f0f9ff;border:1px solid #bae6fd;'
                     f'border-radius:8px;padding:12px 16px;margin:12px 0;">'
                     f'<div style="font-size:13px;color:#0369a1;margin-bottom:8px;">'
                     f'<strong>📊 Your Job Tracker</strong> — pin, reject, and track '
                     f'applications in Google Sheets.</div>'
                     f'<a href="{sheet_url}" style="display:inline-block;'
                     f'background:#1e3a5f;color:#fff;padding:8px 16px;border-radius:6px;'
                     f'font-size:13px;font-weight:600;text-decoration:none;">'
                     f'Open Tracker →</a></div>')

    test_banner = ""
    if TEST_MODE:
        test_banner = ('<div style="background:#fef3c7;border:2px solid #f59e0b;'
                       'border-radius:8px;padding:10px 16px;margin-bottom:14px;'
                       'font-size:13px;color:#92400e;font-weight:600;">'
                       '🧪 TEST MODE — routed to sender for review.</div>')

    gems_html  = "\n".join(card(j) for j in gems_top) or "<p style='color:#9ca3af;font-size:13px;font-style:italic;'>None this run.</p>"
    picks_html = "\n".join(card(j) for j in picks_top) or "<p style='color:#9ca3af;font-size:13px;font-style:italic;'>None this run.</p>"

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
        background:#f3f4f6;margin:0;padding:20px;color:#111827;}}
  .wrap{{max-width:800px;margin:0 auto;}}
  .hdr{{background:#1e3a5f;color:#fff;border-radius:10px 10px 0 0;padding:22px 26px;}}
  .hdr h1{{margin:0 0 3px;font-size:21px;}}
  .hdr p{{margin:0;font-size:13px;opacity:.75;}}
  .stats{{display:flex;background:#fff;border:1px solid #e5e7eb;border-top:none;}}
  .stat{{flex:1;text-align:center;padding:12px 6px;border-right:1px solid #f3f4f6;}}
  .stat:last-child{{border-right:none;}}
  .num{{font-size:24px;font-weight:700;}}
  .lbl{{font-size:11px;color:#6b7280;margin-top:1px;}}
  .warning{{background:#fef9c3;border:1px solid #fde68a;border-radius:8px;
            padding:10px 14px;margin:12px 0;font-size:13px;color:#92400e;}}
  details summary{{list-style:none;}}
  details summary::-webkit-details-marker{{display:none;}}
  .footer{{text-align:center;color:#9ca3af;font-size:11px;padding:16px 0 0;}}
</style></head>
<body><div class="wrap">
  {test_banner}
  <div class="hdr">
    <h1>Job Search Results — {name}</h1>
    <p>{date_str} &nbsp;&middot;&nbsp; {DAYS_BACK}-day window &nbsp;&middot;&nbsp;
       {len(ATS_SITES)} ATS platforms &nbsp;&middot;&nbsp; {total_email} in email</p>
  </div>
  <div class="stats">
    <div class="stat"><div class="num" style="color:#16a34a;">{len(gems)}</div>
      <div class="lbl">🟢 Hidden Gems</div></div>
    <div class="stat"><div class="num" style="color:#2563eb;">{len(open_mkt)}</div>
      <div class="lbl">🔵 Open Market</div></div>
    <div class="stat"><div class="num" style="color:#d97706;">{len(returning)}</div>
      <div class="lbl">🟡 Still Circulating</div></div>
  </div>
  <div class="warning">⚠️ <strong>Verify each posting is still accepting applications
    before tailoring your resume or cover letter.</strong></div>
  {sheet_btn}
  {sec_hdr(1)}
  {gems_html}
  {more_cards(gems_rest, "#166534", "Hidden Gems")}
  {sec_hdr(2)}
  {picks_html}
  {more_cards(picks_rest, "#1e40af", "Open Market Picks")}
  {sec_hdr(3)}
  {grid(ret_top)}
  {more_grid(ret_rest, "Still Circulating")}
  <div class="footer">ATS Job Search Script &middot; serper.dev &middot; {date_str}</div>
</div></body></html>"""


# =============================================================================
# 🔧 EMAIL SENDER
# =============================================================================

def send_email(to_email, to_name, html_body):
    date_str  = datetime.date.today().strftime("%b %d")
    actual_to = BCC_EMAIL if TEST_MODE else to_email
    subject   = f"{'[TEST] ' if TEST_MODE else ''}Job Search — {to_name} · {date_str}"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = actual_to
    if not TEST_MODE and to_email != SENDER_EMAIL:
        msg["Bcc"] = BCC_EMAIL
    msg.attach(MIMEText(html_body, "html"))
    recipients = ([actual_to] if TEST_MODE else
                  ([to_email, BCC_EMAIL] if to_email != SENDER_EMAIL else [to_email]))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
            s.sendmail(SENDER_EMAIL, recipients, msg.as_string())
        mode = "→ TEST" if TEST_MODE else f"→ {to_email}"
        print(f"    📧 {to_name} {mode}")
    except Exception as e:
        print(f"    ❌ Email failed for {to_name}: {e}")


# =============================================================================
# 🔧 MAIN
# =============================================================================

def main():
    print(f"\n🔍 ATS Job Search v4.3.6")
    print(f"   {datetime.date.today()} | {DAYS_BACK}d window | "
          f"{len(ATS_SITES)} ATS | TEST={TEST_MODE} | SINGLE={TEST_PROFILE_ONLY}\n")

    if not SERPER_API_KEY:
        print("❌ SERPER_API_KEY missing from .env"); return
    if not SENDER_APP_PASSWORD:
        print("❌ SENDER_APP_PASSWORD missing from .env"); return
    if not SENDER_EMAIL:
        print("❌ SENDER_EMAIL missing from .env"); return

    profiles_to_run = PROFILES[:1] if TEST_PROFILE_ONLY else PROFILES

    for profile in profiles_to_run:
        name = profile["name"]

        # Read sheet first to get rejected checkboxes from prior run
        sheet_id = SHEET_IDS.get(name, "")
        prev_user_data   = {}
        new_rejected_urls = []

        if SHEETS_ENABLED and sheet_id and sheet_id.strip():
            service = get_sheets_service()
            if service:
                prev_user_data = read_existing_rows(service, sheet_id)
                # Collect URLs newly marked as Reject
                for url, p in prev_user_data.items():
                    if normalize_bool(p.get("reject", "")):
                        new_rejected_urls.append(url)

        results = search_for_profile(profile)

        # Bucket for email
        today = datetime.date.today()
        def age_days(job):
            return (today - job.get("first_seen_date", today)).days

        sg_new     = sorted([j for j in results
                             if j["relevance_label"] in ("🟢 Strong","🟡 Good")
                             and age_days(j) <= GEM_AGE_DAYS],
                            key=lambda x: x["relevance_score"], reverse=True)
        returning  = sorted([j for j in results
                             if j["relevance_label"] in ("🟢 Strong","🟡 Good")
                             and age_days(j) > GEM_AGE_DAYS],
                            key=lambda x: x["relevance_score"], reverse=True)
        possible   = [j for j in results if j["relevance_label"] == "🔵 Possible"]

        gems     = [j for j in sg_new if j["unsyndicated"]]
        open_mkt = [j for j in sg_new if not j["unsyndicated"]]

        if SHEETS_ENABLED:
            update_sheet(name, results, prev_user_data, new_rejected_urls)

        html = build_email_html(profile, gems, open_mkt, returning)
        send_email(profile["email"], name, html)
        print("   Cooling down...\n")
        time.sleep(5)

    print("\n✨ Done.\n")
    if TEST_MODE:
        print("   ⚠️  Set TEST_MODE=False and TEST_PROFILE_ONLY=False for live send.\n")


if __name__ == "__main__":
    main()
