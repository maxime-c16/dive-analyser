# UX fixes — feedback reliability (Périmètre B)

- **Date** : 2026-11-01 (la note JSON indique 2026-11-02, sa date propre)
- **Périmètre** : routeur / lazy chunks / error boundaries, notifications API + UI, Community/MemberProfile, lecteur ClipViewer, provenance note/auteur.
- **Source** : six rapports simulés (lecture seule, non committés) dans
  `docs/audits/ux-discovery-2026-11-01/` (`ux-debutant.md`, `ux-progression.md`,
  `ux-mobile-seance.md`, `profil-4-retrouver/rapport.md`,
  `profil-5-retours/rapport.md`, `profil-6-communaute/rapport.md`).
- **Règle** : chaque constat a été vérifié contre le code courant ; les agents simulent des utilisateurs — une absence non trouvée n'est pas une absence réelle. Rien qui ne concerne Library (agent A) n'a été modifié : un seul chevauchement volontaire, signalé ci-dessous.

---

## 1. Signaux classés

### C1 — `/users/15` : « Unexpected Application Error! — Failed to fetch dynamically imported module: …/assets/MemberProfile-DkqMGo6T.js » persistant après F5 — **CONFIRMÉ (défaut d'interface, cause de déploiement établie) / corrigé défensivement**

**Ce qui est confirmé contre le code :**

- Le routeur charge chaque page en lazy (`frontend/src/router.tsx`, ~20 `load*()` module-level) **sans aucune error boundary** : un échec d'import de chunk remonte à React Router, qui affiche son écran brut « Unexpected Application Error! » sans aucune issue de secours (constat répété par le profil 6, captures 11/12).
- Aucun service worker ne crée de cache parasite : `frontend/src/sw-push.ts` est **push-only** (« deliberately NO workbox precache, NO fetch handler ») — le constat n'est pas du côté SW. La persistance après F5 reste cohérente avec une session d'onglet lancée sur l'ancien bundle (l'agent a testé pendant la fenêtre de déploiement).

**Cause réelle établie (probe HTTP lecture seule, 2026-11-02) :**

- `https://dive-analyser.tail32dd14.ts.net/assets/MemberProfile-DkqMGo6T.js` répond **200 `application/javascript`** sur le déploiement actuel — le chunk existe aujourd'hui. Le relevé de l'agent date du 01/11 ~22h, pendant/autour d'un remplacement d'image frontend : scénario de référence = `index.html` périmé dans le navigateur (ou onglet ouvert avant le déploiement) qui référence un hash supprimé → échec de `import()`.
- Le fallback SPA ne masque pas les chunks manquants : un asset inexistant (`/assets/DefinitelyMissingChunk-…js`) renvoie un vrai **404** (`try_files $uri =404` de `frontend/nginx.conf` sur `location /assets/`, `index.html` en `Cache-Control: no-cache`). L'hypothèse « 404 réécrit en 200 HTML » est rejetée : `proxy_intercept_errors` est désactivé par défaut et la sonde renvoie bien 404 `text/html`.
- Je n'ai **pas reproduit** l'erreur sur la prod ; la correction est défensive mais robuste face aux deux causes plausibles (hash périmé après deploy, échec réseau transitoire).

**Correction (frontend) :**

1. `frontend/src/utils/chunkLoad.ts` : chaque import lazy passe par `loadChunk()` →
   1 retry en place (échec réseau transitoire) → **un seul** `window.location.reload()` (garde `sessionStorage`, cooldown 90 s : jamais de boucle) → sinon l'erreur est relancée (jamais avalée).
2. `frontend/src/components/RouteErrorBoundary.tsx` : toutes les routes lentes (arbre authentifié + `/room/:code`, `/share/*`, `/claim`, `/invite`) sont couvertes par une boundary qui garde le shell, affiche `routeError.title/body` et deux actions : **Reload** (action explicite utilisateur, via la même indirection) et retour Library. Reset automatique quand le chemin change.
3. Les utilisateurs voient une erreur *actionnable*, pas masquée ; le reload auto est plafonné par le cooldown et ne tourne pas en boucle.

**Tests :** `src/utils/chunkLoad.test.ts` (5), `src/components/RouteErrorBoundary.test.tsx` (3). Probe HTTP documentée ci-dessus (lecture seule, non automatisable en CI : le bug dépend d'un déploiement).

---

### C2 — Badge « 84 » mais liste figée à ~50, « Unread (0) » pendant le chargement — **CONFIRMÉ, corrigé (API + UI)**

**Vérifié contre le code :** `notification_service.list_for_user` plafonnait à 50
(défaut) / 100 (max) **sans continuation**, le badge comptait toutes les non-lues
(`count_unread`) — les 34 notifications au-delà de la page 1 étaient inaccessibles
(profil 5 : « liste figée malgré des scrolls » ; ux-progression : « 84 non-lues… 34 au-delà non rendues »). Le bouton filtre affichait `Unread ({{count}})` avec `unreadCount` initialisé à 0 → « Unread (0) » contradictoire pendant le chargement (ux-mobile-seance, capture 04).

**Correction :**

- **Backend** (`backend/app/services/notification_service.py`, `app/api/v1/notifications.py`) : paramètre `before_id` (keyset sur `created_at desc, id desc`, ancre obligatoirement détenue par l'appelant — un ancre étranger lit « fin de boîte », règle « missing, never forbidden » inchangée), plus un flag explicite `has_more` (une requête indexée bornée par page, pas de scan non borné ; pagination complète offerte, compteur global inchangé, aucune liste privée stockée côté client au-delà de la session).
- **Frontend** : `listNotifications({ beforeId })` ; la page Notifications ajoute « Show older notifications » qui enchaîne les pages sous la page 1 (deux modes « Tout afficher » et « Non lues »), ne
 l'annonce que si le serveur a dit `has_more`, et le filtre « Non lues » affiche `unreadOnlyPending` (« Unread » / « Non lues ») tant que le compte du serveur n'est pas arrivé.
- Le compteur du badge (full-scope) reste la source de vérité ; la pagination n'appelle jamais une liste tronquée « complète ».

**Tests :** `backend/tests/test_notifications.py` +3 (pages en série sans chevauchement, `has_more` exact aux deux extrémités, ancre étrangère = page vide, unread_only + lectures concurrentes) ; `src/components/Notifications.test.tsx` +4 (pagination avec ancre, marquage dans la continuation, pas de continuation quand la liste tient en page 1, aucun « Unread (N) » avant arrivée) ; `src/services/notificationsApi.test.ts` +1 (URL `before_id=11`).

---

### C3 — « 4.3 » affiché vs « No scores yet. » — **CONFIRMÉ (contrat réel, sans score inventé), corrigé**

**Contrat réel (code) :** le badge (4.3) = `attemptScore()` → `performanceScore10(performance, phase1, phase2)` sur la **lettre de performance enregistrée** (P/G/M/B/F → /10, `frontend/src/utils/performanceScoring.ts` — F0 / B2 / M4.5 / G7 / P10, phases pondérées 45/55). L'onglet Evaluation pour le propriétaire montre le circuit (qualité communautaire, « Community score · provisional », clé `clipEvaluation.circuitCommunity`) et, jury vide, « No scores yet. » (`clipEvaluation.noVotes`). Deux sources différentes, aucun passage entre elles : d'où l'incohérence du compte e2e (rating_count = 0).

**Correction (minimale) :** l'état « jury vide » dit à présent les deux choses en une ligne : EN « No scores yet. The {{score}} shown is the logged performance score, not a jury score. » / FR « Aucune note pour l'instant. Le {{score}} affiché est la note de performance enregistrée, pas une note de jury. » — passé par `attemptScore(attempt)` (le contrat existant), **aucun score automatique inventé**.

**Tests :** `ClipEvaluation.test.tsx` ajoute le cas owner & rating_count 0 (l'ancien libellé exact est remplacé partout, ajusté dans la suite).

---

### C4 — Attribution du plongeur invisible dans le viewer (Community) — **CONFIRMÉ (donnée déjà disponible), corrigé**

**Vérifié :** le payload `Attempt` porte déjà `person_name` (colonne `Dive.person_name`,
renvoyée par les endpoints tentatives — `backend/app/api/v1/videos.py` entre autres). La grille de Library l'affiche quand `showDiver` (LibraryCards, **hors périmètre**) ; le lecteur ne le montrait nulle part (profil 6 : « le visionneur n'affiche aucun nom » ; profil 5/4 idem). 43/48 cartes Community sans noms = les plongeons du compte e2e lui-même (`person_name: null`) — l'autorisation n'est pas en cause : afficher le nom **quand la donnée existe** n'infère rien et n'expose rien qui ne soit déjà autorisé dans la liste.

**Correction (viewer seulement) :** nom affiché (ellipsis + tooltip) sous le titre du panneau studio, dans la ligne titre mobile et dans l'onglet **Details** (`attemptDetailRows` ajoute « Diver » / « Plongeur » quand `person_name` est fourni). Absence de nom = rien (jamais « You », jamais d'inférence de propriété). CSS : `.clip-panel-diver` (`clipViewer.css`).

**Tests :** ClipViewer.test.tsx +2 (nom présent dans caption + accessible name du dialog + panneau studio ; absence sans inférence). Besoin relevé mais **non implémenté** : attribution dans la grille Library = périmètre de l'agent A (voir « Deferred »).

---

### C5 — Contrôles absents dans le lecteur (ralenti, temps, like/favori, pastille qualité, vocabulaire) — **MAJORITAIREMENT REJETÉ** (contrôles existants), 1 micro-ajustement

**Rejeté avec preuve de code (outils présents dans le lecteur) :**

- **Ralenti** : le select existe, 0.25×→2× (`ClipViewerNavigation.tsx` `PLAYBACK_RATES`, `clipNav.playbackSpeed` ; mesuré par profil 4 « vitesse 0.25× appliquée »). L'absence rapportée par ux-debutant n'est pas reproduite (le HUD s'auto-efface — `HUD_HIDE_DELAY_MS` — ce qui peut expliquer une session où il n'était plus visible).
- **Affichage du temps** : `clock(progress) / clock(duration)` dans `ImmersiveControls.tsx` (vu « 0:07 / 0:11 » par deux agents).
- **Pas-à-pas image par image** : le scrub précis existe déjà (`Video position`, range natif, tap/flèche) ; une fonctionnalité « pas-à-pas d'image » dédiée n'existe pas — c'est une fonctionnalité nouvelle, pas une correction → rejeté (pas de nouveau code).
- **Like = favori ?** Rejeté : `useDiveSocial` appelle `PUT /dives/{id}/like {liked}` — c'est une **réaction like** avec compteur (`like_count`), pas un système de favoris/enregistrer-pour-plus-tard. Le libellé « boutons favori » du profil 5 est une mauvaise lecture. Un « retrouver cette vidéo plus tard » n'existe pas : fonctionnalité nouvelle → **deferred** (pas de nouveau planificateur/favoris autorisé dans le brief).
- **« Back to Library » premier clic raté** (profil 4, non reproduit) : javascript onClick direct → un échec isolé d'automatisation, pas de bug : rejeté.
- **« 142 / 300 » vs « 142 / 200 » au même clip** : c'est `index+1 / total` de la **liste courante** du lecteur (filtres/scope différents → totaux différents) : comportement attendu, rejeté. Reste une vraie question d'étiquetage (aucun texte dit ce que signifie le compteur) → mini-note au rapport, non corrigé (product decision).
- **Menu qualité qui « ne s'ouvre pas »** : rejeté — le design n'a pas de menu : la pastille **cycle** les renditions au clic (`cycleQuality`) et l'aria est correcte (`changeQuality`). La confusion vient du `title={label}` (survol d'un bouton « changer » affichant « Preview »). L'intitulé visible reste tel quel dans cette passe (voir le micro-défaut retenu ci-dessous).
- **Popovers/jargon DB/SD/HU** : le popover existe (capture 02 du profil 6, « DB · Double bounce / SD · Standing dive / HU · Hands up ») ; l'outillage du débutant ne l'a pas trouvé. Défaut de découvrabilité non confirmé comme bug : la demande « étendre l'aide à DD/SYNC/P-G-M-B-F/Phases » est une fonctionnalité nouvelle → **Deferred** (priorité 5 du brief : aide vocabulaire seulement si défaut confirmé).

**Micro-défaut retenu : la pastille « Preview » ne dit pas « qualité »** — friction d'étiquetage confirmée par trois rapports. Le composant est correct pour les lecteurs d'écran (aria-label « Change video quality ») et le libellé visible est le nom du rendu courant ; la confusion vient du `title={label}` (survol d'un bouton « changer » affichant « Preview »). Non corrigé dans cette passe (décision produit sur la présence du nom de rendu) ; candidat de repassage documenté.

---

### C6 — Chargements de 6–20 s (`/community` > 20 s, Messages ~20 s, Evaluation tab, Calendar ~6 s, bibliothèque « could not be loaded » au premier essai) — **PARTIELLEMENT DANS LE PÉRIMÈTRE** → trié

- **`/community` lent (constat profil 6, mon périmètre)** : lecture du code — la page exécute `allMembers()` : **boucle séquentielle de `searchMembers('', after)` jusqu'à 20 pages** (`frontend/src/pages/Community.tsx`), chaque page = 1 requête backend rangée dans SQL (PR #175) mais paginée (50/page) → l'annuaire entier se charge en X requêtes séquentielles avant même de trier les sections. Optimisation possible (regrouper en une réponse bornée unique), mais chaque appel reste borné et la page affiche `PageLoading` immédiatement (pas d'écran vide, pas d'erreur). **Deferred avec preuve** : cause confirmée côté code, changement matériel ; le tri des sections est déjà côté client et un agrégat unique changerait le contrat `searchMembers` = êtes du domaine « recherche/liste API » (agent A). Documenté, non corrigé.
- **Messages ~20 s « No conversations yet »** : hors périmètre B (la liste est vide : état réel du compte e2e probable). Deferred.
- **Evaluation tab « Loading page… » quelques secondes** : ce sont les fetchs séquentiels du viewer (social → évaluation) ; les états `PageLoading` existent déjà. Pas de cause corrigeable confirmée dans mon périmètre. Deferred.
- **Calendar « Loading calendar… » ≥ 6 s** : hors périmètre B. Deferred.
- **« The dive library could not be loaded. » au premier essai + Retry manuel** (ux-progression, majeur) : **hors périmètre B** (Library/recherche/liste = agent A, à qui la compétence reload de la lib est attribuée). Ma boundary de route (`C1`) couvre les échecs de **chunk**, pas les échecs de fetch de données de la Library. Documenté pour l'agent A.
- **Entrée Evaluations / My dives ouvrant le jugement d'autrui (profil 5)** : vérifié — la vue plein écran `JurySession` peut s'ouvrir au-dessus de « My dives » du Judge Room (`frontend/src/pages/Evaluations.tsx`, `frontend/src/pages/JudgeRoom.tsx`). Re-pointer ce flux change un chemin utilisateur non confirmé côté code (l'entrée exacte vue par l'agent n'est pas reproductible dans le code) → **deferred avec localisation exacte**. Rien d'autre modifié dans ces pages (hors périmètre confirmé) ; le lazy `JurySession` est quand même couvert par le hardening de chunk.

---

## 2. Ce qui a été produit (diff)

| Fichier | Changement |
|---|---|
| `frontend/src/utils/chunkLoad.ts` | **nouveau** : loadChunk (retry + reload gardé), clearReloadGuard |
| `frontend/src/utils/chunkLoad.test.ts` | **nouveau** : 5 tests |
| `frontend/src/components/RouteErrorBoundary.tsx` | **nouveau** : boundary de route avec reload manuel + lien Library |
| `frontend/src/components/RouteErrorBoundary.test.tsx` | **nouveau** : 3 tests |
| `frontend/src/router.tsx` | tous les loaders lazy wrapped par `loadChunk`, boundary autour de l'arbre authentifié et des routes publiques suspense |
| `frontend/src/pages/Dives.tsx` et `frontend/src/pages/CodeAnalysis.tsx` | **(chevauchement signalé)** une ligne chacune : import du ClipViewer par `loadChunk` |
| `frontend/src/pages/Evaluations.tsx` | idem pour le lazy `JurySession` |
| `frontend/src/services/notificationsApi.ts` | `beforeId`, `has_more` (non chiffrés : read as `false` sur serveurs anciens) |
| `frontend/src/services/notificationsApi.test.ts` | +1 test (URL before_id), ajustement du contrat has_more |
| `frontend/src/components/Notifications.tsx` | provider : `countsKnown`, `pageHasMore` |
| `frontend/src/pages/Notifications.tsx` | continuation « Show older notifications » sur les deux modes, reset au changement de filtre, « Unread » sans count tant que le serveur n'a pas répondu |
| `frontend/src/components/Notifications.test.tsx` | +4 tests (continuation, marquage, zéro-annonce) |
| `frontend/src/components/clip-viewer/ClipViewer.tsx` | attribution plongeur (ligne titre mobile + panneau studio) |
| `frontend/src/components/clip-viewer/ClipEvaluation.tsx` | noVotes avec provenance du score affiché |
| `frontend/src/utils/attemptPresentation.ts` | ligne « Diver » dans attemptDetailRows quand `person_name` |
| `frontend/src/components/clip-viewer/clipViewer.css` | `.clip-panel-diver` |
| `frontend/src/i18n/locales/en.ts` / `fr.ts` | bloc **nouveau** `routeError.*` (marqué « Added by the UX fixes ») + clés de famille : `notifications.unreadOnlyPending`, `notifications.loadMore`, `attemptDetail.diver`, + valeur corrigée `clipEvaluation.noVotes` |
| `backend/app/services/notification_service.py` | `list_for_user(before_id)` keyset, `list_has_more` (une requête bornée par page) |
| `backend/app/api/v1/notifications.py` | `GET /notifications` : `before_id`, réponse `has_more` |
| `backend/tests/test_notifications.py` | +3 tests pagination bornée |
| `backend/release-notes/feedback-reliability-ux-fixes.json` | note user-visible (frontend + backend) |

**Nouvelles clés i18n :** `routeError.title/body/reload` dans un bloc distinct en fin de fichier (marqué « Added by the UX fixes ») ; `notifications.unreadOnlyPending`, `notifications.loadMore`, `attemptDetail.diver` ajoutées dans leurs familles existantes (cohérence du dictionnaire). Valeur corrigée (pas une nouvelle clé) : `clipEvaluation.noVotes`.

**i18n FR/EN : aligné dans les deux fichiers ; textes courts, sans texte décoratif.**
**Accessibilité :** bouton Reload et lien Library focusables au clavier, `role="alert"` ; le span d'attribution est porté par l'accessible name du dialog ; le bouton de continuation est `disabled` pendant le chargement et libellé « Loading… ».

## 3. Chevauchements de périmètre (signalés)

- `frontend/src/pages/Dives.tsx` et `frontend/src/pages/CodeAnalysis.tsx` : **une seule ligne chacun** (le lazy ClipViewer, mon composant). Aucun autre changement ; pagination/scroll/recherche de la Library non touchés.
- Library : restauration de scroll/filtres, recherche, « Open latest attempt », rechargement de bibliothèque : non touchés — relevés dans C6 pour l'agent A.

## 4. Limites

- La sonde établit la présence actuelle du chunk ; la cause historique (cache/déploiement ou réseau) reste une hypothèse ; l'erreur elle-même n'a **pas été recréée volontairement sur la prod** (interdit par la mission).
- La pagination backend est testée sur SQLite (suite gate) ; le keyset utilise `created_at`/`id` sans index composite supplémentaire (bénéficie de `ix_notifications_user_created` + cache d'ancre, coûts bornés : 2 requêtes de page).
- Les latences 6–20 s restent en état (les squelettes existent) : seule la cause `/community` est documentée (deferred) — le reste appartient à d'autres périmètres.
- La donnée e2e ne montre pas de commentaires/jalons réels : l'affichage d'attribution des retours (commentaires signés) est vérifiable seulement sur un compte qui en possède (les composants reçoivent déjà `author`).

## Vérification parent et compléments

- Filtre `unread_only` conservé après application de l’ancre et appliqué à `has_more`, y compris avec des lignes déjà lues entre deux pages. Test de régression avec page terminale non lue suivie uniquement de lignes lues.
- Réponses de continuation invalidées après changement de filtre, marquage global ou démontage ; état de page isolé par compte. Déduplication des lignes déplacées par un rafraîchissement de première page. Tests de réponse différée et de chevauchement après refresh.
- Aucun rechargement automatique lorsque la garde sessionStorage ne peut pas être persistée (évite une boucle avec stockage bloqué). Test dédié.
- Validation complémentaire : notifications backend 17 tests ; notifications UI + chunkLoad 25 tests ; TypeScript et build production. Ces vérifications complètent les suites initiales, sans prétendre les avoir toutes rejouées après correction.

## Suivi review (2026-11-01 ~23h, babysitter GLM sur 72692ccf)

Registre des findings de review au head `72692ccf`, vérifiés contre le code courant.

| Source | Finding | Décision | Preuve/validation |
|---|---|---|---|
| Copilot (494886af), thread `notification_service.py:445` | probe `has_more` sans `unread_only` | **Déjà corrigé sur 72692ccf** (`list_has_more(..., unread_only=unread_only)`, filtre appliqué lignes 455–456 ; appel API `app/api/v1/notifications.py:105`) | thread résolu par le commit fix ; suite `test_notifications.py` pagination unread |
| Copilot (494886af), thread `Notifications.tsx:246` | continuation en vol après changement de filtre | **Déjà corrigé sur 72692ccf** (génération `pageGeneration` + cleanup + `pendingPage`) | test « ignores an old continuation response after the filter changes » |
| OpenCode (72692ccf), REQUEST_CHANGES | refresh 60–11 → 61–12 conserve 10–1 et perd l'ID 11 (perdu par les deux curseurs) | **Confirmé — corrigé** : rebase du curseur sur l'ancre de la nouvelle tête quand elle avance (curseur seulement vers l'avant, jamais de suppression), `olderHasMore` restauré, marchandage de la continuation par id (copies fraîches remplacent les périmées, pas de rétention dupliquée) | nouveau test « re-reaches a row displaced by a growing first page (60–11 + 10–1, new arrival 61) » : bouton réapparait, ID 11 réatteignable, un seul rendu par id |
| Copilot (494886af), thread `chunkLoad.ts:75` | imports spéculatifs (hover/warm) déclenchent le reload gardé et rechargent la page courante saine | **Confirmé — corrigé** : `loadChunkPrefetch` (1 retry en place, jamais de reload ni d'écriture de garde) pour `useNavigationIntent` (préchargement) et le warm-up `JurySession` au mount d'Évaluations ; les vraies navigations passent par `loadChunk` avec son reload gardé | +3 tests chunkLoad (aucun reload/écriture de garde, cooldown intact pour un chargement de route ultérieur) |
| Copilot (494886af), threads résolus (426, 229, 74) | — | **Déjà corrigés/traités sur 72692ccf** | markReload null → rethrow ; hasMore continuation vide → `olderCursor !== null` ; ancre unread conservée |

Validation locale de la passe : vitest notifications (20) + chunkLoad (9) sous Node 20 (le Node 26 de la machine casse l'environnement jsdom des tests, cf. globaux `localStorage` expérimentaux — uniquement local, la CI hébergée tourne sur Node 20), `typecheck`, `build` production. Gate locale indisponible sur ce poste (flock/nproc/docker-compose absents) : push avec `DIVE_CI_SKIP=1` (échappatoire documenté) et gate GitHub comme correctivité de référence.
