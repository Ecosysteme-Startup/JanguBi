"""Index composites des lectures fréquentes (recommandations du lot B2, docs/SCALING.md §4.2).

Créés sans verrou d'écriture (``CONCURRENTLY``, migration non atomique) : les nouveaux d'abord, puis
le retrait de ``(fund, status)``, préfixe de ``(fund, status, confirmed_at)``.
"""

from django.contrib.postgres.operations import AddIndexConcurrently, RemoveIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("donations", "0006_messe_anticipee_incluse")]

    operations = [
        AddIndexConcurrently(
            model_name="donation",
            index=models.Index(fields=["fund", "status", "confirmed_at"], name="dons_donation_fund_st_conf_idx"),
        ),
        AddIndexConcurrently(
            model_name="donation",
            index=models.Index(fields=["fund", "-created_at"], name="dons_donation_fund_created_idx"),
        ),
        AddIndexConcurrently(
            model_name="cashcollection",
            index=models.Index(fields=["node", "status", "-mass_date"], name="dons_cash_node_st_mass_idx"),
        ),
        RemoveIndexConcurrently(model_name="donation", name="dons_donation_fund_status_idx"),
    ]
