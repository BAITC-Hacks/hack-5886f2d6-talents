import type { Transfer } from './data';

// A directed pair remains stable when filters reorder Cytoscape elements.
export const transferKey = (edge: Pick<Transfer, 'source' | 'target'>): string =>
  JSON.stringify([edge.source, edge.target]);

export function findTransfer(edges: Transfer[], key: string | null): Transfer | undefined {
  return key === null ? undefined : edges.find(edge => transferKey(edge) === key);
}
