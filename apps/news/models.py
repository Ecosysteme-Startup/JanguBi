import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.files.models import File
from apps.users.models import BaseUser


class ArticleCategory(models.Model):
    """Catégorie d'article (ex: Annonces, Événements, Vie paroissiale)."""

    name = models.CharField(max_length=100, verbose_name=_("Nom"))
    slug = models.SlugField(max_length=110, unique=True, verbose_name=_("Slug"))
    icon = models.CharField(max_length=50, blank=True, default="", verbose_name=_("Icône"))
    color = models.CharField(max_length=7, blank=True, default="", verbose_name=_("Couleur hex"))
    display_order = models.IntegerField(default=0, db_index=True, verbose_name=_("Ordre d'affichage"))
    is_active = models.BooleanField(default=True, db_index=True, verbose_name=_("Active"))

    class Meta:
        verbose_name = _("Catégorie d'article")
        verbose_name_plural = _("Catégories d'article")
        ordering = ["display_order", "name"]

    def __str__(self) -> str:
        return self.name


class Article(BaseModel):
    """
    Article éditorial publié à un niveau de portée (global, diocèse, paroisse).

    scope_parish_id et scope_diocese_id sont des IntegerField placeholder
    en attendant que le module Organisation (Parish, Diocese) soit implémenté (V2).
    """

    class ContentType(models.TextChoices):
        ANNOUNCEMENT = "announcement", _("Annonce")
        ARTICLE = "article", _("Article")
        PASTORAL_LETTER = "pastoral_letter", _("Lettre Pastorale")

    class ScopeType(models.TextChoices):
        GLOBAL = "global", _("Global (toute l'Église du Sénégal)")
        DIOCESE = "diocese", _("Diocèse")
        PARISH = "parish", _("Paroisse")
        CHURCH = "church", _("Église")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Brouillon")
        SCHEDULED = "scheduled", _("Programmé")
        PUBLISHED = "published", _("Publié")
        UNPUBLISHED = "unpublished", _("Dépublié")

    class ContentFormat(models.TextChoices):
        TEXT = "text", _("Texte brut")
        HTML = "html", _("HTML riche")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    content_type = models.CharField(
        max_length=20,
        choices=ContentType.choices,
        default=ContentType.ARTICLE,
        db_index=True,
        verbose_name=_("Type de contenu"),
    )

    title = models.CharField(max_length=200, verbose_name=_("Titre"))
    slug = models.SlugField(max_length=220, verbose_name=_("Slug"))
    excerpt = models.CharField(
        max_length=400, blank=True, default="", verbose_name=_("Résumé court")
    )
    content = models.TextField(verbose_name=_("Contenu"))
    # Format du contenu : "text" pour l'existant (rédigé en textarea brut),
    # "html" pour l'éditeur riche (TipTap). Le HTML est SANITIZÉ côté service
    # (nh3) avant persistance — jamais de HTML brut non filtré en base.
    content_format = models.CharField(
        max_length=10,
        choices=ContentFormat.choices,
        default=ContentFormat.TEXT,
        verbose_name=_("Format du contenu"),
    )
    # Pour les annonces : date du jour concerné (ex. le dimanche à venir) —
    # alimente le bloc « Annonces du dimanche » du fil.
    announcement_date = models.DateField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Date de l'annonce"),
    )

    cover_image = models.ForeignKey(
        File,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="article_covers",
        verbose_name=_("Image de couverture"),
    )

    category = models.ForeignKey(
        ArticleCategory,
        on_delete=models.PROTECT,
        related_name="articles",
        verbose_name=_("Catégorie"),
    )

    author = models.ForeignKey(
        BaseUser,
        on_delete=models.PROTECT,
        related_name="articles",
        verbose_name=_("Auteur"),
    )

    # --- Portée ---
    scope_type = models.CharField(
        max_length=20,
        choices=ScopeType.choices,
        default=ScopeType.GLOBAL,
        db_index=True,
        verbose_name=_("Portée"),
    )
    # FK territoriales réelles (Chantier 3a — ex-placeholders IntegerField).
    scope_diocese = models.ForeignKey(
        "org.Diocese",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="scoped_articles",
        db_index=True,
        verbose_name=_("Diocèse de portée"),
    )
    scope_parish = models.ForeignKey(
        "org.Parish",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="scoped_articles",
        db_index=True,
        verbose_name=_("Paroisse de portée"),
    )
    scope_church = models.ForeignKey(
        "org.Church",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="scoped_articles",
        db_index=True,
        verbose_name=_("Église de portée"),
    )

    # --- Portée V1 (L4) : un nœud de l'arbre, ou rien (global Numerisen) ---
    # Les champs scope_type/diocese/parish/church ci-dessus restent lisibles jusqu'en L9.
    scope_node = models.ForeignKey(
        "hierarchy.Node",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="articles",
        verbose_name=_("Nœud de portée"),
    )
    scope_place = models.ForeignKey(
        "hierarchy.PlaceOfWorship",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="articles",
        verbose_name=_("Lieu de culte"),
    )
    is_sunday_notice = models.BooleanField(
        _("annonce du dimanche"), default=False, db_default=False
    )
    sunday_date = models.DateField(_("dimanche concerné"), null=True, blank=True)
    publish_at = models.DateTimeField(_("publication programmée"), null=True, blank=True)

    # --- Statut & workflow ---
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
        verbose_name=_("Statut"),
    )
    published_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Publié le"))
    unpublished_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Dépublié le"))
    unpublished_by = models.ForeignKey(
        BaseUser,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="unpublished_articles",
        verbose_name=_("Dépublié par"),
    )
    unpublish_reason = models.TextField(
        blank=True, default="", verbose_name=_("Motif de dépublication")
    )

    views_count = models.PositiveIntegerField(default=0, verbose_name=_("Nombre de vues"))

    class Meta:
        verbose_name = _("Article")
        verbose_name_plural = _("Articles")
        ordering = ["-published_at", "-created_at"]
        constraints = [
            # Slug unique par portée paroisse
            models.UniqueConstraint(
                fields=["slug", "scope_type", "scope_parish"],
                name="unique_article_slug_parish",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "-published_at"], name="article_status_pub_idx"),
            models.Index(
                fields=["scope_type", "scope_parish", "status"],
                name="article_parish_idx",
            ),
            models.Index(
                fields=["scope_type", "scope_diocese", "status"],
                name="article_diocese_idx",
            ),
            models.Index(
                fields=["scope_type", "scope_church", "status"],
                name="article_church_idx",
            ),
            models.Index(fields=["category", "status"], name="article_category_idx"),
            models.Index(fields=["scope_node", "status", "-published_at"], name="article_node_pub_idx"),
            models.Index(
                fields=["sunday_date"], condition=models.Q(is_sunday_notice=True), name="article_sunday_idx"
            ),
            models.Index(
                fields=["publish_at"], condition=models.Q(status="scheduled"), name="article_scheduled_idx"
            ),
            models.Index(fields=["author", "-created_at"], name="article_author_idx"),
        ]

    def __str__(self) -> str:
        return f"[{self.get_scope_type_display()}] {self.title} ({self.get_status_display()})"


class ArticleReaction(BaseModel):
    """Réaction communautaire d'un fidèle à un article (SRS : prier / amen / participer).

    Le seul geste communautaire du module Actualités : un fidèle qui lit une
    annonce paroissiale peut manifester qu'il prie, qu'il adhère, ou qu'il sera
    présent.

    UNICITÉ (article, user, reaction_type) garantie **en base** et pas seulement
    dans le service : sans la contrainte, un double-clic ou un rejeu réseau
    insère deux lignes et le compteur ment définitivement. Le service passe par
    ``get_or_create``, qui s'appuie sur cette contrainte pour rester idempotent
    même quand deux requêtes concurrentes arrivent en même temps.

    Les trois types sont indépendants : « je prie » et « je participe » peuvent
    coexister pour un même fidèle sur un même article — d'où le ``reaction_type``
    DANS la clé d'unicité, et non une réaction unique par article.
    """

    class ReactionType(models.TextChoices):
        PRAY = "pray", _("Je prie")
        AMEN = "amen", _("Amen")
        ATTEND = "attend", _("Je participe")

    article = models.ForeignKey(
        Article,
        on_delete=models.CASCADE,
        related_name="reactions",
        verbose_name=_("Article"),
    )
    user = models.ForeignKey(
        BaseUser,
        on_delete=models.CASCADE,
        related_name="article_reactions",
        verbose_name=_("Utilisateur"),
    )
    reaction_type = models.CharField(
        max_length=20,
        choices=ReactionType.choices,
        db_index=True,
        verbose_name=_("Type de réaction"),
    )

    class Meta:
        verbose_name = _("Réaction à un article")
        verbose_name_plural = _("Réactions aux articles")
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["article", "user", "reaction_type"],
                name="unique_article_reaction_per_user_and_type",
            ),
        ]
        indexes = [
            # Sert les compteurs par type (sous-requête agrégée du fil).
            models.Index(
                fields=["article", "reaction_type"],
                name="article_reaction_count_idx",
            ),
            # Sert l'état « ai-je réagi ? » de l'utilisateur courant (EXISTS).
            models.Index(
                fields=["user", "article"],
                name="article_reaction_mine_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} → {self.get_reaction_type_display()} sur {self.article_id}"


class ArticleRead(models.Model):
    """Lecture d'un article par une personne — une seule par personne (EF-PAROI-05)."""

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="reads")
    user = models.ForeignKey(BaseUser, on_delete=models.CASCADE, related_name="article_reads")
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Lecture d'un article")
        verbose_name_plural = _("Lectures d'articles")
        constraints = [models.UniqueConstraint(fields=["article", "user"], name="unique_article_read_per_user")]

    def __str__(self) -> str:
        return f"{self.user_id} a lu {self.article_id}"
