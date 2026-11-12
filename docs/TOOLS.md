# Tool catalog

The registry exposes 14 tools:

| Tool | Purpose | Source / behavior |
|---|---|---|
| resolve_ticker | Ticker to CIK/name | SEC ticker map |
| sec_company_facts | Raw company XBRL facts | SEC EDGAR |
| sec_filings | Recent filings | SEC submissions |
| financial_snapshot | Latest supported reported facts | SEC companyfacts |
| price_history | Daily price observations | Yahoo Finance chart endpoint; Stooq CSV fallback |
| technical_summary | Return, volatility, drawdown | Calculated from closes |
| company_profile | Profile and market cap | Optional Finnhub |
| macro_series | Macro observations | FRED public graph CSV |
| news_search | Aggregated live article metadata | GDELT DOC 2.0 + Google News RSS + Yahoo Finance RSS; optional NewsAPI API key |
| memory_search | Search prior evidence | SQLite |
| memory_write | Persist evidence | SQLite |
| calculate_financial_ratio | Transparent arithmetic | Deterministic |
| compare_entities | Group evidence by issuer | Deterministic |
| source_health | Configured integration status | Local configuration |

News results are merged and deduplicated across available providers, with individual provider failures reported when another source still succeeds. Search indexes do not cover every page on the internet; do not describe results as exhaustive. NewsAPI is optional and requires a key. Stock charts use timestamped daily observations, not tick-by-tick streaming; Yahoo Finance is an unofficial integration and Stooq is the fallback. Provider coverage, licensing, quotas, and availability can change. Check upstream terms before production use. SEC requests must use a valid User-Agent and respect SEC fair-access guidance.
