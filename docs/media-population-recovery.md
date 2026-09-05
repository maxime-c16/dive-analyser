# Media Population Recovery

Population state and item outcomes are durable on Debian. On interruption:

1. pause the population run;
2. finish or safely fail the current item;
3. verify no active or duplicate media lease;
4. disable `mac-media-01` if Photos or storage is unhealthy;
5. optionally re-enable `mac-media-old` as the sole lease owner;
6. keep catalog rows and completed cache entries;
7. clean only validated DiveSensei temporary roots;
8. resume from the first nonterminal item after gates recover.

Permission errors pause the run and remain retryable. Two consecutive query or
export timeouts pause the run. Placeholder-only exports are asset outcomes and
are not retried immediately. A valid recalled source is reused for rendition
retry instead of downloading again.

Never use retry-all, delete-all, `--delete`, or filesystem cleanup inside the
Photos library.
