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
- Email: ATS site label removed from cards, job titles underlined as links
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
from googleapiclient.errors import HttpError

# Load credentials from .env
load_dotenv(Path(__file__).parent / ".env")

# =============================================================================
# ✏️  RUN MODE
# =============================================================================

TEST_MODE         = False
TEST_PROFILE_ONLY = False

# Set to True temporarily to see why jobs are being filtered out
DEBUG_FILTERS     = False

# =============================================================================
# ✏️  CREDENTIALS — from .env
# =============================================================================

SENDER_EMAIL        = os.getenv("SENDER_EMAIL", "")
SENDER_APP_PASSWORD = os.getenv("SENDER_APP_PASSWORD", "")
BCC_EMAIL           = os.getenv("BCC_EMAIL", "")
SERPER_API_KEY      = os.getenv("SERPER_API_KEY", "")
_raw_creds = os.getenv("GOOGLE_CREDENTIALS_FILE", "google_credentials.json")
if not os.path.isabs(_raw_creds):
    SERVICE_ACCOUNT_FILE = str(Path(__file__).parent / _raw_creds)
else:
    SERVICE_ACCOUNT_FILE = _raw_creds

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
GEM_AGE_DAYS      = 7
ROWS_VISIBLE      = 20
ATS_RESULTS_CAP   = 5
SHEETS_ENABLED    = True
FETCH_CAP         = 40

# =============================================================================
# ✏️  EXCLUSION FILTERS
# =============================================================================

EXCLUDE_TITLE_KEYWORDS = [
    "nursing", "nurse", "software engineer", "developer", "recruiter",
    "sales management", "security engineer", "event coordinator",
    "government affairs", "revenue integrity", "payment accuracy",
]

EXCLUDE_SNIPPET_KEYWORDS = [
    "entry level", "internship", "intern ", " intern,", "new grad",
    "recent grad", "data scientist",
]

# =============================================================================
# ✏️  PROFILES
# =============================================================================

PROFILES = [
    {
        "name": "Andy",
        "email": "andrew@varyu.net",
        "salary_minimum": 145000,
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
            ["product", "director", "healthcare"],
        ],
        "industry_filter": [
            "healthcare", "community health", "health system",
            "federally qualified", "nonprofit", "public health",
            "life sciences", "medical", "science", "insurance", "clinical"
        ],
    },
    {
        "name": "Vanessa",
        "email": "vdegier@gmail.com",
        "salary_minimum": 180000,
        "priority_titles": ["chief", "vp", "vice president", "svp", "avp", "executive director"],
        "location_preference": "remote",
        "ok_cities": ["santa rosa", "san francisco", "sonoma", "napa", "oakland"],
        "required_title_keywords": ["communications", "communication", "community", "comms", "voice", "reputation"],
        "keyword_combos": [
            ["chief communications officer"],
            ["VP", "communications", "healthcare"],
            ["senior vice president", "communications"],
            ["executive director", "communications", "healthcare"],
            ["AVP", "communications"],
            ["chief marketing", "communications", "healthcare"],
        ],
        "industry_filter": [
            "healthcare", "health system", "hospital", "life sciences",
            "nonprofit", "medical", "science", "insurance", "clinical"
        ],
    },
    {
        "name": "Maryjane",
        "email": "maryjanebeth@gmail.com",
        "salary_minimum": 160000,
        "priority_titles": ["director", "senior director", "vp", "vice president", "executive director"],
        "location_preference": "remote",
        "ok_cities": ["seattle", "redmond", "bellevue", "renton", "bothell", "kirkland"],
        "required_title_keywords": ["communications", "marketing", "brand", "reputation", "social", "campaign", "community"],
        "keyword_combos": [
            ["senior marketing director", "healthcare"],
            ["director", "marketing", "healthcare"],
            ["executive director", "marketing", "communications"],
            ["VP", "marketing", "healthcare"],
            ["director", "consumer marketing", "health"],
            ["director", "brand", "healthcare"],
        ],
        "industry_filter": [
            "healthcare", "health system", "hospital", "health plan",
            "nonprofit", "medical", "science"
        ],
    },
    {
        "name": "David",
        "email": "dvaryu@gmail.com",
        "salary_minimum": 120000,
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
    "rippling.com", "ultipro.com", "eightfold.ai",
]

EMPLOYER_SITES = [
    "careers.microsoft.com",
    "amazon.jobs",
    "jobs.apple.com",
    "careers.google.com",
    "providence.jobs",
    "jobs.boeing.com",
    "jobs.costco.com",
    "careers.t-mobile.com",
]

ALL_SOURCES = ATS_SITES + EMPLOYER_SITES
SYNDICATION_SITES = ["linkedin.com", "indeed.com", "glassdoor.com"]

STAGE_OPTIONS = [
    "New", "Reviewing", "Applied", "Phone Screen",
    "Interview", "Final Round", "Offer", "Rejected", "Pass"
]

REMOTE_OPTIONS = [
    "🏠 Remote", "🏢 In-person", "🏠🏢 Hybrid", "🏠 In-range"
]

# =============================================================================
# 🔧 COLUMN DEFINITIONS
# =============================================================================

COL = {
    "pinned":          0,
    "reject":          1,
    "title":           2,
    "company":         3,
    "match":           4,
    "salary":          5,
    "remote":          6,
    "location":        7,
    "url":             8,
    "hidden":          9,
    "applied_check":  10,
    "date_posted":    11,
    "first_seen":     12,
    "date_applied":   13,
    "stage":          14,
    "notes":          15,
    "date_followed":  16,
    "contact":        17,
    "ats_site":       18,
    "syndication":    19,
    "resume_version": 20,
    "cover_letter":   21,
    "section":        22,
}
NUM_COLS  = 23
USER_COLS = ["pinned", "reject", "applied_check", "date_applied", "stage",
             "notes", "date_followed", "contact", "resume_version", "cover_letter"]

SHEET_HEADERS = [
    "Pin", "Reject", "Title", "Company", "Match", "Salary",
    "Remote", "Location", "URL", "Hidden?", "Applied!", "Date Posted",
    "First Seen", "Date Applied", "Stage", "Notes", "Date Followed Up", "Contact",
    "ATS Site", "Syndication", "Resume Version", "Cover Letter Notes", "Section",
]

JUST_POSTED_DAYS = 2

SECTION_LABELS = {
    0: ("📌 Pinned",            "Jobs you've starred — stay here until unpinned"),
    1: ("💎 Hidden Gems",       "New · Not on major boards · Fresh within 7 days"),
    6: ("⚡ Just Posted",       f"Posted within {JUST_POSTED_DAYS} days · Not already in Hidden Gems"),
    2: ("🌐 Open Market Picks", "New · On major boards · Ranked by relevance · Fresh within 7 days"),
    3: ("♻️ Still Circulating", "Older than 7 days or seen in a previous run"),
    4: ("🤷 Other Matches",     "Possible matches below Strong/Good threshold · Sheet only"),
    5: ("✅ Applied & Waiting", "You've marked as applied"),
}

SECTION_COLORS = {
    0: {"bg": "1e3a5f", "fg": "ffffff"},
    1: {"bg": "166534", "fg": "ffffff"},
    6: {"bg": "b45309", "fg": "ffffff"},
    2: {"bg": "1e40af", "fg": "ffffff"},
    3: {"bg": "92400e", "fg": "ffffff"},
    4: {"bg": "4b5563", "fg": "ffffff"},
    5: {"bg": "5b21b6", "fg": "ffffff"},
}

SECTION_ORDER = [0, 1, 6, 2, 3, 4, 5]

# =============================================================================
# 🔧 HISTORY & REJECT TRACKING
# =============================================================================

HISTORY_DIR = Path(__file__).parent / "history"
HISTORY_DIR.mkdir(exist_ok=True)


def history_path(name):
    return HISTORY_DIR / f"history_{name.lower()}.csv"


HISTORY_FIELDS = [
    "url", "first_seen", "title", "company", "ats_site",
    "pinned", "rejected", "applied", "stage", "salary", "location", "match"
]


def load_history(name):
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
    return {url for url, h in history.items() if h.get("rejected")}


def save_history(name, jobs, prev_user_data, new_rejected_urls=None):
    path     = history_path(name)
    existing = load_history(name)
    today    = datetime.date.today()
    cutoff   = today - datetime.timedelta(days=HISTORY_WEEKS * 7)
    reject_cutoff = today - datetime.timedelta(days=REJECT_DAYS)

    if new_rejected_urls:
        for url in new_rejected_urls:
            if url in existing:
                existing[url]["rejected"] = True
            else:
                existing[url] = {
                    "first_seen_date": today, "first_seen": today.isoformat(),
                    "title": "", "company": "", "ats_site": "",
                    "pinned": False, "rejected": True, "applied": False,
                    "stage": "", "salary": "", "location": "", "match": "",
                }

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
            if stage:                      entry["stage"]    = stage
            if job.get("salary"):          entry["salary"]   = job["salary"]
            if job.get("location"):        entry["location"] = job["location"]
            if job.get("relevance_label"): entry["match"]    = job["relevance_label"]
            if job.get("title"):           entry["title"]    = job["title"]
            if job.get("company"):         entry["company"]  = job["company"]
            if job.get("ats_site"):        entry["ats_site"] = job["ats_site"]
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
    return get_rejected_urls(load_history(name))


def save_rejected(name, new_urls):
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

WRONG_CITY_SIGNALS = [
    "new york", "chicago", "boston", "austin", "denver", "atlanta",
    "dallas", "houston", "miami", "philadelphia", "phoenix", "portland",
    "san diego", "minneapolis", "detroit", "nashville", "charlotte",
    "pittsburgh", "cleveland", "cincinnati",
]


def check_exclusion_filter(job, profile=None):
    title   = job.get("title", "").lower()
    snippet = job.get("snippet", "").lower()
    for kw in EXCLUDE_TITLE_KEYWORDS:
        if kw.lower() in title:
            return False, f"title contains '{kw}'"
    for kw in EXCLUDE_SNIPPET_KEYWORDS:
        if kw.lower() in snippet:
            return False, f"snippet contains '{kw}'"
    if profile:
        required = profile.get("required_title_keywords", [])
        if required and not any(kw.lower() in title for kw in required):
            return False, f"title missing required keyword ({'/'.join(required)})"
    return True, ""


def check_location_filter(job, profile):
    ok_cities = profile.get("ok_cities", [])
    if not ok_cities:
        return True, ""
    text = (job.get("title", "") + " " +
            job.get("snippet", "") + " " +
            job.get("location", "")).lower()
    remote_signals = ["remote", "work from home", "wfh", "fully remote",
                      "100% remote", "anywhere", "distributed", "hybrid"]
    if any(sig in text for sig in remote_signals):
        return True, ""
    if any(city in text for city in ok_cities):
        return True, ""
    for wrong_city in WRONG_CITY_SIGNALS:
        if wrong_city in text:
            return False, f"explicit wrong city: '{wrong_city}'"
    return True, ""


def passes_exclusion_filter(job, profile=None):
    passed, _ = check_exclusion_filter(job, profile)
    return passed


def passes_location_filter(job, profile):
    passed, _ = check_location_filter(job, profile)
    return passed


def write_debug_filtered(name, dropped_jobs):
    if not DEBUG_FILTERS or not dropped_jobs:
        return
    path = HISTORY_DIR / f"debug_filtered_{name.lower()}.csv"
    fields = ["title", "company", "url", "ats_site", "location", "snippet_preview", "filter_reason"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for job, reason in dropped_jobs:
            writer.writerow({
                "title":           job.get("title", "")[:80],
                "company":         job.get("company", ""),
                "url":             job.get("url", ""),
                "ats_site":        job.get("ats_site", ""),
                "location":        job.get("location", ""),
                "snippet_preview": job.get("snippet", "")[:120],
                "filter_reason":   reason,
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
    SEP = r'\s*(?:[-\u2013\u2014]|to)\s*'
    T_DOLLAR  = r'\$\d{1,3}(?:,\d{3})+'
    T_NODOT   = r'\$\d{4,7}'
    T_K       = r'\$\d{2,3}[kK]'
    T_COMMA   = r'\d{1,3}(?:,\d{3})+'
    TOKEN = f'(?:{T_DOLLAR}|{T_NODOT}|{T_K}|{T_COMMA})'
    RANGE = TOKEN + SEP + TOKEN
    m = re.search(RANGE, text, re.IGNORECASE)
    if m: return m.group(0).strip()
    m = re.search(r'\$\d{1,3}(?:,\d{3})+(?:\s*(?:/yr|/year|annually))?', text, re.IGNORECASE)
    if m: return m.group(0).strip()
    m = re.search(r'\$\d{5,7}(?:\s*(?:/yr|/year|annually))?', text, re.IGNORECASE)
    if m: return m.group(0).strip()
    m = re.search(r'\$\d{2,3}[kK](?:\+)?', text)
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
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                                  "Chrome/120.0.0.0 Safari/537.36"}
        r    = requests.get(url, headers=headers, timeout=8)
        html = r.text
        salary = location = remote = date_posted = ""

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
                    if "JobPosting" not in (job_type if isinstance(job_type, str) else " ".join(job_type)):
                        continue
                    if not date_posted:
                        dp = item.get("datePosted", "")
                        if dp:
                            try:
                                d = datetime.date.fromisoformat(dp[:10])
                                date_posted = d.strftime("%b %d, %Y")
                            except ValueError:
                                date_posted = dp[:10]
                    if not location:
                        jl   = item.get("jobLocation", {})
                        if isinstance(jl, list): jl = jl[0] if jl else {}
                        addr = jl.get("address", {}) if isinstance(jl, dict) else {}
                        if isinstance(addr, dict):
                            city  = addr.get("addressLocality", "")
                            state = addr.get("addressRegion", "")
                            if city: location = f"{city}, {state}".strip(", ")
                    if not remote:
                        wl = str(item.get("jobLocationType", "")).lower()
                        if "remote" in wl or "telecommute" in wl:
                            remote = "Remote"
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
                                        salary = f"${mn}\u2013${mx}/hr"
                                    else:
                                        try:
                                            salary = f"${int(float(mn)):,}\u2013${int(float(mx)):,}"
                                        except (ValueError, TypeError):
                                            salary = f"${mn}\u2013${mx}"
                                elif mn:
                                    try: salary = f"${int(float(mn)):,}+"
                                    except: salary = f"${mn}+"
                    if location and salary and date_posted: break
            except (json.JSONDecodeError, Exception):
                continue

        head_html  = html[:5000]
        tail_html  = html[-6000:]

        def clean_html(raw):
            c = re.sub(r'<[^>]+>', ' ', raw)
            return re.sub(r'\s+', ' ', c)

        head_clean = clean_html(head_html)
        tail_clean = clean_html(tail_html)
        full_clean = head_clean + " " + tail_clean

        if not location: location = extract_location(head_clean) or extract_location(tail_clean)
        if not remote:   remote   = extract_remote(full_clean)

        if not salary:
            prox_match = re.search(
                r'(?:compensation|salary range|base pay|pay range|total comp|pay:)(.{0,400})',
                tail_clean, re.IGNORECASE | re.DOTALL
            )
            if prox_match:
                salary = extract_salary(prox_match.group(1))
            if not salary:
                salary = extract_salary(tail_clean)
            if not salary:
                salary = extract_salary(head_clean)

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
# 🔧 RELEVANCE SCORING
# =============================================================================

def score_job(job, profile):
    title   = job["title"].lower()
    score   = 0.0
    reasons = []
    hits        = [t for t in profile["priority_titles"] if t in title]
    title_score = min(24.0, len(hits) * 9.0)
    score      += title_score
    if hits: reasons.append(f"title: {', '.join(hits[:2])}")
    sen_terms = ["director","vp","vice president","chief","svp","avp",
                 "senior","lead","principal","head of","executive"]
    sen_hits  = [t for t in sen_terms if t in title]
    score    += min(2.1, len(sen_hits) * 2.1)
    if sen_hits: reasons.append(f"level: {sen_hits[0]}")
    remote    = job.get("remote", "In-person").lower()
    loc       = job.get("location", "").lower()
    ok_cities = [c.lower() for c in profile.get("ok_cities", [])]
    ls        = 0.0
    if not profile.get("ok_cities"):
        ls = 2.0
    elif "remote" in remote:
        ls = 3.9; reasons.append("remote \u2713")
    elif "hybrid" in remote or "in-range" in remote:
        ls = 2.5; reasons.append(f"{remote} \u2713")
    elif any(city in loc for city in ok_cities):
        ls = 3.9; reasons.append("city \u2713")
    score += ls
    score  = round(score, 1)
    label = "\U0001f7e2 Strong" if score >= 20 else "\U0001f7e1 Good" if score >= 10 else "\U0001f535 Possible"
    job["relevance_score"]   = score
    job["relevance_label"]   = label
    job["relevance_reasons"] = reasons
    return score


# =============================================================================
# 🔧 SECTION LOGIC
# =============================================================================

def is_just_posted(job):
    dp = job.get("date_posted", "")
    if not dp:
        return False
    for fmt in ("%b %d, %Y", "%Y-%m-%d", "%B %d, %Y"):
        try:
            d = datetime.datetime.strptime(dp.strip(), fmt).date()
            return (datetime.date.today() - d).days <= JUST_POSTED_DAYS
        except ValueError:
            continue
    return False


def get_job_section(job, prev_user_data):
    url        = job.get("url", "")
    prev       = prev_user_data.get(url, {})
    today      = datetime.date.today()
    first_seen = job.get("first_seen_date", today)
    age_days   = (today - first_seen).days
    if normalize_bool(prev.get("pinned", "")):
        return 0
    applied = normalize_bool(prev.get("applied_check", ""))
    dated   = bool(prev.get("date_applied", "").strip())
    if applied or dated:
        return 5
    label = job.get("relevance_label", "\U0001f535 Possible")
    if label == "\U0001f535 Possible":
        return 4
    if age_days <= GEM_AGE_DAYS:
        if job.get("unsyndicated"):
            return 1
        if is_just_posted(job):
            return 6
        return 2
    return 3


# =============================================================================
# 🔧 MAIN SEARCH RUNNER
# =============================================================================

def search_for_profile(profile):
    name      = profile["name"]
    sal_min   = profile.get("salary_minimum", 0)
    history   = load_history(name)
    rejected  = load_rejected(name)
    pinned_count = sum(1 for e in history.values() if e.get("pinned"))
    print(f"\n  \U0001f464 {name} | min ${sal_min:,} | {len(history)} history | "
          f"{pinned_count} pinned | {len(rejected)} filtered out")

    results, seen = [], set()

    for site in ALL_SOURCES:
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

    raw_count = len(results)
    kept, dropped = [], []

    for job in results:
        excl_pass, excl_reason = check_exclusion_filter(job, profile)
        if not excl_pass:
            dropped.append((job, excl_reason)); continue
        loc_pass, loc_reason = check_location_filter(job, profile)
        if not loc_pass:
            dropped.append((job, loc_reason)); continue
        kept.append(job)

    results = kept
    print(f"    {raw_count} found \u2192 {len(results)} after filters ({len(dropped)} dropped)")

    if DEBUG_FILTERS:
        write_debug_filtered(name, dropped)

    for job in results:
        score_job(job, profile)

    strong_good = [j for j in results
                   if j["relevance_label"] in ("\U0001f7e2 Strong", "\U0001f7e1 Good")
                   and not j["seen_before"]]

    if len(strong_good) > FETCH_CAP:
        print(f"    \u26a0\ufe0f  {len(strong_good)} Strong/Good found \u2014 capping fetch at {FETCH_CAP}.")
        strong_good.sort(key=lambda x: x["relevance_score"], reverse=True)
        for job in strong_good[FETCH_CAP:]:
            job["relevance_label"] = "\U0001f535 Possible"
            job["relevance_score"] = min(job["relevance_score"], 9.9)
        strong_good = strong_good[:FETCH_CAP]

    print(f"    {len(strong_good)} new Strong/Good to cross-ref+fetch")

    for i, job in enumerate(strong_good):
        print(f"    [{i+1}/{len(strong_good)}] {job['title'][:55]}...")
        synd = check_syndication(job["title"], job["company"])
        job["on_linkedin"]  = synd.get("linkedin.com", False)
        job["on_indeed"]    = synd.get("indeed.com", False)
        job["on_glassdoor"] = synd.get("glassdoor.com", False)
        job["unsyndicated"] = not any(synd.values())

        pg_sal, pg_loc, pg_rem, pg_date = fetch_job_page(job["url"])
        cur_sal = job["salary"] if job["salary"] not in ("", "n/a") else ""
        cur_loc = job["location"] if job["location"] not in ("", "unknown") else ""
        if pg_sal  and not cur_sal:                                    job["salary"]      = pg_sal
        if pg_loc  and not cur_loc:                                    job["location"]    = pg_loc
        if pg_rem  and job["remote"] in ("In-person", "\U0001f3e2 In-person", ""):
                                                                       job["remote"]      = pg_rem
        if pg_date and not job["date_posted"]:                         job["date_posted"] = pg_date
        if pg_sal or pg_loc or pg_rem or pg_date:
            print(f"      \U0001f4c4 Fetched: sal={pg_sal or '-'} loc={pg_loc or '-'} "
                  f"rem={pg_rem or '-'} date={pg_date or '-'}")

        sal_val = extract_salary_value(job["salary"])
        if sal_val is not None and sal_val < sal_min:
            print(f"      \u2193 Demoted (salary {job['salary']} < ${sal_min:,})")
            job["relevance_label"] = "\U0001f535 Possible"
            job["relevance_score"] = min(job["relevance_score"], 9.9)

        time.sleep(0.5)

    for job in results:
        if job["seen_before"]:
            job["unsyndicated"] = True

    return results


# =============================================================================
# 🔧 GOOGLE SHEETS
# =============================================================================

def normalize_bool(val):
    if isinstance(val, bool): return val
    if isinstance(val, str):  return val.upper() in ("TRUE", "1", "YES", "\u2713", "X")
    return False


def get_sheets_service():
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print(f"    \u26a0\ufe0f  Credentials not found: {SERVICE_ACCOUNT_FILE}")
        return None
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        return build("sheets", "v4", credentials=creds)
    except Exception as e:
        print(f"    \u26a0\ufe0f  Sheets auth: {e}")
        return None


def read_existing_rows(service, sheet_id):
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=sheet_id, range="A:W"
        ).execute()
        rows = result.get("values", [])
    except Exception as e:
        print(f"    \u26a0\ufe0f  Read error: {e}")
        return {}
    if len(rows) < 2:
        return {}
    url_idx  = COL["url"]
    existing = {}
    for row in rows[1:]:
        while len(row) < NUM_COLS:
            row.append("")
        url = row[url_idx]
        if not url or not url.startswith("http"):
            continue
        existing[url] = {col_name: row[idx] for col_name, idx in COL.items()}
    return existing


def remote_with_icon(val):
    mapping = {
        "Remote":     "\U0001f3e0 Remote",
        "In-person":  "\U0001f3e2 In-person",
        "Hybrid":     "\U0001f3e0\U0001f3e2 Hybrid",
        "In-range":   "\U0001f3e0 In-range",
        "In-Person":  "\U0001f3e2 In-person",
    }
    return mapping.get(val, val or "\U0001f3e2 In-person")


def job_to_row(job, section_num, prev_user_data, today):
    row  = [""] * NUM_COLS
    url  = job.get("url", "")
    prev = prev_user_data.get(url, {})

    row[COL["title"]]       = job.get("title", "")
    row[COL["company"]]     = job.get("company", "")
    row[COL["match"]]       = job.get("relevance_label", "")
    row[COL["url"]]         = url
    row[COL["date_posted"]] = job.get("date_posted", "")
    row[COL["section"]]     = str(section_num)
    row[COL["ats_site"]]    = job.get("ats_site", "")
    row[COL["first_seen"]]  = job.get("first_seen", today)

    salary   = job.get("salary", "") or prev.get("salary", "") or "n/a"
    location = job.get("location", "") or prev.get("location", "") or "unknown"
    remote   = job.get("remote", "") or prev.get("remote", "") or "In-person"

    row[COL["salary"]]   = salary
    row[COL["location"]] = location
    row[COL["remote"]]   = remote_with_icon(remote)

    flags = []
    if job.get("on_linkedin"):  flags.append("LinkedIn")
    if job.get("on_indeed"):    flags.append("Indeed")
    if job.get("on_glassdoor"): flags.append("Glassdoor")
    row[COL["syndication"]] = ", ".join(flags) if flags else "Not syndicated"
    row[COL["hidden"]]      = "Y" if not flags else "N"

    for col_name in USER_COLS:
        val = prev.get(col_name, "")
        if col_name in ("pinned", "reject", "applied_check"):
            row[COL[col_name]] = normalize_bool(val)
        else:
            row[COL[col_name]] = val

    if normalize_bool(prev.get("applied_check", "")) and not prev.get("date_applied", "").strip():
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        row[COL["date_applied"]] = yesterday

    return row


def rewrite_sheet(service, sheet_id, name, all_jobs, prev_user_data):
    today    = datetime.date.today().isoformat()
    sections = {i: [] for i in SECTION_ORDER}

    for job in all_jobs:
        sec = get_job_section(job, prev_user_data)
        if sec not in sections:
            sections[sec] = []
        sections[sec].append(job)

    for sec in sections:
        sections[sec].sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

    all_rows      = [SHEET_HEADERS]
    row_meta      = []
    blank_row     = [""] * NUM_COLS
    first_section = True

    for sec in SECTION_ORDER:
        jobs = sections.get(sec, [])
        if not jobs:
            continue
        if not first_section:
            for _ in range(2):
                all_rows.append(blank_row[:])
                row_meta.append({"section": sec, "is_header": False,
                                 "is_overflow": False, "is_spacer": True})
        first_section = False
        label, _ = SECTION_LABELS[sec]
        all_rows.append([label] + [""] * (NUM_COLS - 1))
        row_meta.append({"section": sec, "is_header": True,
                         "is_overflow": False, "is_spacer": False})
        for i, job in enumerate(jobs):
            if not job.get("title", "").strip() or not job.get("url", "").startswith("http"):
                continue
            row = job_to_row(job, sec, prev_user_data, today)
            row = ["TRUE" if v is True else "FALSE" if v is False else v for v in row]
            all_rows.append(row)
            overflow = (sec != 5) and (i >= ROWS_VISIBLE)
            row_meta.append({"section": sec, "is_header": False,
                             "is_overflow": overflow, "is_spacer": False})

    try:
        sheet_meta  = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        sheet_props = next(
            (s["properties"] for s in sheet_meta.get("sheets", [])
             if s["properties"]["sheetId"] == 0), {}
        )
        current_rows = sheet_props.get("gridProperties", {}).get("rowCount", 1000)
        current_cols = sheet_props.get("gridProperties", {}).get("columnCount", 26)

        service.spreadsheets().values().clear(
            spreadsheetId=sheet_id, range="A:Z"
        ).execute()
        service.spreadsheets().values().update(
            spreadsheetId=sheet_id, range="A1",
            valueInputOption="USER_ENTERED",
            body={"values": all_rows}
        ).execute()

        rows_written = len(all_rows)
        if current_rows > rows_written + 5:
            sheets_batch_with_backoff(
                service, sheet_id,
                [{"deleteDimension": {"range": {"sheetId": 0, "dimension": "ROWS",
                                                "startIndex": rows_written,
                                                "endIndex": current_rows}}}],
                "delete excess rows"
            )
        if current_cols > NUM_COLS + 1:
            sheets_batch_with_backoff(
                service, sheet_id,
                [{"deleteDimension": {"range": {"sheetId": 0, "dimension": "COLUMNS",
                                                "startIndex": NUM_COLS,
                                                "endIndex": current_cols}}}],
                "delete excess columns"
            )

        print(f"    \U0001f4ca Wrote {len(all_rows)-1} rows ("
              f"{len(sections.get(0,[]))} pinned, "
              f"{len(sections.get(1,[]))} gems, "
              f"{len(sections.get(6,[]))} just posted, "
              f"{len(sections.get(2,[]))} open market, "
              f"{len(sections.get(3,[]))} circulating, "
              f"{len(sections.get(4,[]))} possible, "
              f"{len(sections.get(5,[]))} applied)")
    except Exception as e:
        print(f"    \u274c Write error: {e}"); return

    apply_sheet_formatting(service, sheet_id, all_rows, row_meta)


def apply_sheet_formatting(service, sheet_id, all_rows, row_meta):
    batch = []
    gid   = 0

    batch.append({"updateSheetProperties": {
        "properties": {"sheetId": gid, "gridProperties": {"frozenRowCount": 1}},
        "fields": "gridProperties.frozenRowCount"
    }})

    widths = {
        0:30, 1:30, 2:220, 3:160, 4:50, 5:100, 6:90, 7:90,
        8:100, 9:40, 10:55, 11:90, 12:90, 13:100, 14:140,
        15:205, 16:100, 17:140, 18:110, 19:130, 20:120, 21:200, 22:50,
    }
    for col_idx, px in widths.items():
        batch.append({"updateDimensionProperties": {
            "range": {"sheetId": gid, "dimension": "COLUMNS",
                      "startIndex": col_idx, "endIndex": col_idx + 1},
            "properties": {"pixelSize": px}, "fields": "pixelSize"
        }})

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
    for col_idx in [0, 1]:
        batch.append({"repeatCell": {
            "range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1},
            "cell": {"userEnteredFormat": {"textRotation": {"angle": 90}}},
            "fields": "userEnteredFormat.textRotation"
        }})

    batch.append({"repeatCell": {
        "range": {"sheetId": gid, "startRowIndex": 1},
        "cell": {"userEnteredFormat": {"backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}}},
        "fields": "userEnteredFormat.backgroundColor"
    }})

    for i, meta in enumerate(row_meta):
        sr = i + 1
        if not meta["is_header"]: continue
        sec   = meta["section"]
        color = SECTION_COLORS.get(sec, {"bg": "333333"})
        bg    = color["bg"]
        r = int(bg[0:2], 16) / 255
        g = int(bg[2:4], 16) / 255
        b = int(bg[4:6], 16) / 255
        batch.append({"repeatCell": {
            "range": {"sheetId": gid, "startRowIndex": sr, "endRowIndex": sr + 1},
            "cell": {"userEnteredFormat": {
                "backgroundColor": {"red": r, "green": g, "blue": b},
                "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1},
                               "bold": True, "fontSize": 10}
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)"
        }})

    data_rows = [i + 1 for i, m in enumerate(row_meta)
                 if not m["is_header"] and not m.get("is_spacer", False)]
    for sr in data_rows:
        batch.append({"repeatCell": {
            "range": {"sheetId": gid, "startRowIndex": sr, "endRowIndex": sr + 1,
                      "startColumnIndex": 0, "endColumnIndex": 1},
            "cell": {
                "userEnteredFormat": {"backgroundColor": {"red": 0.88, "green": 0.96, "blue": 0.88}},
                "dataValidation": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}
            },
            "fields": "userEnteredFormat.backgroundColor,dataValidation"
        }})
        batch.append({"repeatCell": {
            "range": {"sheetId": gid, "startRowIndex": sr, "endRowIndex": sr + 1,
                      "startColumnIndex": 1, "endColumnIndex": 2},
            "cell": {
                "userEnteredFormat": {"backgroundColor": {"red": 0.99, "green": 0.88, "blue": 0.88}},
                "dataValidation": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}
            },
            "fields": "userEnteredFormat.backgroundColor,dataValidation"
        }})
        batch.append({"repeatCell": {
            "range": {"sheetId": gid, "startRowIndex": sr, "endRowIndex": sr + 1,
                      "startColumnIndex": 10, "endColumnIndex": 11},
            "cell": {"dataValidation": {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}},
            "fields": "dataValidation"
        }})

    batch.append({"repeatCell": {
        "range": {"sheetId": gid, "startRowIndex": 1,
                  "startColumnIndex": COL["stage"], "endColumnIndex": COL["stage"] + 1},
        "cell": {"dataValidation": {
            "condition": {"type": "ONE_OF_LIST",
                          "values": [{"userEnteredValue": s} for s in STAGE_OPTIONS]},
            "showCustomUi": True, "strict": False
        }},
        "fields": "dataValidation"
    }})
    batch.append({"repeatCell": {
        "range": {"sheetId": gid, "startRowIndex": 1,
                  "startColumnIndex": COL["remote"], "endColumnIndex": COL["remote"] + 1},
        "cell": {"dataValidation": {
            "condition": {"type": "ONE_OF_LIST",
                          "values": [{"userEnteredValue": s} for s in REMOTE_OPTIONS]},
            "showCustomUi": True, "strict": False
        }},
        "fields": "dataValidation"
    }})
    for wrap_col in [COL["notes"], COL["cover_letter"]]:
        batch.append({"repeatCell": {
            "range": {"sheetId": gid, "startRowIndex": 1,
                      "startColumnIndex": wrap_col, "endColumnIndex": wrap_col + 1},
            "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
            "fields": "userEnteredFormat.wrapStrategy"
        }})

    grey_italic  = {"foregroundColor": {"red": 0.6, "green": 0.6, "blue": 0.6},
                    "italic": True, "fontSize": 9}
    black_normal = {"foregroundColor": {"red": 0.0, "green": 0.0, "blue": 0.0},
                    "bold": False, "italic": False, "fontSize": 10}
    text_cols = [COL["title"], COL["company"], COL["match"], COL["remote"],
                 COL["location"], COL["date_posted"], COL["first_seen"],
                 COL["date_applied"], COL["date_followed"], COL["contact"],
                 COL["ats_site"], COL["syndication"], COL["hidden"]]
    for col_idx in text_cols:
        batch.append({"repeatCell": {
            "range": {"sheetId": gid, "startRowIndex": 1,
                      "startColumnIndex": col_idx, "endColumnIndex": col_idx + 1},
            "cell": {"userEnteredFormat": {"textFormat": black_normal}},
            "fields": "userEnteredFormat.textFormat"
        }})
    for i, meta in enumerate(row_meta):
        sr = i + 1
        if meta["is_header"] or meta.get("is_spacer"): continue
        row = all_rows[sr] if sr < len(all_rows) else []
        sal = row[COL["salary"]]   if len(row) > COL["salary"]   else ""
        loc = row[COL["location"]] if len(row) > COL["location"] else ""
        if str(sal) in ("n/a", ""):
            batch.append({"repeatCell": {
                "range": {"sheetId": gid, "startRowIndex": sr, "endRowIndex": sr + 1,
                          "startColumnIndex": COL["salary"], "endColumnIndex": COL["salary"] + 1},
                "cell": {"userEnteredFormat": {"textFormat": grey_italic}},
                "fields": "userEnteredFormat.textFormat"
            }})
        if str(loc) in ("unknown", ""):
            batch.append({"repeatCell": {
                "range": {"sheetId": gid, "startRowIndex": sr, "endRowIndex": sr + 1,
                          "startColumnIndex": COL["location"], "endColumnIndex": COL["location"] + 1},
                "cell": {"userEnteredFormat": {"textFormat": grey_italic}},
                "fields": "userEnteredFormat.textFormat"
            }})

    def run_chunks(requests, chunk_size=50):
        """Send batch requests in chunks with exponential backoff on 429 rate limits."""
        for i in range(0, len(requests), chunk_size):
            chunk   = requests[i:i + chunk_size]
            delay   = 15
            retries = 4
            for attempt in range(retries):
                try:
                    service.spreadsheets().batchUpdate(
                        spreadsheetId=sheet_id, body={"requests": chunk}
                    ).execute()
                    time.sleep(1.2)   # polite pause between chunks
                    break
                except HttpError as e:
                    if e.resp.status == 429:
                        if attempt < retries - 1:
                            print(f"    \u23f3 Rate limit — waiting {delay}s...")
                            time.sleep(delay)
                            delay *= 2
                        else:
                            print(f"    \u26a0\ufe0f  Chunk failed after {retries} retries")
                    else:
                        print(f"    \u26a0\ufe0f  Formatting chunk error: {e}")
                        break
                except Exception as e:
                    print(f"    \u26a0\ufe0f  Formatting chunk error: {e}")
                    break

    run_chunks(batch)
    print(f"    \U0001f3a8 Formatting applied")
    create_filter_views(service, sheet_id, gid)


def sheets_batch_with_backoff(service, sheet_id, requests_body, label=""):
    """Execute a batchUpdate with exponential backoff on 429."""
    delay   = 15
    retries = 4
    for attempt in range(retries):
        try:
            service.spreadsheets().batchUpdate(
                spreadsheetId=sheet_id, body={"requests": requests_body}
            ).execute()
            return True
        except HttpError as e:
            if e.resp.status == 429:
                if attempt < retries - 1:
                    print(f"    \u23f3 Rate limit{' (' + label + ')' if label else ''} — waiting {delay}s...")
                    time.sleep(delay)
                    delay *= 2
                else:
                    print(f"    \u26a0\ufe0f  {label or 'batchUpdate'} failed after {retries} retries")
                    return False
            else:
                print(f"    \u26a0\ufe0f  {label or 'batchUpdate'} error: {e}")
                return False
        except Exception as e:
            print(f"    \u26a0\ufe0f  {label or 'batchUpdate'} error: {e}")
            return False
    return False


def create_filter_views(service, sheet_id, gid):
    today = datetime.date.today().isoformat()
    try:
        meta   = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        sheets = meta.get("sheets", [])
        info   = next((s for s in sheets if s["properties"]["sheetId"] == gid), None)
        if info:
            del_ids = [fv["filterViewId"] for fv in info.get("filterViews", [])
                       if fv.get("title", "").startswith("\U0001f50d")]
            if del_ids:
                sheets_batch_with_backoff(
                    service, sheet_id,
                    [{"deleteFilterView": {"filterId": fid}} for fid in del_ids],
                    "delete filter views"
                )
    except Exception:
        pass
    filter_views = [
        {"title": "\U0001f50d Pinned",       "col": COL["pinned"],     "type": "CUSTOM_FORMULA", "val": "=$A2=TRUE"},
        {"title": "\U0001f50d Strong Matches","col": COL["match"],      "type": "TEXT_CONTAINS",  "val": "Strong"},
        {"title": "\U0001f50d New This Run",  "col": COL["first_seen"], "type": "TEXT_EQ",        "val": today},
        {"title": "\U0001f50d Applied",       "col": COL["section"],    "type": "TEXT_EQ",        "val": "5"},
    ]
    requests_body = []
    for fv in filter_views:
        requests_body.append({"addFilterView": {"filter": {
            "title": fv["title"],
            "range": {"sheetId": gid, "startRowIndex": 0,
                      "startColumnIndex": 0, "endColumnIndex": NUM_COLS},
            "filterSpecs": [{"columnIndex": fv["col"], "filterCriteria": {
                "condition": {"type": fv["type"], "values": [{"userEnteredValue": fv["val"]}]}
            }}]
        }}})
    if sheets_batch_with_backoff(service, sheet_id, requests_body, "create filter views"):
        print(f"    \U0001f50d Filter views created")


def update_sheet(name, all_jobs, prev_user_data, new_rejected_urls):
    if not SHEETS_ENABLED: return
    sheet_id = SHEET_IDS.get(name, "")
    if not sheet_id or not sheet_id.strip():
        print(f"    \u26a0\ufe0f  No Sheet ID for {name}"); return
    service = get_sheets_service()
    if not service: return

    if new_rejected_urls:
        save_rejected(name, new_rejected_urls)
        print(f"    \U0001f6ab {len(new_rejected_urls)} URLs added to reject list")

    current_urls = {j["url"] for j in all_jobs}
    rejected     = load_rejected(name)
    history      = load_history(name)

    for url, h in history.items():
        if url in current_urls or url in rejected: continue
        if not h.get("pinned"): continue
        fs = h.get("first_seen_date", datetime.date.today() - datetime.timedelta(days=8))
        revived = {
            "title": h.get("title",""), "company": h.get("company",""),
            "url": url, "ats_site": h.get("ats_site",""),
            "keywords": "", "snippet": "",
            "salary": h.get("salary",""), "remote": "",
            "location": h.get("location",""), "date_posted": "",
            "seen_before": True, "first_seen_date": fs,
            "first_seen": fs.isoformat() if hasattr(fs, "isoformat") else str(fs),
            "on_linkedin": False, "on_indeed": False, "on_glassdoor": False,
            "unsyndicated": True, "relevance_score": 0.0,
            "relevance_label": h.get("match", "\U0001f535 Possible") or "\U0001f535 Possible",
            "relevance_reasons": [],
        }
        all_jobs.append(revived)
        current_urls.add(url)
        if url not in prev_user_data: prev_user_data[url] = {}
        prev_user_data[url]["pinned"] = "TRUE"
        print(f"    \U0001f4cc Resurrected: {h.get('title','')[:55]}")

    for url, p in prev_user_data.items():
        if url in current_urls or url in rejected: continue
        is_pinned  = normalize_bool(p.get("pinned", ""))
        is_applied = normalize_bool(p.get("applied_check", "")) or bool(p.get("date_applied","").strip())
        has_data   = any(str(p.get(c, "")).strip() for c in USER_COLS
                         if c not in ("pinned", "reject", "applied_check"))
        if is_pinned or is_applied or has_data:
            label = p.get("match", "\U0001f535 Possible") or "\U0001f535 Possible"
            try: fs = datetime.date.fromisoformat(p.get("first_seen", "")[:10])
            except: fs = datetime.date.today() - datetime.timedelta(days=8)
            revived = {
                "title": p.get("title",""), "company": p.get("company",""),
                "url": url, "ats_site": p.get("ats_site",""),
                "keywords": "", "snippet": "",
                "salary": p.get("salary",""), "remote": p.get("remote",""),
                "location": p.get("location",""), "date_posted": "",
                "seen_before": True, "first_seen_date": fs,
                "first_seen": p.get("first_seen",""),
                "on_linkedin": False, "on_indeed": False, "on_glassdoor": False,
                "unsyndicated": is_pinned,
                "relevance_score": float(p.get("relevance_score", 0) or 0),
                "relevance_label": label, "relevance_reasons": [],
            }
            all_jobs.append(revived)
            current_urls.add(url)
            if not is_pinned and not is_applied:
                prev_user_data[url]["stage"] = "Expired?"

    seen_urls = set()
    deduped   = []
    for job in all_jobs:
        url = job.get("url", "")
        if not url or not url.startswith("http") or url in seen_urls: continue
        if url in rejected: seen_urls.add(url); continue
        seen_urls.add(url)
        if not job.get("relevance_label"): job["relevance_label"] = "\U0001f535 Possible"
        if not job.get("title", "").strip(): continue
        deduped.append(job)

    pinned_saved = save_history(name, deduped, prev_user_data, new_rejected_urls)
    if pinned_saved:
        print(f"    \U0001f4cc {pinned_saved} pinned jobs saved in history")

    print(f"    \U0001f4cb Writing {len(deduped)} jobs to sheet")
    rewrite_sheet(service, sheet_id, name, deduped, prev_user_data)


# =============================================================================
# 🔧 EMAIL BUILDER
# =============================================================================

def build_email_html(profile, gems, just_posted):
    name      = profile["name"]
    date_str  = datetime.date.today().strftime("%B %d, %Y")
    sheet_id  = SHEET_IDS.get(name, "")
    sheet_url = (f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
                 if sheet_id and sheet_id.strip() else "")

    def rbadge(val):
        c = {"\U0001f3e0 Remote":    ("#dcfce7","#166534"),
             "\U0001f3e0\U0001f3e2 Hybrid": ("#fef9c3","#92400e"),
             "\U0001f3e0 In-range":  ("#eff6ff","#1e40af"),
             "\U0001f3e2 In-person": ("#fee2e2","#991b1b")}
        bg, fg = c.get(val, ("#f3f4f6","#6b7280"))
        return (f'<span style="background:{bg};color:{fg};padding:1px 7px;'
                f'border-radius:10px;font-size:11px;font-weight:600;">{val}</span>')

    def mbadge(label):
        c = {"\U0001f7e2 Strong":("#dcfce7","#166534"),"\U0001f7e1 Good":("#fef9c3","#92400e")}
        bg, fg = c.get(label, ("#f3f4f6","#6b7280"))
        return (f'<span style="background:{bg};color:{fg};padding:1px 8px;'
                f'border-radius:10px;font-size:11px;font-weight:700;">{label}</span>')

    def card(job):
        sal      = job.get("salary") or "n/a"
        loc      = job.get("location") or "unknown"
        date_p   = job.get("date_posted", "")
        date_html = (f'<span style="font-size:11px;color:#9ca3af;margin-left:8px;">'
                     f'Posted: {date_p}</span>') if date_p else ""
        remote   = job.get("remote", "") or "\U0001f3e2 In-person"
        return f"""
        <div style="border:1px solid #e5e7eb;border-radius:8px;padding:14px 16px;
                    margin-bottom:10px;background:#fff;">
          <div style="margin-bottom:6px;">
            {mbadge(job['relevance_label'])}
            <span style="background:#eff6ff;color:#1e40af;padding:1px 8px;
                         border-radius:10px;font-size:12px;font-weight:600;
                         margin-right:4px;">\U0001f4b0 {sal}</span>
            {rbadge(remote)}
            <span style="font-size:12px;color:#6b7280;margin-left:6px;">\U0001f4cd {loc}</span>
            {date_html}
          </div>
          <div style="margin-bottom:5px;">
            <a href="{job['url']}"
               style="font-size:15px;font-weight:600;color:#1e3a5f;
                      text-decoration:underline;">{job['title']}</a>
          </div>
          <div style="font-size:13px;color:#374151;margin-bottom:4px;">
            \U0001f3e2 {job['company']}
          </div>
          <div style="font-size:13px;color:#4b5563;line-height:1.5;">
            {job.get('snippet','')}
          </div>
        </div>"""

    gems_html = ("\n".join(card(j) for j in gems) if gems else
                 "<p style='color:#9ca3af;font-size:13px;font-style:italic;'>"
                 "No new hidden gems this run \u2014 check your tracker for the full list.</p>")

    sheet_btn = ""
    if sheet_url:
        sheet_btn = (f'<div style="background:#f0f9ff;border:1px solid #bae6fd;'
                     f'border-radius:8px;padding:12px 16px;margin:12px 0;">'
                     f'<div style="font-size:13px;color:#0369a1;margin-bottom:8px;">'
                     f'<strong>\U0001f4ca Full results in your tracker</strong> \u2014 all matches, '
                     f'pinned jobs, and application status.</div>'
                     f'<a href="{sheet_url}" style="display:inline-block;'
                     f'background:#1e3a5f;color:#fff;padding:8px 16px;border-radius:6px;'
                     f'font-size:13px;font-weight:600;text-decoration:none;">'
                     f'Open Tracker \u2192</a></div>')

    test_banner = ""
    if TEST_MODE:
        test_banner = ('<div style="background:#fef3c7;border:2px solid #f59e0b;'
                       'border-radius:8px;padding:10px 16px;margin-bottom:14px;'
                       'font-size:13px;color:#92400e;font-weight:600;">'
                       '\U0001f9ea TEST MODE \u2014 routed to sender for review.</div>')

    label, defn = SECTION_LABELS[1]
    sec_hdr = (f'<div style="background:#166534;color:#fff;border-radius:8px;'
               f'padding:12px 16px;margin:16px 0 10px;">'
               f'<div style="font-size:15px;font-weight:700;">{label} \u2014 {len(gems)} new</div>'
               f'<div style="font-size:12px;opacity:0.85;margin-top:3px;">{defn}</div>'
               f'</div>')

    jp_label, jp_defn = SECTION_LABELS[6]
    jp_color = f"#{SECTION_COLORS[6]['bg']}"
    jp_hdr = (f'<div style="background:{jp_color};color:#fff;border-radius:8px;'
              f'padding:12px 16px;margin:20px 0 10px;">'
              f'<div style="font-size:15px;font-weight:700;">{jp_label} \u2014 {len(just_posted)} new</div>'
              f'<div style="font-size:12px;opacity:0.85;margin-top:3px;">{jp_defn}</div>'
              f'</div>')

    jp_html = "\n".join(card(j) for j in just_posted) if just_posted else ""

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
        background:#f3f4f6;margin:0;padding:20px;color:#111827;}}
  .wrap{{max-width:700px;margin:0 auto;}}
  .hdr{{background:#1e3a5f;color:#fff;border-radius:10px 10px 0 0;padding:22px 26px;}}
  .hdr h1{{margin:0 0 3px;font-size:21px;}}
  .hdr p{{margin:0;font-size:13px;opacity:.75;}}
  .warning{{background:#fef9c3;border:1px solid #fde68a;border-radius:8px;
            padding:10px 14px;margin:12px 0;font-size:13px;color:#92400e;}}
  .footer{{text-align:center;color:#9ca3af;font-size:11px;padding:16px 0 0;}}
</style></head>
<body><div class="wrap">
  {test_banner}
  <div class="hdr">
    <h1>\U0001f48e Hidden Gems \u2014 {name}</h1>
    <p>{date_str} &nbsp;&middot;&nbsp; {DAYS_BACK}-day search window &nbsp;&middot;&nbsp;
       {len(ALL_SOURCES)} sources</p>
  </div>
  <div class="warning">\u26a0\ufe0f <strong>Verify each posting is still open before applying.</strong>
    Full results including all matches are in your tracker.</div>
  {sheet_btn}
  {sec_hdr}
  {gems_html}
  {jp_hdr if just_posted else ""}
  {jp_html}
  <div class="footer">ATS Job Search &middot; serper.dev &middot; {date_str}</div>
</div></body></html>"""


# =============================================================================
# 🔧 EMAIL SENDER
# =============================================================================

def send_email(to_email, to_name, html_body):
    date_str  = datetime.date.today().strftime("%b %d")
    actual_to = BCC_EMAIL if TEST_MODE else to_email
    subject   = f"{'[TEST] ' if TEST_MODE else ''}Job Search \u2014 {to_name} \u00b7 {date_str}"
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
        mode = "\u2192 TEST" if TEST_MODE else f"\u2192 {to_email}"
        print(f"    \U0001f4e7 {to_name} {mode}")
    except Exception as e:
        print(f"    \u274c Email failed for {to_name}: {e}")


# =============================================================================
# 🔧 MAIN
# =============================================================================

def main():
    print(f"\n\U0001f50d ATS Job Search v4.4.3")
    print(f"   {datetime.date.today()} | {DAYS_BACK}d window | "
          f"{len(ALL_SOURCES)} sources ({len(ATS_SITES)} ATS + {len(EMPLOYER_SITES)} employers) | "
          f"TEST={TEST_MODE} | SINGLE={TEST_PROFILE_ONLY}\n")

    if not SERPER_API_KEY:
        print("\u274c SERPER_API_KEY missing from .env"); return
    if not SENDER_APP_PASSWORD:
        print("\u274c SENDER_APP_PASSWORD missing from .env"); return
    if not SENDER_EMAIL:
        print("\u274c SENDER_EMAIL missing from .env"); return

    profiles_to_run = PROFILES[:1] if TEST_PROFILE_ONLY else PROFILES

    for profile in profiles_to_run:
        name     = profile["name"]
        sheet_id = SHEET_IDS.get(name, "")
        prev_user_data    = {}
        new_rejected_urls = []

        if SHEETS_ENABLED and sheet_id and sheet_id.strip():
            service = get_sheets_service()
            if service:
                prev_user_data = read_existing_rows(service, sheet_id)
                print(f"    \U0001f4d6 Read {len(prev_user_data)} existing rows from sheet")
                for url, p in prev_user_data.items():
                    if normalize_bool(p.get("reject", "")):
                        new_rejected_urls.append(url)
                if new_rejected_urls:
                    print(f"    \U0001f6ab {len(new_rejected_urls)} newly rejected jobs found in sheet")
            else:
                print(f"    \u26a0\ufe0f  Could not connect to Google Sheets \u2014 sheet will not update")
        elif not sheet_id:
            print(f"    \u26a0\ufe0f  No Sheet ID configured for {name}")

        results = search_for_profile(profile)
        today   = datetime.date.today()
        sal_min = profile.get("salary_minimum", 0)

        gems = sorted(
            [j for j in results
             if j["relevance_label"] in ("\U0001f7e2 Strong", "\U0001f7e1 Good")
             and not j["seen_before"]
             and j["unsyndicated"]
             and (today - j.get("first_seen_date", today)).days <= GEM_AGE_DAYS],
            key=lambda x: x["relevance_score"], reverse=True
        )
        gem_urls = {j["url"] for j in gems}
        just_posted = sorted(
            [j for j in results
             if j["relevance_label"] in ("\U0001f7e2 Strong", "\U0001f7e1 Good")
             and not j["seen_before"]
             and not j["unsyndicated"]
             and j["url"] not in gem_urls
             and is_just_posted(j)],
            key=lambda x: x["relevance_score"], reverse=True
        )

        # Email-priority deep fetch — ensure Hidden Gems + Just Posted have max data
        # These are the highest-value jobs; fetch any still missing salary or location
        email_jobs = gems + just_posted
        needs_fetch = [j for j in email_jobs
                       if not j.get("salary") or j.get("salary") == "n/a"
                       or not j.get("location") or j.get("location") == "unknown"
                       or not j.get("date_posted")]
        if needs_fetch:
            print(f"    🔎 Email-priority fetch for {len(needs_fetch)} gems/just-posted missing data...")
            for job in needs_fetch:
                pg_sal, pg_loc, pg_rem, pg_date = fetch_job_page(job["url"])
                cur_sal = job.get("salary", "") if job.get("salary") not in ("", "n/a") else ""
                cur_loc = job.get("location", "") if job.get("location") not in ("", "unknown") else ""
                if pg_sal  and not cur_sal:  job["salary"]      = pg_sal
                if pg_loc  and not cur_loc:  job["location"]    = pg_loc
                if pg_rem  and job.get("remote") in ("In-person", "\U0001f3e2 In-person", ""):
                                             job["remote"]      = pg_rem
                if pg_date and not job.get("date_posted"): job["date_posted"] = pg_date
                # Re-check salary minimum after fetch
                sal_val = extract_salary_value(job.get("salary", ""))
                if sal_val is not None and sal_val < sal_min:
                    print(f"      \u2193 Gem demoted post-fetch (salary {job['salary']} < ${sal_min:,})")
                    job["relevance_label"] = "\U0001f535 Possible"
                    job["relevance_score"] = min(job.get("relevance_score", 0), 9.9)
                time.sleep(0.4)
            # Rebuild lists — remove any demoted jobs
            gems        = [j for j in gems        if j["relevance_label"] != "\U0001f535 Possible"]
            just_posted = [j for j in just_posted if j["relevance_label"] != "\U0001f535 Possible"]

        if SHEETS_ENABLED:
            print(f"    \U0001f4ca Updating sheet for {name}...")
            update_sheet(name, results, prev_user_data, new_rejected_urls)

        print(f"    \U0001f4e7 Sending email \u2014 {len(gems)} Hidden Gems, {len(just_posted)} Just Posted...")
        html = build_email_html(profile, gems, just_posted)
        send_email(profile["email"], name, html)
        print("   Cooling down...\n")
        time.sleep(5)

    print("\n\u2728 Done.\n")
    if TEST_MODE:
        print("   \u26a0\ufe0f  Set TEST_MODE=False and TEST_PROFILE_ONLY=False for live send.\n")


if __name__ == "__main__":
    main()