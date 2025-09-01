from django import forms
from .models import RackMaster

class RackMasterForm(forms.ModelForm):
    class Meta:
        model = RackMaster
        fields = [
            'product_nm',
            'product_no',
            'make_comp',
            'con_num',
            'max_count',
            'use_yn',
            'dlt_yn',
            'image',  # ✅ 이미지 필드 포함
        ]
        labels = {
            'product_nm': '품명',
            'product_no': '품번',
            'make_comp': '제작처',
            'con_num': '사출 채결 수량',
            'max_count': '기본 한계 사용수',
            'use_yn': '사용 여부',
            'dlt_yn': '삭제 여부',
            'image': 'RACK 이미지',
        }

    # 추가적으로 파일 첨부 UI 개선을 위한 위젯 속성 지정 (선택 사항)
    image = forms.ImageField(required=False, widget=forms.ClearableFileInput(attrs={'class': 'form-control form-control-sm'}))
