# Composer sa série

Premier lot : séries à hauteur fixe (1, 3, 5, 7,5 ou 10 m), création depuis
une compétition accessible ou hors compétition, ordre, alternatives par
passage, DD calculées avec la référence versionnée existante. Les épreuves
ne sont pas encore structurées dans le calendrier : la hauteur est choisie
à la création, puis immuable. Aucune contrainte fédérale n'est inventée.

Les clips automatiques sont ceux des plongeurs dont le compte est OWNER,
au même code et à la même hauteur, classés par moyenne des évaluations
manuelles et automatiques, puis par date décroissante et ID décroissant.
Sans évaluation, la note enregistrée dans la bibliothèque (deux phases si disponibles,
sinon note globale) sert au classement et à l’affichage, selon la même échelle /10
que les analyses. Sans aucune note, le clip le plus récent est retenu. Le sélecteur « Meilleurs clips /
Plus récents » mémorise le mode automatique par série ; les choix manuels restent
épinglés dans les deux modes. Les notes dont le code
ou la hauteur du snapshot diffère du clip actuel sont exclues. Le choix
automatique est recalculé à la lecture ; un choix manuel reste épinglé,
mais disparaît de la projection si le clip est supprimé ou change de
propriétaire, de code ou de hauteur.

La fiche est privée. Le propriétaire peut donner et retirer un accès en
lecture seule à des membres actifs. Il transmet lui-même le lien affiché :
aucun message automatique. Les lecteurs partagés ne reçoivent ni clips,
ni identifiants de clips privés, ni contexte calendrier, ni destinataires.
Le partage de vidéos pourra utiliser les mécanismes média existants dans
un prochain lot. Les accès média habituels restent inchangés.

Les modifications s'enregistrent explicitement. Le numéro de version et
un verrou de ligne empêchent d'écraser une version concurrente. Les séries
incomplètes (y compris vides) et les DD inconnues s'enregistrent. Des codes
syntaxiquement invalides demandent correction. Les limites de sécurité
sont 20 passages et 5 alternatives par passage.

## Activation

Appliquer **avant** le backend :
`backend/migrations/add_dive_series.sql`. La table est marquée
`sql_migration_only` : aucun changement de schéma au démarrage.
Déployer frontend et backend via le workflow habituel. Aucun service Mac,
aucun import calendrier et aucun worker supplémentaire requis.

## Vérification visuelle locale

`bash backend/scripts/generate_series_review_media.sh` prépare une vidéo
de mire verticale et son affiche (ffmpeg requis, fichiers ignorés par Git).
`SERIES_REVIEW_SIZE=640x360` permet aussi de vérifier un clip horizontal. Aucun clip
personnel n'est copié dans les fixtures. Les clips « meilleurs » / « récents »
de l'aperçu sont des exemples explicitement marqués comme démonstration.

`npm run dev` dans frontend puis
`/e2e/fixtures/series-review.html` (éditeur) ou
`/e2e/fixtures/series-review.html?list=1` (liste/création).
Fixture réservée au développement, données fictives, aucun backend.

Les DD de la fixture proviennent du moteur de production et sont précalculées
pour les cinq hauteurs : `python3 backend/scripts/generate_series_dd_fixture.py`.
Le mode `--check` détecte un catalogue périmé. Aucune table de valeurs
d'exemple indépendante n'est utilisée. `?height=1m` (ou 3m/5m/7.5m/10m)
permet de vérifier les différences par hauteur.

Comparaison de points, répétitions, dépôt fédéral, validation réglementaire,
notation live restent des lots suivants.

## Éditeur compact (révision du 22 octobre)

Six positions horizontales par défaut ; la sixième peut être retirée pour
passer à cinq et restaurée (avec son contenu pendant la session). Les anciens
brouillons de moins de cinq positions sont complétés visuellement à six ; les
séries enregistrées à cinq conservent leur format. Une position vide est un
brouillon valide et conserve sa place à l'enregistrement. La liste affiche le
nombre de codes renseignés et le nombre de positions séparément.

Code saisi en majuscules automatiquement. Un code syntaxiquement complet
lance le calcul de DD et le choix automatique du clip après un court délai,
sans attendre une sortie de champ ; le focus avance immédiatement. Les
réponses sont liées au code et à la hauteur, jamais à la position visuelle,
pour ne pas corrompre une carte modifiée ou réordonnée entre-temps.

Collage de plusieurs codes (espaces, virgules, points-virgules ou retours à la
ligne) dans les positions consécutives. Un collage trop long ou invalide est
refusé sans modifier la série. Entrée et flèches aux bords des champs pour
naviguer, retour arrière dans une position vide pour revenir à la précédente,
Ctrl/Cmd+S pour enregistrer. Total DD des plongeons principaux connus et
compteur de complétion. Alternatives, choix des clips et partage s'ouvrent à
la demande pour garder les six cartes lisibles. Sur mobile, les passages forment une liste verticale compacte : code et DD en tête,
nom à gauche et aperçu vidéo à droite. Les formulaires s’ouvrent dans des panneaux
inférieurs avec gestion du focus ; lecture et enregistrement restent accessibles
en bas de l’écran. Le lecteur privilégie la hauteur de la vidéo : liste latérale sur ordinateur,
sélecteur compact de passages sous la vidéo sur téléphone.

Le format cinq/six est un choix de préparation, sans certification de
conformité d'une catégorie, d'un sexe ou d'une compétition particulière.

## Lecture de la série

La carte ouvre maintenant le lecteur de série au passage choisi, sans
quitter l'éditeur. « Voir la série » ouvre la lecture depuis le premier clip
disponible. Le lecteur fige les choix affichés à son ouverture ; le dialogue
empêche de modifier les cartes pendant la lecture. Une vidéo en erreur
arrête l'enchaînement, avec réessai ou passage explicite au clip suivant.
Les positions sans clip sont annoncées avant la lecture des clips disponibles.

Les routes média existantes contrôlent chaque accès ; aucune nouvelle
autorisation ni URL publique n'est créée. Deux appels média au plus en parallèle, sans monopoliser une place pendant
la préparation d’un autre clip ; le clip courant et le suivant sont chargés dans des éléments
vidéo réutilisés lors de la transition. Les autres originaux ne sont pas
téléchargés spéculativement. Sans version lisible, le lecteur peut demander
la préparation existante puis vérifier son état pendant au plus 30 secondes.
Fermer le dialogue annule les requêtes et libère les éléments vidéo.

Le rendu de la carte et son lecteur ne dépendent pas du succès de la requête
DD. Le choix automatique reste fait par le backend, avec remplacement
manuel possible et respect des droits actuels. Les clips privés ne deviennent
pas lisibles par les destinataires d'un simple partage de fiche.

## Animations

Distribution courte des six cartes à l’ouverture, déplacement FLIP des deux
positions réordonnées, révélation DD et retournement de l’aperçu lors d’un
changement de clip. Les champs et les médias conservent leur identité DOM.
Les panneaux mobiles entrent depuis le bas ; le lecteur et les passages
utilisent des transitions courtes. Animations WAAPI annulées au changement
ou démontage, aucune dépendance ajoutée. Toutes les animations sont
désactivées avec prefers-reduced-motion.

Le lecteur réutilise les URLs d’aperçu autorisées et les affiches déjà reçues
par les cartes. Une URL disponible et une première image décodée sont deux
états distincts ; l’affiche reste visible jusqu’à loadeddata/canplay. Les
appels de statut ont un délai maximum de 12 secondes ; les préparations
sont consultées avec attente progressive et limite de 30 consultations.
Après 10 secondes d’attente sur un passage, le lecteur propose un réessai.
Un réessai conserve les URLs et les éléments vidéo des voisins prêts.

Le lecteur occupe la hauteur disponible : vidéo et liste latérale sur
ordinateur, vidéo flexible et navigation compacte sur téléphone. En paysage
sur écran bas, la liste revient à côté du lecteur. object-fit: contain
préserve l’intégralité des images verticales et horizontales.

## Comparer une alternative

Options du passage → Comparer : deux vidéos portrait côte à côte sur
ordinateur, une vidéo visible avec onglets accessibles au clavier sur
téléphone. La lecture reste indépendante et changer de côté met les vidéos
en pause. Le choix du clip reste local jusqu’à « Utiliser ». Les deux côtés
réutilisent useSeriesMedia, aussi utilisé par le lecteur de série : aperçus
autorisés existants, limite de deux appels, préparation bornée et annulation.
Les médias sont libérés au changement de clip et à la fermeture.

Tableau des DD, notes /10 et points estimés (note du clip × DD × 3).
Un écart est alternative moins plongeon principal. Aucune note/DD manquante
n’est inventée : estimation et écart restent absents. Ces points sont
une estimation, sans application de règlement ou résultat officiel.

Utiliser échange le plongeon principal et l’alternative, en conservant les
clips choisis. Annuler restaure le passage avant l’échange tant qu’il n’a
pas été remodifié ou enregistré. La sauvegarde reste explicite. Animations
courtes de dialogue/onglet/aperçu et d’échange, respectant reduced-motion.
