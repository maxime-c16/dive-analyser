# Navigation mobile — recette PR2

Date : 2026-10-09. Worktree `t3code-mobile-pills`, branche `t3code/mobile-pill-navigation`.
Dépendance : [PR1 #99](https://github.com/maxime-c16/dive-analyser/pull/99), commit `8791223a0a0882782ff81db2f56811ee35c1c775`. PR2 réutilise les overlays, le focus, Escape, inert, les portals et le verrouillage du scroll de PR1. Aucun merge ni déploiement effectué.

## Comportement livré

Quatre liens Bibliothèque, Messages, Communauté, Évaluations, mêmes icônes/ordre/traductions que desktop et préchargement `IntentNavLink`. Capsule flottante sous 1024 px, libellés complets, état actif sur les sous-routes, focus visible. Le header contient la cloche et l’avatar. L’avatar ouvre Compte, Mon profil, Nouveautés ; Révision et Opérations sont réservées aux admins et repliées. Aucun cinquième lien de navigation.

| Situation | Politique | Occupant du bas |
| --- | --- | --- |
| Page du shell <1024 px | Visible | Quatre liens |
| Desktop ≥1024 px | Absente, offset zéro | Sidebar existante |
| Auth et partage | Hors shell | Contrôles de la page |
| Clip, jury, upload, notifications, feuille compte, modal imbriquée | Absente suivant la pile réelle PR1 | Contrôles de sortie de l’overlay |
| Conversation <768 px | Remplacée | Composeur et historique à hauteur disponible |
| Conversation 768–1023 px | Visible hors édition/overlay | Layout existant + navigation |
| Admin avec modifications non enregistrées | Remplacée | Action de sauvegarde, safe-area incluse |
| Édition sur pointeur tactile | Masquée | Champ/composeur |

Aucun masquage au scroll. Les notices Nouveautés et sync conservent leurs états et cooldowns ; leurs hauteurs mesurées réservent du contenu et leurs groupes s’empilent sans recouvrir les pills. Elles se mettent en pause pendant une modal, l’édition tactile ou une action de bas de page. Sur desktop leur présentation reste inchangée. `--mobile-nav-offset` mesure la capsule et son espace inférieur, safe-area comptée une fois, et revient à zéro quand elle disparaît. Les consommateurs préparés dans PR1 utilisent cet offset.

## Conservation et clavier

URL, filtres et scroll sont conservés par onglet et par compte dans `sessionStorage`, avec restauration des entrées Back/Forward. Le paramètre `clip` est retiré des destinations mémorisées : revenir par une pill ne rouvre pas un clip. Le retour du viewer reste sous la responsabilité de PR1. Le retap sur la racine active remonte sans changer de route ; sur une sous-route, il revient à la racine. Reduced motion est respecté. L’onglet interne Évaluations est dans l’URL et l’historique navigateur.

Les brouillons texte/mentions sont isolés par compte et conversation. Une identité d’envoi incertain est conservée pour éviter un doublon après changement de route. Un succès tardif efface uniquement sa propre intention et son texte correspondant : nouvelle saisie, abandon puis retape identique et second envoi identique sont testés. La déconnexion purge les nouvelles clés du compte ; 401/403 purge les clés PR2 des propriétaires précédents ; une panne réseau conserve la récupération. Cela ne prétend pas purger tous les anciens brouillons de l’application. Aucun mot de passe ni jeton n’est stocké.

Le focus d’un champ avec pointeur coarse est une politique conservatrice d’édition, pas une preuve de clavier ouvert. Une diminution de visualViewport >150 px à scale=1 masque également la barre ; le zoom ne compte pas comme clavier. Le blur rétablit les pills après 150 ms. Un clavier externe ou un clavier fermé avec focus conservé peut donc laisser la navigation masquée jusqu’au blur. La hauteur du fil utilise visualViewport si disponible, sans offsetTop Safari, avec fallback innerHeight/dvh. Ni visualViewport ni interactive-widget ne sont présentés comme universels.

## Validation locale

- Suite frontend finale : **549 tests, 67 fichiers, tous passés**, `NODE_OPTIONS=--no-experimental-webstorage npm run test:ci --prefix frontend`.
- **TypeScript + build Vite/PWA passés**, `npm run build --prefix frontend`.
- **29 tests CI Python passés**, `python3 -m unittest discover -s ci/tests -q`.
- Catalogue de release valide (`python3 ci/release-notes.py validate`), note immuable `mobile-pill-navigation`, composant FRONTEND uniquement. Aucun changement backend.
- `git diff --check` propre.
- Recette navigateur finale : **52/52 passés (59,6 s), sans retry ni skip**, Chromium et WebKit, fixture `navigation-review.html`, sans compte réel ni backend. Commande depuis frontend : `ELECTRON_RUN_AS_NODE=1 '/Applications/T3 Code (Alpha).app/Contents/MacOS/T3 Code (Alpha)' node_modules/playwright/cli.js test --config playwright.navigation.config.ts`.

La matrice FR/EN couvre 320, 390, 430, 767, 768, 1023, 1366, 1440 px, paysage et texte agrandi. Elle contrôle les labels, aria-current, absence de débordement, offset nul desktop, et le dernier élément visible/cliquable même avec la notice Nouveautés. Parcours : rôles avatar, Compte/Nouveautés imbriqués et focus/inert/Escape, notifications vers conversation, récupération/envoi du brouillon, Évaluations + Back, profils, filtres/scroll/retap, viewer/commentaires/mentions, upload en vol, jury et sortie, admin dirty et notices sync. Shrink et pinch sont simulés dans les tests de hook ; le navigateur vérifie focus/blur tactile, pas un clavier OS réel.

La fixture jury valide le stage, la disparition de navigation et la sortie avec média indisponible. La lecture d’un vrai média de jury et ses gestes restent à recetter sur appareil ; les tests frontend existants du jury passent. Les données de fixture sont synthétiques et aucun média n’est commité.

La preview T3 a été utilisée en premier pour les interactions et captures. Après déconnexion explicite du host, la recette et les captures finales ont utilisé Playwright. Après interruption de session, le serveur Vite a dû être redémarré ; le run navigateur sans serveur a été arrêté puis relancé, sans changement produit.

Preuves de rendu locales inspectées :

- `/tmp/mobile-pr2-evidence/mobile-fr.png` (390 px)
- `/tmp/mobile-pr2-evidence/small-fr.png` (320 px)
- `/tmp/mobile-pr2-evidence/messages-fr.png` (composeur)
- `/tmp/mobile-pr2-evidence/desktop-fr.png` (desktop)

Les essais ont révélé et corrigé un débordement du header FR320, la couverture du dernier contenu par Nouveautés, la spécificité CSS des notices, l’action admin Review & save qui ne soumettait pas le formulaire, et l’identité d’envoi après réponse tardive. Trois erreurs de recette (upload sans sélectionner de fichier, fixture arrêtée/mauvais port, Escape testé avant le chargement du viewer lazy) et une erreur de type dans le cleanup d’un test ont également été corrigées avant livraison.

## Revues et limites

Assistants T3 locaux Claude Haiku 5.5, effort HIGH, en lecture seule ou tests sans édition :

- Audit indépendant : `c83d53ac-2dc1-4e22-b4cd-e7183d40f5e4` ; ses défauts confirmés sont corrigés et testés. Revue finale du code figé terminée : aucun défaut confirmé restant dans les corrections Messages/brouillons/session. Les deux assistants sont settled.
- Tests ciblés : `69cf2c53-daa2-48cc-a541-75716fe15b6a` ; 68 tests ciblés passés sur l’instantané initial, ses lacunes importantes complétées dans la suite finale.

Pas de simulateur iOS installé (`simctl` indisponible, CommandLineTools seuls), pas d’adb connecté. Chromium/WebKit automatisés ne sont pas de vrais Safari iOS : clavier logiciel/externe, barre système, gestes, safe-area physique, PWA installée et lecture média jury nécessitent une vérification sur appareil. Aucune installation de simulateur ni modification de périphérique effectuée. Le gate Linux complet n’est pas exécuté tel quel sur Mac ; le gate GitHub Linux est attendu sur la PR. Le contournement documenté du hook via `DIVE_CI_SKIP=1` peut être utilisé pour pousser les contrôles portables déjà vérifiés.
