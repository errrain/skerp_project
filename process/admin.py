
from django.contrib import admin
from .models import Process, ProcessFile

class ProcessFileInline(admin.TabularInline):
    model = ProcessFile
    extra = 0

@admin.register(Process)
class ProcessAdmin(admin.ModelAdmin):
    list_display = ['name', 'description']
    inlines = [ProcessFileInline]

@admin.register(ProcessFile)
class ProcessFileAdmin(admin.ModelAdmin):
    list_display = ['process', 'file', 'created_by', 'created_at']
    list_filter = ['created_at']
    search_fields = ['process__name', 'file']
