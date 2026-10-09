<!-- Source: T3 Code local thread a36a7f96-2cb4-4d9f-94dc-96d69ab7139c; Claude Opus 5.5; completed 2026-10-09T10:43:19.053Z. Export includes the complete proposed plan and final assistant response. Recommendations are not implementation authorization or runtime validation. -->

# Barre de navigation mobile flottante (pills) : analyse et recommandations

> Livrable d'analyse uniquement. Aucun fichier du dépôt n'a été modifié, rien n'a été commité, poussé ni déployé. La refonte mobile n'est **pas** autorisée : ce document prépare la décision.
> Code audité : worktree `t3code-90772c41` (branche `t3code/collapse-revision-sidebar-tabs`), y compris le diff non commité de `frontend/src/router.tsx` / `router.test.tsx`. Chemins relatifs à `frontend/src/`.

## Contexte

Aujourd'hui, la navigation mobile passe par un en-tête collant et un menu hamburger plein écran (`router.tsx:286-378`). Ce menu liste les 4 destinations principales, le compte, et pour les admins les sections Révision et Opérations, repliées grâce au `NavigationDisclosure` en cours (`router.tsx:167-202`, `354-373`). L'objectif est de mettre les 4 destinations (Bibliothèque, Messages, Communauté, Évaluations) dans une barre capsule flottante en bas, façon Instagram (image 2), sans casser les nombreux overlays plein écran déjà présents. La difficulté n'est pas de dessiner la barre, mais de la faire coexister avec toutes les pages et tous les états de l'app.

---

## 0. Faits observés (inventaire du code)

### Shell et routes
- **Un seul shell** : `Layout` (`router.tsx:380-444`). La sidebar desktop est en `lg:block` (≥1024 px, l.390) et `MobileNavigation` en `lg:hidden` (l.308). `<main id="main-content">` est à la l.434.
- **Routes hors shell (pas de barre)** : `/share/:shareId` (l.529, page publique), `/login`, `/register` (l.535-550), l'écran de chargement de `AuthGuard` (l.486-491) et `/evaluations-demo` (dev uniquement).
- **Routes dans le shell** (l.560-600) :
  - Pour tous : `/dives`, `/dives/analysis/:diveCode`, `/messages`, `/messages/:conversationId`, `/community`, `/users/:userId`, `/evaluations`, `/notifications`, `/account`, la 404.
  - Admin uniquement (avec le diff) : `/dashboard`, `/journey`, `/analytics`, `/sessions`, `/media/representatives`, `/media/recall`, `/admin`, `/admin/users/:userId`.
  - **`/media/p5-canary` n'est protégée par aucun guard** (l.579).
- Les routes sont imbriquées dans un `<Routes>` sous un `path="*"` unique. `useMatches()` et les `handle` de route ne servent donc à rien ici, alors que le data router existe bien (`App.tsx:16`, `createBrowserRouter`). `useBlocker` est d'ailleurs déjà utilisé (`AccountNavigationGuard.tsx:8`).
- `routeLabelKeys` (l.116-132) fait une **correspondance exacte** des chemins. Ce n'est pas assez pour l'état actif d'un onglet dans les sous-routes.
- Les toasts globaux sont montés **en dehors de `RouterProvider`** (`App.tsx:23-26`) : `SyncNotifications` (fixe bas-droite, z-50, `SyncNotifications.tsx:88`), `SyncErrorHandler` (fixe bas-gauche, z-40, `SyncErrorHandler.tsx:85`) et `MilestoneNotifier` (fixe en haut). Ils ne peuvent pas lire le contexte du router.

### Overlays, portals, modales (état actuel)
| Surface | Fichier | Couche | Inert sur le fond | Scroll lock | Focus trap |
|---|---|---|---|---|---|
| Menu mobile actuel | `router.tsx:334-375` | fixed `top-14` z-50 | non | non | non (Escape seulement) |
| ClipViewer | `ClipViewer.tsx:730-745` | fixed inset z-50, dans `#root` | **oui**, `inertExcept` (l.611-618) | oui, html+body (l.598-607) | oui (l.704-722) |
| ↳ panneau détails/commentaires (bottom sheet <1024) | `ClipViewer.tsx` ~l.918-975, `clipViewer.css:629-662` | absolute, max-height 75 %/82 %, `padding-bottom: env(safe-area-inset-bottom)` | oui, inertExcept panneau (l.576-581) | hérité | oui |
| ↳ « Envoyer » (SendDiveButton) | `clipViewer.css:1189-1191` | **fixed `bottom:120px`** <600 px, z-40 | non | non | Escape |
| ↳ résultat de partage | `clipViewer.css:1107-1125` | fixed en haut | – | – | – |
| ↳ suppression | `DiveManagement.tsx:61` | confirmation en ligne | – | – | – |
| AddVideos (upload) | `AddVideos.tsx:86` | fixed inset z-50, aria-modal | **non** | **non** | Tab manuel ; `beforeunload` seul (l.46-51) |
| EvaluationStage (jury) | `EvaluationStage.tsx:117-157`, `evaluations.css:248-255` | **portal body**, z-80 | **non** | body (l.65-84) | oui |
| What's new, panneau | `WhatsNew.tsx:181-211` | portal body, z-70 | oui, `#root.inert = true` | body | oui |
| What's new, toast auto | `WhatsNew.tsx:158` | **fixed `bottom-5` z-40** | – | – | – |
| Tiroir tentative DiveAnalysis | `DiveAnalysis.tsx:422-438` | fixed inset z-50 | **non** | **non** | Tab manuel |
| CandidatePanel (admin) | `RepresentativeMedia.tsx:126-127` | fixed inset z-50 | non | non | non |
| SessionDetail (admin) | `SessionDetail.tsx:94-100,181` | fixed inset z-50 | oui (inertExcept) | ? | oui |
| Confirmation de sécurité du compte | `AccountSecurity.tsx:10`, `AdminAccount.css:64` | fixed z-100 | non | non | Tab manuel |
| Barre « Enregistrer » collante | `AdminAccount.css:60` | **`position:sticky; bottom:16px` z-10** | – | – | – |
| Menu des mentions | `mentions.css:3` | absolute **au-dessus** du textarea, z-30 | – | – | listbox |

**Conclusion** : sept mécanismes d'isolation différents, trois scroll locks indépendants qui sauvegardent et restaurent chacun la valeur inline précédente (risque de restauration dans le désordre), et une heuristique DOM : `document.querySelector('[role="dialog"]')` dans `WhatsNew.tsx:113`.

### Pages clés
- **Bibliothèque** (`pages/Dives.tsx`) :
  - Le viewer est piloté par l'URL `?clip=` (l.209, l.336-352).
  - L'ancre de scroll est restaurée manuellement à la fermeture (l.354-364).
  - Ouvrir un clip = push dans l'historique ; Prev/Next/fermer = replace (l.396-410). Après fermeture, la pile contient donc `/dives` deux fois, et **le premier Back ne fait rien de visible** (déduit du code, à confirmer en navigateur).
  - Les filtres sont en ligne : bouton `sm:hidden` et `<select>` natifs (l.491-600). Il n'y a pas de bottom sheet.
  - Le bouton « Afficher plus » est en fin de liste (l.707-716). Il n'y a ni multi-sélection ni actions collées en bas dans le code actuel.
- **Liens qui changent d'onglet** : `MessageBubble.tsx:31`, `ProfileDiveGrid.tsx:11` et `MemberProfile.tsx:35` mènent vers `/dives?clip=…&scope=all`. On passe de Messages/Communauté à la Bibliothèque.
- **Messages** (`pages/Messages.tsx`) :
  - Le fil de discussion est limité par `max-h-[60vh]` (l.85).
  - Le composeur est un `<form>` dans le flux, en bas de section (l.97).
  - En dessous de `md`, la boîte de réception est masquée quand un fil est ouvert (l.153).
  - La page rend son propre **`<main>` imbriqué** dans le `<main>` du Layout (l.145).
  - Le brouillon du composeur vit dans un `useState`, donc il est perdu au changement de route.
- **Évaluations** (`pages/Evaluations.tsx`) :
  - L'onglet interne est un `useState` (l.22), perdu au changement d'onglet principal.
  - **`<main>` imbriqué** (l.50).
  - Le jury ouvre l'`EvaluationStage` en portal (z-80).
  - Un lien « Retour à la bibliothèque » se trouve dans le footer de page.
- **Notifications** : le bouton global est un **lien vers la page `/notifications`** (`components/Notifications.tsx:176-205`), pas un overlay. « Notifications au-dessus d'un formulaire » signifie donc concrètement « quitter le formulaire ». Seul `AdminAccount` est protégé (`useBlocker` + `beforeunload`).
- **Viewport et CSS globaux** :
  - `viewport-fit=cover` (`index.html:20`) et utilitaires `pt-safe`/`pb-safe` (`index.css:241-252`).
  - `#root { min-height: 100vh }` (`index.css:113-115`), alors que le viewer utilise `100dvh` (`clipViewer.css:3`).
  - `.touch-target` fait 44 px (`index.css:230`).
  - Le manifest PWA est en `display: standalone`, `orientation: any`.
- **Tests** :
  - `playwright.config.ts:28-41` ne contient que `chromium` et un `mobile-chromium` (Desktop Chrome en 390×844). **Pas de WebKit** : aucun comportement iOS n'est couvert.
  - Le diff non commité ajoute des tests de rôle (diver/admin) dans `router.test.tsx`.

### Comportements navigateur vérifiés en ligne
- `interactive-widget=resizes-content` est supporté par Chrome/Firefox Android, **pas par Safari** ([caniuse](https://caniuse.com/mdn-html_elements_meta_name_viewport_interactive-widget_resizes-content), [MDN](https://developer.mozilla.org/en-US/docs/Web/HTML/Guides/Viewport_meta_element)). Ce n'est donc pas une solution cross-browser pour le clavier.
- iOS 26 Safari a une barre d'outils flottante : il y a des régressions rapportées sur les éléments `position:fixed` en bas, des décalages selon le mode d'onglets (Compact/Bas/Haut), un `visualViewport.offsetTop` qui ne revient pas à 0 après fermeture du clavier, et une teinte du « menton » prise sur la couleur de fond des éléments fixes ([forum Apple 800798](https://developer.apple.com/forums/thread/800798), [799143](https://developer.apple.com/forums/thread/799143), [Ben Frain](https://benfrain.com/ios26-safari-theme-color-tab-tinting-with-fixed-position-elements/), [WebKit 297779](https://bugs.webkit.org/show_bug.cgi?id=297779)). Ces sources sont communautaires et non une doc Apple officielle, d'où l'obligation de tester sur appareil réel.

---

## 1. Architecture UX recommandée

### Barre (< 1024 px, c'est-à-dire le même seuil que `lg:hidden` aujourd'hui)
- **4 pills, dans cet ordre** : Bibliothèque (`Waves`) · Messages (`Send`) · Communauté (`Users`) · Évaluations (`ClipboardCheck`). Ce sont les mêmes icônes, le même ordre et les mêmes clés i18n que `primaryNav` (`router.tsx:96-101`), qui reste **la seule source** pour desktop et mobile.
- **Forme** : capsule flottante, marges latérales de 12 px, hauteur de 60 px. L'onglet actif est une pill intérieure claire (fond `--app-text` à environ 14 % d'opacité), icône et texte en `--app-text` ; les onglets inactifs sont en `--app-muted`. Fond opaque `--app-panel-elevated` à 92 %, avec `backdrop-filter` uniquement sous `@supports`. Pas de flou obligatoire, pour les Android modestes.
- **Libellés** : icône + libellé de 11-12 px sous l'icône pour les 4 onglets. Contrairement à Instagram, l'app ne repose pas sur des icônes universelles : un pictogramme « vagues » ne veut pas dire « Bibliothèque » sans texte.
  - Repli : si la barre fait moins d'environ 340 px de large (iPhone SE en zoom d'affichage, police Android agrandie), passer en icônes seules avec le libellé visible **uniquement sur la pill active**. On le fait avec une container query, pas via le user-agent. Le nom accessible reste toujours le texte complet.
  - Aucun libellé tronqué. « Bibliothèque » et « Évaluations » (FR) sont les plus longs ; à tester aussi en EN (« Evaluations »).
- **Pas de 5e pill.** Compte, notifications et admin vont dans l'en-tête.

### En-tête mobile (allégé)
- À gauche : titre de la page (ou bouton retour dans une sous-route).
- À droite : la **cloche** (`NotificationsButton compact`, badge conservé), puis l'**avatar** (`MemberAvatar`). L'avatar ouvre une **feuille de compte** qui remplace le hamburger et contient :
  - Compte, Mon profil, « Quoi de neuf » (le `WhatsNewButton` sort de l'en-tête : il y en a assez avec deux boutons) ;
  - pour les admins seulement, les deux `NavigationDisclosure compact` (Révision, Opérations), **repliés par défaut** comme dans le diff en cours.
- **Réutilisation** : c'est le panneau actuel `#mobile-navigation` (`router.tsx:334-375`) sans le bloc `primaryNav`, avec l'avatar comme déclencheur. Les plongeurs ordinaires ne voient aucune trace d'admin (cohérent avec `router.test.tsx`, nouveau test « regular divers… »).

### État actif dans les sous-routes
Une seule fonction pure et testée, `primaryTabFor(pathname): 'dives'|'messages'|'community'|'evaluations'|null`, avec `aria-current="page"` posé manuellement (NavLink seul ne suffit pas pour `/users/:id`).

| Chemin | Onglet actif |
|---|---|
| `/dives`, `/dives?…`, `/dives/analysis/:code` | Bibliothèque |
| `/messages`, `/messages/:id` | Messages |
| `/community`, `/users/:id` (y compris mon profil) | Communauté |
| `/evaluations` | Évaluations |
| `/notifications`, `/account`, toutes les pages admin, 404 | **aucun** (l'en-tête porte le titre ; en option, l'avatar reçoit un liseré actif sur `/account`) |

On ne fait pas de « l'onglet d'origine reste actif » via `location.state` : c'est fragile au rechargement et aux liens profonds. On applique une règle déterministe par URL.

### Retour et conservation du contexte
1. **Toucher l'onglet déjà actif** :
   - en sous-route (`/messages/12`, `/users/5`), on revient à sa racine ;
   - à la racine, on remonte en haut avec un scroll fluide (instantané si `prefers-reduced-motion`).
   - On n'efface jamais de brouillon : le brouillon de message est sauvegardé (voir 4).
2. **Mémoire par onglet** (`sessionStorage`, clé `nav:last:<tab>`) : on retient `pathname+search` **sans le paramètre `clip`**. Revenir sur Bibliothèque restaure recherche et filtres (qui sont déjà dans l'URL) mais ne rouvre jamais un lecteur. On retient aussi `scrollY` par onglet et on le restaure après le rendu, en réutilisant le modèle `requestAnimationFrame` de `Dives.tsx:354-364`.
3. **Bouton retour système / swipe iOS** : on garde l'historique du navigateur comme seule vérité. Pas de pile par onglet façon app native, ce qui serait ingérable en web.
   - Correctif préalable : la fermeture du viewer doit faire `navigate(-1)` quand le clip a été ouvert dans l'app (marqueur `location.state`), sinon un `replace` (lien profond). Cela supprime le « Back mort » de `Dives.tsx:403-410`.
4. **Liens qui changent d'onglet** (message ou profil vers un clip) : l'onglet actif bascule sur Bibliothèque ; c'est honnête et Back ramène au fil ou au profil. On l'accepte en le documentant.
5. **Onglet interne d'Évaluations** : il passe dans l'URL (`?tab=jury`) pour survivre aux changements d'onglet principal et au Back.

### Badges
- Notifications : déjà sur la cloche (`unreadCount`), à garder là.
- Messages : la pastille est souhaitable, mais **aucun total non lu global n'existe**. `Conversation.unread_count` n'existe que par conversation, et seulement sur la première page de `listConversations`. Il faut un endpoint ou champ backend `unread_total` : une étape séparée, à reporter.
- Format : un point de 8 px plutôt qu'un nombre dans la pill, avec un nombre dans le nom accessible (« Messages, 3 non lus »).

---

## 2. Matrice page × état

Légende :
- **V** : visible. Le contenu réserve `--mobile-nav-offset` en padding-bottom.
- **M** : masquée. Démontée ou `hidden` + `inert` ; offset à 0 sauf mention contraire.
- **R** : remplacée par une barre d'action propre à l'écran.

| Page / état | Barre | Ce qu'elle cacherait si on la laissait | Réservation | Résolution |
|---|---|---|---|---|
| `/login`, `/register`, `/share/:id`, chargement AuthGuard | M (hors shell) | – | – | Rien à faire, hors `Layout` |
| `/dives` liste et grille | V | Le bouton « Afficher plus » (`Dives.tsx:707`), les dernières vignettes | offset + 16 px | Padding sur `main` |
| `/dives` filtres ouverts, `<select>` natif | V | Le picker natif iOS/Android passe au-dessus de tout, sans conflit | idem | Rien |
| `/dives` champ de recherche focalisé (clavier) | **M** | La barre remonterait au-dessus du clavier (Android) ou flotterait au milieu (iOS) | 0 | Masquer quand un champ éditable a le focus sur un pointeur tactile |
| `/dives` + AddVideos (modale upload) | **M** | Le bouton Enregistrer, la progression | 0 | L'overlay s'enregistre ; il faut aussi lui ajouter inert et scroll lock (absents aujourd'hui) |
| Upload en cours puis tap sur un onglet | impossible (M) | – | – | Seul `beforeunload` protège : ajouter un `useBlocker` si les uploads deviennent un jour non modaux |
| `/dives?clip=` ClipViewer | **M** | Transport, progression (`clip-progress` à `bottom:0`), légende, actions (`clipViewer.css:756-808`), et pager vertical par glisser | 0 | **Ne pas** copier Reels : ici le viewer est une surface de revue modale avec sa propre sortie (`clip-back`) |
| ↳ viewer + commentaires (sheet) | M | Le composeur en bas de sheet | – | Inchangé ; tester le clavier dans la sheet |
| ↳ viewer + menu des mentions | M | Le menu s'ouvre vers le haut (`mentions.css:3`), pas de conflit | – | – |
| ↳ viewer + « Envoyer » (fixed `bottom:120px`) | M | – | – | Si un jour la barre est visible au-dessus d'un fixed, utiliser `calc(120px + offset)` |
| ↳ viewer + confirmation de suppression | M | – | – | Confirmation en ligne, sans conflit |
| ↳ viewer + What's new (z-70) | M | – | – | La pile d'overlays gère (le toast auto ne s'affiche pas car un overlay modal est ouvert) |
| `/dives/analysis/:code` | V | Le bas de la page | offset | – |
| ↳ tiroir de tentative (`DiveAnalysis.tsx:438`) | **M** | La vidéo et les boutons du tiroir | 0 | Enregistrer l'overlay, ajouter inert et scroll lock |
| `/messages` boîte de réception | V | « Plus de conversations » en bas | offset | – |
| ↳ « Nouveau » + MemberPicker (recherche) | V puis M au focus | Résultats | offset | Masquage clavier |
| `/messages/:id` fil (< md) | **R** | Le composeur, collé sous la barre, ou empilé en perdant environ 90 px sur un fil déjà à `60vh` | 0, et le composeur porte `pb-safe` | Masquer la barre dans un fil sur mobile (comme Instagram en DM). En-tête avec ← Messages, fil en `flex-1` avec `dvh` au lieu de `max-h-[60vh]`, composeur collé en bas |
| ↳ fil + clavier | R | – | – | Le composeur suit le clavier (iOS : vérifier `visualViewport`, voir 3) |
| `/messages/:id` (md–lg, 768-1023) | V | Composeur | offset | La boîte reste visible : la barre reste ; le composeur reçoit le padding |
| `/community` | V | « Charger plus » | offset | – |
| `/users/:id` profil + SendDiveButton en ligne | V | Le menu s'ouvre sous le déclencheur (absolute), il peut passer sous la barre en bas de page | offset | Ajouter `scroll-margin-bottom: offset` ou ouvrir vers le haut si l'espace manque |
| `/evaluations` onglets / listes | V | Le lien footer « Retour à la bibliothèque », le bouton Start | offset | – |
| ↳ jury : EvaluationStage (portal z-80) | **M** | Le dock de notation (`eval-stage-dock`, safe-area) | 0 | Enregistrer l'overlay **et** rendre `#root` inert (aujourd'hui la barre resterait atteignable au clavier et au lecteur d'écran derrière le portal) |
| ↳ jury + textarea de commentaire + clavier | M | – | – | Déjà dans le stage |
| `/notifications` | V (aucun actif) | Le bas de liste | offset | – |
| Notifications ouvertes depuis un formulaire non sauvegardé | V | – | – | C'est une **navigation** : brouillons persistés (message) ou `useBlocker` (formulaires de compte) |
| `/account` | V (avatar actif) | Le formulaire mot de passe (`Account.tsx:800`), les boutons d'enregistrement | offset | Masquage clavier |
| ↳ modale de confirmation de sécurité (z-100) | **M** | – | 0 | Enregistrer l'overlay |
| Feuille compte/admin (nouvelle) | **M** (la feuille couvre) | – | – | Overlay modal enregistré, focus trap |
| Pages admin (`/dashboard`… `/admin`) | V (aucun actif) | Le bas des tableaux et graphiques | offset | – |
| ↳ SessionDetail, CandidatePanel | **M** | Actions du panneau | 0 | Enregistrer |
| `/admin/users/:id` dirty, **barre Enregistrer collante** (`AdminAccount.css:60`) | V | **La barre Enregistrer passe sous la barre de navigation** | `bottom: calc(16px + offset)` | Ou **R** : masquer la nav tant que `dirty` (recommandé : un seul bloc d'actions en bas) |
| Toast What's new (`WhatsNew.tsx:158`, `bottom-5`) | V | **Collision directe** | `bottom: calc(20px + offset)` | Variable CSS |
| Toasts admin Sync (`App.tsx:24-26`, hors router) | V | Collision bas-gauche et bas-droite | offset | Lisent `--mobile-nav-offset` sur `:root`, donc pas besoin du contexte router |
| 404 | V | – | offset | – |
| Paysage téléphone (hauteur < 500 px) | V compacte (44 px, icônes seules) ou M dans le viewer | 60 px sur 390 px de hauteur, c'est 15 % de l'écran | offset réduit | `@media (orientation: landscape) and (max-height: 500px)` + safe-area gauche/droite |
| Plein écran vidéo natif iOS (`webkitEnterFullscreen`) / PiP | hors page | – | – | Le système gère ; vérifier que la barre n'apparaît pas pendant la sortie du plein écran |
| Multi-sélection / barre d'actions en bas | **aucune dans le code actuel** | – | – | Règle pour le futur : **R** (la barre d'actions remplace la nav, comme Photos iOS) |

---

## 3. Règles techniques

1. **Un seul propriétaire**. `MobileTabBar` est rendu par `Layout` (`router.tsx`) et uniquement là. Les pages ne rendent jamais de nav. Une table de politique `navPolicyFor(pathname, viewport)` décide de « visible / replaced » par route (ex. fil de messages < md), et la pile d'overlays décide du masquage temporaire. Ce sont des fonctions pures, testées unitairement.
2. **Visibilité fondée sur l'état réel, pas sur le DOM**. Un `OverlayProvider` dans `Router` (au-dessus de `Layout`) expose `useOverlay({ modal: true, hidesNav: true })`, que chaque surface appelle au montage. La barre est masquée si `stack.some(o => o.hidesNav)` ou si le clavier est ouvert. On remplace l'heuristique `querySelector('[role="dialog"]')` (`WhatsNew.tsx:113`) par `stack.length > 0`. Les surfaces hors router (toasts `App.tsx`) consomment seulement une **variable CSS** `--mobile-nav-offset` écrite sur `document.documentElement` par la barre (0 quand elle est masquée ou ≥1024 px).
3. **Couches (échelle unique, documentée dans `index.css`)** :
   - contenu 0-10 ;
   - barres collantes de page 20-30 ;
   - en-tête mobile et **barre de nav 40** ;
   - toasts 45, au-dessus de la nav et décalés de l'offset ;
   - overlays de page (viewer, drawers, AddVideos, feuille compte) 50 ;
   - What's new 70 ;
   - stage jury 80 ;
   - confirmations 90 ;
   - skip-link 100.

   Règle : **on ne règle pas un conflit par le z-index**. Une barre masquée est retirée (`hidden` + `inert`), pas seulement recouverte.
4. **Portals** : un portal sur `body` sort de `#root`, donc `inertExcept` ne l'atteint pas mais `#root.inert` (le modèle What's new) oui. Recommandation : tout overlay modal passe par un helper commun `useModalIsolation(ref)`. Ce helper combine `inertExcept` (dans `#root`) ou `#root.inert` (portal), le `trapTabKey` existant (`utils/a11y.tsx:61`), Escape et la restauration du focus.
5. **Scroll lock** : un compteur unique (`lockScroll()` / `unlock()`) remplace les trois sauvegardes et restaurations concurrentes (`ClipViewer.tsx:598-607`, `EvaluationStage.tsx:65-84`, `WhatsNew.tsx:185-200`).
   - On garde `overflow:hidden` sur `html` et `body`, qui fonctionne sur iOS ≥16. On évite le `body{position:fixed}`, qui provoque des sauts de scroll.
   - `overscroll-behavior: contain` sur les feuilles.
   - On restaure le scroll de la page sous-jacente à la fermeture.
6. **Safe-area et positionnement** :
   - Barre : `position:fixed; left: max(12px, env(safe-area-inset-left)); right: max(12px, env(safe-area-inset-right)); bottom: calc(env(safe-area-inset-bottom) + 8px)`.
   - Offset : `--mobile-nav-offset = 60px + 8px + env(safe-area-inset-bottom) + 8px`.
   - Les zones tactiles restent au-dessus de l'indicateur d'accueil iOS et de la zone de geste Android : pas de tap accidentel vers le sélecteur d'apps.
7. **Safari et barre d'adresse dynamique** :
   - Ne pas masquer la nav au scroll. La barre Safari bouge déjà ; deux éléments animés en sens contraire, c'est instable, et ça gêne la mémoire musculaire. Compromis assumé par rapport à Instagram.
   - Passer `#root` en `min-height: 100dvh` (avec repli `100vh`).
   - Attention à la teinte du « menton » iOS 26 calquée sur le fond des éléments fixes : tester barre opaque contre translucide.
8. **Clavier** :
   - Signal principal : `focusin`/`focusout` sur un élément éditable (`input` non bouton, `textarea`, `[contenteditable]`, `select` exclu) **et** `matchMedia('(pointer: coarse)')`. On masque alors la barre.
   - Signal secondaire, seulement pour le composeur collé du fil de messages : `visualViewport.height` comparée à `innerHeight`, avec un écart de plus de 150 px.
   - Ne pas compter sur `interactive-widget` (absent de Safari), ni sur `visualViewport.offsetTop` après fermeture (bug iOS 26).
   - Hystérésis d'environ 150 ms au `focusout` pour éviter le clignotement en passant d'un champ à l'autre.
9. **Paysage et petits écrans** :
   - Variante compacte (44 px, icônes seules avec libellé de la pill active) quand `max-height: 500px`.
   - Container query si la largeur est inférieure à 340 px.
   - Tester l'iPhone SE (safe-area 0, donc garder le `+8px`).
10. **Plein écran vidéo, PiP et gestes** :
    - La barre est masquée dans tout lecteur. Le pager vertical par glisser et le pinch du viewer (`ClipViewer.tsx:525-563`) n'ont plus de concurrent.
    - Le swipe iOS depuis le bord gauche (retour) n'est pas affecté par une barre en bas.
    - `EvaluationPlayer` désactive déjà le PiP.
11. **Accessibilité** :
    - `<nav aria-label="Navigation principale">`, de vrais liens (`IntentNavLink` pour le préchargement), `aria-current="page"`.
    - Cible tactile d'au moins 48×48 par pill (au-dessus des 44 de `.touch-target`), espacement d'au moins 8 px.
    - Contraste du texte 4.5:1, des icônes et de la pill active 3:1.
    - Focus visible.
    - Ordre DOM : nav **après** `main` (le skip-link reste utile).
    - Corriger les `<main>` imbriqués (`Messages.tsx:145`, `Evaluations.tsx:50`).
    - Respect de `prefers-reduced-motion` pour l'animation de la pill.
12. **i18n** : clés `nav.*` existantes, aucune troncature, test de parité FR/EN déjà présent (`i18n/parity.test.ts`). Ajouter les clés de nom accessible avec compteur non lu.
13. **PWA contre web** :
    - En `display-mode: standalone`, il n'y a pas de barre Safari : l'inset bas vaut 34 px sur les iPhones à Face ID, et la barre doit flotter au-dessus.
    - Sur le web, la barre Safari est en bas en mode Compact/Bas.
    - Les deux se testent séparément ; ni le manifest ni le meta n'ont besoin de changer.

---

## 4. Pièges trouvés dans ce code (par priorité) et modifications futures

**P0, avant toute barre :**
1. Isolation des overlays incohérente : AddVideos, EvaluationStage, tiroir DiveAnalysis, CandidatePanel, confirmation de sécurité et menu mobile **n'inertent pas le fond**. Une barre fixe resterait atteignable au clavier et au lecteur d'écran, et cliquable si son z-index l'emporte. → `OverlayProvider` + `useModalIsolation`.
2. Heuristique DOM du toast What's new (`WhatsNew.tsx:113`) et toast en bas (l.158). → pile d'overlays + offset.
3. Barre Enregistrer collante d'`AdminAccount` (`AdminAccount.css:60`) sous la nav. → masquer la nav si `dirty`, ou appliquer l'offset.
4. Toasts hors router (`App.tsx:24-26`). → variable CSS sur `:root`.
5. Fil de messages en `max-h-[60vh]` avec composeur dans le flux (`Messages.tsx:85,97`). → layout `dvh` + composeur collé + barre remplacée.

**P1 :**
6. « Back mort » après fermeture du viewer (`Dives.tsx:403-410`).
7. Pertes d'état au changement d'onglet : brouillon de message (`useState`), onglet d'Évaluations (`Evaluations.tsx:22`), formulaire mot de passe. → sessionStorage par conversation, `?tab=`, `useBlocker` si dirty.
8. Trois scroll locks concurrents. → compteur unique.
9. `<main>` imbriqués (`Messages.tsx:145`, `Evaluations.tsx:50`).
10. `routeLabelKeys` en correspondance exacte (`router.tsx:116-132`). → `primaryTabFor`.

**P2 :**
11. `#root` en `100vh` (`index.css:114`).
12. Le menu SendDiveButton en ligne peut finir sous la barre.
13. Total non lu des messages absent côté API.
14. Pas de projet WebKit dans Playwright.
15. Hors sujet mais relevé : `/media/p5-canary` est sans guard (`router.tsx:579`).

### Plan de migration (desktop protégé à chaque étape)
0. **Merger d'abord le travail desktop en cours** (Révision admin-only et repliée), sans toucher au mobile. Toute la suite part de `origin/master` après ce merge.
1. **Infrastructure invisible** (PR 1) : `OverlayProvider`, `useModalIsolation`, compteur de scroll lock et `--mobile-nav-offset: 0`. On migre les ~9 overlays listés en 0. Aucun changement visuel : tests unitaires d'isolation (Tab, inert, Escape, restauration du focus) par overlay ; les tests existants de `ClipViewer.test.tsx` doivent rester verts.
2. **Dettes préalables** (PR 2) : `<main>` imbriqués, historique du viewer, `?tab=` pour Évaluations, brouillons de messages, layout du fil en `dvh`, `#root` en `dvh`, échelle de z-index documentée.
3. **Barre derrière un flag** (PR 3) : `MobileTabBar` + `primaryTabFor` + `navPolicyFor` + masquage clavier. L'en-tête passe à « cloche + avatar → feuille », et le hamburger est conservé quand le flag est off. Le flag est un `localStorage` lu au démarrage, activable par les admins en recette. Toasts et barre Enregistrer passent sur l'offset. Tout est sous `lg:hidden` / `max-width: 1023px`, et l'offset vaut 0 à partir de 1024 px, donc le desktop est inchangé par construction (vérifié par les tests du router et un screenshot desktop Playwright).
4. **Recette appareils** (section 5), corrections, puis activation par défaut et suppression du hamburger. Ajout d'une note de version JSON (`backend/release-notes/`, `components: ["frontend"]`) puisque le changement est visible.
5. **Finitions** : mémoire de scroll et d'URL par onglet, re-tap pour remonter en haut, puis pastille Messages une fois l'endpoint `unread_total` disponible (PR backend séparée).

---

## 5. Critères d'acceptation et matrice de tests

### Critères d'acceptation
- La barre n'apparaît **jamais** en même temps qu'un overlay modal, le clavier ouvert, un lecteur ou un fil de messages sur mobile. À chaque instant, **un seul** bloc d'actions est collé en bas.
- Aucun contrôle de page (Afficher plus, Enregistrer, composeur, liens de footer) n'est masqué en fin de scroll. Le dernier élément reste entièrement visible et cliquable avec au moins 16 px de marge.
- Lecteur d'écran et clavier : la barre n'est pas atteignable derrière un overlay, et le focus revient au déclencheur à la fermeture.
- Sous-routes : l'onglet actif est correct pour chaque ligne du tableau de la section 1, et `aria-current` est présent.
- Plongeur ordinaire : 4 pills, avatar sans aucune entrée admin, redirection des URL admin (tests du diff). Admin : Révision et Opérations repliées dans la feuille.
- Desktop (≥1024 px) au pixel près : sidebar inchangée, pas de barre, offset à 0.
- Back et swipe : fermer le viewer puis faire Back ne laisse pas d'étape morte ; retour sur Bibliothèque = mêmes filtres et position de scroll, sans viewer rouvert.
- Aucune régression du toast What's new ni des toasts de synchro admin.

### Matrice de tests (appareils réels requis)
| Axe | Valeurs |
|---|---|
| Appareils | iPhone SE (sans indicateur d'accueil), iPhone 15/16 (Dynamic Island), Pixel en navigation par gestes, Android en navigation 3 boutons (Samsung) |
| Contexte iOS | Safari onglets **Compact / Bas / Haut** (iOS 26.x), PWA écran d'accueil |
| Contexte Android | Chrome, PWA installée, Firefox |
| Orientation | portrait, paysage |
| Rôles | plongeur, admin |
| Langues / taille | FR, EN ; police système agrandie (Android 1.3×, zoom iOS 115-150 %) |
| Scénarios | fin de scroll de chaque page en V ; clavier dans recherche, composeur, commentaire du viewer, mot de passe, MemberPicker ; viewer → commentaires → mention → clavier ; viewer → Envoyer ; AddVideos pendant l'upload ; jury avec commentaire ; What's new par-dessus un formulaire ; toast What's new sur la Bibliothèque ; AdminAccount dirty ; Notifications depuis un brouillon de message ; changement d'onglet aller-retour avec filtres et scroll ; re-tap sur l'onglet actif ; Back et swipe après fermeture du viewer ; rotation pendant que le clavier est ouvert ; plein écran natif puis sortie |
| Automatisable | Vitest : `primaryTabFor`, `navPolicyFor`, pile d'overlays, scroll lock, isolation par overlay. Playwright : ajouter un projet **`webkit` + `devices['iPhone 13']`** (n'émule ni le clavier ni la barre Safari, mais attrape le layout et le z-index), assertions « dernier élément cliquable » via `elementFromPoint`, screenshot desktop de non-régression |
| Manuel uniquement | clavier réel iOS/Android, teinte du menton iOS 26, barre dynamique Safari, gestes système, PWA |

### Ce qui a été vérifié et ce qui reste à faire
- **Vérifié (lecture du code)** : inventaire des routes, overlays, couches, safe-areas, scroll locks et historique, avec les références de lignes ci-dessus ; diff non commité lu ; support navigateur d'`interactive-widget` et rapports iOS 26 consultés en ligne.
- **Non vérifié** :
  - aucune exécution de l'app, aucun test lancé, aucun rendu en navigateur ou appareil ;
  - le « Back mort » du viewer est déduit du code ;
  - les comportements iOS 26 viennent de sources communautaires ;
  - la largeur réelle des libellés à 320 px est à mesurer.

## Décisions à confirmer avant implémentation
1. Le fil de messages masque la barre sur mobile (recommandé) plutôt que d'empiler composeur et barre.
2. Avatar dans l'en-tête → feuille compte/admin (recommandé) plutôt qu'une 5e pill.
3. Libellés visibles sous les icônes (recommandé) plutôt qu'icônes seules à la Instagram.
4. La barre n'est pas masquée au scroll (recommandé).
5. Pastille Messages reportée tant que l'endpoint backend n'existe pas.

---

## Réponse finale du thread Opus 5.5

L'analyse complète est prête dans le plan ci-dessus. C'est uniquement de la lecture : aucun fichier du dépôt n'a été modifié et je n'ai pas lancé l'app, aucun test, ni aucun navigateur ou appareil.

**Proposition :**
- **La barre :** quatre pills (Bibliothèque, Messages, Communauté, Évaluations), avec les mêmes icônes que le desktop et un libellé sous chaque icône. Elle s'affiche sous 1024 px, le même seuil que le menu mobile actuel.
- **Le reste :** la cloche et un avatar passent dans l'en-tête. L'avatar ouvre une feuille avec Compte, Mon profil, Quoi de neuf et, pour les admins seulement, Révision et Opérations repliées. Cette feuille réutilise le panneau du menu hamburger actuel.

**Ce que l'audit révèle :**
- **Isolation des overlays incohérente.** Sept façons différentes de gérer les modales coexistent. Six d'entre elles ne bloquent pas le fond : l'upload de vidéos, la séance de jury, le tiroir d'une tentative, le panneau des candidats admin, la confirmation de sécurité du compte et le menu mobile. Une barre fixe y resterait atteignable au clavier et par les lecteurs d'écran. Il faut d'abord un registre unique des overlays dans le shell, qui décide quand masquer la barre.
- **Collisions directes avec des éléments déjà collés en bas :**
  - le toast « Quoi de neuf » (`WhatsNew.tsx:158`) ;
  - la barre « Enregistrer » de la fiche compte admin (`AdminAccount.css:60`) ;
  - les toasts de synchro admin, montés en dehors du router (`App.tsx:24-26`).
- **Messages :** le fil est limité à 60 % de la hauteur et le composeur est dans le flux. Je recommande de masquer la barre dans un fil sur mobile, comme Instagram dans ses messages privés.
- **Le bouton Notifications ouvre une page.** « Notifications au-dessus d'un formulaire » revient donc à quitter le formulaire. Le brouillon de message et l'onglet choisi dans Évaluations sont alors perdus.
- **Retour après le lecteur de clip :** d'après le code, le premier « Retour » après sa fermeture ne fait rien de visible (`Dives.tsx:403-410`). C'est à confirmer en navigateur.
- **Aucun test iOS automatisé :** Playwright n'a pas de projet WebKit.

**Comportements navigateur vérifiés en ligne :**
- L'option qui redimensionne la page à l'ouverture du clavier (`interactive-widget`) n'existe pas sur Safari. On ne peut donc pas compter dessus.
- Safari iOS 26 a plusieurs bugs signalés sur les éléments fixés en bas de l'écran. Ces rapports viennent des forums, pas d'une doc Apple. D'où la recommandation de masquer la barre dès qu'un champ de saisie a le focus.

**Plan par étapes :**
1. Merger d'abord le travail desktop en cours.
2. Mettre en place, sans changement visible, le registre des overlays, un verrouillage de scroll unique et une variable CSS pour l'espace réservé à la barre.
3. Corriger les dettes listées ci-dessus.
4. Ajouter la barre derrière un flag, en ne touchant qu'aux règles sous 1024 px.
5. Faire la recette sur appareils réels, puis l'activer par défaut avec une note de version.

**Cinq décisions à trancher avant l'implémentation :**
1. Masquer la barre dans un fil de messages sur mobile (recommandé), plutôt qu'empiler composeur et barre.
2. Mettre le compte derrière l'avatar de l'en-tête (recommandé), plutôt qu'en cinquième pill.
3. Afficher les libellés sous les icônes (recommandé), plutôt que des icônes seules comme Instagram.
4. Ne pas masquer la barre au défilement (recommandé).
5. Reporter la pastille de messages non lus : il n'existe aujourd'hui aucun total global côté API, seulement un compteur par conversation.

Sources :
- [caniuse, `interactive-widget`](https://caniuse.com/mdn-html_elements_meta_name_viewport_interactive-widget_resizes-content)
- [MDN, meta viewport](https://developer.mozilla.org/en-US/docs/Web/HTML/Guides/Viewport_meta_element)
- [Forum Apple 800798](https://developer.apple.com/forums/thread/800798)
- [Forum Apple 799143](https://developer.apple.com/forums/thread/799143)
- [Ben Frain, teinte iOS 26](https://benfrain.com/ios26-safari-theme-color-tab-tinting-with-fixed-position-elements/)
- [WebKit 297779](https://bugs.webkit.org/show_bug.cgi?id=297779)