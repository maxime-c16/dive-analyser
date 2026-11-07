# Dive browsing and UI feedback corrections

Evaluation browsing used repeated codes, internal attempt numbers and switches
without enough visual identity. The updated browser combines video preview,
date, code, height and community score. Search and filters cover the complete
owner-scoped collection before fetching a bounded page. Opening a video and
returning preserves the gallery page, filters and focused card.

Requested reviews link to their exact videos. Mobile conversation viewport,
judging progress/recovery, sparse community composition, calendar hierarchy,
primary navigation labels and French/English formatting are also corrected.

## Validation

- Full frontend suite: 980 tests across 118 files passed before the final
  unchanged-query guard; 24 focused tests cover that guard and final small fixes.
- 56 isolated evaluation API tests cover authorization, search, height values,
  aggregate counts, pagination and detail-query growth. Production build passes.
- 60 CI self-tests pass directly. Hosted CI must validate the full gate.
- Browser checks cover desktop and 320px layouts, gallery-to-reader return,
  unsupported-filter reset, requested-video links and narrow member profiles.

## Council review

The prior category scores did not catch concrete findability defects and are
not treated as acceptance. Focused re-check scores were 7/10 from GPT-6.1 Sol
high on the second Codex account, and 6/10 from each Muse 1.3 Contributor xhigh
reviewer. They confirmed the corrected paths while retaining deployment as a
release-verification blocker. A final unchanged-search loading defect, CSS
cascade issue and plural copy were fixed and tested directly afterwards.

## Rollout

Deploy frontend and backend together. No migration, new secret or Mac worker
change is required. After deployment, verify actual automatic previews/dates,
requested dates, full-collection search, combined filters, counts and sorting.
The previous backend does not implement this metadata/filter contract, so local
preview against it cannot establish successful enriched browsing. Physical
Safari keyboard/viewport verification remains deferred.
