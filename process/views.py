import mimetypes

from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator
from django.http import FileResponse, JsonResponse, HttpResponseBadRequest
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET
from django.db.models import Q, Max, Count

from .models import (
    Process,
    ProcessFile,
    ProcessChemical,
    ProcessEquipment,
)
from .forms import ProcessForm, ProcessFileForm

from chemical.models import Chemical
from equipment.models import Equipment

from .models import Process, ProcessChemical, ProcessEquipment, ProcessNonFerrous
from nonferrous.models import Chemical as NonferrousChemical


@login_required
def process_list(request):
    """공정 목록: 이름 검색 + 표시순번 기준 정렬 + 연결 수량 표시"""
    search_name = request.GET.get('name', '').strip()

    processes = Process.objects.all()

    if search_name:
        processes = processes.filter(name__icontains=search_name)

    # 연결된 약품/설비/파일 개수 미리 계산 (N+1 방지)
    processes = processes.annotate(
        chemical_count=Count('processchemical', distinct=True),
        equipment_count=Count('processequipment', distinct=True),
        file_count=Count('files', distinct=True),
    ).order_by('display_order', 'id')

    # 👉 1페이지당 20개
    paginator = Paginator(processes, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'process/process_list.html', {
        'page_obj': page_obj,
        'search_name': search_name,
    })


@login_required
def process_add(request):
    """새 공정 등록 (파일 이력은 edit 화면에서 추가)"""
    files = []

    if request.method == 'POST':
        form = ProcessForm(request.POST)
        file_form = ProcessFileForm()  # 새 공정에서는 사용하지 않지만 템플릿 구조 맞추기용

        if form.is_valid():
            process = form.save()
            return redirect('process:process_edit', pk=process.pk)

    else:
        form = ProcessForm()
        file_form = ProcessFileForm()

    return render(request, 'process/process_form.html', {
        'form': form,
        'files': files,
        'file_form': file_form,
    })


@login_required
def process_edit(request, pk):
    """공정 기본정보 수정 + 작업표준서 파일 이력 관리"""
    process = get_object_or_404(Process, pk=pk)
    files = process.files.all().order_by('-created_at')

    if request.method == 'POST':
        # [ + 파일등록 ] 버튼으로 submit 된 경우
        if 'upload_file' in request.POST:
            # 공정 정보는 그대로 유지
            form = ProcessForm(instance=process)
            file_form = ProcessFileForm(request.POST, request.FILES)

            if file_form.is_valid():
                uploaded_file = file_form.cleaned_data.get('file')

                # 실제 파일이 있을 때만 이력 생성
                if uploaded_file:
                    new_file = file_form.save(commit=False)
                    new_file.process = process
                    new_file.created_by = request.user.username
                    new_file.save()

                # 파일등록 후에는 다시 현재 공정 edit 화면으로
                return redirect('process:process_edit', pk=pk)

        # 그 외(저장 버튼 등) → 공정 기본정보 저장
        else:
            form = ProcessForm(request.POST, instance=process)
            file_form = ProcessFileForm()

            if form.is_valid():
                form.save()
                # 👇 여기! 저장 후 공정 리스트로 이동
                return redirect('process:process_list')

    else:
        form = ProcessForm(instance=process)
        file_form = ProcessFileForm()

    return render(request, 'process/process_form.html', {
        'form': form,
        'files': files,
        'file_form': file_form,
        'process': process,
    })


@login_required
def process_delete(request, pk):
    process = get_object_or_404(Process, pk=pk)
    process.delete()
    return redirect('process:process_list')


@login_required
def process_file_update(request, process_id, file_id):
    file = get_object_or_404(ProcessFile, pk=file_id, process_id=process_id)
    if request.method == 'POST':
        file.note = request.POST.get('note', '')
        file.save()
    return redirect('process:process_edit', pk=process_id)


@login_required
def process_file_delete(request, process_id, file_id):
    file = get_object_or_404(ProcessFile, pk=file_id, process_id=process_id)
    file.delete()
    return redirect('process:process_edit', pk=process_id)


@login_required
def process_file_preview(request, process_id):
    latest_file = ProcessFile.objects.filter(process_id=process_id).order_by('-created_at').first()
    if not latest_file or not latest_file.file:
        return redirect('process:process_edit', pk=process_id)

    mime_type, _ = mimetypes.guess_type(latest_file.file.name)
    return FileResponse(
        latest_file.file.open('rb'),
        as_attachment=False,                 # ← 미리보기
        content_type=mime_type or 'application/octet-stream',
    )


@login_required
def process_file_download(request, process_id):
    latest_file = ProcessFile.objects.filter(process_id=process_id).order_by('-created_at').first()
    if not latest_file or not latest_file.file:
        return redirect('process:process_edit', pk=process_id)

    return FileResponse(
        latest_file.file.open('rb'),
        as_attachment=True,                  # ← 진짜 다운로드
        filename=latest_file.file.name,
    )


# =====================================================================
# 공정별 약품 / 설비 매핑용 헬퍼
# =====================================================================

def _get_next_order_for_chemical(process):
    max_order = ProcessChemical.objects.filter(process=process).aggregate(
        Max('order')
    )['order__max'] or 0
    return max_order + 1


def _get_next_order_for_equipment(process):
    max_order = ProcessEquipment.objects.filter(process=process).aggregate(
        Max('order')
    )['order__max'] or 0
    return max_order + 1


# =====================================================================
# 공정별 약품 매핑 (AJAX)
# =====================================================================

@login_required
def process_chemical_search(request, process_id):
    """공정별 약품 검색 (모달에서 사용)"""
    query = request.GET.get('q', '').strip()

    qs = Chemical.objects.filter(delete_yn='N', use_yn='Y')
    if query:
        qs = qs.filter(
            Q(name__icontains=query) |
            Q(spec__icontains=query)
        )

    qs = qs.order_by('name')[:50]

    mapped_ids = set(
        ProcessChemical.objects.filter(process_id=process_id)
        .values_list('chemical_id', flat=True)
    )

    results = []
    for chem in qs:
        results.append({
            'id': chem.id,
            'name': chem.name,
            'spec': chem.spec or '',
            'mapped': chem.id in mapped_ids,
        })

    return JsonResponse({'results': results})

@login_required
@require_GET
def process_nonferrous_search(request, pk):
    """
    공정별 비철 검색 (모달에서 사용)
    - GET /process/<pk>/nonferrous/search/?q=...
    - nonferrous.Chemical 목록을 리턴하고,
      이미 매핑된 비철은 is_mapped = True 로 표시
    """
    process = get_object_or_404(Process, pk=pk)

    q = request.GET.get("q", "").strip()

    qs = NonferrousChemical.objects.all()
    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(spec__icontains=q)
        )

    # 너무 많아지지 않게 50개 제한 (필요시 조정)
    qs = qs.order_by("name")[:50]

    # 이미 공정에 매핑된 비철 id 세트
    mapped_ids = set(
        ProcessNonFerrous.objects.filter(process=process)
        .values_list("nonferrous_id", flat=True)
    )

    results = []
    for nf in qs:
        results.append(
            {
                "id": nf.id,
                "name": nf.name,
                "spec": getattr(nf, "spec", "") or "",
                "is_mapped": nf.id in mapped_ids,
            }
        )

    return JsonResponse({"results": results})

@login_required
@require_POST
def process_chemical_add(request, process_id):
    """공정에 약품 추가 (AJAX)"""
    process = get_object_or_404(Process, pk=process_id)
    chemical_id = request.POST.get('chemical_id')

    if not chemical_id:
        return JsonResponse(
            {'result': 'error', 'message': '약품 ID가 전달되지 않았습니다.'},
            status=400,
        )

    chemical = get_object_or_404(
        Chemical,
        pk=chemical_id,
        delete_yn='N',
        use_yn='Y',
    )

    # 이미 매핑되어 있으면 에러 반환
    if ProcessChemical.objects.filter(process=process, chemical=chemical).exists():
        return JsonResponse(
            {'result': 'error', 'message': '이미 등록된 약품입니다.'},
            status=400,
        )

    order = _get_next_order_for_chemical(process)

    mapping = ProcessChemical.objects.create(
        process=process,
        chemical=chemical,
        order=order,
    )

    return JsonResponse({
        'result': 'ok',
        'id': mapping.id,
        'name': chemical.name,
        'spec': chemical.spec or '',
        'order': mapping.order,
    })


@login_required
@require_POST
def process_chemical_delete(request, process_id, mapping_id):
    """공정-약품 매핑 삭제 (AJAX)"""
    mapping = get_object_or_404(
        ProcessChemical,
        pk=mapping_id,
        process_id=process_id,
    )
    mapping.delete()
    return JsonResponse({'result': 'ok'})


# =====================================================================
# 공정별 설비 매핑 (AJAX)
# =====================================================================

@login_required
def process_equipment_search(request, process_id):
    """공정별 설비 검색 (모달에서 사용)"""
    query = request.GET.get('q', '').strip()

    qs = Equipment.objects.all()
    if query:
        qs = qs.filter(
            Q(name__icontains=query) |
            Q(spec__icontains=query) |
            Q(equipment_code__icontains=query)
        )

    qs = qs.order_by('name')[:50]

    mapped_ids = set(
        ProcessEquipment.objects.filter(process_id=process_id)
        .values_list('equipment_id', flat=True)
    )

    results = []
    for eq in qs:
        results.append({
            'id': eq.id,
            'name': eq.name,
            'spec': eq.spec,
            'equipment_code': eq.equipment_code,
            'mapped': eq.id in mapped_ids,
        })

    return JsonResponse({'results': results})


@login_required
@require_POST
def process_equipment_add(request, process_id):
    """공정에 설비 추가 (AJAX)"""
    process = get_object_or_404(Process, pk=process_id)
    equipment_id = request.POST.get('equipment_id')

    if not equipment_id:
        return JsonResponse(
            {'result': 'error', 'message': '설비 ID가 전달되지 않았습니다.'},
            status=400,
        )

    equipment = get_object_or_404(Equipment, pk=equipment_id)

    if ProcessEquipment.objects.filter(process=process, equipment=equipment).exists():
        return JsonResponse(
            {'result': 'error', 'message': '이미 등록된 설비입니다.'},
            status=400,
        )

    order = _get_next_order_for_equipment(process)

    mapping = ProcessEquipment.objects.create(
        process=process,
        equipment=equipment,
        order=order,
    )

    return JsonResponse({
        'result': 'ok',
        'id': mapping.id,
        'name': equipment.name,
        'spec': equipment.spec,
        'equipment_code': equipment.equipment_code,
        'order': mapping.order,
    })


@login_required
@require_GET
def process_nonferrous_search(request, process_id):
    """
    공정별 비철 검색 (모달에서 사용)
    GET /process/<process_id>/nonferrous/search/?q=...
    """
    process = get_object_or_404(Process, pk=process_id)

    q = request.GET.get("q", "").strip()

    qs = NonferrousChemical.objects.all()
    if q:
        qs = qs.filter(
            Q(name__icontains=q) |
            Q(spec__icontains=q)
        )

    qs = qs.order_by("name")[:50]

    # 이미 매핑된 비철 ID 집합
    mapped_ids = set(
        ProcessNonFerrous.objects
        .filter(process=process)
        .values_list("nonferrous_id", flat=True)
    )

    results = []
    for nf in qs:
        results.append({
            "id": nf.id,
            "name": nf.name,
            "spec": getattr(nf, "spec", "") or "",
            "mapped": nf.id in mapped_ids,   # JS 에서 item.mapped 로 사용
        })

    return JsonResponse({"results": results})


@login_required
@require_POST
def process_nonferrous_add(request, process_id):
    """
    공정에 비철 추가 (모달에서 '선택' 클릭)
    POST /process/<process_id>/nonferrous/add/
    """
    process = get_object_or_404(Process, pk=process_id)
    nonferrous_id = request.POST.get("nonferrous_id")

    if not nonferrous_id:
        return JsonResponse({"result": "error", "message": "비철 ID가 없습니다."})

    nonferrous = get_object_or_404(NonferrousChemical, pk=nonferrous_id)

    # 이미 매핑된 비철이면 에러
    mapping, created = ProcessNonFerrous.objects.get_or_create(
        process=process,
        nonferrous=nonferrous,
        defaults={},
    )
    if not created:
        return JsonResponse({"result": "error", "message": "이미 매핑된 비철입니다."})

    # 표시순번(order) 부여
    max_order = (
        ProcessNonFerrous.objects
        .filter(process=process)
        .aggregate(Max("order"))["order__max"]
    )
    mapping.order = (max_order or 0) + 1
    mapping.save()

    return JsonResponse({
        "result": "ok",
        "id": mapping.id,
        "order": mapping.order,
        "name": nonferrous.name,
        "spec": getattr(nonferrous, "spec", "") or "",
    })


@login_required
@require_POST
def process_nonferrous_delete(request, process_id, mapping_id):
    """
    공정에서 비철 매핑 삭제
    POST /process/<process_id>/nonferrous/<mapping_id>/delete/
    """
    process = get_object_or_404(Process, pk=process_id)
    mapping = get_object_or_404(
        ProcessNonFerrous,
        pk=mapping_id,
        process=process,
    )
    mapping.delete()
    return JsonResponse({"result": "ok"})

@login_required
@require_POST
def process_equipment_delete(request, process_id, mapping_id):
    process = get_object_or_404(Process, pk=process_id)
    mapping = get_object_or_404(
        ProcessEquipment,
        pk=mapping_id,
        process=process,
    )
    mapping.delete()
    return JsonResponse({"result": "ok"})