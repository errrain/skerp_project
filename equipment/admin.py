# equipment/admin.py

from django.contrib import admin
from .models import Equipment, EquipmentHistory

class EquipmentHistoryInline(admin.TabularInline):
    model = EquipmentHistory
    extra = 1  # 빈 이력 입력 행 개수
    fields = ['content', 'created_by', 'created_at']
    readonly_fields = ['created_at']
    verbose_name = "설비 이력"
    verbose_name_plural = "설비 이력 목록"

@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ['id', 'equipment_code', 'name', 'spec', 'purchase_date', 'vendor']
    list_filter = ['vendor', 'purchase_date']
    search_fields = ['name', 'spec', 'equipment_code']
    readonly_fields = ['equipment_code']
    inlines = [EquipmentHistoryInline]  # ✅ 이력 inline 추가
