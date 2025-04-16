from django import forms
from .models import Injection, InjectionPrice, MoldHistory


class InjectionForm(forms.ModelForm):
    class Meta:
        model = Injection
        fields = '__all__'
        labels = {
            'name': '품명',
            'program_name': '프로그램명',
            'status': '상태',
            'alias': '별칭',
            'part_number': 'Part Number',
            'sub_part_number': 'Sub Part Number',
            'part_size': 'Part Size',
            'material': '소재',
            'ton': '사출기 톤수',
            'cycle_time': 'CYCLETIME',
            'weight': 'Weight (g)',
            'vendor': '사출사',
            'image': '제품 이미지',
            'use_yn': '사용여부',
            'delete_yn': '삭제여부',
            'created_by': '생성자',
            'updated_by': '수정자',
            'created_dt': '생성일시',
            'updated_dt': '수정일시',
        }

class InjectionForm(forms.ModelForm):
    class Meta:
        model = Injection
        fields = '__all__'
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'material': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'vendor': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'use_yn': forms.Select(attrs={'class': 'form-select form-select-sm'}),
        }

class InjectionPriceForm(forms.ModelForm):
    class Meta:
        model = InjectionPrice
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

class MoldHistoryForm(forms.ModelForm):
    class Meta:
        model = MoldHistory
        fields = ['history_date', 'content']
        labels = {
            'history_date': '이력일자',
            'content': '내용',
        }
        widgets = {
            'history_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control form-control-sm'
            }),
            'content': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'placeholder': '금형 관련 내용을 입력하세요'
            }),
        }