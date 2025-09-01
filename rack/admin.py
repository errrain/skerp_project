from django.contrib import admin

# Register your models here.
from django.contrib import admin
from .models import RackMaster

@admin.register(RackMaster)
class RackMasterAdmin(admin.ModelAdmin):
    list_display = ('rack_master_id', 'product_nm', 'product_no', 'make_comp', 'use_yn', 'dlt_yn')
    search_fields = ('rack_master_id', 'product_nm', 'product_no')
