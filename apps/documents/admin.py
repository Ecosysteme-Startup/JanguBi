from django.contrib import admin

from apps.documents.models import (
    DocumentRequest,
    DocumentRequestAttachment,
    DocumentRequestStatusLog,
    InternalNote,
)


class StatusLogInline(admin.TabularInline):
    model = DocumentRequestStatusLog
    extra = 0
    readonly_fields = ("from_status", "to_status", "changed_by", "comment", "created_at")
    can_delete = False


class AttachmentInline(admin.TabularInline):
    model = DocumentRequestAttachment
    extra = 0
    readonly_fields = ("file", "uploaded_by", "attachment_type", "label", "created_at")
    can_delete = False


class InternalNoteInline(admin.TabularInline):
    model = InternalNote
    extra = 0
    readonly_fields = ("author", "content", "created_at")
    can_delete = False


@admin.register(DocumentRequest)
class DocumentRequestAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "document_type",
        "status",
        "requester_last_name",
        "requester_first_names",
        "target_node",
        "assigned_to",
        "created_at",
    )
    list_filter = ("status", "document_type")
    search_fields = ("reference", "requester_last_name", "requester_first_names", "target_node__name")
    readonly_fields = ("reference", "created_at", "updated_at")
    raw_id_fields = ("requester", "assigned_to", "target_node", "pickup_place")
    inlines = [StatusLogInline, AttachmentInline, InternalNoteInline]


@admin.register(DocumentRequestStatusLog)
class DocumentRequestStatusLogAdmin(admin.ModelAdmin):
    list_display = ("request", "from_status", "to_status", "changed_by", "created_at")
    readonly_fields = ("request", "from_status", "to_status", "changed_by", "comment", "created_at")
    list_filter = ("to_status",)


@admin.register(DocumentRequestAttachment)
class DocumentRequestAttachmentAdmin(admin.ModelAdmin):
    list_display = ("request", "attachment_type", "label", "uploaded_by", "created_at")
    readonly_fields = ("request", "file", "uploaded_by", "attachment_type", "label", "created_at")


@admin.register(InternalNote)
class InternalNoteAdmin(admin.ModelAdmin):
    list_display = ("request", "author", "created_at")
    readonly_fields = ("request", "author", "content", "created_at")
