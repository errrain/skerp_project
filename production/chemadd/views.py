from datetime import date

from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from django.db import transaction

from ..models import ChemicalAddition
from ..forms import ChemicalAdditionForm, ChemicalAdditionLineFormSet
from process.models import Process


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
    """
    addition = ChemicalAddition()

    if request.method == "POST":
        form = ChemicalAdditionForm(request.POST, instance=addition)
        formset = ChemicalAdditionLineFormSet(
            request.POST,
            instance=addition,
            prefix="lines",
        )

        if form.is_valid() and formset.is_valid():
            addition = form.save(commit=False)
            addition.created_by = request.user
            addition.save()
            formset.instance = addition
            formset.save()
            return redirect("production:chemadd:chemadd_edit", pk=addition.pk)

    else:
        initial = {
            "work_date": date.today(),
        }
        process_id = request.GET.get("process")
        if process_id:
            initial["process"] = process_id

        form = ChemicalAdditionForm(initial=initial)
        # 신규 등록 시에는 몇 줄 정도 빈 라인 보여주기
        LineFormSet = ChemicalAdditionLineFormSet
        LineFormSet.extra = 5
        formset = LineFormSet(prefix="lines")

    context = {
        "form": form,
        "formset": formset,
        "addition": None,
        "is_create": True,
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

    if request.method == "POST":
        form = ChemicalAdditionForm(request.POST, instance=addition)
        formset = ChemicalAdditionLineFormSet(
            request.POST,
            instance=addition,
            prefix="lines",
        )

        if form.is_valid() and formset.is_valid():
            addition = form.save(commit=False)
            if addition.created_by is None:
                addition.created_by = request.user
            addition.save()
            formset.save()
            return redirect("production:chemadd:chemadd_edit", pk=addition.pk)

    else:
        form = ChemicalAdditionForm(instance=addition)
        formset = ChemicalAdditionLineFormSet(instance=addition, prefix="lines")

    context = {
        "form": form,
        "formset": formset,
        "addition": addition,
        "is_create": False,
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
