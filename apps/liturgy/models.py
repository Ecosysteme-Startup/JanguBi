from django.db import models
from django.utils import timezone


class AelfDataEntry(models.Model):
    """
    Stores raw JSON responses from the AELF API for auditability and rollback capabilities.
    """

    source_endpoint = models.CharField(max_length=255, db_index=True)
    date = models.DateField(db_index=True)
    zone = models.CharField(max_length=50, db_index=True)
    raw_json = models.JSONField(help_text="The exact JSON response returned by the API")
    fetched_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name_plural = "AELF Data Entries"
        ordering = ["-fetched_at"]

    def __str__(self):
        return f"AELF {self.source_endpoint} - {self.date} ({self.zone})"


class LiturgicalDate(models.Model):
    """
    Core metadata for a specific date in a specific liturgical zone.
    """

    date = models.DateField()
    zone = models.CharField(max_length=50)

    # Metadata extracted from /informations
    day_name = models.CharField(max_length=255, blank=True)
    season = models.CharField(max_length=255, blank=True)
    mystery = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("date", "zone")
        ordering = ["-date"]

    def __str__(self):
        return f"{self.date} ({self.zone}) - {self.day_name}"


class AelfResource(models.Model):
    """
    Multimedia or external resources linked to a liturgical date.
    """

    liturgical_date = models.OneToOneField(LiturgicalDate, on_delete=models.CASCADE, related_name="resource")
    audio_url = models.URLField(max_length=500, blank=True, null=True)
    youtube_url = models.URLField(max_length=500, blank=True, null=True)

    def __str__(self):
        return f"Resources for {self.liturgical_date}"


class Reading(models.Model):
    """
    A reading associated with a liturgical event (typically the Mass).
    """

    liturgical_date = models.ForeignKey(LiturgicalDate, on_delete=models.CASCADE, related_name="readings")

    # e.g., 'first_reading', 'psalm', 'gospel'
    type = models.CharField(max_length=100)

    # e.g., 'Dn 9,4-10'
    citation = models.CharField(max_length=255, blank=True)

    # The actual text retrieved from AELF
    text = models.TextField()

    # Additional raw metadata for this specific reading if needed
    raw_metadata = models.JSONField(default=dict, blank=True)

    # Many-to-Many relationship with local Bible Verses
    matched_verses = models.ManyToManyField(
        "bible.Verse",
        related_name="liturgy_readings",
        blank=True,
        help_text="Bible verses from our local DB matched to this reading citation.",
    )

    class Meta:
        # Prevent exact duplicates if run multiple times
        unique_together = ("liturgical_date", "type", "citation")
        ordering = ["id"]

    def __str__(self):
        return f"{self.get_type_display() if hasattr(self, 'get_type_display') else self.type} - {self.citation}"


class Office(models.Model):
    """
    Text blocks for the Liturgy of the Hours (Lauds, Vespers, etc.).
    """

    liturgical_date = models.ForeignKey(LiturgicalDate, on_delete=models.CASCADE, related_name="offices")

    # e.g., 'laudes', 'vepres', 'tierce'
    office_type = models.CharField(max_length=50)

    # JSON-structured fields allowing flexibility for the AELF payload structures
    hymn = models.TextField(blank=True, help_text="Hymn text")
    psalms = models.JSONField(default=list, blank=True, help_text="List of psalms/canticles objects")
    canticle = models.TextField(blank=True, help_text="Main canticle (Benedictus/Magnificat/Nunc Dimittis)")
    readings = models.JSONField(default=list, blank=True, help_text="Short readings and responsories")
    intercessions = models.TextField(blank=True, help_text="Intercessions text")

    raw_metadata = models.JSONField(default=dict, blank=True, help_text="Any additional unmodified data")

    class Meta:
        unique_together = ("liturgical_date", "office_type")

    def __str__(self):
        return f"{self.office_type.capitalize()} on {self.liturgical_date.date}"
