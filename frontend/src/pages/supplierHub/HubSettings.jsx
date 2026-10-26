import { useSearchParams } from 'react-router-dom';
import Tabs from '../../components/common/Tabs';
import PolicySettings from '../../features/supplierHub/settings/PolicySettings';
import TelegramSettings from '../../features/supplierHub/settings/TelegramSettings';

const PANES = [
  { id: 'rules', label: 'Aturan otonomi', el: PolicySettings },
  { id: 'telegram', label: 'Koneksi Telegram', el: TelegramSettings },
];

// Sub-tab disimpan di URL (?tab=) agar bisa ditautkan, mis. dari banner Telegram terputus.
export default function HubSettings() {
  const [params, setParams] = useSearchParams();
  const pane = PANES.find((p) => p.id === params.get('tab')) ?? PANES[0];
  const Pane = pane.el;
  return (
    <>
      <div className="mb-4 overflow-x-auto">
        <Tabs variant="segmented" value={pane.id} onChange={(id) => setParams({ tab: id }, { replace: true })} tabs={PANES} />
      </div>
      <Pane />
    </>
  );
}
