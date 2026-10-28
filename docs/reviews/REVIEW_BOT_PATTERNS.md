# Cartographie des reviews bots — 2026-10-28

## Périmètre et méthode

Collecte GitHub le 28 octobre 2026, dépôt `maxime-c16/dive-analyser` :

- `gh api repos/maxime-c16/dive-analyser/pulls/comments --paginate --slurp` : 65 commentaires inline, dont 23 de Copilot et 42 de Maxime (4–5 octobre).
- `gh api repos/maxime-c16/dive-analyser/issues/comments --paginate --slurp` : 551 commentaires, dont 452 de `github-actions[bot]` et 99 de Maxime (5–28 octobre).
- Workflow : 195 verdicts REQUEST_CHANGES, 110 COMMENT, 142 APPROVE, 5 autres sorties (dont 2 remarques de sécurité sans format Verdict et des échecs d'exécution).
- 307 commentaires candidats à une remarque : les 305 COMMENT/REQUEST_CHANGES et les 2 sorties avec `Severity:`. Ils concernent 81 PR distinctes. Ce ne sont **pas 307 bugs distincts**.

Les commentaires inline et les commentaires de conversation sont deux canaux distincts. L'auteur GitHub Actions désigne le workflow, pas nécessairement une identité de modèle stable dans le temps. Le modèle actuellement configuré est dans `.github/workflows/open code-review.yml`.

Analyse qualitative des familles et de leurs exemples, avec lecture des contrats locaux actuels. Les répétitions sur une même PR sont séparées des récurrences entre PR. Les verdicts et sévérités restent les affirmations du bot : cette étude n'est pas un audit des corrections, des commits historiques ou de la production. Un APPROVE ultérieur ne prouve pas à lui seul la résolution de chaque remarque. Pas de taux de vrais/faux positifs sans adjudication des diffs historiques.

## 1. Travail non borné et N+1 : priorité transversale

**Symptôme :** une réponse limitée masque une lecture de toute la table ; un lot borné masque plusieurs requêtes par élément ; un streaming conserve tout dans des accumulateurs.

**Exemples indépendants :**

- [PR #34 — associations administratives](https://github.com/maxime-c16/dive-analyser/pull/34#issuecomment-6000919414) : page de 200 plongeurs, mais chargement de toutes les associations.
- [PR #69 — notifications](https://github.com/maxime-c16/dive-analyser/pull/69#issuecomment-6022803825) : après insertion en lot, un `refresh` par destinataire réintroduit jusqu'à 500 SELECT.
- [PR #149 — inventaire média](https://github.com/maxime-c16/dive-analyser/pull/149#issuecomment-6341072540) : accès paresseux à `job.asset` dans un traitement par lots.
- [PR #164 — synthèses de codes](https://github.com/maxime-c16/dive-analyser/pull/164#issuecomment-6401630990) : `yield_per` ne borne pas les tuples conservés ni les listes reconstruites.
- [PR #168 — classement](https://github.com/maxime-c16/dive-analyser/pull/168#issuecomment-6404216253) : top 10 appliqué après agrégation de toute la communauté en Python.
- [PR #173 — résolution d'alias](https://github.com/maxime-c16/dive-analyser/pull/173#issuecomment-6467104600) : `.unique().all()` déduplique après lecture ; il faut sélectionner les identités distinctes en SQL avant la limite.

**Règle :** décrire séparément le nombre de lignes lues, le nombre de requêtes, la mémoire retenue et la taille de la réponse. Agréger/classer en SQL ; précharger les associations du lot ; bornes explicites sur historique, scans et files. Une fenêtre temporelle ne borne pas le nombre d'utilisateurs.

**Attention :** ne pas remplacer la justesse par une troncature. [PR #172](https://github.com/maxime-c16/dive-analyser/pull/172#issuecomment-6452271505) : `limit(2)` sur des lignes jointes peut cacher un deuxième plongeur derrière deux alias du premier et autoriser une suppression dangereuse. Limiter les entités distinctes.

**Preuve utile :** volume multiplié, nombre de requêtes stable par lot ; test de deux entités portant plusieurs alias ; statistiques complètes malgré une page bornée.

## 2. Pagination : plafond silencieux ≠ résultat complet

- [PR #71](https://github.com/maxime-c16/dive-analyser/pull/71#issuecomment-6023678586) : les 50 dernières notifications ne représentent pas toutes les non-lues.
- [PR #104](https://github.com/maxime-c16/dive-analyser/pull/104#issuecomment-6085569289) : sommer 250 conversations ne donne pas le total des non-lus.
- [PR #118](https://github.com/maxime-c16/dive-analyser/pull/118#issuecomment-6254787173) : arrêter après 10 pages omet des événements malgré un curseur restant.
- [PR #168](https://github.com/maxime-c16/dive-analyser/pull/168#issuecomment-6404071808) : la recherche perd son chargement des pages suivantes.

**Règle :** pagination visible ou continuation explicite ; calcul des totaux en SQL sur le périmètre complet. Pour les workers, curseur durable et reprise équitable pour ne pas traiter éternellement les premiers éléments. Un cap de sécurité doit rendre l'incomplétude explicite.

## 3. Identité, portée et caches : frontière de confidentialité

- [PR #71](https://github.com/maxime-c16/dive-analyser/pull/71#issuecomment-6023946051) : préférences de secours communes aux comptes.
- [PR #166](https://github.com/maxime-c16/dive-analyser/pull/166#issuecomment-6403091676) : cache d'essais sans identité du lecteur, risque de réaffichage d'essais privés après changement de compte.
- [PR #166 — comparaison](https://github.com/maxime-c16/dive-analyser/pull/166#issuecomment-6402991460) : « Vous » calculé sur le périmètre communautaire et cache excluant le mauvais propriétaire.
- [PR #161](https://github.com/maxime-c16/dive-analyser/pull/161#issuecomment-6397804445) : URL nginx signée émise par une route de statut sans l'autorisation média correspondante.

**Règle :** une clé de cache doit inclure toute dimension qui change le résultat, notamment le lecteur et ses droits. Le reset doit aussi invalider les réponses en vol et les erreurs. Une route de statut qui émet une URL de lecture doit appliquer l'autorisation de lecture. Vérifier compte A → déconnexion → compte B, y compris requête A lente et panne réseau.

## 4. Courses : contrôle et mutation doivent porter sur le même état

- [PR #110](https://github.com/maxime-c16/dive-analyser/pull/110#issuecomment-6091588740) : verrou d'ownership absent d'autres écrivains, dont CLI/bootstrap.
- [PR #145](https://github.com/maxime-c16/dive-analyser/pull/145#issuecomment-6330741599) : caps et preuves calculés avant le verrou puis utilisés sans relecture.
- [PR #158](https://github.com/maxime-c16/dive-analyser/pull/158#issuecomment-6395905172) : source changée entre vérification et commit du poster.
- [PR #134](https://github.com/maxime-c16/dive-analyser/pull/134#issuecomment-6304363814) : migration ne sérialisant pas la suppression physique déjà en cours.

**Règle :** inventorier tous les écrivains (API, CLI, worker, migration), acquérir le verrou avant la lecture décisive, rafraîchir l'état ORM, puis valider et muter sous le même protocole. Pour fichiers/objets : identité de source, publication atomique, fencing et nettoyage des perdants. Une transaction SQL ne rend pas un `unlink` réversible.

**Preuve utile :** interleaving contrôlé sur PostgreSQL avec deux sessions ; tests de conflit et replay. SQLite seul ne prouve pas les verrous ni la récupération après erreur PostgreSQL.

## 5. Asynchrone : la réussite ancienne ne doit pas modifier le nouvel écran

- [PR #48](https://github.com/maxime-c16/dive-analyser/pull/48#issuecomment-6010721227) : navigation différée vers un voisin devenu obsolète.
- [PR #76](https://github.com/maxime-c16/dive-analyser/pull/76#issuecomment-6036467051) : ancienne réponse média sur le nouveau plongeon, vote potentiellement associé à la mauvaise vidéo.
- [PR #76 — deuxième passe](https://github.com/maxime-c16/dive-analyser/pull/76#issuecomment-6036991079) : correction du succès sans garde équivalente dans le `catch` ; sortie de session annulée par une erreur tardive.
- [PR #168](https://github.com/maxime-c16/dive-analyser/pull/168#issuecomment-6404330828) : requête périmée laissant le chargement de pagination bloqué.

**Règle :** identité de requête/génération sur le rendu et chaque branche `then/catch/finally`, annulation lors de changements de compte, sélection, filtres et sortie. Réinitialiser aussi les verrous de chargement et animations. Tester les réponses inversées et les erreurs après sortie.

## 6. Ressources et worker unique : contrôler avant de consommer

- [PR #43](https://github.com/maxime-c16/dive-analyser/pull/43#issuecomment-6004443815) : vidéo entière en `arrayBuffer()` avant la limite.
- [PR #115](https://github.com/maxime-c16/dive-analyser/pull/115#issuecomment-6104030512) : multipart spoulé par FastAPI avant quota/disque du handler ; endpoint historique contournant la nouvelle file.
- [PR #77](https://github.com/maxime-c16/dive-analyser/pull/77#issuecomment-6028691075) : Starlette background task async exécutant des envois synchrones sur l'event loop.
- [PR #86](https://github.com/maxime-c16/dive-analyser/pull/86#issuecomment-6039958901) : un helper async contient encore des accès ORM synchrones.
- [PR #145](https://github.com/maxime-c16/dive-analyser/pull/145#issuecomment-6330476862) : limite appliquée après `read()` intégral.

**Règle :** réservation avant parsing/écriture, lecture bornée pendant le flux, délais et budgets totaux, fermeture/annulation des flux rejetés. Cartographier le call graph jusqu'aux I/O synchrones. Threadpool avec session adaptée, ou file durable selon la durée ; ne pas passer aveuglément une session entre threads. Borner la file sans abandonner silencieusement les destinataires restants.

## 7. Preuves trop faibles et tests qui passent sans exercer le défaut

- [PR #44](https://github.com/maxime-c16/dive-analyser/pull/44#issuecomment-6010224254) : mock sans stream réel ; erreur avalée, test vert sans consommation.
- [PR #56](https://github.com/maxime-c16/dive-analyser/pull/56#issuecomment-6016981061) : fixture différente des données réellement fournies au composant.
- [PR #145](https://github.com/maxime-c16/dive-analyser/pull/145#issuecomment-6329758080) : toute redirection interprétée comme refus d'accès et présence d'un paramètre comme preuve d'expiration.
- [PR #145 — Range](https://github.com/maxime-c16/dive-analyser/pull/145#issuecomment-6330664756) : en-têtes vérifiés sans contrôler les octets retournés.

**Règle :** préciser le comportement observable et faire échouer la preuve si la protection est supprimée. Valider destination des redirections, octets, tailles, annulations et récupération des transactions. Les preuves portent un SHA, un environnement et une fenêtre temporelle ; un booléen saisi manuellement n'est pas une mesure.

## 8. Déploiement : le code seul n'est pas la fonctionnalité

- [PR #44](https://github.com/maxime-c16/dive-analyser/pull/44#issuecomment-6004441247) : flag de rollback non transmis par Compose et nouveau mount non appliqué par simple reload.
- [PR #42](https://github.com/maxime-c16/dive-analyser/pull/42#issuecomment-6010059088) : `getattr` ne protège pas une colonne ORM absente du schéma.
- [PR #107](https://github.com/maxime-c16/dive-analyser/pull/107#issuecomment-6088326055) : annonce d'une fonctionnalité dépendant du Mac avant sa mise à jour.
- [PR #139](https://github.com/maxime-c16/dive-analyser/pull/139#issuecomment-6320822331) : instruction proxy manquante, déjà documentée dans le workflow du dépôt.

**Règle :** relire la matrice de déploiement, préciser l'ordre SQL/backend/frontend/Mac/timers, tester les flags depuis l'environnement réellement injecté. Vérifier le SHA par service ; rollback source + dépendances + images. Les notes publiées sont immuables et listent tous les services nécessaires.

## 9. Secrets et capacités : les outils de preuve sont aussi des clients sensibles

- [PR #77](https://github.com/maxime-c16/dive-analyser/pull/77#issuecomment-6028984705) : erreur d'unicité exposant des paramètres de subscription dans les logs.
- [PR #142](https://github.com/maxime-c16/dive-analyser/pull/142#issuecomment-6324996823) : cause d'exception fournisseur conservée malgré message assaini.
- [PR #145](https://github.com/maxime-c16/dive-analyser/pull/145#issuecomment-6329758080) : cookie de session transmis au stockage lors d'une redirection.
- [PR #171](https://github.com/maxime-c16/dive-analyser/pull/171#issuecomment-6443206787) : capacité de salle trop courte et énumérable.

**Règle :** borner la confiance à chaque hop ; ne pas suivre une redirection avec des credentials d'une autre origine ; assainir tracebacks, causes, URL et artefacts. La détermination reproductible d'un comportement de jeu ne convient pas au choix d'un secret.

## 10. Domaine et UX : préserver le sens de bout en bout

- [PR #46](https://github.com/maxime-c16/dive-analyser/pull/46#issuecomment-6005295336) : traduction utilisée comme état métier, labels figés au chargement et clés absentes.
- [PR #135](https://github.com/maxime-c16/dive-analyser/pull/135#issuecomment-6304086296) : « ready » confond fallback 360p et cible 720p.
- [PR #164](https://github.com/maxime-c16/dive-analyser/pull/164#issuecomment-6401630990) : absence de note transformée en zéro, métriques frontend/backend différentes.
- [PR #162](https://github.com/maxime-c16/dive-analyser/pull/162#issuecomment-6397485362) : seuil CSS différent du seuil JS en paysage mobile.

**Règle :** états et nombres ont une définition commune aux producteurs/consommateurs. Séparer absent/zéro, prêt/fallback/cible, identité/texte traduit ; vérifier les liens et périmètres entre écrans. Pas de nouvelle couche de helper text pour masquer une incohérence.

## Répétitions : comprendre les boucles avant de compter

| PR / thème | Commentaires correspondants | Lecture |
| --- | ---: | --- |
| #34 / « friend ne doit pas écrire » | 5 | Même objection de contrat ; ne pas en tirer une règle actuelle de refus des OWNER |
| #164 / historique conservé en mémoire | 6 | `.all()` → `yield_per().all()` → accumulateur intégral : mécanisme restant au-delà de la correction locale |
| #168 / classement matérialisé avant limite | 5 | Top 10 de sortie, fenêtres temporelles et candidats non bornés ne suffisent pas |
| #115 / cleanup intégral | 4 | Limiter les dossiers de staging ne borne pas le helper de nettoyage appelé |
| #171 / seed publique, cookie, peer queries | 4 | Même triplet dans quatre commentaires ; les textes seuls ne disent pas si les commits avaient changé |

Comptages par commentaire, pas par finding. Les liens des familles permettent de retrouver les séries. Pour reproduire ces sélections, filtrer le numéro de PR puis les textes respectifs : `friend|read.only`, `memory|materializ`, `materializ|histogram|streak queries|response cap`, `cleanup_cache|every expired`, `public room code|public room|Secure|peer.ratings query` (insensible à la casse).

## Faux positifs, contrats périmés et corrections du bot

La répétition ne rend pas une règle vraie. Le [bot sur #34](https://github.com/maxime-c16/dive-analyser/pull/34#issuecomment-6002560080) traite friend comme strictement read-only. Le contrat **actuel** est ownership-scoped et indépendant du rôle pour les écritures de plongeons : voir `backend/app/services/write_guard.py`, `backend/app/services/dive_access.py`, `test_member_can_create_own_dive_but_not_shared_session` et `test_member_dive_visibility.py`. Le prompt de review contient déjà l'exception explicite. Sans comparaison des SHAs historiques, on ne classe pas toute la série comme fausse à sa date.

Un piège documentaire demeure : le résumé en tête de `test_friend_access.py` annonce encore que POST dives est interdit, alors que le test exécutable attend 201. Le corriger évite de réenseigner une règle dépassée aux agents. Le document d'architecture USER_AUTHORIZATION_V1 décrit également son état V1 historique ; ne pas le traiter comme description exhaustive des inscriptions actuelles.

Autre cas à examiner avant de généraliser : la remarque #86 sur l'immutabilité d'une note entre son ajout et sa publication. Le contrat porte sur les notes **publiées** ; vérifier la base de comparaison du garde avant d'inventer une règle « ne jamais modifier un fichier nouvellement ajouté dans sa PR ».

## Où fixer les causes

| Support | Contenu | Action dans cette passe |
| --- | --- | --- |
| `AGENTS.md` | Point d'entrée court obligatoire avant changement de code | Lien ajouté vers le guide |
| `docs/AGENT_ENGINEERING.md` | Règles stables et preuves adaptées au risque | Créé à partir des familles ci-dessus |
| En-tête du test friend | Contrat conforme au test actuel | Corrigé |
| Template PR | Portée vérifiée et décision sur chaque finding | Champs courts ajoutés |
| Prompt bot | Contrats spécifiques + SHA examiné, répétitions et preuves | Complété avec les quatre budgets et le contrôle des contrats actuels |
| CI | Détecteurs déterministes | Suite recommandée : budgets de requêtes sur endpoints ciblés, tests PostgreSQL de concurrence, reset des caches A→B |

## Skills créés après validation de la proposition

1. **`review-findings-to-fix`** : déclenchement à la demande de traiter une review. Entrées : PR, SHA et findings. Étapes : vérifier le contrat, regrouper les doublons, mapper tous les producteurs/consommateurs/écrivains, reproduire, corriger la cause, vérifier succès/erreur/retry, rendre un tableau finding → décision → preuve. Réfuter avec source quand nécessaire. Aucun commentaire GitHub automatique sans autorisation. Valeur : méthode multi-étapes réutilisable ; les règles métier restent dans le dépôt.
2. **`bounded-db-change`** : déclenchement sur listes, agrégations, inventaires et workers SQLAlchemy/PostgreSQL. Livrable : budget lignes/requêtes/mémoire, plan SQL, pagination, preuve de cardinalité et de justesse. Inclure alias distincts, lazy loads, fenêtres historiques, accumulateurs et starvation. Valeur : famille récurrente sur de nombreux domaines.

Ne pas créer dix skills par symptôme. Les invariants doivent rester versionnés dans le projet et accessibles à tous les agents. Les deux skills sont versionnés sous `.agents/skills/` et installés dans `~/.codex/skills/`. Leur description contient les formulations utilisateur qui doivent les déclencher. Les descriptions excluent le code ordinaire sans finding et les petits CRUD sans enjeu de volume. Le guide projet reste la source des invariants spécifiques.

## Suite recommandée, par ordre

1. Utiliser le guide et la grille de traitement sur la prochaine PR, en conservant les objections réfutées et leur source.
2. Ajouter des tests ciblés de nombre de requêtes et des races PostgreSQL là où une régression réelle a déjà été démontrée ; éviter un grep global interdisant `.all()`.
3. Relier les futurs commentaires au SHA du run, puis adjuger « confirmé / contrat périmé / hors diff / déjà corrigé / doublon ». Mesurer les causes distinctes par PR et les retours après correction.
4. Ajuster les deux skills sur leur usage réel ; continuer à référencer les docs du dépôt plutôt que recopier les contrats.

Release notes: none — analyse interne et consignes agents ; aucun comportement produit modifié. Aucun déploiement requis.

## Application de la cartographie

Le [registre des findings](REVIEW_FINDINGS.md) sépare les constats historiques,
les protections déjà présentes et les défauts reproduits dans le code actuel.
Les corrections produit sont préparées dans des PR distinctes des consignes.
