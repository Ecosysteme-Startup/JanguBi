#!/bin/bash
# Compte de l'admin Django (exploitation seulement : il ne donne aucun droit dans l'API,
# où l'administrateur plateforme est le rôle Keycloak platform_admin, ADR-015).
set -a
[ -f .env ] && source .env
set +a

if [ -z "$DJANGO_SUPERUSER_EMAIL" ] || [ -z "$DJANGO_SUPERUSER_PASSWORD" ]; then
    echo "Définir DJANGO_SUPERUSER_EMAIL et DJANGO_SUPERUSER_PASSWORD dans .env."
    exit 1
fi

docker compose exec -T \
    -e DJANGO_SUPERUSER_EMAIL="$DJANGO_SUPERUSER_EMAIL" \
    -e DJANGO_SUPERUSER_PASSWORD="$DJANGO_SUPERUSER_PASSWORD" \
    django python manage.py createsuperuser --noinput
