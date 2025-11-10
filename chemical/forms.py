# chemical/forms.py

import re
from django import forms
from .models import Chemical, ChemicalPrice

# ─────────────────────────────────────────────────────────────
# 자연어 규격(spec) → 표준 필드 자동 정규화 유틸
# - unit_qty : 정수(예: 18)
# - spec_unit: 측정 단위 코드(KG/L/MM/EA/...)
# - container_uom: 포장/용기 단위(말/통/드럼/EA 등)
# - spec_note: 성상/등급 텍스트(분말, SJ2 등)
# 금액/바코드 로직은 다른 앱에서 처리 (여기서는 보관만)
# ─────────────────────────────────────────────────────────────

_UNIT_MAP = {
    '%': 'PCT', 'pct': 'PCT', '퍼센트': 'PCT',
    'kg': 'KG', '킬로그램': 'KG',
    'g':  'G',  '그램': 'G',
    'l':  'L',  'ℓ': 'L',  '리터': 'L',
    'ml': 'ML', '밀리리터': 'ML',
    'mm': 'MM',
    'cm': 'CM',
    'm':  'M',
    'ea': 'EA',
}

# 포장/용기 단위 후보 (필요시 확장)
_CONTAINER_SET = {'말', '통', '드럼', '병', '포대', '박스', '롤', '봉', 'EA', 'ea'}

# 정수형 숫자 + 측정단위 패턴 (예: 18kg, 25L, 500mm, 1EA)
_NUM_UNIT = re.compile(r'(\d+)\s*(%|kg|g|l|ml|mm|cm|m|ea)\b', re.I)

# 우측 슬래시 뒤의 포장단위 (예: "18kg/말" 에서 "/말")
_SLASH_CONT = re.compile(r'/\s*([^\s/]+)\s*$')


def _u2code(u: str | None) -> str | None:
    """사용자 입력 단위 문자열을 표준 코드로 변환."""
    if not u:
        return None
    return _UNIT_MAP.get(u.lower())


class ChemicalForm(forms.ModelForm):
    """
    화면은 단순(자연어 spec + 보조필드)하게 유지,
    저장 직전에 한 번만 파싱하여 표준 필드에 정규화한다.
    """
    class Meta:
        model = Chemical
        fields = [
            'name',
            'spec',            # 자연어 입력
            'unit_qty',        # 단위규격(정수)
            'spec_unit',       # 측정 단위 코드(KG/L/MM/EA/..)
            'container_uom',   # 포장/용기 단위(말/통/드럼/EA)
            'spec_note',       # 성상/등급 텍스트(분말, SJ2 등)
            'customer',
            'image',
            'use_yn',
        ]
        labels = {
            'name': '품명',
            'spec': '규격(자연어)',
            'unit_qty': '단위규격(정수)',
            'spec_unit': '측정 단위',
            'container_uom': '포장단위',
            'spec_note': '비고(성상/등급)',
            'customer': '고객사',
            'image': '제품 이미지',
            'use_yn': '사용 여부',
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'spec': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'placeholder': '예) 18kg/말, 분말, 500mm SJ2'
            }),
            'unit_qty': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm',
                'min': 1,
                'step': 1,
                'placeholder': '예) 18, 25, 500, 1'
            }),
            'spec_unit': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'container_uom': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'placeholder': '예) 말 / 통 / 드럼 / EA'
            }),
            'spec_note': forms.TextInput(attrs={
                'class': 'form-control form-control-sm',
                'placeholder': '예) 분말, SJ2'
            }),
            'customer': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'image': forms.ClearableFileInput(attrs={'class': 'form-control form-control-sm'}),
            'use_yn': forms.Select(attrs={'class': 'form-select form-select-sm'}),
        }

    def clean(self):
        cleaned = super().clean()

        # 원문 자연어 규격
        text = (cleaned.get('spec') or '').strip()
        # 사용자가 직접 넣은 보조필드(있으면 우선)
        unit_qty = cleaned.get('unit_qty')
        spec_unit = cleaned.get('spec_unit')
        container = cleaned.get('container_uom')
        note = cleaned.get('spec_note')

        # 공백 정리
        s = re.sub(r'\s+', ' ', text)

        # 1) 우측 "/포장단위" 추출 (예: "18kg/말")
        m = _SLASH_CONT.search(s)
        if m:
            cont = m.group(1)
            s = s[:m.start()].strip()
            if not container and cont in _CONTAINER_SET:
                container = cont

        # 2) "정수+측정단위" 추출 (예: 18kg, 25L, 500mm, 1EA)
        m = _NUM_UNIT.search(s)
        if m and unit_qty is None:
            # (A) 단위규격(정수)
            try:
                unit_qty = int(m.group(1))
            except ValueError:
                self.add_error('unit_qty', '단위규격은 정수여야 합니다.')
            # (B) 측정단위 코드
            if not spec_unit:
                code = _u2code(m.group(2))
                if code:
                    spec_unit = code
            # 본문에서 추출된 패턴 제거
            s = (_NUM_UNIT.sub('', s)).strip()

        # 3) 남은 문자열은 비고(성상/등급)로 흡수 (예: "SJ2", "분말")
        #if s:
        #    note = (note + ' ' if note else '') + s

        # 4) spec_unit이 문자열 별칭/소문자면 코드로 보정
        if spec_unit and spec_unit not in [c[0] for c in Chemical.SpecUnit.choices]:
            code = _u2code(spec_unit)
            if code:
                spec_unit = code
            else:
                self.add_error('spec_unit', '지원하지 않는 단위입니다.')

        # 5) 유효성: unit_qty는 1 이상의 정수
        if unit_qty is not None and unit_qty <= 0:
            self.add_error('unit_qty', '단위규격은 1 이상의 정수여야 합니다.')

        # 정리된 값 반영
        cleaned['unit_qty'] = unit_qty
        cleaned['spec_unit'] = spec_unit
        cleaned['container_uom'] = container
        cleaned['spec_note'] = (note.strip() if note else None)

        return cleaned


class ChemicalPriceForm(forms.ModelForm):
    class Meta:
        model = ChemicalPrice
        fields = ['date', 'price']
        labels = {
            'date': '일자',
            'price': '단가',
        }
        widgets = {
            'date': forms.DateTimeInput(attrs={
                'type': 'datetime-local',
                'class': 'form-control form-control-sm'
            }),
            'price': forms.NumberInput(attrs={
                'class': 'form-control form-control-sm',
                'placeholder': '숫자만 입력'
            }),
        }
