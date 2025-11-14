# production/spares/views.py

from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required

from ..models import SparePart, SparePartReceipt, SparePartUsage
from ..forms import (
    SparePartForm,
    SparePartReceiptForm,
    SparePartUsageForm,
)


# ----------------------
# 공통 헬퍼
# ----------------------
def _get_sparepart_context(
    spare_part,
    part_form=None,
    receipt_form=None,
    usage_form=None,
):
    """
    스페어파트 상세 화면 공통 컨텍스트 구성 헬퍼
    - 상단 기본정보 폼
    - 입고/사용 이력 테이블
    - 하단 입고/사용 등록 폼
    """
    if part_form is None:
        part_form = SparePartForm(instance=spare_part)
    if receipt_form is None:
        receipt_form = SparePartReceiptForm()
    if usage_form is None:
        usage_form = SparePartUsageForm()

    receipts = spare_part.receipts.all().order_by("-received_at", "-id")
    usages = spare_part.usages.all().order_by("-used_at", "-id")

    return {
        "spare_part": spare_part,
        "part_form": part_form,
        "receipt_form": receipt_form,
        "usage_form": usage_form,
        "receipts": receipts,
        "usages": usages,
    }


# ----------------------
# 스페어파트 목록
# ----------------------
@login_required
def sparepart_list(request):
    """
    스페어파트 목록
    - 검색: 품명(name), 규격(spec)
    - 페이징: 페이지당 10건
    """
    qs = SparePart.objects.all().order_by("name", "id")

    search_name = request.GET.get("name", "").strip()
    search_spec = request.GET.get("spec", "").strip()

    if search_name:
        qs = qs.filter(name__icontains=search_name)
    if search_spec:
        qs = qs.filter(spec__icontains=search_spec)

    paginator = Paginator(qs, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "search_name": search_name,
        "search_spec": search_spec,
    }
    return render(request, "production/spares/spares_list.html", context)


# ----------------------
# 스페어파트 신규등록
# ----------------------
@login_required
def sparepart_create(request):
    """
    스페어파트 신규 등록
    - 저장 후 상세 화면(입·출고 이력 포함)으로 이동
    """
    if request.method == "POST":
        form = SparePartForm(request.POST)
        if form.is_valid():
            spare_part = form.save()
            return redirect("production:spares:part_detail", pk=spare_part.pk)
    else:
        form = SparePartForm()

    # 신규 등록 시에는 이력/입출고 폼 없이 단순 폼만 표시
    context = {
        "spare_part": None,
        "part_form": form,
        "receipt_form": None,
        "usage_form": None,
        "receipts": [],
        "usages": [],
        "is_create": True,
    }
    return render(request, "production/spares/spares_form.html", context)


# ----------------------
# 스페어파트 상세/수정 화면
# ----------------------
@login_required
def sparepart_detail(request, pk):
    """
    스페어파트 상세
    - 상단: 기본정보 폼(수정용, 저장 버튼은 별도 URL로 전송)
    - 중간: 입고 이력
    - 하단: 사용 이력
    - 맨 아래: 입고등록/사용등록 폼 (각각 별도 URL로 POST)
    """
    spare_part = get_object_or_404(SparePart, pk=pk)
    context = _get_sparepart_context(spare_part)
    context["is_create"] = False
    return render(request, "production/spares/spares_form.html", context)


# ----------------------
# 스페어파트 기본정보 저장(수정)
# ----------------------
@login_required
def sparepart_update(request, pk):
    """
    스페어파트 기본정보 저장
    - POST 전용
    - 저장 후 다시 상세 화면으로 리다이렉트
    """
    spare_part = get_object_or_404(SparePart, pk=pk)

    if request.method != "POST":
        return redirect("production:spares:part_detail", pk=pk)

    form = SparePartForm(request.POST, instance=spare_part)
    if form.is_valid():
        form.save()
        return redirect("production:spares:part_list")

    # 에러가 있으면 동일 화면에 에러 표시
    context = _get_sparepart_context(spare_part, part_form=form)
    context["is_create"] = False
    return render(request, "production/spares/spares_form.html", context)


# ----------------------
# 스페어파트 삭제(소프트 삭제)
# ----------------------
@login_required
def sparepart_delete(request, pk):
    """
    스페어파트 삭제
    - 소프트 삭제: is_active=False, dlt_yn='Y'
    """
    spare_part = get_object_or_404(SparePart, pk=pk)

    if request.method == "POST":
        spare_part.is_active = False
        spare_part.dlt_yn = "Y"
        spare_part.save(update_fields=["is_active", "dlt_yn"])
        return redirect("production:spares:part_list")

    # GET으로 들어오면 그냥 상세 화면으로 돌려보냄
    return redirect("production:spares:part_detail", pk=pk)


# ----------------------
# 입고 등록
# ----------------------
@login_required
def sparepart_stock_in(request, pk):
    """
    스페어파트 입고 등록
    - 상세 화면 하단의 '입고등록' 폼에서 POST
    """
    spare_part = get_object_or_404(SparePart, pk=pk)

    if request.method != "POST":
        return redirect("production:spares:part_detail", pk=pk)

    form = SparePartReceiptForm(request.POST)
    if form.is_valid():
        receipt = form.save(commit=False)
        receipt.spare_part = spare_part
        receipt.save()

        # 입·출고 요약 갱신
        spare_part.refresh_stock_summary()
        return redirect("production:spares:part_detail", pk=pk)

    # 에러가 있을 경우, 동일 상세 화면에서 에러 보여주기
    context = _get_sparepart_context(spare_part, receipt_form=form)
    context["is_create"] = False
    return render(request, "production/spares/spares_form.html", context)


# ----------------------
# 사용(출고) 등록
# ----------------------
@login_required
def sparepart_stock_out(request, pk):
    """
    스페어파트 사용(출고) 등록
    - 상세 화면 하단의 '사용등록' 폼에서 POST
    - 현재 수량보다 많이 사용하는 경우 에러 처리
    """
    spare_part = get_object_or_404(SparePart, pk=pk)

    if request.method != "POST":
        return redirect("production:spares:part_detail", pk=pk)

    form = SparePartUsageForm(request.POST)
    if form.is_valid():
        usage = form.save(commit=False)
        usage.spare_part = spare_part

        # 현재 수량 체크
        qty = usage.quantity or 0
        if qty < 1:
            form.add_error("quantity", "사용 수량은 1 이상이어야 합니다.")
        elif spare_part.current_qty is not None and qty > spare_part.current_qty:
            form.add_error("quantity", "현재 수량보다 많이 사용할 수 없습니다.")

        if not form.errors:
            usage.save()
            spare_part.refresh_stock_summary()
            return redirect("production:spares:part_detail", pk=pk)

    # 에러가 있을 경우, 동일 상세 화면에서 에러 보여주기
    context = _get_sparepart_context(spare_part, usage_form=form)
    context["is_create"] = False
    return render(request, "production/spares/spares_form.html", context)
