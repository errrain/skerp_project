# master/forms.py
from django import forms
from .models import CompanyInfo, Warehouse


class CompanyInfoForm(forms.ModelForm):
    class Meta:
        model = CompanyInfo
        fields = '__all__'

class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        exclude = ['warehouse_id']
        labels = {
            'name': '창고명',
            'description': '창고 설명',
            'is_active': '사용 여부',
            'is_deleted': '삭제 여부',
        }