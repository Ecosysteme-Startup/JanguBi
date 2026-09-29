from django.db import models
from django.utils.translation import gettext_lazy as _


class Title(models.TextChoices):
    MR  = ("MR",  _("M."))
    MRS = ("MRS", _("Mme"))
