from django import forms
from .models import CustomUser

class CustomUserForm(forms.ModelForm):
    password = forms.CharField(
        label='비밀번호',
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        strip=False,
        required=False,  # ✅ 필수 아님
    )

    class Meta:
        model = CustomUser
        fields = [
            'username', 'password', 'full_name', 'department', 'level',
            'status', 'phone', 'email'
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
        }
