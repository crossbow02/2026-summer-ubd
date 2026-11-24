#!/usr/bin/env python3
"""
구역편성 초안 만들기.

'구역편성_가정' 시트를 그대로 읽은 JSON({"values": [[머리글...], [행...], ...]})을 받아
확정 구역장 가정마다 한 구역씩 만들고 나머지 가정을 나눈다.

  python3 zone_draft.py 가정.json --leaders 김상단,신상혁,김용현,조민규,홍진기,박진성,전두표 > draft.json

편성 기준
  - 대상: 사랑구역(원본 87행 아래) · 임원 · 3마을 이동(✓) · 내년 배정 의견 '편성 제외'/'사랑구역' 가정을 뺀 나머지
  - 구역마다 가정 수와 출석률(A~D)이 고르게 섞이도록 나눈다
  - 지금 같은 구역이던 가정은 한 구역에 1가정까지만 반기고, 그보다 많으면 흩는다
  - 자녀 나이(막내 출생년)가 비슷한 구역을 조금 더 반긴다
  - 구역장 추천(✓)·현 구역장·권찰 가정 중 앞선 가정을 구역마다 '권찰 후보' 1가정씩
  - GROUPS: 동정·특이사항에서 같이 배정해 달라고 한 가정 묶음 (이름 일부, 고정할 구역장)

결과 draft.json: {"zones": [{"no", "leader", "fams": [[ID, 역할], ...]}], "others": [[ID, 사유], ...]}
"""
import argparse
import collections
import json
import re
import sys

LOVE_ZONE = '사랑구역'
GRADE = {'A': 0, 'B': 1, 'C': 2, 'D': 3}
ROLE_ORDER = {'구역장': 0, '권찰 후보': 1, '구역원': 2}

# (같이 배정할 가정의 형제/자매 이름들, 고정할 구역장 이름 또는 None)
GROUPS = [
    (['서재영', '박상현'], None),
    (['문남연', '신진'], None),
    (['이유동', '유동수'], None),
    (['조영의', '김형태', '박민영'], '홍진기'),
    (['김규봉', '김호정', '유정준'], None),
    (['서상철', '조명규'], None),
]


def load(path):
    values = json.load(open(path))['values']
    head = values[0]
    return [dict(zip(head, r + [''] * (len(head) - len(r)))) for r in values[1:] if r and r[0]]


def label(f):
    return ' · '.join(x for x in (f['형제 이름'], f['자매 이름']) if x)


def rate26(f):
    p = [int(x) for x in re.findall(r'(\d+)%', f.get('26년 출석률', ''))]
    return sum(p) / len(p) if p else 0


def kid_year(f):
    ys = [int(y) for y in re.findall(r'\((\d{2})', f['자녀'])]
    return max(ys) if ys else None


def status(f):
    if f['구분'] == '임원':
        return '임원'
    if f['3마을 이동'] == '✓':
        return '3마을 이동'
    if f['내년 배정 의견'] in ('편성 제외', LOVE_ZONE):
        return f['내년 배정 의견']
    return 'pool'


def order_key(f):
    return (GRADE.get(f['출석률(2년)'], 4), -rate26(f))


def cost(zone, f):
    fams = [x for x, _ in zone['fams']]
    c = 10 * len(fams)
    c += 6 * sum(1 for x in fams if x['출석률(2년)'] == f['출석률(2년)'])
    ky, ks = kid_year(f), [kid_year(x) for x in fams if kid_year(x)]
    if ky and ks:
        c += 1.5 * abs(ky - sum(ks) / len(ks))
    same = sum(1 for x in fams if x['구역'] == f['구역'])
    c += -4 if same == 1 else (8 * (same - 1) if same > 1 else 0)
    return c


def group_cost(zone, group):
    saved = list(zone['fams'])
    total = 0
    for f in group:
        total += cost(zone, f)
        zone['fams'].append((f, '구역원'))
    zone['fams'][:] = saved
    return total


def build(families, leaders, helpers_per_zone=1):
    active = [f for f in families if f['구분'] != LOVE_ZONE]
    pool = [f for f in active if status(f) == 'pool']
    by_leader = {}
    for name in leaders:
        match = [f for f in pool if name in (f['형제 이름'], f['자매 이름'])]
        if len(match) != 1:
            sys.exit(f'구역장 {name}: 편성 대상 가정에서 {len(match)}곳 찾음 (1곳이어야 함)')
        by_leader[name] = match[0]
    zones = [{'no': i + 1, 'leader': n, 'fams': [(by_leader[n], '구역장')]} for i, n in enumerate(leaders)]
    zone_of = {z['leader']: z for z in zones}
    rest = [f for f in pool if f not in by_leader.values()]

    candidates = sorted(
        [f for f in rest if f['구역장 추천'] == '✓' or f['구분'] in ('구역장', '권찰')],
        key=lambda f: (f['구역장 추천'] != '✓',) + order_key(f))
    helper_ids = {f['ID'] for f in candidates[:len(zones) + 2]}

    def find(name):
        return next(f for f in rest if name in (f['형제 이름'], f['자매 이름']))

    units = [([find(n) for n in names], fixed) for names, fixed in GROUPS]
    grouped = {f['ID'] for g, _ in units for f in g}
    units += [([f], None) for f in rest if f['ID'] not in grouped]

    def unit_key(u):
        group = u[0]
        return (0 if any(f['ID'] in helper_ids for f in group) else 1, 0 if len(group) > 1 else 1) + order_key(group[0])

    for group, fixed in sorted(units, key=unit_key):
        zone = zone_of[fixed] if fixed else min(zones, key=lambda z: group_cost(z, group))
        helpers = sum(1 for _, r in zone['fams'] if r == '권찰 후보')
        for f in group:
            role = '구역원'
            if f['ID'] in helper_ids and helpers < helpers_per_zone:
                role, helpers = '권찰 후보', helpers + 1
            zone['fams'].append((f, role))

    for z in zones:
        z['fams'].sort(key=lambda x: (ROLE_ORDER[x[1]],) + order_key(x[0]))
    others = [(f, status(f)) for f in active if status(f) != 'pool']
    return zones, others


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('family_json')
    ap.add_argument('--leaders', required=True, help='쉼표로 구분한 확정 구역장 이름 (형제 또는 자매)')
    args = ap.parse_args()

    zones, others = build(load(args.family_json), [n.strip() for n in args.leaders.split(',') if n.strip()])
    for z in zones:
        c = collections.Counter(f['출석률(2년)'] for f, _ in z['fams'])
        print(f"{z['no']}구역 {z['leader']}: {len(z['fams'])}가정 A{c['A']} B{c['B']} C{c['C']} D{c['D']}", file=sys.stderr)
        for f, role in z['fams']:
            print(f"   {role:6} {f['구역']:5} {label(f):14} {f['출석률(2년)']}", file=sys.stderr)
    print(dict(collections.Counter(s for _, s in others)), file=sys.stderr)
    json.dump({
        'zones': [{'no': z['no'], 'leader': z['leader'], 'fams': [[f['ID'], r] for f, r in z['fams']]} for z in zones],
        'others': [[f['ID'], s] for f, s in others],
    }, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
