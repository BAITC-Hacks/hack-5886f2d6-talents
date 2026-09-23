"""Load, validate and enrich the organizer's directed graph."""
from __future__ import annotations

import math
import re
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd


class DataError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise DataError(message)


def normalize_ids(series: pd.Series, name: str) -> pd.Series:
    require(not series.isna().any(), f"{name}: missing identifier")
    # Never accept floats: a lost int64 bit cannot be recovered by astype(str).
    require(all(isinstance(v, (str, int, np.integer)) and not isinstance(v, (bool, np.bool_))
                for v in series), f"{name}: identifiers must be strings or integers, not floats")
    result = series.map(str)
    require(result.map(lambda s: bool(s) and s == s.strip()).all(), f"{name}: empty/whitespace identifier")
    require(result.map(lambda s: re.fullmatch(r'(0|[1-9][0-9]*|-[1-9][0-9]*)', s) is not None
                       and -(2**63) <= int(s) <= 2**63-1).all(),
            f'{name}: identifiers must be canonical signed int64 strings')
    return result


def integer_column(df, col, low, high=None):
    s = df[col]
    require(pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s), f"{col}: expected numeric integers")
    require(s.notna().all() and np.isfinite(s).all(), f"{col}: missing/nonfinite values")
    require(((s % 1) == 0).all() and (s >= low).all(), f"{col}: invalid integer range")
    if high is not None:
        require((s <= high).all(), f"{col}: must be <= {high}")
    df[col] = s.astype('int64')


def load(data_dir: Path):
    """Same files and return order as starter.load."""
    edges = pd.read_parquet(data_dir / 'edges.parquet')
    nodes = pd.read_parquet(data_dir / 'nodes.parquet')
    tx = pd.read_parquet(data_dir / 'transactions.parquet')
    return edges, nodes, tx


def sanity_check(edges, nodes, tx):
    """Validate every pair, amount and count; do not silently repair input."""
    for label, df, columns in (
        ('nodes', nodes, {'gid', 'depth', 'is_seed'}),
        ('edges', edges, {'src', 'dst', 'sum_kzt', 'n_tx', 'depth'}),
        ('transactions', tx, {'src', 'dst', 'sum_kzt', 'date'}),
    ):
        require(columns.issubset(df.columns), f"{label}: missing columns {sorted(columns-set(df.columns))}")
        require(df.columns.is_unique, f"{label}: duplicate columns")
        for col in ('gid',) if label == 'nodes' else ('src', 'dst'):
            df[col] = normalize_ids(df[col], f'{label}.{col}')
    require(len(nodes) > 0, 'nodes is empty')
    require(nodes.gid.is_unique, 'nodes: duplicate gid')
    require(not edges.duplicated(['src', 'dst']).any(), 'edges: duplicate directed pair')
    require(nodes.is_seed.notna().all() and nodes.is_seed.map(lambda x: isinstance(x, (bool, np.bool_))).all(),
            'nodes.is_seed must be boolean')
    integer_column(nodes, 'depth', 0, 4)
    integer_column(edges, 'depth', 1, 4)
    integer_column(edges, 'n_tx', 1)
    require((nodes.is_seed == (nodes.depth == 0)).all(), 'seed flag inconsistent with depth=0')
    gids = set(nodes.gid)
    for label, df in (('edges', edges), ('transactions', tx)):
        unknown = (set(df.src) | set(df.dst)) - gids
        require(not unknown, f'{label}: unknown endpoint gids {sorted(unknown)[:5]}')
        s = df.sum_kzt
        require(pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s), f'{label}.sum_kzt must be numeric')
        require(s.notna().all() and np.isfinite(s).all() and (s > 0).all(), f'{label}: amounts must be finite and positive')
    tx['date'] = pd.to_datetime(tx['date'], errors='raise')
    require(tx.date.notna().all(), 'transactions: missing date')
    agg = tx.groupby(['src', 'dst'], sort=True).agg(total=('sum_kzt', 'sum'), count=('sum_kzt', 'size')).reset_index()
    m = edges.merge(agg, on=['src', 'dst'], how='outer', indicator=True, validate='one_to_one')
    require((m['_merge'] == 'both').all(), 'edges/transactions: directed pairs differ')
    if len(m):
        bad_sum = ~np.isclose(m.sum_kzt, m.total, rtol=0, atol=0.01)
        bad_count = m.n_tx != m['count']
        require(not bad_sum.any(), f'edges/transactions: amount mismatch for {m.loc[bad_sum, ["src", "dst"]].head().to_dict("records")}')
        require(not bad_count.any(), f'edges/transactions: transaction count mismatch for {m.loc[bad_count, ["src", "dst"]].head().to_dict("records")}')
    orphans = gids - set(edges.src) - set(edges.dst)
    warnings = []
    same_rows = int(tx.duplicated(['src', 'dst', 'date', 'sum_kzt']).sum())
    if same_rows:
        warnings.append(f'{same_rows} identical transaction rows retained: no transaction_id to prove duplicates')
    if len(tx) and ((tx.sum_kzt < 5000).any() or not tx.date.between('2026-07-01', '2026-07-31 23:59:59.999999999').all()):
        warnings.append('Transactions outside the described July 2026 / >=5000 KZT scope')
    return {
        'ok': True, 'n_nodes': len(nodes), 'n_edges': len(edges), 'n_transactions': len(tx),
        'n_seed': int(nodes.is_seed.sum()), 'n_isolated': len(orphans),
        'n_isolated_seed': len(orphans & set(nodes.loc[nodes.is_seed, 'gid'])),
        'sum_kzt': float(math.fsum(edges.sum_kzt)),
        'max_pair_amount_error_kzt': float((m.sum_kzt-m.total).abs().max()) if len(m) else 0.0,
        'period_start': tx.date.min().isoformat() if len(tx) else None,
        'period_end': tx.date.max().isoformat() if len(tx) else None,
        'identical_transaction_rows': same_rows, 'warnings': warnings,
    }


def build_graph(edges: pd.DataFrame, nodes: pd.DataFrame) -> nx.DiGraph:
    G = nx.DiGraph()
    for r in nodes.sort_values('gid').itertuples(index=False):
        G.add_node(r.gid, depth=int(r.depth), is_seed=bool(r.is_seed))
    for r in edges.sort_values(['src', 'dst']).itertuples(index=False):
        G.add_edge(r.src, r.dst, sum_kzt=float(r.sum_kzt), n_tx=int(r.n_tx), depth=int(r.depth))
    return G


def basic_features(G: nx.DiGraph, nodes: pd.DataFrame) -> pd.DataFrame:
    """Starter metrics, now including isolates in the PageRank population."""
    df = nodes[['gid', 'depth', 'is_seed']].sort_values('gid').reset_index(drop=True).copy()
    for field, degree in (
        ('in_deg', G.in_degree()), ('out_deg', G.out_degree()),
        ('in_kzt', G.in_degree(weight='sum_kzt')), ('out_kzt', G.out_degree(weight='sum_kzt')),
        ('in_tx', G.in_degree(weight='n_tx')), ('out_tx', G.out_degree(weight='n_tx')),
    ):
        df[field] = df.gid.map(dict(degree)).astype(float if field.endswith('kzt') else 'int64')
    df['pagerank'] = df.gid.map(nx.pagerank(G, weight='sum_kzt', alpha=0.85, tol=1e-10, max_iter=1000))
    df['pass_through'] = df.out_kzt / df.in_kzt.replace(0, np.nan)
    df['truncated_by_depth'] = (df.depth == 4) & (df.out_deg == 0)
    df['boundary_depth'] = df.depth == 4
    df['isolated'] = (df.in_deg + df.out_deg) == 0
    df['seed_inflow_incomplete'] = df.is_seed
    df['pass_through_reliable'] = (df.in_kzt > 0) & ~df.is_seed & ~df.boundary_depth
    seeds = set(df.loc[df.is_seed, 'gid'])
    df['seed_in_neighbors'] = df.gid.map(lambda gid: len(set(G.predecessors(gid)) & seeds))
    df['turnover_kzt'] = df.in_kzt + df.out_kzt
    return df


def cluster_graph(G: nx.DiGraph, seed: int = 42, resolution: float = 1.0):
    U = nx.Graph()
    U.add_nodes_from(sorted(G.nodes))
    for u, v, attrs in sorted(G.edges(data=True)):
        if u == v:
            continue
        weight = U[u][v]['weight'] if U.has_edge(u, v) else 0.0
        U.add_edge(u, v, weight=weight + attrs['sum_kzt'])
    isolates = sorted(nx.isolates(U))
    active = U.subgraph(sorted(set(U) - set(isolates))).copy()
    communities = nx.community.louvain_communities(active, weight='weight', seed=seed, resolution=resolution) if active.number_of_edges() else []
    communities += [{gid} for gid in isolates]
    communities = sorted(communities, key=lambda c: min(c))
    mapping = {gid: cid for cid, members in enumerate(communities) for gid in sorted(members)}
    modularity = nx.community.modularity(U, communities, weight='weight', resolution=resolution) if U.number_of_edges() else 0.0
    return mapping, {
        'algorithm': 'louvain', 'seed': seed, 'resolution': resolution,
        'projection': 'sum_kzt(u,v)+sum_kzt(v,u); self-loops excluded; isolates singleton',
        'n_clusters': len(communities), 'modularity': float(modularity),
        'networkx_version': nx.__version__,
    }
