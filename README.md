# Job Monitor

Monitors career pages of 161 confirmed-remote companies for VP / Sr. Director of Product Marketing roles. Runs automatically every Monday and Wednesday via GitHub Actions and sends email alerts for new postings.

## Setup

### 1. Create a new GitHub repository

```bash
cd job-monitor
git init
git add .
git commit -m "Initial job monitor setup"
gh repo create greggwilliammiller/job-monitor --private --push --source .
```

### 2. Create a Gmail App Password

1. Go to your Google Account → **Security** → **2-Step Verification** (must be enabled)
2. At the bottom of the 2-Step Verification page, click **App passwords**
3. Select "Mail" + "Other (Custom name)" → type "Job Monitor" → **Generate**
4. Copy the 16-character password shown

### 3. Add GitHub Secrets

In your new repository:
1. Go to **Settings → Secrets and variables → Actions**
2. Click **New repository secret** and add:
   - `GMAIL_USER` — your full Gmail address (e.g. `greggwilliammiller@gmail.com`)
   - `GMAIL_APP_PASSWORD` — the 16-char app password from step 2

### 4. Trigger the first run manually

1. Go to **Actions** tab in your GitHub repo
2. Click **Job Monitor** → **Run workflow**
3. Set "Force first-run mode" to `true` to receive all currently posted matching jobs in the first email
4. Click **Run workflow**

After that, the monitor runs automatically every Monday and Wednesday at 9:00 AM UTC (5:00 AM ET).

## How it works

- **ATS-first**: Checks Greenhouse, Lever, and Ashby JSON APIs directly — fast and reliable
- **HTML fallback**: BeautifulSoup scraper for Workday and custom pages
- **Playwright fallback**: Headless browser for JavaScript-rendered pages
- **State persistence**: `seen_jobs.json` is committed back to the repo after each run so jobs are never re-alerted
- **Error alerting**: If more than 10% of companies fail to scan, an error alert is emailed
- **Title matching**: Flexible regex covers VP, Vice President, Sr. Director, Senior Director, Head of, and PMM abbreviations

## Title patterns matched

- VP of Product Marketing / Vice President of Product Marketing
- Sr. Director / Senior Director of Product Marketing
- Head of Product Marketing
- Director of Product Marketing (included as a near-match)
- VP/Sr. Director of PMM
- Principal Product Marketing (included as emerging-level near-match)

## Manual run

```bash
pip install -r requirements.txt
playwright install chromium

export GMAIL_USER="greggwilliammiller@gmail.com"
export GMAIL_APP_PASSWORD="your-app-password"

python job_monitor.py
```

Set `FORCE_FIRST_RUN=true` to treat all found jobs as new (useful for initial run):

```bash
FORCE_FIRST_RUN=true python job_monitor.py
```
