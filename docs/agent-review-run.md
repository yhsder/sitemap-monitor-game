# Agent Review Run

`Agent Review Run` is a Codex-guided SERP review workflow for finding opportunity candidates from the current day's sitemap diff.

## Trigger

The user can trigger the workflow with a natural language request such as:

```text
跑今天的 SERP Review
```

## Input

- Read only `diff/YYYYMMDD/*.json` for the current date.
- If the current day's diff directory does not exist, stop and report that there is no diff for today.
- Do not automatically fall back to a previous date during a formal run.

## Research Keyword Derivation

- Derive the research keyword from the URL first.
- Use page metadata, title, or h1 only when the URL is unclear.
- Prioritize tool and landing page URLs.
- De-emphasize or skip blog, news, announcement, account, legal, auth, pricing, API, and static asset paths.
- De-duplicate equivalent keywords before browser review.

## Browser Review

- Use the user's Chrome browser so the SiteData extension can inject visible SERP metrics.
- Search Google for each research keyword.
- Read the top 10 natural results and their visible SiteData signals.
- Stop rather than bypassing CAPTCHA or browser safety interstitials.

## Candidate Rules

Create an opportunity candidate when a result matches either rule:

- `domain_age <= 1 year`
- `DR <= 30`

If both rules match, treat the candidate as higher priority.

## Limits

- Default review limit: `100` research keywords per run.
- The user may ask for a smaller or larger limit for a specific run.

## Output

- Append confirmed matches to `research/candidates.jsonl`.
- Also summarize the run in chat.
- Do not write candidates directly to `config.yaml`.
- Do not save screenshots by default.

## Candidate Record

Each candidate should include:

- `reviewed_at`
- `source_type`
- `source_site`
- `source_url`
- `research_keyword`
- `google_url`
- `result_rank`
- `result_title`
- `result_domain`
- `result_url`
- `dr`
- `domain_created_at`
- `domain_age_days`
- `matched_reasons`
- `status`

## De-Duplication

- De-duplicate by `research_keyword + result_domain`.
- Keep the same result domain for different research keywords, because that can indicate broader opportunity coverage.
