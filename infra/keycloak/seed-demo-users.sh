#!/usr/bin/env bash
# Comptes Keycloak des personnes de démonstration (`manage.py seed_demo`, *@demo.jangubi.sn).
# Dev UNIQUEMENT : Keycloak local du compose (profil keycloak). Le mot de passe de test vient de
# KC_DEMO_PASSWORD (.env, non versionné). Idempotent : un compte existant est laissé tel quel.
# À la première connexion d'un responsable, Keycloak impose l'enrôlement TOTP (MFA staff).
set -euo pipefail
: "${KC_DEMO_PASSWORD:?KC_DEMO_PASSWORD manquant (voir .env)}"
kc() { docker compose --profile keycloak exec -T keycloak /opt/keycloak/bin/kcadm.sh "$@" </dev/null; }
kc config credentials --server http://localhost:8080 --realm master \
  --user "${KEYCLOAK_ADMIN_USER:-admin}" --password "${KEYCLOAK_ADMIN_PASSWORD:-admin}" >/dev/null

while IFS='|' read -r key first last; do
  email="${key}@demo.jangubi.sn"
  if [ -n "$(kc get users -r jangubi -q email="$email" --fields id --format csv --noquotes)" ]; then
    echo "existe : $email"; continue
  fi
  kc create users -r jangubi -s username="$email" -s email="$email" -s emailVerified=true \
    -s enabled=true -s firstName="$first" -s lastName="$last" >/dev/null
  kc set-password -r jangubi --username "$email" --new-password "$KC_DEMO_PASSWORD"
  echo "créé : $email"
done <<'LIST'
cure|Joseph|Sarr
vicaire|Paul|Diouf
secretaire|Marie|Faye
doyen|Augustin|Ndiaye
fidele|Awa|Diop
fidele2|Moussa|Mendy
mineur|Fatou|Sène
chancelier|Théodore|Diatta
admin_paroissial|Robert|Sagna
plateforme|Mariama|Ba
LIST

kc add-roles -r jangubi --uusername plateforme@demo.jangubi.sn --rolename platform_admin
echo "rôle platform_admin : plateforme@demo.jangubi.sn"
