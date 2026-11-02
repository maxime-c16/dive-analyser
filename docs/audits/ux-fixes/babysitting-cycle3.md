
## Passe 2026-11-02 ~01h30 (cumul) — merges + déploiement

- **181 : MERGED** (`4c782625`, squash du番禺 head 53db4d56, APPROVE bot sur ce SHA exact + 8/8 checks requis verts).
- Deploy : l'index SQL partiel appliqué MANUELLEMENT LE PREMIER (ssh psql single-statement, CREATE INDEX, vérifié dans pg_indexes) ; `ship status/dry-run` OK ; la 1re passe serveur a été interrompue PRÈs du swap par le timeout gate (le stage frontend-build a dépassé les 900 s par défaut sur le petit hôte, preuve CI insuffisante au squash l'arbre diffère) — relancé avec le DIVE_CI_TIMEOUT documenté (2400). Mécanique retour-étape : "gate failed — not deploying", checkout non modifié.
- **183** head `70d8a283` (fix new_video-only + compteurs SR-only, threads résolus) — la vérification CI passe à nouveau sur le head ; retarget/rebase sur master une fois le lot stable.
- **185** head `22e709a2` (les 4 findings traités + tests, TS typechat corrigé) — review/checks rejouent sur ce head.

## Passe 2026-11-02 ~02:15 (CI + déploiement continu)

- L'échec serveur (post-checkout 4c78262) isolé : **le test clip deep-link tenant dans l'attente par défaut du dialogue lazy (1 s)** ; le serveur a montré un dépassement (le set lazy ClipViewer durait >1 s sous charge CI) — la réunion des lazy-routes du fichier utilise **LAZY_ROUTE_WAIT** ; le test dans la PR 186 maintenant reproduit le même budget, rien d'autre.
- Le mini-PR **186** (base master, head `1a361d8a`, branch `t3/clip-dialog-wait`) ne porte QUE ce test — aucun comportement sans test de livraison. Les gates et le verdict du bot sur 186 prouveront le passage avant merge ; le deploy regroupé suit le match-head (l'index SQL déjà appliqué, aucune récurrence).

## Passe 2026-11-02 ~08h (185 round2)

- **185** head `f9bae848` : les 5 findings du verdict 22e709a2 traités (voir deferred-cycle3.md « Suivi review 2 ») ; le CONFLICT avec master (186 merge) résolu proprement (theirs cycle3-doc seulement); tests back 54/54 + front 35/35 + TS/build → CI/verdict au nouveau SHA.

## Passe 2026-11-02 finale (185 round-3 + 183 verdict round-2)

- **185 head `a1f5033b`** — les 7 findings du verdict cf8b83f8 traités (diverId deps, dénominateur omis en vue diver + clés `cappedPlain`, resume walk qui TIENT l'ancre (ref + tick, régression dédiée qui échoue sur l'ancien code), `depth.anchor` lu (arrêt tôt si atteint / abandon explicite sinon), liveness des walks en vol (trim FIFO y compris pending, stop à la page), facettes hauteurs bornées (limit/partial/after, rétrocompatible), « Recently active » depuis `totals.recent`) ; front 62/62 + back 54/54 + TS/build → CI/verdict sur a1f5033b.
- **183 head `e1e7d7e7`** — les 2 findings du verdict 90961b7a traités : la NOTE IMMUABLE rétablie (notifications-session-date-consult-defaults.json, validate ✅, components frontend+backend) ; l'erreur/chargement passé du calendrier a son état propre (retryable failed + incompletePast, la claim vide n'apparaît qu'après un vrai tableau) + tests pastView étendus. CI e1e7d7e7 : 6/6 SUCCESS (gate/front/back/postgres/review/plan).
- Déploiement : toujours suspendu aux merges restants (183/185) + gates normales ; l'index SQL est déjà appliqué en prod (preuve pg_indexes).

## Passe 2026-11-02 ~09h (185 round-4)

- **185 head `c325799e`** — les 4 findings du verdict a1f5033b traités (dénominateur diver omis, facets keyset-walk client, totals-null honesty, dead-walk no-reinsert) + 4 tests régressifs dont le walk-évincé (échoue sur l'ancien code) ; front 23+21/21, back 40/40, TS/build verts → CI/verdict sur c325799e.

## Point de reprise final du cycle 3 lot (2026-11-02)

- **master = 2506a12c** (181+182+184+186 squash-merged, toutes APPROVE+gates au SHA exact).
- **185** head distant `ed74dcc2` (code c325799e + docs) — CI/verdict à venir (les 4+7 findings traités).
- **183** head `e1e7d7e7` + stash client (dive_date renderer + clipNav.positionAria + tests) à POPPER sur la branche 183 et pousser — CI/verdict ensuite.
- **Déploiement** : après merges 183/185 → `ci/ship.sh status → server --dry-run → server` (index SQL déjà appliqué ; la prod reste sur 31c0695 tant que le ship n'a pas réussi ; DIVE_CI_TIMEOUT=2400 requis côté serveur : le lancer DEPUIS le serveur (ssh inline) car ship.sh n'expédie pas l'env).

## Passe 2026-11-02 ~11h (185 round-6 : REQUEST_CHANGES sur a49b53ad)

- **Verdict** (run 41418744045) : 2 invariants résiduels — (1) `Dives.tsx:828` store `partial:false` pendant tout le walk (échec de continuation → liste bornée affichée comme complète) ; (2) `Community.tsx:63` `page.totals ?? totals` garde les anciens chiffres quand un `totals: null` EXPLICITE arrive sur continuation.
- **Corrigé** : (1) le flag `partial` du serveur est stocké À CHAQUE page (notice visible dès la 1re page bornée, retirée seulement à la page complète) — et le `.catch` de continuation ré-affirme `partial:true` (jamais de downgrade par un échec) ; (2) contrat explicite : `if ('totals' in page) setTotals(page.totals ?? null)` — null explicite EFFACE (bannières count-free, bouton « Load more members » sans chiffre), champ absent garde l'affichage (producteur vérifié : `users.py` sérialise toujours `totals`, null inclus).
- Tests : notice visible dès la 1re page pendant le walk puis retirée à la page complète ; échec de continuation garde la notice ; continuation `totals:null` efface les chiffres des bannières — ancien code rouge sur les trois. 20/20 + typecheck verts. Poussé avec le code de cette passe (CE commit).

## Passe 2026-11-02 ~12h30 (185 round-7 : REQUEST_CHANGES sur b3ec9b9b)

- **Verdict** (run 41421556215) : 2 findings — (1) le cap 1000 s'applique aux résultats `code_prefix` AVANT le filtre exact côté client : un frère de préfixe (201AB) peut évincer les tentatives du code exact ; (2) après un cache HIT frais qui contient déjà l'ancre, `resumeDepth` repart de `nextCursor` (déjà passé l'ancre) → fetch au-delà de la profondeur mémorisée puis scroll jeté.
- **Corrigé (1) serveur + client** : `library_page` (`backend/app/api/v1/dives.py`) expose désormais `dive_code` (match EXACT du filtre déjà présent dans `list_dives`, le scope d'accès inchangé) et le walk passe `dive_code: exact` au lieu de `code_prefix` (client : `codeSummariesApi.ts`) — le fenêtrage borné porte maintenant les SEULES lignes du code. Test backend : 120 × 201AB + 3 × 201A → GET exact ne renvoie QUE 201A (3 lignes, pas de cursor) ; test front : la requête porte `dive_code` et jamais `code_prefix`.
- **Corrigé (2) warm-cache** : dans le `.then` du chargement, si l'ancre mémorisée est DÉJÀ dans les lignes montées (snapshot frais), la reprise NE REJOUE PAS (le `resumeDepth` froid reste borné). Test : cache réensemencé (lignes contenant l'ancre 97 + `nextCursor` p2-new) + workspace {anchor:97, pages:3} → AUCUN appel `/dives/library`, aucun appel avec cursor, scroll restauré (5000) sur les lignes mises en cache — l'ancien code fetch-passait l'ancre puis jettait le scroll (rouge avant).
- Validation : vitest 44/44 (codeSummaries + libraryUx + Dives.cache + Community) + backend 43/43 + TypeScript verts. Push head: CE commit.

## Passe 2026-11-02 ~13h30 (185 round-8 : REQUEST_CHANGES sur 2f038074)

- **Verdict** (run 41423765781) : `CodeAnalysis.tsx:150` — en vue all-divers, quand le summary du code est en attente/échoue, le fallback `items.length` posant comme total de l'historique (un slice borné/période vide affirmait « of 0 »/« of 80 » quand le code dépasse 1000 tentatives).
- **Corrigé** : le dénominateur n'est fourni QUE par le summary CORRESPONDANT au code (`summaries?.find(dive_code === code)?.attempt_count`) — dehors (pending/échec/autre code) il reste INCONNU (`null`) et la notice count-free déjà existante (`cappedPlain`, le title du sample / la note sans chiffre de la branche vide) couvre l'intervalle ; quand le summary arrive, le vrai total (1200) prend la relève. total 0 réel vs Unknown gardés distincts (`?? null` ne neutralise que undefined/null).
- Tests : count-free sur summary pending/mismatché (aucun « of N » visible, wording count-free en title) ; grep période vide + summary absent (donne jamais « of 0 ») ; summary bloqué puis résolu → le dénominateur passe de count-free à « of 1200 » SUR le même montage ; la vue diver continue d'omettre le dénominateur inter-population. 9/9 CodeAnalysis + TS verts. Push head: CE commit.

## Passe 2026-11-02 ~14h30 (185 round-9 : REQUEST_CHANGES sur 04fb83ad)

- **Verdict** (run 41424851092) : sur échec d'une page de reprise, `resumeDepth` renvoie `current:false` → l'ancre pendent garde, mais le `.finally` relâche le hold et l'effet de scroll consomme/écrase l'ancre contre le contenu PARTIEL de page 1.
- **Invariat corrigé (retry borné + discard explicite)** : la lecture de page retente AU PLUS UNE FOIS (même curseur — le précédent 1-retry des route loaders) ; un second échec → `anchorReached:false` explicite (plus jamais le `anchorReached` initialisé à vrai pour ancre null) + error surface ; ET le caller discard l'ancre DÈS QUE `!anchorReached` — échec (après retry) et walk périmé (superseded) également — le clamp ne s'exécute jamais contre un contenu partiel. paths inchangés : walk successuel (tests existants verts) et l'ancre warm-cache (test round-7 vert).

- Tests : (1) reprise p2 rejetée DEUX fois (deferred) → 2 appels p2 (init+retry), alerte d'erreur affichée, scrollTo JAMAIS appelé, aucune ligne fantôme ; (2) p2 rejetée UNE fois → le retry borné sauve la restoration : walk continue jusqu'à p3, ancre 202 re-atteinte, scrollTo restauré sur la depth mémorisée (5000) ; (3) supersession — p2 tenue puis re-filtrage (nouvelle passe page-1) → la walk périmée relâchée NE clamp PAS (scrollTo jamais appelé). 27/27 libraryUx+Dives.cache + TS verts. Push head: CE commit.
