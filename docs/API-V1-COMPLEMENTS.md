# API V1 — compléments (lot V1-routes)

Routes livrées pour clôturer la V1 : elles remplacent les « routes manquantes » listées par les fronts
(web `docs/BRANCHEMENT-FIDELE.md`, `docs/BRANCHEMENT-STAFF.md`, `src/config/fonctionnalites.ts` ;
mobile `docs/BRANCHEMENT-MOBILE-FIDELE.md`, `docs/BRANCHEMENT-MOBILE-STAFF.md`, `features.ts`,
`staffFeatures.ts`). Préfixe `/api/v1/`, authentification Keycloak Bearer, erreurs au format V1
`{"error": {"code", "message", "details"}}`. Toute route à capacité exige la MFA (`amr ∋ otp`).

Listes paginées : `{"count", "next", "previous", "results"}` (`limit` défaut 10, max 50 ; `offset`).

## 0. Capacités ajoutées (migration `hierarchy.0014`)

| Capacité | Libellé | Offices |
| --- | --- | --- |
| `comptes.valider` | Inviter, valider et activer les comptes du clergé | évêque diocésain, vicaire général, chancelier, **plateforme** |
| `intentions.gerer` | Recevoir et planifier les intentions de messe | curé, curé in solidum, secrétaire paroissial, évêque diocésain |

Elles apparaissent dans `GET me/capacites/`. La plateforme n'a pas `intentions.gerer` (elle ne traite
pas les dossiers des paroisses, RG-09).

## 1. Comptes du clergé — `clergy-accounts/` (web : `invitationsClerge`)

Parcours : le diocèse (ou la plateforme) invite → e-mail avec deux liens (inscription Keycloak, puis
page d'acceptation du front `/accept-invitation?token=…`) → la personne, connectée avec l'adresse
invitée, accepte → son compte est « en attente » → validé ou refusé avec motif → activable ou
désactivable. Tout est journalisé (`AuditEvent`) ; le jeton n'est stocké qu'haché (SHA-256).

| Méthode et chemin | Droit | Corps / réponse |
| --- | --- | --- |
| `GET clergy-accounts/invitations/?status=&node=&q=` | `comptes.valider` | liste paginée d'`Invitation` |
| `POST clergy-accounts/invitations/` | `comptes.valider` sur `node` | `InvitationCreate` → 201 `Invitation` + `accept_url` |
| `POST clergy-accounts/invitations/{id}/revoke/` | `comptes.valider` | → `Invitation` (`status: revoquee`) |
| `POST clergy-accounts/invitations/validate/` | public | `{"token"}` → `InvitationPublic` ; 410 si invalide |
| `POST clergy-accounts/invitations/accept/` | connecté | `{"token"}` → `ClergyAccount` ; 403 `invitation_email_mismatch`, 410 |
| `GET clergy-accounts/pending/?node=` | `comptes.valider` | liste paginée de `ClergyAccount` en attente |
| `POST clergy-accounts/{person_id}/validate/` | `comptes.valider` | → `ClergyAccount` (`statut_verification: verifie`) |
| `POST clergy-accounts/{person_id}/refuse/` | `comptes.valider` | `{"reason"}` obligatoire → `ClergyAccount` (`rejete`) |
| `POST clergy-accounts/{person_id}/activate/` | `comptes.valider` | → `ClergyAccount` ; 503 si Keycloak injoignable |
| `POST clergy-accounts/{person_id}/deactivate/` | `comptes.valider` | → `ClergyAccount` (Keycloak désactivé, sessions fermées) |

```json
// POST clergy-accounts/invitations/
{"node": "uuid", "email": "emmanuel.tine@exemple.sn", "first_name": "Emmanuel", "last_name": "Tine",
 "etat_de_vie": "clerc", "degre_ordre": "pretre", "ttl_days": 14}
// 201
{"id": "uuid", "email": "emmanuel.tine@exemple.sn", "first_name": "Emmanuel", "last_name": "Tine",
 "node": {"id": "uuid", "name": "Saint-Dominique"}, "etat_de_vie": "clerc", "degre_ordre": "pretre",
 "status": "en_attente", "expires_at": "2026-10-13T09:00:00Z", "invited_by_name": "…",
 "accepted_at": null, "revoked_at": null, "created_at": "…",
 "accept_url": "https://app…/accept-invitation?token=…"}   // montré une seule fois
// POST clergy-accounts/invitations/validate/ → 200
{"email_masked": "e•••e@exemple.sn", "first_name": "Emmanuel", "node_name": "Saint-Dominique",
 "etat_de_vie": "clerc", "degre_ordre": "pretre", "expires_at": "…",
 "register_url": "https://auth…/realms/jangubi/protocol/openid-connect/registrations?client_id=jangubi-web&…"}
// ClergyAccount
{"id": "uuid", "email": "…", "full_name": "Emmanuel Tine", "etat_de_vie": "clerc", "degre_ordre": "pretre",
 "statut_verification": "declare", "verification_note": "", "declared_at": "…", "is_active": true,
 "node": {"id": "uuid", "name": "Saint-Dominique"}}
```

- `status` : `en_attente`, `acceptee`, `revoquee`, `expiree` (calculé : en attente dont la date est passée).
- Codes : `comptes_forbidden`, `invitation_duplicate` (une invitation en attente par adresse et nœud),
  `invitation_laic`, `degre_ordre_required`, `degre_ordre_invalid`, `ttl_invalid` (1 à 30 jours),
  `invitation_invalide` / `invitation_expiree` (410), `self_action`, `reason_required`, `invalid_transition`.
- Périmètre : `comptes.valider` sur le nœud de l'invitation (héritage sur le sous-arbre) ; un compte hors
  périmètre répond 404. Notifications in-app : `compte.invitation_acceptee` (à l'invitant),
  `compte.valide` / `compte.refuse` (à la personne).
- **Écart web** : le front attendait `POST …/validate/` et `…/accept/` sans corps précis ; ici `{"token"}`.
  La file générale des déclarations spontanées reste `hierarchy/verifications/` (`personnes.verifier`).

## 2. Outils staff du quotidien

### 2.1 Épinglage d'une annonce — `staff/news/{id}/pin/` (mobile : `announcementPin`)

| Méthode | Corps | Réponse |
| --- | --- | --- |
| `POST` | `{"until": "2026-10-04T20:00:00Z"}` (future, 60 jours au plus) | `StaffArticle` |
| `DELETE` | — | `StaffArticle` |

Droit : `annonces.publier` sur le nœud (404 hors portée). Seul un contenu publié ou programmé s'épingle
(`not_published`) ; codes `pin_until_past`, `pin_until_too_far`. Le retrait (`unpublish`) désépingle.
Nouveaux champs : `is_pinned` (bool, date de fin non dépassée) et `pinned_until` sur `StaffArticle`
**et** sur les sorties publiques (`news/`, `news/{id}/`, `me/feed/`, `me/feed/secondaires/`), dont
l'ordre devient : épinglés d'abord, puis `-published_at`. Journal : `annonce.epinglage`, `annonce.desepinglage`.

### 2.2 Équipe des compteurs de quête — `staff/dons/compteurs/` (mobile : `collectionTeam`)

Droit : `dons.saisir_quete` par une nomination **sur la paroisse même** (comme la saisie des quêtes).

| Méthode et chemin | Corps | Réponse |
| --- | --- | --- |
| `GET staff/dons/compteurs/?node=` | — | `{"compteurs": [Compteur], "noms_recents": ["Jean Diouf"]}` |
| `POST staff/dons/compteurs/` | `{"node": "uuid", "nom": "Awa Faye"}` | 201 `Compteur` |
| `PATCH staff/dons/compteurs/{id}/` | `{"nom": "Awa Faye"}` | `Compteur` |
| `DELETE staff/dons/compteurs/{id}/` | — | 204 (désactivé, jamais effacé) |

`Compteur` = `{"id": 3, "nom": "Awa Faye", "actif": true, "ajoute_le": "…"}`. `noms_recents` : noms vus dans
les quêtes des 90 derniers jours et absents de l'équipe (ordre alphabétique). Codes :
`counter_duplicate` (nom déjà actif, sans tenir compte de la casse), `counter_name_required`,
`counter_inactive`, `not_a_parish`, `dons_forbidden`. La saisie d'une quête garde des noms libres.

### 2.3 Séance ponctuelle de confession — `POST staff/confessions/sessions/` (mobile : `confessionSessionOpening`)

```json
{"place_id": 12, "date": "2026-10-10", "start_time": "09:00", "end_time": "10:00", "slot_minutes": 15,
 "priest_id": null}
// 201 : [Slot, …]  (même forme que GET confessions/slots/)
```

Droit : `confessions.gerer` sur le nœud du lieu. `priest_id` (facultatif) : ouvrir pour un autre prêtre
qui a lui aussi `confessions.gerer` sur ce nœud (`priest_not_confessor` sinon). Idempotent (un créneau
existant du prêtre à la même heure est gardé). Codes : `invalid_day` (aujourd'hui à +12 semaines),
`invalid_times`, `no_slot`, `session_too_long` (48 créneaux au plus), `place_inactive`. Journal :
`confessions.seance_ouverture`. Aucun champ de contenu (RG-08).

### 2.4 Conversation avec le demandeur — `POST staff/documents/{request_id}/conversation/` (mobile : `requestConversation`)

Réponse `{"conversation_id": "uuid", "created": true}` (201 à la création, 200 si elle existait). Ouvre ou
retrouve la conversation **prêtre ↔ demandeur** de la messagerie existante (`messaging/conversations/{id}/`).
Droit : `actes.traiter` (404 hors file) **et** `messagerie.recevoir_fideles` sur la paroisse de la demande.
Un secrétaire reçoit 403 `messaging_not_allowed` (la messagerie relie un fidèle et un prêtre, RG-09) : le
front propose alors téléphone et e-mail de contact de la demande. Demandeur mineur : 403 `minor` (RG-13).
Aucune donnée de la demande n'est copiée dans la conversation. Journal : `actes.conversation_demandeur`.

### 2.5 Tâches du jour — `GET staff/taches-du-jour/?node=&date=` (mobile : `todayEditorialTasks`)

```json
{"node": {"id": "uuid", "name": "Saint-Dominique"}, "date": "2026-09-26",
 "tasks": [
   {"code": "demandes_a_traiter", "label": "Demandes d'actes à traiter", "count": 2},
   {"code": "demandes_complement", "label": "Demandes en attente d'un complément", "count": 1},
   {"code": "quetes_a_confirmer", "label": "Quêtes à confirmer", "count": 0},
   {"code": "annonces_a_publier", "label": "Annonces en brouillon", "count": 1},
   {"code": "annonces_du_dimanche", "label": "Annonces du dimanche à relire", "count": 1},
   {"code": "intentions_a_planifier", "label": "Intentions de messe à planifier", "count": 1},
   {"code": "intentions_du_jour", "label": "Intentions de messe du jour", "count": 0},
   {"code": "confessions_du_jour", "label": "Créneaux de confession du jour", "count": 2}],
 "confessions": [{"slot_id": 41, "starts_at": "…", "ends_at": "…", "place_name": "Église Saint-Dominique",
                  "priest_name": "Emmanuel Tine", "reserved": false}]}
```

Chaque rubrique n'apparaît que si la personne a la capacité correspondante sur le nœud
(`actes.traiter`, `dons.saisir_quete`/`dons.gerer_fonds` au niveau paroisse, `annonces.publier`,
`intentions.gerer`, `confessions.gerer`/`confessions.voir_planning`) ; `confessions` vaut `null` sans
capacité confessions. Jamais le nom d'un pénitent. 403 `taches_forbidden` sans aucune de ces capacités
sur le nœud. « Confirmer les confesseurs » du mobile correspond à `confessions_du_jour`.

## 3. Recherche transverse — `GET search/?q=&types=&limit=&offset=` (mobile : `localSearch`)

Publique ; connecté, s'ajoutent les prêtres joignables et les pistes réservées à mes paroisses.
`types` : liste séparée par des virgules parmi `bible, paroisses, lieux, annonces, pretres, audio`
(défaut : tous). `limit` (1 à 20, défaut 5) et `offset` (0 à 200) s'appliquent **à chaque type**.

```json
{"q": "therese",
 "results": {
   "paroisses": {"items": [{"id": "uuid", "code": "DAK-ST", "name": "Sainte-Thérèse", "type": "paroisse",
                            "city": "Dakar", "on_platform": true}], "next_offset": null},
   "lieux": {"items": [{"id": 7, "name": "…", "kind": "chapelle", "city": "Dakar", "node_id": "uuid",
                        "node_name": "…"}], "next_offset": 5},
   "bible": {"items": [{"id": 1, "book_name": "Jean", "book_slug": "jean", "chapter": 1, "verse": 1,
                        "text": "…"}], "next_offset": null},
   "annonces": {"items": [{"id": "uuid", "title": "…", "excerpt": "…", "content_type": "announcement",
                           "published_at": "…", "node_id": "uuid", "node_name": "…"}], "next_offset": null},
   "pretres": {"items": [{"id": "uuid", "name": "Emmanuel Tine", "office": "Curé", "node_id": "uuid",
                          "node_name": "Saint-Dominique"}], "next_offset": null},
   "audio": {"items": [{"id": "uuid", "title": "Kyrie", "duration_seconds": 240.0, "source_name": "…",
                        "album_id": "uuid", "album_title": "…"}], "next_offset": null}}}
```

- Bible : FTS français + repli trigramme existants (`SearchService.verses`), édition configurée
  (ADR-008), 3 caractères au moins (sinon liste vide). Paroisses (paroisses, quasi-paroisses,
  aumôneries non supprimées) et lieux actifs : nom et ville, sans accents. Annonces : **publiées**
  seulement. Prêtres : connecté seulement ; clercs vérifiés actifs, nomination active avec
  `messagerie.recevoir_fideles`, qui acceptent de nouveaux échanges ; nom et office, jamais d'e-mail
  ni de téléphone ; une personne sans nom n'apparaît pas. Sonothèque : filtre d'écoute de
  l'utilisateur (`listenable_tracks` : publiques, paroisse si membre).
- Codes : `recherche_trop_courte` (moins de 2 caractères), `validation_error` (type inconnu).

## 4. Intentions de messe — `mass-intentions/` (web : `intentions`, `intentionsMesse`)

**Aucun paiement ni montant dans l'app** : pas de champ montant en base ni dans les contrats ; chaque
réponse destinée au fidèle porte `notice` : « L'application ne reçoit aucune offrande. Selon l'usage,
l'offrande de messe se remet directement au secrétariat de la paroisse. »

| Méthode et chemin | Droit | Corps / réponse |
| --- | --- | --- |
| `GET mass-intentions/notice/` | public | `{"notice": "…"}` |
| `POST mass-intentions/` | connecté | `IntentionCreate` → 201 `MassIntention` |
| `GET mass-intentions/mine/` | connecté | liste paginée de `MassIntention` |
| `POST mass-intentions/{id}/cancel/` | demandeur | → `MassIntention` (`annulee`) |
| `GET mass-intentions/parish/?node=&status=&date_from=&date_to=` | `intentions.gerer` | liste paginée de `StaffMassIntention` |
| `POST mass-intentions/{id}/accept/` | `intentions.gerer` | `{"scheduled_date", "scheduled_mass", "place_id"}` → `StaffMassIntention` (`planifiee`) |
| `POST mass-intentions/{id}/decline/` | `intentions.gerer` | `{"reason"}` → `StaffMassIntention` (`refusee`) |
| `POST mass-intentions/{id}/celebrate/` | `intentions.gerer` | → `StaffMassIntention` (`celebree`, messe passée) |

```json
// POST mass-intentions/
{"node": "uuid", "place_id": null, "kind": "defunt", "intention": "Pour le repos de l'âme de …",
 "is_anonymous": true, "requested_date": "2026-10-04", "requested_mass": "Messe de 10 h"}
// MassIntention
{"id": "uuid", "parish": {"id": "uuid", "name": "Saint-Dominique"}, "place": null, "kind": "defunt",
 "intention": "…", "is_anonymous": true, "requested_date": "2026-10-04", "requested_mass": "Messe de 10 h",
 "status": "recue", "scheduled_date": null, "scheduled_mass": "", "refusal_reason": "",
 "celebrated_at": null, "cancelled_at": null, "created_at": "…", "notice": "…"}
// StaffMassIntention = MassIntention sans notice + "requester_name", "announced_as" ("Une personne" si anonyme), "decided_at"
```

- `kind` : `defunt`, `action_de_graces`, `particuliere`. `status` : `recue`, `planifiee`, `refusee`,
  `celebree`, `annulee`.
- Règles : paroisse (ou quasi-paroisse) active sur Jàngu Bi (`not_a_parish`, `parish_inactive`) ; date
  entre aujourd'hui et +1 an (`date_past`, `date_too_far`) ; 10 intentions ouvertes au plus par personne
  (`too_many_open`) ; `accept` planifie ou **déplace** une intention reçue ou planifiée (il couvre le
  `propose-date` du web) ; `reason_required`, `not_yet`, `invalid_transition`, `intentions_forbidden`.
  Une intention hors de mes paroisses répond 404.
- Notifications in-app (sans le texte de l'intention) : `intention.recue` et `intention.annulee` au
  secrétariat (titulaires directs de `intentions.gerer` sur la paroisse), `intention.planifiee`,
  `intention.refusee`, `intention.celebree` au fidèle. Journal : `intention.demande`, `.annulation`,
  `.planification`, `.refus`, `.celebration`.

## 5. Indicateurs à basculer côté fronts

| Front | Indicateur | Route |
| --- | --- | --- |
| mobile staff | `announcementPin` | §2.1 |
| mobile staff | `collectionTeam` | §2.2 |
| mobile staff | `confessionSessionOpening` | §2.3 |
| mobile staff | `requestConversation` | §2.4 (prêtres seulement) |
| mobile staff | `todayEditorialTasks` | §2.5 |
| mobile fidèle | `localSearch` | §3 |
| web | `invitationsClerge` | §1 |
| web | `intentionsMesse`, `intentions` | §4 |

Restent sans route (hors lot) : transferts, messagerie cléricale, TV, réflexion pastorale, analytique
« activité », assistant, résumé fidèle, pièce jointe envoyée, rappel de confession désactivable,
sessions d'appareils, chiffrement de bout en bout, consentements par finalité, sujets de notification.
