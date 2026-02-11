from django import forms

from mastercode.models import CodeDetail
from vendor.models import Vendor
from .models import CustomUser


DEPARTMENT_GROUP_CODE = 'DEPARTMENT'

class CustomUserForm(forms.ModelForm):
    password = forms.CharField(
        label='비밀번호',
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        strip=False,
        required=False,  # ✅ 필수 아님
    )
    # ✅ 추가 필드
    is_internal = forms.BooleanField(
        label='서경화학 임직원',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    vendor = forms.ModelChoiceField(
        queryset=Vendor.objects.filter(can_login=True, status='active'),
        label='거래처',
        required=False,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )
    department = forms.ChoiceField(
        label='부서',
        choices=(),
        required=True,
        widget=forms.Select(attrs={'class': 'form-select form-select-sm'})
    )

    class Meta:
        model = CustomUser
        fields = [
            'username', 'password', 'full_name', 'department', 'level',
            'status', 'phone', 'email',
            'is_internal',  # ✅ 추가
            'vendor',  # ✅ 추가
        ]
        labels = {
            'username': '아이디',
            'password': '비밀번호',
            'full_name': '이름',
            'department': '부서',
            'level': '레벨',
            'status': '상태',
            'phone': '전화번호',
            'email': '이메일',
            'is_internal': '서경화학 임직원',
            'vendor': '거래처',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        department_choices = [('', '부서 선택')] + [
            (d.code, d.name)
            for d in CodeDetail.objects.select_related('group').filter(
                group__group_code=DEPARTMENT_GROUP_CODE,
                is_active=True,
            )
        ]
        self.fields['department'].choices = department_choices

    def clean(self):
        cleaned_data = super().clean()
        is_internal = cleaned_data.get('is_internal')
        vendor = cleaned_data.get('vendor')
        if not is_internal and not vendor:
            self.add_error('vendor', '외부 사용자는 반드시 거래처를 선택해야 합니다.')
        if is_internal:
            cleaned_data['vendor'] = None
        return cleaned_data

    def clean_department(self):
        department = self.cleaned_data.get('department')
        if not department:
            raise forms.ValidationError('부서를 선택해 주세요.')

        is_valid = CodeDetail.objects.filter(
            group__group_code=DEPARTMENT_GROUP_CODE,
            code=department,
            is_active=True,
        ).exists()
        if not is_valid:
            raise forms.ValidationError('유효한 부서 코드를 선택해 주세요.')
        return department
