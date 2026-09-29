"""Contrat JSON des endpoints d'analyse des dons (V2). Documenté dans ``docs/API-DONS-ANALYSE.md`` :
toute modification de forme est une rupture pour le mobile et le web.

Conventions : montants entiers en FCFA ; ``part`` = pourcentage entier (``null`` si le total est nul) ;
au-dessus de la paroisse, les montants de ``synthese``, ``tendance`` et ``paroisses`` sont arrondis au
millier (``confidentialite.arrondi``) ; clés toujours présentes, ``null`` quand le bloc ne s'applique pas
au niveau demandé.
"""

from rest_framework import serializers

from apps.donations.enums import DonationChannel, DonationSource, FundKind, PaymentMethod

LEVELS = [("paroisse", "Paroisse (montants exacts)"), ("diocese", "Diocèse ou doyenné (agrégats arrondis)")]
PERIODS = [("semaine", "Semaine ISO (paroisse)"), ("mois", "Mois"), ("trimestre", "Trimestre"), ("annee", "Année")]
TODO_TYPES = [
    ("quete_a_confirmer", "Quête en espèces à confirmer (second compteur) — échéance : messe + 48 h"),
    ("paiements_en_attente", "Paiements en ligne en attente — échéance : expiration du plus ancien"),
    ("paiement_tardif", "Paiement tardif à régulariser — échéance : détection + 7 jours"),
    ("especes_a_deposer", "Espèces validées à déposer en banque — échéance : plus ancienne messe + 7 jours"),
    ("remise_curie", "Espèces de quête impérée à remettre à la curie — échéance : Fund.remit_by"),
    ("remise_a_confirmer", "Remise à la curie à confirmer (diocèse) — échéance : remise + 7 jours"),
    ("cloture_mois", "Mois à clore — échéance : jour DONATIONS_MONTH_CLOSE_DAY du mois suivant"),
]


class AnalyseQuerySerializer(serializers.Serializer):
    niveau = serializers.ChoiceField(choices=LEVELS)
    noeud = serializers.UUIDField(help_text="Paroisse (niveau=paroisse) ; diocèse ou doyenné (niveau=diocese)")
    periode = serializers.ChoiceField(choices=PERIODS, default="mois")
    date = serializers.CharField(
        required=False, allow_blank=True, default="",
        help_text="mois : AAAA-MM · trimestre : AAAA-Tn · annee : AAAA · semaine : AAAA-Www. Défaut : période en cours.",
    )  # fmt: skip


class NoeudSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    nom = serializers.CharField()
    type = serializers.CharField(help_text="Code du type de nœud : paroisse, diocese, doyenne…")


class PeriodeSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=PERIODS)
    code = serializers.CharField(help_text="Ex. 2026-09")
    debut = serializers.DateField()
    fin = serializers.DateField(help_text="Inclus")
    libelle = serializers.CharField(help_text="Ex. « septembre 2026 »")


class ConfidentialiteSerializer(serializers.Serializer):
    arrondi = serializers.IntegerField(help_text="1 (paroisse, exact) ou 1000 (au-dessus de la paroisse)")
    noms_donateurs = serializers.BooleanField(help_text="Toujours false")
    ordre_paroisses = serializers.CharField(help_text="Toujours « alphabetique »")
    tri_par_montant = serializers.BooleanField(help_text="Toujours false")


class DestinationSerializer(serializers.Serializer):
    paroisse = serializers.IntegerField()
    curie = serializers.IntegerField(help_text="Quêtes impérées (c. 1266)")


class TypeFondsLigneSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=FundKind.choices)
    libelle = serializers.CharField()
    en_ligne = serializers.IntegerField()
    especes = serializers.IntegerField()
    total = serializers.IntegerField()
    nombre = serializers.IntegerField(help_text="Dons en ligne + quêtes (ne pas en tirer de don moyen)")
    part = serializers.IntegerField(allow_null=True)


class FondsLigneSerializer(serializers.Serializer):
    fonds_id = serializers.UUIDField()
    titre = serializers.CharField()
    type = serializers.ChoiceField(choices=FundKind.choices)
    destination = serializers.CharField()
    en_ligne = serializers.IntegerField()
    especes = serializers.IntegerField()
    total = serializers.IntegerField()
    nombre = serializers.IntegerField()
    part = serializers.IntegerField(allow_null=True)


class SourceLigneSerializer(serializers.Serializer):
    source = serializers.ChoiceField(choices=DonationSource.choices)  # type: ignore[assignment]  # clé « source »
    libelle = serializers.CharField()
    total = serializers.IntegerField()
    nombre = serializers.IntegerField()
    part = serializers.IntegerField(allow_null=True, help_text="Part du total en ligne")


class CanalLigneSerializer(serializers.Serializer):
    canal = serializers.ChoiceField(choices=DonationChannel.choices)
    libelle = serializers.CharField()
    total = serializers.IntegerField()
    nombre = serializers.IntegerField()
    part = serializers.IntegerField(allow_null=True)
    sources = SourceLigneSerializer(many=True, help_text="Ventilation du canal en ligne (vide pour les espèces)")


class MoyenLigneSerializer(serializers.Serializer):
    moyen = serializers.ChoiceField(choices=PaymentMethod.choices)
    libelle = serializers.CharField()
    total = serializers.IntegerField()
    nombre = serializers.IntegerField()
    part = serializers.IntegerField(allow_null=True, help_text="Part du total en ligne")


class LieuLigneSerializer(serializers.Serializer):
    lieu_id = serializers.IntegerField(allow_null=True, help_text="null : « Lieu non renseigné »")
    nom = serializers.CharField()
    en_ligne = serializers.IntegerField()
    especes = serializers.IntegerField()
    total = serializers.IntegerField()
    nombre = serializers.IntegerField()
    part = serializers.IntegerField(allow_null=True)


class SyntheseSerializer(serializers.Serializer):
    collecte = serializers.IntegerField(help_text="Montant donné, dons confirmés, sur la date de valeur")
    en_ligne = serializers.IntegerField()
    especes = serializers.IntegerField()
    nombre_dons_en_ligne = serializers.IntegerField()
    nombre_quetes = serializers.IntegerField()
    par_destination = DestinationSerializer()
    par_type_fonds = TypeFondsLigneSerializer(many=True, help_text="Ordre fixe de la palette : dominicale, impérée, campagne, contribution")
    par_fonds = FondsLigneSerializer(many=True, allow_null=True, help_text="Paroisse seulement ; null au-dessus")
    par_canal = CanalLigneSerializer(many=True, help_text="En ligne (avec ses sources), puis espèces")
    par_moyen = MoyenLigneSerializer(many=True, help_text="En ligne ; ordre canonique Wave, Orange Money, Free Money, carte")
    par_lieu = LieuLigneSerializer(many=True, allow_null=True, help_text="Paroisse seulement ; null au-dessus")


class TypeFondsMontantsSerializer(serializers.Serializer):
    quete_dominicale = serializers.IntegerField()
    quete_imperee = serializers.IntegerField()
    campagne = serializers.IntegerField()
    contribution_annuelle = serializers.IntegerField()


class TendancePointSerializer(serializers.Serializer):
    debut = serializers.DateField()
    fin = serializers.DateField()
    libelle = serializers.CharField(help_text="Ex. « au dim. 6 »")
    total = serializers.IntegerField()
    en_ligne = serializers.IntegerField()
    especes = serializers.IntegerField()
    par_type_fonds = TypeFondsMontantsSerializer()


class TendanceSerializer(serializers.Serializer):
    grain = serializers.ChoiceField(choices=[("jour", "jour"), ("semaine", "semaine"), ("mois", "mois")])
    points = TendancePointSerializer(many=True, help_text="Sous-périodes déjà commencées, dans l'ordre du calendrier")


class ParoisseBriefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    nom = serializers.CharField()


class ATraiterSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=TODO_TYPES)
    echeance = serializers.DateField(help_text="Tri croissant ; la plus proche en premier")
    libelle = serializers.CharField()
    nombre = serializers.IntegerField()
    montant = serializers.IntegerField(allow_null=True)
    depuis = serializers.DateTimeField(allow_null=True)
    paroisse = ParoisseBriefSerializer(allow_null=True)
    objet_id = serializers.CharField(allow_null=True, help_text="Quête, fonds, remise ou incident concerné")


class ParoisseLigneSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    nom = serializers.CharField()
    statut_collecte = serializers.ChoiceField(choices=[("ouverte", "Collecte ouverte"), ("en_preparation", "En préparation")])
    collecte = serializers.IntegerField(allow_null=True, help_text="Arrondi au millier ; null en préparation")
    part_en_ligne = serializers.IntegerField(allow_null=True)
    quetes_a_valider = serializers.IntegerField(allow_null=True)
    evolution = serializers.ChoiceField(
        choices=[("stable", "stable"), ("en_hausse", "en hausse"), ("en_baisse", "en baisse")], allow_null=True,
        help_text="La paroisse face à elle-même (trois périodes précédentes) ; null sans historique",
    )  # fmt: skip


class ParoissesCompteursSerializer(serializers.Serializer):
    engagees = serializers.IntegerField()
    collecte_ouverte = serializers.IntegerField()
    en_preparation = serializers.IntegerField()


class ParoissesSerializer(serializers.Serializer):
    compteurs = ParoissesCompteursSerializer()
    lignes = ParoisseLigneSerializer(many=True, help_text="Ordre alphabétique imposé")


class ImpereeParoisseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    nom = serializers.CharField()
    en_ligne = serializers.IntegerField()
    especes = serializers.IntegerField()
    total = serializers.IntegerField()
    remis = serializers.IntegerField(help_text="Remises confirmées par la curie")
    remise_declaree = serializers.IntegerField(help_text="Remises déclarées, non encore confirmées")
    reste_a_remettre = serializers.IntegerField()
    part_remise = serializers.IntegerField(allow_null=True)


class QueteImpereeSerializer(serializers.Serializer):
    fonds_id = serializers.UUIDField()
    titre = serializers.CharField()
    date = serializers.DateField()
    echeance = serializers.DateField(allow_null=True)
    messe_anticipee_incluse = serializers.BooleanField()
    paroisses = ImpereeParoisseSerializer(many=True, help_text="Montants exacts (argent de la curie) ; ordre alphabétique")


class TresorerieEnLigneSerializer(serializers.Serializer):
    paye = serializers.IntegerField()
    frais = serializers.IntegerField()
    frais_reels = serializers.IntegerField(help_text="Part des frais transmise par l'agrégateur (le reste est estimé)")
    net = serializers.IntegerField()
    reverse = serializers.IntegerField(help_text="Net inclus dans un reversement de l'agrégateur")
    en_attente_reversement = serializers.IntegerField()
    part_reversee = serializers.IntegerField(allow_null=True)
    net_pour_100 = serializers.IntegerField(allow_null=True, help_text="Pour 100 FCFA payés en ligne, FCFA affectés")
    dons_frais_couverts = serializers.IntegerField()
    nombre = serializers.IntegerField()


class TresorerieEspecesSerializer(serializers.Serializer):
    validees = serializers.IntegerField()
    deposees = serializers.IntegerField()
    en_caisse = serializers.IntegerField()
    a_confirmer = serializers.IntegerField()


class TresorerieSerializer(serializers.Serializer):
    en_ligne = TresorerieEnLigneSerializer()
    especes = TresorerieEspecesSerializer()


class PaiementsSerializer(serializers.Serializer):
    lances = serializers.IntegerField()
    confirmes = serializers.IntegerField()
    en_attente = serializers.IntegerField()
    echoues = serializers.IntegerField()
    expires = serializers.IntegerField()
    taux_confirmation = serializers.IntegerField(allow_null=True)


class CampagneSerializer(serializers.Serializer):
    fonds_id = serializers.UUIDField()
    titre = serializers.CharField()
    objectif = serializers.IntegerField(allow_null=True)
    reuni = serializers.IntegerField(help_text="Cumul donné depuis l'ouverture (montant donné)")
    part = serializers.IntegerField(allow_null=True)
    nombre = serializers.IntegerField()
    periode = serializers.IntegerField(help_text="Donné sur la période analysée")
    debut = serializers.DateField(allow_null=True)
    fin = serializers.DateField(allow_null=True)
    statut = serializers.CharField()
    rythme_hebdo = serializers.IntegerField(help_text="Moyenne des quatre dernières semaines")
    projection_fin = serializers.IntegerField(allow_null=True)
    part_projection = serializers.IntegerField(allow_null=True)


class AnalyseSerializer(serializers.Serializer):
    niveau = serializers.ChoiceField(choices=LEVELS)
    noeud = NoeudSerializer()
    periode = PeriodeSerializer()
    genere_le = serializers.DateTimeField()
    confidentialite = ConfidentialiteSerializer()
    synthese = SyntheseSerializer()
    tendance = TendanceSerializer()
    a_traiter = ATraiterSerializer(many=True)
    paroisses = ParoissesSerializer(allow_null=True, help_text="Diocèse ou doyenné seulement")
    quetes_imperees = QueteImpereeSerializer(many=True)
    tresorerie = TresorerieSerializer(allow_null=True, help_text="Paroisse seulement")
    paiements = PaiementsSerializer(allow_null=True, help_text="Paroisse seulement")
    campagnes = CampagneSerializer(many=True, allow_null=True, help_text="Paroisse seulement")
    notes = serializers.ListField(child=serializers.CharField())


# --- Plateforme : GET platform/dons/activite/ (aucun montant) --------------------------------


class ActiviteQuerySerializer(serializers.Serializer):
    periode = serializers.ChoiceField(choices=PERIODS, default="mois")
    date = serializers.CharField(required=False, allow_blank=True, default="", help_text="Comme pour l'analyse")


class ActivitePaiementsSerializer(serializers.Serializer):
    lances = serializers.IntegerField(help_text="Dons en ligne créés sur la période")
    confirmes = serializers.IntegerField()
    en_attente = serializers.IntegerField()
    echoues = serializers.IntegerField()
    expires = serializers.IntegerField()
    rembourses = serializers.IntegerField()
    taux_confirmation = serializers.IntegerField(allow_null=True)
    taux_echec = serializers.IntegerField(allow_null=True, help_text="(échoués + expirés) / lancés")
    plus_ancien_en_attente = serializers.DateTimeField(allow_null=True, help_text="Toutes périodes confondues")


class ActiviteDelaisSerializer(serializers.Serializer):
    confirmation_mediane_s = serializers.IntegerField(allow_null=True)
    confirmation_p95_s = serializers.IntegerField(allow_null=True)
    reversement_moyen_jours = serializers.IntegerField(allow_null=True)
    reversement_median_jours = serializers.IntegerField(allow_null=True)
    echantillon_confirmation = serializers.IntegerField()


class ActiviteJourSerializer(serializers.Serializer):
    date = serializers.DateField()
    lances = serializers.IntegerField()
    confirmes = serializers.IntegerField()
    en_attente = serializers.IntegerField()
    echoues = serializers.IntegerField()
    expires = serializers.IntegerField()


class ActiviteMoyenSerializer(serializers.Serializer):
    moyen = serializers.ChoiceField(choices=PaymentMethod.choices)
    libelle = serializers.CharField()
    confirmes = serializers.IntegerField()
    echecs = serializers.IntegerField(help_text="Le moyen n'est souvent connu qu'à la confirmation")
    taux_echec = serializers.IntegerField(allow_null=True)


class ActiviteSourceSerializer(serializers.Serializer):
    source = serializers.ChoiceField(choices=DonationSource.choices)  # type: ignore[assignment]  # clé « source »
    libelle = serializers.CharField()
    lances = serializers.IntegerField()
    confirmes = serializers.IntegerField()
    taux_confirmation = serializers.IntegerField(allow_null=True)
    retours = serializers.IntegerField(help_text="Parcours revenus sur la page de statut (lien de retour)")
    taux_retour = serializers.IntegerField(allow_null=True)


class ActiviteParoisseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    nom = serializers.CharField()
    collecte_ouverte = serializers.BooleanField()
    lances = serializers.IntegerField()
    confirmes = serializers.IntegerField()
    en_attente = serializers.IntegerField()
    echoues = serializers.IntegerField()
    expires = serializers.IntegerField()
    taux_confirmation = serializers.IntegerField(allow_null=True)
    derniere_confirmation = serializers.DateTimeField(allow_null=True)
    quetes_saisies = serializers.IntegerField()


class ActiviteNotificationsSerializer(serializers.Serializer):
    recues = serializers.IntegerField()
    traitees = serializers.IntegerField()
    doublons = serializers.IntegerField()
    rejetees = serializers.IntegerField()
    erreurs = serializers.IntegerField()
    en_cours = serializers.IntegerField()
    derniere_recue = serializers.DateTimeField(allow_null=True)


class ActiviteChargeSerializer(serializers.Serializer):
    jour_semaine = serializers.IntegerField(help_text="1 = lundi … 7 = dimanche")
    heure = serializers.IntegerField(help_text="0 à 23, heure de Dakar")
    nombre = serializers.IntegerField()


class ActiviteIncidentSerializer(serializers.Serializer):
    type = serializers.CharField(help_text="late_payment, amount_mismatch, invalid_signature, unknown_reference…")
    reference = serializers.CharField(help_text="Référence du paiement, jamais de montant")
    paroisse = serializers.CharField(allow_null=True)
    detecte_le = serializers.DateTimeField()
    statut = serializers.CharField()


class ActiviteIncidentsSerializer(serializers.Serializer):
    ouverts = serializers.IntegerField()
    par_type = serializers.DictField(child=serializers.IntegerField())
    liste = ActiviteIncidentSerializer(many=True, help_text="Vingt plus récents")


class ActiviteReversementsSerializer(serializers.Serializer):
    a_rapprocher = serializers.IntegerField()
    en_ecart = serializers.IntegerField()


class ActiviteSerializer(serializers.Serializer):
    periode = PeriodeSerializer()
    genere_le = serializers.DateTimeField()
    paiements = ActivitePaiementsSerializer()
    delais = ActiviteDelaisSerializer()
    par_jour = ActiviteJourSerializer(many=True)
    par_moyen = ActiviteMoyenSerializer(many=True)
    par_source = ActiviteSourceSerializer(many=True)
    par_paroisse = ActiviteParoisseSerializer(many=True, help_text="Paroisses engagées, ordre alphabétique")
    notifications = ActiviteNotificationsSerializer()
    charge = ActiviteChargeSerializer(many=True, help_text="Carte jour × heure des paiements lancés (cases non nulles)")
    incidents = ActiviteIncidentsSerializer()
    reversements = ActiviteReversementsSerializer()
