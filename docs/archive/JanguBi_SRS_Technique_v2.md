# Jangu Bi — SRS Technique Complet
> Numerisen — Services Numériques | Version 2.0 | Mai 2025  
> Usage : Développement interne / Claude Code

---

## Table des matières

1. [Vue d'ensemble](#1-vue-densemble)
2. [Rôles et hiérarchie](#2-rôles-et-hiérarchie)
3. [Principes architecturaux](#3-principes-architecturaux)
4. [Super Administrateur](#4-super-administrateur)
5. [Onboarding & Gestion des comptes](#5-onboarding--gestion-des-comptes)
6. [Module — Liturgie du Jour & Liturgie des Heures](#6-module--liturgie-du-jour--liturgie-des-heures)
7. [Module — Bible & Chapelet](#7-module--bible--chapelet)
8. [Module — Messagerie & Allo-Prêtre](#8-module--messagerie--allo-prêtre)
9. [Module — Actus](#9-module--actus)
10. [Module — Documents Officiels](#10-module--documents-officiels)
11. [Module — Agenda & Événements](#11-module--agenda--événements)
12. [Module — Intentions de Messe](#12-module--intentions-de-messe)
13. [Module — Dons & Quêtes](#13-module--dons--quêtes)
14. [Module — Jangu Bi TV](#14-module--jangu-bi-tv)
15. [Système de notifications](#15-système-de-notifications)
16. [Matrice des permissions complète](#16-matrice-des-permissions-complète)
17. [Dashboards par rôle](#17-dashboards-par-rôle)
18. [Assistants & Délégation](#18-assistants--délégation)
19. [Priorités de développement](#19-priorités-de-développement)

---

## 1. Vue d'ensemble

### Identité

- **Nom** : Jangu Bi ("Jàngu Bi" = "La Leçon" en wolof)
- **Éditeur** : Numerisen — Services Numériques
- **Type** : Plateforme communautaire catholique — Sénégal
- **Stack** : Django 5.2 + DRF / Next.js 14 App Router / PostgreSQL + pgvector / Redis / Celery / Django Channels / MinIO

### Objectif produit

Créer une plateforme où chaque acteur de l'Église catholique trouve des outils si adaptés à son quotidien qu'il en devient naturellement dépendant. KPI de succès : fréquence d'ouverture quotidienne, rétention J30, J90.

---

## 2. Rôles et hiérarchie

### 2.1 Deux dimensions de rôles

#### Dimension 1 — Rôles pastoraux

```python
class PastoralRole(models.TextChoices):
    ARCHEVEQUE = 'archeveque'
    EVEQUE     = 'eveque'
    PRETRE     = 'pretre'
    DIACRE     = 'diacre'
    RELIGIEUX  = 'religieux'   # frères, sœurs, moines, moniales
    FIDELE     = 'fidele'      # laïc standard (existant)
```

#### Dimension 2 — Rôles d'administration digitale (existants)

```python
class UserRole(models.TextChoices):
    SUPER_ADMIN    = 'super_admin'
    PROVINCE_ADMIN = 'province_admin'
    DIOCESE_ADMIN  = 'diocese_admin'
    PARISH_ADMIN   = 'parish_admin'
    CHURCH_ADMIN   = 'church_admin'
```

> **Principe** : Ces deux dimensions sont orthogonales. Un curé (`pastoral_role=PRETRE`) peut aussi avoir `role=PARISH_ADMIN`. Ces deux axes coexistent sans se confondre.

### 2.2 Hiérarchie territoriale

```
Province  (Archevêque)
  └── Diocèse  (Évêque)
        └── Paroisse  (Prêtre)
              ├── Fidèle
              ├── Diacre
              └── Religieux (via ReligiousCommunity)
```

### 2.3 Entités territoriales

```python
class Province(models.Model):
    name: CharField
    code: CharField(unique=True)

class Diocese(models.Model):
    name: CharField
    province: FK → Province

class Parish(models.Model):
    name: CharField
    diocese: FK → Diocese
    address: TextField

class ReligiousOrder(models.Model):
    name: CharField           # ex: Franciscains
    abbreviation: CharField   # ex: OFM

class ReligiousCommunity(models.Model):
    name: CharField           # ex: Couvent Saint-François de Dakar
    order: FK → ReligiousOrder
    diocese: FK → Diocese     # obligatoire
    parish: FK → Parish(null=True)  # optionnel
```

### 2.4 Modèle User enrichi

```python
class BaseUser(AbstractUser):
    # Rôle pastoral (nouveau)
    pastoral_role: CharField(choices=PastoralRole.choices, null=True, blank=True)
    # Rôle admin digital (existant)
    role: CharField(choices=UserRole.choices, default=UserRole.FIDELE)

    # Appartenance territoriale (migration depuis IntegerField)
    primary_parish: FK → Parish(null=True)
    diocese: FK → Diocese(null=True)         # déduit de primary_parish
    province: FK → Province(null=True)       # déduit de diocese
    religious_community: FK → ReligiousCommunity(null=True)

    followed_parishes: M2M → Parish(related_name='followers')

    def has_pastoral_role(self):
        return self.pastoral_role in [
            PastoralRole.PRETRE, PastoralRole.DIACRE,
            PastoralRole.RELIGIEUX, PastoralRole.EVEQUE,
            PastoralRole.ARCHEVEQUE
        ]

    def get_scope_ids(self):
        return {
            'parish_ids': list(self.followed_parishes.values_list('id', flat=True)),
            'diocese_id': self.diocese_id,
            'province_id': self.province_id,
        }
```

---

## 3. Principes architecturaux

### 3.1 Scoping de contenu

```python
class ContentScope(models.TextChoices):
    PARISH   = 'parish'
    DIOCESE  = 'diocese'
    PROVINCE = 'province'
    GLOBAL   = 'global'
```

**Règle d'affichage** : Un utilisateur voit le contenu dont le scope correspond à son périmètre ou un périmètre supérieur.

```python
def get_scoped_queryset(user, qs):
    scope = user.get_scope_ids()
    return qs.filter(
        Q(scope=ContentScope.GLOBAL) |
        Q(scope=ContentScope.PROVINCE, scope_id=scope['province_id']) |
        Q(scope=ContentScope.DIOCESE, scope_id=scope['diocese_id']) |
        Q(scope=ContentScope.PARISH, scope_id__in=scope['parish_ids'])
    )
```

### 3.2 Règle de publication maximale par rôle

```python
MAX_SCOPE = {
    PastoralRole.PRETRE:     ContentScope.PARISH,
    PastoralRole.DIACRE:     ContentScope.PARISH,   # brouillons seulement
    PastoralRole.EVEQUE:     ContentScope.DIOCESE,
    PastoralRole.ARCHEVEQUE: ContentScope.PROVINCE,
    UserRole.SUPER_ADMIN:    ContentScope.GLOBAL,
}
```

### 3.3 Chaîne de validation des comptes clergé

```
SUPER_ADMIN     → crée/valide ARCHEVEQUE
ARCHEVEQUE      → crée/valide EVEQUE
EVEQUE          → crée/valide PRETRE (assigne à une paroisse)
PRETRE          → crée/valide DIACRE + RELIGIEUX de sa paroisse
```

---

## 4. Super Administrateur

### 4.1 Profil et accès

Le Super Admin est le garant de l'intégrité technique et structurelle de la plateforme. Il n'a **aucun rôle pastoral**. Il n'a **jamais accès** aux conversations entre fidèles et clergé.

### 4.2 Capacités exclusives

| Domaine | Actions |
|---|---|
| **Structure territoriale** | CRUD complet sur Province, Diocese, Parish, ReligiousOrder, ReligiousCommunity |
| **Comptes** | Créer/valider ARCHEVEQUE. Activer/désactiver tout compte. Reset password. |
| **Dons** | Gérer la table de référence `DonationType` (CRUD) |
| **Contenu global** | Publier actus et vidéos scope=GLOBAL. Gérer catégorie Formation sur TV. |
| **Modération** | Dépublier tout contenu. Suspendre tout compte. Traiter les signalements. |
| **Configuration système** | `MESSAGING_PURGE_DAYS`, SLA des documents, règles de notification globales |
| **Analytics** | Accès lecture à toutes les métriques de toutes les entités |

### 4.3 Modèle de configuration système

```python
class SystemConfig(models.Model):
    key: CharField(unique=True)
    value: TextField
    description: TextField
    updated_by: FK → User
    updated_at: DateTimeField

# Clés gérées :
# messaging.purge_days       → int (défaut 180)
# documents.sla.{type}       → int (jours, par type de document)
# notifications.daily_max    → int (défaut 5)
# notifications.silence_start → int (heure, défaut 22)
# notifications.silence_end   → int (heure, défaut 6)
```

### 4.4 Dashboard Super Admin

```
── Bloc Santé plateforme ─────────────────────────────
  Utilisateurs actifs aujourd'hui / J-7 / J-30
  Taux de rétention J30 / J90
  Paroisses actives / total (ratio de couverture)
  Répartition par province

── Bloc File de validation ───────────────────────────
  Comptes clergé en attente de validation (list)
  Demandes de rôle pastoral non traitées (count)
  Transferts paroissiaux bloqués > 7 jours (count)

── Bloc Modération ───────────────────────────────────
  Signalements non traités (count + list)
  Contenus publiés aujourd'hui par scope
  Vidéos Formation publiées ce mois

── Bloc Finance ──────────────────────────────────────
  Volume total transactions (XOF) par provider
  Taux de succès des paiements par provider
  Campagnes de dons actives (count)
  Intentions de messe en attente (count)
```

### 4.5 Permissions Super Admin — ce qu'il ne peut PAS faire

```python
SUPER_ADMIN_FORBIDDEN = [
    'read_pastoral_conversations',   # Jamais — chiffrement E2E
    'read_lectio_divina_notes',      # Privé par nature
    'impersonate_user',              # Non implémenté
]
```

---

## 5. Onboarding & Gestion des comptes

### 5.1 Flux inscription fidèle

```
1. Inscription (email/password ou OAuth)
2. Vérification email
3. [OBLIGATOIRE] Sélection paroisse principale
   Options: géolocalisation | recherche | navigation Diocese→Paroisses
4. [OPTIONNEL] Suivre d'autres paroisses
5. Accès complet
```

```python
class UserOnboardingState(models.TextChoices):
    PENDING_EMAIL_VERIFICATION = 'pending_email'
    PENDING_PARISH_SELECTION   = 'pending_parish'
    COMPLETED                  = 'completed'
```

### 5.2 Rattachement paroissial

```python
# primary_parish détermine diocese et province automatiquement
@receiver(post_save, sender=UserProfile)
def sync_territorial_scope(sender, instance, **kwargs):
    if instance.primary_parish:
        parish = instance.primary_parish
        instance.diocese = parish.diocese
        instance.province = parish.diocese.province
        UserProfile.objects.filter(pk=instance.pk).update(
            diocese=instance.diocese,
            province=instance.province
        )
```

### 5.3 Transfert paroissial

```python
class ParishTransferRequest(models.Model):
    requester: FK → User
    origin_parish: FK → Parish
    target_parish: FK → Parish
    status: CharField(choices=[
        'pending',            # Soumis par le fidèle
        'origin_validated',   # Prêtre A a validé + lettre émise
        'target_acknowledged',# Prêtre B a accusé réception
        'completed',          # primary_parish mis à jour
    ])
    origin_priest_approval: FK → User(null=True)
    target_priest_acknowledgment: FK → User(null=True)
    transfer_letter_file: FileField(null=True)  # stocké MinIO
    completed_at: DateTimeField(null=True)
```

### 5.4 Création comptes clergé — deux modes

**Mode Invitation** (recommandé) :
```python
class ClergicalInvitation(models.Model):
    invited_by: FK → User
    target_pastoral_role: CharField(choices=PastoralRole.choices)
    target_parish: FK → Parish(null=True)
    target_diocese: FK → Diocese(null=True)
    token: UUIDField(unique=True)
    used: BooleanField(default=False)
    expires_at: DateTimeField  # 7 jours
```

**Mode Auto-déclaration** :
```python
class PastoralRoleRequest(models.Model):
    requester: FK → User
    requested_role: CharField(choices=PastoralRole.choices)
    claimed_parish: FK → Parish(null=True)
    claimed_diocese: FK → Diocese(null=True)
    supporting_document: FileField(null=True)
    status: CharField(choices=['pending', 'approved', 'rejected'])
    reviewed_by: FK → User(null=True)
```

---

## 6. Module — Liturgie du Jour & Liturgie des Heures

### 6.1 Sources AELF

```python
AELF_ENDPOINTS = {
    'messe':    '/v1/messes/{day}/{month}/{year}/fr',
    'laudes':   '/v1/offices/laudes/{day}/{month}/{year}/fr',
    'tierce':   '/v1/offices/tierce/{day}/{month}/{year}/fr',
    'sexte':    '/v1/offices/sexte/{day}/{month}/{year}/fr',
    'none':     '/v1/offices/none/{day}/{month}/{year}/fr',
    'vepres':   '/v1/offices/vepres/{day}/{month}/{year}/fr',
    'complies': '/v1/offices/complies/{day}/{month}/{year}/fr',
    'lectures': '/v1/offices/lectures/{day}/{month}/{year}/fr',  # Matines
}
# Fetch quotidien via Celery Beat à 02:00 UTC
# Cache Redis TTL = 23h
# Fallback: données du jour précédent si AELF inaccessible
```

### 6.2 Logique d'heure active

```python
LITURGICAL_HOURS_SCHEDULE = [
    ((5, 9),   'laudes'),
    ((9, 12),  'tierce'),
    ((12, 14), 'sexte'),
    ((14, 18), 'none'),
    ((18, 21), 'vepres'),
    ((21, 24), 'complies'),
    ((0, 5),   'lectures'),
]

def get_active_hour(local_hour: int) -> str:
    for (start, end), hour_name in LITURGICAL_HOURS_SCHEDULE:
        if start <= local_hour < end:
            return hour_name
    return 'lectures'
```

### 6.3 Réflexion Pastorale

```python
class PastoralReflection(models.Model):
    author: FK → User
    date: DateField               # date liturgique — auto = today à la création
    anchor_verse: TextField(blank=True)
    body: TextField(max_length=500)
    scope: ContentScope
    scope_id: IntegerField
    published: BooleanField(default=True)
    created_at: DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('author', 'date')  # Une seule réflexion par jour par auteur
```

### 6.4 Permissions

| Action | FIDELE | RELIGIEUX | DIACRE | PRETRE | EVEQUE | ARCHEVEQUE |
|---|---|---|---|---|---|---|
| Voir lectures messe | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Voir Liturgie des Heures | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Configurer rappels Heures | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Voir réflexion du curé | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Publier réflexion | ❌ | ❌ | ❌ | paroisse | diocèse | province |
| Vue lectures semaine à venir | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |

---

## 7. Module — Bible & Chapelet

### 7.1 Bible — Modes

#### Mode Prière (tous)
- Lecture verset/verset, favoris, partage deep link, recherche sémantique (pgvector existant)

#### Mode Lectio Divina (tous, conçu pour clergé/religieux)

```python
class LectioDivinaSession(models.Model):
    user: FK → User
    book: CharField
    chapter: IntegerField
    verse_start: IntegerField
    verse_end: IntegerField
    date: DateField
    # Étapes
    meditatio_word: CharField(max_length=100, blank=True)
    oratio_text: TextField(blank=True)   # PRIVÉ — jamais partagé
    duration_minutes: IntegerField(null=True)
    completed: BooleanField(default=False)
    created_at: DateTimeField
```

4 étapes séquentielles : Lectio → Meditatio (timer) → Oratio (zone texte privée) → Contemplatio (timer + son optionnel)

#### Notes d'homélie

```python
class HomilieNote(models.Model):
    author: FK → User   # DIACRE, PRETRE, EVEQUE, ARCHEVEQUE
    book: CharField
    chapter: IntegerField
    body: TextField
    linked_liturgical_date: DateField(null=True)
    created_at: DateTimeField
    updated_at: DateTimeField
    # PRIVÉ — jamais visible par d'autres
```

### 7.2 Parcours de lecture

```python
class ReadingPlan(models.Model):
    creator: FK → User
    title: CharField(max_length=200)
    scope: ContentScope
    scope_id: IntegerField
    duration_days: IntegerField
    entries: JSONField  # [{day:1, book:'Jn', chapter:1, verse_start:1, verse_end:18}]
    is_active: BooleanField(default=True)

class ReadingPlanEnrollment(models.Model):
    user: FK → User
    plan: FK → ReadingPlan
    started_at: DateField
    current_day: IntegerField(default=1)
    completed: BooleanField(default=False)
    class Meta:
        unique_together = ('user', 'plan')
```

### 7.3 Chapelet

#### Mystères par jour

```python
MYSTERIES_BY_WEEKDAY = {
    0: 'joyeux',       # Lundi
    1: 'douloureux',   # Mardi
    2: 'glorieux',     # Mercredi
    3: 'lumineux',     # Jeudi
    4: 'douloureux',   # Vendredi
    5: 'joyeux',       # Samedi
    6: 'glorieux',     # Dimanche
}
```

#### Chapelet Communautaire (WebSocket)

```python
class CommunityRosary(models.Model):
    host: FK → User
    parish: FK → Parish
    started_at: DateTimeField
    current_mystery_index: IntegerField(default=0)  # 0-4
    current_prayer_index: IntegerField(default=0)   # position dans le mystère
    is_active: BooleanField(default=True)
    participants_count: IntegerField(default=0)
    # WebSocket group: f"rosary_{id}"
```

#### Intentions de prière (chapelet)

```python
class PrayerIntention(models.Model):
    author: FK → User
    text: TextField(max_length=300)
    is_public: BooleanField(default=False)
    parish: FK → Parish
    created_at: DateTimeField
    expires_at: DateField  # auto = created_at + 30 jours
```

### 7.4 Permissions

| Action | FIDELE | RELIGIEUX | DIACRE | PRETRE | EVEQUE | ARCHEVEQUE |
|---|---|---|---|---|---|---|
| Mode Prière Bible | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Mode Lectio Divina | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Notes d'homélie | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| Créer parcours | ❌ | ❌ | ❌ | paroisse | diocèse | province |
| Initier chapelet communautaire | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Rejoindre chapelet | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Collecter intentions paroisse | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |

---

## 8. Module — Messagerie & Allo-Prêtre

### 8.1 Architecture

```
Allo-Prêtre  →  Couche DÉCOUVERTE  (disponibilité, services, contact)
Messagerie   →  Couche COMMUNICATION (conversation chiffrée)
```

### 8.2 Disponibilité ministre

```python
class MinisterAvailability(models.Model):
    minister: FK → User   # PRETRE, DIACRE, RELIGIEUX
    pastoral_chat_open: BooleanField(default=False)
    confession_schedule: JSONField(default=list)
    # [{day: 'tuesday', start: '17:00', end: '18:00'}]
    appointment_available: BooleanField(default=False)
    home_visit_available: BooleanField(default=False)
    home_visit_note: CharField(max_length=200, blank=True)
    special_status: CharField(choices=['available','retreat','vacation','unavailable'], default='available')
    special_status_until: DateField(null=True)
    special_status_message: CharField(max_length=200, blank=True)
```

### 8.3 Conversations pastorales

```python
class ConversationType(models.TextChoices):
    SIMPLE_QUESTION     = 'simple_question'      # Réponse < 48h
    SPIRITUAL_DIRECTION = 'spiritual_direction'  # Accompagnement long terme
    URGENT              = 'urgent'               # Priorité haute dans dashboard

class PastoralConversation(models.Model):
    fidele: FK → User
    minister: FK → User
    conversation_type: ConversationType
    status: CharField(choices=['active', 'closed', 'archived'])
    created_at: DateTimeField
    last_message_at: DateTimeField
    purge_at: DateTimeField  # = created_at + SystemConfig('messaging.purge_days')

class PastoralMessage(models.Model):
    conversation: FK → PastoralConversation
    sender: FK → User
    encrypted_content: TextField   # Fernet E2E
    sent_at: DateTimeField
    read_at: DateTimeField(null=True)
```

### 8.4 Communication inter-clergé

```python
class ClergicalMessage(models.Model):
    sender: FK → User
    recipients: M2M → User
    recipient_scope: CharField(choices=[
        'individual', 'parish_clergy', 'diocese_clergy', 'province_bishops'
    ])
    subject: CharField(max_length=200)
    body: TextField
    sent_at: DateTimeField

# Règles d'envoi :
# ARCHEVEQUE → province_bishops (tous ses évêques)
# EVEQUE     → diocese_clergy (tous ses prêtres) | individual
# PRETRE     → parish_clergy (ses diacres) | individual (autres prêtres)
# DIACRE     → individual (son prêtre uniquement)
```

### 8.5 Permissions

| Action | FIDELE | RELIGIEUX | DIACRE | PRETRE | EVEQUE | ARCHEVEQUE |
|---|---|---|---|---|---|---|
| Initier conversation pastorale | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| Recevoir + répondre (pastorale) | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ |
| Initier (pasteur → fidèle) | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ |
| Gérer disponibilités | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ |
| Dashboard conversations | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ |
| Communication inter-clergé | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| Vue activité diocèse (nb conversations actives) | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| Alerte prêtres inactifs (+30j) | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |

---

## 9. Module — Actus

### 9.1 Modèle

```python
class ContentType(models.TextChoices):
    ANNOUNCEMENT    = 'announcement'     # 300 chars max
    ARTICLE         = 'article'          # long format
    PASTORAL_LETTER = 'pastoral_letter'  # formel, EVEQUE+

class ActusContent(models.Model):
    author: FK → User
    content_type: ContentType
    title: CharField(max_length=200, blank=True)
    body: TextField
    scope: ContentScope
    scope_id: IntegerField
    status: CharField(choices=['draft', 'published', 'unpublished'])
    is_validated: BooleanField(default=False)
    validated_by: FK → User(null=True)
    published_at: DateTimeField(null=True)
    created_at: DateTimeField

class ActusReaction(models.Model):
    content: FK → ActusContent
    user: FK → User
    reaction_type: CharField(choices=['pray', 'amen', 'attend'])
    created_at: DateTimeField
    class Meta:
        unique_together = ('content', 'user', 'reaction_type')

class ContentBoost(models.Model):
    content: FK → ActusContent
    boosted_by: FK → User
    target_scope: ContentScope
    target_scope_id: IntegerField
    boosted_at: DateTimeField
```

### 9.2 Règles de workflow

```python
PUBLICATION_RULES = {
    # (content_type, pastoral_role) → peut publier directement ?
    (ContentType.ANNOUNCEMENT,    PastoralRole.DIACRE):     'draft_only',
    (ContentType.ANNOUNCEMENT,    PastoralRole.PRETRE):     'direct',
    (ContentType.ARTICLE,         PastoralRole.DIACRE):     'draft_only',
    (ContentType.ARTICLE,         PastoralRole.PRETRE):     'direct',
    (ContentType.ARTICLE,         PastoralRole.EVEQUE):     'direct',
    (ContentType.PASTORAL_LETTER, PastoralRole.EVEQUE):     'direct',
    (ContentType.PASTORAL_LETTER, PastoralRole.ARCHEVEQUE): 'direct',
}
# Brouillons DIACRE → soumis au PRETRE pour validation avant publication
```

### 9.3 Fil de contenu

```python
def get_actus_feed(user, page=1, page_size=20):
    scope = user.get_scope_ids()
    return ActusContent.objects.filter(
        status='published'
    ).filter(
        Q(scope=ContentScope.GLOBAL) |
        Q(scope=ContentScope.PROVINCE, scope_id=scope['province_id']) |
        Q(scope=ContentScope.DIOCESE,  scope_id=scope['diocese_id']) |
        Q(scope=ContentScope.PARISH,   scope_id__in=scope['parish_ids'])
    ).order_by('-published_at').select_related('author')
```

### 9.4 Permissions

| Action | FIDELE | RELIGIEUX | DIACRE | PRETRE | EVEQUE | ARCHEVEQUE | SUPER_ADMIN |
|---|---|---|---|---|---|---|---|
| Lire + réagir | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Créer brouillon | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Valider brouillon diacre | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| Publier ANNOUNCEMENT | ❌ | ❌ | brouillon | paroisse | diocèse | province | global |
| Publier ARTICLE | ❌ | ❌ | brouillon | paroisse | diocèse | province | global |
| Publier PASTORAL_LETTER | ❌ | ❌ | ❌ | ❌ | diocèse | province | global |
| Boost diocésain | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| Boost provincial | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ |
| Dépublier (modération) | ❌ | ❌ | ❌ | son contenu | son diocèse | sa province | tout |

---

## 10. Module — Documents Officiels

### 10.1 Types

```python
class DocumentType(models.TextChoices):
    BAPTISM_CERT      = 'baptism_cert'
    COMMUNION_CERT    = 'communion_cert'
    CONFIRMATION_CERT = 'confirmation_cert'
    MARRIAGE_CERT     = 'marriage_cert'
    BURIAL_CERT       = 'burial_cert'
    RECOMMENDATION    = 'recommendation'
    TRANSFER          = 'transfer'
    ORDINATION_CERT   = 'ordination_cert'  # EVEQUE uniquement
```

### 10.2 SLA et escalade

```python
SLA_DAYS = {
    DocumentType.BAPTISM_CERT:      3,
    DocumentType.COMMUNION_CERT:    3,
    DocumentType.CONFIRMATION_CERT: 5,
    DocumentType.MARRIAGE_CERT:     5,
    DocumentType.BURIAL_CERT:       3,
    DocumentType.RECOMMENDATION:    5,
    DocumentType.TRANSFER:          5,
    DocumentType.ORDINATION_CERT:  10,
}

ESCALATION_RULES = {
    'to_priest':  lambda sla_days: sla_days,      # J+SLA → notify prêtre
    'to_bishop':  lambda sla_days: sla_days + 2,  # J+SLA+2 → notify évêque
}
# Celery Beat à 08:00 UTC pour vérifier les dépassements
```

### 10.3 Modèle

```python
class DocumentStatus(models.TextChoices):
    SUBMITTED          = 'submitted'
    UNDER_VERIFICATION = 'under_verification'
    INFO_REQUESTED     = 'info_requested'
    VALIDATED          = 'validated'
    DOCUMENT_DEPOSITED = 'document_deposited'
    REJECTED           = 'rejected'

class DocumentRequest(models.Model):
    requester: FK → User
    document_type: DocumentType
    target_parish: FK → Parish
    status: DocumentStatus
    submitted_at: DateTimeField
    # Workflow 3 niveaux
    level1_handler: FK → User(null=True)   # DIACRE ou PARISH_ADMIN
    level2_signer: FK → User(null=True)    # PRETRE
    level3_approver: FK → User(null=True)  # EVEQUE si requis
    # Coffre-fort
    final_document_file: FileField(null=True)
    delivered_at: DateTimeField(null=True)
    stored_in_vault: BooleanField(default=False)
    # SLA
    sla_deadline: DateTimeField
    escalated_to_priest_at: DateTimeField(null=True)
    escalated_to_bishop_at: DateTimeField(null=True)

class DocumentVault(models.Model):
    owner: FK → User
    document_request: FK → DocumentRequest
    document_type: DocumentType
    file_path: CharField   # chemin MinIO
    issued_by: FK → Parish
    issued_at: DateField
    created_at: DateTimeField

# Signal: quand status → document_deposited ET final_document_file renseigné
# → créer automatiquement DocumentVault
```

### 10.4 Permissions

| Action | FIDELE | DIACRE/ADMIN | PRETRE | EVEQUE | ARCHEVEQUE | SUPER_ADMIN |
|---|---|---|---|---|---|---|
| Soumettre demande | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Suivre ses demandes | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Coffre-fort personnel | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Traitement Niv.1 | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Signer Niv.2 | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ |
| Documents diocésains Niv.3 | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ |
| Métriques diocèse | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| Vue toutes demandes (audit) | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

---

## 11. Module — Agenda & Événements

### 11.1 Calendrier liturgique automatique

Données calculées côté backend depuis les rules liturgiques + AELF. Aucune saisie manuelle.

```python
def get_liturgical_context(date: date) -> dict:
    return {
        'season': compute_liturgical_season(date),  # Avent, Noël, Temps Ordinaire, Carême, Pâques, Temps Pascal
        'feast_day': get_feast_day(date),
        'color': compute_liturgical_color(date),    # violet, blanc, rouge, vert
        'rank': compute_feast_rank(date),           # Solennité, Fête, Mémoire
    }
```

### 11.2 Événements pastoraux

```python
class EventType(models.TextChoices):
    LITURGICAL = 'liturgical'
    PASTORAL   = 'pastoral'
    FORMATION  = 'formation'
    SOCIAL     = 'social'
    SACRAMENT  = 'sacrament'

class PastoralEvent(models.Model):
    creator: FK → User
    title: CharField(max_length=200)
    event_type: EventType
    description: TextField(blank=True)
    start_datetime: DateTimeField
    end_datetime: DateTimeField
    location: CharField(max_length=300)
    scope: ContentScope
    scope_id: IntegerField
    requires_registration: BooleanField(default=False)
    max_participants: IntegerField(null=True)
    linked_tv_stream: FK → VideoContent(null=True)
    # Auto-génère une Annonce dans Actus à la création
    linked_actus: FK → ActusContent(null=True)

class EventRegistration(models.Model):
    event: FK → PastoralEvent
    user: FK → User
    registered_at: DateTimeField
    class Meta:
        unique_together = ('event', 'user')
```

### 11.3 Connexions inter-modules

| Module | Trigger | Action |
|---|---|---|
| Actus | Événement créé | Génère automatiquement une `ANNOUNCEMENT` liée |
| Jangu Bi TV | `linked_tv_stream` renseigné | L'événement est lié au live |
| Notifications | Événement à J-1 et J-0 H-1 | Rappels aux inscrits |

### 11.4 Permissions

| Action | FIDELE | DIACRE | PRETRE | EVEQUE | ARCHEVEQUE |
|---|---|---|---|---|---|
| Voir + s'inscrire | ✅ | ✅ | ✅ | ✅ | ✅ |
| Créer événement | ❌ | paroisse | paroisse | diocèse | province |
| Voir liste inscrits | ❌ | ✅ | ✅ | ✅ | ✅ |
| Annuler événement | ❌ | son événement | son événement | son diocèse | sa province |

---

## 12. Module — Intentions de Messe

### 12.1 Distinctions

- **Intention de messe** ≠ Intention de prière chapelet (Module 7)
- **Intention de messe** ≠ Don générique (Module 13)
- L'offrande associée EST référencée dans la table DonationType

### 12.2 Modèle

```python
class MassIntentionType(models.TextChoices):
    FOR_DECEASED  = 'for_deceased'
    FOR_LIVING    = 'for_living'
    FOR_OCCASION  = 'for_occasion'
    FOR_COMMUNITY = 'for_community'

class MassIntention(models.Model):
    requester: FK → User
    priest: FK → User
    parish: FK → Parish
    intention_type: MassIntentionType
    beneficiary_name: CharField(max_length=200)
    description: TextField(max_length=500)
    preferred_date: DateField(null=True)
    confirmed_date: DateField(null=True)
    status: CharField(choices=[
        'pending',         # Soumis, en attente prêtre
        'accepted',        # Prêtre accepte la date proposée
        'date_proposed',   # Prêtre propose une autre date
        'confirmed',       # Fidèle confirme la nouvelle date
        'celebrated',      # Prêtre marque comme célébrée
        'declined',        # Prêtre décline
    ])
    offering_amount: DecimalField(decimal_places=0, null=True)
    offering_paid: BooleanField(default=False)
    offering_transaction: FK → DonationTransaction(null=True)
    celebrated_at: DateTimeField(null=True)
    receipt_issued: BooleanField(default=False)
    created_at: DateTimeField
```

### 12.3 Workflow

```
FIDELE soumet (type + bénéficiaire + date souhaitée + offrande optionnelle)
  ↓
PRETRE reçoit dans son dashboard (tab "Intentions")
  ↓ [accepte] → status=accepted → fidèle notifié
  ↓ [propose date] → status=date_proposed → fidèle notifié
        ↓ [fidèle confirme] → status=confirmed
  ↓
Le jour J → PRETRE marque celebrated → fidèle notifié → reçu généré si offrande
```

### 12.4 Permissions

| Action | FIDELE | DIACRE | PRETRE | EVEQUE | SUPER_ADMIN |
|---|---|---|---|---|---|
| Soumettre intention | ✅ | ✅ | ❌ | ❌ | ❌ |
| Recevoir + traiter | ❌ | ❌ | ✅ | ❌ | ❌ |
| Voir intentions paroisse | ❌ | ✅ | ✅ | ✅ | ✅ |
| Métriques diocèse | ❌ | ❌ | ❌ | ✅ | ✅ |

---

## 13. Module — Dons & Quêtes

### 13.1 Table de référence (gérée par SUPER_ADMIN)

```python
class DonationType(models.Model):
    code: CharField(unique=True)
    label: CharField(max_length=200)
    description: TextField
    beneficiary_level: CharField(choices=['parish', 'diocese', 'province', 'platform'])
    recurrence: CharField(choices=['weekly', 'annual', 'one_time', 'campaign'])
    is_active: BooleanField(default=True)

# Données initiales :
INITIAL_DONATION_TYPES = [
    {'code': 'sunday_collection',        'label': 'Quête dominicale',          'beneficiary_level': 'parish',   'recurrence': 'weekly'},
    {'code': 'church_tithe',             'label': 'Denier de l\'Église',        'beneficiary_level': 'diocese',  'recurrence': 'annual'},
    {'code': 'mass_intention_offering',  'label': 'Offrande intention de messe','beneficiary_level': 'parish',   'recurrence': 'one_time'},
    {'code': 'special_project',          'label': 'Projet spécial',             'beneficiary_level': 'parish',   'recurrence': 'campaign'},
    {'code': 'free_donation',            'label': 'Don libre',                  'beneficiary_level': 'parish',   'recurrence': 'one_time'},
]
```

### 13.2 Campagne de don

```python
class DonationCampaign(models.Model):
    creator: FK → User
    donation_type: FK → DonationType
    title: CharField(max_length=200)
    description: TextField
    target_amount: DecimalField(null=True)
    current_amount: DecimalField(default=0)
    scope: ContentScope
    scope_id: IntegerField
    start_date: DateField
    end_date: DateField(null=True)
    is_active: BooleanField(default=True)
    # Signal: recalcule current_amount à chaque DonationTransaction completed
```

### 13.3 Transaction

```python
class PaymentProvider(models.TextChoices):
    WAVE         = 'wave'
    ORANGE_MONEY = 'orange_money'
    FREE_MONEY   = 'free_money'

class DonationTransaction(models.Model):
    donor: FK → User
    campaign: FK → DonationCampaign(null=True)
    donation_type: FK → DonationType
    amount: DecimalField(decimal_places=0)
    currency: CharField(default='XOF')
    payment_provider: PaymentProvider
    provider_transaction_id: CharField(unique=True)
    status: CharField(choices=['pending', 'completed', 'failed', 'refunded'])
    receipt_number: CharField(unique=True)  # auto-généré
    created_at: DateTimeField
    completed_at: DateTimeField(null=True)
```

### 13.4 Permissions

| Action | FIDELE | PRETRE | EVEQUE | ARCHEVEQUE | SUPER_ADMIN |
|---|---|---|---|---|---|
| Faire un don | ✅ | ✅ | ✅ | ✅ | ❌ |
| Historique + reçu | ✅ | ✅ | ✅ | ✅ | ❌ |
| Créer campagne paroisse | ❌ | ✅ | ✅ | ✅ | ✅ |
| Créer campagne diocèse | ❌ | ❌ | ✅ | ✅ | ✅ |
| Tableau dons paroisse | ❌ | ✅ | ✅ | ✅ | ✅ |
| Tableau dons diocèse | ❌ | ❌ | ✅ | ✅ | ✅ |
| Tableau dons province | ❌ | ❌ | ❌ | ✅ | ✅ |
| Gérer DonationType (ref table) | ❌ | ❌ | ❌ | ❌ | ✅ |
| Activer Denier de l'Église | ❌ | ❌ | ✅ | ✅ | ✅ |

---

## 14. Module — Jangu Bi TV

### 14.1 Catégories

```python
class VideoCategory(models.TextChoices):
    MASS        = 'mass'        # Public
    HOMILY      = 'homily'      # Public
    CATECHESIS  = 'catechesis'  # Public
    EVENT       = 'event'       # Public
    TESTIMONY   = 'testimony'   # Public (après validation admin)
    FORMATION   = 'formation'   # RESTREINT — clergé uniquement
```

### 14.2 Modèle

```python
class VideoContent(models.Model):
    creator: FK → User
    title: CharField(max_length=200)
    youtube_url: URLField
    youtube_id: CharField(max_length=50)
    category: VideoCategory
    description: TextField(blank=True)
    scope: ContentScope
    scope_id: IntegerField
    is_live: BooleanField(default=False)
    is_pinned_live: BooleanField(default=False)
    live_scheduled_at: DateTimeField(null=True)
    status: CharField(choices=['draft', 'published', 'unpublished'])
    requires_validation: BooleanField(default=False)  # True pour TESTIMONY
    validated_by: FK → User(null=True)
    views_count: IntegerField(default=0)
    published_at: DateTimeField(null=True)
```

### 14.3 Fil vidéo

```python
def get_tv_feed(user):
    qs = VideoContent.objects.filter(status='published')
    # Restriction Formation
    if not user.has_pastoral_role():
        qs = qs.exclude(category=VideoCategory.FORMATION)
    return get_scoped_queryset(user, qs).order_by(
        '-is_pinned_live', '-published_at'
    )
```

### 14.4 Workflow live

```
PRETRE annonce live (titre, catégorie, date/heure)
  ↓
J-24h → Notification badge aux fidèles concernés
J-15min → Notification PUSH aux fidèles concernés
  ↓
Début live → is_live=True, is_pinned_live=True
  ↓
Fin live → is_live=False, is_pinned_live=False → archivé en replay
```

### 14.5 Permissions

| Action | FIDELE | RELIGIEUX | DIACRE | PRETRE | EVEQUE | ARCHEVEQUE | SUPER_ADMIN |
|---|---|---|---|---|---|---|---|
| Voir vidéos publiques | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Voir Formation | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Publier vidéo | ❌ | ❌ | paroisse | paroisse | diocèse | province | global |
| Planifier live | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| Valider témoignages | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| Analytics vidéos | ❌ | ❌ | ses vidéos | ses vidéos | son diocèse | sa province | tout |
| Gérer Formation | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

---

## 15. Système de notifications

### 15.1 Types et priorités

```python
class NotificationType(models.TextChoices):
    LITURGICAL = 'liturgical'   # Évangile du jour, rappels Heures
    PASTORAL   = 'pastoral'     # Message prêtre, réponse intention
    EDITORIAL  = 'editorial'    # Nouvel article, lettre pastorale
    DOCUMENT   = 'document'     # Changement statut
    EVENT      = 'event'        # Rappel événement, live TV
    DONATION   = 'donation'     # Confirmation don, nouvelle campagne
    SYSTEM     = 'system'       # Validation compte, transfert paroissial

class NotificationPriority(models.TextChoices):
    HIGH   = 'high'    # Push immédiat — peut contourner anti-flood si urgence
    MEDIUM = 'medium'  # Push si conditions remplies
    LOW    = 'low'     # Badge uniquement si app ouverte récemment
```

### 15.2 Règles globales

```python
NOTIFICATION_GLOBAL_RULES = {
    'silence_start':          22,    # 22h00
    'silence_end':             6,    # 06h00
    'anti_flood_minutes':    120,    # 2h min entre même type
    'recent_open_minutes':    60,    # si app ouverte < 1h → badge only
    'daily_push_max':          5,    # max 5 push/jour tous types
}
# Exception: HIGH priority → contourne silence nocturne et anti-flood
```

### 15.3 Defaults par rôle

| Type | FIDELE | RELIGIEUX | DIACRE | PRETRE | EVEQUE | ARCHEVEQUE |
|---|---|---|---|---|---|---|
| LITURGICAL | push | push | push | push | push | push |
| PASTORAL | push | push | push | push | silent | silent |
| EDITORIAL | silent | silent | silent | push | push | push |
| DOCUMENT | push | — | push | push | silent | silent |
| EVENT | silent | silent | push | push | push | push |
| DONATION | silent | — | — | push | push | push |
| SYSTEM | push | push | push | push | push | push |

`push` = notification active | `silent` = badge uniquement | `—` = désactivé

### 15.4 Statut spécial clergé

```python
class SpecialStatus(models.TextChoices):
    AVAILABLE = 'available'
    RETREAT   = 'retreat'    # Toutes notifs suspendues sauf SYSTEM
    VACATION  = 'vacation'   # Réduit au minimum

# Effets de RETREAT :
# - MinisterAvailability.special_status = 'unavailable'
# - Allo-Prêtre affiche "Indisponible jusqu'au [date]"
# - Auto-reply sur conversations pastorales
# - Suspens toutes notifications sauf SYSTEM
```

---

## 16. Matrice des permissions complète

| Fonctionnalité | FIDELE | RELIGIEUX | DIACRE | PRETRE | EVEQUE | ARCHEVEQUE | SUPER_ADMIN |
|---|---|---|---|---|---|---|---|
| **LITURGIE** | | | | | | | |
| Lectures messe | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Liturgie des Heures | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Publier réflexion | ❌ | ❌ | ❌ | paroisse | diocèse | province | ❌ |
| **BIBLE** | | | | | | | |
| Mode Prière | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Lectio Divina | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Notes homélie | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Créer parcours | ❌ | ❌ | ❌ | paroisse | diocèse | province | global |
| **CHAPELET** | | | | | | | |
| Chapelet guidé | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Initier communautaire | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Collecter intentions | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ |
| **MESSAGERIE** | | | | | | | |
| Initier pastorale | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| Recevoir pastorale | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| Inter-clergé | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ |
| **ACTUS** | | | | | | | |
| Lire + réagir | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Publier ANNOUNCEMENT | ❌ | ❌ | brouillon | paroisse | diocèse | province | global |
| Publier ARTICLE | ❌ | ❌ | brouillon | paroisse | diocèse | province | global |
| Publier PASTORAL_LETTER | ❌ | ❌ | ❌ | ❌ | diocèse | province | global |
| Modérer (dépublier) | ❌ | ❌ | ❌ | son contenu | son diocèse | sa province | tout |
| **DOCUMENTS** | | | | | | | |
| Soumettre | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Coffre-fort | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Traitement Niv.1 | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Signature Niv.2 | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ |
| Diocésain Niv.3 | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ |
| Audit global | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **AGENDA** | | | | | | | |
| Voir + s'inscrire | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Créer événement | ❌ | ❌ | paroisse | paroisse | diocèse | province | global |
| **INTENTIONS MESSE** | | | | | | | |
| Soumettre | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Recevoir + traiter | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ |
| **DONS** | | | | | | | |
| Donner | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Créer campagne | ❌ | ❌ | ❌ | paroisse | diocèse | province | global |
| Gérer DonationType | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **TV** | | | | | | | |
| Vidéos publiques | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Formation | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Publier vidéo | ❌ | ❌ | paroisse | paroisse | diocèse | province | global |
| Planifier live | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| Gérer Formation | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **SUPER ADMIN** | | | | | | | |
| Structure territoriale (CRUD) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Config système | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Gestion utilisateurs | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Analytics globales | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

---

## 17. Dashboards par rôle

### FIDELE
```
Liturgie     → Évangile du jour + réflexion du curé
Documents    → Demandes en cours + statut
Actualités   → 3 dernières actus de sa paroisse
Événements   → Prochains événements paroissiaux
```

### PRETRE
```
Urgent       → Documents en attente signature (count+list)
             → Conversations pastorales URGENT non lues
             → Intentions de messe en attente
À traiter    → Documents under_verification (count)
             → Conversations actives ouvertes (count)
Liturgie     → Prochaine Heure de l'Office
             → Lectures semaine à venir (compact)
Paroisse     → Fidèles actifs cette semaine
             → Dernière actus publiée + engagement
             → Prochains événements
```

### EVEQUE
```
Alertes      → Documents en retard escalade (count)
             → Prêtres inactifs > 30j (count+list)
Diocèse      → Prêtres actifs / total
             → Documents traités cette semaine
             → Fidèles connectés cette semaine
Communication→ Messages inter-clergé non lus
             → Dernière lettre pastorale + vues
Liturgie     → Prochaine Heure de l'Office
```

### ARCHEVEQUE
```
Province     → Vue par diocèse (évêque + dernier contact + activité)
Communication→ Messages avec évêques non lus
Liturgie     → Prochaine Heure de l'Office
```

### SUPER_ADMIN
```
Santé        → Utilisateurs actifs J/J-7/J-30
             → Rétention J30/J90
             → Paroisses actives / total
File valid.  → Comptes clergé en attente
             → Demandes de rôle non traitées
             → Transferts bloqués > 7j
Modération   → Signalements non traités
             → Contenus publiés par scope (aujourd'hui)
Finance      → Volume XOF par provider
             → Taux succès paiements
             → Campagnes actives
```

---

## 18. Assistants & Délégation

```python
class ClergicalAssistant(models.Model):
    principal: FK → User   # PRETRE ou EVEQUE
    assistant: FK → User   # tout utilisateur désigné
    granted_permissions: JSONField  # liste de codes
    valid_from: DateField
    valid_until: DateField(null=True)
    is_active: BooleanField(default=True)

DELEGABLE_PERMISSIONS = [
    'documents.process',      # Traiter demandes Niv.1
    'actus.publish',          # Publier au nom du principal
    'events.manage',          # Créer/modifier événements
    'tv.publish',             # Publier vidéos TV
    'allo_pretre.manage',     # Gérer disponibilités
    'intentions.manage',      # Voir + gérer intentions de messe
    'donations.view',         # Voir tableau de bord dons
]

NON_DELEGABLE_PERMISSIONS = [
    'documents.sign',           # JAMAIS
    'conversations.pastoral',   # JAMAIS — chiffrement E2E
    'clergy.validate',          # JAMAIS
    'donations.withdraw',       # JAMAIS
    'system.config',            # JAMAIS
]
```

---

## 19. Priorités de développement

| Priorité | Feature | Impact rétention | Complexité | Bloquant |
|---|---|---|---|---|
| 🔴 P1 | Modèle User→Parish→Diocese→Province (migration IntegerField) | Critique | Haute | Tout le reste |
| 🔴 P1 | Liturgie des Heures (AELF endpoints + logique heure active) | Très haute — clergé quotidien | Moyenne | Non |
| 🔴 P2 | Comptes clergé — invitation + validation hiérarchique | Critique | Moyenne | Clergé sur plateforme |
| 🔴 P2 | Allo-Prêtre + Messagerie (disponibilités + conversations typées) | Haute | Haute | Non |
| 🔴 P2 | Actus — interface publication + 3 types + fil scopé | Haute — remplace WhatsApp | Moyenne | Non |
| 🟡 P3 | Documents — coffre-fort + 3 niveaux + transfert paroissial | Haute | Haute | Modèle territorial P1 |
| 🟡 P3 | Réflexion pastorale (module liturgie) | Moyenne | Faible | Non |
| 🟡 P4 | Bible — mode Lectio Divina | Haute clergé/religieux | Moyenne | Non |
| 🟡 P4 | Agenda & Événements | Utilité hebdomadaire | Moyenne | Non |
| 🟡 P4 | Intentions de Messe | Pastoral + financier | Moyenne | Dons P5 |
| 🟢 P5 | Dons (Wave, Orange Money, Free Money) | Haute LT | Très haute | Non |
| 🟢 P5 | Chapelet communautaire + intentions | Communautaire | Haute | Non |
| 🟢 P6 | Jangu Bi TV — publication clergé + Formation | Éditoriale | Faible | Non |
| 🟢 P6 | Super Admin dashboard complet | Opérationnel | Moyenne | Non |
| ⏸️ — | Assistant Spirituel RAG | — | — | Stand-by |

---

## Notes d'implémentation critiques

### Migration `primary_parish`

```python
# AVANT (à supprimer)
primary_parish: IntegerField  # placeholder

# APRÈS (à implémenter)
primary_parish: FK → Parish(null=True, on_delete=SET_NULL)
diocese: FK → Diocese(null=True, on_delete=SET_NULL)
province: FK → Province(null=True, on_delete=SET_NULL)
```

Cette migration est le **prérequis absolu** de tout le système de scoping. Sans elle, aucun filtrage de contenu par appartenance n'est possible.

### API AELF — Cache strategy

```python
# Redis cache key pattern
AELF_CACHE_KEYS = {
    'messe':    'aelf:messe:{YYYY-MM-DD}',
    'laudes':   'aelf:laudes:{YYYY-MM-DD}',
    # ...
}
AELF_CACHE_TTL = 23 * 3600  # 23 heures

# Fallback strategy
def get_liturgical_content(office: str, date: date):
    cache_key = f'aelf:{office}:{date.isoformat()}'
    content = cache.get(cache_key)
    if not content:
        content = cache.get(f'aelf:{office}:{(date - timedelta(days=1)).isoformat()}')
        if content:
            content['_fallback'] = True
    return content
```

### HTML sanitization AELF

Conserver `isomorphic-dompurify` côté frontend. Les champs `refrain_psalmique`, `verset_evangile` et `intro_lue` contiennent du HTML provenant d'AELF.

---

*Document généré à partir de la session de conception architecturale Jangu Bi — Numerisen — Mai 2025*  
*Usage : développement interne / Claude Code — Ne pas diffuser*
