# UX fixes — restants différés du cycle 3 (consultation UT + bornes de données)

- **Dates** : 2026-11-01 → 2026-11-02.
- **Sources** (lecture seule) : `docs/audits/ux-discovery-2026-11-01/` (six rapports + `SYNTHESE.md`),
  les triages déjà livrés `docs/audits/ux-fixes/feedback-reliability.md` (PR #181) et
  `library.md` (PR #182), et les audits du cycle 3 : profil 7 (reprise vidéo, propriétaire :
  autre agent), profil 9 (accessibilité, propriétaire : autre agent), profil 10 (hors domaine),
  profil 11 (grill-contradictions), profil 12 (grill-navigation).
- **Règle tenue** : rien de nouveau (pas de favori/planificateur/refonte), Like reste une réaction,
  les données « invraisemblables » ne sont jamais corrigées, contrats vérifiés avant chaque
  correction, périmètres de l'agent viewer (play/pause/aria/focus, noms Community) respectés.
- **Livraison** : deux PR empilées, indépendantes entre elles :
  1. **PR « consultation » (base `t3/feedback-reliability`)** : date de séance réelle dans les
     notifications, Évaluations qui ouvre la consultation, étiquettes lecteur/compteurs, aide
     Calendar « séances passées ».
  2. **PR « bornes de données » (base `t3/library-ux-state-search`)** : annuaire Community en une
     requête bornée, borne d'exploration par code, reprise bornée de profondeur, facettes hauteur,
     aides DD/SYNC/notes et le triage des derniers audits.
  Ordre de merge : #181 → PR consultation, puis #182 → PR bornes ; les deux serpentins sont
  indépendants (fichiers disjoints, aucun conflit).

---

## 1. Restants du brief initial de mission

### (1) Retour à une vidéo ancienne après pagination — **CONFIRMÉ, corrigé (reprise bornée ancrée)**

Constat (profil 4 + garde-fou #182 : « les pages précédemment chargées ne sont pas reconstruites au
retour ; pas de garantie de retrouver un clip situé sur une ancienne page »).

**Corrigé (PR bornes)** : au retour sur une URL nue (`/dives`), la bibliothèque restitue le
mémento de travail existant (#182) **et relit exactement les pages serveur déjà chargées, bornées**
(`MAX_RESUME_PAGES = 6`). Le mémento ne stocke que **deux nombres** — l'identité de la dernière
ligne chargée (`anchor`, un vrai id de plongée) et le nombre de pages — jamais des lignes, jamais
un état illimité ; la ré-lit passe par le curseur live (même requête que « Load more dives »), donc
ni rechargement de l'historique entier ni photo de mémoire privée. La borne est visible de
l'utilisateur : jamais une liste coupée sans signe. Tests : `Dives.libraryUx` (reprise exacte
des pages enregistrées, ancre présente, plafond 9 → 6 pages), `libraryWorkspace` (clamp du
plafond, corruptions réparées, objet à deux nombres uniquement).

### (2) Community en ~20 pages séquentielles — **CONFIRMÉ, corrigé**

**Cause vérifiée** (triage #181 : « cause confirmée côté code », `community.tsx`) : l'annuaire
était chargé par une boucle de ≤20 requêtes `/users?q=` séquentielles avant chaque tri de section.
**Corrigé** :
- Backend `GET /api/v1/users/directory` : une page keyset bornée (défaut 200, cap 500, flag
  `has_more` explicite), même contrat d'identité/stats que `search_members`, et des **totals
  complets calculés sur l'annuaire entier** (`members/divers/others/recent`) — 4 requêtes fixes
  par appel, aucun scan non borné, aucune ligne privée du viewer mise de côté (même clause de
  visibilité).
- Frontend `Community.tsx` : **une seule** requête à l'ouverture ; l'expansion « Afficher les N
  membres restants » est explicite, sous des entêtes de section plus jamais silencieusement
  tronqués (le total serveur fait foi tant que la suite n'est pas chargée).
- Tests backend (keyset sans chevauchement, `has_more` vrai aux deux bouts, totals généraux,
  compte lié exclus de mes pairs) et tests frontend adaptés (une requête, continuation
  explicite, jamais de promesse tenue en silence).

### (3) `getCodeAttempts` boucle toutes les pages — **CONFIRMÉ, corrigé**

**Cause vérifiée** (`codeSummariesApi.ts` : `do/while(cursor)` sans plafond interne, caches sans
bornes de taille). **Corrigé** :
- Le parcours s'arrête à un plafond interne (10 pages de 100 — fenêtre des plus récents, la
  réponse bibliothèque étant date décroissante) et remonte `{ items, capped }` explicite.
- La page d'analyse ne mente jamais un échantillon tronqué : la ligne « sample » devient
  « X essais affichés (sur {{total}}) · … » quand la fenêtre bornée est active, et rien d'autre ne
  se change : la « réussite 17 % » a maintenant **son titre de définition** (part des essais notés
  ≥ G = 7/10) et le rang « #220 sur 265 » son titre (classement par score parmi les plongeons du
  code, ex æquo partageant le rang). Aucun tooltip décoratif : uniquement les définitions réelles
  des métriques affichées, tirées du code.
- Les caches tentatives/sommaires sont bornés en mémoire (≤16 entrées, FIFO d'insertion).
- Tests : pages multiples jusqu'à épuisement réel (aucune coupure à la moitié), plafond atteint
  `capped = true` (10 sondes exactement), suites CodeAnalysis/Community au vert.

### (4) Judge Room par défaut — **CONFIRMÉ, corrigé (défaut consultation)**

`/evaluations` ouvre désormais l'onglet **Mes plongeons** (consultation de ses évaluations) ;
l'arrivée ne déale plus une étape plein écran sur le plongeon d'autrui. Le jugement reste un choix
explicite (`?tab=judge`, liens hérités conservés) et toute la mécanique de salle est inchangée
(reprise d'une session, pause, montages/démontages). Test : l'atterrissage consulte et **ne
convoque jamais** la scène ; le flux juge se vérifie tel quel au tab explicite.

### (5) Détails UX du brief
- **Date réelle de la séance dans la notification** — **corrigé** : les lignes `new_video` portent
  `dive_date` (une requête bornée `IN(ids)` par page, rappelée sur les continuations `before_id` et
  la réponse de marquage-lecture), et la page n'annonce « Séance du 18 oct. 2026 »/`Dive of Oct 18,
  2026` que quand elle diffère du jour d'arrivée (date naïve, pas de conversion ; plongeon supprimé
  = inconnu, jamais une panne). Les autres types d'événement ne changent pas (aucune devinette).
- **Attribution dans la grille** — **REJETÉ : déjà présent** ; preuve : `Dives.tsx` passe
  `showDiver={scope === "all"}` à la grille/liste et `LibraryCards` affiche le nom du plongeur dès
  que la donnée autorisée le porte (`person_name` + tooltip). Rien à recoder, rien à dupliquer.
- **Qualité vidéo/bouton cycle et compteur de contexte** — **corrigé en étiquetage** : l'info-bulle
  de la pastille énonce l'action (« au courant — cliquer pour changer de qualité »), et les
  compteurs `1/N` du lecteur et de sa navigation portent « Position x sur y dans la liste
  courante ». Aucun contrôle lecture/pause/aria réservé à l'agent vidéo n'est touché.
- **Aides DD/SYNC/notations en reprenant l'UI existante** — **corrigé** : le popover d'aide
  DB/SD/HU existant (unité `details/summary` de la barre de filtres, même famille `dives.*`) est
  étendu à SYNC (synchronisé, paire synchronisée), DD (valeur de difficulté, table World Aquatics)
  et l'échelle P/G/M/B/F avec les vrais seuils (P 10 · G 7 · M 4,5 · B 2 · F 0). FR/EN alignés,
  aucune surface nouvelle.

## 2. Triage des audits du cycle 3

### profil 12 (grill-navigation) — C1 confirmé/corrigé, C2 déjà connu, C3 pas un défaut

- **C1 (select Hauteur : options élaguées puis périmées)** — trois passages mesurés :
  `height=3m` → options `All/3m` (1m/3mp/5m disparues) ; bascule All par l'UI → URL
  `?performance=F` mais options périmées `All/3m` ; rechargement froid de la même URL → l'autre
  liste. **Cause** : les options dérivaient des lignes chargées. **Corrigé** :
  `GET /api/v1/dives/library/facets` — un `DISTINCT` sur le périmètre autorisé avec tous les
  filtres **sauf** la hauteur : même URL → mêmes options ; changer la dimension ne passe plus par
  All ; l'exclusion lineup/personnel de la Library reste le contrat de visibilité. En cas
  d'échec du facet, repli honnête sur les hauteurs des lignes chargées. Tests backend (3 :
  ensemble complet, filtres autres appliqués, hauteur sans effet sur ses propres options,
  scope-safe) + test frontend (l'appel facet sans `height`, options complètes avec `height=3m`).
- **C2 (changelog mélangé EN/FR)** — **consigné : déjà connu, pas nouveau** (instruction parent) :
  aucune action dans ce diff.
- **C3 (l'aide DB/SD/HU restée dépliée au retour)** — comportement volontaire de la SPA, surprise
  mineure : **REJETÉ sans changement** (instruction parent : ne pas changer sans raison).
- Audit12 : le triage couvre sans doublon ses constats (les mêmes URL, même sélect).

### profil 10 (hors domaine) — P3 corrigé, le reste rejeté avec preuve de contrat

- **P1 (codes 200A/010B/051B sans nom ni DD ; « 3mp »)** : les noms de figure sont **dérivés par
  regex du format FINA** (aucune table prénom), et les codes en « 0xx »/« 200 » (rotations = 0)
  ne sont PAS définis par la référence : à dessein ils restent affichés bruts (jamais attribuer un
  nom d'un autre plongeon). L'absence de DD sur un code hors FINA est le contrat (instruction
  parent : « 3mp peut être parfaitement valide ; le code pré-préparatoire peut ne pas avoir de
  DD »). **REJETÉ sans toucher aux données.**
- **P2 (échelle /10 peu visible en surface)** : les badges de score portent maintenant
  `title={{score}} sur l'échelle 0–10 — lettre {{letter}}` — un attribut, rien visuel. **Corrigé.**
- **P3 (aide restée DB/SD/HU)** : intégré par l'extension aide D8 (« aides DD/SYNC/notation » du
  brief). **Corrigé.**
- **P4 (Analysis : "success 17 %" et "#220 of 265" sans définition ; "median 0.0 · 15 att." passable)** —
  les définitions exactes sont désormais en title ; le paradoxe `0.0` est une donnée légitime
  (essais F = 0) : **REJETÉ sans correction de données**. L'animation des KPI est documentée par
  l'audit lui-même non déclenchée par clic ; reproduite en non-défaut.
- **P5 («Diver: Fanny», «Member since» sous des plongeons plus anciens ; relation compte/plongeuse)** :
  les plongeons antérieurs à l'inscription sont légitimes (consolidation/import) ; « Diver: Fanny »
  est aussi clair que le libr. permet sans un refonte ; la relation compte/plongeuse pourrait
  recevoir un libellé plus éclaircissant — décision produit possible, pas une correction : **REJETÉ**
  (aucun changement de libellé conservé).

### profil 11 (grill-contradictions) — un confirmé corrigé, quatre exacts par contrat

- **C1 (comptes du jour : Library 15/7/9/11/22 vs profil 16/7/13/15/9 ; graphe aligné Library)** —
  **REJETÉ comme contradiction métier : explicable par contrat, pas un bug de calcul.** La
  bibliothèque « My dives » ET le graphe du profil excluent les plongeons **LINEUP** (et appliquent
  la visibilité du viewer), alors que l'onglet **Dives** du profil liste ce que la plongeuse
  rattache à son compte (y compris les 010B/020C importés). Le graphe coïncide exactement avec la
  Library (31 = 15+7+9 ; 33 = 11+22) — c'est le contrat lineup qui les tient. Aucune refonte des
  métriques, aucune catégorie nouvellement incluse (instruction parent).
- **C2 (010B/020C invisibles dans Library)** — **REJETÉ, root cause C1** (la Library n'inclut pas
  ces familles par contrat ; elles sont visibles en profil et au graphe).
- **C3 (option 7m absente du select Hauteur)** — couvert par profil 12 C1 : les facettes remontent
  tous les hauteurs du périmètre autorisé (donc 7m dès qu'une ligne non-lineup autorisée en
  porte). **Corrigé avec C1/profil 12.**
- **C4 («Dernière activité» Fouiny 25d / 19d / ~20d)** — les définitions diffèrent : le profil
  calcule sur la plongeuse rattachée **hors lineup** (et les visibles), la carte Community mesure
  le partage **avec** les lineup, et la liste « Dives » du profil contient encore d'autres
  catégories. Trois « dernières » distinctes par construction, pas une même donnée corrompue :
  **REJETÉ sans refonte de métrique**, consigné comme décision produit possible (label explicite
  par écran).
- **C5 (Calendar « Rien de prévu dans les trois prochains mois » sous une séance passée)** —
  **CONFIRMÉ, corrigé** : la notice « à venir » ne s'affiche que dans la vue à venir ; la vue
  passée vide énonce « Rien d'enregistré sur les trois derniers mois »/« Nothing recorded in the
  past three months » (clés `strings.ts` de la même famille + test de page couvrant les trois
  cas : passée peuplée, passée vide, vue par défaut).

### profil 9 (accessibilité) et profil 7 (reprise vidéo) — **HORS PÉRIMÈTRE**

Le champ Community (accessible name) et les noms de cartes Community/HUD/Comments, comme les
contrôles play/pause/aria/focus du lecteur, sont l'ownership de l'agent accessibilité/playback. Ce
diff ne touche que **les données et la pagination** de l'annuaire ; le champ et les cartes gardent
leurs éléments DOM. Aucun conflit détecté ni signalé au parent.

## 3. Bornes, identités, erreurs (document d'ingénierie AGENT_ENGINEERING)

- **Lectures SQL bornées** : annuaire = page `IN (ids)` + trois agrégats fixes ; facettes = un
  `DISTINCT` ; dates de notification = un `IN` par page. Aucun scan non borné, aucun N+1, et
  l'authentification/le périmètre du viewer restent pilotés par `visible_dive_clause` dans chacun
  de ces réaffités (tests dédiés inclus).
- **Identité/async/pagination** : l'annuaire re-numéro ses continuations (génération/stale pages
  rejetées par change change de filtre), la reprise de profondeur vit sous le garde de génération
  de la bibliothèque, les répondants facettés tombent en repli silencieux (options des lignes)
  sans bloquer l'écran ; la même URL répond aux mêmes options.
- **Pagination explicite** : chaque liste qu'elle pagine ses limites (`limit` borné + flag/bouton),
  jamais un chiffre tronqué silencieuse.

## 4. Exécutions de tests (horodatées)

- Backend (venv gate, SQLite) sur l'arbre backend final du diff (suite intégrale **1889 passed /
  115 skipped, 0 failed** — facette et annuaire inclus ; les merges de master ultérieurs n'ont
  apporté que la note de release a11y et des docs, aucun fichier backend code). Cibles au vert :
  `test_library_height_facets` 3/3, `test_member_profiles` 20/20, `test_notifications` 19/19,
  `test_clip_downloads` ne présentant que des skips d'async du tier agent (jamais du changement).
- Frontend (Node 26, `NODE_OPTIONS=--localstorage-file` documenté), par branche :
  « bornes » (merge master inclus) — suite intégrale **112 fichiers / 880 tests, 0 failed**,
  `tsc --noEmit` propre et build Vite production (84 entrées de precache) ; « consultation » sur
  son head final — suites cibles de l'interplay master-merge au vert (ClipViewer + Notifications
  + Évaluations + Calendar + NotificationsPage = 133 tests) avec `tsc` et build production
  propres ; la babysitter CI gardera son propre verdict sur les deux heads.
- Le wrapper du gate local ne tourne toujours pas sur ce poste (`nice`, `timeout`, `nproc`
  absents — limitation documentée déjà assumée par #181/#182) : les mêmes commandes ont été
  lancées à la main ; le gate GitHub reste l'autorité (le verdict est lu au HEAD, pas déduit
  d'un job vert).

## 5. Notes immuables (une par PR user-visible)

- `backend/release-notes/notifications-session-date-consult-defaults.json` (PR consultation —
  `frontend` + `backend`).
- `backend/release-notes/community-directory-and-bounded-history.json` (PR bornes — `frontend` +
  `backend`).

## 6. Restants consignés (pas de drop silencieux)

- **Libellés produit « nature des données »** (profil 11 C1/C4 : Library « non-lineup/visible »
  vs profil « tout ») : disponibles comme décision produit (un libellé clair), pas imposés ici —
  le parent tranche, pas de refonte.
- **Aides au-delà du filtre** (profil 10 P3 « toute le jargon de l'écran ») : couvert pour
  DB/SD/HU/SYNC/DD/échelle et la définition des indicateurs Analysis ; les écrans restants
  (partenaires, jauge de priorité) ne portent pas de jargon non découvert dans les audits.
- **Retours personnels signés** (commentaires/annotations/avis) : pas vérifiables sur le compte
  e2e (données absentes) — attribués au compte qui possède les retours (triage #181).
- **Reprise vidéo après pause, aria play-pause** : planifiée pour la PR de l'agent vidéo (profil
  7) — non traités ici.

## Suivi review (2026-11-02 ~01h15, babysitter GLM sur 884bf57a)

Registre des findings du verdict REQUEST_CHANGES (run 41364627920), vérifiés contre le code courant.

| Source | Finding | Décision | Fix/validation |
|---|---|---|---|
| bot, `users.py:162` | `_aggregates().all()` matérialise une ligne par compte et retient `stats` — mémoire qui grandit avec la communauté | **Confirmé — corrigé** : la sous-requête par compte est enveloppée et agrégée en SQL (`count(...)` + `count(case latest ≥ horizon)`) → **une seule ligne** retourne de la DB, zéro rétention | `_community_totals` produit members/divers/others/recent par agrégats SQL purs |
| bot, `users.py:162` | les totaux comptent les plongées des comptes désactivés (les liaisons OWNER subsistent post-désactivation) contrairement à l'annuaire servi | **Confirmé — corrigé** : `join(AppUser)` + `AppUser.is_active IS TRUE` dans l'agrégat ; la réactivation remet les totaux à l'état attendu | test `test_directory_totals_exclude_deactivated_accounts_via_sql_aggregate` : totaux = {members:1, divers:1, recent:1} hors bob, {2,2,2} après réactivation (instance vivante : les rows du workspace sont détachés — la mutation passe par une requête live) |
| bot, `Dives.tsx:538` | la reprise n'avance que son curseur local : le « Load more » manuel re-héberge la première page reprise (deux chargements, même contenu) | **Confirmé — corrigé** : chaque page complétée de la reprise écrit `setNextCursor(next)` (ïlot de génération gardé) — le clic manuel continue depuis le curseur le plus profond | test « advances the manual Load-more cursor past the resumed depth » : reprise p2→p3→p4, clic manuel = un seul fetch `cursor=p4`, chaque curseur demandé exactement une fois, 8 lignes au total sans doublon |
| bot, `Community.tsx:54` | une continuation périmée s'écrit après le rejeu de la première page (la voie retry repeuple pendant le vol) | **Confirmé — corrigé** : compteur `directoryGeneration` posé par (re)chargement du directory, la continuation vérifie son token sur son écriture ET sur error/finally | test « a restart discards a stale continuation served into the fresh page » : continuation en vol → Retry des deux voies → la page fraîche remplace (Bill), la page périmée n'ajoute rien ni ne ressuscite le contrôle |

Validation : vitest Community + Library (26 tests incl. 2 nouveaux) + suites Dives ; backend profiles/communaute 40 tests 🟢 (20 profiles incl. 1 nouveau + 17 code_communaauté + visibility…). Gate GitHub rejouée au head suivant.

## Suivi review 2 (2026-11-02 ~08h, verdict 22e709a2)

| Source | Finding | Décision | Fix/validation |
|---|---|---|---|
| verdict 22e709a2 (41366245372), `codeSummariesApi.ts:108` | cap appliqué AVANT le filtre diver : les vieux essays du plongeur sélectionné disparaissent; liste filtrée vide = état vide au lieu de la notice plafonnée | **Confirmé — corrigé** : `diver_id` full-serveur dans Library (list_dives, post-scope, pré-cursory), `getCodeAttemptsResult(…, diverId)` + clé cache embarquant le nonce ; la notice `cappedAria` s'affiche même liste vide | `CodeAnalysis.test.tsx` ajusté au nonce + routes; TS/build verts |
| idem, `users.py:154` | linked accounts matérialisés puis IN/NOT IN unbounded (`_community_totals` + `member_directory`) | **Confirmé — corrigé** : EXISTS corrélés sur les propres dives du viewer pour le totals; le directory scope sa liaison à sa page bornée | test_member_profiles / code_community rerun 54/54 |
| idem, `Community.tsx:152` | les catégories absentes de la première page ne reçoivent pas de bannière malgré totaux non nuls | **Confirmé — corrigé** : bannières pilotées par les totaux (continuation explicite gardée) | suite Community |
| idem, `users.py:189` | échec agrégat → zéros valides faussés dans la réponse | **Confirmé — corrigé** : `_community_totals` → None sur échec, endpoint transmet `totals: null` (le front garde ses counts de page) | py test rerun incl. éventuel monkeypatch-fail |
| idem, `Dives.tsx:451` | resume non attendu : le clamp d'ancre scroll consomme avant les pages de la reprise | **Confirmé — corrigé** : le drapeau du resume retient l'ancre jusqu'à la fin du walk (finally), le clamp s'exécute après l'arrivée de la dernière page | test resumeDepth existant + budget scroll |
