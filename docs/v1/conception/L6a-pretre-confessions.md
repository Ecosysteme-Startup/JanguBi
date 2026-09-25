# L6a — Parler à un prêtre et rendez-vous de confession

> Conception du lot L6a (plan §2 L6a ; SRS §3.7, §8.3 ; ADR-005, RG-08, RG-09, RG-13). Version du 25/09/2026.

## 1. Messagerie (`apps/messaging`, adaptée)

- **Joignabilité** (EF-PRE-01) : un prêtre est joignable s'il détient `messagerie.recevoir_fideles` (curé, vicaire, aumônier). `GET /messaging/priests/` liste ceux de la paroisse suivie du fidèle (nomination sur ce nœud) et des aumôneries du même diocèse. Chacun porte sa disponibilité.
- **Disponibilités** (EF-PRE-07) : `MessagingAvailability` (une par prêtre) : accepte ou non de nouveaux échanges, absent jusqu'au, plages de réponse indicatives. `GET/PUT /messaging/availability/` sous `messagerie.recevoir_fideles`. Remplace `PriestProfile` (conservé en base jusqu'en L9 ; ses routes sont retirées, ADR-013).
- **Ouverture** (EF-PRE-02, RG-13) : seulement vers un prêtre joignable ; le fidèle doit être majeur (date de naissance du profil ; absente ou < 18 ans → 403 avec un message explicatif).
- **CGU** (EF-PRE-04, correctif A1) : acceptation globale par utilisateur (déjà en place).
- **Bandeau** (EF-PRE-05) : `confession_notice` renvoyé dans chaque conversation.
- **Aucun accès au contenu** (EF-PRE-06, RG-09) : l'admin Django n'affiche plus le contenu (ni les pièces) des messages ; un test parcourt les vues d'administration et vérifie qu'aucune ne renvoie un contenu.
- **Messagerie inter-clergé** : gelée en V1 (SRS §1.3) via le sous-module `messaging.inter_clerge`.
- WebSocket : tickets à usage unique (L3), origines explicites (`WS_ALLOWED_ORIGINS`), socket global `/ws/notifications/`.

## 2. Rendez-vous de confession (`apps/confessions`, nouvelle app)

| Modèle | Rôle |
|---|---|
| `ConfessionSlotRule` | Règle récurrente d'un prêtre sur un lieu : jour, heure de début et de fin, durée d'un créneau (10 min par défaut), période de validité |
| `ConfessionSlot` | Créneau généré sur 4 semaines glissantes (tâche quotidienne, idempotente) : `libre`, `reserve`, `bloque` |
| `ConfessionBooking` | Réservation : `reservee`, `annulee_fidele`, `annulee_pretre`, `honoree`, `absent`. **Aucun champ de contenu** (RG-08) : ni motif, ni texte libre |

- Réservation sous verrou du créneau, **409** s'il est pris ; une réservation active par créneau (contrainte partielle).
- Annulation par le fidèle jusqu'à H-1 ; par le prêtre avec un message aux réservants (le créneau passe `bloque`).
- Rappels à J-1 et H-2 (tâche toutes les 15 min, une seule fois chacun).
- Après le créneau, le prêtre marque `honoree` ou `absent`.
- Planning : le prêtre voit ses réservations nominatives ; le secrétariat (`confessions.voir_planning`) ne voit que des initiales.

Autorisation : `confessions.gerer` sur le nœud du lieu pour créer une règle (et seulement pour soi) ; `confessions.voir_planning` pour le planning du nœud.

## 3. API

Messagerie : `GET /messaging/priests/` · `GET/PUT /messaging/availability/` · conversations et messages inchangés (+ `confession_notice`).
Confessions : `GET /confessions/slots/?node=&from=` · `POST /confessions/bookings/` · `POST /confessions/bookings/{id}/cancel/` · `GET /me/confession-bookings/` · `GET/POST /staff/confessions/rules/` · `DELETE /staff/confessions/rules/{id}/` · `GET /staff/confessions/planning/?node=&from=` · `POST /staff/confessions/slots/{id}/cancel/` · `POST /staff/confessions/bookings/{id}/attendance/`.
