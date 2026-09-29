# Lot B2 (temps réel) : préférence push et désactivation des jetons refusés.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("messaging", "0002_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="notificationpreference",
            name="push",
            # db_default : l'ancien code (déploiement en cours) insère encore sans ce champ.
            field=models.BooleanField(db_default=True, default=True, verbose_name="sur le téléphone (push)"),
        ),
        migrations.AddField(
            model_name="pushdevice",
            name="disabled_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="désactivé le"),
        ),
    ]
