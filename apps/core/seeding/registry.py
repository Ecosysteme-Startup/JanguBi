"""Registre des semeurs de ``seed_realiste`` (plan des données de test, §2).

Chaque application déclare ses semeurs dans ``apps/<app>/seeders.py`` avec ``@register``. Le registre
les découvre (``autodiscover``), résout les dépendances et les ordonne par phase :
hiérarchie → personnes → appartenances → contenus → dons → audio → parole → activité → recalculs.

**Point d'extension** : une application qui arrive plus tard (intentions de messe, validation du
clergé, outils du staff, recherche…) ajoute simplement son ``seeders.py`` :

.. code-block:: python

    from apps.core.seeding.registry import Phase, Seeder, register

    @register
    class IntentionsSeeder(Seeder):
        name = "intentions"
        module = "intentions"          # sélection par --modules intentions
        phase = Phase.CONTENUS
        depends = ("personnes", "appartenances")

        def seed(self, ctx): ...        # crée, trace avec ctx.track(...)
        def reset(self, ctx): ...       # supprime ce que ctx.tracked(...) désigne
        def verify(self, ctx): return []

Aucune modification de l'orchestrateur n'est nécessaire.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from apps.core.seeding.context import SeedContext


class Phase(enum.IntEnum):
    HIERARCHIE = 10
    PERSONNES = 20
    APPARTENANCES = 30
    CONTENUS = 40
    DONS = 50
    AUDIO = 60
    PAROLE = 70
    ACTIVITE = 80
    RECALCULS = 90


@dataclass
class Check:
    """Un invariant contrôlé par ``--verifier``."""

    label: str
    ok: bool
    detail: str = ""


class Seeder:
    name: ClassVar[str] = ""
    module: ClassVar[str] = ""
    phase: ClassVar[Phase] = Phase.CONTENUS
    depends: ClassVar[tuple[str, ...]] = ()
    # Semeur toujours rejoué (recalculs, synchronisations) : pas de marque « déjà fait ».
    always: ClassVar[bool] = False

    def seed(self, ctx: SeedContext) -> dict[str, Any]:
        raise NotImplementedError

    def reset(self, ctx: SeedContext) -> dict[str, Any]:
        return {}

    def verify(self, ctx: SeedContext) -> list[Check]:
        return []

    def produced(self, result: dict[str, Any]) -> bool:
        """Le passage a-t-il produit ce que le semeur doit semer ? Faux : il n'est PAS marqué « fait » et
        sera repris au passage suivant (ex. écoutes sans aucune piste écoutable)."""
        return True


REGISTRY: dict[str, type[Seeder]] = {}


def register(cls: type[Seeder]) -> type[Seeder]:
    if not cls.name or not cls.module:
        raise ValueError(f"{cls.__name__} : `name` et `module` sont obligatoires.")
    if cls.name in REGISTRY and REGISTRY[cls.name] is not cls:
        raise ValueError(f"Semeur « {cls.name} » déjà enregistré.")
    REGISTRY[cls.name] = cls
    return cls


def autodiscover() -> None:
    from django.utils.module_loading import autodiscover_modules

    autodiscover_modules("seeders")


def modules() -> list[str]:
    return sorted({cls.module for cls in REGISTRY.values()})


def ordered(selected_modules: set[str] | None = None) -> list[Seeder]:
    """Semeurs à lancer, dépendances incluses, dans l'ordre des phases puis des dépendances."""
    wanted = {n for n, c in REGISTRY.items() if selected_modules is None or c.module in selected_modules}
    unknown = (selected_modules or set()) - {c.module for c in REGISTRY.values()}
    if unknown:
        raise ValueError(f"Module(s) inconnu(s) : {', '.join(sorted(unknown))}. Connus : {', '.join(modules())}.")
    stack = list(wanted)
    while stack:
        name = stack.pop()
        for dep in REGISTRY[name].depends:
            if dep not in REGISTRY:
                raise ValueError(f"« {name} » dépend de « {dep} », qui n'est pas enregistré.")
            if dep not in wanted:
                wanted.add(dep)
                stack.append(dep)
    result: list[str] = []
    visiting: set[str] = set()

    def visit(name: str) -> None:
        if name in result:
            return
        if name in visiting:
            raise ValueError(f"Dépendance circulaire autour de « {name} ».")
        visiting.add(name)
        for dep in sorted(REGISTRY[name].depends, key=lambda d: (REGISTRY[d].phase, d)):
            visit(dep)
        visiting.discard(name)
        result.append(name)

    for name in sorted(wanted, key=lambda n: (REGISTRY[n].phase, n)):
        visit(name)
    return [REGISTRY[n]() for n in result]
