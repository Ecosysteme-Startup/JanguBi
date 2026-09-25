"""
Management command: seed_demo

Peuple la base de données avec des données de démonstration réalistes pour
la plateforme Jàngu Bi (communauté catholique sénégalaise), au modèle
MULTI-APPARTENANCE (Lot 2).

Prérequis : exécuter `seed_senegal` d'abord (Province/Diocese/Parish + église
principale par paroisse).

Usage :
    docker compose exec django python manage.py seed_senegal
    docker compose exec django python manage.py seed_demo
    docker compose exec django python manage.py seed_demo --reset

Idempotent : peut être exécuté plusieurs fois sans dupliquer les données.

Données incarnant le GOLDEN-PATH :
- Aminata Fall est membre de DEUX églises de diocèses différents (Dakar +
  Thiès) via Membership (PAS Profile.primary_parish en direct : le signal dérive
  diocèse/province/primary_parish et complète l'onboarding par le vrai chemin).
- Le clergé/les admins ont une autorité réelle via RoleAssignment.
- Une demande de document cible une paroisse NON-membre (registre), + une
  orpheline legacy (target_parish NULL).
- Articles scopés église/paroisse/diocèse/global → fil agrégé varié.
- Dons espèces étiquetés à une église (PENDING/CONFIRMED + anonymes).
- Événements (scopes variés) + intentions de messe.
"""

import datetime
import uuid

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

# ─── Identifiants de test ─────────────────────────────────────────────────────

DEMO_PASSWORD = "Jangu2024!"

EMAIL_SUPER_ADMIN = "admin@jangubidev.sn"
EMAIL_ARCHEVEQUE = "archeveque.dakar@jangubidev.sn"
EMAIL_EVEQUE = "eveque.thies@jangubidev.sn"
# Curé : prêtre ET administrateur de paroisse (role=parish_admin + RoleAssignment).
EMAIL_PRETRE = "pere.senghor@jangubidev.sn"
# Vicaire : prêtre « pur » — role=fidele (PAS admin digital), identité clergé dans
# pastoral_role. Cas canonique du modèle 2-dimensions et test du routage pastoral
# (un prêtre dont role='fidele' doit atteindre le dashboard prêtre, pas fidèle).
EMAIL_VICAIRE = "pere.diatta@jangubidev.sn"
EMAIL_DIACRE = "diacre.diop@jangubidev.sn"
EMAIL_FIDELE1 = "aminata.fall@jangubidev.sn"
EMAIL_FIDELE2 = "moussa.ndiaye@jangubidev.sn"
EMAIL_RELIGIEUX = "soeur.marguerite@jangubidev.sn"

# Paroisses de référence (doivent exister via seed_senegal).
PARISH_CATHEDRALE_DAKAR = "Cathédrale du Souvenir Africain"
PARISH_MEDINA = "Paroisse Saint-Joseph de Medina"
PARISH_SAINTE_MARIE = "Paroisse Sainte-Marie de la Mer"
PARISH_CATHEDRALE_THIES = "Cathédrale Saint-Joseph de Thiès"

DIOCESE_DAKAR = "Archidiocèse de Dakar"
DIOCESE_THIES = "Diocèse de Thiès"
PROVINCE_DAKAR = "Province de Dakar"

# Église ANNEXE (is_main=False) de la Cathédrale du Souvenir Africain : rend la
# granularité « église » visible et distincte du scope « paroisse ».
ANNEXE_CHURCH_NAME = "Chapelle Sainte-Thérèse"

DEMO_USERS = [
    {
        "email": EMAIL_SUPER_ADMIN,
        "phone_number": "+221770000001",
        "role": "super_admin",
        "pastoral_role": None,
        "is_staff": True,
        "is_admin": True,
        "first_name": "Mamadou",
        "last_name": "Sy",
        "title": "MR",
    },
    {
        "email": EMAIL_ARCHEVEQUE,
        "phone_number": "+221770000002",
        "role": "province_admin",
        "pastoral_role": "archeveque",
        "is_staff": True,
        "is_admin": True,
        "first_name": "Jean-Baptiste",
        "last_name": "Faye",
        "title": "MR",
    },
    {
        "email": EMAIL_EVEQUE,
        "phone_number": "+221770000003",
        "role": "diocese_admin",
        "pastoral_role": "eveque",
        "is_staff": True,
        "is_admin": True,
        "first_name": "Thomas",
        "last_name": "Mendy",
        "title": "MR",
    },
    {
        "email": EMAIL_PRETRE,
        "phone_number": "+221770000004",
        "role": "parish_admin",
        "pastoral_role": "pretre",
        "is_staff": True,
        "is_admin": True,
        "first_name": "Pierre",
        "last_name": "Senghor",
        "title": "MR",
    },
    {
        # Vicaire — prêtre SANS rôle admin : role='fidele', pastoral_role='pretre'.
        # Frontend : isAdmin=false (lit role), isClergy=true (lit pastoral_role) →
        # dashboard prêtre + nav clergé SANS passerelle Administration.
        "email": EMAIL_VICAIRE,
        "phone_number": "+221770000009",
        "role": "fidele",
        "pastoral_role": "pretre",
        "is_staff": False,
        "is_admin": False,
        "first_name": "Antoine",
        "last_name": "Diatta",
        "title": "MR",
    },
    {
        "email": EMAIL_DIACRE,
        "phone_number": "+221770000005",
        "role": "church_admin",
        "pastoral_role": "diacre",
        "is_staff": False,
        "is_admin": True,
        "first_name": "Joseph",
        "last_name": "Diop",
        "title": "MR",
    },
    {
        "email": EMAIL_FIDELE1,
        "phone_number": "+221770000006",
        "role": "fidele",
        "pastoral_role": "fidele",
        "is_staff": False,
        "is_admin": False,
        "first_name": "Aminata",
        "last_name": "Fall",
        "title": "MRS",
    },
    {
        "email": EMAIL_FIDELE2,
        "phone_number": "+221770000007",
        "role": "fidele",
        "pastoral_role": "fidele",
        "is_staff": False,
        "is_admin": False,
        "first_name": "Moussa",
        "last_name": "Ndiaye",
        "title": "MR",
    },
    {
        "email": EMAIL_RELIGIEUX,
        "phone_number": "+221770000008",
        "role": "fidele",
        "pastoral_role": "religieux",
        "is_staff": False,
        "is_admin": False,
        "first_name": "Marguerite",
        "last_name": "Coly",
        "title": "MRS",
    },
]

# Appartenances ecclésiales — (email → liste de (parish_name, is_primary)).
# Créées via membership_create : le signal dérive diocèse/province/primary_parish
# et l'onboarding passe `completed`. Le clergé n'a PAS d'appartenance fidèle
# (exempté ; autorité via RoleAssignment).
MEMBERSHIPS = {
    # Golden-path : multi-appartenance sur DEUX diocèses (Dakar principale + Thiès).
    EMAIL_FIDELE1: [
        (PARISH_CATHEDRALE_DAKAR, True),
        (PARISH_CATHEDRALE_THIES, False),
    ],
    EMAIL_FIDELE2: [(PARISH_CATHEDRALE_THIES, True)],
    # Marguerite : membre de l'église ANNEXE (3e élément = nom d'église précis).
    # MÊME paroisse qu'Aminata (membre de la principale), église DIFFÉRENTE → grain église.
    EMAIL_RELIGIEUX: [(PARISH_CATHEDRALE_DAKAR, True, ANNEXE_CHURCH_NAME)],
}

# Autorité administrative réelle (RoleAssignment). `church_parish` = on rattache
# l'assignation à l'église principale de cette paroisse.
ROLE_ASSIGNMENTS = [
    {"email": EMAIL_SUPER_ADMIN, "role": "super_admin", "scope": "global"},
    {"email": EMAIL_ARCHEVEQUE, "role": "province_admin", "scope": "province", "province": PROVINCE_DAKAR},
    {"email": EMAIL_EVEQUE, "role": "diocese_admin", "scope": "diocese", "diocese": DIOCESE_THIES},
    {
        "email": EMAIL_PRETRE,
        "role": "parish_admin",
        "scope": "parish",
        "parish": PARISH_CATHEDRALE_DAKAR,
        "is_principal": True,
    },
    # Diacre = church_admin scopé sur l'ANNEXE (et non la principale) → autorité au
    # grain église, distincte de la paroisse.
    {"email": EMAIL_DIACRE, "role": "church_admin", "scope": "church", "church_name": ANNEXE_CHURCH_NAME},
]

TV_CATEGORIES = [
    {"name": "Messes",     "slug": "messes",      "order": 1, "is_clergy_only": False},
    {"name": "Homélies",   "slug": "homelies",    "order": 2, "is_clergy_only": False},
    {"name": "Catéchèse",  "slug": "catechese",   "order": 3, "is_clergy_only": False},
    {"name": "Événements", "slug": "evenements",  "order": 4, "is_clergy_only": False},
    {"name": "Témoignages","slug": "temoignages", "order": 5, "is_clergy_only": False},
    {"name": "Formation",  "slug": "formation",   "order": 6, "is_clergy_only": True},
]

TV_VIDEOS = [
    {
        "title": "Messe dominicale — Cathédrale du Souvenir Africain, Dakar",
        "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "category_slug": "messes",
        "is_live": False,
    },
    {
        "title": "Homélie — 3e Dimanche de l'Avent",
        "youtube_url": "https://www.youtube.com/watch?v=9bZkp7q19f0",
        "category_slug": "homelies",
        "is_live": False,
    },
    {
        "title": "Catéchisme pour adultes — Le sacrement du baptême",
        "youtube_url": "https://www.youtube.com/watch?v=kJQP7kiw5Fk",
        "category_slug": "catechese",
        "is_live": False,
    },
    {
        "title": "Pèlerinage de Popenguine 2024 — Journée des Familles",
        "youtube_url": "https://www.youtube.com/watch?v=L_jWHffIx5E",
        "category_slug": "evenements",
        "is_live": False,
    },
    {
        "title": "Témoignage : ma conversion au cœur de la banlieue dakaroise",
        "youtube_url": "https://www.youtube.com/watch?v=oHg5SJYRHA0",
        "category_slug": "temoignages",
        "is_live": False,
    },
    {
        "title": "Formation des servants de messe — Module 1 : l'autel",
        "youtube_url": "https://www.youtube.com/watch?v=fJ9rUzIMcZQ",
        "category_slug": "formation",
        "is_live": False,
    },
]

ARTICLE_CATEGORIES = [
    {"name": "Vie paroissiale", "slug": "vie-paroissiale", "icon": "church",    "color": "#70CBFF", "display_order": 1},
    {"name": "Liturgie",        "slug": "liturgie",        "icon": "book-open", "color": "#8B5CF6", "display_order": 2},
    {"name": "Actualités",      "slug": "actualites",      "icon": "newspaper", "color": "#F59E0B", "display_order": 3},
    {"name": "Formation",       "slug": "formation-actu",  "icon": "book",      "color": "#10B981", "display_order": 4},
]

# scope_ref : nom de l'entité ciblée selon scope_type
#   global  → None ; diocese → nom diocèse ; parish → nom paroisse ;
#   church  → nom de la paroisse (on cible son église principale).
ARTICLES = [
    {
        "title": "Message de Carême 2024 — Archevêché de Dakar",
        "category_slug": "actualites",
        "scope_type": "global",
        "scope_ref": None,
        "author_email": EMAIL_ARCHEVEQUE,
        "status": "published",
        "excerpt": "En ce temps de Carême, l'Archevêché de Dakar vous invite à un retour sincère vers Dieu.",
        "content": """<h2>Message de Carême 2024</h2>
<p>Frères et sœurs dans le Christ,</p>
<p>En ce temps de Carême, nous sommes invités à renouveler notre engagement baptismal et à approfondir notre relation avec Dieu. Le jeûne, la prière et l'aumône restent les piliers de cette démarche de conversion.</p>
<p><em>† Jean-Baptiste Faye, Archevêque de Dakar</em></p>""",
    },
    {
        "title": "Lettre pastorale — Diocèse de Thiès : L'Église en sortie",
        "category_slug": "actualites",
        "scope_type": "diocese",
        "scope_ref": DIOCESE_THIES,
        "author_email": EMAIL_EVEQUE,
        "status": "published",
        "excerpt": "L'évêque de Thiès appelle les fidèles à porter l'Évangile dans les périphéries.",
        "content": """<h2>Lettre pastorale du Diocèse de Thiès</h2>
<p>Chers fidèles du Diocèse de Thiès,</p>
<p>Le Pape François nous appelle à être une Église en sortie. Allons vers les périphéries géographiques et existentielles.</p>
<p><em>† Thomas Mendy, Évêque de Thiès</em></p>""",
    },
    {
        "title": "Annonce diocésaine — Archidiocèse de Dakar : Synode des jeunes",
        "category_slug": "actualites",
        "scope_type": "diocese",
        "scope_ref": DIOCESE_DAKAR,
        "author_email": EMAIL_ARCHEVEQUE,
        "status": "published",
        "excerpt": "Le synode diocésain des jeunes se tiendra à Dakar en avril.",
        "content": """<h2>Synode des jeunes — Archidiocèse de Dakar</h2>
<p>Tous les jeunes du diocèse sont invités à participer au synode diocésain. Inscriptions auprès de votre paroisse.</p>""",
    },
    {
        "title": "Annonce : Retraite paroissiale — Cathédrale du Souvenir Africain",
        "category_slug": "vie-paroissiale",
        "scope_type": "parish",
        "scope_ref": PARISH_CATHEDRALE_DAKAR,
        "author_email": EMAIL_PRETRE,
        "status": "published",
        "excerpt": "Du 14 au 16 mars 2024, rejoignez-nous pour notre retraite paroissiale annuelle.",
        "content": """<h2>Retraite paroissiale 2024</h2>
<p>La paroisse Cathédrale du Souvenir Africain organise sa retraite spirituelle annuelle au Centre de Keur Moussa.</p>""",
    },
    {
        "title": "Vie de l'église — Cathédrale du Souvenir Africain : nouvel horaire des messes",
        "category_slug": "vie-paroissiale",
        "scope_type": "church",
        "scope_ref": PARISH_CATHEDRALE_DAKAR,
        "author_email": EMAIL_PRETRE,
        "status": "published",
        "excerpt": "À compter de dimanche, la messe dominicale est avancée à 9h00.",
        "content": """<h2>Nouvel horaire des messes</h2>
<p>À compter de ce dimanche, la messe dominicale de notre église PRINCIPALE est célébrée à 9h00 (au lieu de 9h30).</p>""",
    },
    {
        # Scopé à l'ANNEXE (Chapelle Sainte-Thérèse), publié par le diacre church_admin.
        # Visible des membres de l'annexe (Marguerite), EXCLU du fil des membres de la
        # principale (Aminata) — alors qu'ils partagent la même paroisse.
        "title": "Chapelle Sainte-Thérèse (annexe) — Messe de semaine à 18h30",
        "category_slug": "vie-paroissiale",
        "scope_type": "church",
        "scope_ref": ANNEXE_CHURCH_NAME,
        "author_email": EMAIL_DIACRE,
        "status": "published",
        "excerpt": "Horaire propre à la chapelle annexe — réservé à ses membres.",
        "content": """<h2>Chapelle Sainte-Thérèse — annexe</h2>
<p>La messe de semaine à la chapelle annexe est célébrée à 18h30 du lundi au vendredi.</p>""",
    },
    {
        "title": "Paroisse Saint-Joseph de Thiès — Kermesse paroissiale",
        "category_slug": "vie-paroissiale",
        "scope_type": "parish",
        "scope_ref": PARISH_CATHEDRALE_THIES,
        "author_email": EMAIL_EVEQUE,
        "status": "published",
        "excerpt": "La kermesse annuelle de la Cathédrale de Thiès aura lieu le dernier dimanche du mois.",
        "content": """<h2>Kermesse paroissiale</h2>
<p>La Cathédrale Saint-Joseph de Thiès organise sa kermesse annuelle au profit des œuvres caritatives.</p>""",
    },
    {
        "title": "Église de Thiès — Veillée de prière mensuelle",
        "category_slug": "vie-paroissiale",
        "scope_type": "church",
        "scope_ref": PARISH_CATHEDRALE_THIES,
        "author_email": EMAIL_EVEQUE,
        "status": "published",
        "excerpt": "Veillée de prière le premier vendredi du mois à la Cathédrale de Thiès.",
        "content": """<h2>Veillée de prière</h2>
<p>Tous les premiers vendredis du mois, veillée de prière et adoration à notre église.</p>""",
    },
    {
        "title": "Calendrier liturgique — Semaine Sainte 2024 (Souvenir Africain)",
        "category_slug": "liturgie",
        "scope_type": "parish",
        "scope_ref": PARISH_CATHEDRALE_DAKAR,
        "author_email": EMAIL_PRETRE,
        "status": "published",
        "excerpt": "Retrouvez le programme complet des célébrations de la Semaine Sainte à la Cathédrale.",
        "content": """<h2>Semaine Sainte 2024 — Programme</h2>
<p>Dimanche des Rameaux 9h30 · Jeudi Saint 18h30 · Vendredi Saint 15h00 · Veillée Pascale 21h00 · Pâques 9h30.</p>""",
    },
    {
        "title": "Formation : Comprendre la liturgie des Heures",
        "category_slug": "formation-actu",
        "scope_type": "global",
        "scope_ref": None,
        "author_email": EMAIL_SUPER_ADMIN,
        "status": "published",
        "excerpt": "L'Office Divin, prière de l'Église universelle, rythme la journée de 7 heures canoniales.",
        "content": """<h2>La Liturgie des Heures</h2>
<p>La prière officielle de l'Église : Matines, Laudes, Tierce, Sexte, None, Vêpres, Complies.</p>""",
    },
    {
        "title": "Paroisse Saint-Joseph de Medina — Catéchèse de rentrée",
        "category_slug": "vie-paroissiale",
        "scope_type": "parish",
        "scope_ref": PARISH_MEDINA,
        "author_email": EMAIL_PRETRE,
        "status": "published",
        "excerpt": "Article scopé à une 3e paroisse — NE doit PAS apparaître dans le fil d'Aminata.",
        "content": """<h2>Catéchèse de rentrée — Medina</h2>
<p>Les inscriptions à la catéchèse de la paroisse Saint-Joseph de Medina sont ouvertes.</p>""",
    },
    {
        "title": "Brouillon — Témoignage de foi : l'Eucharistie au cœur de ma vie",
        "category_slug": "vie-paroissiale",
        "scope_type": "parish",
        "scope_ref": PARISH_CATHEDRALE_DAKAR,
        "author_email": EMAIL_DIACRE,
        "status": "draft",
        "excerpt": "Un témoignage personnel sur la place de l'Eucharistie dans le quotidien d'un diacre.",
        "content": """<h2>L'Eucharistie, source et sommet</h2>
<p>[Témoignage en cours de rédaction — à compléter avant publication]</p>""",
    },
]

# target_parish_ref : paroisse RÉELLE du registre (résolue → target_parish FK).
#   orphan=True → demande orpheline legacy (target_parish NULL, parish_name texte).
DOCUMENT_REQUESTS = [
    {
        "requester_email": EMAIL_FIDELE1,
        "document_type": "baptism",
        "reason": "personal",
        "status": "submitted",
        "reference_suffix": "DEMO001",
        "target_parish_ref": PARISH_CATHEDRALE_DAKAR,  # paroisse d'appartenance
        "requester_last_name": "Fall",
        "requester_first_names": "Aminata Fatou",
        "date_of_birth": datetime.date(1993, 6, 15),
        "place_of_birth": "Dakar",
        "contact_phone": "+221770000006",
        "father_last_name": "Fall",
        "mother_last_name": "Diop",
        "sacrament_approximate_date": "1993",
        "sacrament_location": "Cathédrale du Souvenir Africain, Dakar",
    },
    {
        "requester_email": EMAIL_FIDELE1,
        "document_type": "confirmation",
        "reason": "religious_marriage",
        "status": "under_verification",
        "reference_suffix": "DEMO002",
        # REGISTRE : Aminata demande à une paroisse où elle N'EST PAS membre.
        "target_parish_ref": PARISH_MEDINA,
        "requester_last_name": "Fall",
        "requester_first_names": "Aminata Fatou",
        "date_of_birth": datetime.date(1993, 6, 15),
        "place_of_birth": "Dakar",
        "contact_phone": "+221770000006",
        "father_last_name": "Fall",
        "mother_last_name": "Diop",
        "sacrament_approximate_date": "2008",
        "sacrament_location": "Paroisse Saint-Joseph de Medina, Dakar",
    },
    {
        "requester_email": EMAIL_FIDELE2,
        "document_type": "first_communion",
        "reason": "catechism",
        "status": "validated",
        "reference_suffix": "DEMO003",
        "target_parish_ref": PARISH_CATHEDRALE_THIES,
        "requester_last_name": "Ndiaye",
        "requester_first_names": "Moussa Ousmane",
        "date_of_birth": datetime.date(1990, 3, 22),
        "place_of_birth": "Thiès",
        "contact_phone": "+221770000007",
        "father_last_name": "Ndiaye",
        "mother_last_name": "Seck",
        "sacrament_approximate_date": "2001",
        "sacrament_location": "Cathédrale Saint-Joseph de Thiès",
    },
    {
        "requester_email": EMAIL_FIDELE2,
        "document_type": "religious_marriage",
        "reason": "religious_marriage",
        "status": "document_deposited",
        "reference_suffix": "DEMO004",
        "target_parish_ref": PARISH_CATHEDRALE_THIES,
        "requester_last_name": "Ndiaye",
        "requester_first_names": "Moussa Ousmane",
        "date_of_birth": datetime.date(1990, 3, 22),
        "place_of_birth": "Thiès",
        "contact_phone": "+221770000007",
        "father_last_name": "Ndiaye",
        "mother_last_name": "Seck",
        "sacrament_approximate_date": "2018",
        "sacrament_location": "Cathédrale Saint-Joseph de Thiès",
    },
    {
        "requester_email": EMAIL_FIDELE1,
        "document_type": "baptism",
        "reason": "godparent",
        "status": "info_requested",
        "reference_suffix": "DEMO005",
        # ORPHELINE legacy : aucune FK résolue, parish_name texte conservé pour
        # illustrer l'affichage de repli (sortie via texte stocké).
        "orphan": True,
        "legacy_parish_name": "Paroisse Sainte-Marie de la Mer",
        "legacy_diocese": "Archidiocèse de Dakar",
        "info_request_message": "Les informations de parrainage sont incomplètes. Merci de préciser la date du baptême.",
        "requester_last_name": "Fall",
        "requester_first_names": "Aminata Fatou",
        "date_of_birth": datetime.date(1993, 6, 15),
        "place_of_birth": "Dakar",
        "contact_phone": "+221770000006",
        "father_last_name": "Fall",
        "mother_last_name": "Diop",
        "sacrament_approximate_date": "1995",
        "sacrament_location": "Paroisse Sainte-Marie de la Mer, Dakar",
    },
    {
        "requester_email": EMAIL_DIACRE,
        "document_type": "confirmation",
        "reason": "personal",
        "status": "rejected",
        "reference_suffix": "DEMO006",
        "target_parish_ref": PARISH_CATHEDRALE_DAKAR,
        "rejection_reason": "Le dossier soumis ne correspond pas aux registres de la paroisse indiquée.",
        "requester_last_name": "Diop",
        "requester_first_names": "Joseph Marie",
        "date_of_birth": datetime.date(1975, 11, 8),
        "place_of_birth": "Saint-Louis",
        "contact_phone": "+221770000005",
        "father_last_name": "Diop",
        "mother_last_name": "Gaye",
        "sacrament_approximate_date": "1989",
        "sacrament_location": "Église Saint-Louis du Sénégal",
    },
]

# Dons en ESPÈCES, étiquetés à l'église principale d'une paroisse (RG-PAY-03 :
# church.parish == parish, dérivé par church_id). `confirm` → confirmation
# manuelle par le clergé scopé. `anonymous` → donor NULL + nom anonyme (≤ 25 000).
DONATIONS = [
    {"donor_email": EMAIL_FIDELE1, "church_parish": PARISH_CATHEDRALE_DAKAR, "amount": 10000, "confirm": True,
     "note": "[demo] Quête du dimanche"},
    {"donor_email": EMAIL_FIDELE1, "church_parish": PARISH_CATHEDRALE_THIES, "amount": 5000, "confirm": False,
     "note": "[demo] Denier — église de Thiès"},
    {"donor_email": EMAIL_FIDELE2, "church_parish": PARISH_CATHEDRALE_THIES, "amount": 15000, "confirm": True,
     "note": "[demo] Projet toiture"},
    {"donor_email": EMAIL_FIDELE2, "church_parish": PARISH_CATHEDRALE_THIES, "amount": 2000, "confirm": False,
     "note": "[demo] Don libre"},
    {"donor_email": EMAIL_FIDELE1, "church_parish": PARISH_CATHEDRALE_DAKAR, "amount": 20000, "confirm": False,
     "anonymous": True, "anonymous_name": "Bienfaiteur anonyme", "note": "[demo] Don anonyme"},
    {"donor_email": EMAIL_FIDELE2, "church_parish": PARISH_CATHEDRALE_THIES, "amount": 12000, "confirm": False,
     "anonymous": True, "anonymous_name": "Famille discrète", "note": "[demo] Don anonyme 2"},
]

# Événements — scopes variés. organizer doit être clergé/admin.
EVENTS = [
    {"organizer_email": EMAIL_SUPER_ADMIN, "title": "[demo] Journée nationale de la jeunesse catholique",
     "event_type": "conference", "scope_type": "global", "scope_ref": None, "in_days": 30},
    {"organizer_email": EMAIL_ARCHEVEQUE, "title": "[demo] Récollection diocésaine — Dakar",
     "event_type": "retreat", "scope_type": "diocese", "scope_ref": DIOCESE_DAKAR, "in_days": 14},
    {"organizer_email": EMAIL_PRETRE, "title": "[demo] Messe d'action de grâce — Souvenir Africain",
     "event_type": "mass", "scope_type": "parish", "scope_ref": PARISH_CATHEDRALE_DAKAR, "in_days": 7},
    {"organizer_email": EMAIL_PRETRE, "title": "[demo] Adoration eucharistique — église du Souvenir",
     "event_type": "other", "scope_type": "church", "scope_ref": PARISH_CATHEDRALE_DAKAR, "in_days": 3},
]

# Intentions de messe — défaut = paroisse principale du demandeur.
INTENTIONS = [
    {"requestor_email": EMAIL_FIDELE1, "intention_type": "for_deceased",
     "intention_text": "[demo] Pour le repos de l'âme de mon grand-père Ibrahima."},
    {"requestor_email": EMAIL_FIDELE2, "intention_type": "for_living",
     "intention_text": "[demo] En action de grâce pour la santé retrouvée de ma mère."},
]

# (sender_key, text) — sender_key matches keys in sender_map built at runtime
CONVERSATION_MESSAGES_1 = [
    ("fidele", "Bonjour Père Senghor, j'aurais besoin de vos conseils pour une situation familiale délicate."),
    ("priest", "Bonjour Aminata, je vous lis. Je suis disponible. Racontez-moi ce qui se passe."),
    ("fidele", "Mon mari souhaite que nous nous réconciliions après une longue séparation, mais j'ai du mal à pardonner. Comment faire ?"),
    ("priest", "Le pardon est un chemin, pas un acte ponctuel. Commencez par prier pour lui chaque jour. Rencontrons-nous samedi à 10h en paroisse."),
]

CONVERSATION_MESSAGES_2 = [
    ("fidele", "Bonjour Père, pouvez-vous m'aider à comprendre comment participer à l'Office Divin ?"),
    ("priest", "Bonjour Moussa ! Commencez par les Laudes le matin et les Vêpres le soir, depuis la section Liturgie. Que le Seigneur bénisse votre démarche !"),
]


class Command(BaseCommand):
    help = "Peuple la base avec des données de démonstration réalistes (modèle multi-appartenance)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Supprime les données de démo existantes avant de les recréer",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            self._reset()

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== Jàngu Bi — Seed Demo (multi-appartenance) ===\n"))

        with transaction.atomic():
            self._load_org_maps()
            self._create_annexe_church()
            users = self._create_users()
            self._create_memberships(users)
            self._create_role_assignments(users)
            self._create_priest_profiles(users)
            self._create_tv_content()
            self._create_news_content(users)
            self._create_document_requests(users)
            self._create_conversations(users)
            self._create_donations(users)
            self._create_agenda_and_intentions(users)

        self._print_summary()

    # ─── Org maps (résolution par nom) ─────────────────────────────────────────

    def _load_org_maps(self):
        from apps.org.models import Church, Diocese, Parish, Province

        self._parishes = {p.name: p for p in Parish.objects.select_related("diocese").all()}
        self._dioceses = {d.name: d for d in Diocese.objects.all()}
        self._provinces = {p.name: p for p in Province.objects.all()}
        self._main_church = {
            c.parish.name: c
            for c in Church.objects.select_related("parish").filter(is_main=True)
        }
        if not self._parishes or not self._main_church:
            raise SystemExit(
                "❌ Aucune paroisse/église trouvée. Lancez `seed_senegal` d'abord."
            )

    def _church_of(self, parish_name):
        church = self._main_church.get(parish_name)
        if church is None:
            raise SystemExit(f"❌ Église principale introuvable pour « {parish_name} » (lancer seed_senegal).")
        return church

    def _resolve_church(self, ref):
        """Résout une église par NOM exact (annexe ou principale) ; à défaut, l'église
        PRINCIPALE de la paroisse nommée `ref` (les principales portent le nom de la
        paroisse)."""
        church = self._churches_by_name.get(ref)
        return church if church is not None else self._church_of(ref)

    def _create_annexe_church(self):
        from apps.org.models import Church

        self.stdout.write(self.style.MIGRATE_HEADING("\n  — Église annexe (grain église)"))
        parish = self._parishes[PARISH_CATHEDRALE_DAKAR]
        _, is_new = Church.objects.get_or_create(
            parish=parish,
            name=ANNEXE_CHURCH_NAME,
            defaults={"church_type": "chapelle", "is_main": False, "city": parish.city, "address": parish.address},
        )
        self.stdout.write(f"  {'[+]' if is_new else '[=]'} {ANNEXE_CHURCH_NAME} (annexe de {parish.name})")
        # Index des églises par nom (inclut désormais l'annexe).
        self._churches_by_name = {c.name: c for c in Church.objects.all()}

    # ─── Users ────────────────────────────────────────────────────────────────

    def _create_users(self):
        from apps.users.enums import UserOnboardingState
        from apps.users.models import BaseUser, Profile

        self.stdout.write(self.style.MIGRATE_HEADING("\n  — Utilisateurs"))

        created_users = {}
        for data in DEMO_USERS:
            # Les fidèles/religieux partent en attente de paroisse : l'onboarding
            # se complète par la création d'appartenance (vrai chemin, via le signal).
            is_clergy_or_admin = bool(data["is_admin"]) or data["email"] not in MEMBERSHIPS
            onboarding = (
                UserOnboardingState.COMPLETED
                if is_clergy_or_admin
                else UserOnboardingState.PENDING_PARISH_SELECTION
            )

            user, is_new = BaseUser.objects.get_or_create(
                email=data["email"],
                defaults={
                    "phone_number": data["phone_number"],
                    "role": data["role"],
                    "is_staff": data.get("is_staff", False),
                    "is_admin": data.get("is_admin", False),
                    "is_active": True,
                    "is_verified": True,
                    "pastoral_role": data["pastoral_role"] or "",
                    "onboarding_state": onboarding,
                },
            )
            if is_new:
                user.set_password(DEMO_PASSWORD)
                user.save(update_fields=["password"])

            # IMPORTANT : on ne pose PAS primary_parish ici — c'est le signal
            # Membership qui le dérive (cf. _create_memberships).
            Profile.objects.get_or_create(
                user=user,
                defaults={
                    "first_name": data["first_name"],
                    "last_name": data["last_name"],
                    "title": data["title"],
                },
            )

            label = "créé" if is_new else "existant"
            self.stdout.write(
                f"  {'[+]' if is_new else '[=]'} {data['email']} [{data['role']}] ({label})"
            )
            created_users[data["email"]] = user

        return created_users

    # ─── Memberships (appartenances ecclésiales) ───────────────────────────────

    def _create_memberships(self, users):
        from apps.users.models import Membership
        from apps.users.services_memberships import membership_create

        self.stdout.write(self.style.MIGRATE_HEADING("\n  — Appartenances (multi-église)"))

        for email, entries in MEMBERSHIPS.items():
            user = users[email]
            for entry in entries:
                parish_name, is_primary = entry[0], entry[1]
                # 3e élément optionnel = nom d'église précis (annexe) ; sinon principale.
                church_name = entry[2] if len(entry) > 2 else None
                church = self._resolve_church(church_name) if church_name else self._church_of(parish_name)
                label = church_name or parish_name
                if Membership.objects.filter(user=user, church=church).exists():
                    self.stdout.write(f"  [=] {email} ↔ {label} (existante)")
                    continue
                membership_create(user=user, church=church, is_primary=is_primary)
                tag = " ★ principale" if is_primary else ""
                self.stdout.write(f"  [+] {email} ↔ {label}{tag}")

    # ─── Role assignments (autorité réelle) ────────────────────────────────────

    def _create_role_assignments(self, users):
        from apps.users.enums import RoleScope
        from apps.users.models import RoleAssignment
        from apps.users.services_roles import role_assignment_create

        self.stdout.write(self.style.MIGRATE_HEADING("\n  — Autorité (RoleAssignment)"))

        for spec in ROLE_ASSIGNMENTS:
            user = users[spec["email"]]
            scope = spec["scope"]
            assert scope in RoleScope.values  # garde-fou cohérence enum
            province = self._provinces.get(spec["province"]) if spec.get("province") else None
            diocese = self._dioceses.get(spec["diocese"]) if spec.get("diocese") else None
            parish = self._parishes.get(spec["parish"]) if spec.get("parish") else None
            if spec.get("church_name"):
                church = self._resolve_church(spec["church_name"])  # église précise (annexe)
            elif spec.get("church_parish"):
                church = self._church_of(spec["church_parish"])  # église principale
            else:
                church = None

            # Idempotence : une assignation (user, role, scope) suffit en démo.
            if RoleAssignment.objects.filter(
                user=user, role=spec["role"], scope=scope, is_active=True
            ).exists():
                self.stdout.write(f"  [=] {spec['email']} [{spec['role']}/{scope}] (existante)")
                continue

            role_assignment_create(
                user=user,
                role=spec["role"],
                scope=scope,
                province=province,
                diocese=diocese,
                parish=parish,
                church=church,
                is_principal=spec.get("is_principal", False),
            )
            target = (
                spec.get("province") or spec.get("diocese") or spec.get("parish")
                or spec.get("church_name") or spec.get("church_parish") or "—"
            )
            self.stdout.write(f"  [+] {spec['email']} [{spec['role']}/{scope}] → {target}")

    # ─── Priest / Deacon profiles ─────────────────────────────────────────────

    def _create_priest_profiles(self, users):
        from apps.messaging.models import PriestProfile

        self.stdout.write(self.style.MIGRATE_HEADING("\n  — Profils clergé"))

        clergy = [
            (users[EMAIL_PRETRE], 2010,
             "Père Pierre Senghor, ordonné en 2010 pour l'Archidiocèse de Dakar. "
             "Accompagnement spirituel des familles et des jeunes."),
            (users[EMAIL_VICAIRE], 2019,
             "Père Antoine Diatta, vicaire, ordonné en 2019. Aumônerie des jeunes "
             "et préparation aux sacrements."),
            (users[EMAIL_DIACRE], 2018,
             "Diacre Joseph Diop, ordonné en 2018. Catéchèse des adultes et accompagnement des familles."),
        ]
        for user, ordination_year, bio in clergy:
            _, is_new = PriestProfile.objects.get_or_create(
                user=user,
                defaults={
                    "accepts_pastoral_chat": True,
                    "cgu_accepted_at": timezone.now(),
                    "ordination_year": ordination_year,
                    "bio": bio,
                },
            )
            self.stdout.write(f"  {'[+]' if is_new else '[=]'} PriestProfile {user.email}")

    # ─── TV content ───────────────────────────────────────────────────────────

    def _create_tv_content(self):
        from apps.tv.models import Category, Video

        self.stdout.write(self.style.MIGRATE_HEADING("\n  — JanguBi TV"))
        cat_map = {}
        for data in TV_CATEGORIES:
            cat, is_new = Category.objects.get_or_create(
                slug=data["slug"],
                defaults={"name": data["name"], "order": data["order"], "is_clergy_only": data["is_clergy_only"]},
            )
            cat_map[data["slug"]] = cat
            clergy_tag = " [clergé]" if data["is_clergy_only"] else ""
            self.stdout.write(f"  {'[+]' if is_new else '[=]'} Catégorie TV : {data['name']}{clergy_tag}")

        for data in TV_VIDEOS:
            cat = cat_map[data["category_slug"]]
            _, is_new = Video.objects.get_or_create(
                youtube_url=data["youtube_url"],
                defaults={"title": data["title"], "category": cat, "is_live": data.get("is_live", False)},
            )
            self.stdout.write(f"  {'[+]' if is_new else '[=]'} Vidéo : {data['title'][:55]}")

    # ─── News content ─────────────────────────────────────────────────────────

    def _create_news_content(self, users):
        from apps.news.models import Article, ArticleCategory

        self.stdout.write(self.style.MIGRATE_HEADING("\n  — Actualités"))
        cat_map = {}
        for data in ARTICLE_CATEGORIES:
            cat, is_new = ArticleCategory.objects.get_or_create(
                slug=data["slug"],
                defaults={
                    "name": data["name"], "icon": data["icon"], "color": data["color"],
                    "display_order": data["display_order"], "is_active": True,
                },
            )
            cat_map[data["slug"]] = cat
            self.stdout.write(f"  {'[+]' if is_new else '[=]'} Catégorie : {data['name']}")

        for data in ARTICLES:
            cat = cat_map[data["category_slug"]]
            author = users[data["author_email"]]
            slug = slugify(data["title"])
            scope_type = data["scope_type"]
            ref = data.get("scope_ref")

            # Résolution du scope FK selon le type.
            scope_parish = scope_diocese = scope_church = None
            if scope_type == "parish":
                scope_parish = self._parishes.get(ref)
            elif scope_type == "diocese":
                scope_diocese = self._dioceses.get(ref)
            elif scope_type == "church":
                scope_church = self._resolve_church(ref)

            _, is_new = Article.objects.get_or_create(
                slug=slug,
                defaults={
                    "title": data["title"],
                    "excerpt": data.get("excerpt", ""),
                    "content": data["content"],
                    "category": cat,
                    "author": author,
                    "scope_type": scope_type,
                    "scope_parish": scope_parish,
                    "scope_diocese": scope_diocese,
                    "scope_church": scope_church,
                    "status": data.get("status", "published"),
                    "published_at": timezone.now() if data.get("status") == "published" else None,
                },
            )
            scope_tag = f"[{scope_type}{(':' + ref) if ref else ''}]"
            status_tag = f"[{data.get('status', 'published')}]"
            self.stdout.write(f"  {'[+]' if is_new else '[=]'} Article {scope_tag}{status_tag} : {data['title'][:42]}")

    # ─── Document requests ────────────────────────────────────────────────────

    def _create_document_requests(self, users):
        from apps.documents.models import DocumentRequest

        self.stdout.write(self.style.MIGRATE_HEADING("\n  — Demandes de documents"))

        for data in DOCUMENT_REQUESTS:
            reference = f"DOC-{data['reference_suffix']}"
            requester = users[data["requester_email"]]

            if DocumentRequest.objects.filter(reference=reference).exists():
                self.stdout.write(f"  [=] Demande {reference} (existante)")
                continue

            if data.get("orphan"):
                # Orpheline legacy : pas de FK, texte stocké conservé.
                target_parish = None
                parish_name = data["legacy_parish_name"]
                diocese = data["legacy_diocese"]
            else:
                target_parish = self._parishes[data["target_parish_ref"]]
                # B5c : nom + diocèse dérivés de la FK.
                parish_name = target_parish.name
                diocese = target_parish.diocese.name

            DocumentRequest.objects.create(
                requester=requester,
                reference=reference,
                document_type=data["document_type"],
                reason=data["reason"],
                status=data["status"],
                rejection_reason=data.get("rejection_reason", ""),
                additional_info=data.get("info_request_message", ""),
                requester_last_name=data["requester_last_name"],
                requester_first_names=data["requester_first_names"],
                date_of_birth=data["date_of_birth"],
                place_of_birth=data["place_of_birth"],
                contact_phone=data["contact_phone"],
                contact_email=requester.email,
                father_last_name=data.get("father_last_name", ""),
                mother_last_name=data.get("mother_last_name", ""),
                parish_name=parish_name,
                diocese=diocese,
                target_parish=target_parish,
                sacrament_approximate_date=data.get("sacrament_approximate_date", ""),
                sacrament_location=data.get("sacrament_location", ""),
                consent_given=True,
            )

            type_label = data["document_type"].replace("_", " ").title()
            target_tag = "[orphelin]" if data.get("orphan") else f"→ {parish_name}"
            self.stdout.write(f"  [+] {reference} — {type_label} [{data['status']}] {target_tag}")

    # ─── Conversations ────────────────────────────────────────────────────────

    def _create_conversations(self, users):
        from apps.messaging.models import Conversation, Message

        self.stdout.write(self.style.MIGRATE_HEADING("\n  — Messagerie"))

        threads = [
            (users[EMAIL_FIDELE1], users[EMAIL_PRETRE], CONVERSATION_MESSAGES_1),
            (users[EMAIL_FIDELE2], users[EMAIL_PRETRE], CONVERSATION_MESSAGES_2),
        ]
        for fidele, priest, messages in threads:
            a, b = (fidele, priest) if str(fidele.id) < str(priest.id) else (priest, fidele)
            conv, is_new = Conversation.objects.get_or_create(
                participant_a=a,
                participant_b=b,
                defaults={"cgu_accepted_by_a": timezone.now(), "cgu_accepted_by_b": timezone.now()},
            )
            self.stdout.write(f"  {'[+]' if is_new else '[=]'} Conversation {fidele.email} ↔ {priest.email}")
            if not is_new:
                continue

            now = timezone.now()
            sender_map = {"fidele": fidele, "priest": priest}
            for i, (sender_key, text) in enumerate(messages):
                msg = Message.objects.create(
                    conversation=conv,
                    sender=sender_map[sender_key],
                    content=text,
                    client_message_id=uuid.uuid4(),
                    content_type="text",
                )
                msg_time = now - datetime.timedelta(hours=len(messages) - i)
                Message.objects.filter(pk=msg.pk).update(created_at=msg_time)
            Conversation.objects.filter(pk=conv.pk).update(last_message_at=now)

    # ─── Donations ────────────────────────────────────────────────────────────

    def _create_donations(self, users):
        from apps.donations.models import Donation
        from apps.donations.services import donation_confirm, donation_make

        self.stdout.write(self.style.MIGRATE_HEADING("\n  — Dons"))

        if Donation.objects.filter(note__startswith="[demo]").exists():
            self.stdout.write("  [=] Dons de démo déjà présents")
            return

        for data in DONATIONS:
            donor = users[data["donor_email"]]
            church = self._church_of(data["church_parish"])
            donation = donation_make(
                donor=donor,
                amount=data["amount"],
                payment_provider="cash",  # garde 5a : aucun provider en ligne
                church_id=church.id,
                is_anonymous=data.get("anonymous", False),
                anonymous_donor_name=data.get("anonymous_name", ""),
                note=data["note"],
            )
            tag = "[PENDING]"
            if data.get("confirm"):
                # Confirmation manuelle (autorité paroisse).
                donation_confirm(donation=donation, payment_reference="[demo] reçu espèces")
                tag = "[CONFIRMED]"
            anon = " (anonyme)" if data.get("anonymous") else ""
            self.stdout.write(
                f"  [+] Don {data['amount']} XOF → {data['church_parish']} {tag}{anon}"
            )

    # ─── Agenda + intentions ──────────────────────────────────────────────────

    def _create_agenda_and_intentions(self, users):
        from apps.agenda.models import Event
        from apps.hierarchy.models import Node
        from apps.mass_intentions.models import MassIntention
        from apps.mass_intentions.services import mass_intention_submit

        self.stdout.write(self.style.MIGRATE_HEADING("\n  — Agenda & intentions"))

        now = timezone.now()
        for data in EVENTS:
            if Event.objects.filter(title=data["title"]).exists():
                self.stdout.write(f"  [=] Événement « {data['title'][:40]} » (existant)")
                continue
            organizer = users[data["organizer_email"]]
            scope_type = data["scope_type"]
            ref = data.get("scope_ref")
            legacy: dict = {}
            node = None
            if scope_type == "parish":
                legacy["scope_parish"] = self._parishes[ref]
                node = Node.objects.filter(legacy_model="org.Parish", legacy_id=self._parishes[ref].id).first()
            elif scope_type == "diocese":
                legacy["scope_diocese"] = self._dioceses[ref]
                node = Node.objects.filter(legacy_model="org.Diocese", legacy_id=self._dioceses[ref].id).first()
            elif scope_type == "church":
                church = self._church_of(ref)
                legacy["scope_church"] = church
                node = Node.objects.filter(legacy_model="org.Parish", legacy_id=church.parish_id).first()

            # Données de démonstration : écriture directe (portée héritée + nœud V1 correspondant),
            # sans le contrôle de capacités du service (les comptes de démo n'ont pas de nomination).
            start = now + datetime.timedelta(days=data["in_days"])
            Event.objects.create(
                organizer=organizer,
                title=data["title"],
                event_type=data["event_type"],
                start_at=start,
                end_at=start + datetime.timedelta(hours=2),
                scope_type=scope_type,
                scope_node=node,
                **legacy,
            )
            self.stdout.write(f"  [+] Événement [{scope_type}] : {data['title'][:42]}")

        for data in INTENTIONS:
            requestor = users[data["requestor_email"]]
            if MassIntention.objects.filter(requestor=requestor, intention_text=data["intention_text"]).exists():
                self.stdout.write(f"  [=] Intention de {requestor.email} (existante)")
                continue
            mass_intention_submit(
                requestor=requestor,
                intention_type=data["intention_type"],
                intention_text=data["intention_text"],
            )
            self.stdout.write(f"  [+] Intention [{data['intention_type']}] — {requestor.email}")

    # ─── Reset ────────────────────────────────────────────────────────────────

    def _reset(self):
        from apps.agenda.models import Event
        from apps.documents.models import DocumentRequest
        from apps.donations.models import Donation
        from apps.mass_intentions.models import MassIntention
        from apps.messaging.models import Conversation
        from apps.news.models import Article, ArticleCategory
        from apps.tv.models import Category as TvCategory
        from apps.tv.models import Video
        from apps.users.models import BaseUser, Membership, RoleAssignment

        self.stdout.write(self.style.WARNING("\n  Suppression des données de démo existantes..."))

        emails = [u["email"] for u in DEMO_USERS]
        legacy_emails = [
            "admin@jangubiapp.com", "pretre@jangubiapp.com",
            "fidele1@jangubiapp.com", "fidele2@jangubiapp.com",
        ]
        users = BaseUser.objects.filter(email__in=emails + legacy_emails)

        # Entités liées aux users d'abord (FK PROTECT empêche sinon la suppression).
        Donation.objects.filter(donor__in=users).delete()
        Donation.objects.filter(note__startswith="[demo]").delete()  # dons anonymes (donor NULL)
        MassIntention.objects.filter(requestor__in=users).delete()
        Event.objects.filter(organizer__in=users).delete()
        Event.objects.filter(title__startswith="[demo]").delete()
        Conversation.objects.filter(participant_a__in=users).delete()
        Conversation.objects.filter(participant_b__in=users).delete()
        DocumentRequest.objects.filter(requester__in=users).delete()
        Article.objects.filter(author__in=users).delete()
        RoleAssignment.objects.filter(user__in=users).delete()
        Membership.objects.filter(user__in=users).delete()

        # Église annexe de démo (créée par seed_demo, pas seed_senegal).
        from apps.org.models import Church
        Church.objects.filter(name=ANNEXE_CHURCH_NAME, is_main=False).delete()

        demo_tv_slugs = [c["slug"] for c in TV_CATEGORIES]
        Video.objects.filter(category__slug__in=demo_tv_slugs).delete()
        TvCategory.objects.filter(slug__in=demo_tv_slugs).delete()
        ArticleCategory.objects.filter(slug__in=[c["slug"] for c in ARTICLE_CATEGORIES]).delete()

        users.delete()
        self.stdout.write(self.style.SUCCESS("  Données supprimées.\n"))

    # ─── Summary ──────────────────────────────────────────────────────────────

    def _print_summary(self):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("✓ Données de démonstration créées avec succès !"))
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("─── Comptes de test ────────────────────────────────────"))
        self.stdout.write(f"  Mot de passe commun : {self.style.WARNING(DEMO_PASSWORD)}")
        self.stdout.write("")
        for u in DEMO_USERS:
            role_label = u["role"].replace("_", " ").title()
            pastoral = f" / {u['pastoral_role']}" if u.get("pastoral_role") else ""
            memb = MEMBERSHIPS.get(u["email"])
            memb_label = (
                "  appartenances: " + ", ".join((e[2] if len(e) > 2 else e[0]) for e in memb)
            ) if memb else ""
            self.stdout.write(f"  {u['email']:<42} [{role_label}{pastoral}]{memb_label}")
        self.stdout.write(self.style.MIGRATE_HEADING("────────────────────────────────────────────────────────"))
        self.stdout.write("")
