from django.contrib import admin
from treebeard.admin import TreeAdmin
from treebeard.forms import movenodeform_factory

from apps.hierarchy.models import MassSchedule, Node, NodeType, PlaceOfWorship, ScheduleException


@admin.register(NodeType)
class NodeTypeAdmin(admin.ModelAdmin):
    list_display = ["code", "label", "is_territorial", "holds_registers", "order"]
    filter_horizontal = ["allowed_parent_types"]


@admin.register(Node)
class NodeAdmin(TreeAdmin):
    form = movenodeform_factory(Node)
    list_display = ["name", "type", "code", "status", "city", "is_active_on_platform"]
    list_filter = ["type", "status", "is_active_on_platform"]
    search_fields = ["name", "code", "city"]
    raw_id_fields = ["located_in"]


class MassScheduleInline(admin.TabularInline):
    model = MassSchedule
    extra = 0


@admin.register(PlaceOfWorship)
class PlaceOfWorshipAdmin(admin.ModelAdmin):
    list_display = ["name", "node", "kind", "is_main", "is_active"]
    list_filter = ["kind", "is_main", "is_active"]
    search_fields = ["name", "node__name"]
    raw_id_fields = ["node"]
    inlines = [MassScheduleInline]


@admin.register(ScheduleException)
class ScheduleExceptionAdmin(admin.ModelAdmin):
    list_display = ["place", "date", "kind", "cancelled", "start_time"]
    list_filter = ["kind", "cancelled"]
    raw_id_fields = ["place"]
