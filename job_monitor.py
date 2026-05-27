#!/usr/bin/env python3
"""
Job monitor: scans 161 confirmed-remote company career pages for
VP/Sr. Director of Product Marketing roles and sends email alerts.
"""

import json
import os
import re
import smtplib
import sys
import time
import traceback
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SEEN_JOBS_FILE = Path(__file__).parent / "seen_jobs.json"
COMPANIES_FILE = Path(__file__).parent / "companies.json"

ALERT_EMAIL = "greggwilliammiller@gmail.com"
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

IS_FIRST_RUN = not SEEN_JOBS_FILE.exists() or os.environ.get("FORCE_FIRST_RUN") == "true"

TITLE_PATTERNS = [
    r"\bvp\b.{0,40}product marketing",
    r"vice president.{0,40}product marketing",
    r"\bsr\.?\s+director.{0,40}product marketing",
    r"\bsenior director.{0,40}product marketing",
    r"\bvp\b.{0,40}\bpmm\b",
    r"\bsr\.?\s+director.{0,40}\bpmm\b",
    r"\bsenior director.{0,40}\bpmm\b",
    r"\bhead of product marketing",
]
TITLE_RE = re.compile("|".join(TITLE_PATTERNS), re.IGNORECASE)

# Location strings that indicate a role is NOT remote
NONREMOTE_RE = re.compile(
    r"\bhybrid\b|\bin.?office\b|\bon.?site\b|\bin.?person\b",
    re.IGNORECASE,
)

def is_remote_location(location: str) -> bool:
    """Return False if the location explicitly signals hybrid or in-person."""
    if not location:
        return True  # unknown → don't filter out
    return not NONREMOTE_RE.search(location)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

REQUEST_TIMEOUT = 20


def load_seen_jobs():
    if SEEN_JOBS_FILE.exists():
        try:
            return json.loads(SEEN_JOBS_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_seen_jobs(seen):
    SEEN_JOBS_FILE.write_text(json.dumps(seen, indent=2))


def title_matches(title: str) -> bool:
    return bool(TITLE_RE.search(title))


def get_greenhouse_jobs(ats_id: str, company_name: str) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{ats_id}/jobs?content=true"
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return []
        data = r.json()
        jobs = []
        for job in data.get("jobs", []):
            title = job.get("title", "")
            if not title_matches(title):
                continue
            location = job.get("location", {}).get("name", "")
            if not is_remote_location(location):
                continue
            jobs.append({
                    "id": str(job.get("id", "")),
                    "company": company_name,
                    "title": title,
                    "location": job.get("location", {}).get("name", ""),
                    "url": job.get("absolute_url", ""),
                    "posted": job.get("updated_at", "")[:10] if job.get("updated_at") else "",
                    "source": "greenhouse",
                })
        return jobs
    except Exception:
        return []


def get_lever_jobs(ats_id: str, company_name: str) -> list[dict]:
    url = f"https://api.lever.co/v0/postings/{ats_id}?mode=json"
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return []
        data = r.json()
        jobs = []
        for job in data:
            title = job.get("text", "")
            if not title_matches(title):
                continue
            location = job.get("categories", {}).get("location", "")
            if not is_remote_location(location):
                continue
            jobs.append({
                    "id": job.get("id", ""),
                    "company": company_name,
                    "title": title,
                    "location": job.get("categories", {}).get("location", ""),
                    "url": job.get("hostedUrl", ""),
                    "posted": datetime.fromtimestamp(job["createdAt"] / 1000).strftime("%Y-%m-%d") if job.get("createdAt") else "",
                    "source": "lever",
                })
        return jobs
    except Exception:
        return []


def get_ashby_jobs(ats_id: str, company_name: str) -> list[dict]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{ats_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return []
        data = r.json()
        jobs = []
        for job in data.get("jobs", []):
            title = job.get("title", "")
            if not title_matches(title):
                continue
            location = job.get("location", "")
            if not is_remote_location(location):
                continue
            jobs.append({
                    "id": job.get("id", ""),
                    "company": company_name,
                    "title": title,
                    "location": job.get("location", ""),
                    "url": job.get("jobUrl", ""),
                    "posted": job.get("publishedAt", "")[:10] if job.get("publishedAt") else "",
                    "source": "ashby",
                })
        return jobs
    except Exception:
        return []


def scrape_jobs_html(career_url: str, company_name: str) -> list[dict]:
    """Fallback HTML scraper for Workday and other non-API ATSs."""
    try:
        r = requests.get(career_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        jobs = []
        seen_titles = set()

        # Look for job title elements in anchor tags and list items
        candidates = []
        for tag in soup.find_all(["a", "li", "h2", "h3", "h4", "span", "div"]):
            text = tag.get_text(strip=True)
            if len(text) < 10 or len(text) > 200:
                continue
            if title_matches(text) and text not in seen_titles:
                seen_titles.add(text)
                href = tag.get("href", "") if tag.name == "a" else ""
                if href and not href.startswith("http"):
                    from urllib.parse import urljoin
                    href = urljoin(career_url, href)
                candidates.append((text, href))

        for title, url in candidates:
            jobs.append({
                "id": f"{company_name}::{title}",
                "company": company_name,
                "title": title,
                "location": "See listing",
                "url": url or career_url,
                "posted": "",
                "source": "scrape",
            })
        return jobs
    except Exception:
        return []


def scrape_jobs_playwright(career_url: str, company_name: str) -> list[dict]:
    """JS-rendered page scraper using Playwright."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({"User-Agent": HEADERS["User-Agent"]})
            page.goto(career_url, timeout=30000, wait_until="networkidle")
            time.sleep(2)
            content = page.content()
            browser.close()

        soup = BeautifulSoup(content, "html.parser")
        jobs = []
        seen_titles = set()

        for tag in soup.find_all(["a", "li", "h2", "h3", "h4", "span", "div"]):
            text = tag.get_text(strip=True)
            if len(text) < 10 or len(text) > 200:
                continue
            if title_matches(text) and text not in seen_titles:
                seen_titles.add(text)
                href = tag.get("href", "") if tag.name == "a" else ""
                if href and not href.startswith("http"):
                    from urllib.parse import urljoin
                    href = urljoin(career_url, href)
                jobs.append({
                    "id": f"{company_name}::{text}",
                    "company": company_name,
                    "title": text,
                    "location": "See listing",
                    "url": href or career_url,
                    "posted": "",
                    "source": "playwright",
                })
        return jobs
    except Exception:
        return []


def scan_company(company: dict) -> list[dict]:
    name = company["name"]
    ats = company.get("ats", "")
    ats_id = company.get("ats_id", "")
    career_url = company.get("career_url_scrape") or company.get("career_url", "")

    if ats == "greenhouse" and ats_id:
        jobs = get_greenhouse_jobs(ats_id, name)
        if jobs is not None:
            return jobs

    if ats == "lever" and ats_id:
        jobs = get_lever_jobs(ats_id, name)
        if jobs is not None:
            return jobs

    if ats == "ashby" and ats_id:
        jobs = get_ashby_jobs(ats_id, name)
        if jobs is not None:
            return jobs

    # Workday and others: try HTML scrape first, then Playwright
    if career_url:
        jobs = scrape_jobs_html(career_url, name)
        if jobs:
            return jobs
        jobs = scrape_jobs_playwright(career_url, name)
        return jobs

    return []


def build_job_key(job: dict) -> str:
    return f"{job['company']}::{job['id']}"


def send_email(subject: str, html_body: str, text_body: str):
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        print("WARNING: Gmail credentials not set. Skipping email.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = ALERT_EMAIL

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, ALERT_EMAIL, msg.as_string())


def build_jobs_email(new_jobs: list[dict]) -> tuple[str, str]:
    run_date = datetime.now().strftime("%B %d, %Y")
    subject = f"Job Alert: {len(new_jobs)} new Product Marketing role(s) — {run_date}"

    by_company = {}
    for job in new_jobs:
        by_company.setdefault(job["company"], []).append(job)

    html_rows = ""
    text_rows = ""
    for company, jobs in sorted(by_company.items()):
        for job in jobs:
            posted = f" · Posted {job['posted']}" if job["posted"] else ""
            loc = job["location"] or "Remote"
            html_rows += (
                f'<tr>'
                f'<td style="padding:8px 12px;border-bottom:1px solid #eee;font-weight:600">'
                f'<a href="{job["url"]}" style="color:#2563eb;text-decoration:none">{job["title"]}</a></td>'
                f'<td style="padding:8px 12px;border-bottom:1px solid #eee">{company}</td>'
                f'<td style="padding:8px 12px;border-bottom:1px solid #eee;color:#555">{loc}{posted}</td>'
                f'</tr>\n'
            )
            text_rows += f"• {job['title']} @ {company}\n  {loc}{posted}\n  {job['url']}\n\n"

    html_body = f"""
<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;max-width:800px;margin:0 auto;padding:20px;color:#333">
  <h2 style="color:#1e3a5f;margin-bottom:4px">Product Marketing Job Alert</h2>
  <p style="color:#666;margin-top:0">{run_date} · {len(new_jobs)} new role(s) found</p>
  <table style="width:100%;border-collapse:collapse;margin-top:16px">
    <thead>
      <tr style="background:#f0f4f8">
        <th style="padding:10px 12px;text-align:left;font-size:13px;color:#555">Role</th>
        <th style="padding:10px 12px;text-align:left;font-size:13px;color:#555">Company</th>
        <th style="padding:10px 12px;text-align:left;font-size:13px;color:#555">Location · Date</th>
      </tr>
    </thead>
    <tbody>
{html_rows}
    </tbody>
  </table>
  <p style="margin-top:24px;font-size:12px;color:#999">
    Monitoring {len(json.loads(COMPANIES_FILE.read_text()))} confirmed-remote companies ·
    Runs every Monday and Wednesday via GitHub Actions
  </p>
</body>
</html>
"""

    text_body = f"Product Marketing Job Alert — {run_date}\n{'='*50}\n\n{text_rows}"
    return subject, html_body, text_body


def send_error_alert(error_summary: str):
    subject = f"[JOB MONITOR ERROR] {datetime.now().strftime('%Y-%m-%d')}"
    body = (
        f"The job monitor encountered errors during its run on {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}.\n\n"
        f"{error_summary}\n\n"
        "Check the GitHub Actions run log for details:\n"
        "https://github.com/greggwilliammiller/job-monitor/actions"
    )
    try:
        send_email(subject, f"<pre>{body}</pre>", body)
    except Exception as e:
        print(f"Failed to send error alert: {e}")


def main():
    print(f"Starting job monitor at {datetime.now().isoformat()}")
    print(f"First run: {IS_FIRST_RUN}")

    companies = json.loads(COMPANIES_FILE.read_text())
    seen_jobs = load_seen_jobs()

    new_jobs = []
    errors = []
    scan_count = 0

    for company in companies:
        name = company["name"]
        try:
            found = scan_company(company)
            scan_count += 1
            for job in found:
                key = build_job_key(job)
                if key not in seen_jobs:
                    new_jobs.append(job)
                    seen_jobs[key] = {
                        "title": job["title"],
                        "company": job["company"],
                        "url": job["url"],
                        "first_seen": datetime.now().strftime("%Y-%m-%d"),
                    }
            if found:
                print(f"  {name}: {len(found)} match(es)")
            else:
                print(f"  {name}: 0 matches")
        except Exception as e:
            err_msg = f"{name}: {type(e).__name__}: {e}"
            errors.append(err_msg)
            print(f"  ERROR {err_msg}")

    save_seen_jobs(seen_jobs)

    print(f"\nScanned {scan_count}/{len(companies)} companies")
    print(f"New jobs found: {len(new_jobs)}")
    print(f"Errors: {len(errors)}")

    if new_jobs:
        subject, html_body, text_body = build_jobs_email(new_jobs)
        try:
            send_email(subject, html_body, text_body)
            print(f"Job alert sent: {subject}")
        except Exception as e:
            errors.append(f"Email send failed: {e}")
            print(f"Failed to send job alert: {e}")
    else:
        print("No new matching jobs found. No email sent.")

    if errors:
        error_pct = len(errors) / len(companies) * 100
        # Only alert if more than 10% of companies errored (some will always fail)
        if error_pct > 10:
            error_summary = f"{len(errors)} of {len(companies)} companies failed ({error_pct:.0f}%):\n\n"
            error_summary += "\n".join(f"  • {e}" for e in errors)
            send_error_alert(error_summary)
            print(f"Error alert sent ({error_pct:.0f}% failure rate)")

    if errors:
        print("\nAll errors:")
        for e in errors:
            print(f"  • {e}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        tb = traceback.format_exc()
        print(f"FATAL ERROR:\n{tb}")
        send_error_alert(f"Fatal unhandled exception:\n\n{tb}")
        sys.exit(1)
