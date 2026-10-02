# BLS Data Automation — OEWS Wages

Pulls wage data from the U.S. Bureau of Labor Statistics (BLS) **Occupational
Employment and Wage Statistics (OEWS)** program and refreshes it automatically
once a year with GitHub Actions.

It produces two views of the same survey:

- **By occupation** (SOC codes) — one national mean wage per occupation.
- **By industry** (NAICS codes) — one national mean wage per industry, plus a
  complete 6-digit grid and a government table.

Everything comes from the [BLS Public Data API](https://www.bls.gov/developers/).
No manual file downloads are required.

---

## Outputs

All results are written to the [`outputs/`](outputs/) folder:

| File | Rows | What it is |
|------|------|------------|
| `soc_wages.csv` | ~825 | Occupation (SOC) code, title, annual mean wage |
| `naics_wages.csv` | ~286 | Industries BLS actually published, at 4/5/6-digit (mixed) |
| `naics_6digit_wages.csv` | ~983 | **Every** 6-digit NAICS code, wage backfilled from parents |
| `government_wages.csv` | 4 | Government wages (OEWS `999` codes: Federal / State / Local / All) |

Each file has `code`, `title`, `wage`. The 6-digit file adds two provenance
columns — `wage_source_level` and `wage_source_naics` — see below.

---

## How it works

### `oews_soc.py` — occupation wages

1. Reads the occupation code list from `soc_codes.csv`.
2. Builds a BLS series ID per occupation:
   `OEUN0000000000000<soc>04`
   (national, all industries, `<soc>` = 6-digit occupation code, `04` = mean wage).
3. Queries the API in batches of 50 series, parses the response, and writes
   `outputs/soc_wages.csv`.

### `oews_naics.py` — industry wages

1. Reads the full NAICS code list (all levels) from `2022_NAICS_Structure (1).csv`.
2. Builds a series ID per industry:
   `OEUN0000000<naics6>00000004`
   (`<naics6>` = NAICS code right-padded to 6 digits, all occupations, `04`).
3. Queries the API at the **3, 4, 5, and 6-digit** levels and builds a wage lookup.

It then produces three files:

- **`naics_wages.csv`** — the raw published industries (whatever BLS reported,
  at mixed levels). If BLS didn't publish an industry, it simply isn't here.

- **`naics_6digit_wages.csv`** — a complete grid of every 6-digit NAICS code.
  For each code the wage is **backfilled** down the hierarchy:

  ```
  own 6-digit  →  5-digit parent  →  4-digit parent  →  3-digit parent  →  blank
  ```

  `wage_source_level` records which level the wage came from, and
  `wage_source_naics` the exact parent code that supplied it. Example: 6-digit
  `113310` has no OEWS estimate of its own, so it inherits its 4-digit parent
  Logging (`113300`) wage — flagged `wage_source_level = 4-digit`.

- **`government_wages.csv`** — OEWS does not classify government by NAICS, so
  NAICS 92 is excluded from the 6-digit grid and government is reported
  separately under the `999` designation codes (the "including schools,
  hospitals, and USPS" variants).

---

## Repository layout

```
.
├── oews_soc.py                  # occupation (SOC) wages
├── oews_naics.py                # industry (NAICS) wages + 6-digit grid + government
├── requirements.txt             # Python dependencies
├── soc_codes.csv                # INPUT: occupation code list
├── 2022_NAICS_Structure (1).csv # INPUT: all NAICS codes (every level)
├── outputs/                     # all generated CSVs land here
└── .github/workflows/
    └── oews-annual.yml          # the automation (see below)
```

`soc_codes.csv` and `2022_NAICS_Structure (1).csv` are **required inputs** — do
not delete them. Everything in `outputs/` is regenerated on each run.

---

## The automation (GitHub Action)

The workflow [`.github/workflows/oews-annual.yml`](.github/workflows/oews-annual.yml)
refreshes the data without anyone running the scripts by hand.

### When it runs

```yaml
on:
  schedule:
    - cron: '0 12 1 6 *'   # June 1, 12:00 UTC, once a year
  workflow_dispatch: {}     # manual "Run workflow" button
```

- **Scheduled:** every June 1 (after the new OEWS release). Edit the `cron` line
  to change the date.
- **Manual:** Actions tab → *Annual OEWS data pull* → **Run workflow**.

### What it does

Each run (on a GitHub-hosted Ubuntu runner):

1. Checks out the repo.
2. Installs Python + dependencies.
3. Runs `oews_soc.py` (needs the API key).
4. Runs `oews_naics.py` (needs the API key).
5. Commits any changed files in `outputs/` back to the repo as
   `github-actions[bot]` with the message `Annual OEWS refresh (<date>)`.

If the data hasn't changed since the last run, step 5 logs
`No changes to commit` and makes no commit — that's the normal "nothing new yet"
outcome, not an error.

**The output lives in the repo.** After a run, the refreshed CSVs are committed
to `main`; pull the repo to get them locally. (The runner's disk is wiped after
each run — the committed files are the only durable output.)

### Required repo settings

The API key is **not** in the code. Configure these once per repo:

1. **Secret** — Settings → Secrets and variables → Actions → New repository
   secret, named exactly **`BLS_API_KEY`**. The workflow injects it as an
   environment variable; `os.getenv('BLS_API_KEY')` picks it up (same variable
   the local `.env` provides).
2. **Write permission** — Settings → Actions → General → Workflow permissions →
   **Read and write** (so the commit-back step can push).

### Maintenance notes

- **Idle disable:** GitHub disables scheduled workflows after **60 days of no
  repo activity**. For a once-a-year job this *will* trigger unless the repo sees
  commits. If that's a risk, change the `cron` to run monthly (harmless — it just
  re-pulls the latest year and commits only when the data actually changes).
- **Protected `main`:** if the default branch requires pull-request reviews, the
  bot's direct commit will be blocked; the workflow then needs to open a PR
  instead of committing to `main`.
- **New NAICS/SOC vintages:** the code lists (`soc_codes.csv`,
  `2022_NAICS_Structure (1).csv`) are static 2022-vintage files. BLS revises SOC
  (~2028) and NAICS (~2027) on long cycles; swap these files when a new vintage
  is adopted.
