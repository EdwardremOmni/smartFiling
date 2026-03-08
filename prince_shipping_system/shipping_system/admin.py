from django.contrib import admin

from .models import (
    Agreement,
    BillOfEntry,
    Importer,
    InternalDocument,
    ShipmentStatusEvent,
    TruckShipment,
    User,
)

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'role')
    search_fields = ('name', 'email', 'role')

@admin.register(Importer)
class ImporterAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_on', 'updated_on')
    search_fields = ('name',)
    ordering = ('-created_on',)

@admin.register(BillOfEntry)
class BillOfEntryAdmin(admin.ModelAdmin):
    list_display = ('importer', 'entry_number', 'invoice_reference', 'created_on', 'updated_on')
    list_filter = ('importer', 'created_on')
    search_fields = ('entry_number', 'invoice_reference', 'importer__name', 'description')
    ordering = ('-created_on',)

@admin.register(InternalDocument)
class InternalDocumentAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'document_name', 'created_on', 'updated_on')
    list_filter = ('created_on',)
    search_fields = ('company_name', 'document_name', 'description')
    ordering = ('-created_on',)


@admin.register(Agreement)
class AgreementAdmin(admin.ModelAdmin):
    list_display = ('importer', 'company_name', 'created_on', 'updated_on')
    list_filter = ('importer', 'created_on')
    search_fields = ('company_name', 'importer__name')
    ordering = ('-created_on',)


@admin.register(TruckShipment)
class TruckShipmentAdmin(admin.ModelAdmin):
    list_display = (
        'truck_registration',
        'manifest_number',
        'status',
        'weight_kg',
        'created_on',
        'updated_on',
    )
    list_filter = ('status', 'created_on')
    search_fields = (
        'truck_registration',
        'manifest_number',
        'cill_number',
        'bill_of_entry_number',
        'assessment_number',
        'receipt_number',
    )
    date_hierarchy = 'created_on'
    ordering = ('-created_on',)
    readonly_fields = ('created_on', 'updated_on')


@admin.register(ShipmentStatusEvent)
class ShipmentStatusEventAdmin(admin.ModelAdmin):
    list_display = ('shipment', 'from_status', 'to_status', 'changed_by', 'changed_at')
    list_filter = ('from_status', 'to_status', 'changed_at')
    search_fields = ('shipment__truck_registration', 'shipment__manifest_number', 'changed_by__username')
    ordering = ('-changed_at',)
    raw_id_fields = ('shipment', 'changed_by')