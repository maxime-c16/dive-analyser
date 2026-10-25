# Brief — audit premier chargement & lecture média (Opus 5.5 medium)

Copie du brief reçu le 2026-10-25 (thread parent b4d4b8d3-8a39-4508-a2d8-dd5e0da88676).

Mission : auditer et explorer les goulots restants du premier chargement et de la lecture média de Dive Analyzer. Maxime demande explicitement un thread Opus 5.5 medium pour comprendre avant de corriger.
Lis AGENTS.md et docs/REPO_WORKFLOW.md avant toute action. Audit autonome jusqu'au rapport, sans implémentation produit ni déploiement.

Périmètre : ton worktree ; lecture seule de la production par SSH selon ~/.t3-nightly/FLEET.md ; tests locaux et expériences contrôlées ; écriture de rapports/sondes locales uniquement.

Interdit : écritures DB/médias/config/services prod, redémarrage, migration, nouvelle charge lourde sur serveurs, push/PR/merge/deploy. Ne modifie pas le worktree parent.

Contexte et preuves du parent (non commités, lisibles aux chemins absolus) :
- …/t3-ff2bc342/docs/audits/2026-10-25-library-first-load.md
- …/t3-ff2bc342/work/first-load/server-history.json et server-history-20261025T090840Z.json
- …/t3-ff2bc342/work/first-load/browser-telemetry.json
- …/t3-ff2bc342/ci/collect-first-load-history.py
- Le diff non commité de …/t3-ff2bc342 décrit le lot 1 : miniatures intégrées à /dives/library via batch borné, amorçage cache, TTL préservés, sources limitées à proximité écran et priorité posters visibles. 768 tests front, 24 backend, dernier rerun 64 ciblés, build réussi. Rien déployé.

Ce lot retire une découverte HTTP, mais ajoute du SQL et du poids à la page. L'expérience Chromium utilise des API simulées et des PNG 1px : 487→305 ms médians après requête bibliothèque, en facturant +30 ms simulés à la bibliothèque ; aucun gain production prouvé.

Historique récupéré : 7 jours demandés, ~25 h retournées, 51 points espacés 30 min, rates sur 5 min. Iowait médian 8.93 %, max observé 56.77 %, disque système ROTA=1. Métriques hôte sans attribution causale ; pas de métrique historique de première miniature trouvée.

Explore sans t'ancrer sur ces hypothèses : auth et bootstrap, attente bibliothèque+divers, payloads/SQL et event loop, frontend/rendu, réseau LAN vs accès public/Funnel, caches froids/chauds, démarrage lecture, droits/grants/HEAD/302/B2, formats/décodage, warming concurrent, contention disque et tâches média.

Pour chaque problème réel : déclencheur, preuve code+mesure si possible, impact UX, degré de certitude, compromis/coût induit, correction candidate, test qui tranche, priorité. Distingue coût réseau, temps serveur, attente disque et décodage ; pas de promesse de secondes inventées.

Exigence Maxime : télémétrie pédagogique et schémas pour comprendre ; il accepte un ralentissement local si le design global est meilleur. Ne cherche pas à faire monter un score à chaque action.

Raccordement posters durables D5 : travail distinct, pas à implémenter ici. Migration PR149/152 en cours via timer dive-media-migration : packages HQ/light/poster dans media_derivatives/B2, jamais media_cache_entries. Sur 1826 clips sans poster cache, 975 avaient déjà un poster durable (mesure 25 oct.) ; PR157/18543d1 corrige ambiguous_location pour posters identiques. Audite l'interaction et les coûts, sans prendre l'ownership du raccordement.

Livrables : docs/audits/2026-10-25-media-startup-opus.md + preuves non sensibles/schéma et plan de remédiation priorisé ; commit local limité à tes livrables si utile, sans push. Copie ce brief en docs/audits/media-startup-opus-brief.md au démarrage.

Ne crée pas d'autres agents/threads. Si un accès manque, avance sur le reste et distingue les limites.

Fin : résumé de 5 lignes avec chemins/preuves/priorités au thread parent b4d4b8d3-8a39-4508-a2d8-dd5e0da88676 via t3_thread_send (clientRequestId stable audit-opus-startup-final-20261025), puis terminer.
