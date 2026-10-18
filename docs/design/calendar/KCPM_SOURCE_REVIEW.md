# KCPM pilot source review — 18 October 2026

Prepared, not loaded into the application. This review and the latest-user-decisions section in IMPLEMENTATION_PLAN.md supersede earlier fixture assumptions.

## Club and venues

KCPM = Kingfisher Club Plongeon Montreuil, a leisure/competition diving club affiliated with FFN according to its club-managed page: https://www.helloasso.com/associations/kingfisher-club-plongeon-montreuil-kingfisher-plongeon-montreuil . Do not infer current staff/manager authorization from old directories.

SNMT is proposed as Stade nautique Maurice Thorez, 21 rue du Colonel Raynal, Montreuil, verified with the operator https://www.est-ensemble.fr/stade-nautique-maurice-thorez-montreuil . The PDFs only say SNMT; preserve this source label and confirm the mapping before import approval. INSEP is preserved as supplied, with exact entrance/access instructions awaiting club confirmation. Municipal public-opening hours are not club training hours and must not overwrite the PDFs.

## Schedules

Two one-page PDFs visually inspected. Each contains 58 dated two-hour sessions, totaling 116: 33 at INSEP and 83 at SNMT. Beginners: 8 September 2026–19 June 2027. Advanced: 15 September 2026–19 June 2027. Weekdays checked against each date; local times converted with Europe/Paris (including DST). Dates are not a simple fixed weekly schedule; group alternation, different Saturday times and breaks must be imported exactly. PDF group names come from user attachment filenames; no roster or coach identity is supplied.

## Workbook

Three sheets: competitions, category details, useful links. 40 titled competition candidates, 14 useful-resource entries, original cell values and hyperlink targets preserved. Formatting extends beyond populated rows; blank formatted rows are not events. Ten date rows require review by the conservative parser (missing year/date, complex cross-month dates, malformed/reversed ranges). Historical competitions remain history; do not turn them into current fixtures. Dates without time stay all-day/date-only, not invented timed appointments.

Specific items:
- Competition row 44 has year 20267; keep raw value and request correction, no silent guess.
- Row 54 has reversed range 25–17 November 2027. Organizer GBDF currently states Edinburgh 26–28 November 2027: https://www.diving-gbdf.com/ . Propose this as a reviewed correction.
- GBDF also confirms Southend 13–15 November 2026 and Manchester 16–18 April 2027, consistent with supplied meet ranges. Training vs competition day detail in the workbook still needs the event information pack to verify.
- World Aquatics confirms Budapest Masters diving 5–10 July 2027, consistent with row 53: https://www.worldaquatics.com/masters/latest/ . This verifies diving dates, not registration deadlines.
- Rows 38/39 are undated titles; hold outside the public agenda until reconciled. Row 60 is a 2029 entry with no full date/location.
- The category sheet references 2023/2024 regulations and contains overlapping-looking age labels (40–45 / 45–49). Preserve as historical source material, not validated current eligibility or scoring rules.
- WhatsApp invite URLs grant group access; keep them club-only and out of documentation/public previews. No messages sent or groups joined.

## Refresh investigation

Organizer pages are readable; GBDF dates and World Aquatics discipline dates can be checked. FFN's discipline-specific calendar exists at https://ffn.extranat.fr/webffn/calendrier.php?idact=pl . Browsing returned older cached months, so no current complete federal import or API/ICS availability is established. LIF search exposes previous-season diving documents; do not substitute a swimming calendar or old season for current diving dates.

The attached XLSX/PDFs are snapshots. No live upstream workbook URL is needed for the selected design. User explicitly chose the embedded resource/organizer links as upstream sources; do not request or depend on the original shared spreadsheet. Do not assume Google Doc links inside meet rows are the source workbook. A refresh feature must store source status, compare versions, respect overrides and queue ambiguous differences for curator review. No automatic refresh has been installed.

## Handoff

Reader script and plan are source code/documentation. Raw files, bundle and future source versions are private runtime data under ignored reports/calendar/kcpm-2026-2027/ for this checkout; application implementation must move/import them into persistent private application storage/PostgreSQL and verify backup coverage. Do not remove this worktree before that transfer. No club members or permissions have been invented or changed.

## Confirmed access and V1 response rules

Club signup selection grants immediate club membership. Members see only their assigned training-group calendar; coaches see both. Club membership does not assign a group or grant staff powers. Capacity and waiting lists are deferred; responses express interest without reserving places. Investigate the embedded links as independent source adapters, not the original table as a synchronization source.
