# Repository Guidelines

## Project Structure & Module Organization
`main.py` contains the sitemap fetching, parsing, diffing, cleanup, and Feishu notification flow. `config.yaml` defines monitored sites, sitemap crawl limits, and notification settings. `latest/` stores the current full URL snapshot for each site as `<site>.json`. `diff/YYYYMMDD/` stores newly discovered URLs by day. Automation lives in `.github/workflows/sitemap-check.yml`.

## Build, Test, and Development Commands
Install runtime dependencies manually because `requirements.txt` is not checked in:

```bash
python -m pip install --upgrade pip
pip install requests beautifulsoup4 python-dateutil pyyaml lxml cloudscraper
```

Run the monitor locally with:

```bash
python main.py
```

This reads `config.yaml`, updates `latest/`, and writes new entries into `diff/<YYYYMMDD>/`.

## Coding Style & Naming Conventions
Use Python with 4-space indentation, `snake_case` for functions and variables, and short helper functions like `parse_xml` or `collect_urls`. Keep changes localized to `main.py` unless the workflow or configuration format must change. Prefer standard library modules first, keep logging messages explicit, and avoid adding new abstractions unless duplication is real.

## Testing Guidelines
No automated test suite is committed today. Validate changes by running `python main.py` with safe config edits and checking:

- `latest/<site>.json` is refreshed without malformed URLs
- `diff/<YYYYMMDD>/` only contains newly added URLs
- logs show graceful handling for HTML responses, bad sitemap files, and request failures

If you add tests, place them under `tests/` and name them `test_<behavior>.py`.

## Commit & Pull Request Guidelines
Recent history shows two commit styles: automated data updates such as `📦 Update sitemap data: 2026-06-30`, and short manual maintenance commits such as `skills update`. For code changes, prefer concise imperative messages like `fix sitemap index parsing` or `add timeout guard for html responses`.

Pull requests should include the purpose of the change, the config or sites affected, a short validation note, and sample output paths when behavior changes data generation.

## Security & Configuration Tips
Do not commit real Feishu webhook secrets in `config.yaml`. Treat `latest/` and `diff/` as generated artifacts; review them carefully before merging changes that alter parsing or deduplication behavior.

## Agent skills

### Issue tracker

本仓库的 issues 和 PRDs 使用 `.scratch/` 下的本地 markdown 文件管理。External PRs 不是 triage surface。详见 `docs/agents/issue-tracker.md`。

### Triage labels

本仓库使用默认的 triage label vocabulary：`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`。详见 `docs/agents/triage-labels.md`。

### Domain docs

本仓库使用 single-context 的 domain docs 布局。详见 `docs/agents/domain.md`。
