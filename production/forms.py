from django import forms
from django.forms import inlineformset_factory
from django.forms.models import BaseInlineFormSet

from .models import (
    WorkOrder,
    WorkOrderLine,
    SparePart,
    SparePartReceipt,
    SparePartUsage,
    ChemicalAddition,
    ChemicalAdditionLine,
    NonFerrousAddition,
    NonFerrousAdditionLine,
)



# ==========================
# 작업지시서 (헤더/라인)
# ==========================

class WorkOrderForm(forms.ModelForm):
    class Meta:
        model = WorkOrder
        fields = ["product", "customer", "order_qty", "planned_start", "planned_end", "remark"]
        widgets = {
            "product": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "customer": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "order_qty": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "min": 1}
            ),
            "planned_start": forms.DateTimeInput(
                attrs={"class": "form-control form-control-sm", "type": "datetime-local"}
            ),
            "planned_end": forms.DateTimeInput(
                attrs={"class": "form-control form-control-sm", "type": "datetime-local"}
            ),
            "remark": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
        }


class WorkOrderLineForm(forms.ModelForm):
    """작업지시서 상세 (렉/행거 단위)"""

    class Meta:
        model = WorkOrderLine
        fields = ["rack_capacity", "rack_count", "hanger_capacity", "hanger_count", "sequence", "remark"]
        widgets = {
            "rack_capacity": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "readonly": True}
            ),
            "rack_count": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "min": 0}
            ),
            "hanger_capacity": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "readonly": True}
            ),
            "hanger_count": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "min": 0}
            ),
            "sequence": forms.NumberInput(
                attrs={"class": "form-control form-control-sm", "min": 1}
            ),
            "remark": forms.TextInput(
                attrs={"class": "form-control form-control-sm"}
            ),
        }


WorkOrderLineFormSet = inlineformset_factory(
    WorkOrder,
    WorkOrderLine,
    form=WorkOrderLineForm,
    extra=1,
    can_delete=True,
)


# ==========================
# 스페어파트
# ==========================

class SparePartForm(forms.ModelForm):
    """스페어파트 마스터 폼"""

    class Meta:
        model = SparePart
        fields = ["name", "model_name", "spec", "remark"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
            "model_name": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
            "spec": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
            "remark": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
        }


class SparePartReceiptForm(forms.ModelForm):
    """스페어파트 입고 등록 폼"""

    class Meta:
        model = SparePartReceipt
        fields = ["received_at", "vendor", "amount", "quantity"]
        widgets = {
            "received_at": forms.DateTimeInput(
                attrs={"class": "form-control form-control-sm", "type": "datetime-local"}
            ),
            "vendor": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "amount": forms.NumberInput(
                attrs={"class": "form-control form-control-sm text-end", "min": 0}
            ),
            "quantity": forms.NumberInput(
                attrs={"class": "form-control form-control-sm text-end", "min": 1}
            ),
        }


class SparePartUsageForm(forms.ModelForm):
    """스페어파트 사용(출고) 등록 폼"""

    class Meta:
        model = SparePartUsage
        fields = ["used_at", "process", "quantity", "reason"]
        widgets = {
            "used_at": forms.DateTimeInput(
                attrs={"class": "form-control form-control-sm", "type": "datetime-local"}
            ),
            "process": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "quantity": forms.NumberInput(
                attrs={"class": "form-control form-control-sm text-end", "min": 1}
            ),
            "reason": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
        }


# ==========================
# 약품 투입일지 (chemadd)
# ==========================

class ChemicalAdditionForm(forms.ModelForm):
    """
    약품 투입 헤더용 폼
    - 공정 / 일자 / 근무조 / 비고
    """

    class Meta:
        model = ChemicalAddition
        fields = ["process", "work_date", "shift", "remark"]
        widgets = {
            "process": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "work_date": forms.DateInput(
                attrs={"class": "form-control form-control-sm", "type": "date"}
            ),
            "shift": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "remark": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
        }


class ChemicalAdditionLineBaseFormSet(BaseInlineFormSet):
    """
    chemadd 피벗 화면용 라인 FormSet
    - 새로 생성되는 행 중에서 '투입량이 비어 있는 행'은 저장하지 않는다.
    - 기존 행은 그대로 두고, DELETE 체크(숨김 필드)된 것만 삭제.
    """

    def save(self, commit=True):
        saved_instances = []

        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            if not form.cleaned_data:
                continue

            # 삭제 플래그 처리
            if self.can_delete and self._should_delete_form(form):
                instance = form.instance
                if instance.pk and commit:
                    instance.delete()
                continue

            qty = form.cleaned_data.get("quantity")
            instance = form.instance

            # 새 행 + 투입량 없음 => 저장 스킵
            if not instance.pk and (qty is None or qty == ""):
                continue

            if commit:
                instance = form.save(commit=True)
            else:
                instance = form.save(commit=False)

            saved_instances.append(instance)

        return saved_instances


class ChemicalAdditionLineForm(forms.ModelForm):
    """약품 투입 상세 라인 폼"""

    class Meta:
        model = ChemicalAdditionLine
        fields = ["chemical", "equipment", "quantity", "unit", "remark"]
        widgets = {
            "chemical": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "equipment": forms.Select(attrs={"class": "form-select form-select-sm"}),
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
                    "readonly": "readonly",
                }
            ),
            "remark": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # POST 바인딩 상태면 그대로 둠
        if self.is_bound:
            return

        # 1순위: initial 에서 단위 세팅 (신규 행)
        init_unit = self.initial.get("unit")
        if init_unit and not self.instance.pk:
            self.initial["unit"] = init_unit
            self.fields["unit"].initial = init_unit
            return

        # 2순위: instance.chemical.use_unit 기반 세팅
        chem = None
        if getattr(self.instance, "chemical_id", None):
            chem = self.instance.chemical

        if chem and getattr(chem, "use_unit", None):
            try:
                unit_display = chem.get_use_unit_display()
            except AttributeError:
                unit_display = chem.use_unit

            if unit_display:
                self.initial["unit"] = unit_display
                self.fields["unit"].initial = unit_display


ChemicalAdditionLineFormSet = inlineformset_factory(
    ChemicalAddition,
    ChemicalAdditionLine,
    form=ChemicalAdditionLineForm,
    extra=0,
    formset=ChemicalAdditionLineBaseFormSet,
    can_delete=True,
)


# ==========================
# 비철 투입일지 (nfadd)
# ==========================

class NonFerrousAdditionForm(forms.ModelForm):
    """비철 투입 헤더 폼 (공정 / 일자 / 근무조 / 비고)"""

    class Meta:
        model = NonFerrousAddition
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # ⚠ 여기서만 import 해서 순환참조 피하기
        from process.models import Process

        # ② 비철이 매핑된 공정만 선택 가능하게 필터
        qs = (
            Process.objects.filter(nonferrous__isnull=False)
            .distinct()
            .order_by("display_order", "id")
        )
        self.fields["process"].queryset = qs
        self.fields["process"].empty_label = "--------"


class NonFerrousAdditionLineForm(forms.ModelForm):
    """비철 투입 상세 라인 폼"""

    class Meta:
        model = NonFerrousAdditionLine
        fields = ["nonferrous", "group_code", "quantity", "unit", "remark"]
        widgets = {
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
                    "readonly": "readonly",
                    "style": "max-width:80px;",
                }
            ),
            "remark": forms.TextInput(
                attrs={"class": "form-control form-control-sm"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # FK, 그룹코드는 화면에서 숨김
        self.fields["nonferrous"].widget = forms.HiddenInput()
        if "group_code" in self.fields:
            self.fields["group_code"].widget = forms.HiddenInput()

        # 삭제 플래그도 사용 중이면 숨김 유지
        if "DELETE" in self.fields:
            self.fields["DELETE"].widget = forms.HiddenInput()

        # ----- 공통 헬퍼: 비철 객체에서 단위 채우기 -----
        def set_unit_from_nf(nf_obj):
            """
            - 사용자가 이미 입력한 값이나 POST 로 들어온 값이 있으면 건드리지 않음
            - 그렇지 않으면 nf_obj 의 단위를 unit 필드 초기값으로 세팅
            """
            if "unit" not in self.fields:
                return
            if self.is_bound:  # POST 된 상태면 그대로 두기
                return
            if self.initial.get("unit"):
                return

            unit_value = getattr(nf_obj, "unit", None) or getattr(
                nf_obj, "use_unit", None
            )
            if hasattr(nf_obj, "get_use_unit_display"):
                unit_value = nf_obj.get_use_unit_display()

            if unit_value:
                self.initial["unit"] = unit_value
                self.fields["unit"].initial = unit_value

        label = ""

        # ① 수정 화면: instance 에 이미 FK 가 있을 때
        nf_obj = getattr(self.instance, "nonferrous", None)
        if getattr(self.instance, "nonferrous_id", None) and nf_obj:
            label = getattr(nf_obj, "name", str(nf_obj))
            set_unit_from_nf(nf_obj)

        # ② 신규 화면: initial 에 nonferrous(pk 또는 객체)가 들어온 경우
        elif "nonferrous" in self.initial and self.initial["nonferrous"]:
            field = self.fields["nonferrous"]
            qs = field.queryset
            value = self.initial["nonferrous"]

            try:
                if hasattr(value, "_meta"):  # 이미 모델 인스턴스면 그대로 사용
                    nf_obj = value
                else:
                    nf_obj = qs.get(pk=value)

                label = getattr(nf_obj, "name", str(nf_obj))
                set_unit_from_nf(nf_obj)
            except Exception:
                # 못 찾으면 조용히 패스
                pass

        # ③ 혹시 뷰에서 nonferrous_label 을 initial 로 넘긴 경우 – 가장 마지막 우선순위
        if not label:
            label = self.initial.get("nonferrous_label", "")

        # 템플릿에서 {{ f.nonferrous_label }} 로 사용
        self.nonferrous_label = label


NonFerrousAdditionLineFormSet = inlineformset_factory(
    NonFerrousAddition,
    NonFerrousAdditionLine,
    form=NonFerrousAdditionLineForm,
    extra=0,   # GET에서 initial 로 행 개수 조정
    can_delete=True,
)
