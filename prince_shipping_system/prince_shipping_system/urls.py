"""
URL configuration for prince_shipping_system project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from shipping_system import views

urlpatterns = [
    path('login/', views.user_login, name='user_login'),
    path('accounts/login/', views.user_login, name='user_login'),
    path('', views.home, name='home'),
    path('admin/', admin.site.urls),
    path('users/', views.user_list, name='user_list'),
    path('users/add/', views.add_user, name='add_user'),
    path('users/<int:user_id>/edit/', views.edit_user, name='edit_user'),
    path('users/<int:user_id>/delete/', views.delete_user, name='delete_user'),
    path('importers/', views.importer_list, name='importer_list'),
    path('importers/add/', views.add_importer, name='add_importer'),
    path('importers/<int:importer_id>/edit/', views.edit_importer, name='edit_importer'),
    path('importers/<int:importer_id>/delete/', views.delete_importer, name='delete_importer'),
    path('bills_of_entry/', views.bill_of_entry_list, name='bill_of_entry_list'),
    path('bills_of_entry/add/', views.add_bill_of_entry, name='add_bill_of_entry'),
    path('bills_of_entry/<int:bill_of_entry_id>/edit/', views.edit_bill_of_entry, name='edit_bill_of_entry'),
    path('bills_of_entry/search/', views.search_bill_of_entry, name='search_bill_of_entry'),
    path('bills_of_entry/<int:document_id>/preview/', views.preview_document, name='preview_document'),
    path('bills_of_entry/<int:document_id>/download/', views.download_document, name='download_document'),
    path('bills_of_entry/<int:bill_of_entry_id>/delete/', views.delete_bill_of_entry, name='delete_bill_of_entry'),
    path('internal_documents/', views.internal_document_list, name='internal_document_list'),
    path('internal_documents/add/', views.add_internal_document, name='add_internal_document'),
    path('internal_documents/<int:internal_document_id>/edit/', views.edit_internal_document, name='edit_internal_document'),
    path('internal_documents/search/', views.search_internal_document, name='search_internal_document'),
    path('internal_documents/<int:document_id>/preview/', views.preview_internal_document, name='preview_internal_document'),
    path('internal_documents/<int:document_id>/download/', views.download_internal_document, name='download_internal_document'),
    path('internal_documents/<int:internal_document_id>/delete/', views.delete_internal_document, name='delete_internal_document'),

    path('agreements/', views.agreement_list, name='agreement_list'),
    path('agreements/add/', views.add_agreement, name='add_agreement'),
    path('agreements/<int:agreement_id>/edit/', views.edit_agreement, name='edit_agreement'),
    path('agreements/<int:document_id>/preview/', views.preview_agreement, name='preview_agreement'),
    path('agreements/<int:document_id>/download/', views.download_agreement, name='download_agreement'),
    path('agreements/<int:agreement_id>/delete/', views.delete_agreement, name='delete_agreement'),

    # Truck / Shipment workflow
    path('shipments/in-progress/', views.shipments_in_progress_list, name='shipments_in_progress_list'),
    path('shipments/not-registered/', views.shipment_not_registered_list, name='shipment_not_registered_list'),
    path('shipments/registered/', views.shipment_registered_list, name='shipment_registered_list'),
    path('shipments/assessed/', views.shipment_assessed_list, name='shipment_assessed_list'),
    path('shipments/paid/', views.shipment_paid_list, name='shipment_paid_list'),
    path('shipments/receipted/', views.shipment_receipted_list, name='shipment_receipted_list'),
    path('shipments/release/', views.shipment_release_list, name='shipment_release_list'),
    path('shipments/completed/', views.shipment_completed_list, name='shipment_completed_list'),

    path('shipments/add/', views.add_shipment, name='add_shipment'),
    path('shipments/<int:shipment_id>/edit/', views.edit_shipment, name='edit_shipment'),
    path('shipments/<int:shipment_id>/uploads/', views.shipment_uploads, name='shipment_uploads'),
    path('shipments/<int:shipment_id>/details/', views.shipment_details, name='shipment_details'),
    path('shipments/<int:shipment_id>/transition/', views.shipment_transition, name='shipment_transition'),

    path('shipments/<int:shipment_id>/files/<str:field>/preview/', views.shipment_file_preview, name='shipment_file_preview'),
    path('shipments/<int:shipment_id>/files/<str:field>/download/', views.shipment_file_download, name='shipment_file_download'),

    path('shipments/export/excel/', views.shipments_export_excel, name='shipments_export_excel'),
    path('shipments/completed/export/zimra/', views.shipments_export_zimra_csv, name='shipments_export_zimra_csv'),
    path('shipments/completed/export/documents/', views.shipments_export_documents_zip, name='shipments_export_documents_zip'),
    path('my-account/', views.my_account, name='my_account'),
    path('my-account/edit/', views.edit_user_details, name='edit_user_details'),
    path('logout/', views.user_logout, name='logout'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
