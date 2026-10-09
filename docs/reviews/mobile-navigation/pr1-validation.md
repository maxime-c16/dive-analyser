# PR 1 — navigation compacte et overlays

## Périmètre

Les quatre destinations principales restent visibles. Révision et Opérations
sont réservées aux administrateurs et repliées. Les notifications et le compte
restent accessibles. Le diagnostic `/media/p5-canary` reçoit aussi le guard admin.
Le menu mobile existant reste en place, sans pills ni nouvel en-tête.

`frontend/src/utils/overlays.ts` possède une pile commune au document, incluant
les portals body et les composants hors router. Les couches suivent les z-index
existants (50, sheet 51, historique 70, jury 80, sécurité 100). Seule la surface
supérieure isole les siblings sur son chemin jusqu'à body, traite Escape/Tab et
contient le focus. Une scrim peut rester une cible de fermeture sans entrer dans
l'ordre Tab. Les attributs inert préexistants et leurs valeurs sont restaurés.
Un observateur childList isole aussi les nouveaux siblings.

Le scroll html/body reste verrouillé jusqu'au départ de la dernière surface ;
les valeurs inline et priorités d'origine sont restaurées même si le parent
part avant un portal enfant. Les callbacks actualisés ne réinscrivent pas une
surface. Le focus de retour est restauré après le commit React, avec annulation
si une nouvelle ouverture/fermeture doit prendre la priorité. Ce délai corrige
un cas reproduit en navigateur : React rétablissait le focus sur « Quoi de neuf »
après fermeture du menu mobile imbriqué.

Surfaces migrées : ClipViewer et sa sheet, AddVideos, EvaluationStage,
What's new, AttemptDrawer de DiveAnalysis, CandidatePanel, SessionDetail,
AccountActionDialog et menu mobile. Les popovers d'envoi et de mentions
consomment Escape avant leur modale. Les confirmations natives restent natives.
Escape n'annule ni un upload ni une opération de sécurité en cours.

`--mobile-nav-offset` vaut **0px**. Les trois toasts globaux concernés et la barre
Enregistrer admin utilisent cette réserve sans déplacement visuel. What's new
consulte la pile explicite ; le contrôle du playback et la politique de cooldown
restent inchangés.

## Historique du viewer

Le test comportemental reproduisait une fermeture suivie d'un Retour qui restait
sur `/dives`. Une ouverture locale pose désormais un marqueur d'origine canonique,
conservé lors de Suivant/Précédent. Fermer revient à cette entrée si les filtres
correspondent encore. Une fermeture depuis un lien profond/profil/message ou après
modification des filtres supprime seulement `clip` en replace. Les URL avec
encodage non canonique sont couvertes ; aucun marqueur n'est déduit de la seule
longueur de l'historique. Le focus a aussi un repli vers la recherche de Bibliothèque.

## Validation locale — 9 octobre 2026

- Suite frontend complète : **500 tests, 63 fichiers, OK**, Vitest, un worker ; router, viewer/handoff, jury,
  What's new, compte et navigation dirty existants inclus.
- Nouveaux tests : pile imbriquée dans root et portal body, Escape supérieur,
  popovers locaux, focus et Tab dans les deux sens, champs masqués/désactivés,
  StrictMode, callbacks actualisés, siblings ajoutés, démontage dans le désordre,
  scroll partagé et restauration des styles/priorités/inert ; offset zéro ;
  portail jury, confirmation busy, upload annulé ou en cours, suppression du
  hint automatique, historique local/liens profonds/profils/messages/filtres/encodage.
- `npm run build` (TypeScript et Vite), `git diff --check`.
- `python3 -m unittest discover -s ci/tests -q` : 29 tests, OK.
- `python3 ci/release-notes.py validate` : OK. Note visible requérant uniquement frontend.
- T3 preview : desktop 1366×768 (FR et EN), sidebar repliée et compte/notifications
  dans le viewport ; mobile 390×844, menus admin et plongeur ; historique portal
  imbriqué dans le menu ; viewer puis sheet commentaires ; import avec faux fichier
  local, sans enregistrement. Focus, inert et libération du scroll inspectés dans
  le navigateur, avec screenshots locaux T3 hors git.
- Fixture reproductible : lancer Vite puis ouvrir
  `/e2e/fixtures/navigation-review.html` (`?role=diver` pour le rôle plongeur).
  Données entièrement locales, aucun compte réel ni secret.
- Assistance : audit lecture seule Claude Haiku 5.5/high, thread local
  `36612709-329d-46e1-9748-cf33836a34fb`. Le cas d'encodage URL signalé a été corrigé
  et testé. Les recommandations statiques Opus originales restent conservées
  intégralement dans `opus-5-5-findings.md`.

### Limites

Node local 26 expose un global localStorage incompatible avec cette version de
Vitest/jsdom : tests lancés avec `NODE_OPTIONS=--no-experimental-webstorage` pour
utiliser le storage jsdom. Le gate shell complet n'est pas exécutable tel quel sur
ce Mac (flock, timeout/nproc et Docker absents). Tentative du tier fast documentée ;
les tests CI Python, validation du catalogue et build/tests frontend ont été exécutés
directement. Aucun backend, worker, serveur live, merge ou déploiement utilisé.

La preview redimensionnée est un navigateur desktop Chromium. Aucun test Safari,
clavier mobile réel, geste système ou PWA sur appareil n'est revendiqué. La
validation visuelle ne couvre pas chaque drawer admin ; leur intégration est
vérifiée par lecture et la pile commune par tests.

## PR 2

Pills, nouvel en-tête/avatar, politique visible/masquée/remplacée, espacements,
layout Messages et clavier, conservation du contexte et recette sur appareils
réels restent à livrer. Aucun badge global Messages/backend dans cette PR.
