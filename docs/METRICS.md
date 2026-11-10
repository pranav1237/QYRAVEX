# Metrics dictionary

The runtime emits 32 named metrics:

1. tool_calls  2. tool_successes  3. tool_failures  4. tool_retries  5. tool_timeouts
6. cache_hits  7. cache_misses  8. plan_steps  9. completed_steps  10. skipped_steps
11. evidence_count  12. unique_sources  13. fresh_evidence_ratio  14. source_coverage
15. conflict_count  16. resolved_conflicts  17. unresolved_conflicts  18. mean_confidence
19. low_confidence_claims  20. unsupported_claims  21. report_latency_seconds
22. planning_latency_seconds  23. synthesis_latency_seconds  24. tokens_estimated
25. fallback_count  26. provider_degradations  27. memory_reads  28. memory_writes
29. retrieval_hits  30. retrieval_misses  31. citation_completeness  32. entity_coverage

Metrics not populated by a given execution path remain zero rather than being inferred. An unimplemented counter must not look like a measured success. Evidence freshness currently uses a 30-day threshold and should be interpreted relative to the research question.
