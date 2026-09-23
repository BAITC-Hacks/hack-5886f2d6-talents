import { useEffect, useRef } from 'react';
import cytoscape, { type Core } from 'cytoscape';
import { Maximize, Minus, Plus } from 'lucide-react';
import { transferKey } from './transfers';
import { clusterColor, roleColors, type Client, type Transfer } from './data';

interface Props {
  nodes: Client[]; edges: Transfer[]; selected: string | null; colorBy: 'role' | 'cluster';
  onSelect: (gid: string) => void; overview: boolean;
  selectedTransfer: string | null; onSelectTransfer: (key: string) => void;
}
export default function GraphView({ nodes, edges, selected, colorBy, onSelect, overview, selectedTransfer, onSelectTransfer }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const graph = useRef<Core | null>(null);
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;
  const transferRef = useRef(onSelectTransfer);
  transferRef.current = onSelectTransfer;
  useEffect(() => {
    if (!container.current) return;
    const cy = cytoscape({
      container: container.current, elements: [], minZoom: 0.01, maxZoom: 3,
      boxSelectionEnabled: false,
      style: [
        { selector: 'node', style: {
          'background-color': 'data(color)', width: 31, height: 31,
          label: 'data(label)', 'font-family': 'Segoe UI, sans-serif', 'font-size': 10,
          color: '#465266', 'text-valign': 'bottom', 'text-margin-y': 7,
          'border-width': 3, 'border-color': '#ffffff', 'text-background-color': '#f8fafc',
          'text-background-opacity': 0.8, 'text-background-padding': '2px',
        } },
        { selector: 'edge', style: {
          width: 1.6, 'line-color': '#bac7d5', 'target-arrow-color': '#8a9aac',
          'target-arrow-shape': 'triangle', 'curve-style': 'bezier', 'arrow-scale': 1.15,
          opacity: 0.8, 'overlay-padding': 7, 'overlay-opacity': 0,
        } },
        { selector: 'node[seed = 1]', style: { shape: 'diamond', width: 40, height: 40 } },
        { selector: 'node.active', style: { 'border-width': 5, 'border-color': '#182b45', width: 43, height: 43, 'font-weight': 'bold', 'z-index': 10 } },
        { selector: 'edge.connected', style: { 'line-color': '#6b839f', 'target-arrow-color': '#405c7d', width: 2.5, opacity: 1 } },
        { selector: 'edge.chosen', style: { 'line-color': '#146c5a', 'target-arrow-color': '#146c5a', width: 4.5, opacity: 1, 'z-index': 20 } },
      ],
    });
    graph.current = cy;
    cy.on('tap', 'node', event => selectRef.current(event.target.data('gid')));
    cy.on('tap', 'edge', event => transferRef.current(event.target.data('transferKey')));
    const resize = new ResizeObserver(() => { cy.resize(); cy.fit(undefined, 48); });
    resize.observe(container.current);
    return () => { resize.disconnect(); cy.destroy(); graph.current = null; };
  }, []);
  useEffect(() => {
    const cy = graph.current;
    if (!cy) return;
    const nodeKeys = new Map(nodes.map((node, i) => [node.gid, 'n' + i]));
    const groups = [...new Set(nodes.map(n => n.cluster))];
    const groupIndex = new Map(groups.map((g, i) => [g, i]));
    const groupNodes = new Map(groups.map(g => [g, nodes.filter(n => n.cluster === g)]));
    const spacing = Math.max(260, ...[...groupNodes.values()].map(group => Math.sqrt(group.length) * 66 + 160));
    cy.batch(() => {
      cy.elements().remove();
      cy.add(nodes.map(node => {
        const group = groupNodes.get(node.cluster)!;
        const i = group.indexOf(node), count = group.length, g = groupIndex.get(node.cluster)!;
        const angle = i * Math.PI * 2 / Math.max(count, 1);
        const radius = Math.max(65, Math.sqrt(count) * 33);
        const columns = Math.ceil(Math.sqrt(groups.length));
        return { data: { id: nodeKeys.get(node.gid)!, gid: node.gid, label: overview && nodes.length > 100 ? '' : node.gid.length > 12 ? '…' + node.gid.slice(-8) : node.gid, seed: node.is_seed ? 1 : 0, color: roleColors[node.role] },
          position: { x: (g % columns) * spacing + Math.cos(angle) * radius, y: Math.floor(g / columns) * spacing + Math.sin(angle) * radius } };
      }));
      cy.add(edges.map((edge, i) => ({ data: { id: 'e' + i, transferKey: transferKey(edge), source: nodeKeys.get(edge.source)!, target: nodeKeys.get(edge.target)! } })));
    });
    cy.layout(overview || nodes.length > 150
      ? { name: 'preset', fit: true, padding: 55 }
      : nodes.length <= 20 ? { name: 'concentric', fit: true, padding: 55, minNodeSpacing: 65, concentric: node => node.data('gid') === selected ? 2 : 1, levelWidth: () => 1, nodeDimensionsIncludeLabels: true } : { name: 'cose', animate: false, fit: true, padding: 55, nodeRepulsion: () => 16000, idealEdgeLength: () => 155, componentSpacing: 95, numIter: 400, randomize: false }).run();
  }, [nodes, edges, overview, selected]);
  useEffect(() => {
    const cy = graph.current;
    if (!cy) return;
    const lookup = new Map(nodes.map(node => [node.gid, node]));
    cy.batch(() => {
      cy.nodes().forEach(element => {
        const node = lookup.get(element.data('gid'))!;
        element.data('color', colorBy === 'role' ? roleColors[node.role] : clusterColor(node.cluster));
        element.toggleClass('active', node.gid === selected);
      });
      cy.edges().removeClass('connected');
      cy.nodes('.active').connectedEdges().addClass('connected');
      cy.edges().forEach(element => { element.toggleClass('chosen', element.data('transferKey') === selectedTransfer); });
    });
  }, [nodes, edges, colorBy, selected, overview, selectedTransfer]);
  return <div className="graph-surface">
    <div ref={container} className="cytoscape" role="img" aria-label={'Направленный граф: ' + nodes.length + ' клиентов, ' + edges.length + ' связей. Выберите клиента в списке или перевод в списке связей над графом.'} />
    {nodes.length === 0 && <div className="graph-empty">Нет клиентов для выбранных фильтров</div>}
    <div className="graph-controls">
      <button aria-label="Увеличить граф" onClick={() => graph.current?.zoom({ level: graph.current.zoom() * 1.25, renderedPosition: { x: (container.current?.clientWidth ?? 0) / 2, y: (container.current?.clientHeight ?? 0) / 2 } })}><Plus size={17} /></button>
      <button aria-label="Уменьшить граф" onClick={() => graph.current?.zoom(graph.current.zoom() / 1.25)}><Minus size={17} /></button>
      <button aria-label="Показать граф целиком" onClick={() => graph.current?.fit(undefined, 48)}><Maximize size={16} /></button>
    </div>
    <div className="graph-hint">Нажмите на связь: сумма и операции · ромб — исходный клиент · подписи: последние 8 цифр gid</div>
  </div>;
}
