"""APIs « Pour vous aujourd'hui » : signaux de lecture, signets, réglage, recommandation (plan V2 §6)."""

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin
from apps.api.pagination import LimitOffsetPagination, get_paginated_response, paginated_response_serializer
from apps.api.v1 import V1ApiMixin
from apps.bible.models import Bookmark, ReadingEvent
from apps.bible.services.reading_signals import MAX_EVENTS_PER_BATCH

TAG = "Bible — Pour vous"


# ─── Serializers ──────────────────────────────────────────────────────────────


class ReadingEventInputSerializer(serializers.Serializer):
    client_event_id = serializers.CharField(max_length=64)
    type = serializers.ChoiceField(choices=ReadingEvent.Kind.choices)
    verset_debut_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    verset_fin_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    livre_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    chapitre = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    termine = serializers.BooleanField(required=False, default=False)
    occurred_at = serializers.DateTimeField()

    def validate(self, attrs):
        has_verse = bool(attrs.get("verset_debut_id") or attrs.get("verset_fin_id"))
        has_chapter = bool(attrs.get("livre_id") and attrs.get("chapitre"))
        if not has_verse and not has_chapter:
            raise serializers.ValidationError("Indiquez un verset (verset_debut_id) ou un chapitre (livre_id et chapitre).")
        return attrs


class ReadingEventBatchInputSerializer(serializers.Serializer):
    evenements = ReadingEventInputSerializer(many=True, allow_empty=False, max_length=MAX_EVENTS_PER_BATCH)  # type: ignore[call-arg]  # ListSerializer accepte max_length


class ReadingEventBatchOutputSerializer(serializers.Serializer):
    recus = serializers.IntegerField()
    enregistres = serializers.IntegerField()
    rejetes = serializers.ListField(child=serializers.CharField(), help_text="client_event_id à référence inconnue")
    personnalisation_parole = serializers.BooleanField()


class BookmarkInputSerializer(serializers.Serializer):
    verset_id = serializers.IntegerField(min_value=1)
    couleur = serializers.ChoiceField(choices=Bookmark.Color.choices, required=False, default="", allow_blank=True)
    note = serializers.CharField(required=False, default="", allow_blank=True, max_length=2000)


class BookmarkUpdateSerializer(serializers.Serializer):
    couleur = serializers.ChoiceField(choices=Bookmark.Color.choices, required=False, allow_blank=True)
    note = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class BookmarkOutputSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    verset_id = serializers.IntegerField(source="verse_id")
    reference = serializers.SerializerMethodField()
    livre_id = serializers.IntegerField(source="verse.chapter.book_id")
    chapitre = serializers.IntegerField(source="verse.chapter.number")
    numero = serializers.IntegerField(source="verse.number")
    texte = serializers.CharField(source="verse.text")
    type = serializers.SerializerMethodField()
    couleur = serializers.CharField(source="color")
    note = serializers.CharField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    def get_reference(self, obj) -> str:
        return f"{obj.verse.chapter.book.name} {obj.verse.chapter.number}, {obj.verse.number}"

    def get_type(self, obj) -> str:
        return "surligne" if obj.color else "signet"


class ParolePreferenceSerializer(serializers.Serializer):
    personnalisation_parole = serializers.BooleanField()


class _BookSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nom = serializers.CharField()
    slug = serializers.CharField()


class _VerseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    reference = serializers.CharField()
    livre = _BookSerializer()
    chapitre = serializers.IntegerField()
    numero = serializers.IntegerField()
    texte = serializers.CharField()
    raisons = serializers.ListField(child=serializers.CharField())


class _ContinueSerializer(serializers.Serializer):
    reference = serializers.CharField()
    livre = _BookSerializer()
    chapitre = serializers.IntegerField()
    reprendre_au_verset = serializers.IntegerField(allow_null=True)


class _SuggestedBookSerializer(_BookSerializer):
    raison = serializers.CharField()


class _SuggestedPlanSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    titre = serializers.CharField()
    description = serializers.CharField()
    raison = serializers.CharField()


class PourVousOutputSerializer(serializers.Serializer):
    """Documentation du contrat : la charge utile est servie telle quelle (aucun score)."""

    date = serializers.DateField()
    personnalise = serializers.BooleanField()
    personnalisation_parole = serializers.BooleanField()
    verset = _VerseSerializer(allow_null=True)
    autres_versets = _VerseSerializer(many=True)
    lecture_a_continuer = _ContinueSerializer(allow_null=True)
    livre_suggere = _SuggestedBookSerializer(allow_null=True)
    plan_suggere = _SuggestedPlanSerializer(allow_null=True)
    raisons = serializers.ListField(child=serializers.CharField())


# ─── APIs ─────────────────────────────────────────────────────────────────────


class ReadingEventApi(V1ApiMixin, ApiAuthMixin, APIView):
    @extend_schema(
        tags=[TAG],
        summary="Envoyer des signaux de lecture (par lots, idempotent par client_event_id)",
        request=ReadingEventBatchInputSerializer,
        responses={200: ReadingEventBatchOutputSerializer},
    )
    def post(self, request: Request) -> Response:
        from apps.bible.services.reading_signals import reading_events_record

        serializer = ReadingEventBatchInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = reading_events_record(user=request.user, events=serializer.validated_data["evenements"])
        return Response(ReadingEventBatchOutputSerializer(result).data)

    @extend_schema(
        tags=[TAG],
        summary="Effacer mon historique de lecture (et les recommandations qui en découlent)",
        request=None,
        responses={204: None},
    )
    def delete(self, request: Request) -> Response:
        from apps.bible.services.reading_signals import reading_history_clear

        reading_history_clear(user=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class BookmarkListCreateApi(V1ApiMixin, ApiAuthMixin, APIView):
    @extend_schema(
        tags=[TAG],
        operation_id="v1_bible_signets_list",
        summary="Mes signets et surlignages",
        responses={200: paginated_response_serializer(BookmarkOutputSerializer)},
    )
    def get(self, request: Request) -> Response:
        from apps.bible.selectors import bookmark_list

        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=BookmarkOutputSerializer,
            queryset=bookmark_list(user=request.user),
            request=request,
            view=self,
        )

    @extend_schema(
        tags=[TAG],
        summary="Poser un signet ou surligner un verset (un seul par verset : met à jour s'il existe)",
        request=BookmarkInputSerializer,
        responses={201: BookmarkOutputSerializer},
    )
    def post(self, request: Request) -> Response:
        from apps.bible.selectors import bookmark_get
        from apps.bible.services.reading_signals import bookmark_upsert

        serializer = BookmarkInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        bookmark = bookmark_upsert(user=request.user, verse_id=data["verset_id"], color=data["couleur"], note=data["note"])
        bookmark = bookmark_get(user=request.user, bookmark_id=bookmark.pk)
        return Response(BookmarkOutputSerializer(bookmark).data, status=status.HTTP_201_CREATED)


class BookmarkDetailApi(V1ApiMixin, ApiAuthMixin, APIView):
    @extend_schema(tags=[TAG], summary="Un signet", responses={200: BookmarkOutputSerializer})
    def get(self, request: Request, bookmark_id: int) -> Response:
        from apps.bible.selectors import bookmark_get

        return Response(BookmarkOutputSerializer(bookmark_get(user=request.user, bookmark_id=bookmark_id)).data)

    @extend_schema(
        tags=[TAG],
        summary="Changer la couleur ou la note d'un signet",
        request=BookmarkUpdateSerializer,
        responses={200: BookmarkOutputSerializer},
    )
    def patch(self, request: Request, bookmark_id: int) -> Response:
        from apps.bible.selectors import bookmark_get
        from apps.bible.services.reading_signals import bookmark_update

        serializer = BookmarkUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = {"color" if k == "couleur" else k: v for k, v in serializer.validated_data.items()}
        bookmark = bookmark_update(bookmark=bookmark_get(user=request.user, bookmark_id=bookmark_id), data=data)
        return Response(BookmarkOutputSerializer(bookmark).data)

    @extend_schema(tags=[TAG], summary="Retirer un signet", request=None, responses={204: None})
    def delete(self, request: Request, bookmark_id: int) -> Response:
        from apps.bible.selectors import bookmark_get
        from apps.bible.services.reading_signals import bookmark_delete

        bookmark_delete(bookmark=bookmark_get(user=request.user, bookmark_id=bookmark_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class ParolePreferenceApi(V1ApiMixin, ApiAuthMixin, APIView):
    @extend_schema(tags=[TAG], summary="Mes réglages de la Parole", responses={200: ParolePreferenceSerializer})
    def get(self, request: Request) -> Response:
        from apps.bible.selectors import parole_preference_get

        return Response(ParolePreferenceSerializer(parole_preference_get(user=request.user)).data)

    @extend_schema(
        tags=[TAG],
        summary="Activer ou désactiver « Pour vous aujourd'hui » personnalisé",
        request=ParolePreferenceSerializer,
        responses={200: ParolePreferenceSerializer},
    )
    def put(self, request: Request) -> Response:
        from apps.bible.services.reading_signals import parole_preference_update

        serializer = ParolePreferenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pref = parole_preference_update(user=request.user, **serializer.validated_data)
        return Response(ParolePreferenceSerializer({"personnalisation_parole": pref.personnalisation_parole}).data)


class PourVousApi(V1ApiMixin, ApiAuthMixin, APIView):
    @extend_schema(
        tags=[TAG],
        summary="« Pour vous aujourd'hui » : verset, lecture à continuer, livre et plan suggérés",
        responses={200: PourVousOutputSerializer},
    )
    def get(self, request: Request) -> Response:
        from apps.bible.selectors import pour_vous_get

        return Response(pour_vous_get(user=request.user, day=timezone.localdate()))


__all__ = [
    "BookmarkDetailApi",
    "BookmarkListCreateApi",
    "ParolePreferenceApi",
    "PourVousApi",
    "ReadingEventApi",
]
