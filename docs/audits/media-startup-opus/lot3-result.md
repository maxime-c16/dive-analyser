# Lot 3 — démarrage local et posters animés

25 octobre 2026, empilé sur `be7b3d61` (lots 1 et 2, enrichissement après commit inclus).
Implémentation : commit local `5707ff93`.
Travail local uniquement : aucun SSH, push, PR, merge, ship.sh, écriture,
migration ou génération en production.

## Résultat et choix

Le statut détaillé et les helpers frontend démarrent sur le proxy local 720p,
puis 360p si nécessaire, via les URLs du lot 2. Sans proxy, Light D5 puis HQ D5
restent les sources de démarrage ; l'original et les préparations gardent leurs
secours. Le poster du lecteur privilégie le thumb, puis le poster local,
puis seulement le poster D5 s'il n'existe aucune couverture locale.

**Choix prudent prévu par le brief : D5 reste une option de qualité explicite.**
Aucun deuxième décodeur, préchargement D5 ou swap automatique pendant la lecture.
La revalidation conserve un proxy déjà présenté s'il est toujours annoncé.
Il n'y a donc aucun changement de currentTime ni coupure imputable à une bascule
automatique. Le cycle explicite devient Preview → Light → HQ → Original,
avec déduplication des alias ; les commandes explicites gardent leur comportement
existant de changement de source. Le mécanisme de récupération des erreurs de
décodage est conservé ; son choix Preview peut maintenant désigner le proxy local,
ce qui est nécessaire pour rendre le démarrage local récupérable. Les chemins
spécifiques des évaluations ne sont pas modifiés (régressions exécutées).
Les séries, qui utilisent déjà le helper commun de lecture, profitent du même
ordre local en premier. D5 et ses preuves restent la source durable, inchangée.

`animated` est une entrée distincte dans `media_cache_entries`, jamais une source
vidéo du lecteur. Le serveur la produit uniquement depuis un proxy local ready
720p ou 360p, sans original distant, Mac, job interactif ou génération au GET.
FFmpeg produit la première seconde, 8 images/s, largeur au plus 360 px sans
agrandissement, WebP animé en boucle. Qualités 55/35/20 : au-delà de **80 000 octets**
au dernier essai, l'animation est abandonnée et le statique reste utilisé.
Une seule thread encode/décode et une thread de filtre ; chaque subprocess a un
timeout de 30 s, au plus trois essais. Priorité abaissée par le script et `nice`.

Fichier `animated/<préfixe>/<SHA-256>.webp`, clé de génération liée à l'id,
au chemin et au checksum du proxy, publication après vérification que celui-ci
est encore ready et inchangé. Une contrainte unique existante évite les doublons
concurrents de clé ; le perdant est compté en échec et peut être rejoué.
Les connexions SQL sont rendues avant FFmpeg. Aucun nouveau hook async ou event loop.
Les anciennes versions et fichiers orphelins sont conservés : pas de purge ajoutée.
Les lignes animated restent évictables par le nettoyeur de cache existant.

Bibliothèque et batch transportent l'URL via leurs lectures bornées existantes.
Le signer du lot 2 signe le fichier ; flag/secret absents, le secours authentifié
existant reste disponible. La grille emploie un `<img>` animé seulement lorsque
la tuile intersecte réellement le viewport, reduced-motion est désactivé et
saveData n'est pas actif. Les changements de préférences sont écoutés ; sortir
du viewport remet le statique. Échec animé → thumb → poster → placeholder.
Un thumb ou animated annoncé empêche la création d'un `<video>`, même après erreur
image. Les clips sans ces renditions gardent leur secours vidéo local antérieur.

## Avant/après local

Référence production fournie : premier Mio médian **1,90 s D5 / 0,70 s local**,
light **4,6 Mo / proxy 0,96 Mo**. Ce ne sont pas des mesures de première image.
Aucun après production n'est revendiqué.

Mesure reproductible sur le vrai `DiveVideoPlayer` avec deux MP4 H.264
synthétiques de 3 s : proxy 640×360, light 1280×720 CRF18. Trois essais alternés
par politique, Chromium du navigateur collaboratif T3, HTTP localhost no-store,
aucune latence de grant/TLS/B2 simulée. Le mode baseline masque le cache local
pour reproduire l'ancienne sélection Light ; ce n'est pas un checkout de l'ancien
lecteur. Le chronomètre part du clic Start, s'arrête au premier
`requestVideoFrameCallback`. Observation pendant 1,8 s ; le petit serveur compte
les octets effectivement écrits, y compris les multiples requêtes Range.

- Light avant : **41,4 / 18,1 / 23,4 ms**, médiane **23,4 ms**.
- Proxy après : **21,6 / 9,6 / 21,1 ms**, médiane **21,1 ms**.
- Octets light : **1 817 227 / 1 817 227 / 637 579** ; proxy : **300 491** à chaque essai.
  Les demandes Range et annulations expliquent les répétitions de bytes light ;
  ces chiffres ne représentent pas un ratio de taille des fichiers de production.
- **0 stall après première image, 0 réinitialisation après première image** dans
  les six essais. Aucune requête Light dans les essais proxy. Pas de swap
  automatique à mesurer : l'option explicite choisie évite ce risque.

Preuve brute : [lot3-playback-measure.json](lot3-playback-measure.json).
Le faible gain de temps sur localhost ne prédit pas le gain sur Funnel/B2.
Il faut comparer les mêmes clips, réseaux et navigateurs après une release autorisée.
Les unités vérifient aussi qu'une revalidation D5 ne remplace pas un proxy présenté.

Rejouer sans données privées :

```sh
mkdir -p frontend/node_modules/.cache
ffmpeg -v error -f lavfi -i testsrc2=size=640x360:rate=30 -t 3 -c:v libx264 -pix_fmt yuv420p -movflags +faststart -y frontend/node_modules/.cache/library-preview-synthetic.mp4
ffmpeg -v error -f lavfi -i testsrc2=size=1280x720:rate=30 -t 3 -c:v libx264 -crf 18 -pix_fmt yuv420p -movflags +faststart -y frontend/node_modules/.cache/library-light-synthetic.mp4
python3 docs/audits/media-startup-opus/lot3_fixture_server.py
# autre terminal
npm run dev --prefix frontend -- --host 127.0.0.1 --port 3022 --strictPort
```

Ouvrir `/e2e/fixtures/media-local-start.html?baseline` puis sans `?baseline`.
Avant le clic, installer une MutationObserver qui attache rVFC au nouveau video,
et compter `waiting`/`emptied` après la première image. `/stats` sur 3023 fournit
les compteurs par source avant/après chaque essai. Les fixtures sont dev-only ;
les MP4 ignorés sous node_modules ne sont pas committés.

## Validation

- **777 tests frontend / 94 fichiers passent**, puis **94 tests ciblés / 4 fichiers passent** après les dernières modifications
  (cycle Preview/Light/HQ/Original, conditions de grille, cache de previews).
- **62 tests backend passent** dans la passe lots 2/3 + D5 + bibliothèque,
  dont roundtrip animated PostgreSQL et les trois contrats D5 PostgreSQL.
- **73 tests passent** dans la passe complémentaire lot 3 + D5 + évaluations,
  incluant concurrence avec refresh du proxy et couverture locale. Ces passes
  se recouvrent ; les nombres ne sont pas à additionner.
- **8 intégrations Postgres lots 1/2 passent** sur une base jetable locale
  `calendar_test_media_lot1`, port 18543 ; les 3 D5 initialement skipped ont
  ensuite été exécutées dans la passe de 62 avec leur variable dédiée.
- Dernière passe du fichier lot 3 : **4 tests passent**, transport bibliothèque/batch
  signé inclus.
- Build TypeScript/Vite/PWA, `git diff --check`, validation release notes : OK.
- FFmpeg Homebrew 8.1.2 n'inclut pas WebP ; pour le test réel local, PATH pointe
  vers le binaire FFmpeg 7.1 fourni par imageio-ffmpeg 0.6.0 dans le venv temporaire.
  Aucune dépendance applicative ajoutée. Le conteneur serveur utilise son FFmpeg
  Alpine ; vérifier `ffmpeg -encoders` et `libwebp_anim` avant le futur backfill.
  Les tests vérifient un vrai WebP multi-image, sa durée, sa taille, le hash,
  l'idempotence, le plancher disque et la publication PostgreSQL.

## Migration, backfill et ordre de déploiement (non exécutés)

Aucune migration propre au lot 3 : `rendition` est déjà un varchar et les colonnes
requises existent. **Le lot 2 exige toujours `add_poster_visuals.sql` avant backend.**

1. Appliquer les prérequis/migration/config nginx/signature des lots 1 et 2
   selon leurs comptes rendus, lors d'une future release autorisée.
2. Livrer backend puis frontend (services requis : les deux). Un frontend ancien
   conserve la lecture ; un backend ancien reste compatible avec les helpers.
   Aucune mise à jour Mac, B2, ledger D5 ou schéma D5 nécessaire.
3. Vérifier l'encodeur WebP du conteneur et le disque. Ne pas paralléliser avec
   migration/encodages intensifs. Le même plancher du lot 2 (**26 Gio**) est
   appliqué avec marge 1 Mio avant encodage, puis recontrôle avant publication.
4. Exécuter explicitement une passe dans le conteneur backend à basse priorité,
   éventuellement sous `ionice -c3` si disponible :
   `PYTHONPATH=/app nice -n 15 python scripts/backfill_animated_visuals.py --limit 4 --after-id 0`.
   Défaut 4, maximum 16 proxies par invocation. Conserver `after_id`, continuer
   avec le curseur retourné, arrêter à scanned=0. Le curseur avance également
   sur skip/échec : recommencer depuis 0 après récupération d'espace/réparation.
   Aucun cron ni démarrage automatique installé par ce lot.
5. Vérifier URL signée, animation visible, reduced-motion/saveData, fallback
   statique, clic sur clip avec/sans proxy et qualité Light/HQ/Original.

Rollback : ancien frontend/backend, conserver données et schéma du lot 2 ;
aucun nettoyage destructif. Les animations facultatives peuvent rester en cache.
Release note : `media-local-start-animated`, backend + frontend.
