from django import forms
from django.forms import inlineformset_factory
from .models import (
    WorkOrder,
    WorkOrderLine,
    SparePart,
    SparePartReceipt,
    SparePartUsage,
    ChemicalAddition,
    ChemicalAdditionLine,
)


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

# 스페어파트 마스터 폼
class SparePartForm(forms.ModelForm):
    """
    스페어파트 기본정보 등록/수정 폼
    - 품명 / 모델명 / 규격 / 비고만 직접 입력
    - 수량·재고금액·최근일시는 시스템 계산값이라 폼에서 제외
    """
    class Meta:
        model = SparePart
        fields = ["name", "model_name", "spec", "remark"]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control form-control-sm"}
            ),
            "model_name": forms.TextInput(
                attrs={"class": "form-control form-control-sm"}
            ),
            "spec": forms.TextInput(
                attrs={"class": "form-control form-control-sm"}
            ),
            "remark": forms.TextInput(
                attrs={"class": "form-control form-control-sm"}
            ),
        }

# 스페어파트 입고 등록 폼
class SparePartReceiptForm(forms.ModelForm):
    """
    스페어파트 입고 등록 폼
    - 입고일시 / 거래처 / 금액 / 수량
    """
    class Meta:
        model = SparePartReceipt
        fields = ["received_at", "vendor", "amount", "quantity"]
        widgets = {
            "received_at": forms.DateTimeInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "type": "datetime-local",
                }
            ),
            "vendor": forms.Select(
                attrs={"class": "form-select form-select-sm"}
            ),
            "amount": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm text-end",
                    "min": 0,
                }
            ),
            "quantity": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm text-end",
                    "min": 1,
                }
            ),
        }

# 스페어파트 사용(출고) 등록 폼
class SparePartUsageForm(forms.ModelForm):
    """
    스페어파트 사용(출고) 등록 폼
    """
    class Meta:
        model = SparePartUsage
        fields = ["used_at", "process", "quantity", "reason"]
        widgets = {
            "used_at": forms.DateTimeInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "type": "datetime-local",
                }
            ),
            "process": forms.Select(
                attrs={"class": "form-select form-select-sm"}
            ),
            "quantity": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm text-end",
                    "min": 1,
                }
            ),
            "reason": forms.TextInput(
                attrs={"class": "form-control form-control-sm"}
            ),
        }

class ChemicalAdditionForm(forms.ModelForm):
    """
    약품 투입 헤더용 폼
    - 공정 / 일자 / 근무조 / 비고
    - created_by 는 뷰에서 request.user 로 세팅
    """
    class Meta:
        model = ChemicalAddition
        fields = ["process", "work_date", "shift", "remark"]
        widgets = {
            "process": forms.Select(
                attrs={"class": "form-select form-select-sm"}
            ),
            "work_date": forms.DateInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "type": "date",
                }
            ),
            "shift": forms.Select(
                attrs={"class": "form-select form-select-sm"}
            ),
            "remark": forms.TextInput(
                attrs={"class": "form-control form-control-sm"}
            ),
        }

class ChemicalAdditionLineForm(forms.ModelForm):
    """
    약품 투입 상세 라인 폼
    - 어떤 약품을 / 어떤 설비에 / 얼마나 / 단위 / 비고
    """
    class Meta:
        model = ChemicalAdditionLine
        fields = ["chemical", "equipment", "quantity", "unit", "remark"]
        widgets = {
            "chemical": forms.Select(
                attrs={"class": "form-select form-select-sm"}
            ),
            "equipment": forms.Select(
                attrs={"class": "form-select form-select-sm"}
            ),
            "quantity": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm text-end",
                    "min": 0,
                    "step": "0.001",
                }
            ),
            "unit": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "style": "max-width:80px;",
                }
            ),
            "remark": forms.TextInput(
                attrs={"class": "form-control form-control-sm"}
            ),
        }

ChemicalAdditionLineFormSet = inlineformset_factory(
    ChemicalAddition,
    ChemicalAdditionLine,
    form=ChemicalAdditionLineForm,
    extra=5,        # 기본은 0행, 뷰에서 initial 로 필요한 만큼 채울 예정
    can_delete=True,
)