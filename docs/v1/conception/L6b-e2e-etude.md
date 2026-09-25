# L6b — Chiffrement de bout en bout : étude

> Étude du lot L6b (plan §2 L6b ; SRS EF-PRE-09, ENF-03 ; ADR-005). Version du 25/09/2026.
> **Point d'arrêt du plan : la décision revient au porteur du projet.** Cette étude prépare la décision (ADR-014) ; aucune implémentation n'est engagée.

## 1. Situation actuelle

- Les messages sont chiffrés **au repos** côté serveur (`EncryptedTextField`, Fernet) : une fuite de la base seule ne livre pas les contenus. Le serveur détient la clé : un administrateur système malveillant, une compromission du serveur ou une réquisition peut les lire.
- L6a a fermé l'accès **applicatif** au contenu : l'admin Django ne l'affiche plus (test dédié), aucune API de supervision ne le renvoie.
- Le bout en bout (E2E) retire au serveur la capacité de lire, y compris à l'opérateur.

## 2. Ce que le serveur fait, quelle que soit la technologie

| Fonction | Olm / Megolm | MLS |
|---|---|---|
| Annuaire des appareils et de leurs clés publiques d'identité | clés Curve25519 + Ed25519 par appareil | identité dans les *credentials* |
| Clés à usage unique, distribuées une seule fois (claim atomique) | *one-time keys* + *fallback key* | *KeyPackages* (à usage unique, plus un de dernier recours) |
| Relais de messages chiffrés opaques | messages Olm (1:1 par appareil) et Megolm (groupe) | messages *Commit* / *Welcome* / applicatifs, **ordonnés par le serveur** |
| Sauvegarde chiffrée de la clé de récupération | sauvegarde de clés côté serveur (clé de récupération détenue par l'utilisateur) | pas de mécanisme standard ; à concevoir |
| Changement de prêtre (rotation) | nouvelle session Megolm | *Remove* + *Commit* |

Contrat serveur prévu par le SRS : `PUT /e2e/devices/`, `POST /e2e/one-time-keys/`, `POST /e2e/keys/claim/`, `PUT /e2e/backup/`.

## 3. Comparaison

| Critère | `vodozemac` (Olm/Megolm) | OpenMLS (RFC 9420) |
|---|---|---|
| Maturité web | Réimplémentation Rust d'Olm par l'équipe Matrix, auditée (2022). Utilisée dans le navigateur via `matrix-sdk-crypto-wasm`, qui porte le chiffrement d'Element Web. Chemin éprouvé à grande échelle. | Bibliothèque Rust sérieuse, compilable en WASM, mais sans client web grand public de référence. Intégration navigateur à construire (stockage des états de groupe, IndexedDB). |
| Multi-appareils | Natif : chaque appareil a ses clés ; vérification croisée possible. | Natif : chaque appareil est une feuille du groupe. |
| Historique sur un nouvel appareil | Sauvegarde de clés + clé de récupération : le nouvel appareil relit l'historique. Correspond à l'attente d'un fidèle qui change de téléphone. | Par conception, un nouveau membre ne lit pas le passé ; il faut un mécanisme maison. |
| Ordonnancement serveur | Aucun (le serveur relaie). | Le serveur doit **ordonner les Commits** par groupe (service de distribution) : logique serveur supplémentaire et sensible. |
| Adéquation au besoin (1:1 fidèle ↔ prêtre, parfois plusieurs appareils) | Très bonne : Olm couvre le 1:1, Megolm les petits groupes d'appareils. | Surdimensionné : MLS vise les grands groupes. |
| Coût d'intégration | Le plus bas si le serveur expose un **sous-ensemble compatible Matrix** (upload/claim/query de clés, messages *to-device*) : le client réutilise `OlmMachine` sans réécrire le protocole. | Élevé : protocole client complet, stockage d'état, sauvegarde et ordonnancement à écrire. |

**Recommandation technique : `vodozemac` via `matrix-sdk-crypto-wasm`**, avec un serveur qui implémente le sous-ensemble d'API de clés attendu par `OlmMachine`.

## 4. Chiffrage

| Poste | Jours |
|---|---|
| Serveur : annuaire des appareils, clés à usage unique (claim atomique, anti-épuisement), requête des clés d'un correspondant limitée aux conversations existantes, messages *to-device*, sauvegarde chiffrée, révocation d'appareil | 4 à 5 |
| Serveur : messages opaques (nouveau type de message, conversation marquée E2E, coexistence Fernet en lecture seule, WebSocket), tests | 2 à 3 |
| Front : intégration `OlmMachine` (WASM, IndexedDB), cycle de vie des appareils, clé de récupération, états « déchiffrement impossible » | 5 à 7 |
| Preuve de concept à deux navigateurs, revue de sécurité ciblée | 2 à 3 |
| **Total** | **13 à 18** |

Le total dépasse le seuil de 12 jours du plan (le seul serveur tient dans 6 à 8 jours, mais le front et la preuve de concept sont indispensables pour que l'E2E existe).

## 5. Conséquences à accepter si l'E2E est livré

- Le **tableau de bord** ne peut plus compter que des métadonnées (volumes, délais), ce qui est déjà la règle (RG-09).
- L'**export de conversation** (EF-PRE-08) devient une fonction du client : le serveur ne peut plus produire de PDF.
- La **modération** et le **signalement** d'abus ne peuvent porter que sur un message transmis volontairement par la personne qui signale.
- La **perte de tous les appareils sans clé de récupération** rend l'historique illisible, définitivement : il faut le dire clairement à l'inscription.
- La recherche plein texte côté serveur dans les messages est impossible.

## 6. Options de décision

1. **Reporter l'E2E après le pilote** (recommandé par le garde-fou du plan). Pilote en Fernet côté serveur, avec : l'accès applicatif au contenu déjà fermé (L6a) ; une **mention de transparence** dans la politique de confidentialité (« les messages sont chiffrés sur nos serveurs ; l'équipe technique pourrait techniquement y accéder ; nous ne le faisons pas et aucun écran ne le permet ; le chiffrement de bout en bout est prévu ») ; la clé Fernet hors de la base, avec une rotation documentée (L9).
2. **Livrer l'E2E avant le pilote** (13 à 18 jours) : décaler le pilote d'autant, lancer la preuve de concept en premier et s'arrêter si elle échoue.
3. **Livrer le serveur seul maintenant** (6 à 8 jours) et le front après le pilote : déconseillé, car du code serveur de sécurité sans client pour l'exercer vieillit mal et doit être revu au moment de l'intégration.
