from django.db import models
from django.utils.timezone import now
from django.contrib.auth.models import AbstractUser
from django.conf import settings

class User(models.Model):
    ROLE_CHOICES = (
        ('Manager', 'Manager'),
        ('User', 'User'),
    )

    def save(self, *args, **kwargs):
        self.updated_on = now()
        super().save(*args, **kwargs)
    
    name = models.CharField(max_length=100)
    email = models.EmailField(
        unique=True,
        error_messages={
            'unique': 'Email already exists. Please enter another email.',
        },
    )
    password = models.CharField(max_length=100)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)

class Importer(models.Model):
    name = models.CharField(max_length=100)
    created_on = models.DateTimeField(auto_now_add=True)
    updated_on = models.DateTimeField(default=now)

    def save(self, *args, **kwargs):
        self.updated_on = now()
        super().save(*args, **kwargs)

class BillOfEntry(models.Model):
    importer = models.ForeignKey(Importer, on_delete=models.CASCADE)
    entry_number = models.CharField(
        max_length=50,
        unique=True,
        error_messages={
            'unique': 'Entry number already exists. Please enter another entry number.',
        },
    )
    invoice_reference = models.CharField(max_length=50, blank=True)
    description = models.TextField()
    attached_documents = models.FileField(upload_to='bills_of_entry/')
    created_on = models.DateTimeField(auto_now_add=True)
    updated_on = models.DateTimeField(default=now)

    def save(self, *args, **kwargs):
        self.updated_on = now()
        super().save(*args, **kwargs)

class InternalDocument(models.Model):
    company_name = models.CharField(max_length=100)
    document_name = models.CharField(max_length=100)
    description = models.TextField()
    attached_documents = models.FileField(upload_to='internal_documents/')
    created_on = models.DateTimeField(auto_now_add=True)
    updated_on = models.DateTimeField(default=now)

    def save(self, *args, **kwargs):
        self.updated_on = now()
        super().save(*args, **kwargs)


class Agreement(models.Model):
    importer = models.ForeignKey(Importer, on_delete=models.CASCADE)
    company_name = models.CharField(max_length=100)
    attached_documents = models.FileField(upload_to='agreements/')
    created_on = models.DateTimeField(auto_now_add=True)
    updated_on = models.DateTimeField(default=now)

    def save(self, *args, **kwargs):
        self.updated_on = now()
        super().save(*args, **kwargs)


class TruckShipment(models.Model):
    class Status(models.TextChoices):
        NOT_REGISTERED = 'NOT_REGISTERED', 'Not Yet Registered – Waiting for Documentation'
        REGISTERED = 'REGISTERED', 'Registered – Waiting Assessment Stage'
        ASSESSED = 'ASSESSED', 'Assessed – Waiting Payment'
        PAID = 'PAID', 'Paid – Waiting Proof of Payment'
        RECEIPTED = 'RECEIPTED', 'Receipted – Waiting Cross'
        RELEASE = 'RELEASE', 'Release'
        COMPLETED = 'COMPLETED', 'Completed'

    # Stage 1: Not Yet Registered
    truck_registration = models.CharField(max_length=50)
    manifest_number = models.CharField(max_length=100)
    weight_kg = models.DecimalField(max_digits=12, decimal_places=2)

    manifest_file = models.FileField(upload_to='shipments/manifest/', blank=True, null=True)
    waybill_file = models.FileField(upload_to='shipments/waybill/', blank=True, null=True)
    invoice_file = models.FileField(upload_to='shipments/invoice/', blank=True, null=True)
    comesa_sadc_file = models.FileField(upload_to='shipments/comesa_sadc/', blank=True, null=True)

    # Stage 2: Registered
    cill_number = models.CharField(max_length=100, blank=True)
    bill_of_entry_number = models.CharField(max_length=100, blank=True)
    date_registered = models.DateField(blank=True, null=True)

    # Stage 3: Assessed
    assessment_number = models.CharField(max_length=100, blank=True)
    date_assessed = models.DateField(blank=True, null=True)

    # Stage 4: Paid
    proof_of_payment_file = models.FileField(upload_to='shipments/proof_of_payment/', blank=True, null=True)

    # Stage 5: Receipted
    receipt_number = models.CharField(max_length=100, blank=True)

    # Stage 6: Release
    date_exited = models.DateTimeField(blank=True, null=True)

    # Workflow
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NOT_REGISTERED)

    # Audit
    created_on = models.DateTimeField(auto_now_add=True)
    updated_on = models.DateTimeField(default=now)

    def save(self, *args, **kwargs):
        self.updated_on = now()
        super().save(*args, **kwargs)

    @property
    def stage1_required_uploads_complete(self) -> bool:
        return bool(self.manifest_file and self.invoice_file)


class ShipmentStatusEvent(models.Model):
    shipment = models.ForeignKey(TruckShipment, on_delete=models.CASCADE, related_name='status_events')
    from_status = models.CharField(max_length=20, choices=TruckShipment.Status.choices)
    to_status = models.CharField(max_length=20, choices=TruckShipment.Status.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='shipment_status_events',
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-changed_at']