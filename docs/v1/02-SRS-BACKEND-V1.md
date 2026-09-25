# Jàngu Bi — Spécification des exigences du backend V1 (SRS)

> Version 1.0 du 24/09/2026. Remplace `docs/SRS_Jangu_Bi_v2.4.md`, `docs/JanguBi_SRS_Complet.md` et `docs/JanguBi_SRS_Technique_v2.md` (archivés).
> Conventions : **EF** = exigence fonctionnelle, **RG** = règle de gestion, **ENF** = exigence non fonctionnelle. Priorités : **M** (Must, V1), **S** (Should, V1 si le temps le permet), **G** (gelé).

---

## 1. Objet et portée

### 1.1 Objet
Backend (Django 5.2, DRF, Channels, Celery) de la V1 de Jàngu Bi, application web gratuite destinée aux fidèles catholiques du Sénégal et à leurs paroisses. Pilote : Paroisse Saint-Dominique (Archidiocèse de Dakar).

### 1.2 Dans le périmètre
1. Référentiel hiérarchique paramétrable (arbre de juridictions, lieux de culte, horaires).
2. Personnes, offices, nominations, capacités.
3. Authentification déléguée à Keycloak.
4. **La Parole** : lectures du jour, Bible, chapelet personnel.
5. **Ma paroisse** : annonces (dont celles du dimanche), horaires, agenda, notifications.
6. **Demandes d'actes** : de la demande au retrait de l'original.
7. **Parler à un prêtre** : messagerie temps réel (chiffrement de bout en bout en L6b) et rendez-vous de confession en présentiel.
8. Tableaux de bord par nœud, journal d'audit, conformité (loi 2008-12).

### 1.3 Hors périmètre (gelé)
Dons, quêtes et paiements ; intentions de messe ; transfert paroissial ; TV ; assistant IA (RAG/Gemini) ; réflexion pastorale ; Liturgie des Heures (jusqu'à un accord AELF) ; chapelet communautaire ; Lectio Divina et plans de lecture ; lettres pastorales ; messagerie inter-clergé (S) ; **confession ou absolution à distance (exclue par l'Église)**.

### 1.4 Définitions
| Terme | Définition |
|---|---|
| Nœud | Élément de l'arbre des juridictions (province, diocèse, zone, doyenné, paroisse, quasi-paroisse, aumônerie, CEB, mouvement) |
| Lieu de culte | Église, chapelle, station ou sanctuaire rattaché à un nœud ; porte les horaires |
| Office | Fonction ecclésiale ou administrative exercée sur un nœud (curé, vicaire, secrétaire…) |
| Nomination | Attribution datée d'un office à une personne sur un nœud |
| Capacité | Droit applicatif élémentaire (`actes.traiter`…), porté par un office |
| Paroisse suivie | Paroisse choisie librement par le fidèle pour ses contenus |
| Paroisse du sacrement | Paroisse détentrice du registre où l'acte est inscrit |

---

## 2. Acteurs

| Acteur | Rôle realm Keycloak | Accès |
|---|---|---|
| Visiteur | — | Contenus publics : Parole, annuaire, fiches paroisses, horaires |
| Fidèle | `fidele` | Droits de base (§6.1) |
| Staff paroissial ou diocésain | `staff` (+ MFA) | Selon ses nominations et capacités |
| Administrateur plateforme (Numerisen) | `platform_admin` (+ MFA) | `plateforme.admin` : référentiels, comptes, supervision |

Un prêtre ou un religieux est d'abord un **fidèle** (il peut suivre une paroisse et demander un acte). Il n'obtient des capacités que par ses nominations.

---

## 3. Exigences fonctionnelles

### 3.1 Référentiel hiérarchique (HIE)
| ID | Exigence | P | Critère d'acceptation |
|---|---|---|---|
| EF-HIE-01 | Gérer des types de nœuds paramétrables avec leurs parents autorisés | M | Créer un nœud sous un parent non autorisé renvoie 400 avec un message explicite |
| EF-HIE-02 | Gérer l'arbre des nœuds (créer, modifier, changer de statut) sous `structure.gerer` | M | Un chancelier crée un doyenné dans son diocèse ; il ne peut pas en créer dans un autre diocèse (403) |
| EF-HIE-03 | Lister un sous-arbre, les enfants et les ancêtres d'un nœud | M | `children` et `ancestors` renvoyés en une requête, ≤ 150 ms pour 500 nœuds |
| EF-HIE-04 | Gérer les lieux de culte d'un nœud, dont un seul principal par paroisse | M | Un second principal renvoie 400 |
| EF-HIE-05 | Gérer les horaires récurrents (messe, confession, adoration) et leurs exceptions datées | M | La semaine calculée intègre les exceptions |
| EF-HIE-06 | Importer nœuds et lieux de culte par CSV avec simulation | M | Mode `dry_run` : rapport ligne par ligne, aucune écriture |
| EF-HIE-07 | Charger le profil « Sénégal » (types, province, 7 diocèses, doyennés de Dakar, paroisse pilote) | M | Commande idempotente |
| EF-HIE-08 | Exposer un annuaire public (recherche par nom, ville, diocèse ; paroisses actives sur Jàngu Bi) | M | Anonyme, paginé |
| EF-HIE-09 | Gérer l'arbre de la vie consacrée (institut → province religieuse → communauté) | S | Types dédiés, non territoriaux |

### 3.2 Personnes, offices, capacités (PER)
| ID | Exigence | P | Critère d'acceptation |
|---|---|---|---|
| EF-PER-01 | Profil : état de vie, degré d'ordre, incardination, institut, paroisse suivie | M | Champs exposés dans `/me/` |
| EF-PER-02 | Statut clérical déclaré par la personne, vérifié uniquement par un titulaire de `personnes.verifier` | M | Une déclaration reste « déclarée » tant qu'elle n'est pas vérifiée ; aucun effet sur les droits |
| EF-PER-03 | Catalogue d'offices paramétrable (profil « Sénégal » fourni) | M | 15 offices chargés (§6.2) |
| EF-PER-04 | Nommer, terminer ou annuler une nomination | M | Seul un titulaire d'un office listé dans `appointed_by` sur un nœud ancêtre (ou le même nœud) peut nommer |
| EF-PER-05 | Contrôler cardinalité, condition d'ordre et compatibilité office / nœud | M | Deuxième curé actif sur une paroisse → 400 (sauf office `cure_in_solidum`) |
| EF-PER-06 | Activer et terminer automatiquement les nominations selon leurs dates | M | Tâche quotidienne ; journal d'audit |
| EF-PER-07 | Importer le mouvement annuel des affectations (CSV, date d'effet, simulation) | M | Rapport : valides, avertissements, erreurs ; application atomique |
| EF-PER-08 | Moteur `peut(user, capacité, nœud)` avec héritage sur le sous-arbre | M | Matrice de tests §6.3 verte |
| EF-PER-09 | Retrait de capacités par diocèse (`CapabilityOverride`) | S | Le retrait s'applique au sous-arbre du diocèse uniquement |
| EF-PER-10 | `GET /me/capacites/` pour adapter l'interface | M | Liste `{capacite, node_id, node_name, herite}` |
| EF-PER-11 | Journal d'audit immuable des actions sensibles | M | Toute nomination, import, changement de statut d'acte ou réglage y figure |

### 3.3 Authentification (AUTH)
| ID | Exigence | P | Critère |
|---|---|---|---|
| EF-AUTH-01 | Valider les jetons d'accès Keycloak (signature JWKS, `iss`, `aud`, `exp`) | M | Jeton expiré ou d'une autre audience → 401 |
| EF-AUTH-02 | Provisionner une personne à la première requête authentifiée (`sub`) | M | Idempotent |
| EF-AUTH-03 | Authentifier les WebSocket avec le même jeton | M | Jeton invalide → fermeture 4401 |
| EF-AUTH-04 | Synchroniser le rôle realm `staff` avec l'existence d'une nomination active | M | Ajout ou retrait en moins d'une minute (tâche) |
| EF-AUTH-05 | Exiger la MFA pour les comptes `staff` et `platform_admin` | M | Configuré dans le realm ; vérifié par la claim `acr` / `amr` côté API pour les endpoints staff |
| EF-AUTH-06 | Migrer les comptes existants vers Keycloak sans réinitialisation de mot de passe | M | Script avec simulation ; les hachages `pbkdf2_sha256` sont importés |

### 3.4 La Parole (PAR)
| ID | Exigence | P |
|---|---|---|
| EF-PAR-01 | Lectures du jour (source selon `LITURGY_SOURCE` : `aelf` ou `crampon_refs`) avec date, temps liturgique, couleur et références | M |
| EF-PAR-02 | Calendrier liturgique calculé localement (temps, fêtes principales, couleur) | M |
| EF-PAR-03 | Bible Crampon 1923 : livres, chapitres, versets, recherche plein texte | M (recherche : S) |
| EF-PAR-04 | Chapelet personnel : mystères du jour, prières | M |
| EF-PAR-05 | Méditation du jour publiée par un prêtre (capacité `annonces.publier`, type `meditation`) | S |

### 3.5 Ma paroisse (PAR-OISSE → `PAROI`)
| ID | Exigence | P | Critère |
|---|---|---|---|
| EF-PAROI-01 | Publier une annonce ou un article sur un nœud (`annonces.publier`) | M | Un secrétaire ne peut pas publier sur une autre paroisse |
| EF-PAROI-02 | Marquer une annonce « du dimanche » avec sa date | M | Filtre `sunday=2026-09-27` |
| EF-PAROI-03 | Programmer une publication | M | Publication à `publish_at` (tâche) |
| EF-PAROI-04 | Flux du fidèle : paroisse suivie et contenus globaux | M | Trié par date, paginé |
| EF-PAROI-05 | Compter les lectures (une par personne) | M | Compteur exposé au staff |
| EF-PAROI-06 | Semaine des horaires d'une paroisse (tous lieux) | M | Public |
| EF-PAROI-07 | Événements avec inscription (places, liste, export CSV) | S | Complet → 409 |
| EF-PAROI-08 | Notifications : nouvelle annonce, rappel d'événement, silence 22 h – 6 h | M | Préférences par canal |

### 3.6 Demandes d'actes (ACT)
| ID | Exigence | P | Critère |
|---|---|---|---|
| EF-ACT-01 | Déposer une demande auprès de la **paroisse du sacrement** (type, motif, identité au moment du sacrement, date approximative, pièce facultative, mode de retrait, consentement) | M | La paroisse du sacrement doit être un nœud de type paroisse |
| EF-ACT-02 | Suivre la demande (statut, historique, messages de la paroisse) | M | Le fidèle ne voit jamais les notes internes |
| EF-ACT-03 | File de traitement par paroisse (`actes.traiter`) : filtres, compteurs par statut, retards | M | Aucune demande d'une autre paroisse |
| EF-ACT-04 | Transitions de statut (§8.1) avec journal immuable et notification bilatérale | M | Transition interdite → 400 |
| EF-ACT-05 | Saisie des références du registre (volume, page, numéro, mentions marginales) | M | Non visibles du fidèle |
| EF-ACT-06 | « Prête à retirer » : lieu, horaires, message ; rappel que l'original est signé et scellé | M | — |
| EF-ACT-07 | Annulation par le fidèle tant que le statut est « soumise » ou « complément demandé » | M | — |
| EF-ACT-08 | SLA et relances automatiques, seuils par nœud | M | — |
| EF-ACT-09 | Purge des pièces justificatives 90 jours après clôture | M | Tâche quotidienne, journal |
| EF-ACT-10 | Vue agrégée pour `actes.superviser` (sans nom) | M | — |

### 3.7 Parler à un prêtre (PRE)
| ID | Exigence | P | Critère |
|---|---|---|---|
| EF-PRE-01 | Lister les prêtres joignables de la paroisse suivie et des aumôneries (capacité `messagerie.recevoir_fideles` + disponibilité) | M | — |
| EF-PRE-02 | Ouvrir une conversation (fidèle majeur) | M | < 18 ans → 403 avec un message pédagogique |
| EF-PRE-03 | Temps réel (WebSocket) : messages, accusés, frappe, notifications globales | M | Reconnexion avec refresh du jeton |
| EF-PRE-04 | CGU de messagerie acceptées une fois par utilisateur | M | Correctif A1 |
| EF-PRE-05 | Bandeau « pas de confession par message » (`confession_notice`) | M | Toujours présent dans la réponse |
| EF-PRE-06 | Aucun accès au contenu par un administrateur ou le staff | M | Test : aucun endpoint admin ne renvoie de contenu |
| EF-PRE-07 | Disponibilités du prêtre (plages, absence jusqu'au) | M | — |
| EF-PRE-08 | Conservation de 180 jours, export et suppression par le fidèle | M | — |
| EF-PRE-09 | Chiffrement de bout en bout (serveur = annuaire de clés + relais opaque) | M (L6b, point d'arrêt) | Le serveur ne stocke aucun clair |
| EF-PRE-10 | Règles de créneaux de confession par prêtre et par lieu ; génération sur 4 semaines | M | — |
| EF-PRE-11 | Réserver ou annuler un créneau (sans aucun champ de contenu) | M | Créneau pris → 409 |
| EF-PRE-12 | Rappels J-1 et H-2 ; annulation par le prêtre avec message | M | — |
| EF-PRE-13 | Vue prêtre nominative ; vue secrétariat avec initiales uniquement | M | — |

### 3.8 Tableaux de bord et plateforme (DASH)
| ID | Exigence | P |
|---|---|---|
| EF-DASH-01 | Tableau de bord d'un nœud (`tableau_bord.voir`), agrégé sur le sous-arbre | M |
| EF-DASH-02 | Aucune donnée nominative au-dessus du niveau paroisse, aucun contenu de message | M |
| EF-DASH-03 | Tableau de bord plateforme : comptes, part MFA, santé Celery et Beat, erreurs | M |
| EF-DASH-04 | Consultation du journal d'audit filtrable (`plateforme.admin`, ou `audit.voir` sur un nœud) | M |

### 3.9 Conformité (CONF)
| ID | Exigence | P |
|---|---|---|
| EF-CONF-01 | Consentement explicite horodaté à l'inscription (version des CGU et de la politique) | M |
| EF-CONF-02 | Export des données personnelles (JSON) | M |
| EF-CONF-03 | Suppression du compte : anonymisation, purge des messages, conservation des traces légales anonymisées | M |
| EF-CONF-04 | Registre des traitements généré (document) | M |

---

## 4. Règles de gestion

| ID | Règle |
|---|---|
| RG-01 | L'appartenance paroissiale n'est pas un « transfert » : la paroisse suivie se change librement, sans validation. |
| RG-02 | Une demande d'acte est **toujours** adressée à la paroisse où le sacrement a été célébré. |
| RG-03 | L'application ne délivre jamais l'acte : l'original est signé par le curé (ou une personne mandatée) et scellé. Aucun PDF d'acte n'est généré. |
| RG-04 | Les files de travail (demandes, conversations « paroisse », créneaux) appartiennent au nœud. Une mutation de curé ne nécessite aucune migration de données. |
| RG-05 | Une capacité portée sur un nœud s'applique à son sous-arbre si l'office est `inherits_down`. |
| RG-06 | Un religieux ou une religieuse n'est pas un clerc ; ses droits découlent uniquement de ses nominations. |
| RG-07 | Le statut clérical n'est jamais auto-validé ni validé par un pair : seul un titulaire de `personnes.verifier` (chancelier par défaut) le vérifie. |
| RG-08 | La confession ne se fait jamais par message. Le module de confession gère des rendez-vous en présentiel, sans aucun contenu. |
| RG-09 | Aucun administrateur, Numerisen compris, n'accède au contenu des conversations. |
| RG-10 | Les données religieuses sont sensibles (loi 2008-12, art. 4.8) : consentement explicite, minimisation, pas de transfert à des tiers. |
| RG-11 | Les tableaux de bord au-dessus de la paroisse n'exposent que des agrégats. |
| RG-12 | Les pièces justificatives sont purgées 90 jours après la clôture de la demande. |
| RG-13 | Messagerie ouverte aux seuls majeurs en V1. |
| RG-14 | Le jeu de capacités est fermé : on n'en crée pas depuis l'interface. |

---

## 5. Modèle de données

### 5.1 Nouvelles entités (`apps/hierarchy`)
```
NodeType(code PK-like unique, label, is_territorial, order, allowed_parent_types M2M self)
Node(MP_Node) : id UUID, type FK NodeType, name, code unique, status[en_fondation|erige|supprime],
               address, city, lat, lng, erected_at, is_active_on_platform, legacy_model, legacy_id
PlaceOfWorship : id, node FK, name, kind[eglise_paroissiale|chapelle|station|sanctuaire], is_main, address, lat, lng
MassSchedule : id, place FK, kind[messe|confession|adoration], weekday 0-6, start_time, end_time?, language, note, valid_from, valid_to
ScheduleException : id, place FK, date, kind, cancelled bool, start_time?, note
Capability : code PK (ex. "actes.traiter"), label, description, domain
OfficeType : code unique, label, node_types M2M NodeType, required_order[aucun|diacre|pretre|eveque],
             cardinality[one|many], appointed_by M2M self, capabilities M2M Capability, inherits_down bool, is_system bool
OfficeAssignment : id, person FK, office_type FK, node FK, start_date, end_date?, status[proposee|active|terminee|annulee],
                   appointed_by FK person?, decree_ref, decree_file FK File?, created_at
CapabilityOverride : id, diocese_node FK, office_type FK, capability FK, effect[retrait]
AuditEvent : id, at, actor FK?, action, target_type, target_id, node FK?, metadata JSON, ip  (insert-only)
```

### 5.2 Personne (extension de `users.BaseUser`)
```
keycloak_sub unique null, etat_de_vie[laic|clerc|consacre], degre_ordre[aucun|diacre_transitoire|diacre_permanent|pretre|eveque],
incardination_node FK Node?, institut_node FK Node?, statut_verification[declare|verifie|rejete], verification_note,
paroisse_suivie FK Node?, date_of_birth?, consent_version, consent_at, messaging_cgu_accepted_at
```

### 5.3 Nouvelles entités (`apps/confessions`)
```
ConfessionSlotRule : id, priest FK person, place FK PlaceOfWorship, weekday, start_time, end_time, slot_minutes (10), valid_from, valid_to
ConfessionSlot : id, rule FK, starts_at, ends_at, status[libre|reserve|bloque]
ConfessionBooking : id, slot FK unique(active), person FK, status[reservee|annulee_fidele|annulee_pretre|honoree|absent],
                    created_at, cancelled_at, cancel_message  (aucun champ de contenu)
```

### 5.4 Correspondance pour la migration (L1, L2)
| Ancien | Nouveau |
|---|---|
| `org.Province` / `Diocese` / `Deanery` / `Parish` | `Node` de type `province` / `diocese` / `doyenne` / `paroisse` |
| `org.Church` | `PlaceOfWorship` |
| `org.ReligiousOrder` / `ReligiousCommunity` | `Node` de type `institut` / `communaute` |
| `UserRole.super_admin` | rôle realm `platform_admin` |
| `UserRole.diocese_admin` + `RoleAssignment(scope=diocese)` | `OfficeAssignment(delegue_numerique_diocesain)` |
| `UserRole.parish_admin` + `pastoral_role=pretre` | `OfficeAssignment(cure)` |
| `UserRole.parish_admin` sans rôle pastoral | `OfficeAssignment(referent_numerique)` |
| `UserRole.church_admin` | `OfficeAssignment(vicaire)` si prêtre, sinon `secretaire_paroissial` (à valider à la main) |
| `pastoral_role` | `etat_de_vie` + `degre_ordre` (statut `declare`) |
| `Membership(is_primary)` / `Profile.primary_parish` | `paroisse_suivie` |
| `ClergicalInvitation` / `ClergySelfDeclaration` | `OfficeAssignment(status=proposee)` / `statut_verification=declare` |
| `DocumentRequest.target_parish (org.Parish)` | FK `Node` |
| `DocumentRequest.Status.document_deposited` | `prete_a_retirer` |

---

## 6. Capacités et offices

### 6.1 Droits de base (sans capacité)
Lire les contenus publics · suivre une paroisse · demander un acte et suivre ses demandes · converser avec un prêtre joignable (majeur) · réserver un créneau de confession · gérer son profil, son consentement, ses données.

### 6.2 Catalogue des capacités (fermé)
| Code | Sens |
|---|---|
| `structure.gerer` | Créer ou modifier des nœuds et lieux de culte du sous-arbre |
| `horaires.gerer` | Horaires et exceptions des lieux de culte |
| `offices.nommer` | Créer des nominations pour les offices dont on est « nommeur » |
| `personnes.verifier` | Vérifier un statut clérical ou consacré |
| `annonces.publier` | Publier annonces et articles |
| `evenements.gerer` | Événements et inscriptions |
| `actes.traiter` | Traiter les demandes d'actes |
| `actes.superviser` | Voir les indicateurs agrégés des demandes |
| `messagerie.recevoir_fideles` | Être joignable par les fidèles |
| `confessions.gerer` | Gérer ses créneaux de confession (et voir ses réservations) |
| `confessions.voir_planning` | Voir le planning (initiales) |
| `tableau_bord.voir` | Tableau de bord du nœud |
| `audit.voir` | Journal d'audit du nœud |
| `plateforme.admin` | Administration Numerisen (hors arbre) |

### 6.3 Offices par défaut (profil « Sénégal ») et capacités
| Office | Nœud | Ordre requis | Card. | Nommé par | Hérite | Capacités |
|---|---|---|---|---|---|---|
| `eveque_diocesain` | diocèse | évêque | 1 | plateforme | oui | toutes sauf `plateforme.admin` et `messagerie.recevoir_fideles` |
| `eveque_auxiliaire` | diocèse | évêque | n | plateforme | oui | `tableau_bord.voir`, `actes.superviser`, `annonces.publier`, `audit.voir` |
| `vicaire_general` | diocèse, zone | prêtre | n | évêque | oui | `structure.gerer`, `offices.nommer`, `tableau_bord.voir`, `actes.superviser`, `audit.voir` |
| `chancelier` | diocèse | aucun | 1 | évêque | oui | `structure.gerer`, `offices.nommer`, `personnes.verifier`, `tableau_bord.voir`, `audit.voir` |
| `delegue_numerique_diocesain` | diocèse | aucun | n | évêque, chancelier | oui | `structure.gerer`, `horaires.gerer`, `tableau_bord.voir` |
| `econome_diocesain` | diocèse | aucun | 1 | évêque | oui | `tableau_bord.voir` |
| `doyen` | doyenné | prêtre | 1 | évêque, chancelier | oui | `tableau_bord.voir`, `actes.superviser` |
| `cure` | paroisse, quasi-paroisse | prêtre | 1 | évêque, chancelier | oui | `horaires.gerer`, `offices.nommer`, `annonces.publier`, `evenements.gerer`, `actes.traiter`, `messagerie.recevoir_fideles`, `confessions.gerer`, `confessions.voir_planning`, `tableau_bord.voir`, `audit.voir` |
| `vicaire_paroissial` | paroisse | prêtre | n | évêque, chancelier | oui | `annonces.publier`, `evenements.gerer`, `actes.traiter`, `messagerie.recevoir_fideles`, `confessions.gerer` |
| `aumonier` | aumônerie | prêtre | 1 | évêque | non | `annonces.publier`, `evenements.gerer`, `messagerie.recevoir_fideles`, `confessions.gerer` |
| `recteur` | lieu de culte (via nœud) | prêtre | 1 | évêque | non | `horaires.gerer`, `annonces.publier`, `confessions.gerer` |
| `secretaire_paroissial` | paroisse | aucun | n | curé | oui | `horaires.gerer`, `annonces.publier`, `evenements.gerer`, `actes.traiter`, `confessions.voir_planning`, `tableau_bord.voir` |
| `referent_numerique` | paroisse | aucun | n | curé | oui | `horaires.gerer`, `annonces.publier`, `evenements.gerer`, `tableau_bord.voir` |
| `catechiste` | paroisse, CEB | aucun | n | curé | non | `evenements.gerer` |
| `responsable_ceb` | CEB | aucun | n | curé | non | `annonces.publier`, `evenements.gerer` |

### 6.4 Tests de matrice obligatoires (extrait)
- Le secrétaire de Saint-Dominique a `actes.traiter` sur Saint-Dominique, mais **pas** sur Sainte-Thérèse.
- Le curé nomme un secrétaire ; il ne peut pas nommer un vicaire (403).
- Le chancelier de Dakar nomme un curé à Dakar ; il ne peut pas nommer à Thiès.
- Un doyen voit le tableau de bord de ses paroisses, pas leurs demandes nominatives.
- Nomination terminée → capacité perdue dès le lendemain (tâche) et immédiatement si terminée manuellement.
- `CapabilityOverride` de Thiès sans effet à Dakar.

---

## 7. Contrat d'API (V1)

Base : `/api/v1/`. JSON, pagination `limit`/`offset`, erreurs `{"error": {"code", "message", "details"}}`. Authentification : `Authorization: Bearer <jeton Keycloak>`.

| Domaine | Méthode et chemin | Accès |
|---|---|---|
| Moi | `GET/PATCH /me/` · `GET /me/capacites/` · `POST /me/consent/` · `GET /me/export/` · `DELETE /me/` | authentifié |
| Hiérarchie | `GET /hierarchy/node-types/` · `GET/POST /hierarchy/nodes/` · `GET/PATCH /hierarchy/nodes/{id}/` · `GET …/{id}/children/` · `GET …/{id}/ancestors/` · `POST /hierarchy/import/nodes/?dry_run=` | lecture publique partielle ; écriture `structure.gerer` |
| Lieux et horaires | `GET/POST /hierarchy/nodes/{id}/places/` · `GET/PUT /hierarchy/places/{id}/schedule/` · `POST …/exceptions/` · `GET /public/nodes/{id}/week/` | `horaires.gerer` / public |
| Offices | `GET /hierarchy/office-types/` · `GET/POST /hierarchy/assignments/` · `PATCH …/{id}/` (terminer, annuler) · `POST /hierarchy/assignments/import/?dry_run=` | `offices.nommer` |
| Personnes | `POST /me/declaration/` · `GET /hierarchy/verifications/` · `POST /hierarchy/verifications/{id}/decision/` | fidèle / `personnes.verifier` |
| Parole | `GET /liturgy/today/` · `GET /liturgy/{date}/` · `GET /bible/books/` · `GET /bible/{book}/{chapter}/` · `GET /bible/search/?q=` · `GET /rosary/today/` | public |
| Annonces | `GET /me/feed/` · `GET /news/?node=&sunday=&type=` · `GET /news/{id}/` · `POST /news/{id}/read/` · `POST/PATCH /staff/news/` | public / fidèle / `annonces.publier` |
| Agenda | `GET /agenda/?node=` · `POST /agenda/{id}/register/` · `POST/PATCH /staff/agenda/` · `GET /staff/agenda/{id}/registrations.csv` | fidèle / `evenements.gerer` |
| Actes | `GET/POST /documents/requests/` · `GET /documents/requests/{id}/` · `POST …/{id}/supplement/` · `POST …/{id}/cancel/` · `GET /staff/documents/?node=` · `GET /staff/documents/counts/?node=` · `POST /staff/documents/{id}/{transition}/` · `PUT /staff/documents/{id}/register-ref/` · `GET/POST /staff/documents/{id}/notes/` | fidèle / `actes.traiter` |
| Messagerie | `GET /messaging/priests/` · `GET/POST /messaging/conversations/` · `GET /messaging/conversations/{id}/messages/?before=` · `POST /messaging/cgu/` · `PUT /messaging/availability/` · WS `/ws/messaging/conversations/{id}/`, `/ws/notifications/` | fidèle / `messagerie.recevoir_fideles` |
| Clés E2E (L6b) | `PUT /e2e/devices/` · `POST /e2e/one-time-keys/` · `POST /e2e/keys/claim/` · `PUT /e2e/backup/` | authentifié |
| Confessions | `GET /confessions/slots/?node=&from=` · `POST /confessions/bookings/` · `POST /confessions/bookings/{id}/cancel/` · `GET /me/confession-bookings/` · `GET/POST /staff/confessions/rules/` · `GET /staff/confessions/planning/?node=` | fidèle / `confessions.*` |
| Tableaux de bord | `GET /dashboards/nodes/{id}/` · `GET /dashboards/platform/` | `tableau_bord.voir` / `plateforme.admin` |
| Audit | `GET /audit/?node=&actor=&action=&from=&to=` | `audit.voir` / `plateforme.admin` |
| Contact paroisses | `POST /public/contact/` (formulaire « Pour les paroisses » : nom, fonction, paroisse, diocèse, téléphone, e-mail, message, consentement ; anti-spam et limitation de débit ; notification e-mail à Numerisen) | public |
| Notifications | `GET /notifications/` · `POST /notifications/read-all/` · `GET/PUT /me/notification-preferences/` | authentifié |

---

## 8. Cycles de vie

### 8.1 Demande d'acte
```
soumise ──start_verification──▶ en_verification ──request_info──▶ complement_demande
   │                                  │  ▲                               │
   │cancel (fidèle)                   │  └──────── supplement (fidèle) ◀─┘
   ▼                                  ├──mark_ready──▶ prete_a_retirer ──mark_collected──▶ retiree
annulee                               └──reject(motif obligatoire)──▶ rejetee
```

### 8.2 Nomination
`proposee → active` (à `start_date`) · `active → terminee` (à `end_date` ou manuellement) · `proposee → annulee`.

### 8.3 Réservation de confession
`reservee → honoree | absent` (par le prêtre après le créneau) · `reservee → annulee_fidele` (jusqu'à H-1) · `reservee → annulee_pretre` (avec message).

---

## 9. Exigences non fonctionnelles

| ID | Exigence |
|---|---|
| ENF-01 Sécurité | OWASP ASVS niveau 2 sur les endpoints staff ; rate limiting (connexion, réservations, messages) ; CORS et `OriginValidator` avec liste explicite ; secrets hors du repo ; en-têtes HSTS, CSP côté front |
| ENF-02 Authentification | Jetons d'accès de 5 à 15 min avec refresh côté client ; MFA obligatoire pour le staff ; révocation des sessions via Keycloak |
| ENF-03 Données sensibles | Consentement explicite ; chiffrement au repos des messages (Fernet jusqu'à L6b, puis E2E) ; aucune donnée religieuse dans les logs ; sauvegardes chiffrées |
| ENF-04 Performance | p95 < 300 ms pour les lectures, < 600 ms pour les écritures, sur le VPS actuel avec 1 000 utilisateurs actifs ; `peut()` < 5 ms avec cache |
| ENF-05 Disponibilité | 99 % en pilote ; restauration testée d'une sauvegarde de moins de 24 h |
| ENF-06 Réseau | Réponses compactes (pagination, champs utiles) pour la 3G ; compression gzip ou brotli |
| ENF-07 Qualité | ruff, mypy strict sur les nouvelles apps ; couverture ≥ 90 % sur services et selectors des apps V1 ; `make act` vert avant tout push |
| ENF-08 Observabilité | Logs structurés (`structlog`) avec identifiant de requête ; Sentry ; métriques Celery et Beat |
| ENF-09 Langue | Messages d'erreur et de notification en français ; typographie française (espaces insécables) dans les gabarits |
| ENF-10 Documentation | OpenAPI à jour à chaque lot (`schema.yml`) ; ADR pour toute nouvelle décision structurante |
| ENF-11 Hébergement | Pilote sur le VPS existant ; localisation des données à réévaluer avant l'ouverture publique (loi 2008-12, art. 49) |
