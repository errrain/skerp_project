# purchase/services.py
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import List, Dict, Optional, Tuple

from django.db import transaction, IntegrityError
from django.db.models import Sum
from django.utils import timezone
from django.core.exceptions import ValidationError

from .models import (
    UnifiedReceipt,
    UnifiedReceiptLine,
    UnifiedUsage,
    # 사출(Injection) 관련이 필요해지면 아래 주석 해제
    # InjectionReceiptLine,
    # InjectionUsage,
)

# ======================================================================
# 공통 유틸
# ======================================================================

_ZERO = Decimal("0")


def _dec(v) -> Decimal:
    """숫자를 Decimal로 안전 변환."""
    if isinstance(v, Decimal):
        return v
    if v is None:
        return _ZERO
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError("수량 형식이 올바르지 않습니다.")


def _coerce_qty(qty) -> Decimal:
    """수량 입력값 정규화(양수, 소수 3자리 반올림)."""
    d = _dec(qty)
    if d <= _ZERO:
        raise ValidationError("수량은 0보다 커야 합니다.")
    return d.quantize(Decimal("0.001"))


def _coerce_delta(delta) -> Decimal:
    """조정값(±) 정규화(0 불가, 소수 3자리)."""
    d = _dec(delta)
    if d == _ZERO:
        raise ValidationError("조정값은 0이 될 수 없습니다.")
    return d.quantize(Decimal("0.001"))


def _status_by(qty: Decimal, used: Decimal) -> str:
    """상태 문자열 계산(모델 save()의 자동 전이 로직과 동일한 기준)."""
    if used <= _ZERO:
        return "미사용"
    if used >= qty:
        return "사용완료"
    return "부분사용"

def ensure_vendor_scope(user, vendor_id: int) -> bool:
    """
    접근 정책:
      - 내부 사용자(is_internal=True): 모든 vendor OK
      - 외부 사용자: 본인 vendor 만 허용
    """
    is_internal = getattr(user, "is_internal", False)
    if is_internal:
        return True

    user_vendor_id = getattr(getattr(user, "vendor", None), "id", None)
    return bool(user_vendor_id and int(user_vendor_id) == int(vendor_id))

# ======================================================================
# 내부 조회/락/멱등
# ======================================================================

def _get_locked_line(line_id: int) -> UnifiedReceiptLine:
    """
    UnifiedReceiptLine 행을 행잠금으로 가져온다(CHEM만 허용).
    """
    line = (
        UnifiedReceiptLine.objects
        .select_for_update()
        .select_related("receipt")
        .get(pk=line_id)
    )
    if line.receipt.category != "CHEM":
        raise ValidationError("CHEM 항목만 라인 단위 처리가 가능합니다.")
    return line


def _get_locked_receipt(receipt_id: int) -> UnifiedReceipt:
    """UnifiedReceipt를 행잠금으로 가져온다."""
    return UnifiedReceipt.objects.select_for_update().get(pk=receipt_id)


def _ensure_txid_unused(txid: str):
    """
    멱등키(transaction_uid) 중복 방지.
    이미 존재하면 재요청으로 판단해 ValidationError 발생.
    """
    if UnifiedUsage.objects.filter(transaction_uid=txid).exists():
        raise ValidationError("이미 처리된 요청입니다(transaction_uid 중복).")


def _create_usage(
    *,
    receipt: UnifiedReceipt,
    action: UnifiedUsage.Action,
    qty_change: Decimal,
    user,
    txid: str,
    line: Optional[UnifiedReceiptLine] = None,
    ref_type: str = "",
    ref_id: str = "",
    note: str = "",
):
    """
    UnifiedUsage 생성(멱등키 포함).
    모델의 clean()에서 부호 일관성 검증이 수행된다.
    """
    try:
        return UnifiedUsage.objects.create(
            receipt=receipt,
            line=line,
            action=action,
            qty_change=qty_change,
            occurred_at=timezone.now(),
            recorded_by=user,
            ref_type=ref_type or "",
            ref_id=ref_id or "",
            note=note or "",
            transaction_uid=txid,
        )
    except IntegrityError:
        # transaction_uid 유니크 충돌
        raise ValidationError("이미 처리된 요청입니다(transaction_uid 중복).")


# ======================================================================
# 헤더 집계 동기화(CHEM 전용: 라인 합산 → 헤더 반영)
# ======================================================================

def _sync_unified_header_from_lines(receipt_id: int) -> Tuple[Decimal, Decimal, str]:
    """
    CHEM 헤더를 라인 합계로 동기화.
    - used_qty = SUM(line.used_qty)
    - qty      = SUM(line.qty) (정합성 유지 목적)
    - use_status는 모델 save()에서 자동 전이.
    """
    receipt = _get_locked_receipt(receipt_id)
    agg = UnifiedReceiptLine.objects.filter(receipt_id=receipt_id).aggregate(
        sum_qty=Sum("qty"),
        sum_used=Sum("used_qty"),
    )
    sum_qty = _dec(agg["sum_qty"])
    sum_used = _dec(agg["sum_used"])

    # 경계 보정
    if sum_used < _ZERO:
        sum_used = _ZERO
    if sum_used > sum_qty:
        sum_used = sum_qty

    # 헤더 갱신
    receipt.qty = sum_qty
    receipt.used_qty = sum_used
    receipt.save(update_fields=["qty", "used_qty", "use_status"])

    return sum_qty, sum_used, receipt.use_status


# ======================================================================
# CHEM: 라인 단위 사용/반납/조정
# ======================================================================

@transaction.atomic
def consume_chem_line(
    line_id: int,
    qty,
    *,
    user,
    transaction_uid: str,
    ref_type: str = "",
    ref_id: str = "",
    note: str = "",
) -> Dict:
    """
    CHEM: 서브 LOT 라인 소비.
    - qty > 0
    - used_qty + qty <= qty
    """
    qty = _coerce_qty(qty)
    line = _get_locked_line(line_id)
    receipt = line.receipt

    _ensure_txid_unused(transaction_uid)

    cur_used = _dec(line.used_qty)
    capacity = _dec(line.qty) - cur_used
    if qty > capacity:
        raise ValidationError(f"요청 수량({qty})이 잔여 가능({capacity})을 초과합니다.")

    # 이력 기록(양수)
    _create_usage(
        receipt=receipt,
        line=line,
        action=UnifiedUsage.Action.CONSUME,
        qty_change=qty,
        user=user,
        txid=transaction_uid,
        ref_type=ref_type,
        ref_id=ref_id,
        note=note,
    )

    # 라인 반영
    line.used_qty = (cur_used + qty).quantize(Decimal("0.001"))
    line.save(update_fields=["used_qty", "use_status"])

    # 헤더 동기화
    sum_qty, sum_used, hdr_status = _sync_unified_header_from_lines(receipt.id)

    return {
        "ok": True,
        "line_id": line.id,
        "line_used_qty": str(line.used_qty),
        "line_status": line.use_status,
        "receipt_id": receipt.id,
        "receipt_qty": str(sum_qty),
        "receipt_used_qty": str(sum_used),
        "receipt_status": hdr_status,
    }


@transaction.atomic
def return_chem_line(
    line_id: int,
    qty,
    *,
    user,
    transaction_uid: str,
    ref_type: str = "",
    ref_id: str = "",
    note: str = "",
) -> Dict:
    """
    CHEM: 서브 LOT 라인 반납.
    - qty > 0
    - used_qty - qty >= 0
    """
    qty = _coerce_qty(qty)
    line = _get_locked_line(line_id)
    receipt = line.receipt

    _ensure_txid_unused(transaction_uid)

    cur_used = _dec(line.used_qty)
    if qty > cur_used:
        raise ValidationError(f"반납 수량({qty})이 현재 사용량({cur_used})을 초과합니다.")

    # 이력 기록(음수)
    _create_usage(
        receipt=receipt,
        line=line,
        action=UnifiedUsage.Action.RETURN,
        qty_change=(qty * Decimal("-1")),
        user=user,
        txid=transaction_uid,
        ref_type=ref_type,
        ref_id=ref_id,
        note=note,
    )

    # 라인 반영
    line.used_qty = (cur_used - qty).quantize(Decimal("0.001"))
    if line.used_qty < _ZERO:
        line.used_qty = _ZERO
    line.save(update_fields=["used_qty", "use_status"])

    # 헤더 동기화
    sum_qty, sum_used, hdr_status = _sync_unified_header_from_lines(receipt.id)

    return {
        "ok": True,
        "line_id": line.id,
        "line_used_qty": str(line.used_qty),
        "line_status": line.use_status,
        "receipt_id": receipt.id,
        "receipt_qty": str(sum_qty),
        "receipt_used_qty": str(sum_used),
        "receipt_status": hdr_status,
    }


@transaction.atomic
def adjust_chem_line(
    line_id: int,
    delta,
    *,
    user,
    transaction_uid: str,
    ref_type: str = "",
    ref_id: str = "",
    note: str = "",
) -> Dict:
    """
    CHEM: 서브 LOT 라인 조정(±).
    - used_qty + delta ∈ [0, qty]
    """
    delta = _coerce_delta(delta)
    line = _get_locked_line(line_id)
    receipt = line.receipt

    _ensure_txid_unused(transaction_uid)

    cur_used = _dec(line.used_qty)
    new_used = (cur_used + delta).quantize(Decimal("0.001"))
    if new_used < _ZERO or new_used > _dec(line.qty):
        raise ValidationError("조정 결과가 허용 범위를 벗어납니다.")

    # 이력 기록(±)
    _create_usage(
        receipt=receipt,
        line=line,
        action=UnifiedUsage.Action.ADJUST,
        qty_change=delta,
        user=user,
        txid=transaction_uid,
        ref_type=ref_type,
        ref_id=ref_id,
        note=note,
    )

    # 라인 반영
    line.used_qty = new_used
    line.save(update_fields=["used_qty", "use_status"])

    # 헤더 동기화
    sum_qty, sum_used, hdr_status = _sync_unified_header_from_lines(receipt.id)

    return {
        "ok": True,
        "line_id": line.id,
        "line_used_qty": str(line.used_qty),
        "line_status": line.use_status,
        "receipt_id": receipt.id,
        "receipt_qty": str(sum_qty),
        "receipt_used_qty": str(sum_used),
        "receipt_status": hdr_status,
    }


# ======================================================================
# CHEM: FIFO 보조(라인 미지정 총량 소비)
# ======================================================================

@transaction.atomic
def consume_chem_fifo(
    receipt_id: int,
    qty_total,
    *,
    user,
    base_transaction_uid: str,
    ref_type: str = "",
    ref_id: str = "",
    note: str = "",
) -> Dict:
    """
    CHEM: FIFO 자동 소비
    - receipt 내 미완료 라인(sub_seq, id 순)부터 잔여를 채움
    - txid는 base_transaction_uid:{증분} 형태로 개별 라인별 멱등 보장
    """
    qty_total = _coerce_qty(qty_total)
    receipt = _get_locked_receipt(receipt_id)
    if receipt.category != "CHEM":
        raise ValidationError("CHEM 항목만 FIFO 소비가 가능합니다.")

    # 라인 잠금 + 사용가능 총량 계산
    lines = list(
        UnifiedReceiptLine.objects
        .select_for_update()
        .filter(receipt_id=receipt_id)
        .order_by("sub_seq", "id")
    )
    total_avail = sum((_dec(l.qty) - _dec(l.used_qty) for l in lines), _ZERO)
    if qty_total > total_avail:
        raise ValidationError(f"요청 수량({qty_total})이 전체 잔여({total_avail})을 초과합니다.")

    remain = qty_total
    moved: List[Tuple[int, Decimal]] = []
    idx = 0

    for line in lines:
        if remain <= _ZERO:
            break
        cap = (_dec(line.qty) - _dec(line.used_qty))
        if cap <= _ZERO:
            continue

        take = cap if cap <= remain else remain
        idx += 1
        txid = f"{base_transaction_uid}:{idx}"

        # 부분 멱등 체크
        if UnifiedUsage.objects.filter(transaction_uid=txid).exists():
            # 이미 처리된 조각 → 논리상 소비된 것으로 간주하고 진행
            remain -= take
            moved.append((line.id, take))
            continue

        # 사용 이력
        _create_usage(
            receipt=receipt,
            line=line,
            action=UnifiedUsage.Action.CONSUME,
            qty_change=take,
            user=user,
            txid=txid,
            ref_type=ref_type,
            ref_id=ref_id,
            note=note,
        )

        # 라인 반영
        line.used_qty = (_dec(line.used_qty) + take).quantize(Decimal("0.001"))
        line.save(update_fields=["used_qty", "use_status"])

        remain -= take
        moved.append((line.id, take))

    # 헤더 동기화
    sum_qty, sum_used, hdr_status = _sync_unified_header_from_lines(receipt.id)

    return {
        "ok": True,
        "receipt_id": receipt.id,
        "filled": [(lid, str(q)) for (lid, q) in moved],
        "remain": str(remain),
        "receipt_qty": str(sum_qty),
        "receipt_used_qty": str(sum_used),
        "receipt_status": hdr_status,
    }


# ======================================================================
# NF/SUP: 헤더 단위 사용/반납/조정
#  - 라인 개념 없음. UnifiedReceipt 자체 used_qty만 관리
# ======================================================================

def _get_locked_unified_receipt_for_header_use(receipt_id: int) -> UnifiedReceipt:
    rc = UnifiedReceipt.objects.select_for_update().get(pk=receipt_id)
    if rc.category not in ("NF", "SUP"):
        raise ValidationError("NF/SUP 항목만 헤더 단위 처리가 가능합니다.")
    return rc


@transaction.atomic
def consume_unified_header(
    receipt_id: int,
    qty,
    *,
    user,
    transaction_uid: str,
    ref_type: str = "",
    ref_id: str = "",
    note: str = "",
) -> Dict:
    qty = _coerce_qty(qty)
    rc = _get_locked_unified_receipt_for_header_use(receipt_id)

    _ensure_txid_unused(transaction_uid)

    cur_used = _dec(rc.used_qty)
    capacity = _dec(rc.qty) - cur_used
    if qty > capacity:
        raise ValidationError(f"요청 수량({qty})이 잔여 가능({capacity})을 초과합니다.")

    _create_usage(
        receipt=rc,
        line=None,
        action=UnifiedUsage.Action.CONSUME,
        qty_change=qty,
        user=user,
        txid=transaction_uid,
        ref_type=ref_type,
        ref_id=ref_id,
        note=note,
    )

    rc.used_qty = (cur_used + qty).quantize(Decimal("0.001"))
    rc.save(update_fields=["used_qty", "use_status"])

    return {
        "ok": True,
        "receipt_id": rc.id,
        "receipt_qty": str(_dec(rc.qty)),
        "receipt_used_qty": str(_dec(rc.used_qty)),
        "receipt_status": rc.use_status,
    }


@transaction.atomic
def return_unified_header(
    receipt_id: int,
    qty,
    *,
    user,
    transaction_uid: str,
    ref_type: str = "",
    ref_id: str = "",
    note: str = "",
) -> Dict:
    qty = _coerce_qty(qty)
    rc = _get_locked_unified_receipt_for_header_use(receipt_id)

    _ensure_txid_unused(transaction_uid)

    cur_used = _dec(rc.used_qty)
    if qty > cur_used:
        raise ValidationError(f"반납 수량({qty})이 현재 사용량({cur_used})을 초과합니다.")

    _create_usage(
        receipt=rc,
        line=None,
        action=UnifiedUsage.Action.RETURN,
        qty_change=(qty * Decimal("-1")),
        user=user,
        txid=transaction_uid,
        ref_type=ref_type,
        ref_id=ref_id,
        note=note,
    )

    rc.used_qty = (cur_used - qty).quantize(Decimal("0.001"))
    if rc.used_qty < _ZERO:
        rc.used_qty = _ZERO
    rc.save(update_fields=["used_qty", "use_status"])

    return {
        "ok": True,
        "receipt_id": rc.id,
        "receipt_qty": str(_dec(rc.qty)),
        "receipt_used_qty": str(_dec(rc.used_qty)),
        "receipt_status": rc.use_status,
    }


@transaction.atomic
def adjust_unified_header(
    receipt_id: int,
    delta,
    *,
    user,
    transaction_uid: str,
    ref_type: str = "",
    ref_id: str = "",
    note: str = "",
) -> Dict:
    delta = _coerce_delta(delta)
    rc = _get_locked_unified_receipt_for_header_use(receipt_id)

    _ensure_txid_unused(transaction_uid)

    cur_used = _dec(rc.used_qty)
    new_used = (cur_used + delta).quantize(Decimal("0.001"))
    if new_used < _ZERO or new_used > _dec(rc.qty):
        raise ValidationError("조정 결과가 허용 범위를 벗어납니다.")

    _create_usage(
        receipt=rc,
        line=None,
        action=UnifiedUsage.Action.ADJUST,
        qty_change=delta,
        user=user,
        txid=transaction_uid,
        ref_type=ref_type,
        ref_id=ref_id,
        note=note,
    )

    rc.used_qty = new_used
    rc.save(update_fields=["used_qty", "use_status"])

    return {
        "ok": True,
        "receipt_id": rc.id,
        "receipt_qty": str(_dec(rc.qty)),
        "receipt_used_qty": str(_dec(rc.used_qty)),
        "receipt_status": rc.use_status,
    }

# ======================================================================
# (선택) 이동/창고 변경 보조 함수가 필요하면 아래에 추가
#  - CHEM 라인 이동: line.warehouse 변경 + 헤더 동기화
#  - NF/SUP 헤더 이동: 별도 Issue 전표와의 연동 규약에 맞게 구현
# ======================================================================

# def move_chem_line(...):
#     ...
#
# def move_unified_header(...):
#     ...
