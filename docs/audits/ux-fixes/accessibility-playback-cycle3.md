# Fixes accessibilité et lecture — cycle 3 (profils 7/9/12)

PR `t3/accessibility-playback-fixes`. Sources de lecture seule :
`docs/audits/ux-discovery-cycle3/profil-9-accessibilite/rapport.md`,
`profil-7-reprise/rapport.md`, `profil-12-grill-navigation/rapport.md`
(travail sur copies, sources non modifiées). Perimètres voisins respectés :
PR #181/#182 (babysitter), agent t3-bf477ab8 (différés Community/Judge/
notifications/qualité) — aucun fichier commun modifié (voir `git show --stat`).

## 1. Escape du viewer ne rend pas le focus à la carte — CONFIRMÉ, cause fragment du skip-link

**Contre-preuve structurante (profil 12)** : le même parcours sur v1.19.7
*(27 Tab depuis le chargement → Enter sur carte → viewer → Escape)* rend bien
le focus à la carte d'origine, Back/Forward compris. Le parours du profil 9
(activation du skip-link au début de session, puis ouverture d'une carte) se
termine sur `document.activeElement = <main>` avec l'URL `…#main-content`.
L'écart entre les deux parcours est l'entrée `#main-content` dans l'historique,
pas la restauration du modal.

**Mécanisme** : l'activation native du skip-link (`<a href="#main-content">`)
écrit le fragment dans l'URL (une entrée d'historique). Les navigations
search-params de React Router résolvent `"?clip=…"` relatif et abandonnent le
hash à l'aller (`resolvePath` → `hash: ""`), mais `closeViewer()` fait
`navigate(-1)` : le retour replonge sur l'entrée **avec** fragment, et la
traversée same-document rejoue la navigation de fragment (étapes de focus du
HTML spec) en recentrant `<main tabindex=-1>` **après** les restaurations de
l'application (microtask `overlays.register` + rAF carte du Library).

**Correction (racine unique, aucun hack de restauration)** :
`frontend/src/router.tsx` — le skip-link prend un handler onClick :
`preventDefault`, `focus({preventScroll:true})` + `scrollIntoView()` sur
`#main-content`, et `history.replaceState` pour nettoyer un fragment qui
trainerait déjà dans l'URL. Aucune entrée d'historique fragmentée n'est plus
créée ; les chemins déjà corrects (profil 12, fermeture par bouton, Back/Forward)
ne sont pas touchés : overlays (`restore:fallback`), l'effet rAF carte de
`Dives.tsx` restent inchangés.

**Tests** (`router.test.tsx`, `Dives.urlState.test.tsx`) :
- skip-link : focus sur `<main>`, URL **sans** fragment, re-skip après sortie
  de `<main>` fonctionne ;
- fermeture du viewer « Back to Library » → focus carte d'origine (existant) ;
- **nouveau** : fermeture par **Escape** → focus carte d'origine (parité avec
  le bouton, parcours profil 12).

## 2. Champ recherche Community sans nom accessible — REJETÉ (faux positif)

`git diff v1.19.7..HEAD -- frontend/src/pages/Community.tsx` est vide : le
code déployé pendant les audits est le code courant. Le `<label class="cm-search">`
parent contient **dépuis la création de la page** (6a172ad4, antérieure aux
versions audités) une étiquette sr-only avec le même texte que le placeholder.
Le nom accessible calculé n'est donc **pas** vide : la seule information
manquante au rapport d'audit est hors attributs explicites (le probe reliait
aria-label/labelledby/title mais pas le sous-arbre du label parent).

Preuve exécutable : le test existant tape dans
`getByRole('searchbox', { name: 'Search by name or @handle' })` — passant.
Aucune modification : obtenir ce nom via un second mécanisme (aria-label) au
dessus d'un label déjà valide ne protégerait rien et dupliquerait la donnée.

## 3. Noms concaténés (« Comments0 », « FOFouiny19 days », « E2Orbit ») — PARTIELLEMENT CONFIRMÉ

**Confirmé et corrigé (séparateur sr-only, pas d'aria-label en masse)** :
- Onglet « Comments 0 » du viewer : le libellé et le compteur étaient deux
  nœuds adjacents sans espace → « Comments0 ». Fix : séparateur sr-only entre
  deux (`ClipViewer.tsx`), le chip garde son style (`:not(.sr-only)`).
- Cartes membres Community : le nom (`<b>`) et les faits (compte + âge) sont
  des lignes distinctes du même lien, collées à la lecture (« Louis2 shared
  dives · 19 days ago »). Fix : virgules sr-only en fin de bloc dans
  `Community.tsx` (rangées `cm-row` et cartes `cm-story`).

**Rejeté (préfixes avatar « E2 »/« FO »)** : `MemberAvatar` est
`aria-hidden="true"` à sa racine depuis son premier commit (9a1b21d3, bien
avant v1.19.7). Les noms calculés par le vérificateur standard excluent les
initiales : les noms mesurés excluent e.g. « E2 »/« LO » (initiales du
fallback). Les boutons HUD du compte se nomment donc « Orbit »/« Reticle »/
« Depth » et les cartes « Fouiny, 19 days », pas « E2Orbit »/« FOFouiny… ».
Le préfixe du rapport correspond à une lecture `textContent`, pas au nom
accessible. Aucune modif (le masquage demandé — « masque décoration avatar »
— était déjà en place).

## 4. aria Play/Pause figé sur « Pause video » avec `video.paused === true` — DÉFÉRRÉ (tests verrouillés)

**Le rapport contient sa propre contradiction** : profil 7 observe
« l'icône visuelle devient bien un Play » tout en lisant « Pause video » sur
les deux boutons — mais l'icône (Play vs Pause) et les deux aria-labels
découlent du **même état React `paused`** dans un seul rendu de
`ImmersiveControls` ; un état partagé ne peut pas donner icône juste +
libellés faux. Code vérifié (et identique au prod :
`git diff v1.19.7..HEAD` vide sur ImmersiveControls/DiveVideoPlayer/
PreparedVideo/overlays) : la source d'état est l'élément réel lui même
(événements `play/pause/volumechange/timeupdate/loadedmetadata` + lecture
`video.paused` au montage et à chaque event, `soundRef` = même élément
poolé) ; le labellisé UI suit l'élément, tous les consommateurs (overlay
gesture, transport, HUD) partagent cet état.

**Traitements faits** : comportement verrouillé par tests
(`DiveVideoPlayer.test.tsx`) — montage avec élément déjà en pause →
« Play video »/« Resume playback » ; lecture → boutons « Pause video » ;
pause **externe** → libellés repassent du côté play ; changement de clip
(remontage clés) → rebinage au **nouvel** élément (état initial du nouvel
élément gagne, les événements de l'ancien élément ne pilotent plus rien) ;
volumechange sans bascule de pause ne contredit pas l'état.

**Non corrigé (faux pas autorisés respectés)** : aucun contournement
d'autoplay/permissions, pas de mutation forcée de lecture, pas de force-flick
de rendu. Suivi proposé : une capture **appairée** (DOM + arbre AX + état JS
au même instant) pendant une tentative de reprise, pour discriminer une
photographie AX périmée d'un vrai désynchro — la capture actuelle y est
réfractaire (l'icône visible prouve l'état juste au même instant).

## 5. Reprise après pause impossible (profil 7) vs réussie clavier (profil 9) — DÉFÉRRÉ, reprod non établi

Chaînes lues en intégralité (`toggle()`, overlay Space du `ClipViewer`,
`handleCanPlay`, fallback autoplay muet de `DiveVideoPlayer`, `PreparedVideo`,
pool `preparedPlayback`) : la reprise appelle `play()` sur l'élément adopté,
sans condition autre que `video.paused` ; les garde-fous `hasPlayedRef`/
`userPausedRef` ne gouvernent que les relances auto de démarrage et
n'empêchent jamais une reprise manuelle ; la restauration son au premier
geste (chemin autoplay muet) ne remute jamais. Aucun chemin code ne bloque
une reprise au clic là où la reprise Espace réussirait (les deux partagent
`play()`).

Hypothèses restées ouvertes, à un seul test appairé : wrap de boucle lu comme
« blocage » (clip 8,27 s en boucle ; « 7,1 s → 6,1 s » compatible avec un
repli de boucle) ; snapshot AX/CDP périmé (même origine que le 4) ; lecture
CDP sur un élément detaché du pool (a priori impossible : le viewer garde
l'élément actif). **Aucune revendication de bug certain, aucune correction
forcée** : « pas de mutation lecture forcée permanente ni contournement
permissions/autoplay » respecté à la lettre.

## Environnement (n'affecte pas la code review)

- La suite locale s'est mise à échouer en masse sous **Node 26.5.0** du Mac
  (64 tests / 7 fichiers) : `localStorage` est un getter global expérimental
  renvoyant `undefined` sans `--localstorage-file`, cassant les tests jsdom
  indépendamment du code. Code identique + **Node 20** (version pinned CI) :
  **109 fichiers / 867 tests verts** sur le même worktree ; typecheck et
  build production verts. Le babysitter avait déjà le même symptôme.
- Le gate local de cette box échoue avant tout tier sans rapport avec le
  code (pas de GNU `timeout`/`nproc`, pas de docker compose, pas de PyYAML
  locaux — logs `~/.cache/dive-ci/logs/*`). Les suites pertinentes ont été
  exécutées manuellement aux versions CI ; le check hébergé obligatoire
  `gate` reste la barrière réelle sur la PR.

## Validation

- `frontend` : vitest 867/867 (Node 20, dont 11 tests nouveaux), tsc, build Vite prod.
- `python3 ci/release-notes.py validate` : ✓.
- Touches : `frontend/src/router.tsx`, `frontend/src/components/clip-viewer/ClipViewer.tsx`,
  `frontend/src/pages/Community.tsx` + 4 fichiers de tests ; i18n FR/EN
  intacts (aucune chaîne nouvelle ; séparateurs = ponctuation sr-only).
