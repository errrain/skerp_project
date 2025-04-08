from django import forms
from .models import Submaterial, SubmaterialPrice

class SubmaterialForm(forms.ModelForm):
    delete_yn = forms.ChoiceField(
        choices=[('Y', '삭제'), ('N', '정상')],
        widget=forms.Select(attrs={'class': 'form-select form-select-sm', 'style': 'width:150px'}),
        required=False,
    )

    use_yn = forms.ChoiceField(
        choices=[('Y', '사용'), ('N', '미사용')],
        widget=forms.Select(attrs={'class': 'form-select form-select-sm', 'style': 'width:150px'}),
        required=False,
    )

    class Meta:
        model = Submaterial
        fields = ['name', 'spec', 'customer', 'image', 'use_yn', 'delete_yn']
        labels = {
            'name': '품명',
            'spec': '규격',
            'customer': '고객사',
            'image': '제품 이미지',
            'use_yn': '사용여부',
            'delete_yn': '삭제여부',
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'spec': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'customer': forms.Select(attrs={'class': 'form-select form-select-sm', 'style': 'width:150px'}),
            'image': forms.ClearableFileInput(attrs={'class': 'form-control form-control-sm'}),
        }

class SubmaterialPriceForm(forms.ModelForm):
    class Meta:
        model = SubmaterialPrice
        fields = ['date', 'price']
        labels = {
            'date': '일자',
            'price': '단가',
        }
        widgets = {
            'date': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control form-control-sm'}),
            'price': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'placeholder': '숫자만 입력'}),
        }