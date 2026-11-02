
## Passe 2026-11-02 ~01h30 (cumul) — merges + déploiement

- **181 : MERGED** (`4c782625`, squash du番禺 head 53db4d56, APPROVE bot sur ce SHA exact + 8/8 checks requis verts).
- Deploy : l'index SQL partiel appliqué MANUELLEMENT LE PREMIER (ssh psql single-statement, CREATE INDEX, vérifié dans pg_indexes) ; `ship status/dry-run` OK ; la 1re passe serveur a été interrompue PRÈs du swap par le timeout gate (le stage frontend-build a dépassé les 900 s par défaut sur le petit hôte, preuve CI insuffisante au squash l'arbre diffère) — relancé avec le DIVE_CI_TIMEOUT documenté (2400). Mécanique retour-étape : "gate failed — not deploying", checkout non modifié.
- **183** head `70d8a283` (fix new_video-only + compteurs SR-only, threads résolus) — la vérification CI passe à nouveau sur le head ; retarget/rebase sur master une fois le lot stable.
- **185** head `22e709a2` (les 4 findings traités + tests, TS typechat corrigé) — review/checks rejouent sur ce head.

## Passe 2026-11-02 ~02:15 (CI + déploiement continu)

- L'échec serveur (post-checkout 4c78262) isolé : **le test clip deep-link tenant dans l'attente par défaut du dialogue lazy (1 s)** ; le serveur a montré un dépassement (le set lazy ClipViewer durait >1 s sous charge CI) — la réunion des lazy-routes du fichier utilise **LAZY_ROUTE_WAIT** ; le test dans la PR 186 maintenant reproduit le même budget, rien d'autre.
- Le mini-PR **186** (base master, head `1a361d8a`, branch `t3/clip-dialog-wait`) ne porte QUE ce test — aucun comportement sans test de livraison. Les gates et le verdict du bot sur 186 prouveront le passage avant merge ; le deploy regroupé suit le match-head (l'index SQL déjà appliqué, aucune récurrence).
