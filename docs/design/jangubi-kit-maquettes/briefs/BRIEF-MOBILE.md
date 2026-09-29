# Brief : application mobile Jàngu Bi (React Native, iOS + Android), thème Ciel

## 1. Enjeu
Maquettes de l'**application native** Jàngu Bi (Expo / React Native, composants dans l'esprit de **react-native-reusables** = shadcn/ui pour RN, NativeWind, icônes Lucide). Elles seront présentées au DG. Chaque écran doit ressembler à une **capture d'une vraie app en production sur l'App Store** : native, calme, précise, dense en vrai contenu. Rien qui fasse « généré par IA ».

Le produit, les règles de l'Église et les données fictives sont dans `../jangubi-v1/BRIEF-V1.md` §2 et §5 : **lis-les et réutilise-les à l'identique** (Marie-Thérèse Diouf, paroisse Saint-Dominique, jeudi 24 septembre 2026, 25e semaine du T.O., vert, lectures Ec 1 / Ps 89 / Lc 9, références JB-2026-00xxx, clergé, horaires, annonces).

Rappels non négociables :
- La demande d'acte va à la **paroisse du sacrement** ; l'acte est un **original papier à retirer**, jamais un PDF.
- **Aucune confession par message** : la conversation avec un prêtre affiche toujours la note « La confession ne se fait pas par message. Prenez rendez-vous pour une confession en présentiel. » ; la réservation de confession n'a **aucun champ de contenu** (pas de « motif », pas de note).
- Messagerie réservée aux majeurs (écran de refus explicatif).
- Messages **chiffrés de bout en bout** (mention discrète avec cadenas, écran de vérification de sécurité).
- Features gelées, à ne JAMAIS montrer : dons, intentions de messe, transfert paroissial, TV, assistant IA, chapelet communautaire, Offices des Heures.

## 2. Direction : « Ciel », natif
Le web est éditorial (filets, papier). L'app, elle, doit être **native** : on garde l'ADN (typographie Source Serif pour la Parole, bleu ciel, sobriété) mais on adopte les codes iOS/Android et ceux de react-native-reusables :
- fond **blanc**, surfaces groupées bleu-gris très pâle, cartes arrondies (rayon 16), filets 1 px ;
- **grands titres** iOS (Large Title) en Source Serif 4, qui tiennent la marque ;
- listes groupées façon Réglages iOS (rangées 52-56 px, chevron, séparateurs indentés) ;
- **bande de dates horizontale** (réf. Schedule/Task management) pour horaires et agenda ; **calendrier mensuel** avec pastilles (réf. Calendar) pour agenda et créneaux ;
- **pilules de filtre** (réf. Task management) ; **bottom sheets** avec poignée ; **segmented control** ; toasts ;
- carte « hero » d'accueil façon « greeting + progression » (réf. Task management) mais sobre : bleu 600 plein, texte blanc, sans dégradé.

Références visuelles vues dans Figma : Schedule Management, Task Management, Calendar mobile, React Native Reusables UI Kit. On emprunte la **structure** (bande de dates, cartes de créneau avec heure à gauche, pilules, tab bar, primitives RNR), jamais leurs couleurs.

## 3. Tokens (couleurs EXACTES, aucune autre)
| Rôle | Hex | Usage |
|---|---|---|
| paper | `#FFFFFF` | fond d'écran, tab bar, cartes posées sur surface, texte sur bouton primaire |
| surface | `#F7FAFD` | fond de liste groupée, champs, cartes sur blanc |
| surface2 | `#EDF3F9` | segmented control, pressed, chips inactives, piste de progression |
| ink | `#0E1A2B` | texte principal, icônes |
| ink2 | `#3A4859` | texte secondaire |
| ink3 | `#586677` | méta, placeholders, libellés d'onglet inactifs |
| line | `#DDE5EE` | séparateurs, bordures de carte |
| lineField | `#8391A4` | bordure de champ, radio/checkbox vides |
| b50 `#EEF6FC` · b100 `#D9EBF7` · b200 `#B3D8F0` · b300 `#7FC0E8` · b400 `#3FA3DD` · b500 `#1A8FCC` | | fonds teintés, sélection, pastilles, calendrier |
| **b600 `#0A6BA3`** | | **primaire** : boutons, liens, onglet actif, sélection |
| b700 `#085887` · b800 `#06466C` · b900 `#052F49` | | pressed, hero, texte sur b50/b100 |
| okT `#1F6B5C` / okBg `#E4F2EE` | | succès (« Prête à retirer ») |
| warnT `#8A5A0B` / warnBg `#FBF1DF` / warnDot `#B7801F` | | attention (« Complément demandé ») |
| errT `#A12A22` / errBg `#FBE8E5` | | erreur, destructif |
| litGreen `#2E6B3F` · litRed `#A3262A` · litGoldRing `#9A7A2C` · litViolet `#5B3A7E` | | couleurs liturgiques (pastilles ; blanc = pastille `#FEFEFE` cerclée litGoldRing) |
| fixedWhite `#FEFEFE` | | uniquement ce qui reste blanc en sombre (pouce de switch, texte sur hero b600) |

Ombres : seulement `0 1px 2px rgba(14,26,43,0.06)` (cartes) et `0 -8px 24px rgba(14,26,43,0.10)` (bottom sheet). Voile de modale : `rgba(14,26,43,0.40)`. Aucun dégradé.
**Les couleurs sont écrites en hex 6 chiffres majuscules exactement comme ci-dessus** (un script génère le thème sombre en les remappant).

## 4. Typographie
- **Source Serif 4** : grands titres (34/40, poids 600, lettrage -0.01em), titres de section éditoriaux (22/28), textes de la Parole (19/30 en lecture), citations (italique).
- **Libre Franklin** : toute l'interface. Corps 16/24, secondaire 14/20, méta 13/18, onglets 11/13 (500), boutons 16 (600), titres de barre de navigation 17 (600), en-têtes de liste groupée 13 (500, ink3, **sans capitales**).
- Chiffres tabulaires (`font-variant-numeric: tabular-nums`) pour heures, dates, références.
- **Interdits** : capitales espacées, mono, Inter/Roboto/SF simulé pour le contenu. (La barre de statut peut utiliser `-apple-system, 'Libre Franklin'`.)

## 5. Cadres et chrome système
- **iOS** : artboard 390 de large (hauteur 844 par défaut, plus pour les écrans qui défilent : montrer le contenu entier, par ex. 390×1240). Barre de statut 54 px (9:41, réseau, wifi, batterie) et **indicateur d'accueil** (134×5, rayon 3, ink, à 8 px du bas). Tab bar 84 px (50 + 34 de zone sûre).
- **Android** (écrans `AND-*`) : 412 de large × 915. Barre de statut 36 px (9:41 à gauche, icônes à droite), Top App Bar Material 3 (64 px, titre 22 Libre Franklin 500), barre de navigation Material 3 (80 px, indicateur pilule 64×32 b100 derrière l'icône active), barre de gestes 24 px. Rayon des boutons : pilule (999). FAB 56 px rayon 16 quand pertinent.
- Le gabarit `templates/tpl-ios.dc.html` fournit barre de statut, en-tête grand titre, tab bar, indicateur d'accueil et la bibliothèque de composants : **copie-le**, ne réinvente pas le chrome.

## 6. Composants (esprit react-native-reusables)
Tous présents dans le gabarit (bloc commenté « BIBLIOTHÈQUE ») :
- Button : primaire (b600, texte blanc, h 52, rayon 14), secondaire (surface2, texte ink), outline (bordure line), ghost, destructif (errT) ; taille sm h 40 rayon 12.
- Input / Textarea / Select : label 14/500 au-dessus, champ h 52 rayon 12 fond surface bordure lineField 1 px ; focus : bordure b600 2 px ; erreur : bordure errT + message 13 errT avec icône ; aide 13 ink3.
- Checkbox 22 rayon 6 ; Radio 22 ; Switch 51×31 (iOS) ; Segmented control ; Progress (h 6 rayon 3) ; Badge (h 24, rayon 999, 12/500) ; Avatar (initiales sur b100, texte b800) ; Skeleton (surface2) ; Separator.
- Card (rayon 16, bordure line, fond paper ou surface, padding 16) ; Accordion ; Tabs ; Alert (bandeau info b50/texte b900, warn, err) ; Dialog (alerte iOS centrée 270 px) ; Bottom sheet (poignée 36×5, rayon haut 20) ; Action sheet ; Toast ; Tooltip.
- Liste groupée (conteneur rayon 14 fond surface, rangées 56 px, icône 20 à gauche, chevron droite, séparateur indenté à 52 px).
- Bande de dates (7 jours, jour abrégé 12 + numéro 17, sélection = pastille b600 rayon 14 texte blanc, point sous les jours ayant des événements).
- Carte de créneau / messe : heure à gauche (tabular, 15/600), filet vertical, titre + lieu.
- Tab bar : 5 onglets **Accueil · Parole · Paroisse · Demandes · Prêtre**, icônes Lucide 24 (stroke 1.75), actif b600 avec icône pleine (fill b100 derrière le trait) et libellé 600 ; inactif ink3.

Icônes : **Lucide** (jeu de react-native-reusables), SVG inline 24×24, `stroke="currentColor"`, stroke-width 1.75, round caps. Utilise les tracés réels de Lucide (house, book-open, church, file-text, message-circle, bell, search, chevron-left/right, calendar, clock, map-pin, lock, shield-check, user, settings, check, x, plus, phone, info, circle-alert, wifi-off, share, bookmark, filter, sun, moon, globe, log-out…).

## 7. Qualité (non négociable)
- Une action principale par écran ; zones sûres respectées ; cibles ≥ 44 pt ; contraste ≥ 4,5:1.
- Contenus réels et cohérents entre écrans (mêmes noms, dates, références, statuts).
- États : chaque lot montre au moins un état particulier (vide, erreur de champ, chargement, succès, hors ligne, confirmation).
- Micro-copie juste, française, ecclésialement correcte ; wolof ponctuel possible (« Jàmm ak jàmm »).
- Interdits : emoji, dégradés, cartes à bordure gauche colorée, grilles de 4 tuiles identiques, rangées de stat cards, icônes dans des ronds pastel en série, lorem ipsum, microcopie creuse.
- Images : aucune photo ; emplacements art-dirigés (fond b50, SVG abstrait vitrail/arc en b200/b300, légende 12 ink3 « Photo · … »), attribut `data-photo-slot="…"`.

## 8. Format .dc.html (échoue EN SILENCE si non respecté)
Voir `../jangubi-v1/BRIEF-V1.md` §6, identique : `<script src="./support.js"></script>` gardé exactement ; `<x-dc><helmet>…</helmet><div racine taille fixe>…</div></x-dc>` ; bloc `<script type="text/x-dc" data-dc-script data-props='{"$preview":{"width":W,"height":H}}'>class Component extends DCLogic { renderVals() { return {}; } }</script>` ; styles inline ; balises fermées, attributs entre guillemets ; pas d'emoji ni d'image externe ; `<a href="APP-….dc.html">` pour naviguer entre écrans (noms EXACTS §9) ; `href="#"` sinon ; pas de `<button>` dans un `<a>`.
Polices : `<link href="https://fonts.googleapis.com/css2?family=Libre+Franklin:ital,wght@0,400;0,500;0,600;0,700;1,400&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&display=swap" rel="stylesheet">`.
**Pas de fausse barre de statut** n'est PLUS la règle ici : l'app native montre la barre de statut du gabarit (cadre de téléphone réaliste), mais **pas de cadre de téléphone** (pas de coque, pas d'encoche dessinée).

## 9. Liste des écrans (nom de fichier = `<ID>.dc.html`, taille)
Voir `ECRANS.md`.
