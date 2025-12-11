# mis/trace/views.py

import re
import traceback
from dataclasses import dataclass
from typing import List, Dict, Tuple

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from sales.models import SalesShipment, SalesShipmentLine
from quality.inspections.models import FinishedBox, FinishedBoxFill
from production.models import WorkOrder, WorkOrderInjectionUsage
from purchase.models import InjectionReceipt, InjectionReceiptLine
from injectionorder.models import InjectionOrder


# ─────────────────────────────────────────────
#  LOT 타입 정의
# ─────────────────────────────────────────────

class LotType:
    ORDER = "ORDER"                # OR 발주 LOT
    RECEIPT_HEADER = "RECEIPT"     # IN 헤더
    RECEIPT_LINE = "RECEIPT_LINE"  # IN 서브
    WORK = "WORK"                  # JB 작업 LOT
    CLOT = "CLOT"                  # C-LOT
    SHIP = "SHIP"                  # SH 출하 LOT
    UNKNOWN = "UNKNOWN"


LOT_TYPE_LABEL = {
    LotType.ORDER: "발주 LOT",
    LotType.RECEIPT_HEADER: "입고 헤더 LOT",
    LotType.RECEIPT_LINE: "입고 서브 LOT",
    LotType.WORK: "작업 LOT",
    LotType.CLOT: "완성 LOT",
    LotType.SHIP: "출하 LOT",
    LotType.UNKNOWN: "LOT",
}

# 여기 추가 👇
LOT_CLASS_MAP = {
    LotType.ORDER: "lot-order",          # OR
    LotType.RECEIPT_HEADER: "lot-in",    # IN 헤더
    LotType.RECEIPT_LINE: "lot-inss",    # IN-SS
    LotType.WORK: "lot-work",            # JB
    LotType.CLOT: "lot-clot",            # C-LOT
    LotType.SHIP: "lot-ship",            # SHLOT
    LotType.UNKNOWN: "lot-unknown",
}

def detect_lot_type(lot_no: str) -> str:
    """
    LOT 번호 패턴으로 타입 판별 (간단 버전)
    OR, IN, IN-SS, JB, C-, SH 모두 대응
    """
    lot_no = (lot_no or "").strip().upper()

    if lot_no.startswith("OR"):
        return LotType.ORDER

    if lot_no.startswith("IN"):
        # IN20251211001-02 같이 '-' 있으면 서브 LOT
        if "-" in lot_no:
            return LotType.RECEIPT_LINE
        # 그 외는 헤더 LOT
        return LotType.RECEIPT_HEADER

    # 작업 LOT 패턴: JB20251211-001 처럼 J? + 날짜 + - + 3자리
    if re.match(r"^J[A-Z]\d{8}-\d{3}$", lot_no):
        return LotType.WORK

    # C-LOT
    if lot_no.startswith("C-"):
        return LotType.CLOT

    # 출하 LOT
    if lot_no.startswith("SH"):
        return LotType.SHIP

    return LotType.UNKNOWN


# ─────────────────────────────────────────────
#  그래프 데이터 구조
# ─────────────────────────────────────────────

@dataclass
class LotNode:
    key: str         # 내부 ID (예: N0, N1...)
    lot_no: str      # 실제 LOT 번호
    lot_type: str    # LotType 값


@dataclass
class LotEdge:
    src: str         # LotNode.key
    dst: str         # LotNode.key


@dataclass
class LotGraph:
    nodes: List[LotNode]
    edges: List[LotEdge]


# ─────────────────────────────────────────────
#  샘플 그래프 생성 (UI 테스트용)
#  → 나중에 DB 조회 버전으로 교체
# ─────────────────────────────────────────────

def build_sample_graph(lot_no: str, lot_type: str) -> LotGraph:
    """
    지금은 LOT 타입에 따라 예시 체인만 만든다.
    실제 구현 시 DB 기반 trace 함수로 교체.
    """
    nodes: List[LotNode] = []
    edges: List[LotEdge] = []

    root = LotNode(key="N0", lot_no=lot_no, lot_type=lot_type)
    nodes.append(root)

    # C-LOT 기준: OR → IN → IN-SS → JB → C(root)
    if lot_type == LotType.CLOT:
        n_or = LotNode("N1", "OR20251211-001", LotType.ORDER)
        n_in = LotNode("N2", "IN20251211002", LotType.RECEIPT_HEADER)
        n_inss = LotNode("N3", "IN20251211002-02", LotType.RECEIPT_LINE)
        n_jb = LotNode("N4", "JB20251211-001", LotType.WORK)

        nodes.extend([n_or, n_in, n_inss, n_jb])

        edges.extend([
            LotEdge("N1", "N2"),
            LotEdge("N2", "N3"),
            LotEdge("N3", "N4"),
            LotEdge("N4", "N0"),
        ])

    # 작업 LOT 기준: OR → IN-SS → JB(root) → C 2개
    elif lot_type == LotType.WORK:
        n_or = LotNode("N1", "OR20251211-001", LotType.ORDER)
        n_inss = LotNode("N2", "IN20251211002-02", LotType.RECEIPT_LINE)
        n_c1 = LotNode("N3", "C-20251211-01", LotType.CLOT)
        n_c2 = LotNode("N4", "C-20251211-02", LotType.CLOT)

        nodes.extend([n_or, n_inss, n_c1, n_c2])

        edges.extend([
            LotEdge("N1", "N2"),
            LotEdge("N2", "N0"),  # N0 = JB(root)
            LotEdge("N0", "N3"),
            LotEdge("N0", "N4"),
        ])

    # 출하 LOT 기준: OR → IN → IN-SS → JB → C → SH(root)
    elif lot_type == LotType.SHIP:
        n_c1 = LotNode("N1", "C-20251211-01", LotType.CLOT)
        n_c2 = LotNode("N2", "C-20251211-02", LotType.CLOT)
        n_jb = LotNode("N3", "JB20251211-001", LotType.WORK)
        n_inss = LotNode("N4", "IN20251211002-02", LotType.RECEIPT_LINE)
        n_in = LotNode("N5", "IN20251211002", LotType.RECEIPT_HEADER)
        n_or = LotNode("N6", "OR20251211-001", LotType.ORDER)

        nodes.extend([n_c1, n_c2, n_jb, n_inss, n_in, n_or])

        edges.extend([
            LotEdge("N6", "N5"),
            LotEdge("N5", "N4"),
            LotEdge("N4", "N3"),
            LotEdge("N3", "N1"),
            LotEdge("N3", "N2"),
            LotEdge("N1", "N0"),
            LotEdge("N2", "N0"),
        ])

    # 그 외 타입은 일단 단일 노드만 표시
    return LotGraph(nodes=nodes, edges=edges)


# ─────────────────────────────────────────────
#  Mermaid 코드 생성
# ─────────────────────────────────────────────

def build_mermaid_from_graph(graph: LotGraph) -> str:
    """
    LotGraph → mermaid flowchart 문자열 변환
    + LOT 타입별 classDef / class 지정
    """
    if not graph.nodes:
        return "graph LR\n  A[LOT 데이터가 없습니다]"

    lines: List[str] = ["graph LR"]

    # 1) LOT 타입별 박스 스타일(classDef)
    lines.extend(
        [
            # OR (발주 LOT) → 노랑
            "  classDef lot-order fill:#fff3cd,stroke:#ffb300,stroke-width:1.5px,color:#333;",

            # IN 헤더 → 파랑
            "  classDef lot-receipt-h fill:#e3f2fd,stroke:#1976d2,stroke-width:1.5px,color:#333;",

            # IN 서브 → 초록
            "  classDef lot-receipt-l fill:#e8f5e9,stroke:#2e7d32,stroke-width:1.5px,color:#333;",

            # 작업 LOT(JB) → 보라
            "  classDef lot-work fill:#ede7f6,stroke:#673ab7,stroke-width:1.5px,color:#333;",

            # C-LOT → 연노랑
            "  classDef lot-clot fill:#fff8e1,stroke:#f9a825,stroke-width:1.5px,color:#333;",

            # 출하 LOT(SHLOT) → 핑크
            "  classDef lot-ship fill:#ffebee,stroke:#d32f2f,stroke-width:1.5px,color:#333;",
        ]
    )

    # 2) 노드 키 → LotNode 매핑 / 노드별 클래스 수집
    node_map: Dict[str, LotNode] = {n.key: n for n in graph.nodes}
    node_classes: Dict[str, str] = {}

    for node in graph.nodes:
        css_class = LOT_CLASS_MAP.get(node.lot_type)
        if css_class:
            node_classes[node.key] = css_class

    # 3) edge 라인 생성
    if graph.edges:
        for edge in graph.edges:
            src = node_map[edge.src]
            dst = node_map[edge.dst]

            src_label = f"{src.lot_no}<br/>({LOT_TYPE_LABEL.get(src.lot_type, 'LOT')})"
            dst_label = f"{dst.lot_no}<br/>({LOT_TYPE_LABEL.get(dst.lot_type, 'LOT')})"

            lines.append(
                f'  {src.key}["{src_label}"] --> {dst.key}["{dst_label}"]'
            )
    else:
        # edge 없으면 root 하나만 출력
        root = graph.nodes[0]
        root_label = f"{root.lot_no}<br/>({LOT_TYPE_LABEL.get(root.lot_type, 'LOT')})"
        lines.append(f'  {root.key}["{root_label}"]')

    # 4) 각 노드에 class 지정
    #    예: class N0 lot-order;
    for key, cls in node_classes.items():
        lines.append(f"  class {key} {cls};")

    return "\n".join(lines)


# ─────────────────────────────────────────────
#  SH LOT(출하 LOT) 실제 DB 기반 그래프 빌더
# ─────────────────────────────────────────────

def _build_graph_for_shipment(sh_lot: str) -> LotGraph:
    """
    출하 LOT(SH...) 기준으로 실제 DB에서 관계를 읽어와
    OR → IN → IN-SS → JB → C-LOT → SH 그래프를 만든다.
    """
    nodes: List[LotNode] = []
    edges: List[LotEdge] = []

    # (lot_type, lot_no) → key(N0, N1, ...)
    node_map: Dict[Tuple[str, str], str] = {}
    edge_set: set[Tuple[str, str]] = set()

    def ensure_node(lot_type: str, lot_no: str) -> str:
        key = (lot_type, lot_no)
        if key in node_map:
            return node_map[key]
        node_id = f"N{len(node_map)}"
        node_map[key] = node_id
        nodes.append(LotNode(key=node_id, lot_no=lot_no, lot_type=lot_type))
        return node_id

    def add_edge(src_key: str, dst_key: str) -> None:
        pair = (src_key, dst_key)
        if pair in edge_set:
            return
        edge_set.add(pair)
        edges.append(LotEdge(src=src_key, dst=dst_key))

    # 1) 출하 헤더 찾기
    try:
        shipment = SalesShipment.objects.get(sh_lot=sh_lot)
    except SalesShipment.DoesNotExist:
        return LotGraph(nodes=[], edges=[])

    # 루트 노드(SH LOT)
    root_key = ensure_node(LotType.SHIP, shipment.sh_lot)

    # 2) 출하 라인 → FinishedBox(C-LOT) 전부
    line_qs = (
        SalesShipmentLine.objects
        .select_related("finished_box")
        .filter(shipment=shipment)
    )

    finished_boxes: List[FinishedBox] = []
    seen_box_ids: set[int] = set()
    for line in line_qs:
        if line.finished_box_id and line.finished_box_id not in seen_box_ids:
            finished_boxes.append(line.finished_box)
            seen_box_ids.add(line.finished_box_id)

    if not finished_boxes:
        # C-LOT 이 없는 출하라면 출하만 표시
        return LotGraph(nodes=nodes, edges=edges)

    box_id_list = [fb.id for fb in finished_boxes]

    # 3) C-LOT ↔ WorkOrder (FinishedBoxFill)
    #    FK 이름: box / box_id, workorder 는 inspection 을 통해 접근
    fill_qs = (
        FinishedBoxFill.objects
        .select_related("box", "inspection__workorder")
        .filter(box_id__in=box_id_list)
    )

    # 이 출하에 연결된 모든 WorkOrder id 수집
    workorder_ids: set[int] = set()
    for f in fill_qs:
        if f.inspection_id and getattr(f.inspection, "workorder_id", None):
            workorder_ids.add(f.inspection.workorder_id)

    # 4) WorkOrder → 사용된 입고 서브 LOT
    usage_qs = (
        WorkOrderInjectionUsage.objects
        .select_related(
            "workorder",
            "line__receipt__order",  # ✅ receipt_line → line 으로 수정
        )
        .filter(workorder_id__in=workorder_ids)
    )

    # OR → IN → IN-SS → JB 체인 구성
    for usage in usage_qs:
        workorder = usage.workorder
        receipt_line = usage.line  # ✅ usage.receipt_line → usage.line
        if not workorder or not receipt_line:
            continue

        receipt = receipt_line.receipt
        order = receipt.order if receipt else None

        jb_key = ensure_node(LotType.WORK, workorder.work_lot)
        inss_key = ensure_node(LotType.RECEIPT_LINE, receipt_line.sub_lot)

        in_key = None
        or_key = None

        if receipt:
            in_key = ensure_node(LotType.RECEIPT_HEADER, receipt.receipt_lot)
        if order:
            or_key = ensure_node(LotType.ORDER, order.order_lot)

        # OR → IN
        if or_key and in_key:
            add_edge(or_key, in_key)
        # IN → IN-SS
        if in_key:
            add_edge(in_key, inss_key)
        # IN-SS → JB
        add_edge(inss_key, jb_key)

    # 5) C-LOT 노드 및 C-LOT ↔ JB ↔ SH 연결
    #    (FinishedBoxFill 기준)
    for fb in finished_boxes:
        c_key = ensure_node(LotType.CLOT, fb.lot_no)
        # C-LOT → SH(출하 LOT)
        add_edge(c_key, root_key)

        # 이 C-LOT 과 연결된 모든 WorkOrder
        for f in filter(lambda x: x.box_id == fb.id, fill_qs):
            if not f.inspection_id or not getattr(f.inspection, "workorder", None):
                continue
            wo = f.inspection.workorder
            jb_key = ensure_node(LotType.WORK, wo.work_lot)
            # JB → C-LOT
            add_edge(jb_key, c_key)

    return LotGraph(nodes=nodes, edges=edges)

def _build_graph_for_order(order_lot: str) -> LotGraph:
    """
    발주 LOT(OR...) 기준 LOT 그래프.
    - OR → IN(헤더) → IN-SS(서브 LOT) → JB(작업 LOT) → C-LOT → SH 까지 전부 그린다.
    - SH LOT 이 여러 개면 전부 오른쪽에 붙음.
    """
    nodes: List[LotNode] = []
    edges: List[LotEdge] = []

    node_map: Dict[Tuple[str, str], str] = {}
    edge_set: set[Tuple[str, str]] = set()

    def ensure_node(lot_type: str, lot_no: str) -> str:
        key = (lot_type, lot_no)
        if key in node_map:
            return node_map[key]
        node_id = f"N{len(node_map)}"
        node_map[key] = node_id
        nodes.append(LotNode(key=node_id, lot_no=lot_no, lot_type=lot_type))
        return node_id

    def add_edge(src_key: str, dst_key: str) -> None:
        pair = (src_key, dst_key)
        if pair in edge_set:
            return
        edge_set.add(pair)
        edges.append(LotEdge(src=src_key, dst=dst_key))

    # 1) 발주 헤더 찾기
    try:
        order = InjectionOrder.objects.get(order_lot=order_lot)
    except InjectionOrder.DoesNotExist:
        return LotGraph(nodes=[], edges=[])

    # OR 노드(루트)
    or_key = ensure_node(LotType.ORDER, order.order_lot)

    # 2) 이 발주와 연결된 입고 헤더 LOT 들
    receipt_qs = InjectionReceipt.objects.filter(order=order)
    receipts = list(receipt_qs)
    if not receipts:
        return LotGraph(nodes=nodes, edges=edges)

    receipt_ids = [r.id for r in receipts]

    # 3) 입고 서브 LOT(IN-SS)
    line_qs = InjectionReceiptLine.objects.filter(receipt_id__in=receipt_ids)
    lines = list(line_qs)
    if not lines:
        # OR → IN 까지만 있는 경우
        for r in receipts:
            in_key = ensure_node(LotType.RECEIPT_HEADER, r.receipt_lot)
            add_edge(or_key, in_key)
        return LotGraph(nodes=nodes, edges=edges)

    line_ids = [ln.id for ln in lines]

    # 4) 서브 LOT 사용 이력: IN-SS → JB
    usage_qs = (
        WorkOrderInjectionUsage.objects
        .select_related(
            "workorder",
            "line__receipt__order",
        )
        .filter(line_id__in=line_ids)
    )

    workorder_ids: set[int] = set()

    for usage in usage_qs:
        workorder = usage.workorder
        receipt_line = usage.line
        if not workorder or not receipt_line:
            continue

        receipt = receipt_line.receipt
        # OR 는 이미 or_key 하나로 고정

        in_key = None
        inss_key = ensure_node(LotType.RECEIPT_LINE, receipt_line.sub_lot)
        jb_key = ensure_node(LotType.WORK, workorder.work_lot)

        if receipt:
            in_key = ensure_node(LotType.RECEIPT_HEADER, receipt.receipt_lot)

        # OR → IN
        if in_key:
            add_edge(or_key, in_key)
            # IN → IN-SS
            add_edge(in_key, inss_key)
        else:
            # 헤더 없이 IN-SS 만 있다면 OR → IN-SS 직접 연결
            add_edge(or_key, inss_key)

        # IN-SS → JB
        add_edge(inss_key, jb_key)
        workorder_ids.add(workorder.id)

    if not workorder_ids:
        return LotGraph(nodes=nodes, edges=edges)

    # 5) JB → C-LOT (FinishedBoxFill)
    fill_qs = (
        FinishedBoxFill.objects
        .select_related("box", "inspection__workorder")
        .filter(inspection__workorder_id__in=workorder_ids)
    )

    box_ids: set[int] = set()
    for f in fill_qs:
        if not f.box_id:
            continue
        box_ids.add(f.box_id)

        c_key = ensure_node(LotType.CLOT, f.box.lot_no)
        jb = f.inspection.workorder
        if jb:
            jb_key = ensure_node(LotType.WORK, jb.work_lot)
            add_edge(inss_key := jb_key, c_key)  # JB → C-LOT

    if not box_ids:
        return LotGraph(nodes=nodes, edges=edges)

    # 6) C-LOT → 출하(SH)
    ship_line_qs = (
        SalesShipmentLine.objects
        .select_related("shipment", "finished_box")
        .filter(finished_box_id__in=box_ids)
    )

    seen_ship_ids: set[int] = set()
    for sl in ship_line_qs:
        fb = sl.finished_box
        ship = sl.shipment
        if not fb or not ship:
            continue

        c_key = ensure_node(LotType.CLOT, fb.lot_no)
        sh_key = ensure_node(LotType.SHIP, ship.sh_lot)
        add_edge(c_key, sh_key)  # C-LOT → SH

        seen_ship_ids.add(ship.id)

    return LotGraph(nodes=nodes, edges=edges)

# ─────────────────────────────────────────────
#  LOT 타입별 그래프 빌더 라우팅
# ─────────────────────────────────────────────

def build_graph_for_lot(lot_no: str, lot_type: str) -> LotGraph:
    """
    LOT 타입별로 적절한 그래프 빌더 호출.
    - SHIP(출하 LOT): 실제 DB 기반 그래프
    - 그 외: 일단 샘플 그래프 (추후 점진적 확장)
    """
    if lot_type == LotType.SHIP:
        return _build_graph_for_shipment(lot_no)

    # TODO: ORDER / RECEIPT / WORK / C-LOT 도 차차 실제 쿼리로 대체
    return build_sample_graph(lot_no, lot_type)


# ─────────────────────────────────────────────
#  View: LOT Trace 화면 & API
# ─────────────────────────────────────────────

def lot_trace_page(request):
    """
    LOT Trace 메인 화면 (/mgmt/trace/ 또는 /mis/trace/)
    """
    return render(request, "trace/lot_trace.html")


@require_GET
def lot_trace_api(request):
    """
    LOT Trace API (/mis/trace/api/)
    - GET 파라미터: lot_no
    - 응답: { success, message, summary, mermaid }
    """
    lot_no = (request.GET.get("lot_no") or "").strip()

    if not lot_no:
        return JsonResponse(
            {"success": False, "message": "LOT 번호를 입력해 주세요."},
            status=400,
        )

    try:
        lot_type = detect_lot_type(lot_no)

        if lot_type == LotType.UNKNOWN:
            return JsonResponse(
                {
                    "success": False,
                    "message": f"인식할 수 없는 LOT 형식입니다: {lot_no}",
                },
                status=400,
            )

        graph = build_graph_for_lot(lot_no, lot_type)

        if not graph.nodes:
            return JsonResponse(
                {
                    "success": False,
                    "message": f"{lot_no} 에 대한 LOT 정보를 찾을 수 없습니다.",
                },
                status=404,
            )

        mermaid_code = build_mermaid_from_graph(graph)
        summary = f"{lot_no} ({LOT_TYPE_LABEL.get(lot_type, 'LOT')}) 기준 LOT 흐름"

        return JsonResponse(
            {
                "success": True,
                "summary": summary,
                "mermaid": mermaid_code,
            }
        )

    except Exception as e:
        # 서버 콘솔에 자세한 스택 출력
        print("=== LOT TRACE ERROR ===")
        print(f"LOT: {lot_no}")
        traceback.print_exc()

        # 프론트에는 JSON 형태로 에러 반환
        return JsonResponse(
            {
                "success": False,
                "message": f"LOT Trace 처리 중 오류: {e}",
            },
            status=500,
        )
