# Lot 2 — URLs signées, ThumbHash et thumbs de grille

25 octobre 2026. Empilé sur le lot 1 (`58b6da76`, incluant #158).
Travail et commits locaux uniquement. Aucun push, PR, merge, appel à ship.sh,
migration, génération de médias ou redémarrage en production. Le choix D5 et
les URLs de transport des évaluations ne sont pas modifiés.

## Livraison

- `playback_url` peut émettre une capability HMAC-SHA256 :
  `/media/cache/signed/<sha256>/<chemin-cache>?expires=…&sig=…`.
  Le chemin complet, le checksum et l'expiration font partie du message signé.
  Les producteurs existants restent derrière leurs contrôles d'accès ; la
  bibliothèque ajoute ses métadonnées uniquement après le filtrage existant.
  Aucune requête SQL, lecture d'image ou génération n'est ajoutée au signer.
- Les deux nginx servent ces URLs directement depuis leur montage **lecture
  seule** du cache : aucune session, `auth_request`, requête backend ou B2.
  GET/HEAD, Range et ETag/304 restent natifs. Méthodes autres, signature absente,
  expirée ou altérée et symlinks sont refusés. Les logs des capabilities sont
  désactivés dans cette location, y compris les erreurs de fichiers.
- Expiration arrondie par fenêtre de 15 minutes, validité **60 à 75 minutes**.
  Les lectures dans la même fenêtre réutilisent exactement l'URL et le cache.
  Cache privé immuable : `max-age=min(3600, expiration-maintenant)`, pour qu'une
  nouvelle réponse ne prolonge pas sa fraîcheur au-delà de l'expiration.
- Les nouveaux fichiers finalisés incluent leur checksum dans leur nom ; les
  posters durables de #158 avaient déjà un chemin propre au contenu. Les thumbs
  sont eux aussi adressés par leur SHA-256 complet. Un refresh ne réécrit pas
  les octets utilisés par les anciennes URLs. Les vieux fichiers sont conservés.
- Les anciennes routes `/api/v1/media/cache/{id}/play` restent disponibles avec
  leurs contrôles et leur cache du lot 1. Secret absent/invalide, flag désactivé
  ou checksum inconnu : émission de l'ancienne URL. Le nouveau secours
  `/api/v1/media/cache/{id}/thumb?v=…` applique les mêmes contrôles d'accès.
- La rendition de grille **thumb** est un fichier WebP subordonné à la ligne du
  poster, référencé par `thumb_storage_path`, `thumb_checksum_sha256` et
  `thumb_size_bytes`. Pas de nouveau job Mac ni de deuxième ligne susceptible
  de dériver du poster. Largeur maximale 480 px, hauteur maximale 1920 px, sans
  agrandissement. Qualité adaptative 72/60/48/36/24 pour viser ≤40 Ko ; les images
  unies peuvent être bien plus petites, les cas extrêmes peuvent dépasser la
  cible au dernier palier. WebP est compatible avec les navigateurs iOS 16+.
- ThumbHash opaque RGBA, calculé sur ≤100×100 pixels, stocké en base en base64.
  Un hook ORM commun couvre finalisation Mac, import navigateur et création /
  refresh `durable_poster_cache` de #158. Il ne s'exécute pas lors des lectures
  ou mises à jour de `last_accessed_at`. Poster illisible : métadonnées nulles,
  poster existant conservé ; jamais de ThumbHash/thumb d'une ancienne version.
- `/dives/library`, batch et statut individuel exposent `thumbhash` et
  `thumb_url`. La bibliothèque fait une seule requête supplémentaire bornée
  aux UUID déjà autorisés, sans N+1. `DiveThumbnail` décode le ThumbHash dès le
  rendu des données bibliothèque, puis essaie **thumb → poster → vidéo locale**.
  Le poster n'est pas téléchargé si le thumb fonctionne. Un hash invalide
  conserve le placeholder habituel. Aucun original caméra ne devient une tuile.

## Vérification nginx en production : lecture seule

Les seuls appels SSH ont exécuté `nginx -V` et `ls /usr/lib/nginx/modules` dans
`dive-analyser-nginx-1` et `dive-funnel-funnel-proxy-1`.
Les deux sont **nginx 1.29.4**, avec `--with-http_secure_link_module` et
`ngx_http_js_module.so` déjà installé.

**Choix explicite :** secure_link est compilé mais sa signature native est un
MD5 secret, pas un HMAC. Utiliser le njs déjà fourni est l'alternative la plus
simple qui respecte HMAC-SHA256, sans nouvel appel serveur ni paquet à installer.
Le module est chargé dans les deux configurations principales ; un `js_set`
valide HMAC et expiration avant le service statique. Sources techniques :
[secure_link](https://nginx.org/en/docs/http/ngx_http_secure_link_module.html),
[crypto HMAC njs](https://nginx.org/en/docs/njs/reference.html),
[js_set](https://nginx.org/en/docs/http/ngx_http_js_module.html).
Les deux Compose épinglent l'image stock `nginx:1.29.4-alpine` et montent le
script, le template et la validation d'environnement ; aucune image spécifique.

## Avant/après local

Voir les JSON `lot2-browser-before.json`, `lot2-browser-after.json` et
`lot2-browser-summary.json` à côté de ce fichier. Frontends **buildés**, servis
localement par Vite preview : avant = lot 1 à `58b6da76`, après = ce lot.
Onze JPEG synthétiques déterministes 1080×1920, environ 156 Ko chacun, aucun
média réel. La grille réelle regroupe ces 11 tentatives en **3 codes** ; les
mesures « premier écran » portent sur les 3 images effectivement visibles,
pas sur une prétendue grille de 11 images visibles.

Le scénario `browser_probe.cjs` d'origine est étendu par un mode fixture local
facultatif. Même frontend, navigation `/dives`, desktop 1280×800 (deux rounds)
et téléphone 390×844 (un round), chaque fois navigation froide puis répétée.
Les réponses média ont le **même délai artificiel de 1080 ms avant/après** pour
isoler le poids et le rendu ; il ne s'agit pas d'une mesure du gain de nginx
sur le handler Python de production. Le routage Playwright désactive le cache
HTTP : « warm » désigne ici une navigation répétée, **pas un cache HTTP chaud**.
La couleur est le ThumbHash après deux requestAnimationFrame, ou le chargement
de la première image avant. Ce sont des marqueurs DOM/rendu et load, pas une
analyse optique de pixels. Le placeholder sombre précédent n'est pas compté
comme une couleur issue du média. Tous les fichiers sont synthétiques.

| Mesure | Avant | Après |
|---|---:|---:|
| 11 fichiers synthétiques, octets utiles | 1 736 326 | 420 934 (−75,8 %) |
| 3 images du premier écran, avec overhead Resource Timing | 475 992 | 116 230 (−75,6 %) |
| 1280x800, navigation froide : première couleur | 1293 ms | 168 ms |
| 1280x800, navigation froide : première image chargée | 1293 ms | 1255.5 ms |
| 390x844, navigation froide : première couleur | 1259 ms | 102 ms |
| 390x844, navigation froide : première image chargée | 1259 ms | 1192 ms |

Les requêtes autour de l'écran, y compris le chargement anticipé natif des
`img loading=lazy`, ne se limitent pas aux trois images visibles : desktop
475 992 → 270 302 octets, téléphone 634 110 → 309 212 octets. Le navigateur
anticipe davantage de petits thumbs que de grands posters. La baisse des
seules images visibles reste de 75,6 %. La première image attend encore le
délai artificiel commun ; ce test prouve surtout la couleur immédiate et la
réduction du poids, pas une disparition mesurée des 1,08 s serveur.


La validation de service nginx est distincte et réelle : nginx+njs compilés
localement dans `/tmp` (nginx 1.29.4, njs 0.9.4), test HTTP sans backend en
écoute. Les deux configurations de déploiement passent aussi `nginx -t`, en
adaptant seulement chemins machine, DNS et `epoll` pour macOS. Les conteneurs
Docker ne sont pas disponibles sur ce Mac ; leur entrypoint et les montages
Compose devront être vérifiés sur la cible avant activation. Aucun « après »
production n'est revendiqué pour les 1,08 s du handler ou le premier écran.

## Migration et backfill : application manuelle requise

**Appliquer `backend/migrations/add_poster_visuals.sql` à la main AVANT le
backend.** Quatre colonnes nullables additives, migration idempotente vérifiée
sur Postgres 16 local. Aucun runner automatique et aucune application prod ici.
Conserver le schéma lors d'un rollback.

Le backfill n'est ni au démarrage ni dans un GET. Une invocation traite au plus
8 posters par défaut, 32 maximum, en ordre d'id ; retourner et conserver
`after_id`, arrêter à `scanned=0`. Le script abaisse lui-même sa priorité de 10.
Il lit uniquement les posters locaux existants, verrouille ses lignes contre
les refreshs et commit sa passe. À exécuter seulement lors d'une future fenêtre
opérateur autorisée, par exemple depuis le conteneur backend :

```sh
PYTHONPATH=/app python scripts/backfill_poster_visuals.py --limit 8 --after-id 0
```

Plancher **26 Gio libres** avec marge de 1 Mio avant encodage et recontrôle de
l'espace exact avant écriture. Sous le plancher, le ThumbHash peut être stocké
mais aucun thumb n'est écrit. Le curseur avance aussi sur un échec : recommencer
une passe depuis 0 après récupération du disque ou réparation des posters.
Pas de téléchargement d'original, pas de nouvelle tâche Mac. Le chemin de lecture
ne répare rien. Les fichiers orphelins après rollback/refresh sont conservés ;
pas de purge automatique de ces fichiers dans ce lot. Garder une marge disque
et ne pas paralléliser les backfills avec des producteurs intensifs.

## Secret, configuration et ordre de déploiement futur

1. Appliquer la migration additive ci-dessus. L'ancien backend fonctionne avec
   les colonnes supplémentaires. Préparer backend/frontend et dépendance Python
   `thumbhash==0.1.2` ; Pillow est déjà présent.
2. Provisionner un secret **aléatoire de 32 octets encodés en 64 caractères hex
   minuscules** dans `~/.config/diveanalyzer/browser-upload.env`, mode **0600**,
   hors dépôt. Génération possible avec `secrets.token_hex(32)` dans un script
   qui écrit directement le fichier privé : ne pas copier le secret dans un
   terminal partagé, une conversation ou une commande journalisée. Conserver
   les autres variables du fichier. Ajouter `MEDIA_SIGNING_SECRET=<valeur>` et
   initialement `MEDIA_SIGNED_URLS_ENABLED=false`. `ci/ship.sh` source déjà ce
   fichier pour le backend, y compris rollback ; il n'a pas été modifié ni lancé.
3. Livrer backend + frontend via la procédure normale lors d'une autorisation
   de déploiement. Le mode non signé reste fonctionnel et permet les thumbs via
   l'ancienne voie authentifiée. Aucune mise à jour Mac nécessaire.
4. Appliquer **manuellement les deux configurations nginx/Compose** : LAN
   `docker-compose.yml`, `nginx/` ; Funnel `ops/tailscale/docker-compose.yml`,
   `ops/tailscale/main.conf`, `ops/tailscale/nginx.conf`. Pour chaque invocation
   Compose, exporter les variables du même fichier privé (`set -a`, source,
   `set +a`) ; le projet Funnel distinct ne les hérite pas automatiquement.
   Recréer les deux proxies pour charger les nouveaux montages, le module et
   l'environnement ; un simple reload ne suffit pas. Le template officiel
   d'entrypoint génère `/etc/nginx/conf.d/media-signing.conf`. Le dossier conf.d
   LAN reste inscriptible dans le conteneur, seul default.conf est monté en RO.
   Le script 19 refuse un secret non vide de format incorrect avant envsubst.
   Ne pas utiliser `nginx -T` : il afficherait le secret généré dans la config.
5. Vérifier `nginx -t` dans chaque cible, module njs chargé, même secret, cache
   monté RO, fichiers lisibles et réponses signées 200/206/304 avec contrôles
   négatifs 403. Puis activer `MEDIA_SIGNED_URLS_ENABLED=true` sur le backend
   par la procédure normale. Toujours nginx prêt **avant** émission des liens.
   Les routes de secours restent disponibles. L'activation n'altère pas D5.
6. Lancer ensuite le backfill borné à faible priorité, si autorisé et disque
   suffisant ; contrôler les tailles et la charge entre les passes. Refaire la
   mesure sur la production uniquement après une autorisation séparée.

**Révocation et retour arrière.** Retirer l'accès empêche l'émission de nouvelles
capabilities mais ne révoque pas une capability déjà émise, transférable à un
porteur pendant au plus 75 minutes. Pour révoquer toutes les capabilities au
réseau, désactiver l'émission puis changer le secret partagé et recréer les deux
nginx avec la nouvelle valeur avant de réactiver le backend. Les anciennes
signatures sont alors rejetées ; les octets déjà dans un navigateur ne peuvent
pas être rappelés. Leur fraîcheur signée ne dépasse pas l'expiration. Le cache
privé immuable un an des anciennes routes du lot 1 conserve sa limite de
révocation déjà documentée. Ne pas partager ni journaliser les URLs signées.
Pour revenir au service Python/X-Accel : flag false côté backend ; conserver
les deux locations signées le temps de laisser expirer les liens en circulation.

## Vérifications et reproduction

- Commit d'implémentation : `a2b43d67`.
- **145 tests backend ciblés passent**, dont **7 intégrations Postgres** (5 du
  lot 1, migration idempotente et backfill du lot 2), **2 tests nginx+njs**
  (service HTTP réel et parsing des deux configurations), production/refresh
  durable #158 avec vraie image, contrôle d'accès du secours thumb, cache
  versionné, import/lecteur existants et vecteur ThumbHash identique au JS de
  référence. Familles exécutées : `media_startup_lot2`, `nginx_signed_media_lot2`,
  `postgres_media_startup_lot2`, `postgres_media_startup_lot1`,
  `media_startup_lot1`, `library_media_payloads`, `media_node`,
  `durable_poster_cache`, `cache_content_version`, `p5_auth_playback`,
  `p6_playback_default`, `evaluation_requests`, `library_bounded_player_flow`.
- **773 tests frontend / 94 fichiers passent** avec
  `NODE_OPTIONS=--no-experimental-webstorage npx vitest run` ; **build
  TypeScript/Vite/service worker passe**.
- Une passe supplémentaire `test_browser_upload.py` donne deux échecs HDR
  PQ/HLG sur ce Mac : ffmpeg local ne fournit pas `zscale` (confirmé par
  `ffmpeg -filters` et une conversion minimale : `No such filter: zscale`).
  L'échec est dans `prepare_video`, avant toute écriture ORM, dans un fichier
  inchangé par ce lot. Les 71 autres tests de cette passe passent. Pas de
  correction du pipeline HDR hors périmètre.
- `python3 ci/release-notes.py validate` et `git diff --check` passent.
- Le Postgres local jetable a été arrêté après les tests. Aucun service de
  production n'a été modifié ; aucune génération de poster/thumb en prod.


Reproduction locale (aucun cookie requis en mode fixture) :

```sh
PYTHONPATH=backend python docs/audits/media-startup-opus/lot2_synthetic_fixture.py /tmp/lot2-fixture
# Préparer deux builds/preview : lot 1 à :5186, ce lot à :5187.
PW_PATH="$PWD/frontend/node_modules/playwright" BASE=http://127.0.0.1:5186 \
  PROBE_FIXTURE=/tmp/lot2-fixture/fixtures.json PROBE_VARIANT=before PROBE_WAIT_MS=2500 \
  node docs/audits/media-startup-opus/browser_probe.cjs
# Même commande : BASE=:5187 et PROBE_VARIANT=after.
```

Tests PG optionnels : `MEDIA_STARTUP_TEST_DATABASE_URL` doit pointer vers une
base locale jetable `calendar_test_*` (mêmes garde-fous que le lot 1).
Tests nginx optionnels : fournir `LOT2_NGINX_BINARY` et `LOT2_NGINX_MODULE` vers
un nginx local avec le module njs ; les tests n'appellent aucun hôte de prod.
Release note additive : `library-small-thumbnails`, backend + frontend. La
signature reste désactivée par défaut et nécessite la configuration opérateur.
