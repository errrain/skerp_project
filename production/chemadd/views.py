from datetime import date

from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.forms import inlineformset_factory

from ..models import (ChemicalAddition,ChemicalAdditionLine)
from ..forms import (
    ChemicalAdditionForm,
    ChemicalAdditionLineForm,
    ChemicalAdditionLineFormSet, ChemicalAdditionLineBaseFormSet,
)
from collections import OrderedDict

from process.models import Process, ProcessChemical, ProcessEquipment

def build_chemadd_pivot(formset, process_obj):
    """
    chemadd 화면에서 사용할 피벗 데이터 생성
    - equipments: 공정에 매핑된 설비 리스트
    - chem_rows: [{ "chemical": Chemical, "forms": [form or None, ...] }, ...]
    """
    if process_obj is None or formset is None:
        return [], []

    # 공정별 설비 리스트 (헤더용)
    equipments = list(
        ProcessEquipment.objects
        .filter(process=process_obj)
        .select_related("equipment")
        .order_by("order", "id")
    )

    # (chemical_id, equipment_id) -> form 매핑
    forms_map = {}
    for f in formset.forms:
        chem_id = getattr(f.instance, "chemical_id", None) or f.initial.get("chemical")
        eq_id = getattr(f.instance, "equipment_id", None) or f.initial.get("equipment")
        if not chem_id or not eq_id:
            continue
        forms_map[(chem_id, eq_id)] = f

    chem_rows = []
    chemicals = (
        ProcessChemical.objects
        .filter(process=process_obj)
        .select_related("chemical")
        .order_by("order", "id")
    )

    for pc in chemicals:
        row_forms = []
        for pe in equipments:
            row_forms.append(forms_map.get((pc.chemical_id, pe.equipment_id)))
        chem_rows.append(
            {
                "chemical": pc.chemical,
                "forms": row_forms,
            }
        )

    return equipments, chem_rows


@login_required
def chemadd_list(request):
    """
    약품 투입 헤더 목록
    - 공정 / 일자 / 근무조로 필터
    """
    qs = ChemicalAddition.objects.select_related("process", "created_by")

    process_id = request.GET.get("process")
    if process_id:
        qs = qs.filter(process_id=process_id)

    date_from = request.GET.get("date_from")
    if date_from:
        qs = qs.filter(work_date__gte=date_from)

    date_to = request.GET.get("date_to")
    if date_to:
        qs = qs.filter(work_date__lte=date_to)

    shift = request.GET.get("shift")
    if shift:
        qs = qs.filter(shift=shift)

    qs = qs.order_by("-work_date", "-id")

    paginator = Paginator(qs, 20)
    page_number = request.GET.get("page", "1")
    page_obj = paginator.get_page(page_number)

    process_list = Process.objects.all().order_by("name")

    context = {
        "page_obj": page_obj,
        "process_list": process_list,
        "selected_process": process_id or "",
        "date_from": date_from or "",
        "date_to": date_to or "",
        "selected_shift": shift or "",
    }
    return render(request, "production/chemadd/chemadd_list.html", context)


@login_required
@transaction.atomic
def chemadd_create(request):
    """
    약품 투입 헤더 + 라인 신규 등록
    - GET : 공정 선택 시 공정별 약품 × 설비 매핑으로 라인 자동 생성
    - POST : 헤더 + 라인 저장
    """
    addition = ChemicalAddition()  # 아직 저장 전 부모 객체
    process_obj = None

    # -------------------- POST (저장) --------------------
    if request.method == "POST":
        form = ChemicalAdditionForm(request.POST, instance=addition)
        formset = ChemicalAdditionLineFormSet(
            request.POST,
            instance=addition,
            prefix="lines",
        )

        # 폼 데이터에서 공정 값 읽어서 피벗용 process_obj 세팅
        process_id = form.data.get("process")
        if process_id:
            try:
                process_obj = Process.objects.get(pk=process_id)
            except Process.DoesNotExist:
                process_obj = None

        if form.is_valid() and formset.is_valid():
            addition = form.save(commit=False)
            if hasattr(addition, "created_by") and not addition.pk:
                addition.created_by = request.user
            addition.save()

            formset.instance = addition
            formset.save()

            messages.success(request, "약품 투입 일지가 저장되었습니다.")  # ← 추가

            return redirect("production:chemadd:chemadd_edit", pk=addition.pk)

    # -------------------- GET (초기 표시) --------------------
    else:
        initial_header = {"work_date": date.today()}

        process_id = request.GET.get("process")
        if process_id:
            initial_header["process"] = process_id
            try:
                process_obj = Process.objects.get(pk=process_id)
            except Process.DoesNotExist:
                process_obj = None

        form = ChemicalAdditionForm(initial=initial_header, instance=addition)

        initial_lines = []

        if process_obj:
            chemicals = (
                ProcessChemical.objects
                .filter(process=process_obj)
                .select_related("chemical")
                .order_by("order", "id")
            )
            equipments = (
                ProcessEquipment.objects
                .filter(process=process_obj)
                .select_related("equipment")
                .order_by("order", "id")
            )

            # 공정별 약품 × 설비 조합으로 초기 라인 생성
            for pc in chemicals:
                chem = pc.chemical
                unit_display = ""
                if getattr(chem, "use_unit", None):
                    try:
                        unit_display = chem.get_use_unit_display()
                    except AttributeError:
                        unit_display = chem.use_unit

                for pe in equipments:
                    initial_lines.append(
                        {
                            "chemical": chem.id,
                            "equipment": pe.equipment_id,
                            "unit": unit_display or "ml",
                        }
                    )

        # 실제 폼셋 생성
        if initial_lines:
            DynamicLineFormSet = inlineformset_factory(
                ChemicalAddition,
                ChemicalAdditionLine,
                form=ChemicalAdditionLineForm,
                formset=ChemicalAdditionLineBaseFormSet,  # ← 추가
                extra=len(initial_lines),
                can_delete=True,
            )
            formset = DynamicLineFormSet(
                instance=addition,
                prefix="lines",
                initial=initial_lines,
            )
        else:
            DynamicLineFormSet = inlineformset_factory(
                ChemicalAddition,
                ChemicalAdditionLine,
                form=ChemicalAdditionLineForm,
                formset=ChemicalAdditionLineBaseFormSet,  # ← 추가
                extra=5,
                can_delete=True,
            )
            formset = DynamicLineFormSet(
                instance=addition,
                prefix="lines",
            )

    # ----- 공통: 피벗용 데이터 구성 -----
    equipments, chem_rows = build_chemadd_pivot(formset, process_obj)

    context = {
        "form": form,
        "formset": formset,
        "addition": None,
        "is_create": True,
        "equipments": equipments,
        "chem_rows": chem_rows,
    }
    return render(request, "production/chemadd/chemadd_form.html", context)


@login_required
@transaction.atomic
def chemadd_edit(request, pk):
    """
    약품 투입 헤더 + 라인 수정 화면
    - 헤더 수정
    - 라인(약품/설비/투입량) 추가/수정/삭제
    """
    addition = get_object_or_404(ChemicalAddition, pk=pk)
    process_obj = addition.process

    if request.method == "POST":
        form = ChemicalAdditionForm(request.POST, instance=addition)
        formset = ChemicalAdditionLineFormSet(
            request.POST,
            instance=addition,
            prefix="lines",
        )

        # 사용자가 공정을 바꿨다면 그 값을 기준으로 피벗 생성
        process_id = form.data.get("process")
        if process_id:
            try:
                process_obj = Process.objects.get(pk=process_id)
            except Process.DoesNotExist:
                process_obj = None

        if form.is_valid() and formset.is_valid():
            addition = form.save(commit=False)
            if addition.created_by is None:
                addition.created_by = request.user
            addition.save()
            formset.save()

            messages.success(request, "약품 투입 일지가 저장되었습니다.")  # ← 추가

            return redirect("production:chemadd:chemadd_edit", pk=addition.pk)

    else:
        form = ChemicalAdditionForm(instance=addition)
        formset = ChemicalAdditionLineFormSet(instance=addition, prefix="lines")
        process_obj = addition.process

    # ----- 공통: 피벗용 데이터 구성 -----
    equipments, chem_rows = build_chemadd_pivot(formset, process_obj)

    context = {
        "form": form,
        "formset": formset,
        "addition": addition,
        "is_create": False,
        "equipments": equipments,
        "chem_rows": chem_rows,
    }
    return render(request, "production/chemadd/chemadd_form.html", context)

@login_required
def chemadd_delete(request, pk):
    """
    약품 투입 헤더 삭제 (라인도 같이 삭제)
    - 필요하면 나중에 soft delete 로 변경 가능
    """
    addition = get_object_or_404(ChemicalAddition, pk=pk)

    if request.method == "POST":
        addition.delete()
        return redirect("production:chemadd:chemadd_list")

    # GET 으로 직접 치고 들어오면 목록으로 돌려보냄
    return redirect("production:chemadd:chemadd_list")
