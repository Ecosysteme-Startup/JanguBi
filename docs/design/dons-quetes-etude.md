# Jàngu Bi — Dons et quêtes : étude et questions ouvertes (27/09/2026)

> Copie du document projet `claude/dons-quetes-etude.md`, transmise le 27/09/2026.
> Décision : intégrer les dons et quêtes (auparavant exclus de la V1, principe « pas d'argent dans la V1 », module `donations` gelé).

## Conclusion de l'étude

Faisable à trois conditions : Numerisen ne touche jamais l'argent ; l'Église autorise la collecte par écrit ; sur iPhone, le paiement se fait hors de l'app (page web dans Safari).

## 1. Règles de l'Église

- **c. 1267 §3** : une offrande faite pour un but précis ne sert qu'à ce but → chaque don est rattaché à un fonds (quête dominicale, quête impérée, campagne projet…).
- **c. 1266** : quêtes impérées décidées par l'Ordinaire, reversées à la curie.
- **c. 1265** : pas de quête par une personne privée sans permission écrite de l'Ordinaire → autorisation de l'archevêché couvrant la collecte via Jàngu Bi.
- **c. 848** : aucun don dans le parcours d'une demande d'acte, aucun service conditionné à un paiement.
- **Honoraires de messe (c. 945-958)** : pas un don, montant fixé par les évêques → relèvent des intentions de messe, pas des dons.

## 2. Réglementation BCEAO

- Instruction n° 001-01-2024 (conformité exigée depuis mai 2025) : encaisser pour le compte de tiers = service de paiement soumis à agrément.
- Solution : agrégateur agréé (ex. PayDunya, agréé EDP au Sénégal), fonds versés directement sur le compte de l'entité d'Église. Frais indicatifs 1 à 3 % à confirmer par contrat.

## 3. Stores (point le plus bloquant)

- **iOS** : don dans l'app réservé aux organisations à but non lucratif approuvées par Apple, avec Apple Pay obligatoire (guideline 3.2.1 vi) ; Apple Pay indisponible au Sénégal → bouton « Donner » qui ouvre une page web dans Safari (3.2.2 iv).
- **Android** : dons défiscalisés exemptés de Google Play Billing ; éligibilité d'une paroisse sénégalaise à vérifier → même parcours web par prudence.

## 4. Données

Un don révèle la religion et des finances (données sensibles, loi 2008-12) : visibilité des noms limitée, aucun classement public, don anonyme possible.

## 5. Existant

Module `donations` gelé : DonationCampaign, Donation, 5 types, Wave / Orange Money / Free Money + espèces ; paiement en ligne non branché (confirmation automatique / IPN à faire). À adapter, pas à refaire ; retirer l'offrande de messe.

> Note du 27/09/2026 (cadrage, `docs/v1/conception/DONS-00-cadrage.md`) : l'app `donations` a été **supprimée** le 25/09/2026 (ADR-016). Le module est donc reconstruit sur le modèle V1 (arbre, offices, capacités) ; l'ancien code ne sert que de lecture via l'historique Git.

## Questions à trancher (dans cet ordre)

1. Qui encaisse juridiquement (titulaire du compte marchand) : l'archidiocèse (économat) avec affectation par paroisse, chaque paroisse, ou Numerisen (déconseillé : agrément BCEAO) ?
2. Quels types de dons en V1 : quête dominicale, quêtes impérées, campagnes pour un projet, contribution annuelle des fidèles (denier), offrandes de messe (via intentions) ?
3. Qui paie les frais : le donateur en supplément, déduits du don, commission Numerisen, ou prise en charge par la paroisse ou le diocèse ?
4. L'archevêché a-t-il déjà donné un accord écrit pour la collecte en ligne ? Ensuite : moyens de paiement (Wave, Orange Money, Free Money, carte, diaspora), reçus (fiscaux ou simples), don anonyme, saisie des quêtes en espèces par le secrétariat, calendrier (pilote Saint-Dominique ou version suivante).

## Sources

developer.apple.com/app-store/review/guidelines · developer.apple.com/apple-pay/nonprofits · support.apple.com/en-us/102775 · support.google.com/googleplay/android-developer/answer/9858738 · bceao.int (instruction 001-01-2024) · droitmediasfinance.com (agréments fintechs) · clerus.org (CIC livre V).
