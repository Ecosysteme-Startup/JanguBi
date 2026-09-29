# L5 — Demandes d'actes (`apps/documents`)

> Conception du lot L5 (plan §2 L5 ; SRS §3.6, §8.1 ; ADR-009, ADR-012, ADR-013). Version du 25/09/2026.

## 1. Cycle de vie (SRS §8.1)

| Code API | Libellé | Transitions sortantes (acteur) |
|---|---|---|
| `submitted` | Soumise | `start_verification` → `under_verification` (paroisse) · `cancel` → `cancelled` (fidèle) |
| `under_verification` | En vérification | `request_info` → `info_requested` · `mark_ready` → `ready_for_pickup` · `reject` (motif obligatoire) → `rejected` (paroisse) |
| `info_requested` | Complément demandé | `supplement` → `under_verification` · `cancel` → `cancelled` (fidèle) |
| `ready_for_pickup` | Prête à retirer | `mark_collected` → `collected` (paroisse) |
| `collected`, `rejected`, `cancelled` | Retirée, Rejetée, Annulée | terminales ; `closed_at` renseigné |

Les codes restent en anglais, comme l'existant ; seuls les libellés sont en français. Migration des statuts : `validated` et `document_deposited` → `ready_for_pickup` (le « dépôt » numérique n'existe plus). Toute transition interdite → 400 ; chaque transition écrit le journal de la demande (`DocumentRequestStatusLog`) et le journal d'audit, et notifie l'autre partie (in-app + e-mail).

## 2. Modèle (expand)

- `target_node` (FK `Node`) : **paroisse du sacrement**, obligatoirement un nœud qui tient des registres (paroisse, quasi-paroisse) — RG-02. Migration depuis `target_parish` (`org.Parish`).
- Retrait : `pickup_mode` (`secretariat` | `transfer_to_followed_parish`, choisi par le fidèle), `pickup_place` (FK `PlaceOfWorship`), `pickup_hours`, `pickup_message`, posés au passage en « prête à retirer » ; rappel au fidèle que l'original est **signé et scellé** (RG-03).
- Registre (EF-ACT-05, jamais exposé au fidèle) : `register_volume`, `register_page`, `register_number`, `register_marginal_notes`.
- `closed_at`, `cancelled_at`, `attachments_purged_at`.
- `DocumentSlaSetting(node, escalate_days, requester_reminder_days, pickup_reminder_days)` : le réglage du plus proche ancêtre s'applique, sinon les valeurs par défaut (7 / 5 / 3 jours).
- Coffre-fort gelé : plus de pièce « document final paroisse » (ADR-009) ; seules les pièces justificatives facultatives du fidèle.

## 3. Autorisation

- Fidèle : ses propres demandes (droits de base, SRS §6.1). Les notes internes et les références du registre ne lui sont jamais renvoyées.
- `actes.traiter` sur le nœud de la demande : file, détail nominatif, transitions, notes, références.
- `actes.superviser` : indicateurs agrégés sans nom (`/staff/documents/stats/`).
- Hors portée → 404.

## 4. API

Fidèle : `GET/POST /documents/requests/` · `GET /documents/requests/options/` · `GET /documents/requests/{id}/` · `POST …/{id}/supplement/` · `POST …/{id}/cancel/`.
Paroisse : `GET /staff/documents/?node=&status=&overdue=` · `GET /staff/documents/counts/?node=` · `GET /staff/documents/stats/?node=` · `GET /staff/documents/{id}/` · `POST /staff/documents/{id}/{transition}/` (`start-verification`, `request-info`, `mark-ready`, `mark-collected`, `reject`) · `PUT /staff/documents/{id}/register-ref/` · `GET/POST /staff/documents/{id}/notes/` · `GET /staff/documents/{id}/logs/`.

## 5. Tâches

- Relances SLA quotidiennes (existant, adapté aux seuils par nœud).
- Purge des pièces justificatives 90 jours après `closed_at` (RG-12), avec audit.
