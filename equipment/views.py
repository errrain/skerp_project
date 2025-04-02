
from django.core.paginator import Paginator
from django.shortcuts import render, get_object_or_404, redirect
from .models import Equipment, EquipmentHistory
from .forms import EquipmentForm, EquipmentHistoryForm

def equipment_list(request):
    name = request.GET.get('name', '')
    code = request.GET.get('code', '')
    page_size = request.GET.get('page_size', 10)

    equipments = Equipment.objects.all()
    if name:
        equipments = equipments.filter(name__icontains=name)
    if code:
        equipments = equipments.filter(equipment_code__icontains=code)

    paginator = Paginator(equipments, page_size)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'name': name,
        'code': code,
        'page_size': int(page_size),
    }
    return render(request, 'equipment/equipment_list.html', context)

def equipment_add(request):
    if request.method == 'POST':
        form = EquipmentForm(request.POST, request.FILES)
        if form.is_valid():
            equipment = form.save()
            return redirect('equipment:equipment_list')
    else:
        form = EquipmentForm()
    return render(request, 'equipment/equipment_form.html', {'form': form})

def equipment_edit(request, pk):
    equipment = get_object_or_404(Equipment, pk=pk)
    histories = equipment.histories.all().order_by('-created_at')

    form = EquipmentForm(instance=equipment)
    history_form = EquipmentHistoryForm()

    if request.method == 'POST':
        if 'save_equipment' in request.POST:
            form = EquipmentForm(request.POST, request.FILES, instance=equipment)
            if form.is_valid():
                form.save()
                return redirect('equipment:equipment_edit', pk=equipment.pk)

        elif 'save_history' in request.POST:
            history_form = EquipmentHistoryForm(request.POST)
            if history_form.is_valid():
                history = history_form.save(commit=False)
                history.equipment = equipment
                history.created_by = request.user.username
                history.save()
                return redirect('equipment:equipment_edit', pk=equipment.pk)

        elif 'update_history' in request.POST:
            history_id = request.POST.get('history_id')
            history = get_object_or_404(EquipmentHistory, pk=history_id, equipment=equipment)
            history.content = request.POST.get('content', '')
            history.save()
            return redirect('equipment:equipment_edit', pk=equipment.pk)

        elif 'delete_history' in request.POST:
            history_id = request.POST.get('history_id')
            history = get_object_or_404(EquipmentHistory, pk=history_id, equipment=equipment)
            history.delete()
            return redirect('equipment:equipment_edit', pk=equipment.pk)

    return render(request, 'equipment/equipment_form.html', {
        'form': form,
        'history_form': history_form,
        'histories': histories,
    })

def equipment_delete(request, pk):
    equipment = get_object_or_404(Equipment, pk=pk)
    equipment.delete()
    return redirect('equipment:equipment_list')
