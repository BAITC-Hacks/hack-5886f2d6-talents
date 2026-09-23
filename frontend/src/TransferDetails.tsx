import { ArrowDown, ArrowLeft, ArrowLeftRight } from 'lucide-react';
import type { Transfer } from './data';

const money = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const count = new Intl.NumberFormat('ru-RU');
interface Props {
  transfer: Transfer;
  reverse?: Transfer;
  onSelectClient: (gid: string) => void;
  onReverse: () => void;
  onClose: () => void;
}
export default function TransferDetails({ transfer, reverse, onSelectClient, onReverse, onClose }: Props) {
  return <aside className="details-panel transfer-details" aria-label="Карточка связи">
    <div className="panel-heading"><span className="eyebrow">ВЫБРАННАЯ СВЯЗЬ</span></div>
    <h2>Направление перевода</h2>
    <div className="transfer-route">
      <div><span>Отправитель · src</span><button onClick={() => onSelectClient(transfer.source)} aria-label={'Открыть отправителя ' + transfer.source}>{transfer.source}</button></div>
      <ArrowDown size={20} aria-label="Перевод от отправителя к получателю"/>
      <div><span>Получатель · dst</span><button onClick={() => onSelectClient(transfer.target)} aria-label={'Открыть получателя ' + transfer.target}>{transfer.target}</button></div>
    </div>
    <dl className="transfer-values">
      <div><dt>Сумма переводов</dt><dd>{transfer.amount === null ? 'Нет данных' : money.format(transfer.amount) + ' ₸'}</dd></div>
      <div><dt>Количество переводов</dt><dd>{transfer.transactions === null ? 'Нет данных' : count.format(transfer.transactions)}</dd></div>
    </dl>
    <p className="muted">Сумма и количество операций от отправителя к получателю в открытой выгрузке. Это одна направленная связь, без вычитания встречных переводов.</p>
    {transfer.source === transfer.target ? <p className="transfer-note">Перевод самому себе. Такие операции исключены из оценки роли и приоритета.</p> : reverse ? <button className="reverse-transfer" onClick={onReverse}><ArrowLeftRight size={16}/> Показать встречные переводы</button> : <p className="transfer-note">Встречная связь в этой выгрузке не наблюдается.</p>}
    <div className="limitations"><h3>Границы наблюдения</h3><p>Связь показывает операции в пределах периода, порога и банка из выгрузки. Она сама по себе не доказывает роль клиента или движение тех же денег дальше.</p></div>
    <button className="back-to-client" onClick={onClose}><ArrowLeft size={16}/> Вернуться к карточке клиента</button>
  </aside>;
}
