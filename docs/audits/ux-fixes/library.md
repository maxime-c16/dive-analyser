# UX fixes — Périmètre A : bibliothèque (état, recherche, période, pagination)

Source : six tests UX indépendants (`docs/audits/ux-discovery-2026-11-01/`, worktree
de test, non committés). Chaque constat attribué à ce périmètre a été revérifié
contre le code avant correction. Classement : **confirmed / rejected / deferred**.

## 1. États de la bibliothèque perdus au changement de rubrique — **confirmed, corrigé**

**Signaux** : profil-4 (« Community ⇄ Calendar → Library : tout ramené à zéro »,
capture 12), mobile parcours D (« perte de scroll après back et changement de
rubrique »).

**Cause (code)** : tout l'état de travail (recherche, scope, hauteur, contexte,
rating, modificateurs, vue, tri) vit dans l'URL `/dives?...`. La navigation
Library → Messages/Calendar → Library atterrit sur `/dives` nu : l'URL ne porte
plus rien, la liste repart de la première page (`frontend/src/pages/Dives.tsx`,
`usePreservedSearchParams` + effet de chargement sur `pageParamsKey`), le scroll
est réinitialisé. *Dans* la bibliothèque (modale ↔ liste), l'URL étant préservée,
l'état tenait — ce qui explique la différence entre les deux constats du profil 4.

**Correction** : mémoire de « workspace » par compte et par onglet
(`frontend/src/hooks/libraryWorkspace.ts`). Au quittage de la page, les clés
propres à la bibliothèque (`q, scope, height, context, performance, modifiers,
view, sort, period` + profondeur de scroll) sont écrites en sessionStorage,
clé artificielle incluant `libraryKey(user)` ; au retour sur **une URL nue**
(aucune de ces clés présente, `clip` et paramètres étrangers exclus de la
restauration), l'URL est recomposée puis la profondeur de scroll restaurée,
bornée par la hauteur de contenu. Priorité à l'URL explicite : un lien profond
ou une URL filtrée ne restaure rien ; le changement de compte change la clé
(isolation) ; l'onglet neuf repart propre. « Réinitialiser les filtres » reste
la sortie volontaire (l'état nu est ensuite persisté tel quel).

**Tests** : `frontend/src/pages/Dives.libraryUx.test.tsx` — restauration filtres/vue/période
+ une seule requête paramétrée ; priorité de l'URL explicite ; isolation par
compte ; encaissement de la scroll-profondeur. La suite existante
`Dives.urlState.test.tsx` couvre le retour de la modale (`back`, fermeture).

**Limites** : le cache de données ne garde qu'une page serveur (`libraryCache`
mono-entrée) — au retour, la `profondeur` paginée (pages « Load more » déjà
chargées) n'est pas retenue ; c'est cohérent avec la consigne « position/profondeur
bornée ». Restitution serrée du scroll plafonnée au contenu réel.

## 2. La recherche ne trouvait pas les noms de figure — **confirmed, corrigé**

**Signal** : profil-4 §2, « back dive / Back dive tuck / dive → No attempts match
this search », « 201C → résultats ».

**Cause (code)** : le **nom affiché** n'est pas stocké : il est dérivé du code
FIG par le catalogue `frontend/src/i18n/diveNames.ts` (`diveCodeName`), avec
légendes duclub souvent absentes (upload sans caption). La recherche serveur
(`search_text` dans `app/services/library_query.py`) ne matche que
`dive_code` + `raw_caption`/`notes` — jamais le nom dérivé ; côté client, le
filtre sous-nom ne voyait que la page chargée.

**Correction** : inversion du catalogue : `frontend/src/utils/diveNameSearch.ts`
indexe **une fois** les ~1 400 codes du catalogue (FR **et** EN, mots normalisés
sans accents, pluriels) → mot de figure → ensemble de codes exacts. La requête
envoie cet ensemble via un nouveau paramètre borné `code_filter`
(`upper(dive_code) IN (...))`) appliqué **avant** pagination sur
`/api/v1/dives/library` **et** `/library/codes` — donc sur **tout le périmètre
autorisé**, pas la page chargée. Côté API, `code_filter` et la phrase
(caption/notes) se composent en **OU** (`_text_filters`), composition reproduite
à l'identique côté client (`Dives.tsx` filtre) pour que paginations et agrégats
s'accordent. Les mots hors catalogue restent de la recherche par phrase ;
les mots de position/hauteur/sync conservent leurs filtres structurés
(`position_filter`, etc.). FR/EN cohérents : « back dive » comme « arrière »
fonctionnent quelle que soit la langue d'interface.

**Bornes (skill bounded-db-change)** : `code_filter` validé par regex
`^[1-6][0-9]{2,3}[A-D]$`, plafonné à **1024 codes** (422 au-delà, jamais tronqué
en silence), longueurs bornées ; filtre SQL avant pagination ; taille de
réponse inchangée (pages ≤ 100, `next_cursor`) ; pas de N+1 (un seul prédicat
`IN`) ; les agrégats codes/progress restent calculés sur le périmètre filtré
complet. **Dégradation assumée** : un mot de famille très large seul (ex.
« somersaults » seul, ~1 264 codes) dépasse le plafond → le critère nom note
`unsupported` et la recherche retombe sur la phrase (comportement identique
client/serveur, fixé par tests). Les requêtes réelles multi-mots
(back dive — 44 codes, arrière — 352, back dive tuck — 11) restent sous le plafond.

**Tests** : backend `tests/test_library_name_and_period_filters.py` (codes
exacts, OR phrase/nom, 422 sur entrée invalide/oversize, périmètre/privé,
pagination au-delà de la page 1) ; frontend `Dives.libraryUx.test.tsx` +
tests unitaires de l'index (`diveNameSearch`) — « back dive », « arrière »,
« back dive tuck », repli phrase, repli unsupported.

## 3. Accès par période — **confirmed, corrigé (modeste)**

**Signal** : profil-4 priorité 3 (« retrouver par période = scroll infini »),
probes « May 2026 », « 30 May ». *(Priorité 3 « si nécessaire » : retenue parce
que le saut par mois dans une liste paginée croissante n'a pas de sémantique
bornée ici ; le filtre oui.)*

**Correction** : filtre `period` (URL explicite `?period=30d|90d|180d|365d`)
dans la rangée de filtres existants → `date_from` naïf (minuit UTC) passé aux
deux endpoints (API accepte désormais `date_from`/`date_to` sur `/library` et
`/library/codes`, appliqués avant pagination et sur les agrégats — cohérence
avec les cartes Code/Progress). Compte de filtres actifs, badge mobile et
« Reset filters » l'incluent. La fenêtre est re-ancrée à chaque montage, jamais
figée en date absolue dans l'URL.

**Tests** : périodes → paramètres + URL + reset (frontend) ; bornes
`date_from`/`date_to` pages + agrégats (backend).

## 4. Deux paginations superposées et dénominateurs trompeurs — **confirmed, corrigé**

**Signal** : profil-4 (deux boutons empilés non distingués), profil-5
(`Show 48 more attempts / Load more dives`).

**Cause (code)** : « Show N more attempts » déplie la tranche client
(`/48` entier, même quand il en reste 12) et « Load more dives » (page
serveur) pouvait s'afficher **en même temps** — deux intentions « voir plus
vieux » rendues par deux boutons.

**Correction** : séquence unique — la tranche client s'consume d'abord
(libellé paramétré avec le **reste réel**, plafonné à 48 : « Show 12 more
attempts » / « Afficher 12 plongeons de plus »), puis « Load more dives »
n'apparaît que la tranche épuisée (`shown >= filtered.length`). Le chargement
serveur poursuit l'étalement (`+100`). Navigation dans le lecteur inchangée
(prolongation auto avant la limite de page). Autosurveillance : un seul
contrôle visible à la fois à chaque étape (test).

**Tests** : `Dives.urlState.test.tsx` (profondeur conservée, remise à 48 sur
changement de filtre — libellé maintenant paramétré), `Dives.libraryUx.test.tsx`
(une pagination à la fois, compte véridique, complétion serveur), tests i18n
(pluriels).

## 5. Écart historique analyse/liste (26 Nov 2024 vs 23 mai 2026) — **rejected (comportement cohérent)**

**Signal** : profil-4 §4-4 ; hypothèse à vérifier : « les filtres 1m+M
peuvent expliquer l'écart ».

**Vérification (code)** : la liste paginée applique hauteur/performance/
exclusion des lignées **avant** le curseur (`_filtered_dive_query` +
`exclude_lineup=True`, `backend/app/api/v1/dives.py`) et se termine
réellement quand le curseur est épuisé — la liste filtrée s'arrête au dernier
essai qui satisfait les filtres ; la page d'analyse couvre le corpus complet
du code, sans ces filtres. Aucun bug de pagination trouvé ; aucune correction
faite. Le compte « 26 Nov 2024 → » de l'analyse reste juste pour le code
affiché sans filtres.

## 6. Bouton « Open latest attempt » sans effet (profil-6) — **unconfirmed, deferred**

**Signal** : profil-6 (« 2 clics exactement centrés, aucun changement d'URL ni de
dialogue ; vignette voisine fonctionnelle »).

**Vérification (code + tests)** : le bouton (`CodeCards.tsx` `ca-thumb`) appelle
`openClipId(code.latest.id)` ; si l'essai n'est pas dans les pages chargées
(résumés = tout le périmètre, pages = 100), il est résolu via
`GET /api/v1/dives/{id}` puis filtré (scope/filtres) avant ouverture du lecteur.
J'ai écrit un test qui rejoue précisément ce chemin (essai hors page chargée) :
**ça passe** (`Dives.libraryUx.test.tsx > opens the latest attempt ... beyond
the loaded pages`). Deux chemins peuvent produire « aucun effet » sur le
compte e2e : une résolution réseau qui échoue fait retomber l'URL
(`catch(() => {})` + nettoyage stale-clip) sans retour visible, ou un essai
hors scope qui est filtré après résolution. **Non reproduit localement** ;
pas de correction inventée. Reporté : repro live avant d'ajouter du bruit
d'erreur ou de modifier le flux de résolution.

## 7. « The dive library could not be loaded » au premier arrivage — **rejected as defect (non modifié), à garder en tête**

**Signal** : ux-progression O-0 (Majeure, un Retry suffit après coup).

**Vérification (code)** : l'erreur vient du premier fetch (`catch → setError`),
le bouton Retry recharge (`tests existants : « a library load failure exposes
what failed and a working Retry »`). Trois agents en parallèle sur cette
instance = pic de charge plausible ; l'état affiché est honnête et réparable.
Un auto-retry masquerait les vraies erreurs d'authentification/réseau ; hors
périmètre de cette PR (correction minimale). Reporté pour une future décision
produit si le constat se reproduit.

## 8. Français codé en dur dans la liste Library — **confirmed, corrigé**

`SessionRow` (vue liste) et la tuile séance de la grille affichaient
« Séance », « X vidéo(s) » et le bouton « Plus de séances » sans i18n. Remplacés
par les clés `libraryUX.*` (EN/FR, pluriels i18next). **Clés nouvelles
uniquement**, dans un bloc `libraryUX` séparé à la fin de chaque locale
(aucune clé existante modifiée).

## 9. Observations hors correction (deferred, hors bug)

- `getCodeAttempts` (frontend) boucle `do/while(cursor)` sans plafond interne :
  pages bornées (100/req) mais compte de tours libre ; utilisé par l'analyse
  par code, pas touché ici (changement séparé si besoin).
- Le cache Library mono-entrée (une clé de filtres) : changer de recherche
  replace la tranche à 48 — raisonnable, borné, inchangé.
- Compteurs d'ambiguïté relevés par profils 1/4/5 (« 142/300 », position
  « x/100 » du lecteur) : propriété du ClipViewer — **hors périmètre A**.

## 10. Périmètre, vérifications et limites

- **Fichiers** : `frontend/src/pages/Dives.tsx`, `frontend/src/hooks/libraryWorkspace.ts`,
  `frontend/src/utils/diveNameSearch.ts`, `frontend/src/components/LibraryCards.tsx`,
  `frontend/src/i18n/locales/{en,fr}.ts` (bloc `libraryUX`),
  `backend/app/api/v1/dives.py`, `backend/app/services/library_query.py`,
  tests (`Dives.libraryUx.test.tsx`, `test_library_name_and_period_filters.py`,
  mises à jour `Dives.sessions`, `LibraryCards`, hygiène `sessionStorage` dans
  les suites Library), note JSON `backend/release-notes/library-remember-search-find.json`.
- **Vérification** : backend — suite complète locale (venv CI) repo + nouveaux
  tests ; frontend — **112 fichiers / 872 tests au vert**, `tsc --noEmit`, build
  Vite production. Le wrapper local `ci/gate.sh` ne passe pas sur ce poste
  (`nice`/`timeout`/`nproc` GNU absents, pas de Docker) : les tiers
  frontend/backend ont été lancés directement avec leurs commandes ; le `gate`
  GitHub reste l'autorité, le push déclenche la matrice complète.
- **Non reproduit sur la prod** : aucune prétention de validation en
  production ; les tests rejouent les comportements sur code, pas l'environnement
  e2e distant (agent-lecture seule, verrou partagé, snap timeouts).
- **Isolation/permissions préservées** : le scope member (`manageable`) prime
  toujours ; `code_filter`/période s'appliquent APRES le scope (`tests
  test_member_dive_visibility` au vert, y compris « search ne sonde pas les
  notes privées d'autrui » et l'égalité des compteurs de requêtes).
- **Hors périmètre** (autres rubriques, ClipViewer/lent, notifications,
  les notifications, la langue FR globale, Like/favoris) : laissés au
  propriétaire correspondant ; les aides DB/SD/HU existent (popover constaté
  par profil 6) — signaux « abréviations » classés sans action ici.
