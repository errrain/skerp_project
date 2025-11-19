# production/nfadd/views.py

from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from ..models import NonFerrousAddition, NonFerrousAdditionLine
from ..forms import NonFerrousAdditionForm, NonFerrousAdditionLineFormSet

from process.models import Process, ProcessNonFerrous
from django.contrib import messages


# ============================================================
#  비철 투입일지 목록
#   - /production/nfadd/
#   - 공정별 필터, 일자 필터(선택)
# ============================================================
@login_required
def nfadd_list(request):
    qs = (
        NonFerrousAddition.objects
        .select_related("process", "created_by")
        .filter(is_active=True, dlt_yn="N")
        .order_by("-work_date", "-id")
    )

    process_id = request.GET.get("process")
    work_date_str = request.GET.get("work_date")

    # 공정 필터
    if process_id:
        try:
            qs = qs.filter(process_id=int(process_id))
        except ValueError:
            pass

    # 일자 필터 (YYYY-MM-DD 형식 가정)
    if work_date_str:
        try:
            year, month, day = map(int, work_date_str.split("-"))
            qs = qs.filter(work_date=date(year, month, day))
        except Exception:
            # 형식 이상하면 그냥 무시
            pass

    paginator = Paginator(qs, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # 공정 드롭다운용
    processes = Process.objects.all().order_by("display_order", "id")

    context = {
        "page_obj": page_obj,
        "additions": page_obj,  # 템플릿에서 for row in additions 로 써도 되게
        "processes": processes,
        "selected_process_id": process_id,
        "work_date": work_date_str,
    }
    return render(request, "production/nfadd/nfadd_list.html", context)


# ============================================================
#  비철 투입일지 신규 등록
#   - /production/nfadd/create/?process=<id>
#   - process에 매핑된 ProcessNonFerrous 기준으로 라인 initial 생성
# ============================================================
@login_required
def nfadd_create(request):
    """
    비철 투입일지 신규 등록
    - GET : 공정에 매핑된 ProcessNonFerrous 기준으로 라인 초기 생성
    - POST : 헤더 + 라인 저장 후 edit 화면으로 이동
    디버그용: 공정 선택 시 매핑 조회 쿼리/결과를 runserver 콘솔에 출력
    """

    # 디버그용: 언제 호출되는지 먼저 찍기
    print("=== [nfadd_create] method:", request.method, "process param:", request.GET.get("process"))

    process_id = request.GET.get("process")
    initial_header = {"work_date": date.today()}

    # 공정 선택되어 있으면 헤더 초기값에 반영
    if process_id:
        try:
            initial_header["process"] = int(process_id)
        except (TypeError, ValueError):
            print("=== [nfadd_create] invalid process_id in GET:", process_id)

    # ---------------- POST : 저장 처리 ----------------
    if request.method == "POST":
        form = NonFerrousAdditionForm(request.POST)
        formset = NonFerrousAdditionLineFormSet(
            request.POST,
            prefix="lines",
        )

        if form.is_valid() and formset.is_valid():
            addition = form.save(commit=False)
            addition.created_by = request.user
            addition.save()

            formset.instance = addition
            formset.save()

            messages.success(request, "비철 투입 정보가 저장되었습니다.")
            print("=== [nfadd_create] saved addition pk:", addition.pk)
            return redirect("production:nfadd:nfadd_edit", pk=addition.pk)
        else:
            print("=== [nfadd_create] POST invalid")
            print("  form errors:", form.errors)
            print("  formset errors:", formset.errors)

    # ---------------- GET : 신규 입력 화면 ----------------
    else:
        form = NonFerrousAdditionForm(initial=initial_header)

        initial_lines = []

        if process_id:
            try:
                process_obj = Process.objects.get(pk=int(process_id))
            except (Process.DoesNotExist, TypeError, ValueError):
                process_obj = None
                print("=== [nfadd_create] Process not found for id:", process_id)
            else:
                print("=== [nfadd_create] Process loaded:",
                      process_obj.pk, getattr(process_obj, "name", ""))

            if process_obj is not None:
                # 🔥 여기서 실제로 어떤 SELECT가 나가는지를 출력
                qs = (
                    ProcessNonFerrous.objects
                    .select_related("nonferrous")
                    .filter(process=process_obj)
                    .order_by("order", "id")
                )

                # SQL 그대로 출력
                print("=== [nfadd_create] ProcessNonFerrous queryset SQL ===")
                print(qs.query)

                # 실제로 데이터를 한 번 리스트로 뽑아서 개수/내용도 출력
                mappings = list(qs)
                print("=== [nfadd_create] mappings count:", len(mappings))
                for m in mappings:
                    nf = getattr(m, "nonferrous", None)
                    print(
                        "    mapping row -> id:",
                        m.pk,
                        "nonferrous_id:",
                        getattr(m, "nonferrous_id", None),
                        "nonferrous_name:",
                        getattr(nf, "name", None),
                    )

                # 화면 초기 라인 생성
                for m in mappings:
                    nf = getattr(m, "nonferrous", None)
                    if nf is None:
                        continue

                    initial_lines.append(
                        {
                            "nonferrous": nf.pk,
                            "nonferrous_label": getattr(nf, "name", str(nf)),
                        }
                    )
        else:
            print("=== [nfadd_create] no process_id in GET")

        formset = NonFerrousAdditionLineFormSet(
            prefix="lines",
            initial=initial_lines,
        )

    context = {
        "form": form,
        "formset": formset,
        "object": None,  # 신규/수정 구분용
    }
    return render(request, "production/nfadd/nfadd_form.html", context)


# ============================================================
#  비철 투입일지 수정
#   - /production/nfadd/<pk>/edit/
# ============================================================
@login_required
def nfadd_edit(request, pk):
    """비철 투입일지 수정"""
    addition = get_object_or_404(NonFerrousAddition, pk=pk)

    if request.method == "POST":
        form = NonFerrousAdditionForm(request.POST, instance=addition)
        formset = NonFerrousAdditionLineFormSet(
            request.POST,
            prefix="lines",
            instance=addition,
        )

        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()

            # ✅ 수정 성공 메시지
            messages.success(request, "비철 투입 정보가 저장되었습니다.")

            # PRG 패턴: 새로고침 시 중복 POST 방지
            return redirect("production:nfadd:nfadd_edit", pk=addition.pk)
    else:
        form = NonFerrousAdditionForm(instance=addition)
        formset = NonFerrousAdditionLineFormSet(
            prefix="lines",
            instance=addition,
        )

    context = {
        "form": form,
        "formset": formset,
        "object": addition,
    }
    return render(request, "production/nfadd/nfadd_form.html", context)


# ============================================================
#  비철 투입일지 삭제
#   - /production/nfadd/<pk>/delete/
#   - 지금은 하드 delete, 필요시 soft delete 로 변경
# ============================================================
@login_required
def nfadd_delete(request, pk):
    addition = get_object_or_404(NonFerrousAddition, pk=pk)

    if request.method == "POST":
        addition.delete()
        return redirect("production:nfadd:nfadd_list")

    # GET 으로 직접 들어오면 목록으로 돌려보냄
    return redirect("production:nfadd:nfadd_list")
