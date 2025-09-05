from django import forms
from django.forms import inlineformset_factory
from .models import WorkOrder, WorkOrderLine


class WorkOrderForm(forms.ModelForm):
    class Meta:
        model = WorkOrder
        fields = ["product", "customer", "order_qty", "planned_start", "planned_end", "remark"]
        widgets = {
            "product": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "customer": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "order_qty": forms.NumberInput(attrs={"class": "form-control form-control-sm", "min": 1}),
            "planned_start": forms.DateTimeInput(attrs={"class": "form-control form-control-sm", "type": "datetime-local"}),
            "planned_end": forms.DateTimeInput(attrs={"class": "form-control form-control-sm", "type": "datetime-local"}),
            "remark": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
        }


class WorkOrderLineForm(forms.ModelForm):
    """작업지시서 상세 (렉/행거 단위)"""

    class Meta:
        model = WorkOrderLine
        fields = ["rack_capacity", "rack_count", "hanger_capacity", "hanger_count", "sequence", "remark"]
        widgets = {
            "rack_capacity": forms.NumberInput(attrs={"class": "form-control form-control-sm", "readonly": True}),
            "rack_count": forms.NumberInput(attrs={"class": "form-control form-control-sm", "min": 0}),
            "hanger_capacity": forms.NumberInput(attrs={"class": "form-control form-control-sm", "readonly": True}),
            "hanger_count": forms.NumberInput(attrs={"class": "form-control form-control-sm", "min": 0}),
            "sequence": forms.NumberInput(attrs={"class": "form-control form-control-sm", "min": 1}),
            "remark": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
        }


# Inline FormSet (WorkOrder ↔ WorkOrderLine)
WorkOrderLineFormSet = inlineformset_factory(
    WorkOrder,
    WorkOrderLine,
    form=WorkOrderLineForm,
    extra=1,            # 기본 1행 표시
    can_delete=True,    # 행 삭제 가능
)
