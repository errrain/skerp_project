from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from .models import Injection, InjectionPrice, MoldHistory
from .forms import InjectionForm, InjectionPriceForm, MoldHistoryForm
from django.core.paginator import Paginator
from django.db.models import Q


# 🔁 공통 저장 처리
def save_form(request, form, template_name, redirect_url, instance=None, extra_context=None):
    if request.method == 'POST':
        if form.is_valid():
            obj = form.save(commit=False)
            if not instance:
                obj.created_by = request.user
                if not obj.delete_yn:
                    obj.delete_yn = 'N'
                if not obj.use_yn:
                    obj.use_yn = 'Y'
            obj.updated_by = request.user
            obj.save()
            return redirect(redirect_url)
        else:
            print("❌ 폼 유효성 검사 실패")
            print(form.errors.as_data())

    context = {'form': form}
    if instance:
        context['injection'] = instance
    if extra_context:
        context.update(extra_context)
    return render(request, template_name, context)


# 목록
@login_required
def injection_list(request):
    query = request.GET.get('q', '')
    status = request.GET.get('status', '')
    vendor = request.GET.get('vendor', '')

    injections = Injection.objects.filter(delete_yn='N')

    if query:
        injections = injections.filter(Q(name__icontains=query) | Q(alias__icontains=query) | Q(spec__icontains=query))

    if status:
        injections = injections.filter(status=status)

    if vendor:
        injections = injections.filter(vendor__name__icontains=vendor)

    paginator = Paginator(injections.order_by('-id'), 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'injection/injection_list.html', {
        'page_obj': page_obj,
        'query': query,
        'status': status,
        'vendor': vendor,
    })


# 등록
@login_required
def injection_add(request):
    form = InjectionForm(request.POST or None, request.FILES or None)
    return save_form(request, form, 'injection/injection_form.html', 'injection:injection_list')


# 수정
@login_required
def injection_edit(request, pk):
    injection = get_object_or_404(Injection, pk=pk)
    form = InjectionForm(request.POST or None, request.FILES or None, instance=injection)
    return save_form(request, form, 'injection/injection_form.html', 'injection:injection_list', instance=injection)


# 삭제 (논리 삭제)
@login_required
def injection_delete(request, pk):
    injection = get_object_or_404(Injection, pk=pk)
    injection.delete_yn = 'Y'
    injection.save()
    return redirect('injection:injection_list')


# 💰 단가 탭
@login_required
def injection_price_view(request, pk):
    injection = get_object_or_404(Injection, pk=pk)
    latest_price = injection.prices.first()
    price_list = injection.prices.all()

    if request.method == 'POST':
        form = InjectionPriceForm(request.POST)
        if form.is_valid():
            price = form.save(commit=False)
            price.injection = injection
            price.created_by = request.user
            price.created_at = timezone.now()
            price.save()
            return redirect('injection:injection_price', pk=pk)
    else:
        form = InjectionPriceForm()

    return render(request, 'injection/injection_price.html', {
        'injection': injection,
        'form': form,
        'latest_price': latest_price,
        'price_list': price_list,
    })


# 🧰 금형이력 탭
@login_required
def mold_history_view(request, pk):
    injection = get_object_or_404(Injection, pk=pk)
    mold_list = injection.mold_histories.all()

    if request.method == 'POST':
        form = MoldHistoryForm(request.POST)
        if form.is_valid():
            mold = form.save(commit=False)
            mold.injection = injection
            mold.created_by = request.user
            mold.created_at = timezone.now()
            mold.save()
            return redirect('injection:mold_history', pk=pk)
    else:
        form = MoldHistoryForm()

    return render(request, 'injection/mold_history.html', {
        'injection': injection,
        'form': form,
        'mold_list': mold_list,
    })
