from django.shortcuts import render, get_object_or_404, redirect
from .models import Chemical
from .forms import ChemicalForm
from django.core.paginator import Paginator
from .forms import ChemicalPriceForm
from django.utils import timezone

from django.db.models import Q


def nonferrous_list(request):
    search_name = request.GET.get('name', '')
    search_spec = request.GET.get('spec', '')
    search_customer = request.GET.get('customer', '')

    nonferrous_qs = Chemical.objects.filter(delete_yn='N')

    if search_name:
        nonferrous_qs = nonferrous_qs.filter(name__icontains=search_name)
    if search_spec:
        nonferrous_qs = nonferrous_qs.filter(spec__icontains=search_spec)
    if search_customer:
        nonferrous_qs = nonferrous_qs.filter(customer__name__icontains=search_customer)

    paginator = Paginator(nonferrous_qs.order_by('-id'), 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'name': search_name,
        'spec': search_spec,
        'customer': search_customer,
    }
    return render(request, 'nonferrous/nonferrous_list.html', context)


def nonferrous_add(request):
    if request.method == 'POST':
        form = ChemicalForm(request.POST, request.FILES)
        if form.is_valid():
            chem = form.save(commit=False)
            chem.created_by = request.user.username
            chem.updated_by = request.user.username
            chem.save()
            return redirect('nonferrous:nonferrous_list')
    else:
        form = ChemicalForm()
    return render(request, 'nonferrous/nonferrous_form.html', {'form': form})


def nonferrous_edit(request, pk):
    chem = get_object_or_404(Chemical, pk=pk)
    if request.method == 'POST':
        form = ChemicalForm(request.POST, request.FILES, instance=chem)
        if form.is_valid():
            chem = form.save(commit=False)
            chem.updated_by = request.user.username
            chem.save()
            return redirect('nonferrous:nonferrous_list')
    else:
        form = ChemicalForm(instance=chem)
    return render(request, 'nonferrous/nonferrous_form.html', {'form': form})


def nonferrous_delete(request, pk):
    chem = get_object_or_404(Chemical, pk=pk)
    if request.method == 'POST':
        chem.delete_yn = 'Y'
        chem.save()
        return redirect('nonferrous:nonferrous_list')
    return render(request, 'nonferrous/nonferrous_confirm_delete.html', {'nonferrous': chem})

def nonferrous_price_view(request, pk):
    nonferrous = get_object_or_404(Chemical, pk=pk)

    if not nonferrous.id:
        messages.warning(request, "약품을 먼저 등록완료하세요.")
        return redirect('nonferrous:nonferrous_list')

    latest_price = nonferrous.prices.first()

    if request.method == 'POST':
        form = ChemicalPriceForm(request.POST)
        if form.is_valid():
            price = form.save(commit=False)
            price.nonferrous = nonferrous
            price.created_by = request.user.username
            price.save()
            return redirect('nonferrous:nonferrous_price', pk=nonferrous.pk)
    else:
        form = ChemicalPriceForm(initial={
            'date': timezone.now().strftime('%Y-%m-%dT%H:%M')
        })

    context = {
        'nonferrous': nonferrous,
        'latest_price': latest_price,
        'price_list': nonferrous.prices.all(),
        'form': form,
    }
    return render(request, 'nonferrous/nonferrous_price.html', context)