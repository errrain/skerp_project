# spec/admin.py
from django.contrib import admin
from .models import Spec

@admin.register(Spec)
class SpecAdmin(admin.ModelAdmin):
    list_display = ['name', 'created_at']
    search_fields = ['name', 'description']