# Separate opportunity candidates from monitored sites

Opportunity candidates are stored in `research/candidates.jsonl` instead of being written directly to `config.yaml`. The sitemap monitor should only track human-approved monitored sites, while SERP review can append candidate findings for later review; this keeps noisy or uncertain SERP signals from automatically changing the monitored site configuration.

SERP review starts from the current day's newly discovered URLs, not the full latest sitemap snapshots. The first version prioritizes tool and landing page URLs and de-emphasizes blog, news, announcement, account, legal, and other non-landing-page paths to reduce noisy research work.
