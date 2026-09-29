"""Conformité (SRS §3.9, ADR-011)."""

from config.env import env

# Version en vigueur des CGU et de la politique de confidentialité. La changer impose un
# nouveau consentement explicite à chaque personne (EF-CONF-01).
CONSENT_CURRENT_VERSION = env("CONSENT_CURRENT_VERSION", default="2026-09")
