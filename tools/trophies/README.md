# Trophées DiveSensei (impression 3D)

Générateur paramétrique de trophées physiques aux couleurs de l'app : socle
anthracite inspiré de l'icône (carré arrondi), médaillon avec emblème en relief
(vagues du logo, plongeur stylisé dans les positions de plongeon), titre gravé.
Les trophées « milestone » reprennent les jalons détectés par
`backend/app/services/milestones.py`, les trophées « competition » servent aux
remises de prix (podium, progression, plongeur de l'année).

```
catalog.json  →  build.py  →  out/<id>/<id>.scad  →  OpenSCAD  →  STL
                                                  →  Blender   →  rendu PNG
```

## Prérequis

```bash
brew install --cask openscad@snapshot   # moteur Manifold + textmetrics
brew install --cask blender             # uniquement pour les rendus
pip3 install pillow                     # uniquement pour --sheet
```

Police : *Avenir Next Condensed* (macOS). Ailleurs, changer `FONT` /
`FONT_LIGHT` en tête de `trophy.scad`.

## Utilisation

```bash
python3 tools/trophies/build.py                          # tous les STL (~1 s / trophée)
python3 tools/trophies/build.py --sheet                  # planche 2D rapide pour valider les emblèmes
python3 tools/trophies/build.py --only serie --render    # STL + rendu Blender
python3 tools/trophies/build.py --render --lineup        # rendus + photo de groupe
python3 tools/trophies/build.py --only podium-or --owner "Léa Martin" --date "Saison 2026"
```

Sorties dans `tools/trophies/out/<id>/` (ignoré par git) :

| Fichier | Usage |
| --- | --- |
| `<id>_socle.stl` | socle, à imprimer tel quel (debout, sans support) |
| `<id>_embleme.stl` | médaillon, déjà à plat relief vers le haut (sans support) |
| `<id>_assemble.stl` | les deux pièces montées, pour visualiser uniquement |
| `<id>.png` | rendu studio (`--render`) |

## Impression

- Deux pièces → deux filaments sans imprimante multi-couleurs : socle en PLA
  noir/anthracite, médaillon en PLA teal (milestones) ou PLA silk or / argent /
  bronze (compétition). Le rendu montre ce choix.
- Couches 0,16–0,2 mm, buse 0,4 mm, 3 périmètres, 15 % de remplissage.
- La languette du médaillon (4,2 mm) entre dans la fente du socle avec 0,35 mm
  de jeu : ajuster `SLOT_CLEAR` si c'est trop serré ou lâche, un point de colle
  sinon.
- Astuce : passer un feutre peinture blanc ou teal dans la gravure du socle
  puis essuyer la surface → texte très lisible.
- Dimensions : 84 × 54 mm au sol, ~11,5 cm de haut. Pour un trophée plus grand,
  mettre à l'échelle les deux pièces du même facteur dans le trancheur.

## Ajouter un trophée

Ajouter une entrée dans `catalog.json` :

```json
{"id": "premier-10m", "family": "milestone", "title": "PREMIER 10 M",
  "layers": [
    {"shape": "tower", "at": [-10, -7], "args": {"h": 30, "levels": 3}, "h": 1.6},
    {"shape": "diver", "pose": "pike", "at": [10, 8], "rot": 30, "s": 0.5, "h": 2.2},
    {"shape": "water", "at": [0, -22], "args": {"w": 50, "rows": 1}, "h": 1.0}
  ]
}
```

- `title` : gravé en façade (taille ajustée automatiquement à la largeur).
- `owner` / `date` : gravés au dos (sinon « DIVESENSEI »), surchargeables avec
  `--owner` / `--date`.
- `finish` : couleur du médaillon dans le rendu (`teal`, `gold`, `silver`,
  `bronze`, `white`, `ink`).
- `layers` : reliefs empilés sur le médaillon, coordonnées en mm, centre du
  médaillon = `[0, 0]`, rayon utile ≈ 31 mm.
  - `at` position, `rot` rotation (°), `s` échelle, `scale_y` écrasement
    vertical, `h` hauteur du relief en mm (1,0 = fond discret, 2,0–2,4 =
    sujet principal).

Puis `build.py --only <id> --sheet` pour vérifier la composition (couleur =
hauteur de relief), et `--render` quand c'est bon.

### Vocabulaire des formes

| `shape` | `args` principaux |
| --- | --- |
| `diver` | `"pose"` (hors args) : `straight` (tendu/entrée), `pike` (carpé), `tuck` (groupé), `reach` (appel bras levés), `arch` (cambré), `stand` |
| `text` | `"text"` (hors args), `size`, `max_w` |
| `water` | `w`, `rows`, `gap`, `t` — vagues du logo |
| `wave` | `w`, `amp`, `periods`, `t`, `phase` |
| `splash` | `size`, `drops`, `spread` |
| `ripples` | `r`, `rings`, `t`, `squash` |
| `star` / `sparkle` | `r` |
| `check` | `s`, `t` |
| `flame` | `w`, `h`, `curl`, `inner` |
| `diamond` | `w` |
| `arc_arrow` | `r`, `t`, `a0`, `a1`, `head` |
| `arrow` | `a`, `b`, `t`, `head` |
| `chart` | `pts`, `t`, `head` |
| `bars` | `heights`, `w`, `gap` |
| `tower` | `h`, `levels`, `w` |
| `springboard` | `len_`, `t` |
| `laurel` | `r`, `a0`, `a1`, `leaves`, `leaf` |
| `peak` | `w`, `h` |
| `circle` | `r` |

Nouvelle forme : écrire un `module` 2D dans `trophy.scad` et ajouter son nom
dans `MODULE_SHAPES` de `build.py`. Nouvelle position de plongeur : ajouter une
ligne dans `POSES` (angles absolus des segments).

## Catalogue actuel

Milestones (médaillon teal) : premier-essai, premiere-reussite,
premier-parfait, percee, serie, nouvelle-hauteur, comeback, regularite,
plateau-franchi, face-a-la-peur.

Compétition : podium-or, podium-argent, podium-bronze, meilleure-progression,
plongeur-de-l-annee.
