from django import forms
from .models import Product, ProductSubmaterial, ProductPrice
from django.forms import inlineformset_factory

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

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        hanger_count = cleaned_data.get('hanger_count')
        turn_time_per_hanger = cleaned_data.get('turn_time_per_hanger')
        rack_per_hanger = cleaned_data.get('rack_per_hanger')
        product_per_rack = cleaned_data.get('product_per_rack')

        # 총 생산량 계산
        if hanger_count and rack_per_hanger and product_per_rack:
            cleaned_data['total_quantity'] = hanger_count * rack_per_hanger * product_per_rack

        # 총 생산시간 계산
        if hanger_count and turn_time_per_hanger:
            cleaned_data['total_time'] = hanger_count * turn_time_per_hanger

        return cleaned_data

ProductSubmaterialFormSet = inlineformset_factory(
    Product,
    ProductSubmaterial,
    fields=('submaterial', 'quantity'),
    extra=1,
    can_delete=True,
    widgets={
        'submaterial': forms.Select(attrs={'class': 'form-select form-select-sm'}),
        'quantity': forms.NumberInput(attrs={'class': 'form-control form-control-sm'}),
    },
    labels={
        'submaterial': '부자재',
        'quantity': '소요 수량',
    }
)