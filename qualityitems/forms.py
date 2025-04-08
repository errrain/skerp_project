from django import forms
from .models import QualityGroup, QualityItem


class QualityGroupForm(forms.ModelForm):
    class Meta:
        model = QualityGroup
        fields = ['code', 'name', 'use_yn']
        labels = {
            'code': '검사구분코드',
            'name': '검사구분명',
            'use_yn': '사용여부',
        }


class QualityItemForm(forms.ModelForm):
    class Meta:
        model = QualityItem
        fields = ['group', 'name', 'method', 'upper_limit', 'lower_limit', 'use_yn']
        labels = {
            'group': '검사구분',
            'name': '검사항목명',
            'method': '검사방법',
            'upper_limit': '허용 상한',
            'lower_limit': '허용 하한',
            'use_yn': '사용여부',
        }

    def save(self, commit=True, user=None):
        instance = super().save(commit=False)

        # 코드 자동 생성
        if not instance.pk:  # 신규 등록 시
            prefix = instance.group.code  # 예: Q001
            last = QualityItem.objects.filter(group=instance.group).order_by('-code').first()
            if last:
                last_no = int(last.code.split('_')[-1][1:])  # A001 → 1
                new_code = f"{prefix}_A{last_no + 1:03}"
            else:
                new_code = f"{prefix}_A001"
            instance.code = new_code

            instance.created_by = user.username if user else None
        else:
            instance.updated_by = user.username if user else None

        if commit:
            instance.save()
        return instance
