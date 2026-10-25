# Audit : premier chargement et démarrage de lecture (Opus, 25 octobre 2026)

Statut : audit et expériences contrôlées uniquement. Aucun changement produit, aucun
déploiement, aucune écriture en production. Brief : `docs/audits/media-startup-opus-brief.md`.
Preuves : `docs/audits/media-startup-opus/`. SHA déployé au moment des mesures : `18543d1`.

## En une phrase

Le goulot principal en production n'est ni le réseau ni la bibliothèque. C'est **l'unique
event loop du backend**, qui peut **se figer 30 s ou plus** : des requêtes `async def` exécutent
du SQL synchrone, et l'une d'elles (`GET /media/{uuid}/status`) prend un verrou consultatif
Postgres. Ce verrou peut interbloquer la boucle avec elle-même. Ce scénario a été
reproduit à l'identique en local et une trace réelle de ce matin (08:34 UTC) a la même
signature. Le reste (posters trop lourds, tuiles vidéo, écriture SQL à chaque affichage de
poster, attente de `/auth/me`, Funnel) est réel mais de second ordre tant que ce gel existe.

## Ce que j'ai pu mesurer, et ce que je n'ai pas fait

- Lecture seule en production : logs Docker (nginx LAN, nginx Funnel, backend depuis son
  redémarrage de 09:02, Postgres sur 7 jours), `pg_stat_*` et quelques SELECT,
  `/proc/diskstats`, `stat`/`ffprobe` sur quelques fichiers du cache, plus `curl` **non
  authentifié** (aucune écriture : un 401 ne touche pas `user_sessions`).
- **Pas de requête authentifiée** : un login insère une session, chaque requête met à jour
  `last_used_at` une fois par minute, et chaque GET de poster écrit en base (voir P1-3).
  Je n'ai donc mesuré en production ni la durée de `/dives/library`, ni le premier poster.
- Expériences locales contrôlées, scripts versionnés :
  - `advisory_lock_probe.py` : FastAPI 0.104.1, SQLAlchemy 2.0.23 et psycopg2, comme en
    production, avec un Postgres 16 local jetable.
  - `event_loop_probe.py` : modèle de sérialisation de l'event loop.
  - `decode_probe.cjs` : décodage Chrome sur des JPEG **synthétiques** aux dimensions réelles.
    Aucune donnée utilisateur n'a été copiée.
- Les logs nginx n'ont pas de `$request_time`. Les heures sont donc à la seconde, au moment
  où la réponse se termine. Les logs backend antérieurs à 09:02 ont été perdus au redéploiement.

## Schéma 1 : chemin d'un premier chargement (accès public Funnel)

```
iPhone/Mac ──TLS──► relais Tailscale Funnel ──► nginx funnel-proxy ──► backend (1 worker uvicorn, 1 event loop)
                                               │  auth_request /auth/me      │  pool SQL 10+2, pool_timeout 30 s
                                               │  avant CHAQUE /api et "/"   ▼
                                               │                          Postgres (HDD 5400 tr/min, fsync ≈ 39 ms)
                                               └─ X-Accel ─► fichiers /app/media-cache (même HDD)

t=0   GET /  (index.html, lui-même derrière auth_request → /auth/me backend)
      GET /assets/index-*.js   229 Ko gzip (617 Ko brut), cache immuable
      GET /api/v1/auth/me      ← le routeur React affiche le splash tant que ce n'est pas revenu
      ┌ /dives/library + /divers   (Promise.all : la grille attend la plus lente)
      ├ /updates, /notifications, /messages/unread-count, /achievements/unseen, /deposits/pending
      ├ /media/status/batch     (supprimé par le lot 1 du parent)
      ├ ~15 tuiles visibles : 34 % <img> poster cache, 61 % <video preload=metadata>, 5 % placeholder
      └ préparation lecture : jusqu'à 3 × GET /media/{uuid}/status + preload=auto du proxy (~1 Mo chacun)
```

Chaque flèche `/api` passe par le même event loop. Sur Funnel, chacune déclenche aussi une
sous-requête `/auth/me` vers ce même backend (`ops/tailscale/nginx.conf:94-106`).

## Schéma 2 : l'interblocage (P0-1)

```
event loop (un seul thread)                        Postgres
───────────────────────────                        ────────
Req A  GET /media/{u1}/status  (async def)
  member_access_context : SELECT ×3                T_A ouverte
  _status_for_asset → latest_active_job_for_asset
    → reclaim_expired_media_jobs
    → SELECT pg_advisory_xact_lock(73125,1)        T_A détient le verrou
  retourne le JSON (pas de COMMIT)                 T_A "idle in transaction"
  await send(...)  ← point de bascule
Req B  GET /media/{u2}/status  (ou POST /media/jobs/lease du Mac)
  ... SELECT pg_advisory_xact_lock(73125,1)  ──►   attend T_A
  appel psycopg2 SYNCHRONE : la boucle est bloquée
Teardown de A (get_db → rollback) : il ne peut jamais être planifié, car la boucle est figée
                                   … 30 s …
                                                   FATAL idle-in-transaction timeout (T_A tuée)
B obtient le verrou ; la boucle repart ; toutes les requêtes en attente se terminent d'un coup
```

En FastAPI 0.104, le code après le `yield` d'une dépendance s'exécute **après l'envoi de la
réponse**. La transaction de A reste donc ouverte, verrou compris, au-delà de son `return`.

## Problèmes, par priorité

### P0-1 · Interblocage de l'event loop par le verrou consultatif `(73125,1)`

- **Déclencheur** : au moins deux requêtes concurrentes sur le même worker qui prennent le
  verrou depuis un handler `async def`. Côté utilisateur : `GET /media/{uuid}/status`, ou
  `POST /media/{uuid}/request` via `_status_for_asset` → `latest_active_job_for_asset` /
  `create_or_reuse_media_job` → `reclaim_expired_media_jobs`
  (`backend/app/services/media_jobs.py:85,133,464`). Côté Mac : `POST /media/jobs/lease`
  (`backend/app/api/v1/media.py:1265`). Le statut média des évaluations y passe aussi
  (`evaluation_access.py:284`). Le verrou existe depuis la PR #128 (20 oct.).
- **Preuve dans le code** : tous ces handlers sont des `async def` qui appellent SQLAlchemy de
  façon synchrone. `pg_advisory_xact_lock` bloque donc le thread de la boucle.
- **Preuve expérimentale** (`advisory-lock-probe*.json`, timeout idle local à 5 s) :

  | Scénario (6 rounds) | Pire requête par round |
  |---|---|
  | Forme actuelle, 3 status + 1 lease | 15,0 / 10,0 / 15,0 / 10,0 / 15,0 / 5,0 s |
  | Forme actuelle, **3 status seuls** (trafic utilisateur seul) | 10,0 s à chaque round |
  | Mêmes handlers en `def` (threadpool) | 14 à 24 ms |
  | Status sans `reclaim` (lecture pure) | 11 à 13 ms |

  Le gel dure un multiple exact du timeout. En production, ce timeout vaut 30 s.
  **Aucune réponse n'est en erreur** : l'utilisateur voit un écran figé, pas un message.
- **Preuve en production** (`prod-evidence-2026-10-25.json`), session réelle de ce matin :
  - 08:34:52–53 : la page charge (`/auth/me`, bibliothèque, un `status` à 200).
  - Puis **aucune réponse utilisateur pendant 30 s** sur les deux front doors.
  - 08:35:03 : le client abandonne 10 requêtes (499 : 6 posters, 2 status, 1 grant).
  - 08:35:22.9–23.8 : **Postgres tue 5 connexions "idle in transaction"** ouvertes vers 08:34:53.
  - 08:35:55 : 2 nouveaux kills, le heartbeat du job Mac part en 499, puis le Mac déclare
    le job en échec à 08:35:57.
  - 08:35:56–57 : toutes les réponses en attente arrivent en même temps, plus un 500.

  Sur 7 jours, 148 des 219 minutes avec un kill coïncident avec de l'activité API
  utilisateur, alors que seulement 18 % des minutes sont actives (≈ 3,7 × la base).
- **Impact UX** : la bibliothèque s'affiche, puis posters, ouverture de clip et
  notifications restent figés 30 à 60 s. Sur Funnel, même `index.html` attend
  (auth_request), ce qui peut bloquer un rechargement. La migration média en souffre aussi :
  heartbeats perdus et jobs déclarés en échec.
- **Certitude** : mécanisme **prouvé** (code et reproduction déterministe avec les versions
  de production). Rôle dans l'incident de 08:34 **très probable** (même signature, même
  minute, même nombre d'acteurs), sans trace backend pour le confirmer. Les kills en grappe
  du 18 octobre précèdent la PR #128 : au moins une autre cause a existé (voir P0-2).
- **Correction candidate** :
  1. Ne plus faire de `reclaim` (écriture + verrou) sur les chemins de lecture `status` :
     le réserver au lease et au tick de fond.
  2. Passer ces handlers en `def` (threadpool) pour qu'une attente de verrou ne fige plus
     tout le worker.
  3. En défense, mettre un `SET LOCAL lock_timeout` court sur toute prise de verrou en
     chemin interactif.
- **Coût induit** : une reprise de job expiré légèrement plus tardive (au prochain lease ou
  tick), et un threadpool plus sollicité, borné par le pool SQL.
- **Test qui tranche** : `advisory_lock_probe.py` comme test de non-régression avec
  Postgres. Exigence : 3 status + 1 lease concurrents sous 1 s, et 0 kill
  "idle-in-transaction" dans le log. En production, après déploiement : courbe des kills par
  jour et disparition des grappes.

### P0-2 · SQL synchrone sur l'event loop partout (dépendance d'auth globale, routes média)

- **Déclencheur** : chaque `/api/v1/*` exécute `member_access_context`
  (`backend/app/services/dive_access.py:187`). C'est une dépendance **async** au niveau du
  routeur (`backend/app/api/v1/__init__.py:25`) qui lance 3 SELECT synchrones et, une fois
  par minute, un COMMIT.
  - Les routes média sont aussi `async def` avec du SQL synchrone : poster/proxy
    `cache/{id}/play`, `status`, `status/batch`, `revisions/{id}/play` avant et après le HEAD.
  - `/auth/me` aussi.
  - Le backend tourne avec **un seul worker uvicorn** (`docker-compose.yml:147`).
- **Preuve** : modèle contrôlé avec 15 posters simultanés, SELECT à 1 ms et COMMIT à 39 ms,
  soit la latence de flush mesurée sur `sda` (`event-loop-probe-commit39.json`) :

  | Forme | Dernier poster | `/me` arrivé pendant la rafale |
  |---|---|---|
  | Actuelle (tout sur la boucle) | 782 ms | 422 ms |
  | Threadpool | 66 ms | 17 ms |
  | Boucle mais sans COMMIT par vue | 151 ms | 67 ms |

  Avec un flush à 150 ms, ce qui reste plausible sous la pression I/O observée
  (PSI jusqu'à 82 %), on passe à 2,5 s contre 185 ms. C'est un **modèle**, pas une mesure de
  production.
- **Impact UX** : toutes les requêtes passent l'une après l'autre. Un poster lent ralentit
  `/auth/me`, la bibliothèque et l'ouverture de clip.
- **Certitude** : mécanisme certain ; ampleur en production non mesurée (pas de
  `request_time` dans les logs).
- **Correction** : convertir `member_access_context` en dépendance synchrone, ou exécuter son
  corps via `run_in_threadpool`, et passer les routes média de lecture en `def`. Ajouter un
  indicateur de « lag de boucle » (voir Télémétrie).
- **Coût** : un saut de thread par requête, négligeable. Il faut aussi vérifier que le
  pool SQL (12) ne devient pas le nouveau goulot : c'est un goulot visible et mesurable,
  plutôt qu'un gel global.
- **Test** : `event_loop_probe.py`, puis en production `Server-Timing` et la mesure du lag de boucle.

### P1-3 · Chaque affichage de poster ou de proxy écrit en base (UPDATE + COMMIT) et se revalide toutes les heures

- **Déclencheur** : `get_playable_entry` (`backend/app/services/media_cache.py:146-150`) met à
  jour `last_accessed_at`, `updated_at`, puis fait un COMMIT et un refresh à **chaque** GET,
  304 compris. Il faut ajouter 2 résolutions de session (dépendance globale et
  `require_legacy_media_user`) et la chaîne d'accès.
  - `last_accessed_at` est indexé : sur 13 314 mises à jour, seules 13 sont HOT, donc chaque
    vue réécrit aussi les index et génère plus de WAL.
  - `Cache-Control: private, max-age=3600` sur une URL dont le contenu est adressé par hash :
    après une heure, chaque tuile repart en requête conditionnelle et repaie toute la chaîne
    pour un 304. Sur 7 jours de Funnel, le 304 est le statut poster le plus fréquent.
- **Impact** : environ 15 COMMIT avec fsync sur disque dur par écran de grille, exécutés sur
  la boucle (voir P0-2).
- **Certitude** : élevée pour le mécanisme et les compteurs ; le coût par COMMIT est
  estimé à partir de la latence de flush mesurée (39 ms en moyenne sur 30 s).
- **Correction** :
  - Limiter l'écriture à une fois par heure ou par jour et par entrée (comme
    `LAST_USED_WRITE_SECONDS` pour les sessions), ou l'accumuler en mémoire.
  - Servir les posters avec `private, max-age=31536000, immutable`, puisque l'id d'entrée et
    le chemin par sha sont immuables.
  - Éventuellement `SET LOCAL synchronous_commit = off` pour cette écriture de faible valeur.
- **Coût** : l'éviction LRU du cache devient moins précise (granularité d'une heure) ; la
  révocation d'accès ne s'applique plus aux posters déjà en cache navigateur (cache privé :
  risque faible, à accepter explicitement).
- **Test** : compter les COMMIT de `pg_stat_database.xact_commit` pendant une rafale de 15
  posters, avant et après ; ratio 304/200 dans les logs.

### P1-4 · Chaque WebSocket `ws/sync` immobilise une connexion du pool et laisse une transaction ouverte

- **Déclencheur** : les dépendances du routeur (`get_db` + `member_access_context`)
  s'appliquent aussi aux WebSockets. La session reste ouverte **pendant toute la vie de la
  socket** (vérifié avec FastAPI 0.104.1 : `open → ctx → accepted … close` seulement à la
  déconnexion). Postgres tue la transaction au bout de 30 s, mais le pool considère la
  connexion comme empruntée jusqu'à la fermeture de la socket.
- **Preuve** : par jour, le nombre de kills isolés suit le nombre d'upgrades `101 ws/sync`
  (19 oct. : 43 vs 52 ; 20 oct. : 43 vs 49 ; 22 oct. : 49 vs 56 ; 25 oct. : 5 vs 2 à
  10 h UTC).
- **Impact** : chaque onglet admin ouvert retire une connexion sur 12. À l'épuisement, une
  requête attend `pool_timeout` (30 s) puis renvoie un 500.
- **Certitude** : mécanisme prouvé, corrélation forte. Je n'ai pas observé d'épuisement
  du pool (non observable de l'extérieur).
- **Correction** : sortir `ws/sync` des dépendances du routeur, ou fermer la session juste
  après l'authentification, puisque `_ws_session_ok` ouvre déjà sa propre session courte.
- **Test** : ouvrir N WebSockets en local, puis vérifier `engine.pool.checkedout()` et les kills.

### P1-5 · Poids média de la grille : posters pleine résolution et 61 % de tuiles `<video>`

- **Mesures** sur 2 998 clips :
  - 1 013 tuiles ont un poster cache : JPEG **1080×1920 à 2034×3616**, médiane
    156 Ko, p90 208 Ko, max 454 Ko.
  - **1 826 tuiles retombent sur `<video preload=metadata>`** (proxy 720p, médiane 963 Ko).
  - 159 tuiles sont des placeholders.
  - 1 135 des clips sans poster cache ont déjà un poster durable D5, soit 975 → 1 135 depuis
    la mesure du matin.
- **Décodage** (Chrome desktop, images synthétiques, `decode-probe.json`) : ≤ 77 ms pour
  15 images, même en 2034×3616 : **ce n'est pas le goulot sur desktop**. En revanche, la
  mémoire décodée pour 15 tuiles vaut 119 Mio (1080×1920) à 421 Mio (2034×3616), contre
  18 Mio en 480×640. Sur iPhone, c'est le vrai risque (évictions, re-décodages, saccades).
  **Non mesuré sur appareil.**
- **Réseau** : 15 posters d'environ 156 Ko font ≈ 2,3 Mo, contre ≈ 0,35 Mo pour des
  vignettes de 480 px. Sur Funnel et en 4G, c'est la différence la plus visible. Les tuiles
  vidéo ajoutent des requêtes Range, chacune passant par la chaîne backend complète et un
  COMMIT.
- **Certitude** : élevée pour les tailles et la couverture ; impact en secondes non
  chiffré (débit client inconnu).
- **Correction** : produire une **vignette de grille** (≈ 480 px de large, WebP ou JPEG
  ≈ 20–40 Ko), servie localement avec un cache immuable. Une fois la vignette disponible,
  ne plus monter de `<video>` dans la grille.
- **Coût** : un rendu supplémentaire par clip côté Mac et un peu de disque (≈ 100 Mo pour
  3 000 clips).
- **Interaction D5 (pas d'ownership ici)** : brancher tel quel le poster durable dans la
  grille serait une **régression**. Chaque tuile ferait :
  - un grant (SQL ×2, HEAD B2 éventuel, INSERT + COMMIT dans `media_playback_grants`) ;
  - un 302 `no-store` vers une URL présignée qui expire en 120 s, donc **jamais en cache
    navigateur d'une visite à l'autre** ;
  - un nouvel aller-retour TLS vers B2 eu-central (≈ 50–85 ms de handshake mesuré depuis le
    Mac, et le temps de réponse de B2 en plus).

  Le poster D5 fait 720 px de petit côté, q:v 3, médiane 168 Ko : il est aussi trop lourd
  pour une tuile. Je recommande au thread D5 un **miroir local** du poster ou de la vignette
  durable, servi par X-Accel et une URL stable immuable. B2 resterait la source durable,
  pas le chemin de grille.

### P2-6 · Funnel : `auth_request` double la charge backend et bloque `index.html`

- **Preuve dans le code** : `ops/tailscale/nginx.conf:94-106` et `166-170`. Chaque `/api/*`
  et `/` déclenchent d'abord `/_funnel_session` → `/auth/me`. Cette route est `async`, avec
  une requête `UserDiverAccess` et un `calendar_enabled` sur la boucle, plus une résolution
  de session en threadpool.
- **Impact** : il faut doubler le nombre de passages backend sur Funnel (≈ 30 requêtes
  utilisateur → ≈ 60 passages au premier écran). Pendant un gel P0-1, même la page
  d'accueil attend.
- **Certitude** : élevée sur le mécanisme ; coût unitaire non mesuré.
- **Correction** : mettre en cache le résultat d'`auth_request` dans nginx
  (`proxy_cache` sur le cookie, TTL de 5 à 10 s), ou ne garder `auth_request` que pour le
  HTML, puisque le backend applique déjà l'authentification sur `/api`.
- **Compromis** : une révocation prend effet jusqu'à 10 s plus tard sur Funnel. Il faut
  décider explicitement quelle défense en profondeur conserver.
- **Test** : compter les requêtes backend par chargement de page, avant et après.

### P2-7 · Cascade de boot : `/auth/me` bloque l'affichage du snapshot local de la bibliothèque

- **Code** : `AuthGuard` (`frontend/src/router.tsx:527-537`) affiche le splash tant que
  `checking` est vrai. La clé du snapshot (`libraryKey(user)`) dépend de la réponse de
  `/me`. Une visite « chaude », avec un snapshot de moins de 24 h dans `localStorage`,
  attend donc quand même un aller-retour complet.
  - La bibliothèque attend aussi `/divers` (`Promise.all`, `frontend/src/pages/Dives.tsx:255-258`).
  - Le snapshot ne contient pas d'URL de poster : il faut l'appel média en plus. Le lot 1
    du parent l'ajoute.
- **Mesure (non authentifiée)** : un aller-retour Funnel coûte environ 75 à 110 ms de TTFB
  depuis le LAN via le relais public, contre environ 27 ms en LAN HTTPS.
- **Correction** : rendre le dernier snapshot de façon optimiste, avec la clé utilisateur
  stockée, pendant la vérification de `/me`, et lancer `/dives/library` en parallèle de
  `/me`. Purger en cas de 401, comme c'est déjà le cas.
- **Compromis** : un flash de données de la session précédente si l'appareil est partagé
  et la session expirée. Le risque est faible car le logout purge déjà le snapshot ; il
  reste à valider.

### P2-8 · La préparation spéculative de lecture concurrence le premier écran et alimente P0-1

- **Code** : `DiveThumbnail` déclenche `prepareLibraryPlayback` pour les 2 premières tuiles
  visibles (`frontend/src/components/DiveThumbnail.tsx:28-33`). Il en découle des
  `GET /media/{uuid}/status` (le chemin verrouillé de P0-1) et le `preload=auto` de proxies
  d'environ 1 Mo, pendant que les posters chargent.
- **Correction** : différer la préparation jusqu'au premier poster affiché ou à
  `requestIdleCallback`. Utile surtout **après** P0-1.
- **Certitude** : moyenne sur l'impact. Le gain au clic existe et doit être préservé.

### P2-9 · Des onglets expirés interrogent le serveur sans fin

- **Preuve** : 42 333 réponses 401 sur Funnel en 7 jours, venant d'un même navigateur Mac :
  `ws/sync` 23 579, `unread-count` 9 222, `notifications`, `achievements` et `updates`
  ≈ 3 000 chacun.
- **Correction** : arrêter les pollers et reconnecter le WebSocket avec un backoff après un
  401, en déclenchant `AuthContext.refresh`.
- **Impact** : du bruit de fond (≈ 6 000 passages backend par jour). C'est peu, mais
  inutile. Certitude élevée.

### P3-10 · Bundle et sourcemaps

- **Mesure** : entrée de 229 Ko gzip (617 Ko brut), dont environ 143 Kio de source de
  traductions **toutes langues**. Les sourcemaps sont **publiques sur Funnel** : le code
  source complet est téléchargeable sans session.
- **Correction** : charger les traductions de la langue active à la demande et générer des
  sourcemaps `hidden`.
- **Certitude** : élevée. L'impact sur le premier écran est modéré (fichier en cache
  immuable dès la 2ᵉ visite).

### P3-11 · Disque partagé et co-locataires

- **Constat** : Postgres (WAL, fsync), le cache média (posters, proxies, staging des packages
  de migration), Docker et le swap partagent un **HDD 5400 tr/min**. Sur une fenêtre de
  30 s : flush moyen de 39 ms, écriture moyenne de 13 ms, PSI I/O `some` à 16 %.
  - Jellyfin, sonarr, qbittorrent (sur l'autre disque) et synapse tournent sur le même hôte,
    qui n'a que 2 cœurs.
  - La base fait 86 Mo et tient en `shared_buffers` (taux de hit de 100 %) : **les lectures
    SQL ne vont pas au disque, seuls les COMMIT y vont**.
- **Correction structurelle** : déplacer les données Postgres et le cache média sur SSD.
  À court terme, retirer les COMMIT du chemin de lecture (P1-3, P0-1) produit l'essentiel
  de l'effet.
- **Certitude** : élevée sur la topologie. L'attribution par requête manque
  (`track_io_timing` et `track_wal_io_timing` sont désactivés).

### P3-12 · Couplage entre migration et utilisateurs

- **Constat** : les `package/slots` prennent entre 0,5 et 18 s : 44 requêtes au-dessus de
  500 ms depuis 09:02.
  - La partie lourde est bien déportée (`asyncio.to_thread`).
  - En revanche, l'écriture du staging par blocs de 1 Mio reste synchrone sur la boucle
    (`media.py:1749`) et vise le HDD.
  - La vérification par relecture complète depuis B2 double le trafic du lien montant.
- **Impact** : sous P0-1 et P0-2, la migration et les utilisateurs se gênent mutuellement
  (voir le 08:35:55 ci-dessus).
- **Correction** : déporter l'écriture du staging dans le threadpool et, si nécessaire,
  mettre en pause la migration quand des utilisateurs sont actifs. Une fois P0-1 réglé, à
  mesurer avant de décider.

## Ce qui n'est **pas** un goulot aujourd'hui (mesuré)

- **DNS et TLS B2 depuis le conteneur** : `getaddrinfo` médian à 4,4 ms, 0 échec sur 10 ;
  TCP+TLS ≈ 35 ms. Le correctif DNS du 20 octobre tient.
- **Lectures SQL** : la base est entièrement en mémoire.
- **Décodage JPEG sur desktop** : ≤ 77 ms pour 15 images.
- **`/dives/library`** : handler `def` (threadpool), pas de N+1 visible. Le lot 1 du
  parent y ajoute 2 SELECT dans ce même handler `def` : il ne passe **pas** par le verrou
  de P0-1. Il est compatible, mais son gain peut être masqué par les gels.

## Télémétrie pédagogique proposée (pour comprendre avant et après)

1. **Lag de boucle** : une tâche `asyncio` qui mesure la dérive d'un `sleep(0.1)`, publiée
   en log et en métrique (p50, p99, max par minute). C'est le signal direct de P0-1 et P0-2.
2. **`Server-Timing`** sur chaque réponse : `auth;dur=`, `db;dur=`, `lock;dur=`, `app;dur=`.
   Visible dans l'onglet Réseau du navigateur, sans outil supplémentaire.
3. **nginx** : un `log_format` avec `$request_time $upstream_connect_time
   $upstream_response_time` sur les deux front doors, pour obtenir p50 et p95 par route
   à partir des logs.
4. **Postgres** : `log_lock_waits=on`, `track_io_timing=on`, `track_wal_io_timing=on`, pour
   attribuer coûts de COMMIT et attentes de verrou.
5. **Navigateur** (échantillonné) : temps jusqu'à `/me`, jusqu'à la bibliothèque, jusqu'au
   premier poster (`load` de l'élément et Element Timing ou LCP) et jusqu'à la première
   image vidéo au clic. Les envoyer avec un `sendBeacon` borné, sans identifiant de média.

Ces cinq signaux permettent de tracer un chargement comme le schéma 1, avec des durées
réelles par segment : réseau, temps serveur, attente de verrou ou de disque, décodage.

## Plan de remédiation priorisé

| # | Action | Quoi mesurer pour trancher | Taille |
|---|---|---|---|
| 1 | P0-1 : supprimer `reclaim` et le verrou des chemins de lecture `status` ; handlers `def` ; `lock_timeout` | `advisory_lock_probe.py` < 1 s ; kills en grappe → 0 | S |
| 2 | Télémétrie 1 à 3 (lag de boucle, Server-Timing, request_time nginx) | base avant et après pour tout le reste | S |
| 3 | P0-2 : `member_access_context` et routes média en synchrone | `event_loop_probe.py`, lag de boucle p99 | M |
| 4 | P1-3 : écriture d'accès limitée + `immutable` sur les posters | COMMIT par rafale ; ratio 304/200 | S |
| 5 | P1-4 : WebSocket sans session de routeur | kills isolés ≈ 0 ; `pool.checkedout()` | S |
| 6 | P1-5 : vignette de grille et miroir local (à coordonner avec D5) | octets du premier écran ; mémoire iPhone | M |
| 7 | P2-7 / P2-8 : boot optimiste, préparation différée | temps jusqu'au premier poster (télémétrie 5) | S |
| 8 | P2-6 / P2-9 / P3-10 : Funnel, pollers, bundle | passages backend par page ; 401 par jour | S |
| 9 | P3-11 : SSD pour Postgres et le cache | flush moyen ; PSI | infra |

Les étapes 1 et 2 passent avant le lot 1 du parent, ou dans la même release : sinon,
l'avant/après du lot 1 sera dominé par les gels.

## Fichiers de preuve

- `docs/audits/media-startup-opus/prod-evidence-2026-10-25.json` : agrégats de production
  sans identifiants, URL ni jetons ; chronologie de l'incident de 08:34.
- `advisory_lock_probe.py`, `advisory-lock-probe.json`, `advisory-lock-probe-user-only.json`
  : reproduction de P0-1.
- `event_loop_probe.py`, `event-loop-probe-commit39.json`,
  `event-loop-probe-commit150.json` : modèle de P0-2 et P1-3.
- `decode_probe.cjs`, `decode-probe.json` : décodage sur images synthétiques.
- `docs/audits/media-startup-opus-brief.md` : brief.

Pour rejouer : `initdb` et `pg_ctl` locaux avec `idle_in_transaction_session_timeout=5000`,
puis
`python advisory_lock_probe.py "postgresql+psycopg2://USER@/postgres?host=/tmp/SOCKDIR&port=PORT"`
dans un venv contenant `fastapi==0.104.1 uvicorn[standard]==0.24.0 sqlalchemy==2.0.23
psycopg2-binary "httpx<0.28"`.
