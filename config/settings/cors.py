from config.env import env

# Le refresh token voyage désormais dans un cookie HttpOnly (config/settings/jwt.py).
# Pour qu'un navigateur accepte de l'envoyer sur une requête cross-origin, il faut
# `Access-Control-Allow-Credentials: true` — d'où ce réglage.
CORS_ALLOW_CREDENTIALS = True

# ⚠️ Avec CORS_ALLOW_CREDENTIALS=True, `Access-Control-Allow-Origin: *` est REFUSÉ
# par le navigateur : les origines doivent être explicites. django-cors-headers
# contourne la règle quand CORS_ALLOW_ALL_ORIGINS=True (il renvoie l'origine
# reçue au lieu de `*`), ce qui « marche » mais autorise de fait N'IMPORTE QUEL
# site à émettre des requêtes authentifiées vers l'API. On garde donc une liste
# blanche, même en développement.
CORS_ALLOW_ALL_ORIGINS = env.bool("CORS_ALLOW_ALL_ORIGINS", default=False)

BASE_BACKEND_URL = env.str("DJANGO_BASE_BACKEND_URL", default="http://localhost:8001")
BASE_FRONTEND_URL = env.str("DJANGO_BASE_FRONTEND_URL", default="http://localhost:3000")

# Le thème de connexion Keycloak lit le jour liturgique (lecture publique) pour son bandeau.
KEYCLOAK_ORIGIN = env.str("KEYCLOAK_SERVER_URL", default="http://localhost:8180").rstrip("/")

CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=[BASE_FRONTEND_URL, "http://127.0.0.1:3000", KEYCLOAK_ORIGIN],
)
CORS_ORIGIN_WHITELIST = env.list("DJANGO_CORS_ORIGIN_WHITELIST", default=[BASE_FRONTEND_URL])

# L'en-tête par lequel le client web réclame le transport du refresh token par
# cookie. Non safelisté CORS → il doit être explicitement autorisé, sinon le
# preflight échoue et le mode cookie ne s'active jamais.
CORS_ALLOW_HEADERS = (
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "x-auth-transport",
)
