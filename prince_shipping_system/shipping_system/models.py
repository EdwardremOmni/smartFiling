from django.db import models
from django.utils.timezone import now
from django.contrib.auth.models import AbstractUser

class User(models.Model):
    ROLE_CHOICES = (
        ('Manager', 'Manager'),
        ('User', 'User'),
    )

    def save(self, *args, **kwargs):
        self.updated_on = now()
        super().save(*args, **kwargs)
    
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
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
    entry_number = models.CharField(max_length=50, unique=True)
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