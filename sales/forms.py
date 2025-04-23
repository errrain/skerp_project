# sales/forms.py

from django import forms
from .models import CustomerOrder, CustomerOrderItem

class CustomerOrderForm(forms.ModelForm):
    class Meta:
        model = CustomerOrder
        fields = ['customer', 'memo']

        widgets = {
            'memo': forms.Textarea(attrs={'rows': 2}),
        }

class CustomerOrderItemForm(forms.ModelForm):
    class Meta:
        model = CustomerOrderItem
        fields = ['product', 'quantity', 'delivery_date', 'invoice_number']

        widgets = {
            'quantity': forms.NumberInput(attrs={'class': 'form-control form-control-sm'}),
            'delivery_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control form-control-sm'}),
            'invoice_number': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
        }
