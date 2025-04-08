from django.shortcuts import render, get_object_or_404, redirect
from .models import Chemical
from .forms import ChemicalForm
from django.core.paginator import Paginator
from .forms import ChemicalPriceForm
from django.utils import timezone

from django.db.models import Q


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

    paginator = Paginator(chemical_qs.order_by('-id'), 10)
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