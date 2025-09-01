from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST

from .models import RackMaster
from .forms import RackMasterForm

# RACK MASTER 리스트
def rack_master_list(request):
    queryset = RackMaster.objects.filter(dlt_yn='N').order_by('rack_master_id')
    keyword = request.GET.get('q', '')
    if keyword:
        queryset = queryset.filter(product_nm__icontains=keyword)

    paginator = Paginator(queryset, 20)
    page = request.GET.get('page')
    page_obj = paginator.get_page(page)

    context = {
        'page_obj': page_obj,
        'q': keyword,
    }
    return render(request, 'rack/rack_list.html', context)


# 신규 RACK MASTER 등록
def rack_master_add(request):
    if request.method == 'POST':
        form = RackMasterForm(request.POST, request.FILES)
        if form.is_valid():
            rack_master = form.save(commit=False)

            # rack_master_id 자동 생성
            last = RackMaster.objects.order_by('-id').first()
            next_no = 1 if not last else int(last.rack_master_id.replace("SKRA", "")) + 1
            rack_master.rack_master_id = f"SKRA{next_no:03d}"

            rack_master.save()
            return redirect('rack:rack_master_list')
    else:
        form = RackMasterForm()

    return render(request, 'rack/rack_master_form.html', {'form': form})


# RACK MASTER 상세(수정 포함)
def rack_master_detail(request, rack_master_id):
    rack = get_object_or_404(RackMaster, rack_master_id=rack_master_id)

    if request.method == 'POST':
        form = RackMasterForm(request.POST, request.FILES, instance=rack)
        if form.is_valid():
            form.save()
            # redirect 없이 본 페이지 유지
            # 메시지 또는 저장 완료 알림은 템플릿에서 처리
    else:
        form = RackMasterForm(instance=rack)

    context = {
        'rack': rack,
        'form': form,
        # TODO: 하위 RACK 리스트 및 상태 요약 데이터 추가 예정
    }
    return render(request, 'rack/rack_master_detail.html', context)


@require_POST
def rack_master_image_delete(request, rack_master_id):
    rack = get_object_or_404(RackMaster, rack_master_id=rack_master_id)
    if rack.image:
        rack.image.delete(save=False)
        rack.image = None
        rack.save()
    return redirect('rack:rack_master_detail', rack_master_id=rack_master_id)

# RACK 상세 등록 (하위 랙)
def rack_detail_add(request, rack_master_id):
    return HttpResponse("rack_detail_add - 구현 예정")


# RACK 상세 수정
def rack_detail_edit(request, pk):
    return HttpResponse("rack_detail_edit - 구현 예정")


# RACK 상세 삭제
def rack_detail_delete(request, pk):
    return HttpResponse("rack_detail_delete - 구현 예정")
