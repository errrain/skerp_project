from django import forms
from .models import InjectionOrder, InjectionOrderItem
from injection.models import Injection
from django.forms import modelformset_factory

class InjectionOrderForm(forms.ModelForm):
    class Meta:
        model = InjectionOrder
        fields = ['vendor', 'order_date']
        widgets = {
            'order_date': forms.DateInput(attrs={'type': 'date'}),
        }

class InjectionOrderItemForm(forms.ModelForm):
    class Meta:
        model = InjectionOrderItem
        fields = ['injection', 'quantity', 'expected_date']
        widgets = {
            'quantity': forms.NumberInput(attrs={'disabled': 'disabled'}),
            'expected_date': forms.DateInput(attrs={'type': 'date', 'disabled': 'disabled'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['injection'].widget = forms.HiddenInput()

InjectionOrderItemFormSet = modelformset_factory(
    InjectionOrderItem,
    form=InjectionOrderItemForm,
    extra=10,
    can_delete=False
)
