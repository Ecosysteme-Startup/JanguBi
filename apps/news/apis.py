from typing import Any

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin, PermissionClassesType
from apps.api.pagination import LimitOffsetPagination, get_paginated_response, paginated_response_serializer
from apps.api.v1 import V1ApiMixin
from apps.core.exceptions import NotFoundError
from apps.hierarchy import selectors as hierarchy_selectors
from apps.hierarchy.authz import HasCapability
from apps.hierarchy.models import PlaceOfWorship
from apps.news import selectors, services
from apps.news.serializers import (
    ArticleCreateInputSerializer,
    ArticleFilterSerializer,
    ArticleListOutputSerializer,
    ArticleOutputSerializer,
    ArticlePublishInputSerializer,
    ArticleUnpublishInputSerializer,
    ArticleUpdateInputSerializer,
    CategoryOutputSerializer,
    ReactionInputSerializer,
    ReadOutputSerializer,
    StaffArticleFilterSerializer,
    StaffArticleOutputSerializer,
)

TAG = ["news"]
_PAGINATION = [
    OpenApiParameter("limit", int, description="Nombre de résultats (défaut 10, max 50)"),
    OpenApiParameter("offset", int, description="Décalage"),
]


class _PublicApi(V1ApiMixin, ApiAuthMixin, APIView):
    """Lecture publique ; un utilisateur connecté voit en plus ses propres réactions."""

    permission_classes: PermissionClassesType = (AllowAny,)


class _AuthedApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes: PermissionClassesType = (IsAuthenticated,)


class _StaffApi(V1ApiMixin, ApiAuthMixin, APIView):
    """``annonces.publier`` sur au moins un nœud (ou plateforme) ; le nœud précis est
    vérifié par le service, et les objets hors portée répondent 404."""

    permission_classes: PermissionClassesType = (IsAuthenticated, HasCapability("annonces.publier"))

    def get_permissions(self):
        from apps.hierarchy import authz

        if authz.peut(self.request.user, "plateforme.admin", None):
            return [IsAuthenticated()]
        return super().get_permissions()


# --- Public ----------------------------------------------------------------------------------


class CategoryListApi(_PublicApi):
    @extend_schema(tags=TAG, summary="Catégories d'articles", responses=CategoryOutputSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(CategoryOutputSerializer(selectors.category_list(), many=True).data)


class ArticleListApi(_PublicApi):
    @extend_schema(
        tags=TAG,
        operation_id="news_list",
        summary="Annonces et articles publiés (filtres : nœud et sous-arbre, dimanche, type, catégorie)",
        parameters=[ArticleFilterSerializer, *_PAGINATION],
        responses=paginated_response_serializer(ArticleListOutputSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = ArticleFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        data = filters.validated_data
        node = hierarchy_selectors.node_get(node_id=data["node"]) if data.get("node") else None
        queryset = selectors.article_list_published(
            node=node,
            sunday=data.get("sunday"),
            content_type=data.get("type"),
            category_id=data.get("category"),
            viewer=request.user,
        )
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=ArticleListOutputSerializer,
            queryset=queryset,
            request=request,
            view=self,
        )


class ArticleDetailApi(_PublicApi):
    @extend_schema(tags=TAG, summary="Détail d'un article publié", responses=ArticleOutputSerializer)
    def get(self, request: Request, article_id: str) -> Response:
        return Response(ArticleOutputSerializer(selectors.article_get_published(article_id=article_id, viewer=request.user)).data)


class ArticleReadApi(_AuthedApi):
    @extend_schema(tags=TAG, summary="Marquer comme lu (une lecture par personne)", request=None, responses=ReadOutputSerializer)
    def post(self, request: Request, article_id: str) -> Response:
        article = selectors.article_get_published(article_id=article_id)
        return Response({"first_read": services.article_mark_read(article=article, user=request.user)})


class ArticleReactionApi(_AuthedApi):
    @extend_schema(
        tags=TAG,
        summary="Poser ou retirer une réaction (idempotent)",
        request=ReactionInputSerializer,
        responses=ArticleOutputSerializer,
    )
    def put(self, request: Request, article_id: str) -> Response:
        serializer = ReactionInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        article = selectors.article_get_published(article_id=article_id)
        services.article_reaction_set(article=article, user=request.user, **serializer.validated_data)
        return Response(ArticleOutputSerializer(selectors.article_get_published(article_id=article_id, viewer=request.user)).data)


class MeFeedApi(_AuthedApi):
    @extend_schema(
        tags=["me"],
        operation_id="me_feed",
        summary="Mon flux : contenus globaux, de ma paroisse suivie et de ses ancêtres",
        parameters=_PAGINATION,
        responses=paginated_response_serializer(ArticleListOutputSerializer),
    )
    def get(self, request: Request) -> Response:
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=ArticleListOutputSerializer,
            queryset=selectors.feed_for(user=request.user),
            request=request,
            view=self,
        )


# --- Staff ---------------------------------------------------------------------------------


def _resolve_scope(data: dict[str, Any]) -> dict[str, Any]:
    data = dict(data)
    node_id = data.pop("node_id", None)
    place_id = data.pop("place_id", None)
    data["node"] = hierarchy_selectors.node_get(node_id=node_id) if node_id else None
    data["place"] = None
    if place_id:
        data["place"] = PlaceOfWorship.objects.filter(pk=place_id).first()
        if data["place"] is None:
            raise NotFoundError("Lieu de culte introuvable.", {"place_id": place_id})
    if "category_id" in data:
        data["category"] = selectors.category_get(category_id=data.pop("category_id"))
    return data


class StaffArticleListCreateApi(_StaffApi):
    @extend_schema(
        tags=TAG,
        operation_id="staff_news_list",
        summary="Mes contenus à gérer (tous statuts, compteur de lectures)",
        parameters=[StaffArticleFilterSerializer, *_PAGINATION],
        responses=paginated_response_serializer(StaffArticleOutputSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = StaffArticleFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=StaffArticleOutputSerializer,
            queryset=selectors.article_list_for_staff(user=request.user, filters=filters.validated_data),
            request=request,
            view=self,
        )

    @extend_schema(
        tags=TAG,
        summary="Créer un brouillon (annonces.publier sur le nœud)",
        request=ArticleCreateInputSerializer,
        responses={201: StaffArticleOutputSerializer},
    )
    def post(self, request: Request) -> Response:
        serializer = ArticleCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        article = services.article_create(author=request.user, **_resolve_scope(serializer.validated_data))
        return Response(
            StaffArticleOutputSerializer(selectors.article_get_for_staff(user=request.user, article_id=article.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class StaffArticleDetailApi(_StaffApi):
    @extend_schema(tags=TAG, summary="Détail d'un contenu (tous statuts)", responses=StaffArticleOutputSerializer)
    def get(self, request: Request, article_id: str) -> Response:
        return Response(StaffArticleOutputSerializer(selectors.article_get_for_staff(user=request.user, article_id=article_id)).data)

    @extend_schema(
        tags=TAG, summary="Modifier un contenu", request=ArticleUpdateInputSerializer, responses=StaffArticleOutputSerializer
    )
    def patch(self, request: Request, article_id: str) -> Response:
        article = selectors.article_get_for_staff(user=request.user, article_id=article_id)
        serializer = ArticleUpdateInputSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if "category_id" in data:
            data["category"] = selectors.category_get(category_id=data.pop("category_id"))
        services.article_update(article=article, editor=request.user, data=data)
        return Response(StaffArticleOutputSerializer(selectors.article_get_for_staff(user=request.user, article_id=article_id)).data)

    @extend_schema(tags=TAG, summary="Supprimer un brouillon ou un contenu retiré", responses={204: None})
    def delete(self, request: Request, article_id: str) -> Response:
        services.article_delete(article=selectors.article_get_for_staff(user=request.user, article_id=article_id), editor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class StaffArticlePublishApi(_StaffApi):
    @extend_schema(
        tags=TAG,
        summary="Publier maintenant ou programmer (publish_at futur)",
        request=ArticlePublishInputSerializer,
        responses=StaffArticleOutputSerializer,
    )
    def post(self, request: Request, article_id: str) -> Response:
        serializer = ArticlePublishInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        article = selectors.article_get_for_staff(user=request.user, article_id=article_id)
        services.article_publish(article=article, editor=request.user, publish_at=serializer.validated_data.get("publish_at"))
        return Response(StaffArticleOutputSerializer(selectors.article_get_for_staff(user=request.user, article_id=article_id)).data)


class StaffArticleUnpublishApi(_StaffApi):
    @extend_schema(
        tags=TAG, summary="Retirer un contenu publié ou programmé", request=ArticleUnpublishInputSerializer,
        responses=StaffArticleOutputSerializer,
    )
    def post(self, request: Request, article_id: str) -> Response:
        serializer = ArticleUnpublishInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        article = selectors.article_get_for_staff(user=request.user, article_id=article_id)
        services.article_unpublish(article=article, editor=request.user, reason=serializer.validated_data["reason"])
        return Response(StaffArticleOutputSerializer(selectors.article_get_for_staff(user=request.user, article_id=article_id)).data)
