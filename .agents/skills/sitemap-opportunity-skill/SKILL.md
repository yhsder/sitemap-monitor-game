---
name: sitemap-opportunity-radar
description: Daily sitemap demand report: one date, each diff/YYYYMMDD site on its own, one reports/YYYYMMDD/index.html. Use when asked for that day's new user demands from sitemap diffs.
---

# Sitemap Opportunity Radar

## Goal
Write one **snapshot** for one date: `reports/YYYYMMDD/index.html`. A snapshot says which user tasks show up in that day's sitemap diff. Quote `page_id`s from the prepared file, and mark each demand `observed` or `inferred`. User-facing prose is Chinese.

Read every `diff/YYYYMMDD/*.json`. Each file is a UTF-8 URL list, one URL per line. Each site keeps its own demands. A theme that shows up on more than one site goes in `cross_site_themes`.

`latest/` sits next to `diff/` and is easy to open. This run reads `diff/YYYYMMDD/*.json`.

## Input
- The repo root is the checkout that contains `diff/`. Use the `YYYYMMDD` the user names. When the user names no date, use the latest dated directory under `diff/`.
- Take every file in that directory, including a site with one URL.
- An unreadable file is a site record with `error` and an empty `pages` list. Continue with the other files.

## Workflow

1. **Prepare.** From the repo root, run `python .agents/skills/sitemap-opportunity-skill/scripts/prepare_daily.py --date YYYYMMDD --repo . --output reports/YYYYMMDD/prepared.json`.
   Done when the command exits 0 and `reports/YYYYMMDD/prepared.json` exists. When the command exits non-zero, the result is that error. Use this file's `page_id` and `page_type` as the page identity and class.

2. **Analyze one site.** Cluster that site's `pages[]` by the task the user wants done and the result they expect. For a site with more than 80 pages, batch 40–80 pages that share similar slugs, then merge the batches inside that same site.
   Keep one demand per distinct task. A logo generator and a logo animation are two demands. Pages about one model family may share a heading; each distinct operation is its own demand.
   A tool page, a tutorial, and a template may support the same task and keep their own `page_type`.
   Generic navigation and community room lists belong to a `platform_update` demand. An unclear slug goes in `uncertain_page_ids`.
   A site with `error` is done with `demands: []` and `uncertain_page_ids: []`.
   Done when every `page_id` is in exactly one demand or in `uncertain_page_ids`, and those ids together number `canonical_page_count`.

3. **Write each demand** with `id`, `name`, `category`, `summary`, `audience`, `job_to_be_done`, `page_ids`, `signal`, `confidence`, `opportunity`, `caveats`, and `evidence`. `id` stays a latin slug. `signal` is a short label such as 工具上线, 教程系列, or 模板簇.
   - `category`: `tool`, `trend_template`, `model_api`, `content_strategy`, `platform_update`, `other`. `platform_update` is site chrome. `content_strategy` is a tutorial or editorial series. `trend_template` is one visual task.
   - `confidence`: `high`, `medium`, `low`. For `inferred`, use `medium` or `low`.
   - `opportunity`: `worth_researching`, `watch`, `low_priority`
   - `evidence`: `observed` or `inferred`. `inferred` means the slug is the only source; say so in `caveats`.
   Done when every demand includes every field above.

4. **Open a page when one slug still has two plausible readings.** Open one representative URL for that demand. Set that demand's `evidence` to `observed` and record the opened URL in `caveats`. Set every other demand to `inferred`.
   Done when every demand is `observed` or `inferred`, and each `observed` caveat contains the URL that was opened.

5. **Summarize.** Begin when every site meets the step 2 count. Write `highlights` as `{site, demand_id, reason}` and `cross_site_themes` as `{name, sites, demand_ids, description}`. Each theme `demand_id` belongs to one of that theme's sites. Rank independently buildable tools and distinctive video tasks first. The overview prints the page URL of every cited demand under 数据源.
   Save `reports/YYYYMMDD/analysis.json` with `date`, `sites`, `cross_site_themes`, `highlights`, and `notes`. Copy each prepared site, its count fields, and its `pages` unchanged, then add `demands` and `uncertain_page_ids`. A site with no demand keeps `demands: []` and its pages. `notes` says this is a one-day sitemap snapshot. The analysis JSON is pipeline state.
   Done when the set of `site` values equals the prepared file, including records with `error`, and every site still meets the step 2 count.

6. **Render.** Run `python .agents/skills/sitemap-opportunity-skill/scripts/render_daily.py --input reports/YYYYMMDD/analysis.json --output reports/YYYYMMDD/index.html`.
   The user-facing report is that HTML file. One date is one directory.
   Done when the command exits 0.
