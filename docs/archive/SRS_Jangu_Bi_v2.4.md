# SRS — Jàngu Bi Platform v2.4

**Software Requirements Specification**
Plateforme web pastorale pour l'Archidiocèse de Dakar et diocèses suffragants

| Propriété | Valeur |
|---|---|
| Version du document | 2.4 |
| Statut | Draft pour validation |
| Auteur | Équipe Produit & Architecture |
| Date | Avril 2026 |
| Remplace | SRS v2.2 (obsolète — modèle de données corrigé) |

---

## 📋 Table des matières

1. [Introduction](#1-introduction)
2. [Vision produit et parties prenantes](#2-vision-produit-et-parties-prenantes)
3. [Glossaire ecclésiastique](#3-glossaire-ecclésiastique)
4. [Architecture globale](#4-architecture-globale)
5. [Modèle de données](#5-modèle-de-données)
6. [Matrice RBAC](#6-matrice-rbac)
7. [Exigences fonctionnelles](#7-exigences-fonctionnelles)
8. [Règles métier critiques](#8-règles-métier-critiques)
9. [Exigences non fonctionnelles](#9-exigences-non-fonctionnelles)
10. [Parcours utilisateurs clés](#10-parcours-utilisateurs-clés)
11. [Stratégie de release](#11-stratégie-de-release)
12. [Annexes](#12-annexes)

---

## 1. Introduction

### 1.1 Objectif du document

Ce document constitue la **spécification unique et officielle** de la plateforme web Jàngu Bi v2.4. Il remplace intégralement la version 2.2 qui comportait des erreurs de modélisation critiques (hiérarchie ecclésiastique mal posée, RBAC incohérent, mélange inapproprié vente de livres / dons, absence de soft-delete, etc.).

Ce SRS sert de :
- Contrat fonctionnel entre le Product Owner et l'équipe de développement
- Référence technique pour la modélisation de la base PostgreSQL
- Base de validation pour les tests fonctionnels et de recette

### 1.2 Périmètre

La plateforme Jàngu Bi v2.4 est un **système 100% web** couvrant :

- Un **Espace Administration** (hiérarchique : Province → Diocèse → Paroisse → Église)
- Un **Espace Membre** destiné aux fidèles (profil, actualités, dons)
- Un **moteur de dons en ligne** connecté à PayDunya
- Un système de **notifications temps réel** (WebSockets)
- Un système de **gestion de contenu éditorial** (actualités, horaires de messe)

**Hors scope v2.4** :
- Application mobile native (prévue ultérieurement)
- Vente de livres / contenus numériques (supprimée définitivement de ce périmètre)
- Reçus fiscaux (non applicables au cadre sénégalais actuel)
- Multi-devise (FCFA uniquement)

### 1.3 Conventions

- **REQ-XXX-NN** : identifiant d'une exigence fonctionnelle
- **NFR-XXX-NN** : identifiant d'une exigence non fonctionnelle
- **RG-XXX-NN** : identifiant d'une règle de gestion métier
- **MUST / SHOULD / MAY** : niveaux d'obligation (RFC 2119)

### 1.4 Historique des versions

| Version | Date | Modifications |
|---|---|---|
| 2.0 | — | Version initiale Firebase |
| 2.1 | — | Migration Firestore → PostgreSQL (partielle) |
| 2.2 | — | Refonte Web avec Django, erreurs de modélisation |
| 2.3 | Avril 2026 | Réécriture complète, modèle corrigé, hiérarchie canonique respectée |
| 2.3.1 | Avril 2026 | Phasage délégation admins V1/V2/V3 + module CHAT pastoral (V2) avec cadrage théologique |
| **2.4** | **Avril 2026** | **Modules Bible/Liturgie/Chapelet/TV/RAG marqués implémentés. Alignement technique complet avec le code source.** |

---

## 2. Vision produit et parties prenantes

### 2.1 Vision

> Doter l'Église catholique du Sénégal d'une plateforme web unifiée permettant :
> (1) aux fidèles de rester connectés à leur paroisse et de contribuer financièrement avec simplicité et transparence,
> (2) aux responsables ecclésiastiques de gérer efficacement leur territoire pastoral (contenus, finances, communication).

### 2.2 Parties prenantes

| Partie prenante | Rôle dans le projet |
|---|---|
| Archidiocèse de Dakar | Sponsor principal, validation périmètre |
| Diocèses suffragants (6) | Utilisateurs admins, adoption progressive |
| Paroisses | Utilisateurs opérationnels (contenu + finances) |
| Fidèles | Utilisateurs finaux (Espace Membre) |
| PayDunya | Prestataire paiement |
| Équipe dev | Réalisation technique |

### 2.3 Objectifs mesurables (KPI)

| KPI | Cible à 12 mois |
|---|---|
| Nombre de paroisses actives sur la plateforme | ≥ 30 |
| Nombre de fidèles inscrits | ≥ 5 000 |
| Volume de dons traités par mois | ≥ 10 M FCFA |
| Taux d'uptime | ≥ 99,5 % |
| Délai moyen de traitement d'un paiement | < 30 secondes |

---

## 3. Glossaire ecclésiastique

**Essentiel pour aligner l'équipe technique sur la réalité canonique catholique.**

| Terme | Définition |
|---|---|
| **Province ecclésiastique** | Regroupement de diocèses voisins placés sous la coordination d'un archevêque métropolitain. Au Sénégal : une seule province (Dakar) regroupant 7 diocèses. |
| **Archidiocèse** | Diocèse principal d'une province, dirigé par un **archevêque métropolitain**. L'archidiocèse est **lui-même un diocèse** (l'archevêque en est l'évêque diocésain) ; son rôle métropolitain sur les autres diocèses est honorifique et coordinateur, pas juridictionnel. |
| **Diocèse suffragant** | Diocèse "simple" de la province, dirigé par un **évêque pleinement souverain** sur son territoire. Au Sénégal : Thiès, Kaolack, Saint-Louis, Ziguinchor, Tambacounda, Kolda. |
| **Paroisse** | Subdivision territoriale d'un diocèse, dirigée par un **curé** (prêtre responsable). Une paroisse est la communauté de fidèles vivant sur un territoire défini. |
| **Église** | **Bâtiment de culte** appartenant à une paroisse. Une paroisse peut avoir une ou plusieurs églises (église principale + annexes ou églises équivalentes en milieu rural). |
| **Curé** | Prêtre responsable d'une paroisse, nommé par l'évêque. |
| **Fidèle** | Personne baptisée de l'Église catholique, rattachée canoniquement à une paroisse (sa "paroisse d'origine" ou "paroisse de rattachement"). |
| **Denier du culte** | Contribution annuelle des fidèles au fonctionnement de leur paroisse. |
| **Quête** | Collecte effectuée durant la messe. |
| **Messe** | Célébration liturgique principale, objet des horaires publiés. |

---

## 4. Architecture globale

### 4.1 Stack technique retenue

| Couche | Technologie | Justification |
|---|---|---|
| Frontend | Next.js 14+ (App Router, TypeScript) | SSR, SEO, excellente DX |
| Backend | Django 5.x + Django REST Framework | Maturité, ORM puissant, admin natif |
| Authentification | djangorestframework-simplejwt (JWT) | Standard du marché, stateless |
| Base de données | PostgreSQL 16 | Fiabilité, ArrayField, JSONField natifs |
| Cache / Queues | Redis 7 | Sessions WebSocket, Celery broker |
| WebSockets | Django Channels + Daphne | Notifications temps réel |
| Tâches async | Celery | Emails, webhooks, PDF |
| Paiement | PayDunya (sandbox + prod) | Adaptée au marché sénégalais |
| Containerisation | Docker + docker-compose | Portabilité, staging |
| Déploiement | DigitalOcean / Sonatel Cloud | Staging + prod |

### 4.2 Architecture logique

```
┌─────────────────────────────────────────────────┐
│  Espace Admin Web        Espace Membre Web      │
│  (Next.js)               (Next.js)              │
└──────────────┬──────────────────┬───────────────┘
               │                  │
               │ HTTPS / JWT      │
               ▼                  ▼
┌─────────────────────────────────────────────────┐
│            API REST Django (DRF)                │
│  ┌─────────┬──────────┬─────────┬────────────┐ │
│  │  Auth   │ Organisa-│ Finances│  Contenu   │ │
│  │  RBAC   │   tion   │  Dons   │  Pastoral  │ │
│  └─────────┴──────────┴─────────┴────────────┘ │
└──────┬──────────────┬──────────────┬────────────┘
       │              │              │
       ▼              ▼              ▼
  ┌─────────┐   ┌──────────┐   ┌──────────┐
  │PostgreSQL│   │  Redis   │   │PayDunya  │
  │          │   │+Channels │   │  API     │
  └──────────┘   └──────────┘   └──────────┘
```

### 4.3 Principes architecturaux

- **API-first** : toutes les fonctionnalités sont exposées via l'API REST, le frontend est un simple consommateur.
- **HackSoftware Django Styleguide** : séparation stricte Models / Services / Selectors / APIs.
- **RBAC natif Django** : utilisation des `Group` et `Permission` de Django, pas de réinvention.
- **Soft delete** : Prévu en V2 pour les données sensibles. Le code actuel utilise `is_active` pour les comptes.
- **Audit trail** : Journalisation de sécurité (`SecurityAuditLog`) implémentée.
- **Idempotence** : Appliquée aux messages et aux futures opérations financières.

---

## 5. Modèle de données

### 5.1 Principes de modélisation

Le modèle suit les principes suivants :

- **Respect de la hiérarchie canonique réelle** (Province → Diocèse → Paroisse → Église)
- **Normalisation 3NF** sans redondance
- **Soft delete universel** via champ `deleted_at` (héritage d'une classe abstraite `BaseModel`)
- **Audit dates** (`created_at`, `updated_at`) sur toutes les entités
- **Clés étrangères explicites** avec `on_delete` raisonné (jamais `CASCADE` sur données financières)
- **Contraintes d'unicité au niveau BDD** (pas seulement applicatif)

### 5.2 Classe abstraite BaseModel

Toutes les entités métier héritent de :

```python
class BaseModel(models.Model):
    created_at = DateTimeField(auto_now_add=True, db_index=True)
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        abstract = True
```

> ⚠️ **Note** : Le soft-delete via `deleted_at` est reporté en V2 pour simplifier la logique initiale. Les identifiants utilisent le type par défaut (BigAuto) sauf mention contraire.

### 5.3 Modules Organisation & Finances — [EN ATTENTE V2/V3]

**Note technique** : Ces modules ne sont pas présents dans la base de code actuelle. Les spécifications ci-dessous sont maintenues à titre de référence pour le développement futur. Le profil utilisateur utilise actuellement un `IntegerField` (`primary_parish`) comme placeholder.

#### 5.3.1 EcclesiasticalProvince (Futur)

Représente une province ecclésiastique. Au lancement : une seule entrée (Dakar), mais le modèle supporte plusieurs provinces pour une éventuelle extension régionale.

| Champ | Type | Contraintes | Description |
|---|---|---|---|
| `id` | UUID | PK | Identifiant unique |
| `code` | CharField(20) | UNIQUE, NOT NULL | Code court (ex: "DAKAR") |
| `name` | CharField(150) | NOT NULL | Nom complet |
| `country` | CharField(2) | Default "SN" | Code ISO pays |
| `created_at` | DateTimeField | auto | Hérité BaseModel |
| `updated_at` | DateTimeField | auto | Hérité BaseModel |

**Seed initial** : 1 entrée `{code: "DAKAR", name: "Province ecclésiastique de Dakar"}`.

#### 5.3.2 Diocese

Représente un diocèse. L'archidiocèse est un diocèse avec le flag `is_metropolitan=True`.

| Champ | Type | Contraintes | Description |
|---|---|---|---|
| `id` | UUID | PK | |
| `province` | FK(EcclesiasticalProvince) | NOT NULL, PROTECT | Province de rattachement |
| `code` | CharField(20) | UNIQUE, NOT NULL | Ex: "DAKAR-DIOCESE", "THIES" |
| `name` | CharField(150) | NOT NULL | Nom officiel |
| `is_metropolitan` | BooleanField | Default False | True uniquement pour l'archidiocèse de sa province |
| `bishop_name` | CharField(150) | Nullable | Nom de l'évêque / archevêque en exercice |
| `seat_city` | CharField(100) | NOT NULL | Ville du siège épiscopal |
| `created_at` / `updated_at` | — | — | Hérité |

**Contraintes métier** :
- RG-ORG-01 : Au sein d'une même province, il ne peut exister **qu'un seul** `Diocese` avec `is_metropolitan=True` (contrainte unique conditionnelle via PostgreSQL partial index).
- RG-ORG-02 : Le `code` d'un diocèse doit être unique globalement (pas seulement par province).

**Seed initial** :
- `DAKAR-ARCH` (is_metropolitan=True)
- `THIES`, `KAOLACK`, `SAINT-LOUIS`, `ZIGUINCHOR`, `TAMBACOUNDA`, `KOLDA` (is_metropolitan=False)

#### 5.3.3 Parish

Représente une paroisse, subdivision territoriale d'un diocèse.

| Champ | Type | Contraintes | Description |
|---|---|---|---|
| `id` | UUID | PK | |
| `diocese` | FK(Diocese) | NOT NULL, PROTECT | Diocèse de rattachement |
| `name` | CharField(150) | NOT NULL | Nom de la paroisse (ex: "Paroisse Saint-Pierre de Rufisque") |
| `slug` | SlugField | UNIQUE_TOGETHER avec diocese | Pour URLs publiques |
| `city` | CharField(100) | NOT NULL | Commune d'implantation |
| `address` | TextField | Nullable | Adresse postale |
| `priest_name` | CharField(150) | Nullable | Nom du curé en exercice |
| `contact_email` | EmailField | Nullable | Email de contact public |
| `contact_phone` | CharField(30) | Nullable | Téléphone de contact |
| `is_active` | BooleanField | Default True | Active / suspendue |
| `created_at` / `updated_at` | — | — | Hérité |

**Contrainte** : `UNIQUE (diocese_id, slug)` — deux paroisses de diocèses différents peuvent avoir le même slug.

#### 5.3.4 Church

Représente un bâtiment de culte (église physique) appartenant à une paroisse.

| Champ | Type | Contraintes | Description |
|---|---|---|---|
| `id` | UUID | PK | |
| `parish` | FK(Parish) | NOT NULL, PROTECT | Paroisse de rattachement |
| `name` | CharField(150) | NOT NULL | Nom de l'église |
| `is_main` | BooleanField | Default False | True = église principale de la paroisse |
| `address` | TextField | Nullable | |
| `latitude` / `longitude` | DecimalField | Nullable | Géolocalisation optionnelle |
| `photo_url` | URLField | Nullable | Photo de l'église |
| `created_at` / `updated_at` | — | — | Hérité |

**Contraintes métier** :
- RG-ORG-03 : Une paroisse DOIT avoir exactement une église avec `is_main=True` (contrainte partielle).
- RG-ORG-04 : La suppression (soft delete) d'une église principale est interdite tant qu'une autre église n'a pas été promue principale.

> ⚠️ **Correction vs SRS v2.2** : Dans la v2.2, `Church` avait une FK redondante vers `Diocese`. C'est supprimé : le diocèse d'une église est déduit par `church.parish.diocese`.

### 5.4 Entités utilisateur et sécurité

#### 5.4.1 BaseUser

Modèle d'authentification principal étendant `AbstractBaseUser` et `PermissionsMixin`.

| Champ | Type | Contraintes | Description |
|---|---|---|---|
| `id` | UUID | PK | |
| `email` | EmailField | UNIQUE, NOT NULL | Identifiant principal de connexion |
| `phone_number` | PhoneNumberField | UNIQUE, NOT NULL | Numéro de téléphone (format international) |
| `role` | CharField(20) | NOT NULL | Rôle principal (cf. UserRole enum) |
| `password` | CharField | NOT NULL | Hash (Django gère) |
| `is_verified` | BooleanField | Default False | Email/Compte vérifié |
| `is_active` | BooleanField | Default False | Compte activé par l'utilisateur |
| `is_staff` | BooleanField | Default False | Accès interface admin Django |
| `is_admin` | BooleanField | Default False | Flag administrateur métier |
| `jwt_key` | UUID | Default uuid4 | Rotation des tokens JWT |
| `last_login` | DateTimeField | Nullable | Django standard |
| `created_at` / `updated_at` | — | — | Hérité BaseModel |

#### 5.4.2 Profile

Informations personnelles liées à l'utilisateur via une relation `OneToOne`.

| Champ | Type | Contraintes | Description |
|---|---|---|---|
| `user` | OneToOne(BaseUser) | NOT NULL, CASCADE | Lien vers le compte auth |
| `first_name` | CharField(50) | Default "" | |
| `last_name` | CharField(50) | Default "" | |
| `title` | CharField(10) | Choices: MR, MRS | Civilité |
| `date_of_birth` | DateField | Nullable | |
| `phone` | PhoneNumberField | Nullable | Téléphone de contact additionnel |
| `avatar` | ImageField | Nullable | Photo de profil |
| `primary_parish` | IntegerField | Nullable | Placeholder (ID temporaire) |
| `created_at` / `updated_at` | — | — | Hérité BaseModel |


**Contraintes** :
- RG-USER-01 : L'email est **obligatoirement vérifié** avant que l'utilisateur puisse faire un don connecté ou exercer un rôle admin.
- RG-USER-02 : `primary_parish` peut être `NULL` pour un admin de province/diocèse qui ne souhaite pas se rattacher à une paroisse précise.

#### 5.4.3 Rôles et permissions (Django natif)

Le SRS v2.3 **abandonne l'enum de rôles** utilisée en v2.2 au profit des **Django Groups natifs**. Cela apporte :
- Scalabilité (création de nouveaux rôles sans migration de code)
- Intégration native avec l'admin Django
- Permissions granulaires par action

**Groupes seed initiaux** :

| Groupe Django | Scope | Description |
|---|---|---|
| `super_admin` | Global | Accès total, gestion plateforme |
| `province_admin` | Province | Admin d'une province ecclésiastique |
| `diocese_admin` | Diocèse | Admin d'un diocèse |
| `parish_admin` | Paroisse | Admin d'une paroisse (équivalent curé ou délégué) |
| `church_admin` | Église | Admin d'une église (sacristain, responsable local) |
| `fidele` | Self | Fidèle inscrit (accordé automatiquement à tout compte) |

**Règle fondamentale** : Tout utilisateur appartient **automatiquement** au groupe `fidele` dès l'inscription. Il peut en plus appartenir à **au plus un** groupe admin (hors `super_admin` et `fidele`).

#### 5.4.4 RoleAssignment (Futur / En attente module ORG)

Permet de rattacher un utilisateur à un rôle ET à une entité organisationnelle (indispensable pour le RBAC scopé).

| Champ | Type | Contraintes | Description |
|---|---|---|---|
| `id` | UUID | PK | |
| `user` | FK(UserProfile) | NOT NULL, CASCADE | |
| `group` | FK(auth.Group) | NOT NULL, PROTECT | Rôle Django |
| `scope_type` | CharField | Choices: `province`, `diocese`, `parish`, `church`, `global` | Niveau de scope |
| `province` | FK(EcclesiasticalProvince) | Nullable | Remplie si scope=province |
| `diocese` | FK(Diocese) | Nullable | Remplie si scope=diocese |
| `parish` | FK(Parish) | Nullable | Remplie si scope=parish |
| `church` | FK(Church) | Nullable | Remplie si scope=church |
| `assigned_by` | FK(UserProfile) | NOT NULL, PROTECT | Qui a attribué ce rôle |
| `assigned_at` | DateTimeField | auto | |
| `revoked_at` | DateTimeField | Nullable | Date de révocation |

**Contraintes métier** :
- RG-RBAC-01 : Exactement **un** des champs `province / diocese / parish / church` doit être rempli selon `scope_type` (sauf pour `global` qui les laisse tous NULL).
- RG-RBAC-02 : Un utilisateur peut avoir **plusieurs** `RoleAssignment` actifs (ex: Parish Admin de Paroisse A ET Church Admin d'une église d'une autre paroisse), mais jamais **deux rôles admin du même niveau** sur la même entité.
- RG-RBAC-03 : Seul un `super_admin` peut créer des `RoleAssignment` (toutes catégories confondues, en V1). La délégation (Diocese Admin crée Parish Admin, etc.) est prévue en V2.

### 5.5 Entités finances et dons

#### 5.5.1 DonationType

**Les 4 types de dons sont globaux et fixes**. Les montants par défaut sont paramétrables par paroisse (via `ParishDonationConfig`, voir plus bas).

| Champ | Type | Contraintes | Description |
|---|---|---|---|
| `id` | UUID | PK | |
| `slug` | CharField(20) | UNIQUE, NOT NULL | Parmi : `quete`, `denier`, `cierge`, `priere` |
| `name` | CharField(100) | NOT NULL | Ex: "Quête dominicale" |
| `description` | TextField | Nullable | |
| `icon` | CharField(50) | Nullable | Nom de l'icône frontend |
| `display_order` | IntegerField | Default 0 | Ordre d'affichage |
| `is_active` | BooleanField | Default True | |

**Seed initial** : 4 entrées immuables en V1 :
- `quete` — Quête dominicale
- `denier` — Denier du culte
- `cierge` — Cierge / intention
- `priere` — Intention de prière

> ⚠️ **Correction vs SRS v2.2** : En v2.2, `DonationType` avait une FK vers `Parish` et les slugs étaient uniques globalement — contradiction qui cassait dès la 2e paroisse. Corrigé ici : les types sont globaux, les configurations par paroisse sont dans une table dédiée.

#### 5.5.2 ParishDonationConfig

Configuration des montants par défaut d'un type de don, pour une paroisse donnée.

| Champ | Type | Contraintes | Description |
|---|---|---|---|
| `id` | UUID | PK | |
| `parish` | FK(Parish) | NOT NULL, CASCADE | |
| `donation_type` | FK(DonationType) | NOT NULL, PROTECT | |
| `default_amounts` | ArrayField(IntegerField, size=4) | NOT NULL | 4 montants suggérés en FCFA |
| `min_amount` | IntegerField | Default 500 | Don minimum accepté (FCFA) |
| `is_enabled` | BooleanField | Default True | La paroisse accepte ce type de don |
| `created_at` / `updated_at` | — | — | |

**Contrainte** : `UNIQUE (parish_id, donation_type_id)` — une seule config par couple.

#### 5.5.3 Payment (Futur)

**Source unique de vérité** pour tous les paiements. La vente de livres étant supprimée, le champ `payment_type` disparaît.

| Champ | Type | Contraintes | Description |
|---|---|---|---|
| `id` | UUID | PK | |
| `internal_reference` | CharField(32) | UNIQUE, NOT NULL | Référence interne (ex: "PAY-2026-00001") |
| `donation_type` | FK(DonationType) | NOT NULL, PROTECT | |
| `parish` | FK(Parish) | NOT NULL, PROTECT | Paroisse bénéficiaire |
| `church` | FK(Church) | Nullable, PROTECT | Église spécifique (pour cierges, etc.) |
| `donor` | FK(UserProfile) | Nullable, SET_NULL | NULL si don anonyme |
| `anonymous_donor_name` | CharField(150) | Nullable | Rempli si don anonyme sans compte |
| `anonymous_donor_email` | EmailField | Nullable | Optionnel, pour envoi reçu |
| `anonymous_donor_phone` | CharField(30) | Nullable | Optionnel |
| `amount` | IntegerField | NOT NULL, CHECK > 0 | Montant en FCFA |
| `currency` | CharField(3) | Default "XOF" | ISO 4217 |
| `status` | CharField | Choices: PENDING, COMPLETED, FAILED, CANCELED, REFUNDED | |
| `provider` | CharField(20) | Default "paydunya" | Extensible à d'autres prestataires |
| `provider_token` | CharField(128) | UNIQUE, NOT NULL | Token PayDunya (invoice_token) |
| `provider_payload` | JSONField | Nullable | Payload brut du webhook (traçabilité) |
| `intention_message` | TextField | Nullable | Message du donateur (prière, cierge) |
| `initiated_at` | DateTimeField | auto | Date d'initiation |
| `completed_at` | DateTimeField | Nullable | Date de confirmation COMPLETED |
| `created_at` / `updated_at` / `deleted_at` | — | — | Hérité |

**Contraintes métier critiques** :
- RG-PAY-01 (Don anonyme) : Si `donor IS NULL`, `anonymous_donor_*` peut être renseigné ; si `donor IS NOT NULL`, `anonymous_donor_*` DOIT être NULL.
- RG-PAY-02 (Seuil anonyme) : Si `donor IS NULL`, `amount` DOIT être ≤ **25 000 FCFA**. Au-delà, l'API rejette avec HTTP 403.
- RG-PAY-03 (Cohérence église) : Si `church IS NOT NULL`, alors `church.parish_id == parish_id` (vérifié en validation).
- RG-PAY-04 (Idempotence) : Le statut `COMPLETED` est **terminal**. Tout webhook tentant de repasser un paiement COMPLETED en un autre statut est ignoré (cf. REQ-FIN-03).
- RG-PAY-05 (Soft delete interdit) : Un `Payment` n'est **jamais** soft-deleted. L'intégrité financière l'exige. Une erreur est annulée via `status=CANCELED` ou `REFUNDED`.

> ⚠️ **Correction vs SRS v2.2** :
> - Suppression du champ `payment_type` (vente de livres hors scope)
> - `donor` devient nullable pour supporter les dons anonymes
> - Ajout de `parish` et `church` (manquait dans v2.2 : impossible de savoir quelle paroisse bénéficiait)
> - Ajout de `anonymous_donor_*` pour les dons sans compte
> - Ajout de `intention_message` pour les cierges / prières
> - `amount` : ajout CHECK > 0 (évite les montants négatifs)

#### 5.5.4 SecurityAuditLog

Journalisation des événements de sécurité.

| Champ | Type | Contraintes | Description |
|---|---|---|---|
| `user` | FK(BaseUser) | Nullable, SET_NULL | Auteur de l'action |
| `event` | CharField(50) | NOT NULL | Ex: LOGIN_SUCCESS, PASSWORD_CHANGED |
| `ip_address` | GenericIPAddressField | Nullable | IP source |
| `user_agent` | TextField | Nullable | User-Agent du client |
| `metadata` | JSONField | Default {} | Métadonnées contextuelles |
| `created_at` | DateTimeField | auto | |

**Règle** : un `AuditLog` n'est **jamais** ni modifié ni supprimé. Table append-only. À des fins de conformité, un job nocturne peut archiver les entrées > 2 ans vers un stockage froid.

### 5.6 Entités contenu éditorial

#### 5.6.1 News

Actualité publiée à un certain niveau hiérarchique.

| Champ | Type | Contraintes | Description |
|---|---|---|---|
| `id` | UUID | PK | |
| `title` | CharField(200) | NOT NULL | |
| `slug` | SlugField(220) | UNIQUE_TOGETHER avec scope_type+scope_id | |
| `content` | TextField | NOT NULL | Contenu riche (Markdown ou HTML sanitisé) |
| `cover_image_url` | URLField | Nullable | |
| `author` | FK(UserProfile) | NOT NULL, PROTECT | Créateur |
| `scope_type` | CharField | Choices: `province`, `diocese`, `parish`, `church` | Niveau de diffusion |
| `scope_province` | FK(EcclesiasticalProvince) | Nullable | Rempli si scope=province |
| `scope_diocese` | FK(Diocese) | Nullable | Rempli si scope=diocese |
| `scope_parish` | FK(Parish) | Nullable | Rempli si scope=parish |
| `scope_church` | FK(Church) | Nullable | Rempli si scope=church |
| `status` | CharField | Choices: `draft`, `published`, `unpublished` | |
| `published_at` | DateTimeField | Nullable | |
| `unpublished_at` | DateTimeField | Nullable | |
| `unpublished_by` | FK(UserProfile) | Nullable, PROTECT | |
| `unpublish_reason` | TextField | Nullable | Motif de dépublication |
| `created_at` / `updated_at` / `deleted_at` | — | — | Hérité |

**Contrainte** : Exactement UN des `scope_*` champs est rempli selon `scope_type`.

> ⚠️ **Correction vs SRS v2.2** : Le champ `validated_by_parish` et le workflow `pending` → `published` sont supprimés. Cf. RG-CONT-01 pour le workflow simplifié.

#### 5.6.2 MassTime (ex-PrayerTime corrigé)

Horaire de messe d'une église.

| Champ | Type | Contraintes | Description |
|---|---|---|---|
| `id` | UUID | PK | |
| `church` | FK(Church) | NOT NULL, CASCADE | |
| `name` | CharField(150) | NOT NULL | Ex: "Messe dominicale en français" |
| `time` | TimeField | NOT NULL | Heure locale (Africa/Dakar) |
| `day_of_week` | IntegerField | Choices 0-6 (0=Lundi) | Jour de la semaine |
| `language` | CharField(30) | Nullable | Ex: "Français", "Wolof", "Latin" |
| `celebrant` | CharField(150) | Nullable | Prêtre célébrant habituel |
| `is_recurring` | BooleanField | Default True | Messe hebdomadaire récurrente |
| `valid_from` | DateField | Nullable | Début de validité de l'horaire |
| `valid_until` | DateField | Nullable | Fin de validité (ex: horaire d'été) |
| `is_active` | BooleanField | Default True | |
| `created_at` / `updated_at` / `deleted_at` | — | — | Hérité |

> ⚠️ **Correction vs SRS v2.2** :
> - `days` (ArrayField de strings) remplacé par `day_of_week` (int) : permet des requêtes efficaces ("toutes les messes du dimanche").
> - Si une église a des messes plusieurs jours, on crée **plusieurs MassTime** (une par jour) — modélisation propre.
> - Ajout de `language`, `celebrant`, `valid_from/until` pour la réalité des paroisses.
> - Suppression de `validated_by_parish` (workflow simplifié).

#### 5.6.3 MassTimeException

Exceptions aux horaires réguliers (jour férié, messe supplémentaire, annulation).

| Champ | Type | Contraintes | Description |
|---|---|---|---|
| `id` | UUID | PK | |
| `church` | FK(Church) | NOT NULL, CASCADE | |
| `exception_type` | CharField | Choices: `added`, `canceled`, `moved` | |
| `date` | DateField | NOT NULL | Date concernée |
| `original_mass_time` | FK(MassTime) | Nullable | Si type=canceled ou moved |
| `new_time` | TimeField | Nullable | Si type=moved ou added |
| `reason` | CharField(200) | Nullable | Ex: "Fête de l'Assomption" |
| `created_at` / `updated_at` | — | — | |

### 5.7 Notifications

#### 5.7.1 Notification

Notification stockée pour un utilisateur (vue/non vue).

| Champ | Type | Contraintes | Description |
|---|---|---|---|
| `user` | FK(BaseUser) | NOT NULL, CASCADE | Destinataire |
| `event_type` | CharField(50) | NOT NULL | Ex: `payment_received`, `news_published` |
| `payload` | JSONField | Default {} | Données contextuelles (titre, message, lien, etc.) |
| `is_read` | BooleanField | Default False, db_index | |
| `read_at` | DateTimeField | Nullable | |
| `created_at` | DateTimeField | auto, db_index | |

### 5.8 Vue d'ensemble — Diagramme ER simplifié

```
EcclesiasticalProvince
       │ 1:N
       ▼
    Diocese ──────────────────────────┐
       │ 1:N                          │
       ▼                              │
    Parish ──────── ParishDonationConfig ── DonationType
       │ 1:N               N:1              (seed: 4)
       ▼
    Church
       │ 1:N
       ▼
    MassTime, MassTimeException

UserProfile ─── RoleAssignment ─── auth.Group
    │ N:1                           (seed: 6 groupes)
    │
    │ 1:N
    ▼
Payment (donor nullable, anon supportés)
    │ 1:N
    ▼
AuditLog (tous événements sensibles)

News (scope_type + scope_entity)
    ▲
    │ 1:N
UserProfile (author)
```

---

## 6. Matrice RBAC

Légende : ✅ autorisé | ❌ interdit | 👁 lecture seule | 🏠 scopé à son entité

| Action | Super Admin | Province Admin | Diocese Admin | Parish Admin | Church Admin | Fidèle |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Organisation** | | | | | | |
| Créer / éditer Province | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Créer / éditer Diocese | ✅ | 🏠 | ❌ | ❌ | ❌ | ❌ |
| Créer / éditer Parish | ✅ | 🏠 | 🏠 | ❌ | ❌ | ❌ |
| Créer / éditer Church | ✅ | 🏠 | 🏠 | 🏠 | ❌ | ❌ |
| Lister Paroisses (publiques) | ✅ | ✅ | ✅ | ✅ | ✅ | 👁 |
| **Utilisateurs** | | | | | | |
| Créer compte admin | ✅ | ❌ (V1) | ❌ (V1) | ❌ (V1) | ❌ | ❌ |
| S'inscrire en tant que Fidèle | — | — | — | — | — | ✅ (public) |
| Lister users de son scope | ✅ | 🏠 | 🏠 | 🏠 | 🏠 | ❌ |
| Modifier son profil | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Changer rôle d'un user | ✅ | ❌ (V1) | ❌ (V1) | ❌ | ❌ | ❌ |
| **Contenu** | | | | | | |
| Créer News | ✅ | 🏠 | 🏠 | 🏠 | 🏠 | ❌ |
| Publier News (direct) | ✅ | 🏠 | 🏠 | 🏠 | 🏠 | — |
| Dépublier News | ✅ | 🏠 | 🏠 | 🏠 | ❌ | ❌ |
| Créer MassTime | ✅ | ❌ | ❌ | 🏠 | 🏠 | ❌ |
| Éditer MassTime | ✅ | ❌ | ❌ | 🏠 | 🏠 | ❌ |
| **Dons** | | | | | | |
| Configurer ParishDonationConfig | ✅ | 🏠 | 🏠 | 🏠 | ❌ | ❌ |
| Initier un don | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Don anonyme (≤ 25k FCFA) | — | — | — | — | — | Public |
| Consulter historique dons paroisse | ✅ | 🏠 | 🏠 | 🏠 | 👁 🏠 | ❌ |
| Consulter SON historique de dons | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Audit et sécurité** | | | | | | |
| Consulter AuditLog complet | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Consulter AuditLog de son scope | — | 🏠 | 🏠 | 🏠 | ❌ | ❌ |

> 🏠 signifie : **uniquement pour les entités de son scope de rattachement**.
> Ex: un Parish Admin de la paroisse P ne peut gérer les churches, news, dons que de P.

---

## 7. Exigences fonctionnelles

Les exigences sont numérotées par module et doivent être tracées vers les tests de recette.

### 7.1 Module AUTH — Authentification et sécurité

> **État d'implémentation** : Mécanismes de sécurité implémentés (JWT, OTP, reset mot de passe, audit log, rate limiting, rotation JWT). Rôles en cours d'adaptation depuis un projet B2B antérieur. Les 6 rôles Jàngu Bi (`fidele`, `super_admin`, `province_admin`, `diocese_admin`, `parish_admin`, `church_admin`) remplacent les anciens rôles dans le sprint courant. Le modèle `RoleAssignment` avec scope ecclésiastique sera livré avec le module ORG.

| ID | Exigence | Priorité |
|---|---|---|
| REQ-AUTH-01 | Le système MUST gérer l'authentification via JWT (access token 15 min + refresh token 7 jours) sans dépendance Firebase | V1 |
| REQ-AUTH-02 | Un compte admin créé par un super_admin reçoit un mot de passe temporaire fort par email ; si aucune connexion n'intervient dans le délai configuré (`ADMIN_ACCOUNT_EXPIRY_DAYS`), le compte est supprimé automatiquement | V1 |
| REQ-AUTH-03 | Les permissions RBAC MUST être évaluées via `RoleAssignment` et le scope (province/diocese/parish/church) | V1 |
| REQ-AUTH-04 | L'email d'un utilisateur MUST être vérifié (lien cliquable envoyé à l'inscription, valide 24h) avant toute action sensible | V1 |
| REQ-AUTH-05 | Le système MUST verrouiller un compte après 5 échecs de connexion consécutifs (blocage 15 min) | V1 |
| REQ-AUTH-06 | Les mots de passe MUST respecter : min 10 caractères, maj + min + chiffre + spécial | V1 |
| REQ-AUTH-07 | Le système MUST fournir un workflow "mot de passe oublié" (token email usage unique, 1h) | V1 |
| REQ-AUTH-08 | Le système SHOULD supporter 2FA par email pour les comptes admin (code à 6 chiffres) | V2 |

### 7.2 Module ORG — Gestion de l'organisation ecclésiastique

| ID | Exigence | Priorité |
|---|---|---|
| REQ-ORG-01 | Le système MUST supporter une hiérarchie Province → Diocese → Parish → Church configurable via admin (pas de valeurs codées en dur) | V1 |
| REQ-ORG-02 | Un seed initial MUST créer : 1 Province (Dakar), 7 Diocèses (dont Dakar=metropolitan), ces entités sont modifiables mais pas supprimables via UI standard | V1 |
| REQ-ORG-03 | Un fidèle, à l'inscription, DOIT sélectionner sa `primary_parish` dans la liste des paroisses actives | V1 |
| REQ-ORG-04 | Une paroisse DOIT avoir au moins une Church avec `is_main=True` pour être marquée `is_active=True` | V1 |
| REQ-ORG-05 | La géolocalisation d'une église est optionnelle en V1, requise en V2 (pour la fonctionnalité "trouver une église près de moi") | V2 |

### 7.3 Module USER — Gestion des utilisateurs

> **État d'implémentation** : Code issu d'un projet B2B (champs SIRET/TVA/company, rôles PARTICULIER/ENTREPRISE) en cours de suppression. Les champs B2B sont retirés du modèle `Profile`. Les 6 rôles ecclésiastiques sont branchés via Django Groups. La logique de vérification email, changement de mot de passe et activation de compte est conservée intacte.

| ID | Exigence | Priorité |
|---|---|---|
| REQ-USER-01 | L'auto-inscription des fidèles MUST être publique (pas d'approbation nécessaire) | V1 |
| REQ-USER-02 | Tout utilisateur inscrit est automatiquement ajouté au groupe `fidele` | V1 |
| REQ-USER-03 | En V1, seul un Super Admin peut créer des comptes avec rôle admin (modèle centralisé, simplicité opérationnelle pour ~30 paroisses) | V1 |
| REQ-USER-04 | Un utilisateur peut cumuler : rôle `fidele` (par défaut) + au plus un rôle admin sur une entité précise | V1 |
| REQ-USER-05 | Un utilisateur peut mettre à jour son profil (nom, téléphone, primary_parish) à tout moment | V1 |
| REQ-USER-06 | Un utilisateur peut demander la suppression de son compte : celui-ci est soft-deleted, ses dons historiques sont conservés mais anonymisés (`donor` = NULL) | V1 |
| REQ-USER-07 | En V2, la création d'admins MUST suivre une délégation hiérarchique descendante stricte (un échelon vers l'échelon immédiatement inférieur) : Super Admin→Province, Province→Diocese de sa province, Diocese→Parish de son diocèse, Parish→Church de sa paroisse | V2 |
| REQ-USER-08 | En V2, toute création d'admin déléguée MUST être journalisée dans `AuditLog` avec `created_by`, `scope`, `target_role` et horodatage | V2 |
| REQ-USER-09 | En V2, la délégation MUST interdire le saut d'échelon : un Diocese Admin NE PEUT PAS créer directement un Church Admin (il doit passer par un Parish Admin) | V2 |
| REQ-USER-10 | En V3, un workflow self-service permettra à un admin de demander la création d'un sous-admin à son supérieur hiérarchique via l'interface (avec approbation explicite avant activation du compte) | V3 |

**Justification du phasage** : le modèle V1 centralisé reste viable tant que le nombre de paroisses actives reste limité (≤ 30). Au-delà, le Super Admin devient goulot d'étranglement (30 paroisses × 3 admins = 90 comptes à gérer, projection 100 paroisses = 300 comptes, ingérable par une seule personne). La V2 distribue la charge opérationnelle en respectant la hiérarchie ecclésiale réelle. La V3 ajoute un confort de délégation sans compromettre la sécurité (approbation toujours humaine).

### 7.4 Module FIN — Dons et trésorerie

| ID | Exigence | Priorité |
|---|---|---|
| REQ-FIN-01 | Chaque `Parish Admin` peut définir pour sa paroisse les 4 montants suggérés de chaque type de don, et activer/désactiver chaque type | V1 |
| REQ-FIN-02 | Le système MUST supporter les dons anonymes ≤ 25 000 FCFA sans création de compte (saisie nom/email optionnels) | V1 |
| REQ-FIN-03 | Au-delà de 25 000 FCFA, la connexion au compte est obligatoire | V1 |
| REQ-FIN-04 | L'initiation d'un don crée un `Payment` en statut `PENDING` puis redirige vers PayDunya | V1 |
| REQ-FIN-05 | Le webhook IPN PayDunya MUST être idempotent : un paiement déjà `COMPLETED` ignore tout nouveau webhook (cf. RG-PAY-04) | V1 |
| REQ-FIN-06 | La signature cryptographique du webhook PayDunya MUST être vérifiée avant toute modification en BDD | V1 |
| REQ-FIN-07 | Un don `COMPLETED` déclenche : (a) email de reçu simple au donateur, (b) notification temps réel au `Parish Admin`, (c) écriture `AuditLog` | V1 |
| REQ-FIN-08 | Aucun don ne doit **jamais** débloquer de contenu payant (la vente de livres est définitivement hors scope v2.3) | V1 |
| REQ-FIN-09 | Le `Parish Admin` peut consulter la liste de tous les dons reçus pour sa paroisse avec filtres (type, période, statut) | V1 |
| REQ-FIN-10 | Le fidèle peut consulter son propre historique de dons dans l'Espace Membre | V1 |
| REQ-FIN-11 | Un Parish Admin peut initier un remboursement manuel (statut `REFUNDED`) avec justification obligatoire | V2 |

### 7.5 Module CONT — Contenu éditorial

| ID | Exigence | Priorité |
|---|---|---|
| REQ-CONT-01 | Un utilisateur avec un rôle admin peut créer une `News` au scope de son rôle ou niveaux inférieurs (ex: Diocese Admin peut poster au scope diocese, parish, ou church de son diocèse) | V1 |
| REQ-CONT-02 | Une `News` passe directement du statut `draft` à `published` par action de l'auteur (workflow simplifié, pas de validation intermédiaire en V1) | V1 |
| REQ-CONT-03 | Un admin du scope supérieur ou égal peut dépublier une `News` inappropriée (modération a posteriori) avec motif obligatoire | V1 |
| REQ-CONT-04 | Le fil d'actualité de l'Espace Membre Fidèle affiche les `News` `published` dont le scope correspond à : sa province, son diocèse, sa paroisse, une église de sa paroisse | V1 |
| REQ-CONT-05 | Un `Parish Admin` ou `Church Admin` peut créer, éditer, désactiver des `MassTime` pour son église | V1 |
| REQ-CONT-06 | Un `Church Admin` peut enregistrer une `MassTimeException` (ex: messe déplacée le 15 août) | V1 |
| REQ-CONT-07 | Les horaires de messe d'une église MUST être consultables publiquement (sans connexion) | V1 |

### 7.6 Module RT — Notifications temps réel

| ID | Exigence | Priorité |
|---|---|---|
| REQ-RT-01 | Le backend MUST émettre un événement WebSocket `donation.completed` à la destination du Parish Admin concerné lors de la confirmation d'un don | V1 |
| REQ-RT-02 | Le backend MUST émettre un événement WebSocket `news.published` à tous les fidèles du scope concerné lors de la publication d'une News | V1 |
| REQ-RT-03 | Le frontend MUST maintenir une connexion WebSocket authentifiée (JWT) tant que l'utilisateur est sur la plateforme | V1 |
| REQ-RT-04 | Chaque notification émise MUST être également persistée dans la table `Notification` (pour consultation ultérieure si l'utilisateur est offline) | V1 |
| REQ-RT-05 | L'Espace Membre SHOULD afficher une pastille de comptage des notifications non lues | V1 |

### 7.7 Module AUDIT — Journalisation

| ID | Exigence | Priorité |
|---|---|---|
| REQ-AUDIT-01 | Toute création / modification / suppression d'une entité admin (User, RoleAssignment, Parish, DonationConfig) MUST produire une entrée `AuditLog` | V1 |
| REQ-AUDIT-02 | Tout événement de paiement (initiated, completed, failed, canceled) MUST produire une entrée `AuditLog` | V1 |
| REQ-AUDIT-03 | Tout événement d'authentification (login réussi, échec, logout, password change) SHOULD produire une entrée `AuditLog` | V1 |
| REQ-AUDIT-04 | Les entrées `AuditLog` sont immuables : aucune modification ni suppression ne doit être possible, y compris par le Super Admin | V1 |
| REQ-AUDIT-05 | Le Super Admin peut consulter / filtrer / exporter le journal d'audit complet | V1 |

### 7.8 Module CHAT — Messagerie pastorale (V2)

**Positionnement** : fonctionnalité **V2 exclusivement**. Le MVP (V1) ne contient aucun module de messagerie. La V2 sera déclenchée après validation de l'usage réel du MVP (donations + contenu) et identification concrète des besoins pastoraux exprimés par les utilisateurs.

**⚠️ Cadrage théologique et juridique — lecture obligatoire**

La messagerie pastorale **N'EST PAS** un canal de confession sacramentelle. Le sacrement de réconciliation requiert la présence physique selon le droit canon catholique (rappel magistériel du Pape François, mars 2020) ; aucune absolution valide ne peut être donnée via un chat numérique. Ce cadrage doit être :
- **Affiché en permanence** dans chaque conversation (bandeau non-dismissable)
- **Accepté explicitement** par fidèle et prêtre lors de l'activation du module (CGU spécifique)
- **Rappelé par les prêtres** formés à rediriger toute demande de confession vers un rendez-vous physique

**Cas d'usage autorisés** :
- Demande de rendez-vous (confession, direction spirituelle, entretien pastoral)
- Questions de foi, de catéchèse, d'organisation paroissiale
- Demandes de prières, d'intentions de messe
- Signalement de besoins pastoraux (visite aux malades, extrême-onction à organiser)
- Échanges administratifs (baptême, mariage, obsèques, confirmation)
- Suivi post-sacramentel (par le prêtre, ex : relance catéchumène, message au nouveau couple marié)

**Cas d'usage interdits par conception** :
- Confession sacramentelle elle-même (contenu = aveu de péché attendant absolution)
- Direction spirituelle longue sans cadre de rendez-vous physique
- Échanges de nature privée ou intime sortant du cadre pastoral

| ID | Exigence | Priorité |
|---|---|---|
| REQ-CHAT-01 | Le module MUST permettre à un fidèle d'initier une conversation avec un prêtre autorisé (priest ayant un `RoleAssignment` `parish_admin` ou `church_admin` et flag `is_priest=True` sur son profil) | V2 |
| REQ-CHAT-02 | Le module MUST permettre à un prêtre d'initier une conversation avec un fidèle de son scope (sa paroisse principale ou une paroisse de sa juridiction) | V2 |
| REQ-CHAT-03 | Une conversation bilatérale (1-to-1) MUST être représentée par une entité `Conversation(participant_a, participant_b, created_at, last_message_at, is_archived)` avec contrainte unicité sur paire (A, B) ordonnée | V2 |
| REQ-CHAT-04 | Chaque message MUST être stocké dans une entité `Message(conversation, sender, content_encrypted, sent_at, read_at)` avec le contenu **chiffré au repos** via `django-cryptography` (clé serveur, non accessible aux admins techniques par défaut) | V2 |
| REQ-CHAT-05 | L'accès en lecture d'une conversation MUST être strictement limité aux deux participants. Aucun admin (y compris Super Admin) ne peut lire le contenu des messages en usage normal | V2 |
| REQ-CHAT-06 | Un bandeau non-dismissable MUST être affiché en permanence dans chaque conversation : **"⚠️ Ce chat ne remplace pas le sacrement de réconciliation. Pour vous confesser, prenez rendez-vous ou rendez-vous à l'église. Les prêtres ne peuvent pas donner l'absolution à distance."** | V2 |
| REQ-CHAT-07 | L'activation du module pour un utilisateur (fidèle ou prêtre) MUST exiger l'acceptation explicite d'une CGU spécifique rappelant les cas d'usage autorisés et interdits | V2 |
| REQ-CHAT-08 | Les messages MUST être automatiquement purgés (contenu supprimé, métadonnées conservées) **180 jours après le dernier message** d'une conversation | V2 |
| REQ-CHAT-09 | Un utilisateur MUST pouvoir exporter ses conversations (format JSON + PDF lisible) avant purge, au titre du droit à la portabilité (loi 2008-12, art. 43) | V2 |
| REQ-CHAT-10 | Un utilisateur MUST pouvoir supprimer une conversation à tout moment (suppression immédiate du contenu, conservation des métadonnées anonymisées pour audit) | V2 |
| REQ-CHAT-11 | Le déchiffrement exceptionnel par l'équipe technique MUST suivre une procédure documentée : réquisition judiciaire OU demande explicite d'un des deux participants, double validation Super Admin + DPO, entrée `AuditLog` obligatoire avec motif | V2 |
| REQ-CHAT-12 | Les messages MUST être transmis via WebSocket (Django Channels) avec émission d'un événement `message.received` pour l'accusé de réception temps réel | V2 |
| REQ-CHAT-13 | Un utilisateur (fidèle ou prêtre) MUST pouvoir bloquer un autre utilisateur (empêche toute nouvelle conversation) | V2 |
| REQ-CHAT-14 | Un prêtre MUST pouvoir marquer une conversation comme **"à transférer"** pour rediriger vers un confrère en cas d'indisponibilité ou de sujet hors compétence | V2 |
| REQ-CHAT-15 | Le système MUST limiter le volume : max 50 messages par conversation par jour par utilisateur (anti-spam, anti-abus) | V2 |
| REQ-CHAT-16 | Les notifications push (email ou notification web) de nouveau message NE DOIVENT PAS afficher le contenu du message (seulement "Nouveau message de [Prénom]") pour éviter les fuites sur écran de verrouillage | V2 |

**Modèle de données Chat** :

```python
class PriestProfile(BaseModel):
    user = OneToOne(User)
    accepts_pastoral_chat = BooleanField()
    cgu_accepted_at = DateTimeField()
    ordination_year = IntegerField()
    bio = TextField()

class Conversation(BaseModel):
    participant_a = FK(User)
    participant_b = FK(User)
    last_message_at = DateTimeField()
    is_archived = BooleanField()
    cgu_accepted_by_a = DateTimeField()
    cgu_accepted_by_b = DateTimeField()
    scheduled_purge_at = DateTimeField()

class Message(BaseModel):
    conversation = FK(Conversation)
    sender = FK(User)
    content = EncryptedTextField()
    content_type = CharField() # text, media, system
    client_message_id = UUIDField() # idempotency
    reply_to = FK("self")
    read_at = DateTimeField()

class MessageBlock(BaseModel):
    blocker = FK(User)
    blocked = FK(User)

class MessageAttachment(BaseModel):
    message = FK(Message)
    file = FK("files.File")

class MessageReaction(BaseModel):
    message = FK(Message)
    user = FK(User)
    emoji = CharField()

class Notification(BaseModel):
    user = FK(User)
    event_type = CharField()
    payload = JSONField()
    is_read = BooleanField()
    read_at = DateTimeField()
```

**Justification du compromis confidentialité** : l'option E2E pure (clés côté client) a été écartée car (1) elle est incompatible avec la stack serveur actuelle sans effort R&D lourd, (2) les métadonnées restant visibles offrent une fausse promesse de secret, (3) elle complique la récupération en cas de perte d'appareil. L'option "lisible par admin" a été écartée car incompatible avec la sensibilité pastorale et les obligations de la loi sénégalaise 2008-12 sur les données à caractère religieux (catégorie particulière). Le compromis retenu (chiffrement au repos + accès restreint aux participants + rétention 180j + export avant purge) offre un équilibre implémentable qui protège les échanges du regard admin banal tout en préservant une porte de sortie légale encadrée.

### 7.9 Module BIBLE — La Sainte Bible

**Positionnement** : ✅ Implémenté. Contient le texte intégral de la Bible (Ancien et Nouveau Testament), avec support de la recherche full-text et des embeddings vectoriels.

| ID | Exigence | Priorité |
|---|---|---|
| REQ-BIBLE-01 | Le système MUST stocker intégralement les textes bibliques (Livres, Chapitres, Versets) | V1 |
| REQ-BIBLE-02 | Le système MUST proposer une recherche par mots-clés via PostgreSQL full-text search | V1 |
| REQ-BIBLE-03 | Le système SHOULD supporter la recherche sémantique via pgvector (embeddings) | V1 |
| REQ-BIBLE-04 | Le fidèle MUST pouvoir naviguer par Testament -> Livre -> Chapitre | V1 |

**Modèle de données Bible** :

```python
class Testament(models.Model):
    slug = SlugField(unique=True)
    name = CharField()
    order = IntegerField()

class Book(BaseModel):
    testament = FK(Testament)
    name = CharField()
    slug = SlugField()
    alt_names = JSONField() # e.g. ["Gn", "Genesis"]
    order = IntegerField()
    verse_count = IntegerField()

class Chapter(models.Model):
    book = FK(Book)
    number = IntegerField()
    name = CharField()
    verse_count = IntegerField()

class Verse(models.Model):
    chapter = FK(Chapter)
    number = IntegerField()
    text = TextField()
    original_id = IntegerField()
    original_position = IntegerField()
    source_file = CharField()
    tsv = SearchVectorField() # Full-text search
    embedding = VectorField(dimensions=768) # pgvector

class DailyText(BaseModel):
    """Lien entre Bible et AELF (fallback)."""
    date = DateField()
    category = CharField()
    title = CharField()
    content = TextField()
    local_matches = JSONField()
```

### 7.10 Module LITURGY — Liturgie et textes du jour

**Positionnement** : ✅ Implémenté. Intégration API AELF, synchronisation quotidienne via Celery.

| ID | Exigence | Priorité |
|---|---|---|
| REQ-LIT-01 | Le système MUST récupérer quotidiennement les lectures de la messe et de l'office des heures via l'API AELF | V1 |
| REQ-LIT-02 | Le système MUST stocker une copie locale (cache) des lectures pour garantir la performance et l'audit | V1 |
| REQ-LIT-03 | Les textes liturgiques MUST être liés aux versets de la Bible locale quand une correspondance est possible | V1 |

**Modèle de données Liturgie** :

```python
class AelfDataEntry(models.Model):
    """Journal technique des réponses brutes AELF."""
    source_endpoint = CharField()
    date = DateField()
    zone = CharField() # 'afrique', 'france'
    raw_json = JSONField()
    fetched_at = DateTimeField(auto_now_add=True)

class LiturgicalDate(models.Model):
    date = DateField()
    zone = CharField()
    day_name = CharField()
    season = CharField()
    mystery = CharField()
    notes = TextField()

class AelfResource(models.Model):
    liturgical_date = OneToOne(LiturgicalDate)
    audio_url = URLField()
    youtube_url = URLField()

class Reading(models.Model):
    liturgical_date = FK(LiturgicalDate)
    type = CharField() # 'premiere_lecture', 'evangile', etc.
    citation = CharField() # e.g., 'Jn 3,16'
    text = TextField()
    raw_metadata = JSONField()
    matched_verses = ManyToMany("bible.Verse")

class Office(models.Model):
    liturgical_date = FK(LiturgicalDate)
    office_type = CharField() # 'laudes', 'vepres', etc.
    hymn = TextField()
    psalms = JSONField()
    canticle = TextField()
    readings = JSONField()
    intercessions = TextField()
    raw_metadata = JSONField()
```


### 7.11 Module CHAPELET — Mon Chapelet Quotidien

**Positionnement** : ✅ Implémenté — en cours de validation interne. Mystères, rotation liturgique quotidienne et audio via MinIO. La mise en production publique est conditionnée à la disponibilité des enregistrements audio finaux.

**Position sur les contenus**

- **Textes des prières** (Notre Père, Je vous salue Marie, Gloire au Père, Credo, litanies de la Sainte Vierge) : **domaine public** (textes liturgiques multi-séculaires). Aucune restriction d'usage.
- **Méditations des mystères** : rédaction originale pour Jàngu Bi, ou textes du domaine public / issus d'œuvres sous licence compatible (Rosarium Virginis Mariae de Jean-Paul II, 2002 : consultation autorisée, à vérifier pour reproduction intégrale).
- **Audio** : **réenregistrement local obligatoire**. Les contenus audio issus de sites tiers (chapelet.net ou autres) **NE DOIVENT PAS** être utilisés sans licence écrite. Un partenariat avec un ou plusieurs prêtres de l'Archidiocèse de Dakar pour enregistrer les 20 mystères en français est prévu. Une version en wolof est souhaitable dans un second temps (atout identitaire fort de la plateforme).

**Répartition quotidienne des mystères** (norme universelle post-*Rosarium Virginis Mariae*, 2002) :

| Jour | Mystères par défaut | Exception liturgique |
|---|---|---|
| Lundi | Joyeux | — |
| Mardi | Douloureux | — |
| Mercredi | Glorieux | — |
| Jeudi | Lumineux | — |
| Vendredi | Douloureux | — |
| Samedi | Joyeux | — |
| Dimanche | Glorieux | **Avent : Joyeux / Carême : Douloureux** |

| ID | Exigence | Priorité |
|---|---|---|
| REQ-CHAP-01 | Le module MUST proposer un parcours guidé étape par étape : signe de croix, Credo, Notre Père, 3 Je vous salue Marie (vertus théologales), Gloire au Père, puis les 5 dizaines des mystères du jour, enfin Salve Regina | V2 |
| REQ-CHAP-02 | Le module MUST proposer les 4 mystères (Joyeux, Douloureux, Glorieux, Lumineux), chacun comprenant 5 méditations structurées | V2 |
| REQ-CHAP-03 | Le module MUST proposer par défaut les mystères du jour selon la répartition universelle, avec gestion des exceptions Avent (Joyeux) et Carême (Douloureux) le dimanche | V2 |
| REQ-CHAP-04 | Le calendrier liturgique (Avent, Carême) MUST être calculé automatiquement à partir de la date de Pâques de l'année en cours (algorithme de Butcher-Meeus) | V2 |
| REQ-CHAP-05 | Le fidèle MUST pouvoir choisir manuellement un autre mystère que celui proposé par défaut (liberté spirituelle) | V2 |
| REQ-CHAP-06 | Le module MUST proposer deux modes d'usage : mode lecture (texte) et mode audio (écoute guidée) | V2 |
| REQ-CHAP-07 | Les enregistrements audio MUST être produits par un ou plusieurs prêtres partenaires de l'Archidiocèse de Dakar. L'usage d'audio issu de sites tiers non licenciés est PROSCRIT | V2 |
| REQ-CHAP-08 | Le mode audio SHOULD permettre de prier hors connexion (téléchargement préalable des fichiers MP3/AAC sur l'appareil du fidèle) | V2 |
| REQ-CHAP-09 | Le module SHOULD historiser les chapelets priés par le fidèle (date, mystères médités) dans son espace personnel, sans partage ni affichage public | V2 |
| REQ-CHAP-10 | Une version en langue wolof SHOULD être proposée en V2.1 ou V3, après enregistrement audio par un prêtre wolophone | V3 |

**Modèle de données Chapelet** :

```python
class MysteryGroup(BaseModel):
    name = CharField()
    slug = SlugField()
    audio_file = FileField() # MinIO storage

class Mystery(BaseModel):
    group = FK(MysteryGroup)
    order = IntegerField() # 1 to 5
    title = CharField()
    meditation = TextField()
    audio_file = FileField()
    audio_duration = IntegerField()

class Prayer(BaseModel):
    type = CharField() # choices: SIGN_OF_CROSS, CREED, etc.
    text = TextField()
    language = CharField() # e.g., 'FR', 'WO'
    tsv = SearchVectorField()
    embedding = JSONField()

class MysteryPrayer(models.Model):
    mystery = FK(Mystery)
    prayer = FK(Prayer)
    order = IntegerField()

class RosaryDay(BaseModel):
    weekday = IntegerField() # 0-6
    group = FK(MysteryGroup)
```

### 7.12 Module RAG — Assistant Pastoral Intelligent

**Positionnement** : ✅ Implémenté. Moteur de recherche sémantique et assistant conversationnel basé sur les textes bibliques et le chapelet.

| ID | Exigence | Priorité |
|---|---|---|
| REQ-RAG-01 | Le système MUST utiliser pgvector pour stocker les embeddings des versets bibliques et des prières | V1 |
| REQ-RAG-02 | L'utilisateur MUST pouvoir poser des questions en langage naturel ("Que dit la Bible sur la paix ?") | V1 |
| REQ-RAG-03 | Les réponses MUST être sourcées avec des citations précises (Livre, Chapitre, Verset) | V1 |
| REQ-RAG-04 | L'assistant SHOULD pouvoir suggérer des méditations pour le chapelet basées sur le contexte | V1 |

### 7.13 Module TV — Jàngu Bi TV

**Positionnement** : ✅ Implémenté. Agrégation de contenus vidéos (YouTube) par catégories.

| ID | Exigence | Priorité |
|---|---|---|
| REQ-TV-01 | Le système MUST permettre de catégoriser les vidéos (Messes, Enseignement, etc.) | V1 |
| REQ-TV-02 | Le système MUST supporter l'intégration de flux YouTube (Live et Replay) | V1 |
| REQ-TV-03 | Une vidéo peut être marquée comme "Live" et "Épinglée" pour apparaître en priorité | V1 |

**Modèle de données TV** :

```python
class Category(BaseModel):
    name = CharField()
    slug = SlugField()
    order = IntegerField()

class Video(BaseModel):
    title = CharField()
    youtube_url = URLField()
    category = FK(Category)
    is_live = BooleanField()
    is_pinned_live = BooleanField()
```

### 7.14 Module DOCUMENTS — Demande de documents ecclésiaux (V3)

**Positionnement** : fonctionnalité **V3, sous réserve de décision**. Le modèle économique n'est pas encore tranché et nécessite une validation canoniste et épiscopale avant spécification définitive.

**⚠️ Point de décision en suspens**

La mise en œuvre de ce module est conditionnée à une décision ferme sur le modèle économique. Trois options sont envisageables, avec des implications canoniques différentes :

1. **Gratuit intégral** : aucun coût pour le fidèle. Modèle canoniquement sûr, cohérent avec la pratique universelle de l'Église. Requiert un financement par ailleurs (subvention diocésaine, mécénat).
2. **Don libre suggéré** (*recommandation forte*) : le document est délivré indépendamment de tout paiement, mais un écran optionnel propose un don libre "pour les frais de secrétariat" à la fin du formulaire. Le fidèle peut choisir 0 FCFA sans conséquence. Modèle canoniquement sûr (évite toute simonie), économiquement viable.
3. **Payant** : facturation obligatoire. **Non recommandé** — risque canonique (frontière avec la simonie au sens du canon 848), risque social (exclusion des fidèles pauvres), risque réputationnel.

**Tant que cette décision n'est pas tranchée et validée par l'Archevêque de Dakar (ou son représentant canoniste), le module reste en état de spécification préliminaire et n'entre pas en développement.**

**Spécification fonctionnelle (sous réserve de validation du modèle économique)**

Cette section reprend et adapte la spécification fonctionnelle "Formulaire unique de demande de documents ecclésiaux" (v1.0, 8 avril 2026) fournie par la maîtrise d'ouvrage, tout en l'intégrant dans le modèle de données et la logique RBAC de Jàngu Bi.

**Documents couverts en V3** :
- Certificat de baptême
- Attestation de première communion
- Attestation de confirmation
- Attestation de mariage religieux
- Attestation pour être parrain ou marraine

**Principe directeur** : formulaire simple côté fidèle, recherche riche côté back-office paroisse. Le fidèle ne renseigne **jamais** les références internes de registre (folio, tome, numéro d'acte).

| ID | Exigence | Priorité |
|---|---|---|
| REQ-DOC-00 | L'activation du module MUST être conditionnée à une décision écrite de l'Archevêque sur le modèle économique (gratuit / don libre / payant) | V3 |
| REQ-DOC-01 | Le formulaire MUST permettre une seule demande par soumission (un seul type de document, un seul motif) | V3 |
| REQ-DOC-02 | Le parcours MUST tenir en 4 écrans maximum sur mobile : (1) choix document + motif, (2) identification, (3) recherche registres, (4) validation | V3 |
| REQ-DOC-03 | Les champs dynamiques (parrain/marraine, nom du célébrant, date approximative, etc.) MUST s'afficher conditionnellement selon le type de document choisi | V3 |
| REQ-DOC-04 | Les références internes de registre (folio, tome, numéro d'acte) NE DOIVENT PAS être demandées au fidèle | V3 |
| REQ-DOC-05 | La date du sacrement MUST accepter une année seule ou une fourchette approximative (le fidèle ne se souvient souvent pas de la date exacte) | V3 |
| REQ-DOC-06 | Le consentement explicite à la vérification en registres (case à cocher) MUST être obligatoire avant soumission | V3 |
| REQ-DOC-07 | Chaque demande MUST recevoir un identifiant unique lisible au format `DOC-YYYYMMDD-NNNNNN` | V3 |
| REQ-DOC-08 | Le back-office paroisse MUST proposer 6 statuts : Soumise, En vérification, Complément demandé, Validée, Rejetée, Document déposé | V3 |
| REQ-DOC-09 | Le rejet d'une demande MUST être accompagné d'un motif écrit obligatoire, notifié au fidèle | V3 |
| REQ-DOC-10 | Le document final validé MUST être déposé en PDF dans l'espace personnel du fidèle, avec notification email + push | V3 |
| REQ-DOC-11 | Un agent paroissial MUST pouvoir demander un complément au fidèle sans recréer la demande (thread de messages internes) | V3 |
| REQ-DOC-12 | Toute action (consultation, annotation, validation, rejet) sur une demande MUST être tracée dans `AuditLog` | V3 |
| REQ-DOC-13 | Si le modèle "don libre" est retenu, un écran optionnel de don SHOULD apparaître après soumission, avec option claire "Non, merci" sans aucun impact sur le traitement de la demande | V3 |
| REQ-DOC-14 | Le document final MUST être accessible uniquement au demandeur authentifié et, le cas échéant, au curé destinataire s'il est renseigné dans le formulaire | V3 |
| REQ-DOC-15 | Les pièces jointes (pièce d'identité, ancien document religieux) MUST être stockées avec accès restreint (URL non publique, authentification requise) | V3 |

**Modèle de données additionnel V3** (à finaliser après décision modèle économique) :

```python
class DocumentRequest(BaseModel):
    STATUS_CHOICES = [
        ('submitted', 'Soumise'),
        ('in_review', 'En vérification'),
        ('complement_needed', 'Complément demandé'),
        ('validated', 'Validée'),
        ('rejected', 'Rejetée'),
        ('delivered', 'Document déposé'),
    ]
    DOCUMENT_TYPES = [
        ('bapteme', 'Certificat de baptême'),
        ('premiere_communion', 'Attestation de première communion'),
        ('confirmation', 'Attestation de confirmation'),
        ('mariage', 'Attestation de mariage religieux'),
        ('parrain_marraine', 'Attestation pour parrain/marraine'),
    ]

    reference = models.CharField(max_length=30, unique=True)  # DOC-20260408-000123
    requester = models.ForeignKey(User, on_delete=models.PROTECT, related_name='document_requests')
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPES)
    motive = models.CharField(max_length=50)
    parish = models.ForeignKey(Parish, on_delete=models.PROTECT, related_name='document_requests')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='submitted')
    form_data = models.JSONField()  # Contient les champs dynamiques selon document_type
    consent_given_at = models.DateTimeField()
    final_document = models.FileField(upload_to='documents/final/', null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    assigned_to = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='assigned_requests')

class DocumentRequestMessage(BaseModel):
    """Thread interne : paroisse ↔ fidèle pour demandes de complément."""
    request = models.ForeignKey(DocumentRequest, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.PROTECT)
    body = models.TextField()
    is_internal_note = models.BooleanField(default=False)  # Note interne paroisse, invisible au fidèle

class DocumentRequestAttachment(BaseModel):
    request = models.ForeignKey(DocumentRequest, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='documents/attachments/')
    uploaded_by = models.ForeignKey(User, on_delete=models.PROTECT)
    description = models.CharField(max_length=200, blank=True)

### 7.13 Module RAG — Assistant Pastoral Intelligent

**Positionnement** : ✅ Implémenté. Moteur de recherche sémantique et assistant conversationnel basé sur les textes bibliques et le chapelet.

| ID | Exigence | Priorité |
|---|---|---|
| REQ-RAG-01 | Le système MUST utiliser pgvector pour stocker les embeddings des versets bibliques et des prières | V1 |
| REQ-RAG-02 | L'utilisateur MUST pouvoir poser des questions en langage naturel ("Que dit la Bible sur la paix ?") | V1 |
| REQ-RAG-03 | Les réponses MUST être sourcées avec des citations précises (Livre, Chapitre, Verset) | V1 |
| REQ-RAG-04 | L'assistant SHOULD pouvoir suggérer des méditations pour le chapelet basées sur le contexte | V1 |

### 7.14 Module TV — Jàngu Bi TV

**Positionnement** : ✅ Implémenté. Plateforme de diffusion de contenus vidéo (Messes en direct, enseignements).

| ID | Exigence | Priorité |
|---|---|---|
| REQ-TV-01 | Le système MUST gérer des catégories de vidéos (Messes, Enseignement, Documentaires) | V1 |
| REQ-TV-02 | Le système MUST permettre d'épingler une vidéo "En Direct" (Live) sur la page d'accueil | V1 |
| REQ-TV-03 | L'intégration MUST se faire via des URLs YouTube avec extraction automatique de l'ID | V1 |

**Modèle de données TV** :

```python
class Category(BaseModel):
    name = CharField()
    slug = SlugField(unique=True)
    order = IntegerField()

class Video(BaseModel):
    title = CharField()
    youtube_url = URLField()
    category = FK(Category)
    is_live = BooleanField()
    is_pinned_live = BooleanField()
```
```

---

## 8. Règles métier critiques

Récapitulatif des règles de gestion qui doivent être **implémentées au niveau base de données** (contraintes PostgreSQL) et/ou **au niveau service** (Django).

| ID | Règle | Niveau |
|---|---|---|
| RG-ORG-01 | Un seul Diocese peut avoir `is_metropolitan=True` par EcclesiasticalProvince | DB (partial unique index) |
| RG-ORG-02 | Le `code` d'un Diocese est unique globalement | DB (UNIQUE) |
| RG-ORG-03 | Une Parish doit avoir exactement une Church avec `is_main=True` | Service + check on save |
| RG-ORG-04 | Suppression d'une Church principale interdite tant qu'une autre n'est pas promue | Service (override delete) |
| RG-USER-01 | Email vérifié obligatoire avant don connecté ou rôle admin | Service (validation API) |
| RG-RBAC-01 | Cohérence scope ↔ entité remplie dans RoleAssignment | DB (CHECK constraint) |
| RG-RBAC-02 | Un user ne peut avoir deux rôles admin du même niveau sur la même entité | DB (partial unique) |
| RG-RBAC-03 | Seul super_admin crée des RoleAssignment en V1 | Service (permission API) |
| RG-PAY-01 | `donor IS NULL` XOR `anonymous_donor_*` renseigné | DB (CHECK) |
| RG-PAY-02 | Don anonyme ≤ 25 000 FCFA | Service (validation) |
| RG-PAY-03 | `church.parish` doit égaler `payment.parish` si church renseignée | Service |
| RG-PAY-04 | Idempotence : COMPLETED est terminal | Service (state machine) |
| RG-PAY-05 | Payment jamais soft-deleted | Service (bloquer delete) |
| RG-CONT-01 | Scope_type ↔ scope_entity cohérent dans News | DB (CHECK) |
| RG-AUDIT-01 | AuditLog append-only | DB (trigger refuser UPDATE/DELETE) |

### 8.1 State machine des paiements

```
                    ┌─────────┐
                    │ PENDING │  (initiation, token PayDunya obtenu)
                    └────┬────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
         ▼               ▼               ▼
    ┌─────────┐    ┌─────────┐    ┌─────────┐
    │COMPLETED│    │ FAILED  │    │CANCELED │
    └────┬────┘    └─────────┘    └─────────┘
         │            (terminal)    (terminal)
         │
         ▼
    ┌─────────┐
    │REFUNDED │  (uniquement via action admin V2)
    └─────────┘
     (terminal)
```

**Règles** :
- `PENDING` → `COMPLETED` : via webhook PayDunya authentifié
- `PENDING` → `FAILED` : via webhook ou timeout (24h sans réponse)
- `PENDING` → `CANCELED` : via retour utilisateur ou webhook d'annulation
- `COMPLETED` → `REFUNDED` : uniquement via action manuelle Parish Admin (V2)
- **Aucune autre transition n'est autorisée.**

---

## 9. Exigences non fonctionnelles

### 9.1 Sécurité

| ID | Exigence |
|---|---|
| NFR-SEC-01 | La signature des webhooks PayDunya MUST être vérifiée cryptographiquement avant toute opération BDD |
| NFR-SEC-02 | Toutes les communications MUST utiliser HTTPS (TLS 1.3) en production |
| NFR-SEC-03 | Les mots de passe MUST être hachés avec Argon2 (algorithme par défaut Django 5.x) |
| NFR-SEC-04 | Les tokens JWT MUST être signés avec une clé secrète ≥ 256 bits, rotatable |
| NFR-SEC-05 | L'API MUST inclure les en-têtes de sécurité : HSTS, CSP, X-Frame-Options, X-Content-Type-Options |
| NFR-SEC-06 | Le rate limiting MUST être activé : 100 req/min par IP, 10 tentatives de login/5 min par email |
| NFR-SEC-07 | Toute donnée sensible en BDD (téléphone, email optionnel anonyme) SHOULD être chiffrée applicativement |
| NFR-SEC-08 | Backup quotidien chiffré de la base, rétention 30 jours minimum |

### 9.2 Performance

| ID | Exigence |
|---|---|
| NFR-PERF-01 | Temps de réponse API p95 < 500 ms (hors appels PayDunya) |
| NFR-PERF-02 | Les endpoints listant des ressources liées MUST utiliser `select_related` / `prefetch_related` pour éviter le N+1 |
| NFR-PERF-03 | La liste publique des paroisses MUST être cachée (Redis, TTL 15 min) |
| NFR-PERF-04 | Les fils d'actualité MUST être paginés (20 items par page par défaut) |
| NFR-PERF-05 | La plateforme MUST supporter 500 utilisateurs concurrents en V1 |

### 9.3 Disponibilité

| ID | Exigence |
|---|---|
| NFR-AVAIL-01 | Uptime cible ≥ 99,5 % (hors maintenances planifiées annoncées) |
| NFR-AVAIL-02 | Monitoring actif : Sentry (erreurs applicatives) + UptimeRobot (disponibilité) |
| NFR-AVAIL-03 | Alerting : email + SMS (admin technique) en cas de downtime > 5 min |

### 9.4 UX et accessibilité

| ID | Exigence |
|---|---|
| NFR-UI-01 | Les deux portails (Admin et Membre) MUST être responsive (mobile-first) |
| NFR-UI-02 | Le portail Membre MUST être utilisable sur un smartphone bas de gamme (2GB RAM, 3G) |
| NFR-UI-03 | Langue par défaut : français. Wolof envisagé en V2 |
| NFR-UI-04 | Accessibilité : respect des bonnes pratiques WCAG 2.1 niveau AA minimum |
| NFR-UI-05 | Temps de chargement initial de la home < 3 secondes en 3G |

### 9.5 Maintenabilité

| ID | Exigence |
|---|---|
| NFR-MAINT-01 | Le code Django MUST suivre le HackSoftware Django Styleguide (Models / Services / Selectors / APIs) |
| NFR-MAINT-02 | Couverture de tests unitaires ≥ 70 % sur les services et règles métier |
| NFR-MAINT-03 | Documentation API auto-générée via drf-spectacular (OpenAPI 3) |
| NFR-MAINT-04 | CI/CD : lint (ruff), type-check (mypy), tests (pytest) obligatoires avant merge |

### 9.6 Conformité

| ID | Exigence |
|---|---|
| NFR-COMP-01 | Conformité RGPD-like : droit d'accès, rectification, effacement des fidèles |
| NFR-COMP-02 | Déclaration CDP (Commission de Protection des Données - Sénégal) à la charge du client |
| NFR-COMP-03 | Politique de confidentialité publique et CGU accessibles sur la plateforme |

---

## 10. Parcours utilisateurs clés

### 10.1 Parcours : Don anonyme (< 25 000 FCFA)

1. Visiteur arrive sur la page publique d'une paroisse
2. Clique sur "Faire un don"
3. Choisit un type de don (ex: Quête) parmi ceux activés par la paroisse
4. Choisit un montant parmi les 4 suggérés ou saisit un montant libre (≤ 25 000)
5. Saisit **optionnellement** nom, email, téléphone
6. Clique sur "Payer" → redirection PayDunya
7. Paie sur PayDunya (mobile money, carte)
8. PayDunya redirige vers la page "Merci" de la plateforme
9. Simultanément, PayDunya envoie un webhook IPN → backend valide signature, met `Payment.status=COMPLETED`
10. Si email fourni, envoi d'un reçu simple par email
11. Le Parish Admin reçoit une notification temps réel + email

### 10.2 Parcours : Don connecté (montant libre)

1. Fidèle se connecte à son Espace Membre
2. Sélectionne sa paroisse (par défaut : sa `primary_parish`, peut en choisir une autre)
3. Choisit type de don + montant (pas de limite)
4. Confirmation → initiation `Payment` avec `donor=user.id`
5. Redirection PayDunya
6. [Idem 7 à 11 du parcours précédent, mais le reçu va à l'email du compte]
7. Le don apparaît dans l'historique de l'Espace Membre

### 10.3 Parcours : Publication d'une News par un Church Admin

1. Church Admin se connecte à l'Espace Admin
2. Va sur "Contenus → Actualités"
3. Clique "Nouvelle actualité"
4. Rédige titre + contenu + scope automatiquement fixé à son église
5. Clique "Publier"
6. Statut passe à `published`, `published_at=now()`
7. Événement WebSocket émis à tous les fidèles dont `primary_parish` correspond à la paroisse de l'église
8. Chaque fidèle concerné voit sa pastille de notifications s'incrémenter

### 10.4 Parcours : Modération a posteriori par un Parish Admin

1. Un Church Admin publie une News jugée inappropriée
2. Le Parish Admin, en parcourant le flux, la repère
3. Clique "Dépublier" → motif obligatoire (ex: "Contenu politique non approprié")
4. `News.status` passe à `unpublished`, `unpublished_by=user.id`, `unpublish_reason=...`
5. La News disparaît du fil des fidèles
6. `AuditLog` enregistre l'événement
7. Le Church Admin auteur reçoit une notification du motif

### 10.5 Parcours : Création d'un nouveau Parish Admin (Super Admin)

1. Super Admin se connecte à l'Espace Admin
2. Va sur "Utilisateurs → Nouveau"
3. Saisit email, nom, prénom, primary_parish
4. Coche "Rôle : Parish Admin" et sélectionne la Parish concernée
5. Valide → création `UserProfile` avec mot de passe temporaire généré + `must_change_password=True`
6. Création `RoleAssignment` scope=parish, parish=X, group=parish_admin
7. Email envoyé au nouveau Parish Admin avec lien de vérification + mot de passe temporaire
8. AuditLog enregistre `USER_CREATED` + `ROLE_ASSIGNED`

---

## 11. Stratégie de release

### 11.1 V1 — MVP fonctionnel (3-4 mois)

**Objectif** : plateforme utilisable de bout en bout pour les fonctions essentielles.

Contenu :
- Tous les modules ci-dessus avec priorité V1
- Déploiement staging + production
- Documentation utilisateur de base
- Seed initial 1 Province + 7 Diocèses

### 11.2 V2 — Montée en maturité (+2-3 mois)

**Thème principal** : scale opérationnel + première ouverture pastorale et spirituelle numérique.

- **Délégation hiérarchique descendante** de création d'admins (Super Admin → Province Admin → Diocese Admin → Parish Admin → Church Admin), avec règles strictes anti-saut d'échelon et journalisation complète
- **Module CHAT pastoral** (section 7.8) : messagerie bilatérale fidèle ↔ prêtre avec cadrage théologique explicite, chiffrement au repos, rétention 180 jours, export RGPD
- **Module BIBLE / Liturgie** (section 7.9) : ✅ implémenté — activation en production conditionnée à l'accord écrit AELF
- **Module CHAPELET quotidien** (section 7.10) : ✅ implémenté — activation en production conditionnée à la disponibilité des enregistrements audio
- 2FA par email pour comptes admin
- Remboursement manuel des dons
- Géolocalisation d'églises + carte "Trouver une église"
- Export PDF des historiques de dons (Parish Admin)
- Wolof dans l'UI

**Prérequis métier pour déclencher la V2** : au moins 3 mois d'exploitation V1 stable + retour structuré des Parish Admins sur les besoins pastoraux réellement exprimés par les fidèles.

**Prérequis externes à lever avant la V2** :
- Accord écrit AELF (module Bible) — démarche à lancer dès validation de la v2.4 auprès de `contact@aelf.org` avec lettre de soutien de l'Archevêque de Dakar
- Identification d'un ou plusieurs prêtres volontaires pour enregistrer les méditations du chapelet (français) — 20 enregistrements à prévoir

### 11.3 V3 — Évolutions stratégiques

- **Workflow self-service de délégation** : un admin demande la création d'un sous-admin via l'interface, approbation explicite par le supérieur hiérarchique avant activation
- **Module DOCUMENTS ecclésiaux** (section 7.11) : demande en ligne de certificats de baptême, confirmation, mariage, première communion, parrainage. **Prérequis bloquant** : décision écrite de l'Archevêque sur le modèle économique (gratuit / don libre / payant)
- **Chapelet en wolof** : enregistrement audio par un prêtre wolophone, traduction des méditations — atout identitaire fort de la plateforme
- Application mobile native (iOS + Android)
- Reçus fiscaux si le cadre réglementaire évolue
- Dashboard analytique multi-niveaux
- Intégration d'autres prestataires de paiement (Wave, Orange Money direct)
- Envois SMS des notifications importantes

### 11.4 Hors scope définitif

- Vente de livres / contenus numériques (retiré de v2.2)
- Gestion de sacrements (baptême, mariage) — autre projet
- Comptabilité paroissiale complète — autre projet

---

## 12. Annexes

### 12.1 Corrections majeures par rapport au SRS v2.2

| # | Problème v2.2 | Correction v2.4 |
|---|---|---|
| 1 | Fusion Archdiocese/Diocese avec simple flag `is_metropolitan`, sans province parente | Introduction `EcclesiasticalProvince` + `Diocese` appartient à une province, avec `is_metropolitan` qui identifie l'archidiocèse au sein de sa province |
| 2 | Relation Parish → Church sans distinction église principale | Ajout `Church.is_main` + règle RG-ORG-03 |
| 3 | FK redondante `Church.dioceseId` | Supprimée, dérivée via `church.parish.diocese` |
| 4 | `UserProfile.role` enum figé | Remplacé par Django Groups + RoleAssignment scopés |
| 5 | Pas de table RoleAssignment, donc impossible de scoper un rôle à une paroisse précise | `RoleAssignment` avec scope_type + FK scopée |
| 6 | `DonationType` avec FK Parish + slug UNIQUE global : contradiction | Types globaux fixes + `ParishDonationConfig` pour les montants par paroisse |
| 7 | `Payment.donor` obligatoire : pas de dons anonymes possibles | `donor` nullable + champs anonymous_* + seuil 25 000 FCFA |
| 8 | `payment_type='book'` alors qu'aucune entité Book définie | Vente de livres supprimée du scope v2.4 |
| 9 | Pas de `parish` ni `church` sur Payment : impossible de savoir qui reçoit | Ajout FK parish (obligatoire) + church (optionnelle pour cierges) |
| 10 | `News.validated_by_parish` + workflow pending→published complexe | Workflow simplifié : publish direct + modération a posteriori |
| 11 | `MassTime.days` en ArrayField de strings non requêtable | Remplacé par `day_of_week` (int) + N enregistrements si plusieurs jours + table d'exceptions |
| 12 | `AuditLog` limité aux paiements, sans timestamp ni user | Généralisé à tous événements, avec user, timestamp, IP, user-agent |
| 13 | Pas de soft-delete | `BaseModel` abstrait (soft-delete reporté en V2) |
| 14 | Pas de contraintes d'intégrité (CHECK, partial unique) | Contraintes DB explicites via Meta.constraints |
| 15 | Pas de journalisation d'authentification | REQ-AUDIT-03 ajoutée |
| 16 | Création admins centralisée sans stratégie de scale | Phasage V1 centralisé → V2 délégation descendante → V3 self-service (REQ-USER-07 à 10) |
| 17 | Absence de canal pastoral direct fidèle ↔ prêtre | Module CHAT V2 avec cadrage théologique strict (section 7.8) — rejet explicite de la confession à distance, chiffrement au repos, rétention 180j |
| 18 | Absence de module spirituel (Bible, liturgie) malgré son centralité pour une plateforme catholique | Modules BIBLE & LITURGY (sections 7.9 et 7.10) ✅ Implémentés |
| 19 | Absence de soutien à la prière personnelle des fidèles | Module CHAPELET (section 7.11) ✅ Implémenté |
| 20 | Demande de documents ecclésiaux non prévue alors qu'il s'agit d'un besoin réel des fidèles | Module DOCUMENTS (section 7.12) spécifié (V3) |

### 12.2 Glossaire technique

| Terme | Définition |
|---|---|
| JWT | JSON Web Token — standard d'authentification stateless |
| IPN | Instant Payment Notification — webhook PayDunya |
| RBAC | Role-Based Access Control |
| DRF | Django REST Framework |
| FCFA / XOF | Franc CFA (ouest-africain), devise du Sénégal |
| WebSocket | Protocole de communication bidirectionnelle temps réel |
| CDP | Commission de Protection des Données (Sénégal) |
| WCAG | Web Content Accessibility Guidelines |
| CSP | Content Security Policy |
| HSTS | HTTP Strict Transport Security |

### 12.3 Questions ouvertes à valider

| # | Question | Impact |
|---|---|---|
| 1 | Validation du seuil 25 000 FCFA pour dons anonymes par le Product Owner | Sécurité / UX |
| 2 | Le Super Admin centralisé est-il tenable à 30+ paroisses ? Délégation V2 à prioriser ? | Scalabilité |
| 3 | Les églises ont-elles vraiment besoin d'un admin dédié `church_admin`, ou suffit-il de `parish_admin` + `is_main` ? | Simplification possible |
| 4 | Gestion des intentions de prière : notification au curé ? Historique patient ? | Fonctionnel |
| 5 | Politique de gestion des paroisses fusionnées / scindées au fil du temps | Scalabilité |
| 6 | **Conformité juridique AELF** : maintien des mentions légales et respect des quotas d'usage | Conformité |
| 7 | **Enregistrements audio du chapelet** : finalisation des audios par des prêtres de l'Archidiocèse | **Qualité contenu** |
| 8 | **Modèle économique des documents ecclésiaux** : gratuit, don libre (recommandé), ou payant ? Validation canoniste requise | **Bloquant V3** |
| 9 | **RAG / Assistant Pastoral** : validation de la pertinence des réponses par des théologiens | **Qualité IA** |
| 10 | **TV / Lives** : stabilité du flux lors des pics d'audience (messes solennelles) | **Performance** |
| 11 | **Définition d'une DPIA** (analyse d'impact RGPD/CDP) pour les modules CHAT et DOCUMENTS | Conformité légale |
| 12 | **Politique de gestion de l'accord AELF** en cas d'évolution des CGU | Conformité juridique |

---

**Fin du document — SRS Jàngu Bi v2.4**
