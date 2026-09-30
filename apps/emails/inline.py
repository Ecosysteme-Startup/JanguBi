"""Mise en ligne du CSS des e-mails (attributs ``style``).

Gmail, Outlook et la plupart des webmails ignorent tout ou partie des feuilles ``<style>`` :
seules les déclarations posées sur chaque balise sont fiables. Les gabarits écrivent donc
leurs règles dans un bloc ``<style data-inline>`` (sélecteurs CSS simples, sans ``@media``) ;
``css_inline`` les recopie dans l'attribut ``style`` des balises visées, puis retire le bloc.
Les autres blocs ``<style>`` (mode sombre, petits écrans) restent dans l'en-tête pour les
clients qui les comprennent.

Règles appliquées dans l'ordre du fichier (la dernière l'emporte) ; un ``style`` écrit à la
main sur une balise a toujours le dernier mot.
"""

import re

from bs4 import BeautifulSoup, Tag

_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def _declarations(block: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for part in block.split(";"):
        if ":" not in part:
            continue
        prop, value = part.split(":", 1)
        prop, value = prop.strip().lower(), value.strip()
        if prop and value:
            out.append((prop, value))
    return out


def _parse_style_attr(style: str) -> dict[str, str]:
    return dict(_declarations(style))


def _format(styles: dict[str, str]) -> str:
    return "; ".join(f"{prop}: {value}" for prop, value in styles.items())


def css_inline(html: str) -> str:
    """Recopie les règles des blocs ``<style data-inline>`` dans les attributs ``style``."""
    soup = BeautifulSoup(html, "html.parser")
    blocks = soup.find_all("style", attrs={"data-inline": True})
    if not blocks:
        return html

    rules: list[tuple[str, list[tuple[str, str]]]] = []
    for block in blocks:
        css = _COMMENT.sub("", block.get_text())
        for selectors, body in _RULE.findall(css):
            declarations = _declarations(body)
            for selector in selectors.split(","):
                if selector.strip():
                    rules.append((selector.strip(), declarations))
        block.decompose()

    computed: dict[int, tuple[Tag, dict[str, str]]] = {}
    for selector, declarations in rules:
        for element in soup.select(selector):
            _, styles = computed.setdefault(id(element), (element, {}))
            styles.update(declarations)

    for element, styles in computed.values():
        own = _parse_style_attr(str(element.get("style") or ""))
        element["style"] = _format({**styles, **own})

    return str(soup)
