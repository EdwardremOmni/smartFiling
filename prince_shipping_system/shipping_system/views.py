from django.shortcuts import render, redirect, get_object_or_404
from .models import User as AppUser, Importer, BillOfEntry, InternalDocument, Agreement
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

    context = {'users': users, 'query': query, 'title': 'Users'}
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
            errors.append('Email already exists.')

        if errors:
            if _is_htmx(request) and _hx_target(request) == 'modal-body':
                return render(
                    request,
                    'partials/modals/user_form.html',
                    {'user_obj': None, 'errors': errors, 'values': {'name': name, 'email': email, 'role': role}},
                    status=422,
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
            errors.append('Email already exists.')

        if errors:
            if _is_htmx(request) and _hx_target(request) == 'modal-body':
                return render(
                    request,
                    'partials/modals/user_form.html',
                    {'user_obj': user_obj, 'errors': errors, 'values': {'name': name, 'email': email, 'role': role}},
                    status=422,
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

    context = {'importers': importers, 'query': query, 'title': 'Importers'}
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
                    status=422,
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
                    status=422,
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

    context = {'bills_of_entry': bills_of_entry, 'query': query, 'title': 'Bills of Entry'}
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

        if errors:
            if _is_htmx(request) and _hx_target(request) == 'modal-body':
                return render(
                    request,
                    'partials/modals/bill_form.html',
                    {'bill_of_entry': None, 'importers': importers, 'errors': errors, 'values': values},
                    status=422,
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
            errors = ['Entry number already exists.']

        if errors:
            if _is_htmx(request) and _hx_target(request) == 'modal-body':
                return render(
                    request,
                    'partials/modals/bill_form.html',
                    {'bill_of_entry': None, 'importers': importers, 'errors': errors, 'values': values},
                    status=422,
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

        if errors:
            if _is_htmx(request) and _hx_target(request) == 'modal-body':
                return render(
                    request,
                    'partials/modals/bill_form.html',
                    {'bill_of_entry': bill_of_entry, 'importers': importers, 'errors': errors, 'values': values},
                    status=422,
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
                    {'bill_of_entry': bill_of_entry, 'importers': importers, 'errors': errors, 'values': values},
                    status=422,
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
            errors = ['Entry number already exists.']
            if _is_htmx(request) and _hx_target(request) == 'modal-body':
                return render(
                    request,
                    'partials/modals/bill_form.html',
                    {'bill_of_entry': bill_of_entry, 'importers': importers, 'errors': errors, 'values': values},
                    status=422,
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

    context = {'internal_documents': internal_documents, 'query': query, 'title': 'Documents'}
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
                    status=422,
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
                    status=422,
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

    context = {'agreements': agreements, 'query': query, 'title': 'Agreements'}
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
                    status=422,
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
                    status=422,
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
                    status=422,
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
                    status=422,
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
    context = {'title': 'Dashboard'}
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