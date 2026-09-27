# Jàngu Bi — kit de reprise des maquettes (27/09/2026)

Tout ce qu'il faut pour reprendre la conception dans une nouvelle session, sans l'historique de la précédente.

## 1. Où en est-on
| Livrable | Où | État |
|---|---|---|
| App mobile React Native (iOS + Android), thème Ciel | Canvas Claude Design « Jàngu Bi — App mobile · Ciel » (claude.ai/artifact/78YJ3YiLtjZWCb82hBsYjG) | 68 écrans × clair/sombre, validés |
| Web « Ciel produit » | Canvas « Jàngu Bi — Web · Ciel produit » (claude.ai/artifact/NMrbMhcbbFaTXXojoXg8Az) | 45 écrans × clair/sombre, jeu V1 complet |
| Anciennes maquettes web éditoriales (Lumière, Ciel, Atlantique, Cathédrale) | 4 canvas épinglés | Remplacées par « Ciel produit » |
| Étude dons et quêtes | Doc projet `claude/dons-quetes-etude.md` | 4 questions ouvertes |

## 2. Contenu du kit
- `briefs/BRIEF-V1.md` : produit, règles de l'Église, **données fictives de référence** (Marie-Thérèse Diouf, Saint-Dominique, 24 sept. 2026, références JB-2026-…), **format .dc.html** (§6).
- `briefs/BRIEF-MOBILE.md` : tokens Ciel EXACTS (§3), typo, composants, chrome iOS/Android.
- `briefs/BRIEF-WEB-CIEL.md` : direction web, liste des tics « IA » interdits.
- `briefs/ECRANS.md` (mobile) et `briefs/ECRANS-WEB.md` (web) : liste des écrans et noms de fichiers.
- `briefs/CONSIGNES-AGENT-*.md` : consignes données à chaque sous-agent (chemins à adapter).
- `gabarits/` : chrome iOS + bibliothèque de composants en commentaire ; en-tête public et barre latérale web.
- `scripts/themes.py` + `scripts/build_dark.py` : génèrent les variantes sombres par remappage des tokens (adapter `sys.path` vers le dossier de `themes.py`).
- `scripts/shot.py` : captures Playwright ; il injecte `fonts.css` (@font-face locaux Source Serif 4 et Libre Franklin, obtenus via `npm pack @fontsource/source-serif-4 @fontsource/libre-franklin`, car Google Fonts peut être bloqué dans le conteneur).

## 3. Méthode qui a marché
1. Brief + gabarit d'abord, validés sur capture.
2. Sous-agents en parallèle, un lot de 6 à 9 écrans chacun, avec lecture obligatoire des écrans déjà faits.
3. Contrôles automatiques : `support.js`, `DCLogic`, `$preview` = taille de la racine, hex hors tokens, liens morts.
4. Revue visuelle sur planches de captures, puis `build_dark.py`, puis publication sur le canvas (index `canvas.json` + fichiers).
5. Pour modifier un canvas existant : lire `project/canvas.json` et les écrans à changer, ne republier que ceux-là.

## 4. Prompt de reprise
```
Projet Jàngu Bi (Numerisen). Lis le doc projet claude/app-mobile-maquettes.md et le kit jangubi-kit-maquettes
(README-REPRISE.md d'abord). On reprend la conception des maquettes sur les canvas Claude Design existants :
<ce que je veux faire>. Respecte les tokens Ciel, les règles de l'Église et le format .dc.html du kit.
```
Pour les dons et quêtes : « Reprends claude/dons-quetes-etude.md et pose-moi les questions une à une. »
