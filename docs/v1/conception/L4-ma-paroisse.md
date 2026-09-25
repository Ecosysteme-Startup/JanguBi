# L4 — Ma paroisse : annonces, agenda, notifications

> Conception du lot L4 (plan §2 L4 ; SRS §3.5, §7 ; ADR-012, ADR-013). Version du 25/09/2026.

## 1. Annonces (`apps/news`)

- **Modèle (expand)** : `scope_node` (FK `Node`, vide = global Numerisen), `scope_place` (FK `PlaceOfWorship`, facultatif), `is_sunday_notice` + `sunday_date`, `publish_at`, statut `scheduled`. `ArticleRead(article, user)` unique : une lecture par personne (EF-PAROI-05). Les colonnes `scope_type/diocese/parish/church` restent lisibles jusqu'en L9 ; une migration de données remplit `scope_node`/`scope_place` depuis elles.
- **Types** : `announcement` et `article` ; `pastoral_letter` est gelé (création refusée).
- **Autorisation** : `annonces.publier` sur le nœud ; portée globale réservée à `plateforme.admin`. Le lieu de culte doit appartenir au nœud.
- **Programmation** : `publish_at` futur → `scheduled` ; tâche Beat toutes les 5 min qui publie et notifie.
- **Flux** (`GET /me/feed/`) : contenus publiés globaux + ceux de la paroisse suivie et de ses ancêtres (diocèse, doyenné), triés par date, paginés.
- **API** : `GET /news/?node=&sunday=&type=` (public, `node` = le nœud et son sous-arbre) · `GET /news/{id}/` · `POST /news/{id}/read/` · `GET /news/categories/` · réactions conservées · `GET/POST /staff/news/` · `GET/PATCH/DELETE /staff/news/{id}/` · `POST /staff/news/{id}/publish/` · `POST /staff/news/{id}/unpublish/`. Le compteur `reads_count` n'est exposé qu'au staff.

## 2. Agenda (`apps/agenda`)

- **Modèle (expand)** : `scope_node`, `scope_place` ; `max_participants` existant.
- **Inscription** : verrou `select_for_update` sur l'événement, **409** si complet, idempotente pour la même personne ; désinscription.
- **API** : `GET /agenda/?node=&from=&to=` (public) · `GET /agenda/{id}/` · `POST/DELETE /agenda/{id}/register/` · `GET/POST /staff/agenda/` · `GET/PATCH/DELETE /staff/agenda/{id}/` (annulation douce) · `GET /staff/agenda/{id}/registrations/` · `GET /staff/agenda/{id}/registrations.csv` — sous `evenements.gerer`.

## 3. Paroisse suivie

`PUT /me/paroisse-suivie/` (`node_id` d'un nœud qui tient des registres, actif sur la plateforme ou non) : changement libre, sans validation (RG-01).

## 4. Notifications (EF-PAROI-08)

- `NotificationPreference` (une par personne) : canaux `in_app`, `email` ; sujets `annonces`, `evenements` ; silence de 22 h à 6 h (réglable).
- Nouvelle annonce publiée sur la paroisse suivie (ou un ancêtre) → notification in-app immédiate ; e-mail envoyé hors silence, sinon différé à la fin de la plage de silence.
- Rappel d'événement la veille aux inscrits (tâche Beat horaire).
- `GET/PUT /me/notification-preferences/`. La liste `GET /notifications/` et `POST /notifications/read-all/` existent déjà.

## 5. Revue (25/09/2026)

- Tâches par lot (publication programmée, rappels) : une transaction par élément ; un élément en erreur est journalisé et repris au passage suivant, sans annuler ni redoubler les autres.
- Diffusion aux fidèles par tranches de 500 (un diocèse peut compter des dizaines de milliers de fidèles).
- Contenus publiés **publics** (SRS §7 : `GET /news/` sans authentification), y compris ceux d'une paroisse : une annonce paroissiale est faite pour être lue. Les brouillons, programmés et retirés ne sont visibles que du staff du nœud.
- `TIME_ZONE = "Africa/Dakar"` (UTC+0 sans heure d'été) : les plages de silence sont exprimées dans l'heure locale.
