# Registre des traitements — Jàngu Bi

> Document de travail pour la déclaration à la Commission de protection des données personnelles (CDP, Sénégal), loi n° 2008-12 du 25 janvier 2008 (EF-CONF-04, ADR-011). Établi à partir du code (lots L0 à L9, 25/09/2026).
> **Les mentions `[À COMPLÉTER]` relèvent du responsable du traitement.** Le dépôt auprès de la CDP est fait par Numerisen, pas par l'équipe technique.

## 0. Identification

| Rubrique | Valeur |
|---|---|
| Responsable du traitement | Numerisen `[À COMPLÉTER : forme juridique, NINEA, adresse, représentant]` |
| Co-responsables ou sous-traitance | Les paroisses et diocèses traitent les demandes d'actes et la messagerie par leurs titulaires d'office : `[À COMPLÉTER : convention avec l'Archidiocèse de Dakar et la paroisse pilote]` |
| Délégué ou contact « données » | `[À COMPLÉTER]` |
| Hébergement | VPS `[À COMPLÉTER : hébergeur, pays]`. Hors du Sénégal : transfert à déclarer (art. 49) ; réévaluation prévue avant l'ouverture publique (ENF-11) |
| Sous-traitants techniques | Keycloak (auto-hébergé), envoi d'e-mails `[À COMPLÉTER : prestataire SMTP, pays]`, Sentry `[À COMPLÉTER : instance, pays ; vérifier qu'aucune donnée religieuse n'y part]`, stockage objet MinIO (auto-hébergé) |

## 1. Données sensibles

L'appartenance religieuse, l'état de vie (laïc, clerc, religieux), les demandes d'actes de sacrements, les échanges avec un prêtre et les rendez-vous de confession sont des **données sensibles** (art. 4.8). Base légale : **consentement explicite** de la personne (art. 40), horodaté et lié à la version des conditions (`POST /me/consent/`, réglage `CONSENT_CURRENT_VERSION`). Aucune donnée n'est cédée ni transmise à des tiers à des fins commerciales.

## 2. Traitements

| # | Traitement | Finalité | Personnes | Données | Destinataires | Conservation |
|---|---|---|---|---|---|---|
| T1 | Comptes et authentification | Accès sécurisé, MFA du staff | Toute personne inscrite | e-mail, téléphone (facultatif), identifiant Keycloak, dates d'activité (au jour près), dernière connexion MFA | Numerisen (exploitation) | Durée du compte ; à la suppression : anonymisation immédiate, compte Keycloak supprimé |
| T2 | Profil ecclésial | Adapter les services (majorité pour la messagerie, droits des titulaires d'office) | Inscrits | nom, prénom, date de naissance, état de vie, degré d'ordre, paroisse suivie, statut de vérification | Personne concernée ; chancellerie (`personnes.verifier`) pour la vérification des clercs | Durée du compte |
| T3 | Nominations et capacités | Autoriser les responsables selon leur office | Titulaires d'office | office, nœud, dates, autorité de nomination | Autorité de nomination, plateforme | Durée de l'office + historique d'audit `[À COMPLÉTER : durée]` |
| T4 | Annonces, événements, méditations | Informer les fidèles de leur paroisse | Inscrits | lectures d'annonces, inscriptions aux événements | Organisateurs (liste des inscrits d'un événement) | Lectures : durée du compte ; inscriptions : `[À COMPLÉTER]` |
| T5 | Demandes d'actes | Transmettre une demande à la paroisse du sacrement ; l'acte n'est jamais délivré en numérique | Demandeur | identité au moment du sacrement, parents, date et lieu, contacts, pièce jointe facultative, références du registre (paroisse seulement) | Paroisse du sacrement (`actes.traiter`) ; supervision en agrégats | Pièces : 90 jours après clôture (purge automatique) ; demande : `[À COMPLÉTER]` ; à la suppression du compte : anonymisée, référence et statut conservés |
| T6 | Parler à un prêtre | Écoute et accompagnement (jamais la confession) | Fidèles majeurs, prêtres joignables | contenu des messages (chiffré au repos), pièces jointes, horodatages | Les deux participants seulement ; **aucun administrateur** (RG-09) | 180 jours (`MESSAGING_PURGE_DAYS`) ; purge immédiate à la suppression du compte |
| T7 | Rendez-vous de confession | Réserver un créneau en présentiel | Fidèles, prêtres | créneau, lieu, statut ; **aucun contenu** | Le prêtre du créneau (nom) ; le secrétariat (initiales seulement) | `[À COMPLÉTER]` ; réservations à venir annulées à la suppression du compte |
| T8 | Notifications | Prévenir (annonces, rappels, suivi des demandes) | Inscrits | préférences, notifications, e-mails envoyés | Personne concernée ; prestataire e-mail | Notifications : `[À COMPLÉTER]` ; supprimées avec le compte |
| T9 | Tableaux de bord | Pilotage pastoral | — | agrégats uniquement, aucun nom, aucun contenu de message | Titulaires de `tableau_bord.voir`, plateforme | Calculés à la demande (cache 5 min) |
| T10 | Journal d'audit | Traçabilité des actions sensibles | Responsables, personnes concernées | acteur, action, cible, nœud, date, adresse IP tronquée (IPv4 /24, IPv6 /48 : réseau, jamais la machine) | Plateforme, `audit.voir` | `[À COMPLÉTER]` (journal immuable) |
| T11 | Formulaire « Pour les paroisses » | Contact commercial et pastoral | Représentants de paroisses | nom, fonction, paroisse, diocèse, téléphone, e-mail, message | Numerisen | `[À COMPLÉTER]` |

## 3. Droits des personnes

| Droit | Mise en œuvre |
|---|---|
| Information | Politique de confidentialité `[À RÉDIGER, version = CONSENT_CURRENT_VERSION]` ; bandeau dans la messagerie (pas de confession par message) |
| Accès et portabilité | `GET /me/export/` (JSON : compte, profil, préférences, demandes, rendez-vous, inscriptions, messages écrits par la personne) |
| Rectification | `PATCH /me/` |
| Suppression | `DELETE /me/` : anonymisation de l'identité, purge des conversations, annulation des demandes et rendez-vous en cours, conservation des traces légales anonymisées ; refusée tant qu'une nomination est active |
| Retrait du consentement | Suppression du compte `[À COMPLÉTER : procédure de retrait sans suppression si souhaitée]` |

## 4. Mesures de sécurité

Authentification Keycloak (OIDC, PKCE), MFA exigée pour tout titulaire d'office ; autorisation par capacités sur l'arbre des juridictions ; messages chiffrés au repos (Fernet, clé distincte de `SECRET_KEY` en production) ; aucune vue d'administration n'affiche le contenu des messages (test automatisé) ; tableaux de bord agrégés ; journal d'audit ; HTTPS et HSTS ; limitation de débit ; sauvegardes `[À COMPLÉTER : fréquence, chiffrement, lieu, test de restauration]`. Chiffrement de bout en bout : étudié (ADR-014), reporté après le pilote par défaut, avec une mention de transparence dans la politique.
