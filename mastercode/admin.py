# mastercode/admin.py

from django.contrib import admin
from .models import CodeGroup, CodeDetail


@admin.register(CodeGroup)
class CodeGroupAdmin(admin.ModelAdmin):
    list_display = ('group_code', 'group_name')
    search_fields = ('group_code', 'group_name')


@admin.register(CodeDetail)
class CodeDetailAdmin(admin.ModelAdmin):
    list_display = ('group', 'code', 'name', 'sort_order', 'is_active')
    list_filter = ('group', 'is_active')
    search_fields = ('code', 'name')
    ordering = ('group', 'sort_order')
