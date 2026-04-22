# Changelog

All notable changes to the ATS Job Search Script are documented here.

---

## v4.3.1 — April 2026
- Fixed 500 error on Google Sheets formatting by splitting batch requests into chunks of 50
- Fixed section header rows being misread as job rows on sheet rewrite (now skips rows with no URL)
- Fixed checkbox columns showing "ALS" — switched Reject column to standard BOOLEAN validation
- Fixed Applied! column showing "False" as text — changed valueInputOption to USER_ENTERED
- Adjusted column widths: Pinned/Reject narrower, Title wider

## v4.3 — April 2026
- Scoring reweighted: title 80% / seniority 7% / location 13%
- Section logic now age-based: jobs stay in Section 1/2 for 7 days from first_seen, then move to Section 3
- Added Reject column (col B) with red background and 90-day memory — rejected URLs suppressed from future runs
- Pinned column (col A) now has light green background
- Applied! checkbox moved to col J, immediately right of URL
- Date Posted added (col K) via JSON-LD structured data extraction
- Date Applied auto-filled by script when Applied! is checked but date is blank
- Stage column is now a combined dropdown replacing separate Stage + Interview Stage columns
- Removed · barrier column (Applied! checkbox serves as visual break)
- Email: ATS site label removed from job cards, job title links now underlined
- Credentials moved to .env file — no more editing API keys in the script
- Reject memory stored in rejected_urls_NAME.csv with 90-day TTL

## v4.2.3 — April 2026
- Added filter views to Google Sheets: Pinned, Strong Matches, New This Run, Applied
- Fixed Pinned column writing "True" as text instead of checkbox boolean
- Fixed row group collapse error — groups now deleted depth-by-depth before recreating
- Added Apps Script macro for "Open Pinned Jobs" menu in each sheet

## v4.2.2 — April 2026
- Tightened salary regex — now requires $XXX,XXX format, $XXXk, or $XX/hr (rejects single-digit junk)
- Added JSON-LD structured data parsing in fetch_job_page() for more reliable salary and location extraction

## v4.2.1 — April 2026
- Fixed persistent row grouping HttpError 400 — delete step now runs as separate pre-step
- Fixed sheet color bleeding into job rows — backgrounds now explicitly cleared before re-applying
- Fixed Section 3 grid table rendering (added proper thead/tbody structure)
- Added .env credential file support — credentials no longer hardcoded in script

## v4.2 — April 2026
- Pre-filters applied before cross-referencing to save API credits:
  - Location filter (strict): requires remote signal OR recognized ok city, drops ambiguous
  - Title exclusion keywords: nursing, nurse, software engineer, developer, recruiter
  - Snippet exclusion keywords: entry level, internship, new grad, data scientist
- Full page fetch + cross-reference now runs only on Strong/Good jobs (not Possible)
- Post-fetch salary demotion: jobs below salary minimum demoted to Possible
- Improved company name extraction — fixes ATS domain bleeding into company field
- Remote options expanded: Remote / Hybrid / In-range / In-person
- Scoring: title 60% / seniority 15% / location 25%
- Email shows Strong + Good only; Possible goes to sheet Section 4 only
- Salary minimums per profile: Andy/David $150k, Vanessa/Maryjane $200k
- Placeholder · column added after URL as visual barrier
- Pinned and Applied! columns formatted as proper Sheets checkboxes
- Color section headers added to email with white text and section definitions

## v4.1 — April 2026
- Skip cross-reference checks for returning jobs (seen_before=True) — only new jobs checked
- ATS results capped at 5 per query (was 10) to reduce Serper credit consumption
- Email job cards always show Location, Remote, and Salary (or "Not listed")
- Column widths tuned to user specification
- Text wrap enabled on Notes and Cover Letter Notes columns

## v4 — April 2026
- Four-section email: Hidden Gems / Open Market Picks / Still Circulating / Other Matches
- Section 5 (Applied & Waiting): triggered by Applied! checkbox or Date Applied
- Section 0 (Pinned): jobs always stay at top regardless of other logic
- Google Sheets integration: full rewrite on each run, user data preserved across rewrites
- Row grouping: top 20 rows visible per section, overflow collapsed with + toggle
- Salary surfacing via $ proximity detection in snippets
- Relevance scoring with color labels (Strong / Good / Possible)
- Test mode switches: TEST_MODE and TEST_PROFILE_ONLY
- History tracking per person in local CSV files (3-week TTL)
- BCC on all outgoing emails for sender monitoring

## v3 — March 2026
- Rebuilt email with 4 sections and expandable overflow
- Added relevance scoring (equal weight across title, seniority, location)
- History tracking introduced (seen_before logic)
- Google Sheets tracker added with append-on-run logic

## v2 — March 2026
- Multi-profile support: Andy, Vanessa, Maryjane, David
- Gmail delivery with App Password authentication
- Per-profile keyword combos, industry filters, location preferences
- BCC monitoring for sender

## v1 — March 2026
- Initial script: single profile, Serper.dev ATS search
- Cross-reference check against LinkedIn, Indeed, Glassdoor
- CSV and HTML output
- 14 ATS platforms: Ashby, Lever, Greenhouse, Workable, BambooHR, Paylocity,
  iCIMS, Jobvite, Workday, SmartRecruiters, Recruitee, ApplyToJob, Jazz, Breezy
