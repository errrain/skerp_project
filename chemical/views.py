# chemical/views.py

from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages                    # ← 추가 (chemical_price_view에서 사용)
from django.core.paginator import Paginator
from django.utils import timezone

from .models import Chemical
from .forms import (
    ChemicalForm,
    ChemicalPriceForm,
    ChemicalStdConcentrationForm,  # ✅ 추가
    ChemicalControlRangeForm,  # ✅ 추가
)

# XLSX 내보내기용 (누락 보완)
from io import BytesIO                                  # ← 추가
from urllib.parse import quote                          # ← 추가
from openpyxl import Workbook                           # ← 추가
from openpyxl.styles import Alignment, Font             # ← 추가

from django.template.loader import render_to_string      # ✅ 추가
from django.views.decorators.http import require_http_methods  # ✅ 추가

def chemical_list(request):
    search_name = request.GET.get('name', '')
    search_spec = request.GET.get('spec', '')
    search_customer = request.GET.get('customer', '')

    chemical_qs = Chemical.objects.filter(delete_yn='N')

    if search_name:
        chemical_qs = chemical_qs.filter(name__icontains=search_name)
    if search_spec:
        chemical_qs = chemical_qs.filter(spec__icontains=search_spec)
    if search_customer:
        chemical_qs = chemical_qs.filter(customer__name__icontains=search_customer)

    paginator = Paginator(chemical_qs.order_by('name', 'id'), 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'name': search_name,
        'spec': search_spec,
        'customer': search_customer,
    }
    return render(request, 'chemical/chemical_list.html', context)


def chemical_add(request):
    if request.method == 'POST':
        form = ChemicalForm(request.POST, request.FILES)
        if form.is_valid():
            chem = form.save(commit=False)
            chem.created_by = request.user.username
            chem.updated_by = request.user.username
            chem.save()
            return redirect('chemical:chemical_list')
    else:
        form = ChemicalForm()
    return render(request, 'chemical/chemical_form.html', {'form': form})


def chemical_edit(request, pk):
    chem = get_object_or_404(Chemical, pk=pk)
    if request.method == 'POST':
        form = ChemicalForm(request.POST, request.FILES, instance=chem)
        if form.is_valid():
            chem = form.save(commit=False)
            chem.updated_by = request.user.username
            chem.save()
            return redirect('chemical:chemical_list')
    else:
        form = ChemicalForm(instance=chem)
    return render(request, 'chemical/chemical_form.html', {'form': form})


def chemical_delete(request, pk):
    chem = get_object_or_404(Chemical, pk=pk)
    if request.method == 'POST':
        chem.delete_yn = 'Y'
        chem.save()
        return redirect('chemical:chemical_list')
    return render(request, 'chemical/chemical_confirm_delete.html', {'chemical': chem})

def chemical_price_view(request, pk):
    chemical = get_object_or_404(Chemical, pk=pk)

    if not chemical.id:
        messages.warning(request, "약품을 먼저 등록완료하세요.")
        return redirect('chemical:chemical_list')

    latest_price = chemical.prices.first()

    if request.method == 'POST':
        form = ChemicalPriceForm(request.POST)
        if form.is_valid():
            price = form.save(commit=False)
            price.chemical = chemical
            price.created_by = request.user.username
            price.save()
            return redirect('chemical:chemical_price', pk=chemical.pk)
    else:
        form = ChemicalPriceForm(initial={
            'date': timezone.now().strftime('%Y-%m-%dT%H:%M')
        })

    context = {
        'chemical': chemical,
        'latest_price': latest_price,
        'price_list': chemical.prices.all(),
        'form': form,
    }
    return render(request, 'chemical/chemical_price.html', context)

def chemical_export(request):
    # 검색 파라미터 그대로 사용
    search_name = request.GET.get('name', '')
    search_spec = request.GET.get('spec', '')
    search_customer = request.GET.get('customer', '')

    qs = Chemical.objects.filter(delete_yn='N')
    if search_name:
        qs = qs.filter(name__icontains=search_name)
    if search_spec:
        qs = qs.filter(spec__icontains=search_spec)
    if search_customer:
        qs = qs.filter(customer__name__icontains=search_customer)

    qs = qs.order_by('name', 'id')  # 목록 정렬과 동일 권장

    # ── openpyxl로 XLSX 생성 (한글 깨짐 방지: XLSX 사용)
    wb = Workbook()
    ws = wb.active
    ws.title = '약품목록'

    headers = [
        '번호', '품명', '규격(자연어)', '단위규격(정수)', '측정 단위', '포장단위', '비고',
        '고객사', '사용여부'
    ]
    ws.append(headers)

    # 헤더 스타일
    header_font = Font(bold=True)
    center = Alignment(horizontal='center', vertical='center')
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.alignment = center

    # 데이터
    for idx, c in enumerate(qs, start=1):
        ws.append([
            idx,
            c.name or '',
            c.spec or '',
            c.unit_qty or '',
            c.get_spec_unit_display() if c.spec_unit else '',
            c.container_uom or '',
            c.spec_note or '',
            (c.customer.name if c.customer else ''),
            c.get_use_yn_display() if hasattr(c, 'get_use_yn_display') else c.use_yn,
        ])

    # 열 너비(가독성)
    widths = [6, 24, 30, 12, 12, 12, 20, 18, 10]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w

    # 첫 행 고정
    ws.freeze_panes = 'A2'

    # 응답
    now = timezone.now().strftime('%Y%m%d_%H%M%S')
    filename_ko = f'약품목록_{now}.xlsx'
    resp = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    # 한글 파일명 호환(IE/Edge/Chrome)
    resp['Content-Disposition'] = f"attachment; filename=chemical.xlsx; filename*=UTF-8''{quote(filename_ko)}"

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    resp.write(buffer.getvalue())
    return resp

@require_http_methods(["GET", "POST"])
def chemical_std_view(request, pk):
    """
    표준농도 이력 블럭을 HTML 조각으로 반환.
    - GET  : 표준농도 이력 + 입력폼 초기값
    - POST : 이력 저장 후, 갱신된 블럭 HTML 반환
    """
    chemical = get_object_or_404(Chemical, pk=pk)

    latest_std = chemical.latest_std_concentration()

    if request.method == "POST":
        form = ChemicalStdConcentrationForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.chemical = chemical
            obj.created_by = getattr(request.user, "username", "")
            obj.save()

            # 저장 후에는 빈 폼(최근 단위 기준)으로 초기화
            initial = {
                "date": timezone.now().strftime("%Y-%m-%dT%H:%M"),
                "unit": obj.unit,
            }
            form = ChemicalStdConcentrationForm(initial=initial)
    else:
        initial = {"date": timezone.now().strftime("%Y-%m-%dT%H:%M")}
        if latest_std:
            initial["unit"] = latest_std.unit
        form = ChemicalStdConcentrationForm(initial=initial)

    html = render_to_string(
        "chemical/_chemical_std_block.html",
        {
            "chemical": chemical,
            "latest_std": chemical.latest_std_concentration(),
            "std_list": chemical.std_concentrations.all(),
            "form": form,
        },
        request=request,
    )
    return HttpResponse(html)

@require_http_methods(["GET", "POST"])
def chemical_range_view(request, pk):
    """
    관리범위 이력 블럭을 HTML 조각으로 반환.
    - GET  : 관리범위 이력 + 입력폼 초기값
    - POST : 이력 저장 후, 갱신된 블럭 HTML 반환
    """
    chemical = get_object_or_404(Chemical, pk=pk)

    latest_range = chemical.latest_control_range()

    if request.method == "POST":
        form = ChemicalControlRangeForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.chemical = chemical
            obj.created_by = getattr(request.user, "username", "")
            obj.save()

            initial = {
                "date": timezone.now().strftime("%Y-%m-%dT%H:%M"),
                "lower_value": obj.lower_value,
                "upper_value": obj.upper_value,
                "avg_value": obj.avg_value,
                "unit": obj.unit,
            }
            form = ChemicalControlRangeForm(initial=initial)
    else:
        initial = {"date": timezone.now().strftime("%Y-%m-%dT%H:%M")}
        if latest_range:
            initial.update(
                {
                    "lower_value": latest_range.lower_value,
                    "upper_value": latest_range.upper_value,
                    "avg_value": latest_range.avg_value,
                    "unit": latest_range.unit,
                }
            )
        form = ChemicalControlRangeForm(initial=initial)

    html = render_to_string(
        "chemical/_chemical_range_block.html",
        {
            "chemical": chemical,
            "latest_range": chemical.latest_control_range(),
            "range_list": chemical.control_ranges.all(),
            "form": form,
        },
        request=request,
    )
    return HttpResponse(html)