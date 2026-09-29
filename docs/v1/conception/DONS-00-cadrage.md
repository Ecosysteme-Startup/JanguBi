# DONS-00 — Cadrage du module Dons et quêtes

> Version du 27/09/2026. Branche `feat/v1-dons`. Sources : `docs/design/dons-quetes-etude.md`, `docs/design/PROMPTS-DONS.md` (prompt 3).
> Décision de principe : ADR-017 (`docs/v1/03-DECISIONS-ADR.md`), qui réintègre les dons dans le périmètre (SRS §1.3 amendé).

## 1. Hypothèses retenues (H1 à H4, validées le 27/09/2026)

| # | Hypothèse | Conséquence dans le code |
|---|---|---|
| H1 | L'**archidiocèse** (économat) est titulaire du compte marchand chez l'agrégateur ; chaque paroisse a une clé d'affectation. Numerisen ne détient jamais les fonds. | Les **reversements** (`Payout`) de l'agrégateur sont rattachés au **diocèse**. La paroisse voit ce qui lui est **affecté** (dons confirmés nets), pas les virements bancaires. Le rapprochement se fait au diocèse. `DonationActivation.allocation_key` porte la clé d'affectation transmise à l'agrégateur. |
| H2 | Types : quête dominicale, quêtes impérées (reversées à la curie), campagnes de projet, contribution annuelle. Offrandes de messe **exclues**. | `Fund.kind` ∈ {`quete_dominicale`, `quete_imperee`, `campagne`, `contribution_annuelle`} ; aucun type « messe ». Une quête impérée a toujours la destination `curie` (contrainte en base). |
| H3 | Frais affichés, le donateur choisit de les couvrir (décoché par défaut) ; sinon déduits. Pas de commission Numerisen. | Trois montants stockés : `amount` (le don choisi), `fee_amount`, `charged_amount` (payé), `net_amount` (affecté au fonds). Taux estimé `DONATIONS_FEE_RATE_BP` ; frais réels repris de l'agrégateur à la confirmation s'il les communique. |
| H4 | Autorisation écrite de l'archevêché supposée obtenue pour le pilote. | `DonationActivation` par paroisse : `authorization_ref`, `authorization_date`, texte de mention exposé par l'API publique. **Aucune collecte sans activation** du nœud. |

Décisions complémentaires prises au cadrage (réponse du 27/09) :

- **Reçu** : reçu **simple** (« Reçu de don »), PDF, disponible **uniquement** pour un don confirmé ; jamais de reçu fiscal dans cette version.
- **Capacités** : les noms du prompt back font foi partout (`dons.gerer_fonds`, pas `dons.gerer`).
- **Don sans compte** : adresse e-mail facultative, utilisée seulement pour envoyer le reçu, **effacée 90 jours** après la fin du paiement (tâche quotidienne).

## 2. Existant : ce qui se garde, ce qui se refait

L'étude dit « à adapter, pas à refaire », mais l'app `donations` et `mass_intentions` ont été **supprimées le 25/09/2026** (ADR-016, migrations remises à zéro). Il n'y a ni code, ni table, ni donnée.

| Élément du prompt | Traitement |
|---|---|
| « Réactiver le module gelé » | Nouvelle app `apps/donations`, bâtie sur `hierarchy.Node`, les offices et `peut()`. L'ancien code (`DonationCampaign`, `Donation`) n'est qu'une lecture dans l'historique Git (avant `7cd68a9`). |
| « Lire `apps/mass_intentions` » | Sans objet (supprimée). Les honoraires de messe restent hors module. |
| « Retirer l'offrande de messe (expand/contract) » | Sans objet : aucune table à migrer. On ne crée simplement **aucun** type « offrande de messe ». |
| Moyens Wave / Orange Money / Free Money / espèces | Gardés comme **moyens constatés** (`payment_method`) ; le moyen en ligne est choisi sur la page de l'agrégateur, jamais dans Jàngu Bi. |

## 3. Modèle

```
DonationActivation : node (paroisse, unique), enabled, authorization_ref, authorization_date, authorization_text, allocation_key, receipt_prefix
ReceiptSequence : node, year, last_number (verrouillée à chaque attribution : série sans trou)
Fund       : id UUID, node FK (paroisse ou diocèse), kind, destination[paroisse|curie], title, description (usage des fonds),
             starts_on?, ends_on?, goal_amount?, status[brouillon|ouvert|clos], parent FK self? (déclinaison d'une quête impérée),
             decided_by FK person?, decided_by_office (code), authorization_ref, image FK File?, published_at?
FundUpdate : fund FK, author FK, body, created_at                       (« nouvelles du curé » d'une campagne)
Donation   : id UUID, reference unique « 4817-2093-6651 » (aléatoire), receipt_number unique « SD-2026-00147 »
             (série continue par paroisse et par an, attribuée à la confirmation), fund FK PROTECT (immuable), amount, fee_amount, fees_covered,
             charged_amount, net_amount, anonymous, donor FK person?, donor_email?, channel[en_ligne|especes],
             payment_method[wave|orange_money|free_money|carte|especes|autre|inconnu], status, status_changed_at,
             confirmed_at?, cash_collection FK?, payout FK?
DonationStatusChange : donation FK, from_status, to_status, source[checkout|webhook|reconciliation|staff|system], actor?, note, at
PaymentAttempt : donation FK, provider, external_ref unique, idempotency_key unique, checkout_url, status, raw_payload (chiffré),
                 expires_at?, last_checked_at?
PaymentWebhookEvent : provider, payload_hash unique, external_ref, signature_valid, status[recu|traite|doublon|rejete|erreur],
                      error_code, payload (chiffré), received_at, processed_at?
CashCollection : node FK (paroisse), fund FK, mass_date, mass_label, place FK?, amount, counter_one, counter_two,
                 observation, status[saisie|validee|rejetee], entered_by FK, validated_by FK?, validated_at?
Payout     : provider, external_ref unique, node FK (diocèse, H1), paid_at, gross_amount, fee_amount, net_amount,
             status[recu|rapproche|ecart], discrepancy_amount, unmatched_count
PayoutLine : payout FK, external_ref, amount, fee_amount, attempt FK?   (une ligne = une transaction de l'agrégateur)
```

Invariants (tests) :

- `Donation.fund` ne change jamais (c. 1267 §3) : aucun service ni aucune API ne le modifie, et l'admin des dons est en lecture seule.
- Montants entiers en FCFA, `DONATIONS_MIN_AMOUNT ≤ amount ≤ DONATIONS_MAX_AMOUNT` ; contraintes en base (`> 0`, `net ≤ charged`).
- Une quête impérée a la destination `curie` ; sa déclinaison paroissiale a pour parent la quête diocésaine.
- On ne donne qu'à un fonds **ouvert**, dans sa période, sur une paroisse **activée**.
- Une campagne se **ferme d'elle-même** dès que l'objectif est atteint (décision du 27/09/2026).
- Un remboursement garde son numéro de reçu : la série ne comporte ni trou ni réemploi.

## 4. Cycle de vie du don (SRS §8.4)

```
initie ──checkout créé──▶ en_attente ──webhook confirmé──▶ confirme ──remboursement (staff)──▶ rembourse
  │                          ├──webhook échec / annulé──▶ echoue
  │                          └──délai dépassé (tâche)────▶ expire
  └──échec de création du checkout──▶ echoue
especes : créé directement « confirme » à la validation d'une saisie de quête (source staff).
```

- Transition stricte (`TRANSITIONS`), journalisée (`DonationStatusChange`) ; `rembourse` écrit aussi un `AuditEvent`.
- **Confirmation uniquement par le serveur** : webhook signé **puis** contre-vérification `fetch_status` auprès de l'agrégateur, ou tâche de réconciliation. Le retour du navigateur n'a aucun effet sur le statut.
- Rejeu du webhook : même corps → `doublon` (empreinte unique) ; autre corps pour un don déjà confirmé → no-op. Aucun double comptage.
- Montant confirmé différent du montant attendu → le don reste `en_attente`, l'événement passe en `erreur` (`amount_mismatch`) et apparaît dans la santé plateforme.

## 5. Paiement

- Interface `PaymentProvider` : `create_checkout`, `verify_callback`, `fetch_status`, `list_payouts` (`apps/donations/providers/`).
- `FakeProvider` (tests, CI, démo locale) : signature HMAC-SHA256 (`X-Fake-Signature`), états pilotables.
- `PayDunyaProvider` : API « checkout-invoice » (création, confirmation par jeton), IPN vérifiée par l'empreinte SHA-512 de la clé maître **et** par une confirmation serveur à serveur. Clés en variables d'environnement (`PAYDUNYA_*`). **À valider** contre le contrat et la documentation à jour de PayDunya avant la mise en production ; `list_payouts` renvoie une liste vide tant qu'aucune API de relevé n'est confirmée (rapprochement alors manuel).
- Fournisseur choisi par `DONATIONS_PROVIDER` (`fake` par défaut hors production ; la production refuse `fake`).
- **KYC** : entièrement chez l'agrégateur (identification selon les seuils de l'instruction BCEAO et des émetteurs de monnaie électronique). Jàngu Bi applique seulement un **plafond par don** `DONATIONS_MAX_AMOUNT` (défaut 1 000 000 FCFA) et un plancher `DONATIONS_MIN_AMOUNT` (défaut 100 FCFA), à aligner sur le contrat.
- **iOS / Android** : aucun paiement dans l'app ; l'app ouvre la page publique de don dans le navigateur externe. Le retour se fait par l'URL `DONATIONS_RETURN_URL` (lien universel côté front), qui ne fait qu'**afficher** le statut.

## 6. Accès (capacités, catalogue fermé)

| Capacité | Sens |
|---|---|
| `dons.voir_fonds` | Voir les fonds, la synthèse et les opérations (noms masqués) d'une paroisse |
| `dons.gerer_fonds` | Créer, publier, clore les fonds et campagnes ; marquer un remboursement |
| `dons.saisir_quete` | Saisir et valider (seconde personne) les quêtes en espèces |
| `dons.voir_donateurs` | Voir le nom des donateurs non anonymes |
| `dons.exporter` | Export comptable et rapprochement de la paroisse |
| `dons.definir_quete_imperee` | Définir une quête impérée et suivre les agrégats par paroisse (diocèse) |

| Office | Capacités « dons » |
|---|---|
| `cure`, `cure_in_solidum` | voir_fonds, gerer_fonds, saisir_quete, voir_donateurs, exporter |
| `econome_paroissial` (**nouvel office**, paroisse, nommé par le curé, 1) | voir_fonds, gerer_fonds, saisir_quete, voir_donateurs, exporter (+ `tableau_bord.voir`) |
| `secretaire_paroissial` | voir_fonds, saisir_quete |
| `eveque_diocesain`, `econome_diocesain` | definir_quete_imperee |

Règle « agrégats au-dessus de la paroisse » : les capacités de lecture fines (`voir_fonds`, `voir_donateurs`, `exporter`) ne valent que si la nomination est **sur la paroisse elle-même** (type `paroisse` ou `quasi_paroisse`), jamais héritée d'un diocèse ou d'un doyenné (`apps/donations/access.py`). Le diocèse ne voit que des sommes par paroisse. L'évêque n'a **pas** `dons.voir_donateurs` (retiré de « toutes les capacités »). La plateforme n'a aucune capacité « dons » ; elle voit la santé technique (`plateforme.admin`), sans montant par donateur ni nom.

## 7. API (préfixe `/api/v1/`)

| Méthode et chemin | Accès |
|---|---|
| `GET public/dons/paroisses/{node_id}/` (activation, mention, montants suggérés, taux de frais, fonds ouverts) | public |
| `GET public/dons/fonds/{fund_id}/` (détail, montant réuni, nouvelles) | public |
| `POST dons/checkout/` (en-tête `Idempotency-Key` facultatif) | public (compte facultatif), limité en débit |
| `GET dons/checkout/{donation_id}/` (statut après retour) | public, identifiant non devinable |
| `POST dons/webhooks/{provider}/` | agrégateur (signature) |
| `GET me/dons/?fund=&year=` · `GET me/dons/resume/?year=` · `GET me/dons/{id}/recu/` | fidèle |
| `GET/POST staff/dons/fonds/?node=` · `GET/PATCH staff/dons/fonds/{id}/` · `POST …/{id}/publier/` · `POST …/{id}/clore/` · `POST …/{id}/nouvelles/` | `dons.voir_fonds` / `dons.gerer_fonds` |
| `GET staff/dons/synthese/?node=&month=` · `GET staff/dons/operations/?node=&fund=&status=&from=&to=` · `POST staff/dons/operations/{id}/rembourser/` | `dons.voir_fonds` / `dons.gerer_fonds` |
| `GET/POST staff/dons/quetes/?node=` · `POST staff/dons/quetes/{id}/valider/` · `POST …/{id}/rejeter/` | `dons.saisir_quete` |
| `GET staff/dons/export/?node=&from=&to=&fund=&fichier=csv|xlsx` · `GET staff/dons/rapprochement/?node=&from=&to=` | `dons.exporter` |
| `GET/POST staff/dons/quetes-imperees/?node=` · `GET staff/dons/quetes-imperees/{id}/suivi/` · `GET staff/dons/reversements/?node=` | `dons.definir_quete_imperee` |
| `GET platform/dons/sante/` | `plateforme.admin` |

Drapeau : module `donations` dans `JANGUBI_MODULES` (actif par défaut) **et** activation par nœud (`DonationActivation`, pilote Saint-Dominique dans `seed_demo`).

## 8. Données sensibles (loi 2008-12)

- Aucun montant, nom ni e-mail dans les logs ; les payloads de l'agrégateur sont chiffrés au repos (Fernet, clé dérivée de `DONATIONS_PAYLOAD_KEY` ou de `SECRET_KEY`).
- Anonymat : un don anonyme n'expose jamais le donateur, même à `dons.voir_donateurs` ; il reste visible du seul donateur dans « Mes dons ».
- Aucun classement ni liste publique : l'API publique ne renvoie que des totaux par fonds.
- Garde c. 848 : aucune dépendance entre `donations` et `documents`, `messaging`, `confessions` (test d'imports dans les deux sens).

## 9. Écarts avec le SRS et suites

- SRS §1.3 amendé (dons retirés du hors-périmètre), §6.2 (6 capacités), §6.3 (office `econome_paroissial`, capacités ajoutées), §7 (routes ci-dessus), §8.4 (cycle du don).
- À valider par le porteur : taux de frais réel, plafonds, texte exact de la mention d'autorisation, choix définitif de l'agrégateur, format de la clé d'affectation.
- Front : feature `dons` à dégeler (ADR-F12) une fois les maquettes validées ; maquettes en attente du kit `docs/design/jangubi-kit-maquettes/`.
