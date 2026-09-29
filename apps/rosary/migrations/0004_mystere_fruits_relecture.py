from django.db import migrations
from django.db.models import Q

# Formulations corrigées après relecture. On ne remplace que si la valeur actuelle est
# l'ancienne formulation : une saisie manuelle différente est conservée. Copie figée.
CORRECTIONS = [
    # (groupe, ordre, ancienne formulation, nouvelle formulation)
    ("joyeux", 5, "La recherche de Dieu en toutes choses", "La recherche de Dieu et la vraie sagesse"),
    ("douloureux", 3, "Le courage face au mépris du monde", "Le détachement des vanités du monde"),
]


def _apply(apps, *, reverse: bool) -> None:
    Mystery = apps.get_model("rosary", "Mystery")
    for group, order, old, new in CORRECTIONS:
        current, target = (new, old) if reverse else (old, new)
        Mystery.objects.filter(
            Q(group__slug__iexact=group) | Q(group__name__iexact=group), order=order, fruit=current
        ).update(fruit=target)


def fruits_correct(apps, schema_editor):
    _apply(apps, reverse=False)


def fruits_restore(apps, schema_editor):
    _apply(apps, reverse=True)


class Migration(migrations.Migration):
    dependencies = [
        ("rosary", "0003_mystere_fruit_libelles_fr"),
    ]

    operations = [
        migrations.RunPython(fruits_correct, fruits_restore),
    ]
