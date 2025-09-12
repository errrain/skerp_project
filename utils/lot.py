# utils/lot.py
from django.db import connection
from django.utils import timezone
from datetime import date as _date  # ★ 추가

def get_next_lot(lot_type: str, anchor_dt=None) -> str:
    """
    LOT 발급 헬퍼
    - lot_type: 'PO','OR','IN','JB','CP','OT'
    - anchor_dt: datetime 또는 date (없으면 timezone.now())
    """
    if anchor_dt is None:
        anchor_dt = timezone.now()

    # ★ anchor_dt가 date면 그대로 사용, datetime이면 localdate/UTC 보정
    if isinstance(anchor_dt, _date) and not hasattr(anchor_dt, "hour"):
        lot_date = anchor_dt
    else:
        lot_date = timezone.localdate(anchor_dt) if timezone.is_aware(anchor_dt) else anchor_dt.date()

    with connection.cursor() as cur:
        cur.execute("SELECT next_lot_seq(%s, %s)", [lot_type, lot_date])
        (lot,) = cur.fetchone()
    return lot
