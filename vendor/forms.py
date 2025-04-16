from django import forms
from .models import Vendor

class VendorForm(forms.ModelForm):
    class Meta:
        model = Vendor
        fields = [
            'vendor_type', 'name', 'biz_number', 'transaction_type',
            'outsourcing_type', 'ceo_name', 'biz_type', 'biz_item',
            'phone', 'fax', 'email', 'manager_name', 'contact_phone', 'status'
        ]
        labels = {
            'vendor_type': '구분',
            'name': '기업명',
            'biz_number': '사업자번호',
            'transaction_type': '거래구분',
            'outsourcing_type': '외주구분',
            'ceo_name': '대표자 이름',
            'biz_type': '업태',
            'biz_item': '업종',
            'phone': '대표 전화',
            'fax': '대표 팩스',
            'email': '대표 이메일',
            'manager_name': '담당자명',
            'contact_phone': '담당자 전화번호',
            'status': '사용 여부',
        }
        widgets = {
            'vendor_type': forms.Select,
            'transaction_type': forms.Select,
            'outsourcing_type': forms.Select,
            'status': forms.Select,
        }
