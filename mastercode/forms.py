# mastercode/forms.py

from django import forms
from .models import CodeGroup, CodeDetail


class CodeGroupForm(forms.ModelForm):
    class Meta:
        model = CodeGroup
        fields = ['group_code', 'group_name']
        labels = {
            'group_code': '그룹코드',
            'group_name': '그룹명',
        }


class CodeDetailForm(forms.ModelForm):
    class Meta:
        model = CodeDetail
        fields = ['group', 'code', 'name', 'sort_order', 'is_active']
        labels = {
            'group': '코드그룹',
            'code': '코드',
            'name': '코드명',
            'sort_order': '정렬순서',
            'is_active': '사용여부',
        }
