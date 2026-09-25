from django.contrib.postgres.search import SearchVectorField
from django.db import models

from apps.common.models import BaseModel

# Import removed since we fallback to JSON like the Bible module
from apps.rosary.storage import RosaryAudioStorage


class MysteryGroup(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=255, unique=True)
    audio_file = models.FileField(storage=RosaryAudioStorage(), upload_to="", null=True, blank=True)

    def __str__(self):
        return self.name


class Mystery(BaseModel):
    group = models.ForeignKey(MysteryGroup, on_delete=models.CASCADE, related_name="mysteries")
    order = models.PositiveSmallIntegerField()  # 1 to 5
    title = models.CharField(max_length=255)
    meditation = models.TextField(null=True, blank=True, help_text="Scripture reading or meditation for the mystery")
    # Provenance du texte de méditation (audit L7, ADR-008) : œuvre, auteur, licence.
    meditation_source = models.CharField(max_length=255, blank=True, default="", db_default="")
    audio_file = models.FileField(storage=RosaryAudioStorage(), upload_to="", null=True, blank=True)
    audio_duration = models.PositiveIntegerField(null=True, blank=True, help_text="Duration in seconds")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["group", "order"], name="unique_mystery_order_per_group")
        ]
        verbose_name_plural = "Mysteries"

    def __str__(self):
        return f"{self.group.name} - {self.order} - {self.title}"


class Prayer(BaseModel):
    class Type(models.TextChoices):
        SIGN_OF_CROSS = "SIGN_OF_CROSS", "Sign of Cross"
        CREED = "CREED", "Apostles Creed"
        OUR_FATHER = "OUR_FATHER", "Our Father"
        HAIL_MARY = "HAIL_MARY", "Hail Mary"
        GLORY_BE = "GLORY_BE", "Glory Be"
        FATIMA = "FATIMA", "Fatima Prayer"
        HOLY_QUEEN = "HOLY_QUEEN", "Hail Holy Queen"
        FINAL_PRAYER = "FINAL_PRAYER", "Final Prayer"
        OTHER = "OTHER", "Other"

    type = models.CharField(max_length=50, choices=Type.choices)
    text = models.TextField()
    language = models.CharField(max_length=10, default="FR")
    # Provenance (audit L7) : prières traditionnelles du domaine public, ou source et licence.
    source = models.CharField(max_length=255, blank=True, default="", db_default="")
    
    # Text Search Field (populated via triggers/SQL)
    tsv = SearchVectorField(null=True, blank=True)
    
    # Vector DB Search Field for Future RAG (Stubbed as JSONField for now)
    embedding = models.JSONField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["type"]),
        ]

    def __str__(self):
        return f"{self.get_type_display()} ({self.language})"


class MysteryPrayer(models.Model):
    mystery = models.ForeignKey(Mystery, on_delete=models.CASCADE, related_name="prayers")
    prayer = models.ForeignKey(Prayer, on_delete=models.CASCADE, related_name="mysteries")
    order = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["mystery", "order"], name="unique_prayer_order_per_mystery")
        ]
        ordering = ["order"]

    def __str__(self):
        return f"{self.mystery.title} -> {self.prayer.type} (Order: {self.order})"


class RosaryDay(BaseModel):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    weekday = models.IntegerField(choices=Weekday.choices, unique=True)
    group = models.ForeignKey(MysteryGroup, on_delete=models.CASCADE, related_name="days")

    def __str__(self):
        return f"{self.get_weekday_display()} -> {self.group.name}"


class CommunityRosary(BaseModel):
    """A live community rosary session initiated by clergy."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Actif"
        COMPLETED = "completed", "Terminé"
        CANCELLED = "cancelled", "Annulé"

    initiator = models.ForeignKey(
        "users.BaseUser",
        on_delete=models.CASCADE,
        related_name="initiated_rosaries",
    )
    mystery_group = models.ForeignKey(
        MysteryGroup,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="community_sessions",
    )
    intention = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )
    current_decade = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "Chapelet communautaire"
        verbose_name_plural = "Chapelets communautaires"

    def __str__(self) -> str:
        return f"CommunityRosary({self.initiator_id}, {self.status})"


class RosaryParticipant(BaseModel):
    """Tracks who joined a community rosary session."""

    rosary = models.ForeignKey(
        CommunityRosary,
        on_delete=models.CASCADE,
        related_name="participants",
    )
    user = models.ForeignKey(
        "users.BaseUser",
        on_delete=models.CASCADE,
        related_name="rosary_participations",
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [["rosary", "user"]]
        verbose_name = "Participant chapelet"
        verbose_name_plural = "Participants chapelet"

    def __str__(self) -> str:
        return f"Participant({self.user_id} → rosary {self.rosary_id})"


class RosaryIntention(BaseModel):
    """An intention submitted during a community rosary."""

    rosary = models.ForeignKey(
        CommunityRosary,
        on_delete=models.CASCADE,
        related_name="intentions",
    )
    submitted_by = models.ForeignKey(
        "users.BaseUser",
        on_delete=models.CASCADE,
        related_name="submitted_rosary_intentions",
    )
    text = models.TextField()

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Intention chapelet"
        verbose_name_plural = "Intentions chapelet"

    def __str__(self) -> str:
        return f"Intention({self.rosary_id}, {self.submitted_by_id})"
