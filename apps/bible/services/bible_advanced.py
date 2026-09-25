from django.db import transaction

from apps.core.exceptions import ApplicationError
from apps.hierarchy.persons import is_clerc_or_consecrated, is_priest_or_bishop


def _require_clergy(user) -> None:
    if not is_clerc_or_consecrated(user):
        raise ApplicationError("Réservé aux membres du clergé.")


def _require_priest_or_above(user) -> None:
    if not is_priest_or_bishop(user):
        raise ApplicationError("Réservé aux prêtres et évêques.")


@transaction.atomic
def homilenote_create(*, author, passage_start_id: int, content: str, passage_end_id: int | None = None):
    from apps.bible.models import HomilieNote, Verse

    _require_clergy(author)
    try:
        passage_start = Verse.objects.get(pk=passage_start_id)
    except Verse.DoesNotExist:
        raise ApplicationError("Verset de début introuvable.")
    passage_end = None
    if passage_end_id is not None:
        try:
            passage_end = Verse.objects.get(pk=passage_end_id)
        except Verse.DoesNotExist:
            raise ApplicationError("Verset de fin introuvable.")
    return HomilieNote.objects.create(
        author=author,
        passage_start=passage_start,
        passage_end=passage_end,
        content=content,
    )


@transaction.atomic
def homilenote_update(*, note, content: str):
    note.content = content
    note.save(update_fields=["content", "updated_at"])
    return note


@transaction.atomic
def homilenote_delete(*, note, user) -> None:
    if note.author_id != user.pk:
        raise ApplicationError("Vous ne pouvez supprimer que vos propres notes.")
    note.delete()


@transaction.atomic
def lectio_divina_upsert(
    *,
    user,
    passage_id: int | None = None,
    lectio: str = "",
    meditatio: str = "",
    oratio: str = "",
    contemplatio: str = "",
):
    """Crée ou met à jour la session Lectio Divina du fidèle.

    Deux modes, selon `passage_id` :
      - **verset précis** → clé (user, passage) ;
      - **lecture du jour** (`passage_id` absent, `None` ou `0`) → clé
        (user, jour courant). Le `0` est accepté car c'est la convention
        historique du client web pour « pas de verset sélectionné ».
    """
    from django.utils import timezone

    from apps.bible.models import LectioDivinaSession, Verse

    fields = {
        "lectio": lectio,
        "meditatio": meditatio,
        "oratio": oratio,
        "contemplatio": contemplatio,
    }

    if not passage_id:  # None ou 0 → Lectio « lecture du jour »
        session, _ = LectioDivinaSession.objects.update_or_create(
            user=user,
            passage__isnull=True,
            session_date=timezone.localdate(),
            defaults={**fields, "passage": None},
        )
        return session

    try:
        passage = Verse.objects.get(pk=passage_id)
    except Verse.DoesNotExist:
        raise ApplicationError("Verset introuvable.")

    session, _ = LectioDivinaSession.objects.update_or_create(
        user=user,
        passage=passage,
        defaults=fields,
    )
    return session


@transaction.atomic
def reading_plan_create(*, author, title: str, description: str = ""):
    from apps.bible.models import ReadingPlan

    _require_priest_or_above(author)
    return ReadingPlan.objects.create(author=author, title=title, description=description)


@transaction.atomic
def reading_plan_subscribe(*, plan, user):
    """Inscrit le fidèle au parcours. Idempotent : ré-inscrire ne duplique pas."""
    from apps.bible.models import ReadingPlanSubscription

    if not plan.is_published:
        raise ApplicationError("Ce parcours de lecture n'est pas encore publié.")

    ReadingPlanSubscription.objects.get_or_create(user=user, plan=plan)
    return plan


@transaction.atomic
def reading_plan_unsubscribe(*, plan, user):
    """Désinscrit le fidèle. Idempotent : se désinscrire deux fois n'est pas une erreur."""
    from apps.bible.models import ReadingPlanSubscription

    ReadingPlanSubscription.objects.filter(user=user, plan=plan).delete()
    return plan


@transaction.atomic
def reading_plan_publish(*, plan, user):
    if plan.author_id != user.pk:
        raise ApplicationError("Vous ne pouvez publier que vos propres plans.")
    plan.is_published = True
    plan.save(update_fields=["is_published", "updated_at"])
    return plan
