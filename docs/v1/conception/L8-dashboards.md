# L8 — Tableaux de bord

> Conception du lot L8 (plan §2 L8 ; SRS §3.8 EF-DASH-01 à 04 ; RG-09, RG-11 ; ADR-012, ADR-013). Version du 25/09/2026.

## 1. Contrat

| Route | Autorisation | Contenu |
|---|---|---|
| `GET /dashboards/nodes/{id}/?period=30` | `tableau_bord.voir` sur le nœud (héritage sur le sous-arbre) | Indicateurs agrégés sur le sous-arbre du nœud |
| `GET /dashboards/platform/` | `plateforme.admin` | Comptes, part du staff avec MFA, santé des files, dernières exécutions Beat, e-mails en échec |
| `GET /audit/` (livré en L2) | `plateforme.admin`, ou `audit.voir` sur un nœud | Journal d'audit filtrable (EF-DASH-04) |

`period` ∈ {7, 30, 90, 365} jours (30 par défaut). Les routes historiques (`me/`, `my-parish/`, `my-diocese/`, `my-province/`, `global/`, `parish/<id>/`, `diocese/<id>/`, `analytics/…`) sont retirées (ADR-013) : elles reposaient sur `org.*`, les rôles et les dons (gelés).

## 2. Indicateurs d'un nœud (sous-arbre)

| Bloc | Indicateurs | Source |
|---|---|---|
| Fidèles | rattachés (paroisse suivie dans le sous-arbre), actifs (connexion sur la période), nouveaux | `BaseUser.paroisse_suivie`, `last_login`, `date_joined` |
| Annonces | publiées sur la période, lectures, taux de lecture moyen | `Article` (portée `scope_node`), `ArticleRead` |
| Événements | à venir, inscriptions sur la période | `Event`, `EventRegistration` |
| Demandes d'actes | par statut, reçues sur la période, délai médian jusqu'au retrait, en retard | `apps.documents.selectors` (`status_counts`, `overdue_ids`) |
| Messagerie | conversations ouvertes sur la période, délai médian de première réponse, part sans réponse à 48 h | `Conversation`, `Message` (**horodatages et expéditeurs seulement, jamais le contenu**) |
| Confessions | créneaux proposés, réservés, honorés, absences, annulations | `ConfessionSlot`, `ConfessionBooking` |

- **Aucune donnée nominative, quel que soit le niveau** (RG-11 imposait seulement au-dessus de la paroisse ; la paroisse dispose déjà de ses files nominatives dans les écrans métier).
- Rattachement d'une conversation au sous-arbre : la paroisse suivie du participant qui n'est pas le prêtre joignable.
- Cache de 5 minutes par (nœud, période) : les agrégats ne dépendent pas de la personne qui consulte.
- Les requêtes de messagerie n'utilisent que `values_list` sur les colonnes de métadonnées : un test vérifie que la colonne `content` n'apparaît dans aucune requête SQL du tableau de bord.

## 3. Plateforme

- Comptes : total, actifs sur 30 jours, nouveaux sur 30 jours.
- Staff (titulaires d'une nomination active) : nombre, part avec une connexion MFA dans les 30 derniers jours. Nouveau champ `BaseUser.last_mfa_at` (expand, nullable), mis à jour au plus une fois par jour lors d'une authentification Keycloak avec `amr ∋ otp`.
- Santé : e-mails en échec sur 7 jours, demandes d'actes en retard, dernières exécutions des tâches Beat (`django_celery_beat.PeriodicTask.last_run_at`) et tâches Beat actives sans exécution depuis plus de 2 jours.

## 4. Tests

Autorisation par capacité et par sous-arbre (doyen → ses paroisses ; curé → sa paroisse, pas la voisine), absence de nom et d'e-mail dans la réponse, absence de `content` dans le SQL, valeurs agrégées sur un jeu de données construit, cache.
