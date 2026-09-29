# Consignes communes aux agents (échantillon web « Ciel produit »)

Dossier : `/tmp/claude-0/-home-claude/975bd498-8631-57d1-9f2e-59a3b5a3056e/scratchpad/web2/` (noté `W/`). Le mobile est dans `W/../mobile/`.

1. Lis ENTIÈREMENT : `W/BRIEF-WEB-CIEL.md` (surtout §1 : ce qu'il ne faut plus faire), `W/../mobile/BRIEF-MOBILE.md` §3, §4, §6, les deux gabarits `W/templates/*.dc.html`, puis `W/../jangubi-v1/BRIEF-V1.md` §2, §5, §6. Regarde en image les captures mobiles de référence dans `W/../mobile/shots/` (APP-B01-Accueil.png, APP-C01-Paroisse.png, APP-D05-Nouvelle-Infos.png, APP-E04-Conversation.png, APP-G01-Staff-Accueil.png, APP-G02-Staff-Demandes.png, APP-H01-Design-System.png) : le web doit visiblement être la même famille.
2. Écris chaque écran de ton lot dans `W/project/<ID>.dc.html` (nom EXACT), un fichier par appel Write. Copie le chrome du bon gabarit.
3. Hauteur de la racine = `$preview` = hauteur réelle du contenu (pas de contenu coupé, pas de grand vide). Pied de page public en bas.
4. Couleurs : uniquement les hex du tableau §3 du brief mobile, en MAJUSCULES 6 chiffres, plus `#FEFEFE` et les rgba d'ombre/voile indiqués.
5. Qualité : ce doit être indiscernable d'un vrai produit en production conçu par une bonne équipe produit. Hiérarchie simple, une action principale par écran, rythme régulier (8/16/24/32/48/96), densité honnête, contenus réels et cohérents (personnes, dates, références, horaires du brief), états visibles (erreur de champ, vide, sélection). Aucun des tics listés au §1 du brief web ; pas d'emoji, pas de dégradé, pas de bordure gauche colorée, pas de tuiles d'icônes en grille, pas de rangée de stat cards.
6. Liens vers les autres écrans de l'échantillon (`WEB-….dc.html`, liste §4), sinon `href="#"`. Pas de `<button>` dans un `<a>`.
7. Vérification obligatoire : `cd W && python3 shot.py shots project/<tes fichiers>`, puis **regarde chaque PNG** avec Read (réduis-le d'abord si très haut : PIL, crop par tranches de 1000 px) et corrige débordements, retours à la ligne malheureux (mets `&nbsp;` dans « 18 h 30 », « 24 sept. », avant « : ? ! »), alignements, vides. Vérifie par script : `<script src="./support.js"></script>`, `class Component extends DCLogic`, `$preview` = taille racine, aucun hex hors tokens.
8. Réponse finale : une ligne par écran `ID | W×H | Titre court`. Rien d'autre.
