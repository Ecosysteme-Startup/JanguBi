"""Semeur des annonces et actualités (``seed_realiste``, lot S3) : paroisse, diocèse et global, avec
réactions et lectures des membres."""

from __future__ import annotations

import datetime
from typing import Any

from django.db import transaction
from django.utils.text import slugify

from apps.core.seeding import textes
from apps.core.seeding.context import SeedContext
from apps.core.seeding.registry import Check, Phase, Seeder, register
from apps.hierarchy.seeders import staff_of


@register
class AnnoncesSeeder(Seeder):
    name = "annonces"
    module = "vie"
    phase = Phase.CONTENUS
    depends = ("appartenances",)

    def seed(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.hierarchy.models import Node
        from apps.news.models import Article, ArticleCategory, ArticleReaction, ArticleRead

        rng = ctx.rng(self.name)
        t = textes()
        category, created = ArticleCategory.objects.get_or_create(
            slug="vie-paroissiale", defaults={"name": "Vie paroissiale"}
        )
        if created:
            ctx.track(ArticleCategory, [category.pk])
        articles: list[Any] = []

        def article(**fields: Any) -> Any:
            title = fields["title"]
            a = Article(slug=f"{slugify(title)[:180]}-{rng.getrandbits(32):08x}", category=category, **fields)
            articles.append(a)
            return a

        last_sunday = ctx.today - datetime.timedelta(days=(ctx.today.weekday() + 1) % 7)
        for parish in ctx.parishes():
            author = staff_of(parish, "cure") or staff_of(parish, "secretaire_paroissial")
            n = ctx.scale.articles_par_paroisse
            for i in range(n // 2):  # annonces des derniers dimanches
                sunday = last_sunday - datetime.timedelta(days=7 * i)
                lines = rng.sample(t["annonces"]["lignes"], k=4)
                article(title=f"{rng.choice(t['annonces']['titres'])} — {sunday:%d/%m}", content="\n".join(f"- {x}" for x in lines),
                        excerpt=lines[0][:380], content_type="announcement", author=author, scope_node=parish,
                        is_sunday_notice=True, sunday_date=sunday, status="published",
                        published_at=ctx.aware(sunday - datetime.timedelta(days=1), 18), announcement_date=sunday)  # fmt: skip
            for i in range(n - n // 2):
                kind = "meditation" if i % 3 == 2 else "article"
                src = rng.choice(t["meditations"] if kind == "meditation" else t["articles"])
                published: datetime.datetime | None = ctx.now - datetime.timedelta(
                    days=rng.randint(1, 120), hours=rng.randint(0, 12)
                )
                status = "published"
                if i == 0:
                    status, published = "draft", None  # brouillon du staff
                article(title=src["titre"], content=src["texte"], excerpt=src["texte"][:380], content_type=kind,
                        author=author, scope_node=parish, status=status, published_at=published)  # fmt: skip
        diocese = Node.objects.get(code="DAK")
        chancelier = ctx.persona("chancelier")
        for src in t["diocese"]:
            article(title=src["titre"], content=src["texte"], excerpt=src["texte"][:380], content_type="pastoral_letter",
                    author=chancelier, scope_node=diocese, status="published",
                    published_at=ctx.now - datetime.timedelta(days=rng.randint(3, 60)))  # fmt: skip
        for src in t["global"]:
            article(title=src["titre"], content=src["texte"], excerpt=src["texte"][:380], content_type="article",
                    author=ctx.persona("plateforme"), scope_node=None, status="published", notify_followers=False,
                    published_at=ctx.now - datetime.timedelta(days=90))  # fmt: skip
        with transaction.atomic():
            Article.objects.bulk_create(articles)
            ctx.track(Article, [a.pk for a in articles])
            members = ctx.members()
            everyone = [u for us in members.values() for u in us]
            reactions: list[Any] = []
            reads: list[Any] = []
            for a in articles:
                if a.status != "published":
                    continue
                pool = members.get(a.scope_node_id, everyone) if a.scope_node_id else everyone
                readers = rng.sample(pool, k=min(len(pool), int(len(pool) * rng.uniform(0.15, 0.55))))
                reads.extend(ArticleRead(article=a, user_id=u) for u in readers)
                for u in readers:
                    if rng.random() < 0.3:
                        kind = rng.choices(
                            ["pray", "amen", "attend"], [5, 4, 2 if a.content_type == "announcement" else 0]
                        )[0]
                        reactions.append(ArticleReaction(article=a, user_id=u, reaction_type=kind))
                a.views_count = int(len(readers) * rng.uniform(1.1, 1.8))
            ArticleRead.objects.bulk_create(reads, batch_size=5000, ignore_conflicts=True)
            ArticleReaction.objects.bulk_create(reactions, batch_size=5000, ignore_conflicts=True)
            Article.objects.bulk_update(articles, ["views_count"], batch_size=1000)
        return {"articles": len(articles), "lectures": len(reads), "reactions": len(reactions)}

    def reset(self, ctx: SeedContext) -> dict[str, Any]:
        from apps.news.models import Article, ArticleCategory

        n, _ = ctx.tracked(Article).delete()
        ctx.tracked(ArticleCategory).delete()
        return {"objets": n}

    def verify(self, ctx: SeedContext) -> list[Check]:
        from apps.news.models import Article

        qs = ctx.tracked(Article)
        return [Check("Annonces publiées", qs.filter(status="published").exists(), f"{qs.count()} articles")]
