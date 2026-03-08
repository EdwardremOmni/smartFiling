from django.shortcuts import render, redirect, get_object_or_404
from .models import (
    User as AppUser,
    Importer,
    BillOfEntry,
    InternalDocument,
    Agreement,
    TruckShipment,
    ShipmentStatusEvent,
)
from django.contrib.auth.decorators import login_required
import mimetypes
from django.http import HttpResponse, FileResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User as AuthUser
from django.conf import settings
from django.core.files.storage import FileSystemStorage
import os
from django.db.models import Q
from django.db import IntegrityError
import json
from django.urls import reverse
from django.core.paginator import Paginator

from datetime import datetime, date
from decimal import Decimal
from typing import Optional
import io
import zipfile

from openpyxl import Workbook




# --- HTMX helpers ---
def _is_htmx(request) -> bool:
    return request.headers.get('HX-Request', '').lower() == 'true'


def _hx_target(request) -> str:
    return request.headers.get('HX-Target', '')


def _render_htmx(request, full_template: str, partial_template: str, context: dict):
    if _is_htmx(request):
        # If the request is swapping the main content area, include OOB updates
        # for sidebar/topbar so role/auth-based links stay in sync.
        if _hx_target(request) == 'main-content':
            merged = dict(context)
            merged['content_template'] = partial_template
            return render(request, 'partials/_htmx_page.html', merged)
        return render(request, partial_template, context)
    return render(request, full_template, context)


def _hx_trigger_response(events: dict, status: int = 204):
    response = HttpResponse('', status=status)
    response['HX-Trigger'] = json.dumps(events)
    return response


def _clean(value: str) -> str:
    return (value or '').strip()


def _is_manager(user) -> bool:
    return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))


DEFAULT_PER_PAGE = 50
PER_PAGE_CHOICES = {10, 25, 50, 100}


def _get_per_page(request) -> int:
    raw = request.GET.get('per_page')
    try:
        value = int(raw) if raw else DEFAULT_PER_PAGE
    except (TypeError, ValueError):
        value = DEFAULT_PER_PAGE
    return value if value in PER_PAGE_CHOICES else DEFAULT_PER_PAGE


def _forbid_unless_manager(request):
    if _is_manager(request.user):
        return None
    return HttpResponse('Forbidden', status=403)



#Login Views
def user_login(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            # Redirect to a specific page after login (e.g., home page)
            return redirect('home')
        else:
            # Handle invalid login credentials (display an error message, redirect to login page, etc.)
            context = {'error_message': 'Invalid username or password'}
            if _is_htmx(request):
                return render(request, 'partials/login.html', context, status=401)
            return render(request, 'login.html', context)
    
    # If it's a GET request or login failed, render the login page
    if _is_htmx(request):
        return render(request, 'partials/login.html')
    return render(request, 'login.html')

# User Views
@login_required
def user_list(request):
    forbidden = _forbid_unless_manager(request)
    if forbidden:
        return forbidden

    users = AuthUser.objects.all().order_by('username')
    query = request.GET.get('q')
    if query:
        q = query.strip()
        users = users.filter(
            Q(username__icontains=q)
            | Q(email__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
        )
        q_lower = q.lower()
        if q_lower in {'manager', 'managers'}:
            users = users.filter(is_staff=True)
        elif q_lower in {'user', 'users'}:
            users = users.filter(is_staff=False)

    per_page = _get_per_page(request)
    paginator = Paginator(users, per_page)
    page_obj = paginator.get_page(request.GET.get('page'))
    context = {
        'users': page_obj,
        'page_obj': page_obj,
        'query': query,
        'per_page': per_page,
        'title': 'Users',
        'base_url': reverse('user_list'),
        'target_id': 'user-table',
    }
    if _is_htmx(request) and _hx_target(request) == 'user-table':
        return render(request, 'partials/users/_table.html', context)
    return _render_htmx(request, 'users/user_list.html', 'partials/users/user_list.html', context)

@login_required
def add_user(request):
    forbidden = _forbid_unless_manager(request)
    if forbidden:
        return forbidden

    if _is_htmx(request) and request.method == 'GET' and _hx_target(request) == 'modal-body':
        return render(request, 'partials/modals/user_form.html', {'user_obj': None, 'values': {}})

    if request.method == 'POST':
        name = _clean(request.POST.get('name'))
        email = _clean(request.POST.get('email'))
        password = _clean(request.POST.get('password'))
        role = _clean(request.POST.get('role'))

        errors = []
        if not name:
            errors.append('Name is required.')
        if not email:
            errors.append('Email is required.')
        if not password:
            errors.append('Password is required.')
        if role not in ['Manager', 'User']:
            errors.append('Role must be Manager or User.')

        username = (email or '').lower()
        if username and AuthUser.objects.filter(username=username).exists():
            errors.append('Email already exists. Please enter another email.')

        if errors:
            if _is_htmx(request) and _hx_target(request) == 'modal-body':
                return render(
                    request,
                    'partials/modals/user_form.html',
                    {'user_obj': None, 'errors': errors, 'values': {'name': name, 'email': email, 'role': role}},
                )
            return render(request, 'users/add_user.html', {'errors': errors, 'values': {'name': name, 'email': email, 'role': role}})

        new_user = AuthUser.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=name,
        )
        new_user.is_staff = role == 'Manager'
        new_user.save()

        if _is_htmx(request) and _hx_target(request) == 'modal-body':
            return _hx_trigger_response({'closeModal': True, 'usersChanged': True})
        return redirect('user_list')

    return _render_htmx(request, 'users/add_user.html', 'partials/users/add_user.html', {'title': 'Add User', 'values': {}})

@login_required
def edit_user(request, user_id):
    forbidden = _forbid_unless_manager(request)
    if forbidden:
        return forbidden

    user_obj = get_object_or_404(AuthUser, id=user_id)

    if _is_htmx(request) and request.method == 'GET' and _hx_target(request) == 'modal-body':
        values = {
            'name': (user_obj.get_full_name() or user_obj.first_name or user_obj.username),
            'email': user_obj.email,
            'role': 'Manager' if (user_obj.is_staff or user_obj.is_superuser) else 'User',
        }
        return render(request, 'partials/modals/user_form.html', {'user_obj': user_obj, 'values': values})

    if request.method == 'POST':
        name = _clean(request.POST.get('name'))
        email = _clean(request.POST.get('email'))
        password = _clean(request.POST.get('password'))
        role = _clean(request.POST.get('role'))

        errors = []
        if not name:
            errors.append('Name is required.')
        if not email:
            errors.append('Email is required.')
        if role not in ['Manager', 'User']:
            errors.append('Role must be Manager or User.')

        username = (email or '').lower()
        if username and AuthUser.objects.filter(username=username).exclude(pk=user_obj.pk).exists():
            errors.append('Email already exists. Please enter another email.')

        if errors:
            if _is_htmx(request) and _hx_target(request) == 'modal-body':
                return render(
                    request,
                    'partials/modals/user_form.html',
                    {'user_obj': user_obj, 'errors': errors, 'values': {'name': name, 'email': email, 'role': role}},
                )
            return render(request, 'users/edit_user.html', {'user_obj': user_obj, 'errors': errors, 'values': {'name': name, 'email': email, 'role': role}})

        user_obj.first_name = name
        user_obj.email = email
        user_obj.username = username
        user_obj.is_staff = role == 'Manager'
        if password:
            user_obj.set_password(password)
        user_obj.save()

        if _is_htmx(request) and _hx_target(request) == 'modal-body':
            return _hx_trigger_response({'closeModal': True, 'usersChanged': True})
        return redirect('user_list')

    values = {
        'name': (user_obj.get_full_name() or user_obj.first_name or user_obj.username),
        'email': user_obj.email,
        'role': 'Manager' if (user_obj.is_staff or user_obj.is_superuser) else 'User',
    }
    return _render_htmx(
        request,
        'users/edit_user.html',
        'partials/users/edit_user.html',
        {'user_obj': user_obj, 'values': values, 'title': 'Edit User'},
    )

@login_required
def delete_user(request, user_id):
    forbidden = _forbid_unless_manager(request)
    if forbidden:
        return forbidden

    user_obj = get_object_or_404(AuthUser, id=user_id)
    if user_obj.id == request.user.id:
        return HttpResponse('Cannot delete your own account.', status=400)
    if user_obj.is_superuser:
        return HttpResponse('Cannot delete a superuser account.', status=400)

    user_obj.delete()
    if _is_htmx(request) and _hx_target(request) == 'modal-body':
        return _hx_trigger_response({'closeModal': True, 'usersChanged': True})
    return redirect('user_list')

# Importer Views
@login_required
def importer_list(request):
    importers = Importer.objects.all()

    query = request.GET.get('q')
    if query:
        importers = importers.filter(name__icontains=query)  # Filter importers by name (case-insensitive)

    per_page = _get_per_page(request)
    paginator = Paginator(importers.order_by('-created_on'), per_page)
    page_obj = paginator.get_page(request.GET.get('page'))
    context = {
        'importers': page_obj,
        'page_obj': page_obj,
        'query': query,
        'per_page': per_page,
        'title': 'Importers',
        'base_url': reverse('importer_list'),
        'target_id': 'importer-table',
    }
    if _is_htmx(request) and _hx_target(request) == 'importer-table':
        return render(request, 'partials/importers/_table.html', context)
    return _render_htmx(request, 'importers/importer_list.html', 'partials/importers/importer_list.html', context)

@login_required
def add_importer(request):
    if _is_htmx(request) and request.method == 'GET' and _hx_target(request) == 'modal-body':
        return render(request, 'partials/modals/importer_form.html', {'importer': None, 'values': {}})

    if request.method == 'POST':
        name = _clean(request.POST.get('name'))
        errors = []
        if not name:
            errors.append('Importer name is required.')

        if errors:
            if _is_htmx(request) and _hx_target(request) == 'modal-body':
                return render(
                    request,
                    'partials/modals/importer_form.html',
                    {'importer': None, 'errors': errors, 'values': {'name': name}},
                )
            return render(request, 'importers/add_importer.html', {'errors': errors})

        Importer.objects.create(name=name)
        if _is_htmx(request) and _hx_target(request) == 'modal-body':
            return _hx_trigger_response({'closeModal': True, 'importersChanged': True})
        return redirect('importer_list')

    return _render_htmx(request, 'importers/add_importer.html', 'partials/importers/add_importer.html', {'title': 'Add Importer'})

@login_required
def edit_importer(request, importer_id):
    importer = Importer.objects.get(id=importer_id)

    if _is_htmx(request) and request.method == 'GET' and _hx_target(request) == 'modal-body':
        return render(request, 'partials/modals/importer_form.html', {'importer': importer, 'values': {'name': importer.name}})

    if request.method == 'POST':
        name = _clean(request.POST.get('name'))
        errors = []
        if not name:
            errors.append('Importer name is required.')

        if errors:
            if _is_htmx(request) and _hx_target(request) == 'modal-body':
                return render(
                    request,
                    'partials/modals/importer_form.html',
                    {'importer': importer, 'errors': errors, 'values': {'name': name}},
                )
            return render(request, 'importers/edit_importer.html', {'importer': importer, 'errors': errors})

        importer.name = name
        importer.save()
        if _is_htmx(request) and _hx_target(request) == 'modal-body':
            return _hx_trigger_response({'closeModal': True, 'importersChanged': True})
        return redirect('importer_list')

    return _render_htmx(
        request,
        'importers/edit_importer.html',
        'partials/importers/edit_importer.html',
        {'importer': importer, 'title': 'Edit Importer'},
    )

@login_required
def delete_importer(request, importer_id):
    importer = Importer.objects.get(id=importer_id)
    importer.delete()
    return redirect('importer_list')

# Bill of Entry Views
@login_required
def bill_of_entry_list(request):
    bills_of_entry = BillOfEntry.objects.all()
    query = request.GET.get('q')
    if query:
        bills_of_entry = bills_of_entry.filter(
            Q(importer__name__icontains=query)
            | Q(entry_number__icontains=query)
            | Q(invoice_reference__icontains=query)
            | Q(description__icontains=query)
        )

    per_page = _get_per_page(request)
    paginator = Paginator(bills_of_entry.order_by('-created_on'), per_page)
    page_obj = paginator.get_page(request.GET.get('page'))
    context = {
        'bills_of_entry': page_obj,
        'page_obj': page_obj,
        'query': query,
        'per_page': per_page,
        'title': 'Bills of Entry',
        'base_url': reverse('bill_of_entry_list'),
        'target_id': 'bill-table',
    }
    if _is_htmx(request) and _hx_target(request) == 'bill-table':
        return render(request, 'partials/bills/_table.html', context)
    return _render_htmx(request, 'bills/bill_of_entry_list.html', 'partials/bills/bill_of_entry_list.html', context)

@login_required
def add_bill_of_entry(request):
    importers = Importer.objects.all()

    if _is_htmx(request) and request.method == 'GET' and _hx_target(request) == 'modal-body':
        return render(
            request,
            'partials/modals/bill_form.html',
            {'bill_of_entry': None, 'importers': importers, 'values': {}},
        )
    
    if request.method == 'POST':
        importer_id = _clean(request.POST.get('importer'))
        entry_number = _clean(request.POST.get('entry_number'))
        invoice_reference = _clean(request.POST.get('invoice_reference'))
        description = _clean(request.POST.get('description'))
        attached_document = request.FILES.get('documents')

        errors = []
        if not importer_id:
            errors.append('Importer is required.')
        if not entry_number:
            errors.append('Entry number is required.')
        if not description:
            errors.append('Description is required.')
        if not attached_document:
            errors.append('A document attachment is required.')

        values = {
            'importer': importer_id,
            'entry_number': entry_number,
            'invoice_reference': invoice_reference,
            'description': description,
        }

        focus_entry_number = False
        if entry_number and BillOfEntry.objects.filter(entry_number=entry_number).exists():
            errors.append('Entry number already exists. Please enter another entry number.')
            focus_entry_number = True

        if errors:
            if _is_htmx(request) and _hx_target(request) == 'modal-body':
                return render(
                    request,
                    'partials/modals/bill_form.html',
                    {'bill_of_entry': None, 'importers': importers, 'errors': errors, 'values': values, 'focus_entry_number': focus_entry_number},
                )
            return render(request, 'bills/add_bill_of_entry.html', {'importers': importers, 'errors': errors})

        try:
            importer_instance = Importer.objects.get(id=importer_id)
            BillOfEntry.objects.create(
                importer=importer_instance,
                entry_number=entry_number,
                invoice_reference=invoice_reference,
                description=description,
                attached_documents=attached_document,
            )
        except Importer.DoesNotExist:
            errors = ['Selected importer does not exist.']
        except IntegrityError:
            errors = ['Entry number already exists. Please enter another entry number.']

        if errors:
            if _is_htmx(request) and _hx_target(request) == 'modal-body':
                return render(
                    request,
                    'partials/modals/bill_form.html',
                    {'bill_of_entry': None, 'importers': importers, 'errors': errors, 'values': values, 'focus_entry_number': focus_entry_number},
                )
            return render(request, 'bills/add_bill_of_entry.html', {'importers': importers, 'errors': errors})

        if _is_htmx(request) and _hx_target(request) == 'modal-body':
            return _hx_trigger_response({'closeModal': True, 'billsChanged': True})
        return redirect('bill_of_entry_list')
    return _render_htmx(
        request,
        'bills/add_bill_of_entry.html',
        'partials/bills/add_bill_of_entry.html',
        {'importers': importers, 'title': 'Add Bill of Entry'},
    )

@login_required
def edit_bill_of_entry(request, bill_of_entry_id):
    importers = Importer.objects.all()
    bill_of_entry = BillOfEntry.objects.get(id=bill_of_entry_id)

    if _is_htmx(request) and request.method == 'GET' and _hx_target(request) == 'modal-body':
        values = {
            'importer': str(bill_of_entry.importer_id),
            'entry_number': bill_of_entry.entry_number,
            'invoice_reference': bill_of_entry.invoice_reference,
            'description': bill_of_entry.description,
        }
        return render(
            request,
            'partials/modals/bill_form.html',
            {'bill_of_entry': bill_of_entry, 'importers': importers, 'values': values},
        )
    if request.method == 'POST':
        importer_id = _clean(request.POST.get('importer'))
        entry_number = _clean(request.POST.get('entry_number'))
        invoice_reference = _clean(request.POST.get('invoice_reference'))
        description = _clean(request.POST.get('description'))
        attached_document = request.FILES.get('documents')

        errors = []
        if not importer_id:
            errors.append('Importer is required.')
        if not entry_number:
            errors.append('Entry number is required.')
        if not description:
            errors.append('Description is required.')

        values = {
            'importer': importer_id,
            'entry_number': entry_number,
            'invoice_reference': invoice_reference,
            'description': description,
        }

        focus_entry_number = False
        if entry_number and BillOfEntry.objects.filter(entry_number=entry_number).exclude(pk=bill_of_entry.pk).exists():
            errors.append('Entry number already exists. Please enter another entry number.')
            focus_entry_number = True

        if errors:
            if _is_htmx(request) and _hx_target(request) == 'modal-body':
                return render(
                    request,
                    'partials/modals/bill_form.html',
                    {'bill_of_entry': bill_of_entry, 'importers': importers, 'errors': errors, 'values': values, 'focus_entry_number': focus_entry_number},
                )
            return render(request, 'bills/edit_bill_of_entry.html', {'bill_of_entry': bill_of_entry, 'importers': importers, 'errors': errors})

        try:
            bill_of_entry.importer = Importer.objects.get(id=importer_id)
        except Importer.DoesNotExist:
            errors = ['Selected importer does not exist.']
            if _is_htmx(request) and _hx_target(request) == 'modal-body':
                return render(
                    request,
                    'partials/modals/bill_form.html',
                    {'bill_of_entry': bill_of_entry, 'importers': importers, 'errors': errors, 'values': values, 'focus_entry_number': focus_entry_number},
                )
            return render(request, 'bills/edit_bill_of_entry.html', {'bill_of_entry': bill_of_entry, 'importers': importers, 'errors': errors})

        bill_of_entry.entry_number = entry_number
        bill_of_entry.invoice_reference = invoice_reference
        bill_of_entry.description = description
        if attached_document:
            bill_of_entry.attached_documents = attached_document

        try:
            bill_of_entry.save()
        except IntegrityError:
            errors = ['Entry number already exists. Please enter another entry number.']
            if _is_htmx(request) and _hx_target(request) == 'modal-body':
                return render(
                    request,
                    'partials/modals/bill_form.html',
                    {'bill_of_entry': bill_of_entry, 'importers': importers, 'errors': errors, 'values': values, 'focus_entry_number': True},
                )
            return render(request, 'bills/edit_bill_of_entry.html', {'bill_of_entry': bill_of_entry, 'importers': importers, 'errors': errors})

        if _is_htmx(request) and _hx_target(request) == 'modal-body':
            return _hx_trigger_response({'closeModal': True, 'billsChanged': True})
        return redirect('bill_of_entry_list')
    return _render_htmx(
        request,
        'bills/edit_bill_of_entry.html',
        'partials/bills/edit_bill_of_entry.html',
        {'bill_of_entry': bill_of_entry, 'importers': importers, 'title': 'Edit Bill of Entry'},
    )

@login_required
def search_bill_of_entry(request):
    # Backwards-compatible endpoint: delegate to list view filtering.
    return bill_of_entry_list(request)

@login_required
def preview_document(request, document_id):
    bill_of_entry = BillOfEntry.objects.get(id=document_id)
    file_path = bill_of_entry.attached_documents.name  # Get the file path of the attached document
    file_name = bill_of_entry.attached_documents.name.split('/')[-1]  # Extract the file name

    # Check if the file is a PDF
    if file_path.endswith('.pdf'):
        # Serve the PDF file for preview
        with open(os.path.join(settings.MEDIA_ROOT, file_path), 'rb') as pdf_file:
            response = HttpResponse(pdf_file.read(), content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="{file_name}"'
            return response
    else:
        return HttpResponse("Document Preview is not available for this file type.")

@login_required
def download_document(request, document_id):
    # Retrieve the BillOfEntry object based on the document_id
    bill_of_entry = get_object_or_404(BillOfEntry, id=document_id)
    
    # Get the file path of the attached document
    file_path = bill_of_entry.attached_documents.path
    
    # Set the appropriate content type for the response
    content_type = mimetypes.guess_type(file_path)[0]
    
    # Create a FileResponse with the file
    response = FileResponse(open(file_path, 'rb'), content_type=content_type)
    
    # Set the content-disposition header for the response to trigger a download
    response['Content-Disposition'] = f'attachment; filename="{os.path.basename(file_path)}"'
    
    return response

@login_required
def delete_bill_of_entry(request, bill_of_entry_id):
    bill_of_entry = BillOfEntry.objects.get(id=bill_of_entry_id)
    bill_of_entry.delete()
    return redirect('bill_of_entry_list')

# Internal Document Views
@login_required
def internal_document_list(request):
    internal_documents = InternalDocument.objects.all()
    query = request.GET.get('q')
    if query:
        internal_documents = internal_documents.filter(
            Q(company_name__icontains=query)
            | Q(document_name__icontains=query)
            | Q(description__icontains=query)
        )

    per_page = _get_per_page(request)
    paginator = Paginator(internal_documents.order_by('-created_on'), per_page)
    page_obj = paginator.get_page(request.GET.get('page'))
    context = {
        'internal_documents': page_obj,
        'page_obj': page_obj,
        'query': query,
        'per_page': per_page,
        'title': 'Documents',
        'base_url': reverse('internal_document_list'),
        'target_id': 'doc-table',
    }
    if _is_htmx(request) and _hx_target(request) == 'doc-table':
        return render(request, 'partials/docs/_table.html', context)
    return _render_htmx(
        request,
        'docs/internal_document_list.html',
        'partials/docs/internal_document_list.html',
        context,
    )

@login_required
def add_internal_document(request):
    if _is_htmx(request) and request.method == 'GET' and _hx_target(request) == 'modal-body':
        return render(request, 'partials/modals/doc_form.html', {'internal_document': None, 'values': {}})

    if request.method == 'POST':
        company_name = _clean(request.POST.get('company_name'))
        document_name = _clean(request.POST.get('document_name'))
        description = _clean(request.POST.get('description'))
        attached_document = request.FILES.get('documents')

        errors = []
        if not company_name:
            errors.append('Company name is required.')
        if not document_name:
            errors.append('Document name is required.')
        if not description:
            errors.append('Description is required.')
        if not attached_document:
            errors.append('A document attachment is required.')

        values = {'company_name': company_name, 'document_name': document_name, 'description': description}
        if errors:
            if _is_htmx(request) and _hx_target(request) == 'modal-body':
                return render(
                    request,
                    'partials/modals/doc_form.html',
                    {'internal_document': None, 'errors': errors, 'values': values},
                )
            return render(request, 'docs/add_internal_document.html', {'errors': errors})

        InternalDocument.objects.create(
            company_name=company_name,
            document_name=document_name,
            description=description,
            attached_documents=attached_document,
        )

        if _is_htmx(request) and _hx_target(request) == 'modal-body':
            return _hx_trigger_response({'closeModal': True, 'docsChanged': True})
        return redirect('internal_document_list')

    return _render_htmx(request, 'docs/add_internal_document.html', 'partials/docs/add_internal_document.html', {'title': 'Add Document'})

@login_required
def edit_internal_document(request, internal_document_id):
    internal_document = InternalDocument.objects.get(id=internal_document_id)

    if _is_htmx(request) and request.method == 'GET' and _hx_target(request) == 'modal-body':
        values = {
            'company_name': internal_document.company_name,
            'document_name': internal_document.document_name,
            'description': internal_document.description,
        }
        return render(request, 'partials/modals/doc_form.html', {'internal_document': internal_document, 'values': values})
    
    if request.method == 'POST':
        company_name = _clean(request.POST.get('company_name'))
        document_name = _clean(request.POST.get('document_name'))
        description = _clean(request.POST.get('description'))
        attached_document = request.FILES.get('documents')

        errors = []
        if not company_name:
            errors.append('Company name is required.')
        if not document_name:
            errors.append('Document name is required.')
        if not description:
            errors.append('Description is required.')

        values = {'company_name': company_name, 'document_name': document_name, 'description': description}
        if errors:
            if _is_htmx(request) and _hx_target(request) == 'modal-body':
                return render(
                    request,
                    'partials/modals/doc_form.html',
                    {'internal_document': internal_document, 'errors': errors, 'values': values},
                )
            return render(request, 'docs/edit_internal_document.html', {'internal_document': internal_document, 'errors': errors})

        internal_document.company_name = company_name
        internal_document.document_name = document_name
        internal_document.description = description
        if attached_document:
            internal_document.attached_documents = attached_document
        internal_document.save()

        if _is_htmx(request) and _hx_target(request) == 'modal-body':
            return _hx_trigger_response({'closeModal': True, 'docsChanged': True})
        return redirect('internal_document_list')

    return _render_htmx(
        request,
        'docs/edit_internal_document.html',
        'partials/docs/edit_internal_document.html',
        {'internal_document': internal_document, 'title': 'Edit Document'},
    )

@login_required
def search_internal_document(request):
    # Backwards-compatible endpoint: delegate to list view filtering.
    return internal_document_list(request)

@login_required
def preview_internal_document(request, document_id):
    internal_document = InternalDocument.objects.get(id=document_id)
    file_path = internal_document.attached_documents.name  # Get the file path of the attached document
    file_name = internal_document.attached_documents.name.split('/')[-1]  # Extract the file name
    
    # Check if the file is a PDF
    if file_path.endswith('.pdf'):
        # Serve the PDF file for preview
        with open(os.path.join(settings.MEDIA_ROOT, file_path), 'rb') as pdf_file:
            response = HttpResponse(pdf_file.read(), content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="{file_name}"'
            return response
    else:
        return HttpResponse("Document Preview is not available for this file type.")

@login_required
def download_internal_document(request, document_id):
    internal_documents = get_object_or_404(InternalDocument, id=document_id)
    
    # Logic to download the internal document file
    file_path = internal_documents.attached_documents.path
    
    with open(file_path, 'rb') as file:
        response = HttpResponse(file.read(), content_type='application/octet-stream')
        response['Content-Disposition'] = 'attachment; filename="{}"'.format(internal_documents.attached_documents.name)
        return response

@login_required
def delete_internal_document(request, internal_document_id):
    internal_document = InternalDocument.objects.get(id=internal_document_id)
    internal_document.delete()
    return redirect('internal_document_list')


# Agreement Views
@login_required
def agreement_list(request):
    agreements = Agreement.objects.select_related('importer').all()
    query = request.GET.get('q')
    if query:
        agreements = agreements.filter(Q(importer__name__icontains=query) | Q(company_name__icontains=query))

    per_page = _get_per_page(request)
    paginator = Paginator(agreements.order_by('-created_on'), per_page)
    page_obj = paginator.get_page(request.GET.get('page'))
    context = {
        'agreements': page_obj,
        'page_obj': page_obj,
        'query': query,
        'per_page': per_page,
        'title': 'Agreements',
        'base_url': reverse('agreement_list'),
        'target_id': 'agreement-table',
    }
    if _is_htmx(request) and _hx_target(request) == 'agreement-table':
        return render(request, 'partials/agreements/_table.html', context)
    return _render_htmx(request, 'agreements/agreement_list.html', 'partials/agreements/agreement_list.html', context)


@login_required
def add_agreement(request):
    importers = Importer.objects.all()

    if _is_htmx(request) and request.method == 'GET' and _hx_target(request) == 'modal-body':
        return render(
            request,
            'partials/modals/agreement_form.html',
            {'agreement': None, 'importers': importers, 'values': {}},
        )

    if request.method == 'POST':
        importer_id = _clean(request.POST.get('importer'))
        company_name = _clean(request.POST.get('company_name'))
        attached_document = request.FILES.get('documents')

        errors = []
        if not importer_id:
            errors.append('Importer is required.')
        if not company_name:
            errors.append('Company name is required.')
        if not attached_document:
            errors.append('A document attachment is required.')

        values = {'importer': importer_id, 'company_name': company_name}
        if errors:
            if _is_htmx(request) and _hx_target(request) == 'modal-body':
                return render(
                    request,
                    'partials/modals/agreement_form.html',
                    {'agreement': None, 'importers': importers, 'errors': errors, 'values': values},
                )
            return render(request, 'agreements/add_agreement.html', {'importers': importers, 'errors': errors})

        try:
            importer_instance = Importer.objects.get(id=importer_id)
        except Importer.DoesNotExist:
            errors = ['Selected importer does not exist.']
            if _is_htmx(request) and _hx_target(request) == 'modal-body':
                return render(
                    request,
                    'partials/modals/agreement_form.html',
                    {'agreement': None, 'importers': importers, 'errors': errors, 'values': values},
                )
            return render(request, 'agreements/add_agreement.html', {'importers': importers, 'errors': errors})

        Agreement.objects.create(importer=importer_instance, company_name=company_name, attached_documents=attached_document)

        if _is_htmx(request) and _hx_target(request) == 'modal-body':
            return _hx_trigger_response({'closeModal': True, 'agreementsChanged': True})
        return redirect('agreement_list')

    return _render_htmx(
        request,
        'agreements/add_agreement.html',
        'partials/agreements/add_agreement.html',
        {'importers': importers, 'title': 'Add Agreement'},
    )


@login_required
def edit_agreement(request, agreement_id):
    importers = Importer.objects.all()
    agreement = Agreement.objects.get(id=agreement_id)

    if _is_htmx(request) and request.method == 'GET' and _hx_target(request) == 'modal-body':
        values = {'importer': str(agreement.importer_id), 'company_name': agreement.company_name}
        return render(
            request,
            'partials/modals/agreement_form.html',
            {'agreement': agreement, 'importers': importers, 'values': values},
        )

    if request.method == 'POST':
        importer_id = _clean(request.POST.get('importer'))
        company_name = _clean(request.POST.get('company_name'))
        attached_document = request.FILES.get('documents')

        errors = []
        if not importer_id:
            errors.append('Importer is required.')
        if not company_name:
            errors.append('Company name is required.')

        values = {'importer': importer_id, 'company_name': company_name}
        if errors:
            if _is_htmx(request) and _hx_target(request) == 'modal-body':
                return render(
                    request,
                    'partials/modals/agreement_form.html',
                    {'agreement': agreement, 'importers': importers, 'errors': errors, 'values': values},
                )
            return render(request, 'agreements/edit_agreement.html', {'agreement': agreement, 'importers': importers, 'errors': errors})

        try:
            agreement.importer = Importer.objects.get(id=importer_id)
        except Importer.DoesNotExist:
            errors = ['Selected importer does not exist.']
            if _is_htmx(request) and _hx_target(request) == 'modal-body':
                return render(
                    request,
                    'partials/modals/agreement_form.html',
                    {'agreement': agreement, 'importers': importers, 'errors': errors, 'values': values},
                )
            return render(request, 'agreements/edit_agreement.html', {'agreement': agreement, 'importers': importers, 'errors': errors})

        agreement.company_name = company_name
        if attached_document:
            agreement.attached_documents = attached_document
        agreement.save()

        if _is_htmx(request) and _hx_target(request) == 'modal-body':
            return _hx_trigger_response({'closeModal': True, 'agreementsChanged': True})
        return redirect('agreement_list')

    return _render_htmx(
        request,
        'agreements/edit_agreement.html',
        'partials/agreements/edit_agreement.html',
        {'agreement': agreement, 'importers': importers, 'title': 'Edit Agreement'},
    )


@login_required
def preview_agreement(request, document_id):
    agreement = Agreement.objects.get(id=document_id)
    file_path = agreement.attached_documents.name
    file_name = agreement.attached_documents.name.split('/')[-1]
    if file_path.endswith('.pdf'):
        with open(os.path.join(settings.MEDIA_ROOT, file_path), 'rb') as pdf_file:
            response = HttpResponse(pdf_file.read(), content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="{file_name}"'
            return response
    return HttpResponse('Document Preview is not available for this file type.')


@login_required
def download_agreement(request, document_id):
    agreement = get_object_or_404(Agreement, id=document_id)
    file_path = agreement.attached_documents.path
    content_type = mimetypes.guess_type(file_path)[0]
    response = FileResponse(open(file_path, 'rb'), content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{os.path.basename(file_path)}"'
    return response


@login_required
def delete_agreement(request, agreement_id):
    agreement = Agreement.objects.get(id=agreement_id)
    agreement.delete()
    return redirect('agreement_list')

@login_required
def home(request):
    # Lightweight analytics for the dashboard
    metrics = {
        'bills': BillOfEntry.objects.count(),
        'agreements': Agreement.objects.count(),
        'documents': InternalDocument.objects.count(),
        'shipments_total': TruckShipment.objects.count(),
        'shipments_completed': TruckShipment.objects.filter(status=TruckShipment.Status.COMPLETED).count(),
        # Manager-only metrics (filled in below)
        'importers': None,
        'users': None,
    }

    if _is_manager(request.user):
        metrics['importers'] = Importer.objects.count()
        metrics['users'] = AuthUser.objects.count()

    shipment_stage_counts = {
        TruckShipment.Status.NOT_REGISTERED: TruckShipment.objects.filter(status=TruckShipment.Status.NOT_REGISTERED).count(),
        TruckShipment.Status.REGISTERED: TruckShipment.objects.filter(status=TruckShipment.Status.REGISTERED).count(),
        TruckShipment.Status.ASSESSED: TruckShipment.objects.filter(status=TruckShipment.Status.ASSESSED).count(),
        TruckShipment.Status.PAID: TruckShipment.objects.filter(status=TruckShipment.Status.PAID).count(),
        TruckShipment.Status.RECEIPTED: TruckShipment.objects.filter(status=TruckShipment.Status.RECEIPTED).count(),
        TruckShipment.Status.RELEASE: TruckShipment.objects.filter(status=TruckShipment.Status.RELEASE).count(),
        TruckShipment.Status.COMPLETED: TruckShipment.objects.filter(status=TruckShipment.Status.COMPLETED).count(),
    }

    context = {
        'title': 'Dashboard',
        'metrics': metrics,
        'shipment_stage_counts': shipment_stage_counts,
    }
    return _render_htmx(request, 'home.html', 'partials/home.html', context)

@login_required
def my_account(request):
    user = request.user  # Get the current logged-in user
    context = {'user': user, 'title': 'My Account'}
    return _render_htmx(request, 'users/my_account.html', 'partials/users/my_account.html', context)

@login_required
def edit_user_details(request):
    user = request.user  # Django auth user
    if request.method == 'POST':
        user.first_name = request.POST.get('first_name')
        user.last_name = request.POST.get('last_name')
        user.email = request.POST.get('email')
        password = _clean(request.POST.get('password'))
        if password:
            user.set_password(password)
        user.save()
        return redirect('my_account')
    return render(request, 'users/edit_user.html', {'user': user})

@login_required
def user_logout(request):
    logout(request)
    if _is_htmx(request):
        response = HttpResponse('', status=204)
        response['HX-Redirect'] = reverse('user_login')
        return response
    return redirect('user_login')


# -----------------------------------------------------------------------------
# Truck / Shipment workflow
# -----------------------------------------------------------------------------

SHIPMENT_STATUS_ORDER = [
    TruckShipment.Status.NOT_REGISTERED,
    TruckShipment.Status.REGISTERED,
    TruckShipment.Status.ASSESSED,
    TruckShipment.Status.PAID,
    TruckShipment.Status.RECEIPTED,
    TruckShipment.Status.RELEASE,
    TruckShipment.Status.COMPLETED,
]


def _parse_date(value: str) -> Optional[date]:
    value = _clean(value)
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def _parse_decimal(value: str) -> Optional[Decimal]:
    value = _clean(value)
    if not value:
        return None
    try:
        return Decimal(value)
    except Exception:
        return None


def _shipment_next_status(current: str) -> Optional[str]:
    try:
        idx = SHIPMENT_STATUS_ORDER.index(current)
    except ValueError:
        return None
    return SHIPMENT_STATUS_ORDER[idx + 1] if idx < len(SHIPMENT_STATUS_ORDER) - 1 else None


def _shipment_transition_errors(shipment: TruckShipment, to_status: str) -> list[str]:
    errors: list[str] = []
    expected_next = _shipment_next_status(shipment.status)
    if not expected_next:
        errors.append('This shipment is already completed.')
        return errors
    if to_status != expected_next:
        errors.append('Invalid status transition.')
        return errors

    if shipment.status == TruckShipment.Status.NOT_REGISTERED:
        if not shipment.manifest_file:
            errors.append('Manifest upload is required to register this shipment.')
        if not shipment.invoice_file:
            errors.append('Invoice upload is required to register this shipment.')
    elif shipment.status == TruckShipment.Status.REGISTERED:
        if not _clean(shipment.cill_number):
            errors.append('Cill Number is required.')
        if not _clean(shipment.bill_of_entry_number):
            errors.append('Bill of Entry Number is required.')
        if not shipment.date_registered:
            errors.append('Date Registered is required.')
    elif shipment.status == TruckShipment.Status.ASSESSED:
        if not _clean(shipment.assessment_number):
            errors.append('Assessment Number is required.')
        if not shipment.date_assessed:
            errors.append('Date Assessed is required.')
    elif shipment.status == TruckShipment.Status.PAID:
        if not shipment.proof_of_payment_file:
            errors.append('Proof of Payment upload is required.')
    elif shipment.status == TruckShipment.Status.RECEIPTED:
        if not _clean(shipment.receipt_number):
            errors.append('Receipt Number is required.')
    elif shipment.status == TruckShipment.Status.RELEASE:
        if not shipment.date_exited:
            errors.append('Date Exited is required.')

    return errors


def _shipment_apply_filters(request, qs):
    q = _clean(request.GET.get('q'))
    truck_registration = _clean(request.GET.get('truck_registration'))
    manifest_number = _clean(request.GET.get('manifest_number'))
    cill_number = _clean(request.GET.get('cill_number'))
    bill_of_entry_number = _clean(request.GET.get('bill_of_entry_number'))
    assessment_number = _clean(request.GET.get('assessment_number'))
    receipt_number = _clean(request.GET.get('receipt_number'))
    weight_min = _parse_decimal(request.GET.get('weight_min'))
    weight_max = _parse_decimal(request.GET.get('weight_max'))
    upload_status = _clean(request.GET.get('upload_status'))
    date_from = _parse_date(request.GET.get('date_from'))
    date_to = _parse_date(request.GET.get('date_to'))

    if q:
        qs = qs.filter(
            Q(truck_registration__icontains=q)
            | Q(manifest_number__icontains=q)
            | Q(cill_number__icontains=q)
            | Q(bill_of_entry_number__icontains=q)
            | Q(assessment_number__icontains=q)
            | Q(receipt_number__icontains=q)
        )
    if truck_registration:
        qs = qs.filter(truck_registration__icontains=truck_registration)
    if manifest_number:
        qs = qs.filter(manifest_number__icontains=manifest_number)
    if cill_number:
        qs = qs.filter(cill_number__icontains=cill_number)
    if bill_of_entry_number:
        qs = qs.filter(bill_of_entry_number__icontains=bill_of_entry_number)
    if assessment_number:
        qs = qs.filter(assessment_number__icontains=assessment_number)
    if receipt_number:
        qs = qs.filter(receipt_number__icontains=receipt_number)
    if weight_min is not None:
        qs = qs.filter(weight_kg__gte=weight_min)
    if weight_max is not None:
        qs = qs.filter(weight_kg__lte=weight_max)

    if upload_status == 'required_complete':
        qs = qs.filter(manifest_file__isnull=False, invoice_file__isnull=False)
    elif upload_status == 'missing_required':
        qs = qs.filter(Q(manifest_file__isnull=True) | Q(invoice_file__isnull=True))
    elif upload_status == 'any_missing':
        qs = qs.filter(
            Q(manifest_file__isnull=True)
            | Q(waybill_file__isnull=True)
            | Q(invoice_file__isnull=True)
            | Q(comesa_sadc_file__isnull=True)
        )

    if date_from:
        qs = qs.filter(created_on__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_on__date__lte=date_to)

    filters = {
        'q': q,
        'truck_registration': truck_registration,
        'manifest_number': manifest_number,
        'cill_number': cill_number,
        'bill_of_entry_number': bill_of_entry_number,
        'assessment_number': assessment_number,
        'receipt_number': receipt_number,
        'weight_min': request.GET.get('weight_min') or '',
        'weight_max': request.GET.get('weight_max') or '',
        'upload_status': upload_status,
        'date_from': request.GET.get('date_from') or '',
        'date_to': request.GET.get('date_to') or '',
    }
    return qs, filters


def _shipment_extra_query(request) -> str:
    params = request.GET.copy()
    params.pop('page', None)
    return params.urlencode()


@login_required
def shipment_not_registered_list(request):
    return _shipment_stage_list(
        request,
        TruckShipment.Status.NOT_REGISTERED,
        'Not Yet Registered',
        'Waiting for documentation.',
        'fas fa-truck',
    )


@login_required
def shipment_registered_list(request):
    return _shipment_stage_list(
        request,
        TruckShipment.Status.REGISTERED,
        'Registered',
        'Waiting assessment stage.',
        'fas fa-clipboard-check',
    )


@login_required
def shipment_assessed_list(request):
    return _shipment_stage_list(
        request,
        TruckShipment.Status.ASSESSED,
        'Assessed',
        'Waiting payment.',
        'fas fa-scale-balanced',
    )


@login_required
def shipment_paid_list(request):
    return _shipment_stage_list(
        request,
        TruckShipment.Status.PAID,
        'Paid',
        'Waiting proof of payment.',
        'fas fa-money-bill-wave',
    )


@login_required
def shipment_receipted_list(request):
    return _shipment_stage_list(
        request,
        TruckShipment.Status.RECEIPTED,
        'Receipted',
        'Waiting cross.',
        'fas fa-receipt',
    )


@login_required
def shipment_release_list(request):
    return _shipment_stage_list(
        request,
        TruckShipment.Status.RELEASE,
        'Release',
        'Record exit details.',
        'fas fa-door-open',
    )


@login_required
def shipment_completed_list(request):
    return _shipment_stage_list(
        request,
        TruckShipment.Status.COMPLETED,
        'Completed',
        'Fully processed shipments.',
        'fas fa-circle-check',
    )


def _shipment_stage_list(request, status: str, title: str, subtitle: str, icon: str):
    qs = TruckShipment.objects.filter(status=status).order_by('-created_on')
    qs, filters = _shipment_apply_filters(request, qs)

    per_page = _get_per_page(request)
    paginator = Paginator(qs, per_page)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'shipments': page_obj,
        'page_obj': page_obj,
        'per_page': per_page,
        'title': title,
        'subtitle': subtitle,
        'icon': icon,
        'status_code': status,
        'filters': filters,
        'base_url': request.path,
        'target_id': 'shipment-cards',
        'extra_query': _shipment_extra_query(request),
        'can_add': status == TruckShipment.Status.NOT_REGISTERED,
        'can_export_documents': status == TruckShipment.Status.COMPLETED,
    }

    if _is_htmx(request) and _hx_target(request) == 'shipment-cards':
        return render(request, 'partials/shipments/_cards.html', context)

    return _render_htmx(
        request,
        'shipments/shipment_list.html',
        'partials/shipments/shipment_list.html',
        context,
    )


@login_required
def add_shipment(request):
    if _is_htmx(request) and request.method == 'GET' and _hx_target(request) == 'modal-body':
        return render(request, 'partials/modals/shipment_create_form.html', {'values': {}})

    if request.method == 'POST':
        truck_registration = _clean(request.POST.get('truck_registration'))
        manifest_number = _clean(request.POST.get('manifest_number'))
        weight_raw = _clean(request.POST.get('weight_kg'))
        weight_kg = _parse_decimal(weight_raw)

        manifest_file = request.FILES.get('manifest_file')
        waybill_file = request.FILES.get('waybill_file')
        invoice_file = request.FILES.get('invoice_file')
        comesa_sadc_file = request.FILES.get('comesa_sadc_file')

        errors = []
        if not truck_registration:
            errors.append('Truck Registration is required.')
        if not manifest_number:
            errors.append('Manifest Number is required.')
        if weight_kg is None:
            errors.append('Weight (kg) must be a valid number.')

        values = {
            'truck_registration': truck_registration,
            'manifest_number': manifest_number,
            'weight_kg': weight_raw,
        }

        if errors:
            if _is_htmx(request) and _hx_target(request) == 'modal-body':
                return render(
                    request,
                    'partials/modals/shipment_create_form.html',
                    {'errors': errors, 'values': values},
                    status=400,
                )
            return render(request, 'shipments/shipment_list.html', {'errors': errors})

        shipment = TruckShipment.objects.create(
            truck_registration=truck_registration,
            manifest_number=manifest_number,
            weight_kg=weight_kg,
            manifest_file=manifest_file,
            waybill_file=waybill_file,
            invoice_file=invoice_file,
            comesa_sadc_file=comesa_sadc_file,
            status=TruckShipment.Status.NOT_REGISTERED,
        )

        if _is_htmx(request) and _hx_target(request) == 'modal-body':
            return _hx_trigger_response({'closeModal': True, 'shipmentsChanged': True})
        return redirect('shipment_not_registered_list')

    return HttpResponse('Method Not Allowed', status=405)


@login_required
def edit_shipment(request, shipment_id: int):
    shipment = get_object_or_404(TruckShipment, id=shipment_id)

    if _is_htmx(request) and request.method == 'GET' and _hx_target(request) == 'modal-body':
        return render(
            request,
            'partials/modals/shipment_edit_form.html',
            {
                'shipment': shipment,
                'next_status': _shipment_next_status(shipment.status),
                'transition_errors': _shipment_transition_errors(shipment, _shipment_next_status(shipment.status) or ''),
            },
        )

    if request.method == 'POST':
        errors: list[str] = []

        if shipment.status == TruckShipment.Status.NOT_REGISTERED:
            truck_registration = _clean(request.POST.get('truck_registration'))
            manifest_number = _clean(request.POST.get('manifest_number'))
            weight_raw = _clean(request.POST.get('weight_kg'))
            weight_kg = _parse_decimal(weight_raw)

            if not truck_registration:
                errors.append('Truck Registration is required.')
            if not manifest_number:
                errors.append('Manifest Number is required.')
            if weight_kg is None:
                errors.append('Weight (kg) must be a valid number.')

            if not errors:
                shipment.truck_registration = truck_registration
                shipment.manifest_number = manifest_number
                shipment.weight_kg = weight_kg

            # Allow updating uploads at stage 1
            manifest_file = request.FILES.get('manifest_file')
            waybill_file = request.FILES.get('waybill_file')
            invoice_file = request.FILES.get('invoice_file')
            comesa_sadc_file = request.FILES.get('comesa_sadc_file')
            if manifest_file:
                shipment.manifest_file = manifest_file
            if waybill_file:
                shipment.waybill_file = waybill_file
            if invoice_file:
                shipment.invoice_file = invoice_file
            if comesa_sadc_file:
                shipment.comesa_sadc_file = comesa_sadc_file

        elif shipment.status == TruckShipment.Status.REGISTERED:
            shipment.cill_number = _clean(request.POST.get('cill_number'))
            shipment.bill_of_entry_number = _clean(request.POST.get('bill_of_entry_number'))
            shipment.date_registered = _parse_date(request.POST.get('date_registered'))

        elif shipment.status == TruckShipment.Status.ASSESSED:
            shipment.assessment_number = _clean(request.POST.get('assessment_number'))
            shipment.date_assessed = _parse_date(request.POST.get('date_assessed'))

        elif shipment.status == TruckShipment.Status.PAID:
            proof_file = request.FILES.get('proof_of_payment_file')
            if proof_file:
                shipment.proof_of_payment_file = proof_file

        elif shipment.status == TruckShipment.Status.RECEIPTED:
            shipment.receipt_number = _clean(request.POST.get('receipt_number'))

        elif shipment.status == TruckShipment.Status.RELEASE:
            raw = _clean(request.POST.get('date_exited'))
            if raw:
                try:
                    shipment.date_exited = datetime.strptime(raw, '%Y-%m-%dT%H:%M')
                except ValueError:
                    errors.append('Date Exited must be a valid date/time.')
            else:
                shipment.date_exited = None

        if errors:
            if _is_htmx(request) and _hx_target(request) == 'modal-body':
                return render(
                    request,
                    'partials/modals/shipment_edit_form.html',
                    {
                        'shipment': shipment,
                        'errors': errors,
                        'next_status': _shipment_next_status(shipment.status),
                        'transition_errors': _shipment_transition_errors(shipment, _shipment_next_status(shipment.status) or ''),
                    },
                    status=400,
                )
            return HttpResponse('Bad Request', status=400)

        shipment.save()

        if _is_htmx(request) and _hx_target(request) == 'modal-body':
            return _hx_trigger_response({'closeModal': True, 'shipmentsChanged': True})
        return redirect(request.META.get('HTTP_REFERER', reverse('shipment_not_registered_list')))

    return HttpResponse('Method Not Allowed', status=405)


@login_required
def shipment_uploads(request, shipment_id: int):
    shipment = get_object_or_404(TruckShipment, id=shipment_id)

    if _is_htmx(request) and request.method == 'GET' and _hx_target(request) == 'modal-body':
        return render(request, 'partials/modals/shipment_uploads_form.html', {'shipment': shipment})

    if request.method == 'POST':
        manifest_file = request.FILES.get('manifest_file')
        waybill_file = request.FILES.get('waybill_file')
        invoice_file = request.FILES.get('invoice_file')
        comesa_sadc_file = request.FILES.get('comesa_sadc_file')

        if manifest_file:
            shipment.manifest_file = manifest_file
        if waybill_file:
            shipment.waybill_file = waybill_file
        if invoice_file:
            shipment.invoice_file = invoice_file
        if comesa_sadc_file:
            shipment.comesa_sadc_file = comesa_sadc_file
        shipment.save()

        if _is_htmx(request) and _hx_target(request) == 'modal-body':
            return _hx_trigger_response({'closeModal': True, 'shipmentsChanged': True})
        return redirect(request.META.get('HTTP_REFERER', reverse('shipment_not_registered_list')))

    return HttpResponse('Method Not Allowed', status=405)


@login_required
def shipment_details(request, shipment_id: int):
    shipment = get_object_or_404(TruckShipment.objects.prefetch_related('status_events'), id=shipment_id)
    events = list(shipment.status_events.all())
    if _is_htmx(request) and request.method == 'GET' and _hx_target(request) == 'modal-body':
        return render(request, 'partials/modals/shipment_details.html', {'shipment': shipment, 'events': events})
    return HttpResponse('Bad Request', status=400)


@login_required
def shipment_transition(request, shipment_id: int):
    shipment = get_object_or_404(TruckShipment, id=shipment_id)
    if request.method != 'POST':
        return HttpResponse('Method Not Allowed', status=405)

    to_status = _clean(request.POST.get('to_status'))
    errors = _shipment_transition_errors(shipment, to_status)
    if errors:
        if _is_htmx(request) and _hx_target(request) == 'modal-body':
            return render(
                request,
                'partials/modals/shipment_edit_form.html',
                {
                    'shipment': shipment,
                    'errors': errors,
                    'next_status': _shipment_next_status(shipment.status),
                    'transition_errors': errors,
                },
                status=400,
            )
        return HttpResponse('Bad Request', status=400)

    from_status = shipment.status
    shipment.status = to_status
    shipment.save()
    ShipmentStatusEvent.objects.create(
        shipment=shipment,
        from_status=from_status,
        to_status=to_status,
        changed_by=request.user if request.user.is_authenticated else None,
    )

    if _is_htmx(request) and _hx_target(request) == 'modal-body':
        return _hx_trigger_response({'closeModal': True, 'shipmentsChanged': True})
    return redirect(request.META.get('HTTP_REFERER', reverse('shipment_not_registered_list')))


SHIPMENT_FILE_FIELDS = {
    'manifest_file': 'Manifest',
    'waybill_file': 'Waybill',
    'invoice_file': 'Invoice',
    'comesa_sadc_file': 'COMESA_SADC',
    'proof_of_payment_file': 'Proof_of_Payment',
}


def _get_shipment_file(shipment: TruckShipment, field: str):
    if field not in SHIPMENT_FILE_FIELDS:
        return None
    return getattr(shipment, field)


@login_required
def shipment_file_preview(request, shipment_id: int, field: str):
    shipment = get_object_or_404(TruckShipment, id=shipment_id)
    f = _get_shipment_file(shipment, field)
    if not f:
        return HttpResponse('Not Found', status=404)
    path = f.path
    content_type = mimetypes.guess_type(path)[0] or 'application/octet-stream'
    response = FileResponse(open(path, 'rb'), content_type=content_type)
    response['Content-Disposition'] = f'inline; filename="{os.path.basename(path)}"'
    return response


@login_required
def shipment_file_download(request, shipment_id: int, field: str):
    shipment = get_object_or_404(TruckShipment, id=shipment_id)
    f = _get_shipment_file(shipment, field)
    if not f:
        return HttpResponse('Not Found', status=404)
    path = f.path
    content_type = mimetypes.guess_type(path)[0] or 'application/octet-stream'
    response = FileResponse(open(path, 'rb'), content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{os.path.basename(path)}"'
    return response


def _shipment_export_queryset(request):
    status = _clean(request.GET.get('status'))
    qs = TruckShipment.objects.all().order_by('-created_on')
    if status in {s for s, _ in TruckShipment.Status.choices}:
        qs = qs.filter(status=status)
    qs, _ = _shipment_apply_filters(request, qs)
    return qs


def _shipment_upload_indicator(file_field) -> str:
    return 'Uploaded' if file_field else 'Not Uploaded'


@login_required
def shipments_export_excel(request):
    qs = _shipment_export_queryset(request)

    wb = Workbook()
    ws = wb.active
    ws.title = 'Shipments'

    headers = [
        'Status',
        'Truck Registration',
        'Manifest Number',
        'Weight (kg)',
        'Cill Number',
        'Bill of Entry Number',
        'Date Registered',
        'Assessment Number',
        'Date Assessed',
        'Receipt Number',
        'Date Exited',
        'Created At',
        'Updated At',
        'Manifest',
        'Waybill',
        'Invoice',
        'COMESA / SADC',
        'Proof of Payment',
    ]
    ws.append(headers)

    for s in qs:
        ws.append(
            [
                s.get_status_display(),
                s.truck_registration,
                s.manifest_number,
                float(s.weight_kg) if s.weight_kg is not None else '',
                s.cill_number,
                s.bill_of_entry_number,
                s.date_registered.isoformat() if s.date_registered else '',
                s.assessment_number,
                s.date_assessed.isoformat() if s.date_assessed else '',
                s.receipt_number,
                s.date_exited.isoformat(sep=' ') if s.date_exited else '',
                s.created_on.isoformat(sep=' '),
                s.updated_on.isoformat(sep=' '),
                _shipment_upload_indicator(s.manifest_file),
                _shipment_upload_indicator(s.waybill_file),
                _shipment_upload_indicator(s.invoice_file),
                _shipment_upload_indicator(s.comesa_sadc_file),
                _shipment_upload_indicator(s.proof_of_payment_file),
            ]
        )

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    filename = 'shipments_export.xlsx'
    response = HttpResponse(
        out.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def _safe_folder_name(value: str) -> str:
    value = (value or '').strip() or 'Unknown_Truck'
    keep = []
    for ch in value:
        if ch.isalnum() or ch in {'-', '_'}:
            keep.append(ch)
        elif ch in {' ', '/'}:
            keep.append('_')
    return ''.join(keep)[:80]


@login_required
def shipments_export_documents_zip(request):
    qs = _shipment_export_queryset(request)
    qs = qs.filter(status=TruckShipment.Status.COMPLETED)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for s in qs:
            folder = _safe_folder_name(s.truck_registration)
            for field, label in SHIPMENT_FILE_FIELDS.items():
                f = getattr(s, field)
                if not f:
                    continue
                src_path = f.path
                ext = os.path.splitext(src_path)[1] or ''
                arcname = f'{folder}/{label}{ext}'
                try:
                    zf.write(src_path, arcname=arcname)
                except FileNotFoundError:
                    continue

    buf.seek(0)
    response = HttpResponse(buf.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = 'attachment; filename="completed_shipments_documents.zip"'
    return response