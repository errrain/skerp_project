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
            'vendor_type': forms.RadioSelect,
            'transaction_type': forms.RadioSelect,
            'outsourcing_type': forms.RadioSelect,
            'status': forms.RadioSelect,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # "---------" 제거
        # "---------" 제거 및 choices 명시
        self.fields['vendor_type'].required = True
        self.fields['vendor_type'].widget = forms.RadioSelect(
            choices=Vendor.VENDOR_TYPE_CHOICES
        )

        self.fields['transaction_type'].required = True
        self.fields['transaction_type'].widget = forms.RadioSelect(
            choices=Vendor.TRANSACTION_TYPE_CHOICES
        )

        self.fields['outsourcing_type'].required = True
        self.fields['outsourcing_type'].widget = forms.RadioSelect(
            choices=Vendor.OUTSOURCING_TYPE_CHOICES
        )

        self.fields['status'].required = True
        self.fields['status'].widget = forms.RadioSelect(
            choices=Vendor.STATUS_CHOICES
        )