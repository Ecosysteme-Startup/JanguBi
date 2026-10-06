from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.rosary.serializers import (
    GroupSerializer,
    MysterySerializer,
    PrayerSerializer,
    RosaryDaySerializer,
    SearchPrayerSerializer,
)
from apps.rosary.services import RosaryService


class GroupListApi(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        responses=GroupSerializer(many=True), 
        tags=["Rosary"], 
        summary="List all rosary groups (Mysteries)",
        description="""
        Returns a list of all Rosary Groups (Joyeux, Lumineux, Douloureux, Glorieux).
        
        **What is a Rosary Group?**
        In the Catholic tradition, the Rosary is a meditative prayer based on the life of Jesus Christ. 
        It is divided into 4 groups called 'Mysteries'. Each group contains 5 specific events 
        (e.g., 'The Annunciation' is the 1st Joyful Mystery).
        """
    )
    @method_decorator(cache_page(60 * 60 * 24))  # Cache for 24 hours
    def get(self, request):
        groups = RosaryService.get_groups()
        serializer = GroupSerializer(groups, many=True)
        return Response(serializer.data)


class GroupDetailApi(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        responses=GroupSerializer, 
        tags=["Rosary"], 
        summary="Get details of a specific rosary group by slug",
        description="""
        Retrieve a specific Rosary Group (e.g., 'joyeux') and its 5 mysteries.
        
        **Structure of a Mystery (Dizaine/Decade):**
        When praying a mystery, the believer meditates on the event (often reading a short scripture), 
        then recites a specific sequence of prayers:
        1. One 'Our Father' (Notre Père)
        2. Ten 'Hail Mary's (Je vous salue Marie) - This is why it's called a 'decade' or 'dizaine'.
        3. One 'Glory Be' (Gloire au Père)
        4. (Optional) The Fatima Prayer
        
        The API returns this exact sequential order of prayers under each mystery.
        """
    )
    @method_decorator(cache_page(60 * 60 * 24))
    def get(self, request, slug):
        from apps.rosary.models import MysteryGroup
        try:
            group = RosaryService.get_group_with_mysteries(slug)
            serializer = GroupSerializer(group)
            return Response(serializer.data)
        except MysteryGroup.DoesNotExist:
            return Response({"error": "Rosary Group not found."}, status=404)


class TodayRosaryApi(APIView):
    permission_classes = [AllowAny]

    class TodayRosaryOutputSerializer(serializers.Serializer):
        day = RosaryDaySerializer()
        opening_prayers = PrayerSerializer(many=True)
        standalone_prayers = PrayerSerializer(many=True)

    @extend_schema(
        responses=TodayRosaryOutputSerializer, 
        tags=["Rosary"], 
        summary="Get today's rosary prayers along with standalone prayers",
        description="""
        Fetches the Rosary Group assigned to the current day of the week, along with the introductory 
        and concluding prayers.
        
        **Daily Tradition:**
        - Monday & Saturday: Joyful Mysteries (Joyeux)
        - Tuesday & Friday: Sorrowful Mysteries (Douloureux)
        - Wednesday & Sunday: Glorious Mysteries (Glorieux)
        - Thursday: Luminous Mysteries (Lumineux)
        
        This endpoint also returns `standalone_prayers` (like the Apostles' Creed or the Hail Holy Queen) 
        which are recited at the very beginning and very end of the entire Rosary.
        """
    )
    @method_decorator(cache_page(60 * 60 * 1))  # Cache for 1 hour because day changes
    def get(self, request):
        from apps.rosary.models import RosaryDay
        try:
            day_rosary = RosaryService.get_today_rosary()
        except RosaryDay.DoesNotExist:
            return Response(
                {"error": "Les données du chapelet pour aujourd'hui ne sont pas encore configurées."},
                status=404,
            )
        serializer = RosaryDaySerializer(day_rosary)
        standalone = RosaryService.get_all_standalone_prayers()
        standalone_data = PrayerSerializer(standalone, many=True).data
        opening_data = PrayerSerializer(RosaryService.get_opening_prayers(), many=True).data

        return Response({
            "day": serializer.data,
            "opening_prayers": opening_data,
            "standalone_prayers": standalone_data
        })


class RosarySearchApi(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter("q", OpenApiTypes.STR, description="Search query")
        ],
        responses=SearchPrayerSerializer(many=True),
        tags=["Rosary"],
        summary="Search within rosary prayers using text match"
    )
    def get(self, request):
        query = request.query_params.get("q", "").strip()
        if len(query) < 2:  # validation minimale (endpoint public)
            return Response([])

        prayers = RosaryService.search_text(query)[:50]  # borne défensive
        serializer = SearchPrayerSerializer(prayers, many=True)
        return Response(serializer.data)


class RosaryVectorSearchApi(APIView):
    """Stub endpoint for future RAG implementation via pgvector."""
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter("q", OpenApiTypes.STR, description="Semantic search query")
        ],
        responses=SearchPrayerSerializer(many=True),
        tags=["Rosary"],
        summary="Search within rosary prayers using vector embeddings"
    )
    def get(self, request):
        query = request.query_params.get("q", "").strip()
        if len(query) < 2:
            return Response([])

        prayers = RosaryService.vector_search(query)[:50]
        serializer = SearchPrayerSerializer(prayers, many=True)
        return Response(serializer.data)


class RosaryWeekdayApi(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        responses=TodayRosaryApi.TodayRosaryOutputSerializer, 
        tags=["Rosary"], 
        summary="Get rosary prayers for a specific day of the week",
        description="""
        Fetches the Rosary Group assigned to a given weekday, along with the introductory 
        and concluding standalone prayers.
        
        **Day mapping (0-6):**
        0: Monday (Joyeux)
        1: Tuesday (Douloureux)
        2: Wednesday (Glorieux)
        3: Thursday (Lumineux)
        4: Friday (Douloureux)
        5: Saturday (Joyeux)
        6: Sunday (Glorieux)
        """
    )
    @method_decorator(cache_page(60 * 60 * 24))
    def get(self, request, day):
        from apps.rosary.models import RosaryDay
        try:
            day_rosary = RosaryService.get_daily_rosary(day_of_week=int(day))
            serializer = RosaryDaySerializer(day_rosary)
            standalone = RosaryService.get_all_standalone_prayers()
            standalone_data = PrayerSerializer(standalone, many=True).data
            opening_data = PrayerSerializer(RosaryService.get_opening_prayers(), many=True).data

            return Response({
                "day": serializer.data,
                "opening_prayers": opening_data,
                "standalone_prayers": standalone_data
            })
        except RosaryDay.DoesNotExist:
            return Response({"error": "Invalid day (must be 0-6)."}, status=400)
        except ValueError:
            return Response({"error": "Day must be an integer."}, status=400)


class PrayerListApi(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        responses=PrayerSerializer(many=True), 
        tags=["Rosary"], 
        summary="List all foundational standalone prayers",
        description="""
        Retrieve all foundational pieces used in the Rosary, such as the 'Our Father', 
        the 'Apostles Creed' (Je crois en Dieu), or the 'Fatima Prayer'.
        """
    )
    @method_decorator(cache_page(60 * 60 * 24))
    def get(self, request):
        from apps.rosary.models import Prayer
        prayers = Prayer.objects.all().order_by("id")
        serializer = PrayerSerializer(prayers, many=True)
        return Response(serializer.data)


class MysteryDetailApi(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        responses=MysterySerializer, 
        tags=["Rosary"], 
        summary="Get details of a specific Mystery (Dizaine)",
        description="""
        Retrieve a specific Mystery by its ID, complete with its scriptural meditation 
        and the full sequence of prayers (1 Our Father, 10 Hail Marys, etc.) that 
        compose its 'decade'.
        """
    )
    @method_decorator(cache_page(60 * 60 * 24))
    def get(self, request, pk):
        from apps.rosary.models import Mystery
        try:
            mystery = Mystery.objects.prefetch_related("prayers__prayer").get(pk=pk)
            # Flag it so the serializer knows to include prayers
            mystery._prefetched_objects_cache = mystery._prefetched_objects_cache or {}
            mystery._prefetched_objects_cache["prayers"] = mystery.prayers.all()
            serializer = MysterySerializer(mystery)
            return Response(serializer.data)
        except Mystery.DoesNotExist:
            return Response({"error": "Mystery not found."}, status=404)
