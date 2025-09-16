# vendor/forms.py
from django import forms
from .models import Vendor, VendorItemKind

class VendorForm(forms.ModelForm):
    major_items = forms.ModelMultipleChoiceField(
        label='주거래품목',
        queryset=VendorItemKind.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = Vendor
        fields = [
            'vendor_type', 'name', 'biz_number', 'transaction_type',
            'outsourcing_type', 'ceo_name', 'biz_type', 'biz_item',
            'phone', 'fax', 'email', 'manager_name', 'contact_phone', 'status',
            'can_login', 'address',
            'major_items',  # ✅ 반드시 포함
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
            'can_login': '로그인 허용',
            'address': '주소',
            'major_items': '주거래품목',
        }
        widgets = {
            'vendor_type': forms.Select,
            'transaction_type': forms.Select,
            'outsourcing_type': forms.Select,
            'status': forms.Select,
            'can_login': forms.CheckboxInput(),
            'address': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            # major_items는 필드 선언부에서 CheckboxSelectMultiple 지정
        }

    def clean(self):
        data = super().clean()
        tt = data.get('transaction_type')
        items = data.get('major_items')
        if tt in ('buy', 'both') and (not items or items.count() == 0):
            self.add_error('major_items', '거래구분이 [매입/매입매출 병행]이면 주거래품목을 1개 이상 선택하세요.')
        return data
