# Tableaux de bord — contrat d'API

`GET /api/v1/dashboards/nodes/<node_id>/?period=7|30|90|365` (capacité `tableau_bord.voir` sur le
nœud, héritée sur le sous-arbre) et `GET /api/v1/dashboards/platform/` (`plateforme.admin`).
Agrégats seulement, **aucune donnée nominative**, quel que soit le niveau (RG-09, RG-11). Réponse
mise en cache 5 minutes.

## Bloc `fideles` (paroisses multiples, décisions 6-8 du 29/09/2026)

Un fidèle est rattaché au sous-arbre dès qu'il est membre d'une paroisse du sous-arbre, en
**principal** ou en **secondaire** (`ParishMembership` active : ni quittée, ni retirée par la
paroisse). Chaque personne n'est comptée qu'une fois, même membre de plusieurs paroisses du
sous-arbre.

| Clé | Sens |
|---|---|
| `attached` | Fidèles rattachés (`primary` + `secondary`) |
| `primary` | Fidèles dont la paroisse **principale** est dans le sous-arbre |
| `secondary` | Membres d'au moins une paroisse du sous-arbre dont la principale est ailleurs (ou qui n'en ont pas) |
| `active` | Parmi `attached`, vus sur la période (`last_seen_on` ou dernière connexion) |
| `new` | Parmi `attached`, appartenance au sous-arbre prise sur la période |

- Pour une **paroisse**, `primary` et `secondary` sont exactement ses membres principaux et
  secondaires.
- Au-dessus (doyenné, zone, diocèse), un fidèle principal à Saint-Dominique et secondaire à
  Sainte-Thérèse (même doyenné) compte une fois, en `primary`.
- Un compte dont `paroisse_suivie` a été écrit hors des services (sans ligne d'appartenance) compte
  comme principal, comme dans `selectors_memberships.memberships_of`.
- La liste nominative des membres reste réservée à la paroisse (`GET /api/v1/hierarchy/nodes/<id>/membres/`,
  capacité `paroissiens.gerer`).

Exemple (paroisse Saint-Dominique, 30 jours) :

```json
"fideles": {"attached": 3, "primary": 2, "secondary": 1, "active": 3, "new": 3}
```

Les autres blocs (`annonces`, `evenements`, `actes`, `messagerie`, `confessions`) sont inchangés ;
la messagerie rattache encore une conversation au sous-arbre par la paroisse principale
(`paroisse_suivie`) d'un participant.
