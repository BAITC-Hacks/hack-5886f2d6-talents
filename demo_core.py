#!/usr/bin/env python3
"""Explicit Python integration demo. Replace with Arthur's C++ executable."""
import argparse
import math
from pathlib import Path

from hackalem.protocol import strict_json, write_json


def score(payload):
    rows = payload['nodes']
    max_turnover = max((n['metrics']['turnover_kzt'] for n in rows), default=0)
    max_pr = max((n['metrics']['pagerank'] for n in rows), default=0)
    result = []
    for n in rows:
        m, f = n['metrics'], n['flags']
        indeg, outdeg = m['in_deg'], m['out_deg']
        ratio = m['pass_through']
        role, confidence = 'peripheral', 0.25
        explanation = f'Гипотеза периферии: входов={indeg}, выходов={outdeg}; явных признаков роли нет.'
        if f['isolated']:
            confidence = 0.0
            explanation = 'Нет наблюдаемых переводов; роль не установлена. Периферия — техническая метка.'
        elif f['truncated_by_depth']:
            confidence = 0.0
            explanation = f'Граница depth=4: входов={indeg}; исходящие не наблюдаются, роль не установлена.'
        elif indeg >= 3 and outdeg >= 3 and m['seed_in_neighbors'] >= 2 and m['neighbor_clusters'] >= 2:
            role, confidence = 'coordinator', 0.55
            explanation = f'Гипотеза координации: входов={indeg}, выходов={outdeg}, плательщиков-seed={m["seed_in_neighbors"]}, соседних кластеров={m["neighbor_clusters"]}.'
        elif outdeg >= 10:
            role, confidence = 'distributor', 0.7
            explanation = f'Гипотеза распределения: получателей={outdeg}; исходящий объём={m["out_kzt"]:.0f} KZT.'
        elif f['pass_through_reliable'] and indeg >= 1 and outdeg >= 1 and 0.8 <= ratio <= 1.2:
            role, confidence = 'transit', 0.65
            explanation = f'Гипотеза транзита: выход/вход={ratio:.2f}, входов={indeg}, выходов={outdeg}; совпадение сумм не доказывает маршрут.'
        elif f['pass_through_reliable'] and indeg >= 3 and ratio < 0.5:
            role, confidence = 'consolidator', 0.7
            explanation = f'Гипотеза консолидации: плательщиков={indeg}; вход={m["in_kzt"]:.0f} KZT; выход/вход={ratio:.2f}.'
        elif f['pass_through_reliable'] and indeg >= 1 and outdeg == 0:
            role, confidence = 'terminal', 0.5
            explanation = f'Гипотеза конечного получения в выборке: вход={m["in_kzt"]:.0f} KZT; исходящих нет; depth={n["depth"]}.'
        if f['seed_inflow_incomplete'] and not f['isolated']:
            explanation += ' Вход seed неполон.'
        volume = math.log1p(m['turnover_kzt']) / math.log1p(max_turnover) if max_turnover else 0
        pr = m['pagerank'] / max_pr if max_pr else 0
        seed = min(m['seed_in_neighbors'] / 3, 1)
        priority = 0 if f['isolated'] else 0.35*volume + 0.25*pr + 0.2*seed + 0.2*confidence
        if f['boundary_depth']:
            priority *= 0.6
        why = (f'Гипотеза для проверки: оборот={m["turnover_kzt"]:.0f} KZT, PageRank={m["pagerank"]:.6f}, '
               f'прямых плательщиков-seed={m["seed_in_neighbors"]}; роль={role}.')
        if f['boundary_depth']:
            why += ' Граница depth=4: нужны исходящие за пределами обхода.'
        if f['seed_inflow_incomplete']:
            why += ' Входящие seed неполны.'
        if f['isolated']:
            why = 'Нет наблюдаемых связей; приоритет 0 отражает нехватку данных, а не отсутствие риска.'
        result.append({'gid': n['gid'], 'role': role, 'role_score': confidence,
                       'priority_score': round(priority, 8), 'evidence': explanation[:200], 'why': why})
    return {'schema_version': '1.0', 'engine': 'python-demo-v1', 'nodes': result}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    write_json(args.output, score(strict_json(args.input)))
