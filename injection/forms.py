from django import forms
from .models import Injection, InjectionPrice, MoldHistory


class InjectionForm(forms.ModelForm):
    class Meta:
        model = Injection
        fields = [
            'name', 'alias', 'spec', 'status', 'part_number', 'sub_part_number',
            'part_size', 'material', 'vendor', 'image', 'use_yn', 'delete_yn'
        ]
        labels = {
            'name': '품명',
            'alias': '별칭',
            'spec': '규격',
            'status': '상태',
            'part_number': 'Part Number',
            'sub_part_number': 'Sub Part Number',
            'part_size': 'Part Size',
            'material': '소재',
            'vendor': '사출업체',
            'image': '제품 이미지',
            'use_yn': '사용 여부',
            'delete_yn': '삭제 여부',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['delete_yn'].required = False
        self.fields['use_yn'].required = False


class InjectionPriceForm(forms.ModelForm):
    class Meta:
        model = InjectionPrice
        fields = ['date', 'price']
        labels = {
            'date': '일자',
            'price': '단가',
        }


class MoldHistoryForm(forms.ModelForm):
    class Meta:
        model = MoldHistory
        fields = ['history_date', 'content']
        labels = {
            'history_date': '이력일자',
            'content': '이력 내용',
        }
