# master/forms.py
from django import forms
from .models import CompanyInfo, Warehouse
import re     # ← 추가


class CompanyInfoForm(forms.ModelForm):
    class Meta:
        model = CompanyInfo
        fields = [
            'name', 'biz_number', 'corp_number', 'establish_date',
            'ceo_name', 'biz_type', 'biz_item', 'address',
            'phone', 'fax', 'email', 'tax_email'
        ]
        widgets = {
            'establish_date': forms.DateInput(attrs={'type': 'date'}),
            'address': forms.Textarea(attrs={'rows': 2}),
        }

    # ---------------- 공통 유틸 ----------------
    def _only_digits(self, value: str) -> str:
        """숫자만 남기기"""
        return re.sub(r'\D', '', value or '')

    def _format_phone(self, digits: str):
        """한국 전화번호 포맷팅 (02 / 휴대폰 / 지역번호)"""
        if not digits:
            return None

        # 02 국번
        if digits.startswith('02'):
            if len(digits) == 9:
                # 02-123-4567
                return f'{digits[0:2]}-{digits[2:5]}-{digits[5:9]}'
            elif len(digits) == 10:
                # 02-1234-5678
                return f'{digits[0:2]}-{digits[2:6]}-{digits[6:10]}'
            else:
                return None

        # 그 외 (010, 031 등)
        if len(digits) == 10:
            # 031-123-4567, 053-123-4567
            return f'{digits[0:3]}-{digits[3:6]}-{digits[6:10]}'
        elif len(digits) == 11:
            # 010-1234-5678
            return f'{digits[0:3]}-{digits[3:7]}-{digits[7:11]}'

        return None

    # ---------------- 사업자번호 ----------------
    def clean_biz_number(self):
        raw = self.cleaned_data.get('biz_number', '')
        digits = self._only_digits(raw)

        if digits and len(digits) != 10:
            raise forms.ValidationError('사업자번호는 숫자 10자리여야 합니다.')

        # 123-45-67890 형식으로 저장
        return f'{digits[0:3]}-{digits[3:5]}-{digits[5:10]}' if digits else ''

    # ---------------- 법인번호 ----------------
    def clean_corp_number(self):
        raw = self.cleaned_data.get('corp_number', '')
        if not raw:
            return ''  # 선택 입력

        digits = self._only_digits(raw)

        if len(digits) != 13:
            raise forms.ValidationError('법인번호는 숫자 13자리여야 합니다.')

        # 123456-1234567 형식으로 저장
        return f'{digits[0:6]}-{digits[6:13]}'

    # ---------------- 대표 전화번호 ----------------
    def clean_phone(self):
        raw = self.cleaned_data.get('phone', '')
        digits = self._only_digits(raw)

        formatted = self._format_phone(digits)
        if not formatted:
            raise forms.ValidationError('대표 전화번호 형식이 올바르지 않습니다.')

        return formatted

    # ---------------- 대표 팩스번호 ----------------
    def clean_fax(self):
        raw = self.cleaned_data.get('fax', '')
        if not raw:
            return ''  # 선택 입력이니까 비어 있으면 그냥 통과

        digits = self._only_digits(raw)
        formatted = self._format_phone(digits)

        if not formatted:
            raise forms.ValidationError('대표 팩스번호 형식이 올바르지 않습니다.')

        return formatted

class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        exclude = ['warehouse_id']
        labels = {
            'name': '창고명',
            'description': '창고 설명',
            'is_active': '사용 여부',
            'is_deleted': '삭제 여부',
        }