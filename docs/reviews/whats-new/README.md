# Propositions « What's new »

Version B retenue et intégrée à React. Le flow final et ses garanties sont
documentés dans `../../RELEASE_NOTES.md`. Les captures `implemented-*.png`
montrent le vrai frontend avec `fixture-api.py` (compte et plongeons fictifs).
Les fichiers A/B/C ci-dessous restent les maquettes de comparaison initiales.

Maquettes HTML interactives, avec données fictives, reprenant les couleurs et la structure de la Library actuelle. Ce ne sont pas des captures d'une fonctionnalité intégrée à React. Aucun déploiement ni changement aux scripts de livraison.

## Trois présentations

- **A — Badge + popover** : indicateur discret ; ouverture au clic, sans notification automatique. `a-badge.png` montre le popover ouvert pour comparaison.
- **B — Notification + panneau (recommandé)** : notification non bloquante à la première visite après mise à jour ; bouton pour les détails, lien permanent « What's new » pour retrouver l'historique. Captures : `b-notification.png`, `b-details.png`, `b-mobile.png`.
- **C — Bandeau Library** : annonce dans la page, fermable ; plus visible, mais occupe de la place. `c-banner.png`.

Le prototype montre ces états et permet de fermer/ouvrir les détails ; il ne persiste pas les lectures et ne charge pas de données de release. L'historique affiché est illustratif.

Prévisualisation locale depuis la racine du dépôt : `python3 -m http.server 8765 --bind 127.0.0.1`, puis `/docs/reviews/whats-new/index.html?v=badge`, `?v=toast`, `?v=drawer&open=1` ou `?v=banner`.

## Production du contenu

### Choix validé et comportement anti-spam

Version B retenue par l'utilisateur. « What's new » ouvre le panneau latéral de détails et d'historique, uniquement au clic. Sur mobile, le panneau occupe la largeur de l'écran.

- Notification fermable par une croix ; cette fermeture est mémorisée. Le panneau possède aussi une croix, un bouton de retour et une fermeture par Échap.
- Une seule notification regroupe les nouveautés non vues, même si plusieurs déploiements se succèdent. Aucun empilement de notifications.
- Limite proposée : au plus une notification automatique par période de 24 heures et par compte/navigateur ; les nouveautés supplémentaires restent accessibles via le badge et l'historique. La limite est enregistrée dès l'affichage, pas uniquement à la fermeture, pour éviter une répétition au rechargement.
- Au clic ou à la fermeture de la notification, acquitter uniquement les identifiants des nouveautés présentes dans cette notification. Une mise à jour arrivée entre-temps reste non vue et ne remplace pas le contenu du panneau en cours de lecture.
- Dédupliquer par identifiant de note stable ; ne pas se baser sur un simple compteur ni un ordre lexical des SHA. Un rollback ou un redéploiement n'efface pas les acquittements.
- Synchroniser les lectures entre onglets ; les annonces arrivant pendant une lecture vidéo restent silencieuses. Une erreur de chargement du manifeste ou du stockage ne doit pas casser l'app ; en cas de stockage indisponible, garder le lien manuel et supprimer les annonces automatiques répétées.

Ces règles sont le contrat proposé pour l'implémentation. Le prototype HTML reste une maquette visuelle et ne les implémente pas encore.

Trois approches possibles, communes aux trois interfaces :

1. **Titres de PR automatiques** : très peu de travail, mais titres techniques et bénéfice utilisateur peu clair.
2. **Notes versionnées par PR (recommandé)** : l'agent ajoute une petite note structurée au code, relue dans la PR. `ship.sh` assemble les notes correspondant aux changements effectivement livrés. Aucun texte à saisir au moment du déploiement.
3. **Résumé IA pendant le déploiement** : flexible, mais ajoute une dépendance réseau/modèle et produit un texte non relu. À réserver éventuellement à une commande de préparation avant la PR.

Exemple de note dans un futur répertoire `release-notes/` :

```json
{
  "id": "browser-video-import",
  "audience": "all",
  "component": "frontend",
  "kind": "feature",
  "title": "Add videos from your browser",
  "description": "Select several clips and save them straight to your library."
}
```

Les identifiants sont stables et uniques. Une PR purement technique déclare explicitement « aucune nouveauté utilisateur » dans un mécanisme contrôlé par la CI ; elle ne déclenche pas une annonce vide. La CI valide la structure et la couverture des changements. AGENTS.md et REPO_WORKFLOW.md expliquent cette étape aux agents au même endroit que le flow PR → ship.

## Intégration proposée dans le flow existant

1. L'agent écrit la note dans sa PR, en une ou deux phrases centrées sur le bénéfice utilisateur.
2. `ci/ship.sh server --dry-run` affiche le contenu qui sera annoncé et les éventuelles notes manquantes.
3. `ship.sh server` prépare le manifeste depuis les commits réellement déployés jusqu'au commit cible, regroupe toutes les PR concernées et conserve un historique. Le manifeste est stocké hors du checkout live pour préserver le contrôle de propreté du dépôt.
4. Publication du manifeste uniquement après réussite des vérifications de déploiement. Si échec, aucune nouvelle annonce ; si rollback, restauration du manifeste correspondant aux services réellement actifs.
5. L'app lit un manifeste authentifié comprenant un identifiant de release et les notes. Elle affiche la notification une fois par compte et par release ; pour un premier MVP, stockage local avec clé compte + release (donc une fois par navigateur). Le panneau reste accessible dans la navigation.

Points à couvrir lors de l'implémentation : utiliser les SHA des images des services et pas seulement HEAD, car `--frontend-only` / `--backend-only` existent déjà ; ne pas annoncer une fonctionnalité nécessitant un service non livré ; n'activer les notes d'une fonctionnalité dépendant du Mac qu'après livraison effective du worker ; un redéploiement `--force` ne crée pas de nouvelle notification ; les notes admin ne sont pas exposées aux membres ; les PR multiples donnent une seule notification ; ne pas ouvrir spontanément un panneau ni interrompre la lecture d'une vidéo ; prévoir un état « nouvelle version disponible » si l'onglet utilise encore l'ancien frontend.

## Vérification des maquettes

Captures navigateur à 1280 × 800 et 390 × 844. Inspection visuelle des cinq captures, ouverture du panneau depuis la notification vérifiée ; aucun débordement horizontal à 390 px. La fonctionnalité finale nécessitera ses propres tests de déploiement, rollback et persistance de lecture.
