import React, { useState, useEffect } from 'react';
import Navbar from './components/Navbar';
import Sidebar from './components/Sidebar';
import Toast from './components/Toast';

import OverviewPage from './pages/OverviewPage';
import NamespacesPage from './pages/NamespacesPage';
import ZombiePage from './pages/ZombiePage';
import RightSizingPage from './pages/RightSizingPage';
import ActionHistoryPage from './pages/ActionHistoryPage';
import LifecyclePage from './pages/LifecyclePage';
import SettingsPage from './pages/SettingsPage';

const API_BASE = '/api';

export default function App() {
  const [activeTab, setActiveTab] = useState('overview');
  const [overview, setOverview] = useState(null);
  const [trend, setTrend] = useState([]);
  const [namespaces, setNamespaces] = useState([]);
  const [zombies, setZombies] = useState([]);
  const [recommendations, setRecommendations] = useState([]);
  const [actionHistory, setActionHistory] = useState([]);
  const [lifecycle, setLifecycle] = useState(null);
  const [settings, setSettings] = useState(null);

  const [isRefreshing, setIsRefreshing] = useState(false);
  const [toast, setToast] = useState(null);

  const fetchAllData = async () => {
    setIsRefreshing(true);
    try {
      const [ovRes, trRes, nsRes, zbRes, recRes, actRes, lcRes, stRes] = await Promise.all([
        fetch(`${API_BASE}/overview`).then(r => r.json()),
        fetch(`${API_BASE}/cost-trend?range=30d`).then(r => r.json()),
        fetch(`${API_BASE}/namespaces`).then(r => r.json()),
        fetch(`${API_BASE}/zombies`).then(r => r.json()),
        fetch(`${API_BASE}/recommendations`).then(r => r.json()),
        fetch(`${API_BASE}/actions/history`).then(r => r.json()),
        fetch(`${API_BASE}/lifecycle`).then(r => r.json()),
        fetch(`${API_BASE}/settings`).then(r => r.json()),
      ]);

      setOverview(ovRes);
      setTrend(trRes);
      setNamespaces(nsRes);
      setZombies(zbRes);
      setRecommendations(recRes);
      setActionHistory(actRes);
      setLifecycle(lcRes);
      setSettings(stRes);
    } catch (err) {
      console.error('API Fetch error:', err);
    } finally {
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    fetchAllData();
    // Poll telemetry every 15s
    const interval = setInterval(fetchAllData, 15000);
    return () => clearInterval(interval);
  }, []);

  const fetchPods = async (namespaceName) => {
    const res = await fetch(`${API_BASE}/namespaces/${namespaceName}/pods`);
    return await res.json();
  };

  const handleRemediateZombie = async (id) => {
    const res = await fetch(`${API_BASE}/zombies/${id}/remediate`, { method: 'POST' });
    if (res.ok) {
      const action = await res.json();
      setToast({ message: `Zombie workload scaled to 0! Realized $${action.monthly_savings.toFixed(2)}/mo savings.`, type: 'success' });
      fetchAllData();
    } else {
      setToast({ message: 'Failed to remediate zombie workload.', type: 'error' });
    }
  };

  const handleApplyRecommendation = async (id) => {
    const res = await fetch(`${API_BASE}/recommendations/${id}/apply`, { method: 'POST' });
    if (res.ok) {
      const action = await res.json();
      setToast({ message: `Patched container requests! Realized $${action.monthly_savings.toFixed(2)}/mo savings.`, type: 'success' });
      fetchAllData();
    } else {
      setToast({ message: 'Failed to apply recommendation.', type: 'error' });
    }
  };

  const handleSaveSettings = async (newSettings) => {
    const res = await fetch(`${API_BASE}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newSettings)
    });
    if (res.ok) {
      setToast({ message: 'FinOps settings & pricing updated successfully!', type: 'success' });
      fetchAllData();
    } else {
      setToast({ message: 'Failed to update settings.', type: 'error' });
    }
  };

  const zombieActiveCount = (zombies || []).filter(z => z.status === 'ACTIVE').length;
  const recPendingCount = (recommendations || []).filter(r => r.status === 'PENDING').length;

  return (
    <div className="min-h-screen bg-[#090D16] text-slate-100 flex flex-col font-sans">
      <Navbar
        overviewData={overview}
        onRefresh={fetchAllData}
        isRefreshing={isRefreshing}
      />

      <div className="flex-1 flex overflow-hidden">
        <Sidebar
          activeTab={activeTab}
          setActiveTab={setActiveTab}
          zombieCount={zombieActiveCount}
          recCount={recPendingCount}
        />

        <main className="flex-1 p-8 overflow-y-auto max-w-7xl mx-auto w-full space-y-6">
          {activeTab === 'overview' && (
            <OverviewPage
              overviewData={overview}
              trendData={trend}
              namespacesData={namespaces}
              onNavigate={setActiveTab}
            />
          )}

          {activeTab === 'namespaces' && (
            <NamespacesPage
              namespacesData={namespaces}
              fetchPods={fetchPods}
            />
          )}

          {activeTab === 'zombies' && (
            <ZombiePage
              zombiesData={zombies}
              onRemediateZombie={handleRemediateZombie}
            />
          )}

          {activeTab === 'rightsizing' && (
            <RightSizingPage
              recommendationsData={recommendations}
              onApplyRecommendation={handleApplyRecommendation}
            />
          )}

          {activeTab === 'history' && (
            <ActionHistoryPage
              actionHistoryData={actionHistory}
            />
          )}

          {activeTab === 'lifecycle' && (
            <LifecyclePage
              lifecycleData={lifecycle}
            />
          )}

          {activeTab === 'settings' && (
            <SettingsPage
              settingsData={settings}
              onSaveSettings={handleSaveSettings}
            />
          )}
        </main>
      </div>

      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
        />
      )}
    </div>
  );
}
