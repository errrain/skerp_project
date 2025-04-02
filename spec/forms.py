from django import forms
from .models import Spec

class SpecForm(forms.ModelForm):
    class Meta:
        model = Spec
        fields = ['name', 'description', 'image']
        labels = {
            'name': '사양명',
            'description': '설명',
            'image': 'COLOR SAMPLE',
        }