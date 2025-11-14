# process/forms.py
from django import forms
from .models import Process, ProcessFile


class ProcessForm(forms.ModelForm):
    """
    공정 기본정보 입력 폼
    - 공정명(name)만 사실상 필수
    - 공정설명(description)은 선택
    - 표시순번(display_order)은 정렬용
    """
    class Meta:
        model = Process
        fields = ['name', 'description', 'display_order']
        labels = {
            'name': '공정명',
            'description': '공정설명',
            'display_order': '표시순번',
        }


class ProcessFileForm(forms.ModelForm):
    """
    작업표준서 파일 이력 등록용 폼
    - file: 선택 입력(필수 아님, required=False)
    """
    file = forms.FileField(label='작업표준서 파일', required=False)

    class Meta:
        model = ProcessFile
        fields = ['file', 'note']
        labels = {
            'file': '작업표준서 파일',
            'note': '비고',
        }