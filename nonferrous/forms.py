from django import forms
from .models import Chemical
from .models import ChemicalPrice

class ChemicalForm(forms.ModelForm):
    class Meta:
        model = Chemical
        fields = ['name', 'spec', 'customer', 'image', 'use_yn']
        labels = {
            'name': '품명',
            'spec': '규격',
            'customer': '고객사',
            'image': '제품 이미지',
            'use_yn': '사용 여부',
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'spec': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'customer': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'image': forms.ClearableFileInput(attrs={'class': 'form-control form-control-sm'}),
            'use_yn': forms.Select(attrs={'class': 'form-select form-select-sm'}),
        }

class ChemicalPriceForm(forms.ModelForm):
    class Meta:
        model = ChemicalPrice
        fields = ['date', 'price']
        labels = {
            'date': '일자',
            'price': '단가',
        }
        widgets = {
            'date': forms.DateTimeInput(attrs={
                'type': 'datetime-local',
                'class': 'form-control form-control-sm'
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm',
                'placeholder': '숫자만 입력'
            }),
        }
