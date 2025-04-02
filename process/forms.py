
from django import forms
from .models import Process, ProcessFile

class ProcessForm(forms.ModelForm):
    class Meta:
        model = Process
        fields = ['name', 'description']
        labels = {
            'name': '공정명',
            'description': '공정설명',
        }

class ProcessFileForm(forms.ModelForm):
    class Meta:
        model = ProcessFile
        fields = ['file', 'note']
        labels = {
            'file': '작업표준서 파일',
            'note': '비고',
        }
