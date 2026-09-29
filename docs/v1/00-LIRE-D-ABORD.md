# Jàngu Bi — Kit de démarrage du backend V1

> Dossier : `JanguBi/docs/v1/` · Version du 24/09/2026 · Cible : Claude Code et l'équipe backend.
> **Ce dossier est la source de vérité de la V1.** Il remplace les SRS antérieurs (`docs/SRS_*`, `docs/JanguBi_SRS_*`) et les fichiers `../memory/*.md`, désormais archivés.

## Ordre de lecture

| # | Document | Contenu | Quand le lire |
|---|---|---|---|
| 1 | `01-PLAN-BACKEND-V1.md` | Le plan de A à Z : 10 lots, ordre, branches, estimations, critères de sortie | Avant tout |
| 2 | `02-SRS-BACKEND-V1.md` | Exigences fonctionnelles et non fonctionnelles, règles métier, modèle de données, contrats d'API, matrice des capacités | Avant chaque lot |
| 3 | `03-DECISIONS-ADR.md` | Les décisions d'architecture verrouillées et leur justification | Avant de remettre en cause un choix |
| 4 | `04-CI-LOCALE-ET-GIT.md` | Git flow, et la règle **act avant tout push** sur develop/stage/main | Avant le premier push |
| 5 | `05-PROMPTS-CLAUDE-CODE.md` | Les prompts prêts à coller, un par lot | Au lancement de chaque lot |

## Documents de cadrage (racine `Numerisen/`)

Ils ne sont pas à relire à chaque lot, mais ils expliquent le *pourquoi* :

- `CARTOGRAPHIE-JANGUBI.md` : l'état du code avant la V1 et le diagnostic.
- `BASE-CONNAISSANCE-EGLISE.md` : l'organisation de l'Église (droit canonique, Sénégal) et le cadre légal (loi 2008-12, AELF).
- `PERIMETRE-V1.md` : le périmètre fonctionnel de la V1.
- `HIERARCHIE-ECCLESIALE-PARAMETRAGE.md` : le modèle arbre + offices + capacités.
- `DESIGN-SYSTEM-LUMIERE-BLEU.md` et `PALETTES-JANGUBI.md` : la charte validée. Les maquettes sont dans Claude Design.

## En une phrase

La V1 réutilise le code existant, dans le même repo et sans réécriture. On **gèle** ce qui sort du périmètre, on **refond** l'identité et la hiérarchie (arbre paramétrable, offices, capacités, Keycloak), puis on **adapte** les quatre briques : Parole, Ma paroisse, Demandes d'actes, Parler à un prêtre (avec les rendez-vous de confession). À chaque étape, la CI est rejouée en local avec `act` avant tout push.
