# API des tableaux de bord des dons — contrat JSON

> Lot A2 (suite V2), 27/09/2026. Backend `JanguBi`, module `apps/donations`.
> Ce document fixe la forme **exacte** des deux endpoints d'analyse. Les écrans mobiles (G10, G11) et web
> (`WEB-PAR-Dons-Analyse`, `WEB-DIO-Dons-Analyse`, `WEB-PLA-Dons-Sante`) s'alignent dessus.
> Source de vérité du schéma : `apps/donations/serializers_analyse.py` (`@extend_schema`, `schema.yml`).
> Spec fonctionnelle : `JanguBIMobileApp/docs/design/ECRANS-TABLEAU-DE-BORD-DONS.md`, avec les décisions du 27/09/2026.

## 1. Conventions communes

- **Montants** : entiers en FCFA, sans séparateur. Le client formate (espaces insécables, « FCFA »).
- **`part`** : pourcentage entier. Il est calculé sur les valeurs **exactes**, puis arrondi. Il vaut `null` quand le
  total de référence est nul.
- **Clés toujours présentes.** Un bloc qui ne s'applique pas au niveau demandé vaut `null`. On ne supprime jamais
  une clé. Toute évolution sera **additive** : nouvelles clés, nouvelles valeurs d'énumération.
- **Dates** : ISO 8601. `AAAA-MM-JJ` pour une date, UTC `…Z` pour un instant (Africa/Dakar = UTC).
- **Collecté** : montant **donné** (`amount`) des dons confirmés, sur leur **date de valeur**.
  - Espèces : jour de la messe (et non jour de la validation).
  - En ligne : date de confirmation.
  - Un remboursement est une ligne **négative** du mois où il a lieu. Le mois du don ne change donc jamais,
    et un mois clos reste figé.
- **Confidentialité**, appliquée par le serveur :
  - aucun nom de donateur, à aucun niveau ;
  - au-dessus de la paroisse, montants de `synthese`, `tendance` et `paroisses` arrondis au millier (demi vers le
    haut) ;
  - pas de seuil k ni de règle de dominance (décision du 27/09) ;
  - paroisses **toujours** en ordre alphabétique, sans tenir compte des accents ni de la casse ;
  - **aucun tri par montant** : les listes suivent un ordre fixe, décrit plus bas ;
  - plateforme : **aucun montant**, même agrégé.
- **Ordres fixes**, à ne jamais permuter côté client :
  - types de fonds, dans l'ordre de la palette : `quete_dominicale`, `quete_imperee`, `campagne`,
    `contribution_annuelle` ;
  - sources : `app_ios`, `app_android`, `web`, puis `qr` et `inconnu` s'ils ne sont pas vides ;
  - moyens : `wave`, `orange_money`, `free_money`, `carte`, puis `autre` et `inconnu` s'ils ne sont pas vides ;
  - lieux : le lieu principal d'abord, puis l'ordre alphabétique, et enfin « Lieu non renseigné » (`lieu_id: null`).
- **Erreurs** : enveloppe standard de l'API v1 (`code`, `message`, `details`).

## 2. `GET /api/v1/staff/dons/analyse/`

### 2.1 Paramètres

| Paramètre | Valeurs | Défaut |
|---|---|---|
| `niveau` | `paroisse` · `diocese` | obligatoire |
| `noeud` | UUID : une paroisse (`niveau=paroisse`), un diocèse ou un doyenné (`niveau=diocese`) | obligatoire |
| `periode` | `semaine` (paroisse seulement) · `mois` · `trimestre` · `annee` | `mois` |
| `date` | `semaine` : `2026-W39` · `mois` : `2026-09` · `trimestre` : `2026-T3` · `annee` : `2026` | période en cours |

Exemples :
- `?niveau=paroisse&noeud=<saint-dominique>&periode=mois&date=2026-09`
- `?niveau=diocese&noeud=<archidiocese>&periode=mois&date=2026-09`

### 2.2 Droits et erreurs

| Cas | Réponse |
|---|---|
| `niveau=paroisse` : `dons.voir_fonds` par une nomination **sur la paroisse même** (curé, économe, secrétaire). Un droit hérité du diocèse ne suffit pas. | 200 |
| `niveau=diocese` : `dons.voir_agregats` sur le nœud ou un ancêtre (évêque, économe diocésain) | 200 |
| Pas de droit, MFA absente, plateforme | 403 `dons_forbidden` / `mfa_required` |
| `niveau=paroisse` sur un nœud qui n'est pas une paroisse | 400 `not_a_parish` |
| `niveau=diocese` sur un nœud qui n'est ni un diocèse ni un doyenné | 400 `not_an_aggregate_node` |
| `periode=semaine` au-dessus de la paroisse | 400 `period_not_allowed` |
| `date` mal formée | 400 `invalid_period` |

### 2.3 Blocs de la réponse

| Clé | Paroisse | Diocèse / doyenné |
|---|---|---|
| `niveau`, `noeud`, `periode`, `genere_le`, `confidentialite` | oui | oui (`confidentialite.arrondi` = 1000) |
| `synthese` | exacte, avec `par_fonds` et `par_lieu` | arrondie ; `par_fonds` et `par_lieu` à `null` |
| `tendance` | `grain` : `jour` (semaine), `semaine` (mois), `mois` (trimestre, année) | idem, arrondie |
| `a_traiter` | tâches de la paroisse | tâches de la curie, chacune avec sa `paroisse` |
| `paroisses` | `null` | `compteurs` et `lignes` alphabétiques ; les colonnes chiffrées d'une paroisse en préparation valent `null` |
| `quetes_imperees` | la déclinaison de la paroisse | toutes les paroisses concernées. Montants **exacts** : c'est l'argent de la curie, à rapprocher des remises |
| `tresorerie`, `paiements`, `campagnes` | oui | `null` |
| `notes` | phrases prêtes à afficher | idem, avec la mention de l'arrondi |

Détails :
- **Tendance.** Les semaines vont du lundi au dimanche, sont coupées aux bornes de la période et portent le libellé
  de leur dimanche (« au dim. 6 »). Les sous-périodes qui n'ont pas encore commencé sont omises.
- **`paroisses.lignes[].evolution`** compare la paroisse **à elle-même** : la période face à la moyenne des trois
  précédentes (`stable` à ±10 %, `en_hausse`, `en_baisse`). La valeur est `null` tant que trois périodes complètes
  n'ont pas suivi l'ouverture de la collecte.
- **Paroisses engagées** : celles qui ont une fiche d'activation.
  - `ouverte` : la collecte est active ;
  - `en_preparation` : la fiche existe, mais la collecte n'est pas encore active.

### 2.4 « À traiter »

La liste est triée par `echeance` croissante (la plus proche en premier). Chaque élément porte :
- `type` ;
- `echeance` (date) ;
- `libelle` ;
- `nombre` ;
- `montant` (`null` si sans objet) ;
- `depuis` (instant, ou `null`) ;
- `paroisse` (`{id, nom}` au diocèse, `null` en paroisse) ;
- `objet_id` : la quête, le fonds, la remise, l'incident, ou le mois `AAAA-MM`.

| `type` | Niveau | Échéance |
|---|---|---|
| `quete_a_confirmer` | paroisse (une par quête), diocèse (une par paroisse) | jour de la messe + 2 j (`DONATIONS_CASH_VALIDATE_DAYS`) |
| `paiements_en_attente` | paroisse (groupé) | expiration du plus ancien (création + 24 h) |
| `paiement_tardif` | paroisse | détection + 7 j (`DONATIONS_INCIDENT_DAYS`) ; montant incohérent compris |
| `especes_a_deposer` | paroisse (groupé) | plus ancienne messe non déposée + 7 j (`DONATIONS_CASH_DEPOSIT_DAYS`) |
| `remise_curie` | paroisse, diocèse | `Fund.remit_by` de la quête impérée (défaut : quête + 7 j) |
| `remise_a_confirmer` | diocèse | date de remise + 7 j (`DONATIONS_REMITTANCE_CONFIRM_DAYS`) |
| `cloture_mois` | paroisse | le 10 du mois courant (`DONATIONS_MONTH_CLOSE_DAY`) |

À échéance égale, l'ordre des types est celui du tableau.

### 2.5 Exemple : paroisse, septembre 2026

Jeu de référence de la spec §2 : Saint-Dominique, requête du dimanche 27 septembre 2026 à 20 h.
- 1 214 830 FCFA collectés : 356 330 en ligne et 858 500 en espèces.
- Par type de fonds : 259 905, 674 525, 236 400 et 44 000.
- Le jeu est reproduit par `apps/donations/tests/dataset_septembre.py`. La réponse ci-dessous est la sortie réelle
  de l'API ; seuls les UUID ont été remplacés par des valeurs lisibles.

```json
{
  "niveau": "paroisse",
  "noeud": {"id": "5d000000-0000-4000-8000-00000000000d", "nom": "Saint-Dominique", "type": "paroisse"},
  "periode": {"type": "mois", "code": "2026-09", "debut": "2026-09-01", "fin": "2026-09-30", "libelle": "septembre 2026"},
  "genere_le": "2026-09-27T20:00:00Z",
  "confidentialite": {"arrondi": 1, "noms_donateurs": false, "ordre_paroisses": "alphabetique", "tri_par_montant": false},
  "synthese": {
    "collecte": 1214830,
    "en_ligne": 356330,
    "especes": 858500,
    "nombre_dons_en_ligne": 47,
    "nombre_quetes": 9,
    "par_destination": {"paroisse": 540305, "curie": 674525},
    "par_type_fonds": [
      {"type": "quete_dominicale", "libelle": "Quête dominicale", "en_ligne": 47405, "especes": 212500, "total": 259905, "nombre": 9, "part": 21},
      {"type": "quete_imperee", "libelle": "Quête impérée", "en_ligne": 28525, "especes": 646000, "total": 674525, "nombre": 10, "part": 56},
      {"type": "campagne", "libelle": "Campagne pour un projet", "en_ligne": 236400, "especes": 0, "total": 236400, "nombre": 31, "part": 19},
      {"type": "contribution_annuelle", "libelle": "Contribution annuelle", "en_ligne": 44000, "especes": 0, "total": 44000, "nombre": 6, "part": 4}
    ],
    "par_fonds": [
      {
        "fonds_id": "00000000-0000-4000-8000-000000000001",
        "titre": "Quête dominicale",
        "type": "quete_dominicale",
        "destination": "paroisse",
        "en_ligne": 47405,
        "especes": 212500,
        "total": 259905,
        "nombre": 9,
        "part": 21
      },
      {
        "fonds_id": "00000000-0000-4000-8000-000000000002",
        "titre": "Quête impérée · Grand Séminaire de Brin",
        "type": "quete_imperee",
        "destination": "curie",
        "en_ligne": 28525,
        "especes": 646000,
        "total": 674525,
        "nombre": 10,
        "part": 56
      },
      {
        "fonds_id": "00000000-0000-4000-8000-000000000003",
        "titre": "Toiture de la chapelle",
        "type": "campagne",
        "destination": "paroisse",
        "en_ligne": 236400,
        "especes": 0,
        "total": 236400,
        "nombre": 31,
        "part": 19
      },
      {
        "fonds_id": "00000000-0000-4000-8000-000000000004",
        "titre": "Contribution annuelle 2026",
        "type": "contribution_annuelle",
        "destination": "paroisse",
        "en_ligne": 44000,
        "especes": 0,
        "total": 44000,
        "nombre": 6,
        "part": 4
      }
    ],
    "par_canal": [
      {
        "canal": "en_ligne",
        "libelle": "En ligne",
        "total": 356330,
        "nombre": 47,
        "part": 29,
        "sources": [
          {"source": "app_ios", "libelle": "App iOS", "total": 61500, "nombre": 8, "part": 17},
          {"source": "app_android", "libelle": "App Android", "total": 199000, "nombre": 26, "part": 56},
          {"source": "web", "libelle": "Site", "total": 95830, "nombre": 13, "part": 27}
        ]
      },
      {"canal": "especes", "libelle": "Espèces", "total": 858500, "nombre": 9, "part": 71, "sources": []}
    ],
    "par_moyen": [
      {"moyen": "wave", "libelle": "Wave", "total": 208450, "nombre": 29, "part": 58},
      {"moyen": "orange_money", "libelle": "Orange Money", "total": 106380, "nombre": 14, "part": 30},
      {"moyen": "free_money", "libelle": "Free Money", "total": 0, "nombre": 0, "part": 0},
      {"moyen": "carte", "libelle": "Carte bancaire", "total": 41500, "nombre": 4, "part": 12}
    ],
    "par_lieu": [
      {"lieu_id": 1, "nom": "Église Saint-Dominique", "en_ligne": 0, "especes": 775000, "total": 775000, "nombre": 7, "part": 64},
      {"lieu_id": 2, "nom": "Chapelle de la Cité universitaire", "en_ligne": 0, "especes": 83500, "total": 83500, "nombre": 2, "part": 7},
      {"lieu_id": null, "nom": "Lieu non renseigné", "en_ligne": 356330, "especes": 0, "total": 356330, "nombre": 47, "part": 29}
    ]
  },
  "tendance": {
    "grain": "semaine",
    "points": [
      {
        "debut": "2026-09-01",
        "fin": "2026-09-06",
        "libelle": "au dim. 6",
        "total": 71500,
        "en_ligne": 71500,
        "especes": 0,
        "par_type_fonds": {"quete_dominicale": 3000, "quete_imperee": 0, "campagne": 60500, "contribution_annuelle": 8000}
      },
      {
        "debut": "2026-09-07",
        "fin": "2026-09-13",
        "libelle": "au dim. 13",
        "total": 84250,
        "en_ligne": 84250,
        "especes": 0,
        "par_type_fonds": {"quete_dominicale": 2905, "quete_imperee": 0, "campagne": 71345, "contribution_annuelle": 10000}
      },
      {
        "debut": "2026-09-14",
        "fin": "2026-09-20",
        "libelle": "au dim. 20",
        "total": 297805,
        "en_ligne": 85305,
        "especes": 212500,
        "par_type_fonds": {"quete_dominicale": 215500, "quete_imperee": 0, "campagne": 64305, "contribution_annuelle": 18000}
      },
      {
        "debut": "2026-09-21",
        "fin": "2026-09-27",
        "libelle": "au dim. 27",
        "total": 761275,
        "en_ligne": 115275,
        "especes": 646000,
        "par_type_fonds": {"quete_dominicale": 38500, "quete_imperee": 674525, "campagne": 40250, "contribution_annuelle": 8000}
      }
    ]
  },
  "a_traiter": [
    {
      "type": "paiements_en_attente",
      "echeance": "2026-09-28",
      "libelle": "3 paiement(s) en attente de confirmation",
      "nombre": 3,
      "montant": 18000,
      "depuis": "2026-09-27T01:00:00Z",
      "paroisse": null,
      "objet_id": null
    },
    {
      "type": "quete_a_confirmer",
      "echeance": "2026-09-29",
      "libelle": "Quête à confirmer : Chapelle de la Cité universitaire, Messe de 17 h, 27/09",
      "nombre": 1,
      "montant": 64000,
      "depuis": "2026-09-27T18:30:00Z",
      "paroisse": null,
      "objet_id": "10"
    },
    {
      "type": "especes_a_deposer",
      "echeance": "2026-10-03",
      "libelle": "Espèces à déposer en banque",
      "nombre": 5,
      "montant": 646000,
      "depuis": "2026-09-26T20:00:00Z",
      "paroisse": null,
      "objet_id": null
    },
    {
      "type": "remise_curie",
      "echeance": "2026-10-04",
      "libelle": "Quête impérée · Grand Séminaire de Brin : espèces à remettre à la curie",
      "nombre": 1,
      "montant": 646000,
      "depuis": null,
      "paroisse": null,
      "objet_id": "00000000-0000-4000-8000-000000000002"
    }
  ],
  "paroisses": null,
  "quetes_imperees": [
    {
      "fonds_id": "00000000-0000-4000-8000-000000000005",
      "titre": "Quête impérée · Grand Séminaire de Brin",
      "date": "2026-09-27",
      "echeance": "2026-10-04",
      "messe_anticipee_incluse": true,
      "paroisses": [
        {
          "id": "5d000000-0000-4000-8000-00000000000d",
          "nom": "Saint-Dominique",
          "en_ligne": 28525,
          "especes": 646000,
          "total": 674525,
          "remis": 0,
          "remise_declaree": 0,
          "reste_a_remettre": 646000,
          "part_remise": 0
        }
      ]
    }
  ],
  "tresorerie": {
    "en_ligne": {
      "paye": 356330,
      "frais": 7120,
      "frais_reels": 7120,
      "net": 349210,
      "reverse": 301480,
      "en_attente_reversement": 47730,
      "part_reversee": 86,
      "net_pour_100": 98,
      "dons_frais_couverts": 0,
      "nombre": 47
    },
    "especes": {"validees": 858500, "deposees": 212500, "en_caisse": 646000, "a_confirmer": 64000}
  },
  "paiements": {"lances": 58, "confirmes": 47, "en_attente": 3, "echoues": 4, "expires": 4, "taux_confirmation": 81},
  "campagnes": [
    {
      "fonds_id": "00000000-0000-4000-8000-000000000003",
      "titre": "Toiture de la chapelle",
      "objectif": 4500000,
      "reuni": 1186400,
      "part": 26,
      "nombre": 57,
      "periode": 236400,
      "debut": "2026-06-01",
      "fin": "2026-12-31",
      "statut": "ouvert",
      "rythme_hebdo": 59100,
      "projection_fin": 1988471,
      "part_projection": 44
    }
  ],
  "notes": [
    "Les quêtes en espèces sont saisies sur Jàngu Bi depuis le 20 septembre.",
    "Comparaison avec l'an dernier disponible à partir de juin 2027.",
    "Montants en FCFA. Aucun nom de donateur dans cette vue."
  ]
}
```

### 2.6 Exemple : diocèse, septembre 2026

Même jeu. La vue est celle de l'économe diocésain sur l'archidiocèse de Dakar.
- « Environ 1 215 000 FCFA, dont 675 000 destinés à la curie. »
- 1 paroisse sur 5 engagées collecte.

```json
{
  "niveau": "diocese",
  "noeud": {"id": "da000000-0000-4000-8000-00000000000a", "nom": "Archidiocèse de Dakar", "type": "diocese"},
  "periode": {"type": "mois", "code": "2026-09", "debut": "2026-09-01", "fin": "2026-09-30", "libelle": "septembre 2026"},
  "genere_le": "2026-09-27T20:00:00Z",
  "confidentialite": {"arrondi": 1000, "noms_donateurs": false, "ordre_paroisses": "alphabetique", "tri_par_montant": false},
  "synthese": {
    "collecte": 1215000,
    "en_ligne": 356000,
    "especes": 859000,
    "nombre_dons_en_ligne": 47,
    "nombre_quetes": 9,
    "par_destination": {"paroisse": 540000, "curie": 675000},
    "par_type_fonds": [
      {"type": "quete_dominicale", "libelle": "Quête dominicale", "en_ligne": 47000, "especes": 213000, "total": 260000, "nombre": 9, "part": 21},
      {"type": "quete_imperee", "libelle": "Quête impérée", "en_ligne": 29000, "especes": 646000, "total": 675000, "nombre": 10, "part": 56},
      {"type": "campagne", "libelle": "Campagne pour un projet", "en_ligne": 236000, "especes": 0, "total": 236000, "nombre": 31, "part": 19},
      {"type": "contribution_annuelle", "libelle": "Contribution annuelle", "en_ligne": 44000, "especes": 0, "total": 44000, "nombre": 6, "part": 4}
    ],
    "par_fonds": null,
    "par_canal": [
      {
        "canal": "en_ligne",
        "libelle": "En ligne",
        "total": 356000,
        "nombre": 47,
        "part": 29,
        "sources": [
          {"source": "app_ios", "libelle": "App iOS", "total": 62000, "nombre": 8, "part": 17},
          {"source": "app_android", "libelle": "App Android", "total": 199000, "nombre": 26, "part": 56},
          {"source": "web", "libelle": "Site", "total": 96000, "nombre": 13, "part": 27}
        ]
      },
      {"canal": "especes", "libelle": "Espèces", "total": 859000, "nombre": 9, "part": 71, "sources": []}
    ],
    "par_moyen": [
      {"moyen": "wave", "libelle": "Wave", "total": 208000, "nombre": 29, "part": 58},
      {"moyen": "orange_money", "libelle": "Orange Money", "total": 106000, "nombre": 14, "part": 30},
      {"moyen": "free_money", "libelle": "Free Money", "total": 0, "nombre": 0, "part": 0},
      {"moyen": "carte", "libelle": "Carte bancaire", "total": 42000, "nombre": 4, "part": 12}
    ],
    "par_lieu": null
  },
  "tendance": {
    "grain": "semaine",
    "points": [
      {
        "debut": "2026-09-01",
        "fin": "2026-09-06",
        "libelle": "au dim. 6",
        "total": 72000,
        "en_ligne": 72000,
        "especes": 0,
        "par_type_fonds": {"quete_dominicale": 3000, "quete_imperee": 0, "campagne": 61000, "contribution_annuelle": 8000}
      },
      {
        "debut": "2026-09-07",
        "fin": "2026-09-13",
        "libelle": "au dim. 13",
        "total": 84000,
        "en_ligne": 84000,
        "especes": 0,
        "par_type_fonds": {"quete_dominicale": 3000, "quete_imperee": 0, "campagne": 71000, "contribution_annuelle": 10000}
      },
      {
        "debut": "2026-09-14",
        "fin": "2026-09-20",
        "libelle": "au dim. 20",
        "total": 298000,
        "en_ligne": 85000,
        "especes": 213000,
        "par_type_fonds": {"quete_dominicale": 216000, "quete_imperee": 0, "campagne": 64000, "contribution_annuelle": 18000}
      },
      {
        "debut": "2026-09-21",
        "fin": "2026-09-27",
        "libelle": "au dim. 27",
        "total": 761000,
        "en_ligne": 115000,
        "especes": 646000,
        "par_type_fonds": {"quete_dominicale": 39000, "quete_imperee": 675000, "campagne": 40000, "contribution_annuelle": 8000}
      }
    ]
  },
  "a_traiter": [
    {
      "type": "quete_a_confirmer",
      "echeance": "2026-09-29",
      "libelle": "Saint-Dominique : 1 quête(s) à confirmer",
      "nombre": 1,
      "montant": null,
      "depuis": null,
      "paroisse": {"id": "5d000000-0000-4000-8000-00000000000d", "nom": "Saint-Dominique"},
      "objet_id": null
    },
    {
      "type": "remise_curie",
      "echeance": "2026-10-04",
      "libelle": "Quête impérée · Grand Séminaire de Brin : espèces de Saint-Dominique à remettre",
      "nombre": 1,
      "montant": 646000,
      "depuis": null,
      "paroisse": {"id": "5d000000-0000-4000-8000-00000000000d", "nom": "Saint-Dominique"},
      "objet_id": "00000000-0000-4000-8000-000000000002"
    }
  ],
  "paroisses": {
    "compteurs": {"engagees": 5, "collecte_ouverte": 1, "en_preparation": 4},
    "lignes": [
      {
        "id": "00000000-0000-4000-8000-000000000006",
        "nom": "Cathédrale Notre-Dame-des-Victoires",
        "statut_collecte": "en_preparation",
        "collecte": null,
        "part_en_ligne": null,
        "quetes_a_valider": null,
        "evolution": null
      },
      {
        "id": "00000000-0000-4000-8000-000000000007",
        "nom": "Notre-Dame des Anges de Ouakam",
        "statut_collecte": "en_preparation",
        "collecte": null,
        "part_en_ligne": null,
        "quetes_a_valider": null,
        "evolution": null
      },
      {
        "id": "5d000000-0000-4000-8000-00000000000d",
        "nom": "Saint-Dominique",
        "statut_collecte": "ouverte",
        "collecte": 1215000,
        "part_en_ligne": 29,
        "quetes_a_valider": 1,
        "evolution": null
      },
      {
        "id": "00000000-0000-4000-8000-000000000008",
        "nom": "Saint-Joseph de Médina",
        "statut_collecte": "en_preparation",
        "collecte": null,
        "part_en_ligne": null,
        "quetes_a_valider": null,
        "evolution": null
      },
      {
        "id": "00000000-0000-4000-8000-000000000009",
        "nom": "Sainte-Thérèse de Grand-Dakar",
        "statut_collecte": "en_preparation",
        "collecte": null,
        "part_en_ligne": null,
        "quetes_a_valider": null,
        "evolution": null
      }
    ]
  },
  "quetes_imperees": [
    {
      "fonds_id": "00000000-0000-4000-8000-000000000005",
      "titre": "Quête impérée · Grand Séminaire de Brin",
      "date": "2026-09-27",
      "echeance": "2026-10-04",
      "messe_anticipee_incluse": true,
      "paroisses": [
        {
          "id": "5d000000-0000-4000-8000-00000000000d",
          "nom": "Saint-Dominique",
          "en_ligne": 28525,
          "especes": 646000,
          "total": 674525,
          "remis": 0,
          "remise_declaree": 0,
          "reste_a_remettre": 646000,
          "part_remise": 0
        }
      ]
    }
  ],
  "tresorerie": null,
  "paiements": null,
  "campagnes": null,
  "notes": [
    "Les quêtes en espèces sont saisies sur Jàngu Bi depuis le 20 septembre.",
    "Comparaison avec l'an dernier disponible à partir de juin 2027.",
    "Montants arrondis au millier : la somme des lignes peut différer du total.",
    "Montants en FCFA. Aucun nom de donateur dans cette vue."
  ]
}
```

## 3. `GET /api/v1/platform/dons/activite/`

- **Droit** : `plateforme.admin` (rôle de realm `platform_admin`, MFA). Tout autre compte reçoit 403.
- **Paramètres** : `periode` (`semaine`, `mois`, `trimestre`, `annee`) et `date`, comme au §2.1. Défaut : le mois en
  cours.
- **Aucun montant.** Un test parcourt toutes les clés de la réponse et refuse `montant`, `total`, `net`, `frais`,
  `collecte`, etc.

Blocs de la réponse :

| Clé | Contenu |
|---|---|
| `paiements` | Dons en ligne **lancés** sur la période (date de création), par statut, avec `taux_confirmation` et `taux_echec`. `taux_echec` = (échoués + expirés) / lancés. `plus_ancien_en_attente` couvre toutes les périodes. |
| `delais` | Délai de confirmation (médiane et 95ᵉ centile, en secondes) des dons confirmés sur la période. Délai de reversement (moyen et médian, en jours) pour les reversements reçus sur la période. |
| `par_jour` | Un point par jour écoulé de la période, avec les nombres par statut. |
| `par_moyen` | Ordre canonique. `confirmes` et `echecs`. Le moyen n'est souvent connu qu'à la confirmation, d'où une ligne `inconnu` pour les échecs. |
| `par_source` | Ordre canonique. Lancés, confirmés, `retours` : parcours revenus sur la page de statut (`returned_at`). |
| `par_paroisse` | Paroisses engagées, **alphabétiques**. Nombres par statut, `derniere_confirmation`, `quetes_saisies`. |
| `notifications` | Notifications de l'agrégateur reçues sur la période, par statut, et `derniere_recue`. |
| `charge` | Carte jour × heure des paiements lancés : `jour_semaine` de 1 à 7 (lundi à dimanche), `heure` de 0 à 23. Seules les cases non nulles figurent. |
| `incidents` | Incidents encore ouverts, sans montant. Paiements tardifs et montants incohérents persistés (avec la référence et le nom de la paroisse), et notifications rejetées ou en erreur pour une autre cause. La liste donne les 20 plus récents. |
| `reversements` | Nombres de reversements à rapprocher et en écart. |

### 3.1 Exemple : septembre 2026

Même jeu. Les séries `par_jour` et `charge` sont abrégées par « … ».

```json
{
  "periode": {"type": "mois", "code": "2026-09", "debut": "2026-09-01", "fin": "2026-09-30", "libelle": "septembre 2026"},
  "genere_le": "2026-09-27T20:00:00Z",
  "paiements": {
    "lances": 58,
    "confirmes": 47,
    "en_attente": 3,
    "echoues": 4,
    "expires": 4,
    "rembourses": 0,
    "taux_confirmation": 81,
    "taux_echec": 14,
    "plus_ancien_en_attente": "2026-09-27T01:00:00Z"
  },
  "delais": {
    "confirmation_mediane_s": 41,
    "confirmation_p95_s": 41,
    "reversement_moyen_jours": 13,
    "reversement_median_jours": 13,
    "echantillon_confirmation": 47
  },
  "par_jour": [
    {"date": "2026-09-01", "lances": 3, "confirmes": 3, "en_attente": 0, "echoues": 0, "expires": 0},
    {"date": "2026-09-02", "lances": 1, "confirmes": 1, "en_attente": 0, "echoues": 0, "expires": 0},
    …,
    {"date": "2026-09-27", "lances": 5, "confirmes": 2, "en_attente": 3, "echoues": 0, "expires": 0}
  ],
  "par_moyen": [
    {"moyen": "wave", "libelle": "Wave", "confirmes": 29, "echecs": 0, "taux_echec": 0},
    {"moyen": "orange_money", "libelle": "Orange Money", "confirmes": 14, "echecs": 0, "taux_echec": 0},
    {"moyen": "free_money", "libelle": "Free Money", "confirmes": 0, "echecs": 0, "taux_echec": null},
    {"moyen": "carte", "libelle": "Carte bancaire", "confirmes": 4, "echecs": 0, "taux_echec": 0},
    {"moyen": "inconnu", "libelle": "Inconnu", "confirmes": 0, "echecs": 8, "taux_echec": 100}
  ],
  "par_source": [
    {"source": "app_ios", "libelle": "App iOS", "lances": 12, "confirmes": 8, "taux_confirmation": 67, "retours": 0, "taux_retour": 0},
    {"source": "app_android", "libelle": "App Android", "lances": 29, "confirmes": 26, "taux_confirmation": 90, "retours": 0, "taux_retour": 0},
    {"source": "web", "libelle": "Site", "lances": 17, "confirmes": 13, "taux_confirmation": 76, "retours": 0, "taux_retour": 0}
  ],
  "par_paroisse": [
    {
      "id": "00000000-0000-4000-8000-000000000006",
      "nom": "Cathédrale Notre-Dame-des-Victoires",
      "collecte_ouverte": false,
      "lances": 0,
      "confirmes": 0,
      "en_attente": 0,
      "echoues": 0,
      "expires": 0,
      "taux_confirmation": null,
      "derniere_confirmation": null,
      "quetes_saisies": 0
    },
    {
      "id": "00000000-0000-4000-8000-000000000007",
      "nom": "Notre-Dame des Anges de Ouakam",
      "collecte_ouverte": false,
      "lances": 0,
      "confirmes": 0,
      "en_attente": 0,
      "echoues": 0,
      "expires": 0,
      "taux_confirmation": null,
      "derniere_confirmation": null,
      "quetes_saisies": 0
    },
    {
      "id": "5d000000-0000-4000-8000-00000000000d",
      "nom": "Saint-Dominique",
      "collecte_ouverte": true,
      "lances": 58,
      "confirmes": 47,
      "en_attente": 3,
      "echoues": 4,
      "expires": 4,
      "taux_confirmation": 81,
      "derniere_confirmation": "2026-09-27T16:08:00Z",
      "quetes_saisies": 10
    },
    {
      "id": "00000000-0000-4000-8000-000000000008",
      "nom": "Saint-Joseph de Médina",
      "collecte_ouverte": false,
      "lances": 0,
      "confirmes": 0,
      "en_attente": 0,
      "echoues": 0,
      "expires": 0,
      "taux_confirmation": null,
      "derniere_confirmation": null,
      "quetes_saisies": 0
    },
    {
      "id": "00000000-0000-4000-8000-000000000009",
      "nom": "Sainte-Thérèse de Grand-Dakar",
      "collecte_ouverte": false,
      "lances": 0,
      "confirmes": 0,
      "en_attente": 0,
      "echoues": 0,
      "expires": 0,
      "taux_confirmation": null,
      "derniere_confirmation": null,
      "quetes_saisies": 0
    }
  ],
  "notifications": {"recues": 0, "traitees": 0, "doublons": 0, "rejetees": 0, "erreurs": 0, "en_cours": 0, "derniere_recue": null},
  "charge": [
    {"jour_semaine": 1, "heure": 11, "nombre": 1},
    {"jour_semaine": 1, "heure": 16, "nombre": 1},
    {"jour_semaine": 1, "heure": 18, "nombre": 1},
    …
  ],
  "incidents": {"ouverts": 0, "par_type": {}, "liste": []},
  "reversements": {"a_rapprocher": 0, "en_ecart": 0}
}
```

## 4. Écarts entre le jeu d'exemple et la spec §2

Ces écarts viennent des données fictives. La forme de la réponse n'est pas en cause.

- **Frais couverts.** Le jeu ne contient aucun don dont le donateur couvre les frais : `dons_frais_couverts` vaut 0,
  alors que la spec en compte 12 sur 47. C'est ce qui permet d'avoir « payé » = « donné » = 356 330, comme dans la
  spec. Quand un donateur couvre les frais, `paye` dépasse `en_ligne` du montant de ces frais.
- **Projection de la campagne.** Elle est calculée au 27 septembre : 1 988 471 FCFA. La spec, arrêtée au 28, donne
  ≈ 1 978 000. Le rythme est le même : 59 100 FCFA par semaine.
- **Comparaison avec l'an dernier.** La note annonce « juin 2027 », parce que la campagne a reçu des dons en ligne dès
  juin. La spec disait « septembre 2027 ».
- **Délais et notifications.** Le délai de confirmation est constant dans le jeu (41 s) ; le 95ᵉ centile vaut donc
  aussi 41 s, contre 5 min 30 dans la spec. Le délai de reversement ressort à 13 jours, contre 9. Le jeu ne contient
  aucune notification de l'agrégateur, alors que la spec en compte 131.

## 5. Endpoints voisins livrés dans le lot A2

Tous exigent une nomination sur la paroisse même, sauf mention contraire. Tous figurent dans `schema.yml`.

| Endpoint | Rôle |
|---|---|
| `POST /dons/checkout/` | Nouveaux champs facultatifs. `source` : `app_ios`, `app_android`, `web`, `qr` ou `inconnu` ; l'app relaie `?src=`. `place_id` : lieu du QR code, sinon le lieu du fonds. |
| `GET /staff/dons/synthese/` | Corrigé : date de valeur ; `daily[]` = `{date, online, cash, total}` ; `online_count` et `cash_collections_count` ; `count` obsolète mais conservé ; `by_fund[].destination` ; `by_destination` ; `pending_count` limité au mois ; `pending_oldest_at` ; `closed` ; `closed_at`. |
| `GET/POST /staff/dons/depots/` | Dépôt bancaire de quêtes validées. Le montant est la somme des quêtes ; une quête ne se dépose qu'une fois. |
| `GET/POST /staff/dons/remises-curie/` | La paroisse déclare la remise à la curie des espèces d'une quête impérée. Avec `?node=<diocèse>`, liste de la curie. |
| `POST /staff/dons/remises-curie/{id}/confirmer/`, `…/contester/` | La curie confirme ou conteste la remise (`dons.definir_quete_imperee`). La personne qui confirme n'est pas celle qui a déclaré. |
| `GET/POST /staff/dons/clotures/` | Clôture d'un mois écoulé, avec les totaux figés. Une tâche quotidienne clôt automatiquement à partir du 10, s'il ne reste aucune quête à confirmer. |
| `GET/POST /staff/dons/ajustements/` | Écriture de correction, signée et datée du jour. C'est la seule façon de corriger un mois clos. |
| `GET /staff/dons/incidents/`, `POST …/{id}/regulariser/` | Paiements tardifs et montants incohérents. Régularisation : `integre` (confirme le don), `rembourse` ou `sans_suite`. |
| `POST /staff/dons/operations/{id}/donateur/` | Anonymat partiel. Réservé au curé, avec un `motif` d'au moins 10 caractères. Chaque consultation est journalisée (`AuditEvent` `dons.anonymat_consultation`). |
| `GET /staff/dons/quetes/fonds-proposes/?node=&date=` | Fonds proposés pour saisir la quête d'une messe. La quête impérée vient d'abord ; la messe anticipée de la veille n'y entre que si `messe_anticipee_incluse` est vrai. |
| `POST /staff/dons/quetes-imperees/` | Nouveaux champs `remit_by` et `messe_anticipee_incluse`. Tous deux sont décidés par le diocèse, quête par quête. |
