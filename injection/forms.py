from django import forms
from .models import Injection

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
