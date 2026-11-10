# Tool catalog

The registry exposes 14 tools:

| Tool | Purpose | Source / behavior |
|---|---|---|
| resolve_ticker | Ticker to CIK/name | SEC ticker map |
| sec_company_facts | Raw company XBRL facts | SEC EDGAR |
| sec_filings | Recent filings | SEC submissions |
| financial_snapshot | Latest supported reported facts | SEC companyfacts |
| price_history | Daily price observations | Yahoo chart endpoint |
| technical_summary | Return, volatility, drawdown | Calculated from closes |
| company_profile | Profile and market cap | Optional Finnhub |
| macro_series | Macro observations | Optional FRED |
| news_search | Recent article metadata | Optional NewsAPI |
| memory_search | Search prior evidence | SQLite |
| memory_write | Persist evidence | SQLite |
| calculate_financial_ratio | Transparent arithmetic | Deterministic |
| compare_entities | Group evidence by issuer | Deterministic |
| source_health | Configured integration status | Local configuration |

Provider coverage, licensing, quotas, and availability can change. Check upstream terms before production use. Yahoo Finance's chart endpoint is an unofficial integration and may change without notice. SEC requests must use a valid User-Agent and respect SEC fair-access guidance.
