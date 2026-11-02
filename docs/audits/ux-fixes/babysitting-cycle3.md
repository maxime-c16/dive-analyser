
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
