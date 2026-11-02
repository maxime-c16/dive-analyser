# Babysitting cycle 3 — PRs UX 181/182 (+ lot suivant)

- **Rôle** : sous-agent babysitter (GLM / T3 Code), mandat explicite de Maxime — corrections, reviews, merge puis déploiement serveur vérifié. Pas de sous-agents ; pas de watch/loop : chaque attente est rendue au parent avec un point de reprise.
- **Worktree unique** : `~/.t3-nightly/worktrees/dive-analyser/t3-f3538634`, branches locales `babysit/feedback-reliability` et `babysit/library-ux-state-search` (push explicites vers les branches des PR, têtes préservées, pas de reset).
- **PRs liées au thread** : 181 et 182 (`link_pull_request`). PR asso/playback annoncée par le parent (URL non encore fournie) : à intégrer quand elle arrive, même boucle.

## État fin de passe (2026-11-02, ~00h55 UTC)

- **182 : MERGED** — squash `5b5a0ef4` sur master, match-head `66f5f86f` vérifié, APPROVE bot sur le SHA exact (run 41360104925), aucune régression gate. Déploiement : l'auto-deploy cron peut livrer `5b5a0ef4` seul (aucun rollback, aucun recours à un SHA ancien) ; le ship final regroupé se fera après le merge de 181 (avec la migration précâblée: SQL appliqué AVANT le ship via ssh psql single-statement CONCURRENTLY).
- **181 : head `f035e617`** (chaîne 72692ccf → 9249e64d → 7662e64b → ffc3d555(merge 182) → 920519c9 → f035e617, branche `t3/feedback-reliability`) :
  - fence par génération au rebase (les réponses antérieures perdent la propriété du chargement), test A→finA-avant-B (label « Loading… » maintenu), curseur rebasé non-raphaeté par les réponses tardives ;
  - test Library réécrit : lecture des appels DANS le poll (snapshot périmé corrigé, fenetre 3 s, assertion causale inchangée) ;
  - fixture PG complet : fermeture FK réelle + seed app_users conforme au contrat émis par create_all (role/flags/timestamps NOT NULL sans DEFAULT — risque de NotNullViolation d'initiatives croisées documenté dans le seed) ;
  - historique : APPROVE bot sur 920519c9 (comment 6565622176) conservé en preuve ; noueau verdict requis sur f035e617.
- **184 : head `29733254`** (6361a8cd → 3e5a9d17 → 29733254, branche `t3/accessibility-playback-fixes`) :
  - le nettoyage passe par le routeur (`useSkipToMainContent` → `navigate(replace, state, preventScrollReset)`) + normalisation `#main-content` dans `withoutClip` (mémoire d'onglet) ;
  - test BrowserRouter de bout en bout : hash initial + state seedé, focus/URL/useLocation/état/mémoire propres, départ-retour mobile sans résurrection de fragment (échoue sur l'ancien replaceState) ;
  - audit réécrit autour du mécanisme final ; verdict bot COMMENT traité en deux findings ; les findings Community/avatars restent rejetés, play/pause reste tests-only.

### 181 — fix ffc3d555 (deux verdicts du run 41360587627 traités)

- head **`ffc3d555`** (après 72692ccf → 9249e64d → 7662e64b → ffc3d555, branche `t3/feedback-reliability`), linked, réponse aux deux findings postée https://github.com/maxime-c16/dive-analyser/pull/181#issuecomment-6565418755.
- **race curseur rebasé vs continuation en vol** : `rebaseSeq` (rebase y compris curseur nul pendant un vol, fence levée, contrôle actionnable ; les réponses antérieures au rebase ne réécrivent plus curseur/hasMore, leurs lignes fusionnent) — test « keeps the rebased cursor… » + suite front 885 tests.
- **index partiel unread** : `backend/migrations/add_notifications_unread_index.sql` (CONCURRENTLY, idempotent, additif) + ORM miroir + `test_postgres_notifications_unread_index.py` (DDL ×2, 2000 lues + 30 non-lues, EXPLAIN page & sonde sur l'index) ajouté au tier postgres CI + **prérequis manuel documenté** (REPO_WORKFLOW.md § « Notification unread index ») : SQL à appliquer AVANT tout déploy incluant 181.
- conflits 181↔master(182) : aucun (merge-tree write-tree exit 0 à 7662e64b).

### Merge 182 ✔

- **PR 182 fusionnée (squash, match-head 66f5f86f…)** : merge commit `5b5a0ef4785c`. Gates vérifiées au head courant (gate/checks backend+frontend/postgres/review/plan ✔), APPROVE explicite du bot sur `66f5f86f` (run 41360104925, commentaires GitHub), mergeStateStatus CLEAN avant merge, aucun thread bloquant restant. Linked.
- Master avance donc au-delà de 181 : conflits d'i18n anticipés évités (le bloc 182 est placé en tête des dictionnaires, le bloc routeError 181 en fin) ; 181 reste en corrections (pastille ci-dessous).

### PR 181 — feedback reliability — https://github.com/maxime-c16/dive-analyser/pull/181

- Head nouveau : `9249e64d` (au-dessus de `72692ccf`, branche `t3/feedback-reliability`), CI complète verte sur `72692ccf` (plan, review, frontend, backend, postgres, gate ✔ 21:57Z) ; checks + review bot rejouent sur `9249e64d`.
- Traitement verdict REQUEST_CHANGES (72692ccf) : trou de pagination au refresh — **corrigé** (rebase du curseur de continuation sur l'anchor de la nouvelle tête quand elle avance ; gain des lignes déplacées au clic suivant via keyset ; fusion par id sans duplication ni rétention illimitée). Test régression : « re-reaches a row displaced by a growing first page… ».
- Threads copilot : 4 ouverts traités — 2 déjà fixés par `72692ccf` (probe `unread_only`, fence des pages périmées ; résolus avec réf. tests) et 2 fixés par `9249e64d` (reload gardé sur imports spéculatifs → `loadChunkPrefetch` ; +3 tests chunkLoad). Threads résolus avec réponses agent GLM.
- Commentaire synthèse posté : https://github.com/maxime-c16/dive-analyser/pull/181#issuecomment-6565094264
- Validation locale : vitest notifications+chunkLoad (29/29), TS, build production ; suite backend inchangée (aucun fichier backend touché par la passe).

### PR 182 — Library UX — https://github.com/maxime-c16/dive-analyser/pull/182

- Head nouveau : `66f5f86f` (au-dessus de `31baab0f`, branche `t3/library-ux-state-search`). CI de `31baab0f` : ✗ `checks (frontend)` → ✗ `gate` (run 41355157181) ; les autres verts.
- CI frontend diagnostiquée : flake de timing démontré (`waitFor` défaut 1000 ms derrière un rendu `useDeferredValue`, sur runner chargé) — suite intégrale 872/872 rejouée 2× en local avec les flags CI exacts sur le même head. Fenêtre dédiée portée à 5 s (assertion inchangée).
- Verdict COMMENT (bot, Dives.tsx:387/427) : **corrigés** — filtre client borné par `periodFrom` (les lignes « keep-mounted » d'une autre période disparaissent de la liste et impossible d'ouvrir un deep-link hors période) ; ancre scroll restaurée consommée uniquement par les lignes de la clé restaurée (`loadedKeyRef` vs `workspaceRestoreKeyRef`).
- Copilot ouvert : restore de présentation seule (`view`/`sort`) sans re-fetch — **corrigé** (re-run explicite `setReloadKey`). Copilot outdated (`libraryWorkspace` reset, `diveNameSearch` doublons/cap) : déjà fixés sur `05eb65f6`, vérifiés dans le code, threads résolus avec réf. tests.
- Commentaire synthèse posté : https://github.com/maxime-c16/dive-analyser/pull/182#issuecomment-6565215908
- Validation locale : 55 tests Dives (4 nouveaux + 1 renforcé), **suite intégrale 876/876**, typecheck OK, build production relancé (frontend tier de la gate sur GitHub).

## Registres

- PR 181 : `docs/audits/ux-fixes/feedback-reliability.md` → section « Suivi review (2026-11-01 ~23h) ».
- PR 182 : `docs/audits/ux-fixes/library.md` → section « Suivi review (2026-11-02 ~00h) ».

## Partagé transversal

- **Environnement dev de ce poste** : `ci/gate.sh` local non exécutable (flock, `nproc`, `timeout`/`nice`, docker-compose absents) → pushes faits avec l'échappatoire documenté `DIVE_CI_SKIP=1` ; la gate GitHub (frontale) reste la référence de correctivité et continue de gate les merges. **Node 26** (brew) casse l'environnement jsdom des tests (globaux `localStorage` expérimentaux) : validation locale faite sur **Node 20 installé non-linké** (`/opt/homebrew/opt/node@20/bin`), même version que la CI. Aucun changement repo lié à ce poste.
- Pas de secret affiché/copié. Opérationnel : clé GitHub fournie en amont par Maxime, aucun contournement de review/gate.

## Merge & déploiement planifiés (à exécuter aux prochains réveils)

1. **Attente sur les nouveaux heads** (`9249e64d` sur 181, `66f5f86f` sur 182) : checks requis verts + verdict **APPROVE/clean explicite** du bot pour le SHA courant (pas d'approbation antérieure comptée). Si le bot trouve encore : nouvelle passe (fix justifié ou rejet motivé), et seulement ensuite verdict demandé.
2. Merge **181 puis 182** en squash via `gh pr merge <url> --squash --match-head-commit <sha-approuvé>` — gates : reviewDecision APPROVED sur le head courant, aucun thread blocking, mergeStateStatus CLEAN. Si base bougée entre les deux : maj de branche → nouvelle review exigée pour le nouveau SHA. Git statut par couche, chaque couche des couches.
3. Déploiement : `ci/ship.sh status` → `ci/ship.sh server --ref <merge-sha> --dry-run` → `ci/ship.sh server` (gates normales, jamais `--allow-unmerged`/`--skip-gate`). Regrouper si les deux merges sont avalés en chaîne : déployer le dernier SHALes source puisque le merge 182 inclut les commits 181 (vérifier via `git merge-base`/ancestralité avant) ; ne jamais reculer un déploiement plus récent.
4. Prérequis opérationnels : **aucune migration SQL** pour ces deux PRs (aucun fichier `backend/migrations/` touché) ; notes de release bien présentes (`feedback-reliability-ux-fixes.json` côté 181 via #180 déjà publié → vérifiable au dry-run, et `library-remember-search-find.json` côté 182 — les deux user-visible, components frontend+backend). Rien côté Mac/mac-agent, rien côté nginx/tailscale → pas d'action manuelle attendue au-delà de la procédure standard.
5. Vérification post-déploiement : SHA services (labels images), health LAN/Funnel/public, `deploys.log`, note publication (catalogue), probe média si le runtime l'exige. **Pas de Mac par défaut.**
6. À l'arrivée de la PR asso/playback du lot : prendre le head d'aujourd'hui/période, appliquer la boucle (collecte → vérification → fix/tests → push → verdict bot récent → merge → dernière passe déploiement au lot).

## Passe 2026-11-02 ~01h05 (fin de cycle)

- **184 : MERGED** (`c73905b6`) — gates vertes sur 29733254 + APPROVE bot exact (comment 6565728233), match-head. Le master avance (184 inclus) : merge-tree 181↔master re-validé propre (exit 0).
- **181 : head `53db4d56`** (887089ea + registre docs) — groupé et posté avec : (1) fix parse psycopg2 du plan EXPLAIN (l'échec postgres restant était le decodage JSON natif, pas la fixture) ; (2) le finding du verdict (async state anchor 11→40 au switch) corrigé avec régression switch All/Unread sans arrivée, et les races refresh précédentes toujours couvertes ; (3) durcissement JurySession (les contrôles « Finish video » attendus, assertion causale inchangé) après l'échec CI démontré comme settle sous charge (arbre identique PASS au run précédent, seul delta = le fichier seed).
- Déploiement : après merge 181 → SQL index ⇒ ship regroupé avec effets SHAs/health.
