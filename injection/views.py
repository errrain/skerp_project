from django.http import HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone
from .models import Injection
from .forms import InjectionForm, MoldHistoryForm
from .forms import InjectionPriceForm


def injection_list(request):
    # ✅ 검색 조건 수집
    name = request.GET.get('name', '')
    program_name = request.GET.get('program_name', '')
    status = request.GET.get('status', '')
    alias = request.GET.get('alias', '')
    weight = request.GET.get('weight', '')
    vendor = request.GET.get('vendor', '')

    # ✅ 기본 쿼리셋
    queryset = Injection.objects.all()

    # ✅ 조건별 필터링
    if name:
        queryset = queryset.filter(name__icontains=name)
    if program_name:
        queryset = queryset.filter(program_name__icontains=program_name)
    if status:
        queryset = queryset.filter(status=status)
    if alias:
        queryset = queryset.filter(alias__icontains=alias)
    if weight:
        queryset = queryset.filter(weight__icontains=weight)
    if vendor:
        queryset = queryset.filter(vendor__name__icontains=vendor)

    # ✅ 정렬 및 페이징
    queryset = queryset.order_by('-id')
    paginator = Paginator(queryset, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # ✅ 템플릿 전달
    context = {
        'page_obj': page_obj,
    }
    return render(request, 'injection/injection_list.html', context)

def injection_create(request):
    if request.method == 'POST':
        form = InjectionForm(request.POST, request.FILES)
        if form.is_valid():
            injection = form.save(commit=False)
            injection.created_by = request.user.username
            injection.updated_by = request.user.username
            injection.save()
            return redirect('injection:injection_list')
        else:
            print("🛑 [injection_create] 유효성 검사 실패:")
            print(form.errors)  # 👈 콘솔에 상세 에러 출력
    else:
        form = InjectionForm()
    return render(request, 'injection/injection_form.html', {'form': form})

def injection_update(request, pk):
    injection = get_object_or_404(Injection, pk=pk)
    if request.method == 'POST':
        form = InjectionForm(request.POST, request.FILES, instance=injection)
        if form.is_valid():
            injection = form.save(commit=False)
            injection.updated_by = request.user.username
            injection.save()
            return redirect('injection:injection_list')
        else:
            print("🛑 [injection_update] 유효성 검사 실패:")
            print(form.errors)
    else:
        form = InjectionForm(instance=injection)
    return render(request, 'injection/injection_form.html', {'form': form, 'edit_mode': True})

def injection_delete(request, pk):
    injection = get_object_or_404(Injection, pk=pk)
    if request.method == 'POST':
        injection.delete()
        return redirect('injection:injection_list')
    return render(request, 'injection/injection_confirm_delete.html', {'object': injection})

def mold_history(request, pk):
    return HttpResponse(f"[임시화면] 금형이력 페이지: ID={pk}")

def injection_price(request, pk):
    return HttpResponse(f"[임시화면] 단가정보 페이지: ID={pk}")

def injection_price(request, pk):
    injection = get_object_or_404(Injection, pk=pk)

    if not injection.id:
        messages.warning(request, "사출품을 먼저 등록완료하세요.")
        return redirect('injection:injection_list')

    latest_price = injection.prices.first()

    if request.method == 'POST':
        form = InjectionPriceForm(request.POST)
        if form.is_valid():
            price = form.save(commit=False)
            price.injection = injection
            price.created_by = request.user.username
            price.save()
            return redirect('injection:injection_price', pk=injection.pk)
    else:
        form = InjectionPriceForm(initial={
            'date': timezone.now().strftime('%Y-%m-%dT%H:%M')
        })

    context = {
        'injection': injection,
        'latest_price': latest_price,
        'price_list': injection.prices.all(),
        'form': form,
    }
    return render(request, 'injection/injection_price.html', context)

def mold_history(request, pk):
    injection = get_object_or_404(Injection, pk=pk)

    if request.method == 'POST':
        form = MoldHistoryForm(request.POST)
        if form.is_valid():
            history = form.save(commit=False)
            history.injection = injection
            history.created_by = request.user.username
            history.save()
            return redirect('injection:mold_history', pk=pk)
    else:
        form = MoldHistoryForm()

    context = {
        'injection': injection,
        'form': form,
        'mold_list': injection.molds.all(),
    }
    return render(request, 'injection/mold_history.html', context)