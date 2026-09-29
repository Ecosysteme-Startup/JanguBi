import logging

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from pgvector.django import HnswIndex, VectorField

from apps.common.models import BaseModel

logger = logging.getLogger(__name__)


class Testament(models.Model):
    """Ancien or Nouveau Testament."""

    # Prevent pytest from mistaking this model for a test class on import.
    __test__ = False

    slug = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=200)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self) -> str:
        return self.name


class Book(BaseModel):
    """A book of the Bible (e.g. Genèse, Psaumes, Matthieu)."""

    testament = models.ForeignKey(
        Testament,
        on_delete=models.PROTECT,
        related_name="books",
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    alt_names = models.JSONField(default=list, blank=True)
    order = models.IntegerField()
    verse_count = models.IntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Chapter(models.Model):
    """A chapter within a book."""

    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name="chapters",
    )
    number = models.IntegerField()
    name = models.CharField(max_length=255, blank=True, default="")
    verse_count = models.IntegerField(default=0)

    class Meta:
        unique_together = ("book", "number")
        ordering = ["number"]

    def __str__(self) -> str:
        return f"{self.book.name} {self.number}"


class Verse(models.Model):
    """A single verse within a chapter."""

    chapter = models.ForeignKey(
        Chapter,
        on_delete=models.CASCADE,
        related_name="verses",
    )
    number = models.IntegerField()
    text = models.TextField()
    original_id = models.IntegerField(null=True, blank=True)
    original_position = models.IntegerField(null=True, blank=True)
    source_file = models.CharField(max_length=128, blank=True, null=True)

    # Postgres full-text search vector
    tsv = SearchVectorField(null=True)

    # pgvector embedding — 768 dims (modèle local mpnet-base-v2, recherche
    # sémantique cosine). Vecteurs non normalisés => on interroge en cosine
    # (<=> / vector_cosine_ops), invariant à l'échelle.
    embedding = VectorField(dimensions=768, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("chapter", "number", "source_file")
        ordering = ["number"]
        indexes = [
            GinIndex(fields=["tsv"], name="idx_verse_tsv"),
            # Index ANN cosine pour la recherche vectorielle (top-k via <=>).
            HnswIndex(
                name="idx_verse_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]

    def __str__(self) -> str:
        return f"{self.chapter} : {self.number}"


class DailyText(BaseModel):
    """Daily readings fetched from the AELF API."""

    date = models.DateField(db_index=True)
    category = models.CharField(max_length=64)  # 'messe', 'heures', 'lecture'
    title = models.CharField(max_length=255, blank=True, default="")
    content = models.TextField()
    source_url = models.URLField(blank=True, null=True)

    # Cross-references to matched verses, populated by SearchService
    local_matches = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self) -> str:
        return f"{self.date} — {self.category}: {self.title[:50]}"


class HomilieNote(BaseModel):
    """Homily note linked to a Bible passage. Restricted to DIACRE and above."""

    author = models.ForeignKey(
        "users.BaseUser",
        on_delete=models.CASCADE,
        related_name="homilinotes",
    )
    passage_start = models.ForeignKey(
        Verse,
        on_delete=models.CASCADE,
        related_name="homilinote_starts",
    )
    passage_end = models.ForeignKey(
        Verse,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="homilinote_ends",
    )
    content = models.TextField()
    shared_with = models.ManyToManyField(
        "users.BaseUser",
        related_name="shared_homilinotes",
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Note d'homélie"
        verbose_name_plural = "Notes d'homélie"

    def __str__(self) -> str:
        return f"HomilieNote({self.author_id}, v{self.passage_start_id})"


class LectioDivinaSession(BaseModel):
    """Personal Lectio Divina session, optionnellement liée à un verset.

    `passage` est NULLABLE : une Lectio faite sur la **lecture du jour** (parcours
    depuis l'accueil Bible) n'est rattachée à aucun verset précis. Dans ce cas la
    session est identifiée par le **jour** (`session_date`) — sinon un fidèle
    écraserait sa Lectio de la veille, ou accumulerait une ligne par sauvegarde.
    """

    user = models.ForeignKey(
        "users.BaseUser",
        on_delete=models.CASCADE,
        related_name="lectio_sessions",
    )
    passage = models.ForeignKey(
        Verse,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="lectio_sessions",
    )
    session_date = models.DateField(default=timezone.localdate, db_index=True)
    lectio = models.TextField(blank=True)
    meditatio = models.TextField(blank=True)
    oratio = models.TextField(blank=True)
    contemplatio = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Session Lectio Divina"
        verbose_name_plural = "Sessions Lectio Divina"
        constraints = [
            # Session rattachée à un verset : une seule par (fidèle, verset).
            models.UniqueConstraint(
                fields=["user", "passage"],
                condition=models.Q(passage__isnull=False),
                name="uniq_lectio_user_passage",
            ),
            # Session « lecture du jour » : une seule par (fidèle, jour).
            # Contrainte partielle obligatoire : en SQL, NULL != NULL, donc un
            # unique_together classique n'empêcherait AUCUN doublon sans verset.
            models.UniqueConstraint(
                fields=["user", "session_date"],
                condition=models.Q(passage__isnull=True),
                name="uniq_lectio_user_day_without_passage",
            ),
        ]

    def __str__(self) -> str:
        if self.passage_id:
            return f"LectioDivina({self.user_id}, v{self.passage_id})"
        return f"LectioDivina({self.user_id}, {self.session_date})"


class ReadingPlan(BaseModel):
    """Curated Bible reading plan created by clergy."""

    author = models.ForeignKey(
        "users.BaseUser",
        on_delete=models.CASCADE,
        related_name="reading_plans",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_published = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Plan de lecture"
        verbose_name_plural = "Plans de lecture"

    def __str__(self) -> str:
        return f"ReadingPlan({self.title})"


class ReadingPlanSubscription(BaseModel):
    """Inscription d'un fidèle à un parcours de lecture."""

    user = models.ForeignKey(
        "users.BaseUser",
        on_delete=models.CASCADE,
        related_name="reading_plan_subscriptions",
    )
    plan = models.ForeignKey(
        ReadingPlan,
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Inscription à un parcours"
        verbose_name_plural = "Inscriptions aux parcours"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "plan"], name="uniq_reading_plan_subscription"
            ),
        ]

    def __str__(self) -> str:
        return f"ReadingPlanSubscription(user={self.user_id}, plan={self.plan_id})"


class ReadingPlanPassage(BaseModel):
    """Ordered passage within a reading plan."""

    plan = models.ForeignKey(
        ReadingPlan,
        on_delete=models.CASCADE,
        related_name="plan_passages",
    )
    verse = models.ForeignKey(
        Verse,
        on_delete=models.CASCADE,
        related_name="plan_passages",
    )
    day_number = models.PositiveSmallIntegerField()
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["day_number", "order"]
        verbose_name = "Passage du plan"
        verbose_name_plural = "Passages du plan"

    def __str__(self) -> str:
        return f"PlanPassage(plan={self.plan_id}, day={self.day_number})"


# ─── « Pour vous aujourd'hui » : signaux de lecture et recommandations (plan V2 §6) ───
#
# Données religieuses sensibles (loi 2008-12) : jamais dans les logs, pas d'admin Django,
# effacées avec le compte, exportées avec les données personnelles.


class ReadingEvent(models.Model):
    """Signal de lecture envoyé par l'app (par lots, idempotent par ``client_event_id``).

    Porte sur un verset, une plage de versets du même chapitre, ou un chapitre entier.
    Aucun texte libre n'est stocké (pas de requête de recherche : on garde seulement le
    verset ouvert depuis les résultats).
    """

    class Kind(models.TextChoices):
        LU = "lu", "Lu"
        SIGNET = "signet", "Signet"
        SURLIGNE = "surligne", "Surligné"
        RECHERCHE = "recherche", "Ouvert depuis une recherche"
        LECTIO = "lectio", "Lectio divina"

    user = models.ForeignKey("users.BaseUser", on_delete=models.CASCADE, related_name="reading_events")
    client_event_id = models.CharField(max_length=64)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    chapter = models.ForeignKey(Chapter, on_delete=models.CASCADE, related_name="reading_events")
    verse_start = models.ForeignKey(
        Verse, null=True, blank=True, on_delete=models.CASCADE, related_name="reading_events_start"
    )
    verse_end = models.ForeignKey(
        Verse, null=True, blank=True, on_delete=models.CASCADE, related_name="reading_events_end"
    )
    # Chapitre lu jusqu'au bout (sert à « lecture à continuer »).
    finished = models.BooleanField(default=False)
    occurred_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-occurred_at"]
        verbose_name = "Signal de lecture"
        verbose_name_plural = "Signaux de lecture"
        constraints = [
            models.UniqueConstraint(fields=["user", "client_event_id"], name="uniq_reading_event_client_id"),
        ]
        indexes = [models.Index(fields=["user", "-occurred_at"], name="idx_reading_event_user_time")]

    def __str__(self) -> str:
        return f"ReadingEvent({self.user_id}, {self.kind}, ch{self.chapter_id})"


class Bookmark(BaseModel):
    """Signet (sans couleur) ou surlignage (avec couleur) d'un verset, avec une note facultative."""

    class Color(models.TextChoices):
        AUCUNE = "", "Aucune (signet)"
        JAUNE = "jaune", "Jaune"
        VERT = "vert", "Vert"
        BLEU = "bleu", "Bleu"
        ROSE = "rose", "Rose"
        VIOLET = "violet", "Violet"

    user = models.ForeignKey("users.BaseUser", on_delete=models.CASCADE, related_name="bible_bookmarks")
    verse = models.ForeignKey(Verse, on_delete=models.CASCADE, related_name="bookmarks")
    color = models.CharField(max_length=16, choices=Color.choices, blank=True, default="")
    note = models.TextField(blank=True, default="", max_length=2000)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "Signet"
        verbose_name_plural = "Signets"
        constraints = [models.UniqueConstraint(fields=["user", "verse"], name="uniq_bookmark_user_verse")]

    def __str__(self) -> str:
        return f"Bookmark({self.user_id}, v{self.verse_id})"


class ParolePreference(BaseModel):
    """Réglages de la Parole propres au fidèle. Absent = valeurs par défaut."""

    user = models.OneToOneField("users.BaseUser", on_delete=models.CASCADE, related_name="parole_preference")
    # « Pour vous aujourd'hui » personnalisé à partir de ses lectures. Désactivé : aucun signal
    # n'est plus enregistré ni utilisé, et on sert le verset des lectures du jour.
    personnalisation_parole = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Réglages de la Parole"
        verbose_name_plural = "Réglages de la Parole"

    def __str__(self) -> str:
        return f"ParolePreference({self.user_id})"


class DailyRecommendation(models.Model):
    """« Pour vous aujourd'hui » précalculé la nuit (tâche ``bible_reco_recompute_task``)."""

    user = models.ForeignKey("users.BaseUser", on_delete=models.CASCADE, related_name="daily_recommendations")
    date = models.DateField()
    payload = models.JSONField(default=dict)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        verbose_name = "Recommandation du jour"
        verbose_name_plural = "Recommandations du jour"
        constraints = [models.UniqueConstraint(fields=["user", "date"], name="uniq_daily_reco_user_date")]

    def __str__(self) -> str:
        return f"DailyRecommendation({self.user_id}, {self.date})"
