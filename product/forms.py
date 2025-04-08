from django import forms
from .models import Product
from .models import ProductPrice

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
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
            'spec': '제조사양',
            'weight': '무게(g)',
            'customer': '고객사',
            'injection_vendor': '사출사',
            'rack_info': '렉정보',
            'finishing': 'Finishing',
            'grade': 'Grade',
            'injection_info': 'Injection',
            'plating': 'Plating',
            'assembly_packaging': 'Assembly/Packaging',
            'final_delivery': 'Final Delivery',
            'image': '제품 이미지',
            'ppap_file': 'PPAP DATA',
            'run_rate_file': 'RUN%RATE DATA',
            'transfer_file': '양산이관 DATA',
            'use_yn': '사용여부',
        }

class ProductPriceForm(forms.ModelForm):
    class Meta:
        model = ProductPrice
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