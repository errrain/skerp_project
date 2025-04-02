
from django import forms
from .models import Equipment, EquipmentHistory
from django.forms.widgets import DateInput

class EquipmentForm(forms.ModelForm):
    class Meta:
        model = Equipment
        fields = ['name', 'spec', 'purchase_date', 'vendor', 'description', 'image']
        labels = {
            'name': '설비명',
            'spec': '설비규격',
            'purchase_date': '구입일자',
            'vendor': '구입처',
            'description': '설비설명',
            'image': '설비사진',
        }
        widgets = {
            'purchase_date': DateInput(attrs={'type': 'date', 'class': 'form-control form-control-sm'}),
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control form-control-sm'}),
        }

class EquipmentHistoryForm(forms.ModelForm):
    class Meta:
        model = EquipmentHistory
        fields = ['content']
        labels = {
            'content': '이력내용',
        }
        widgets = {
            'content': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
        }
