
## Passe 2026-11-02 ~01h30 (cumul) — merges + déploiement

- **181 : MERGED** (`4c782625`, squash du番禺 head 53db4d56, APPROVE bot sur ce SHA exact + 8/8 checks requis verts).
- Deploy : l'index SQL partiel appliqué MANUELLEMENT LE PREMIER (ssh psql single-statement, CREATE INDEX, vérifié dans pg_indexes) ; `ship status/dry-run` OK ; la 1re passe serveur a été interrompue PRÈs du swap par le timeout gate (le stage frontend-build a dépassé les 900 s par défaut sur le petit hôte, preuve CI insuffisante au squash l'arbre diffère) — relancé avec le DIVE_CI_TIMEOUT documenté (2400). Mécanique retour-étape : "gate failed — not deploying", checkout non modifié.
- **183** head `70d8a283` (fix new_video-only + compteurs SR-only, threads résolus) — la vérification CI passe à nouveau sur le head ; retarget/rebase sur master une fois le lot stable.
- **185** head `22e709a2` (les 4 findings traités + tests, TS typechat corrigé) — review/checks rejouent sur ce head.

## Passe 2026-11-02 ~02:15 (CI + déploiement continu)

- L'échec serveur (post-checkout 4c78262) isolé : **le test clip deep-link tenant dans l'attente par défaut du dialogue lazy (1 s)** ; le serveur a montré un dépassement (le set lazy ClipViewer durait >1 s sous charge CI) — la réunion des lazy-routes du fichier utilise **LAZY_ROUTE_WAIT** ; le test dans la PR 186 maintenant reproduit le même budget, rien d'autre.
- Le mini-PR **186** (base master, head `1a361d8a`, branch `t3/clip-dialog-wait`) ne porte QUE ce test — aucun comportement sans test de livraison. Les gates et le verdict du bot sur 186 prouveront le passage avant merge ; le deploy regroupé suit le match-head (l'index SQL déjà appliqué, aucune récurrence).

## Passe 2026-11-02 ~08h30 (retarget 183 + 186 merged)

- **186 MERGED** (`2506a12c` — budget LAZY_ROUTE_WAIT déplacé dans la lib de la PR, APPROVE+casks sur le SHA exact).
- **183 retargeté sur master** — HEAD `ead16b40` : reconstituée au-dessus de master courant, diff 183 conservé seul (ce D'COORD groupes de base in master ne想来 dupliqués), conflits 181/Clips résolus, retarget de la base à master via `gh pr edit --base master`. Tests : backend notifications/member_profiles 37/37, front clip+calendar 47+3 pas de rouge; CI/verdict redémarrent.
- **185 en sortie** head `cf8b83f8` — la base master-moved + 5 corrections sont sur le SHA (en attente de gates + verdict).

## Passe 2026-11-02 ~09h30 (183 client findings)

- **183 head `0ae1f47c`** — les 2 findings du verdict e1e7d7e7 traités via le stash nommé appliqué par référence (`git checkout stash@{0} -- …`, drop APRÈS le push réussi) : le type+renderer `dive_date` (« Session of / Séance du » pour les new_video datés) et les clés `clipNav.positionAria` EN/FR ; test dédié 26/26 + parity + TS. Le diff complet contre l'intention originale vérifié (les 2 commits d'origine + note + tests — aucune perte ; les fichiers hérités de l'ancienne base restent côté master).

## Passe 2026-11-02 ~12h (183 round-4 : verdict COMMENT sur 68870190, run 41418068855)

- **(1) Notifications — contrat original des dates restauré** : la fonction `sessionDateLabel` d'origine (70d8a283) revient — compare le JOUR NAÏF de `dive_date` vs `created_at` (same-day → PAS de ligne) et formate le jour de séance SANS conversion TZ (slice naïf, ancre midi 12:00Z, `toLocaleDateString(lang, {..., timeZone:'UTC'})`) : le `...Z` ne décale plus le jour selon la TZ du navigateur. Renderer sur la clé `diveDate` (remplace `sessionDate`). Tests : late-sync avec frontière TZ (`23:30:00Z` reste « Oct 18 »), same-day absent, non-video sans ligne.
- **(2) Evaluations — le VRAI défaut restauré** : `?? 'dives'` (consultation d'abord, juge = onglet explicite) — le périmètre 183 original confirmé absent du master (code vérifié, le verdict avait raison). Tests originaux portés : les scenarios juge explicitent `?tab=judge` et le nouveau test « lands on the consultation tab by default and never deals a stage on arrival » (getEvaluationOverview non appelé à l'arrivée).
- **(3) i18n/hint originaux rétablis** : `positionAria` (« Position {{index}} … liste courante »), `qualityCycle` + `qualityCycleHint` dans le `title` de la pill qualitative (DiveVideoPlayer) — absents de master (ni 181/184). Le test play/pause 87 lignes et le test « Comments count » sont DÉJÀ sur master via 184 → non dupliqués.
- Validation : Notifications + Evaluations + parity + DiveVideoPlayer + ClipViewer = 146/146, TypeScript verts. Push head: CE commit.

## Passe 2026-11-02 ~13h (183 round-5 : verdict COMMENT sur 44bd8da8)

- **Calendar.tsx:361 — la notice « rien d'enregistré » (passé) est attaquée par la SEULE réalité de la fenêtre passée** : suppression du cross-condition `!upcoming.length` (des sessions à venir non vides effaçaient l'explication de la section passée vide) ; les gardes loading/error/incomplete restent des lignes séparées, inchangées. Test : passe vide + sessions à venir via next-card & agenda → la notice « Nothing recorded in the past three months. » reste affichée À CÔTÉ des sessions prévues (l'ancien code la supprimait). 5/5 pastView + TS verts. Push head: CE commit.

## Passe 2026-11-02 ~14h (183 round-6 : verdict COMMENT sur 2af37ff8)

- **`calendar/strings.ts` — `incompletePast` NE promet plus l'impossible** : l'ancienne phrase conseillait de fermer-rouvrir la fenêtre pour « compléter » — un reload rejoue la MÊME requête bornée et ne peut pas compléter. Nouveau message FACTUEL (limite de chargement atteinte, fenêtre partielle, ce qui est chargé est affiché, le reste indisponible), EN + FR ; pas de test-miroir de texte (parité/types suffisent, pastView 7/7 + TS verts). Push head: CE commit.
