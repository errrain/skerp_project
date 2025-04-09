from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator
from django.db.models import Q
from .models import Injection
from .forms import InjectionForm

def injection_list(request):
    query = request.GET.get('q', '')
    queryset = Injection.objects.all()

    if query:
        queryset = queryset.filter(
            Q(name__icontains=query) |
            Q(program_name__icontains=query) |
            Q(status__icontains=query) |
            Q(alias__icontains=query)
        )

    paginator = Paginator(queryset.order_by('-id'), 10)  # 페이지당 10개
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'query': query,
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
        form = InjectionForm(instance=injection)
    return render(request, 'injection/injection_form.html', {'form': form, 'edit_mode': True})

def injection_delete(request, pk):
    injection = get_object_or_404(Injection, pk=pk)
    if request.method == 'POST':
        injection.delete()
        return redirect('injection:injection_list')
    return render(request, 'injection/injection_confirm_delete.html', {'object': injection})
