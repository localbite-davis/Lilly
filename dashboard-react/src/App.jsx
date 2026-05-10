import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import {
  ClipboardList,
  History,
  FileText,
  BarChart3,
  CheckCircle2,
  Activity,
  RefreshCw,
  AlertTriangle,
  Loader2,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

const BASE_URL = '/api/portal';

export default function App() {
  const [currentView, setCurrentView] = useState('queue');
  const [cases, setCases] = useState([]);
  const [pastCases, setPastCases] = useState([]);
  const [standingOrders, setStandingOrders] = useState([]);
  const [analytics, setAnalytics] = useState({});
  const [patients, setPatients] = useState([]);
  const [resolvedIds, setResolvedIds] = useState(new Set());
  const [timers, setTimers] = useState({});
  const [toast, setToast] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Load patients once for standing orders dropdown
  useEffect(() => {
    axios.get(`${BASE_URL}/patients`)
      .then(res => setPatients(res.data))
      .catch(() => {}); // silently fail — dropdown falls back to static options
  }, []);

  // Fetch data on view change and interval
  useEffect(() => {
    fetchView(currentView);
    const interval = setInterval(() => fetchView(currentView), 15000);
    return () => clearInterval(interval);
  }, [currentView]);

  // Countdown timer effect
  useEffect(() => {
    const timer = setInterval(() => {
      setTimers(prev => {
        const next = { ...prev };
        let changed = false;
        Object.keys(next).forEach(id => {
          if (!resolvedIds.has(Number(id)) && next[id] > 0) {
            next[id] -= 1;
            changed = true;
          }
        });
        return changed ? next : prev;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [resolvedIds]);

  const fetchView = async (view, silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      if (view === 'queue') {
        const res = await axios.get(`${BASE_URL}/queue`);
        setCases(res.data);
        setTimers(prev => {
          const next = { ...prev };
          res.data.forEach(c => {
            if (next[c.id] === undefined && c.timer !== null) {
              next[c.id] = c.timer;
            }
          });
          return next;
        });
      } else if (view === 'past') {
        const res = await axios.get(`${BASE_URL}/past`);
        setPastCases(res.data);
      } else if (view === 'standing') {
        const res = await axios.get(`${BASE_URL}/standing-orders`);
        setStandingOrders(res.data);
      } else if (view === 'analytics') {
        const res = await axios.get(`${BASE_URL}/analytics`);
        setAnalytics(res.data);
      }
    } catch (err) {
      const msg = err.response
        ? `Server error ${err.response.status}: ${JSON.stringify(err.response.data)}`
        : `Could not reach API — is the server running? (${err.message})`;
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const doAction = async (id, type, note = '') => {
    try {
      const res = await axios.post(`${BASE_URL}/cases/${id}/${type}`, { note });
      if (res.status === 200) {
        if (type !== 'note') {
          setResolvedIds(prev => new Set([...prev, id]));
          showToast(type === 'approve' ? 'Care plan authorized' : 'Emergency escalation triggered');
        } else {
          showToast('Clinical note saved');
        }
        fetchView(currentView, true);
      }
    } catch {
      showToast('Action failed — check server logs');
    }
  };

  const showToast = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3500);
  };

  const formatTime = (s) => {
    if (s === null || s === undefined) return '--:--';
    if (s <= 0) return 'EXPIRED';
    return `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, '0')}`;
  };

  const activeCount = cases.filter(c => !resolvedIds.has(c.id)).length;

  return (
    <div className="flex h-screen bg-[#f8fafc] text-[#0f172a] font-sans overflow-hidden">
      {/* Sidebar */}
      <aside className="w-[260px] bg-white border-r border-border p-8 flex flex-col gap-2 z-10 shrink-0">
        <div className="flex items-center gap-3 mb-10 px-3">
          <div className="w-8 h-8 bg-gradient-to-br from-primary to-secondary rounded-lg flex items-center justify-center text-white font-bold text-lg">L</div>
          <div className="text-2xl font-semibold tracking-tight">Lily<span className="text-primary">.</span></div>
        </div>

        <NavButton active={currentView === 'queue'} icon={<ClipboardList size={18}/>} label="Case Queue" badge={activeCount || null} onClick={() => setCurrentView('queue')} />
        <NavButton active={currentView === 'past'} icon={<History size={18}/>} label="Resolution History" onClick={() => setCurrentView('past')} />
        <NavButton active={currentView === 'standing'} icon={<FileText size={18}/>} label="Standing Orders" onClick={() => setCurrentView('standing')} />
        <NavButton active={currentView === 'analytics'} icon={<BarChart3 size={18}/>} label="Clinical Analytics" onClick={() => setCurrentView('analytics')} />

        <div className="mt-auto p-4 bg-bg rounded-xl flex items-center gap-3">
          <div className="w-8 h-8 bg-slate-200 rounded-full flex items-center justify-center text-xs font-bold text-slate-500">Dr</div>
          <div>
            <p className="text-xs font-semibold">Dr. Demo</p>
            <p className="text-[10px] text-text-muted">Attending Physician</p>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 p-12 overflow-y-auto flex flex-col gap-8">
        <header className="flex items-center justify-between">
          <h1 className="text-[28px] font-semibold tracking-tight">
            {currentView === 'queue' && 'Active Intelligence Queue'}
            {currentView === 'past' && 'Clinical Resolution History'}
            {currentView === 'standing' && 'Standing Clinical Orders'}
            {currentView === 'analytics' && 'Maternal Health Analytics'}
          </h1>
          <div className="flex items-center gap-3">
            {loading && <Loader2 size={16} className="text-text-muted animate-spin" />}
            <button
              onClick={() => fetchView(currentView)}
              className="text-text-muted hover:text-primary transition-colors"
              title="Refresh"
            >
              <RefreshCw size={16} />
            </button>
            <div className="bg-[#ecfdf5] text-success px-3.5 py-1.5 rounded-full text-xs font-semibold flex items-center gap-2">
              <div className="w-2 h-2 bg-success rounded-full pulse-animation"></div>
              Live Monitoring Active
            </div>
          </div>
        </header>

        {error && (
          <div className="bg-danger-soft border border-danger/20 rounded-2xl p-5 flex items-start gap-3 text-danger">
            <AlertTriangle size={18} className="shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-sm mb-1">Failed to load data</p>
              <p className="text-xs opacity-80">{error}</p>
            </div>
          </div>
        )}

        <AnimatePresence mode="wait">
          {currentView === 'queue' && (
            <motion.div key="queue" initial={{opacity:0, y:10}} animate={{opacity:1, y:0}} exit={{opacity:0, y:-10}} className="flex flex-col gap-8">
              <StatsSummary cases={cases} resolvedIds={resolvedIds} analytics={analytics} />
              <div className="flex flex-col gap-5">
                {cases.filter(c => !resolvedIds.has(c.id)).map(c => (
                  <CaseCard key={c.id} c={c} timer={timers[c.id]} onAction={doAction} formatTime={formatTime} />
                ))}
                {!loading && !error && cases.filter(c => !resolvedIds.has(c.id)).length === 0 && (
                  <div className="p-16 text-center text-text-muted card">
                    <div className="text-5xl mb-4">✓</div>
                    <p className="font-semibold">Queue is clear — no active clinical escalations</p>
                    <p className="text-xs mt-2">Patients are being monitored by Lily AI</p>
                  </div>
                )}
              </div>
            </motion.div>
          )}

          {currentView === 'past' && (
            <motion.div key="past" initial={{opacity:0, y:10}} animate={{opacity:1, y:0}} exit={{opacity:0, y:-10}}>
              <PastCasesTable pastCases={pastCases} loading={loading} />
            </motion.div>
          )}

          {currentView === 'standing' && (
            <motion.div key="standing" initial={{opacity:0, y:10}} animate={{opacity:1, y:0}} exit={{opacity:0, y:-10}}>
              <StandingOrdersSection orders={standingOrders} patients={patients} onSave={() => fetchView('standing', true)} showToast={showToast} />
            </motion.div>
          )}

          {currentView === 'analytics' && (
            <motion.div key="analytics" initial={{opacity:0, y:10}} animate={{opacity:1, y:0}} exit={{opacity:0, y:-10}}>
              <AnalyticsView analytics={analytics} loading={loading} />
            </motion.div>
          )}
        </AnimatePresence>
      </main>

      {/* Toast Notification */}
      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{y:100, opacity:0}}
            animate={{y:0, opacity:1}}
            exit={{y:100, opacity:0}}
            className="fixed bottom-8 right-8 bg-slate-900 text-white px-6 py-3 rounded-xl text-sm font-medium shadow-2xl z-50"
          >
            {toast}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function NavButton({ active, icon, label, badge, onClick }) {
  return (
    <div
      onClick={onClick}
      className={`flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium cursor-pointer transition-all duration-200 ${
        active ? 'bg-primary text-white shadow-lg shadow-primary/30' : 'text-text-muted hover:bg-primary-soft hover:text-primary'
      }`}
    >
      {icon}
      <span className="flex-1">{label}</span>
      {badge && (
        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${active ? 'bg-white/20 text-white' : 'bg-danger text-white'}`}>
          {badge}
        </span>
      )}
    </div>
  );
}

function StatsSummary({ cases, resolvedIds, analytics }) {
  const activeCount = cases.filter(c => !resolvedIds.has(c.id)).length;
  const handoffCount = cases.filter(c => !resolvedIds.has(c.id) && c.tier === 'hand_off').length;
  const resolvedToday = analytics?.resolved_today ?? resolvedIds.size;

  return (
    <div className="grid grid-cols-4 gap-6">
      <StatCard label="Active Escalations" value={activeCount} trend="Pending physician review" trendUp={activeCount > 0} />
      <StatCard label="Urgent (Hand-off)" value={handoffCount} color={handoffCount > 0 ? 'text-danger' : ''} trend={handoffCount > 0 ? 'Requires immediate action' : 'None critical'} />
      <StatCard label="Response Time (Avg)" value={analytics?.avg_response_time ?? '—'} trend="SLA target: 20 min" />
      <StatCard label="Resolved (Today)" value={resolvedToday} trend="Authorized care plans" trendUp={resolvedToday > 0} />
    </div>
  );
}

function StatCard({ label, value, trend, trendUp, color }) {
  return (
    <div className="bg-white p-6 rounded-2xl border border-border flex flex-col gap-2 hover:translate-y-[-2px] transition-transform hover:shadow-md">
      <p className="text-[13px] text-text-muted font-medium">{label}</p>
      <p className={`text-3xl font-bold ${color}`}>{value}</p>
      <p className={`text-xs font-medium ${trendUp ? 'text-warning' : 'text-text-muted'}`}>{trend}</p>
    </div>
  );
}

function CaseCard({ c, timer, onAction, formatTime }) {
  const [showNote, setShowNote] = useState(false);
  const [noteText, setNoteText] = useState('');
  const expired = timer !== null && timer !== undefined && timer <= 0;
  const urgent = timer !== null && timer !== undefined && timer > 0 && timer < 300;

  const tierMeta = {
    hand_off: { label: '🔴 Emergency Hand-off', style: 'bg-danger-soft text-danger' },
    hand_up: { label: '🟡 Physician Review', style: 'bg-warning-soft text-warning' },
    handle: { label: '🟢 AI Managed', style: 'bg-success-soft text-success' }
  }[c.tier] || { label: '🟡 Review', style: 'bg-slate-100 text-slate-600' };

  return (
    <motion.div
      layout
      className={`bg-white rounded-[20px] border p-8 grid grid-cols-[1fr,220px] gap-8 shadow-sm hover:shadow-md transition-shadow ${
        c.tier === 'hand_off' ? 'border-danger/30' : expired ? 'border-danger/20' : 'border-border'
      }`}
    >
      <div>
        <div className="flex items-center gap-4 mb-6">
          <div className="w-[52px] h-[52px] bg-primary-soft text-primary rounded-2xl flex items-center justify-center font-bold text-xl">{c.initials}</div>
          <div className="flex-1">
            <h3 className="text-lg font-semibold">{c.patient_name}</h3>
            <p className="text-[13px] text-text-muted">{c.stage || 'Clinical Intake'}</p>
          </div>
          <span className={`px-3 py-1 rounded-lg text-[11px] font-bold uppercase tracking-wider ${tierMeta.style}`}>{tierMeta.label}</span>
        </div>

        <div className="grid grid-cols-3 gap-8 bg-bg p-5 rounded-xl mb-6">
          <VitalItem label="Blood Pressure" value={c.bp} alert={c.bp_alert} />
          <VitalItem label="Heart Rate" value={c.hr !== '—' ? `${c.hr} BPM` : '—'} />
          <VitalItem label="Oxygen (SpO₂)" value={c.spo2} />
        </div>

        {c.symptoms.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-6">
            {c.symptoms.map(s => (
              <span key={s} className="bg-white border border-border px-3 py-1 rounded-lg text-xs text-text-muted">
                {s.replace(/_/g, ' ')}
              </span>
            ))}
          </div>
        )}

        <div className="bg-slate-50 border-l-4 border-primary p-4 rounded-r-xl text-sm leading-relaxed text-slate-600 mb-6 italic">
          &ldquo;{c.sbar}&rdquo;
        </div>

        <div className="flex gap-3 flex-wrap">
          <button className="btn btn-primary" onClick={() => onAction(c.id, 'approve')}>Authorize Care Plan</button>
          <button className="btn btn-danger" onClick={() => onAction(c.id, 'escalate')}>Immediate Escalation</button>
          <button className="btn btn-outline" onClick={() => setShowNote(!showNote)}>Add Clinical Note</button>
        </div>

        {showNote && (
          <motion.div initial={{opacity:0, height:0}} animate={{opacity:1, height:'auto'}} className="mt-4 overflow-hidden">
            <textarea
              value={noteText}
              onChange={(e) => setNoteText(e.target.value)}
              className="w-full p-4 border border-border rounded-xl text-sm focus:ring-2 focus:ring-primary/20 outline-none resize-none"
              rows={3}
              placeholder={`Enter note for ${c.patient_name}'s record...`}
            />
            <button className="btn btn-primary mt-2" onClick={() => { onAction(c.id, 'note', noteText); setShowNote(false); setNoteText(''); }}>Save Clinical Note</button>
          </motion.div>
        )}
      </div>

      <div className="border-l border-border pl-8 flex flex-col justify-center items-center text-center">
        {timer !== null && timer !== undefined ? (
          <>
            <div className={`text-[42px] font-mono font-medium tracking-tighter mb-2 ${expired ? 'text-danger animate-pulse' : urgent ? 'timer-urgent' : ''}`}>
              {formatTime(timer)}
            </div>
            <p className="text-[12px] text-text-muted font-bold tracking-widest">SLA TARGET</p>
            {expired && <p className="text-[11px] text-danger font-bold mt-2">⚠️ SLA BREACHED</p>}
            {urgent && !expired && <p className="text-[11px] text-warning font-bold mt-2">⚠️ CRITICAL THRESHOLD</p>}
          </>
        ) : (
          <>
            <div className="text-success flex items-center gap-2 font-semibold mb-1">
              <CheckCircle2 size={18} />
              AI Managed
            </div>
            <p className="text-[11px] text-text-muted font-medium">Real-time Monitoring</p>
          </>
        )}
      </div>
    </motion.div>
  );
}

function VitalItem({ label, value, alert }) {
  return (
    <div>
      <p className="text-[11px] text-text-muted font-bold uppercase mb-1">{label}</p>
      <p className={`font-mono text-base font-semibold ${alert ? 'text-danger' : 'text-slate-700'}`}>{value}</p>
    </div>
  );
}

function PastCasesTable({ pastCases, loading }) {
  const statusStyle = {
    resolved: 'bg-success-soft text-success',
    escalated_by_doctor: 'bg-danger-soft text-danger',
    auto_escalated: 'bg-warning-soft text-warning',
  };

  return (
    <div className="card p-0 overflow-hidden shadow-sm">
      <table className="w-full text-left border-collapse">
        <thead className="bg-slate-50 border-b border-border">
          <tr>
            <th className="p-5 pl-8 text-xs font-bold text-text-muted tracking-widest">PATIENT</th>
            <th className="p-5 text-xs font-bold text-text-muted tracking-widest">STAGE</th>
            <th className="p-5 text-xs font-bold text-text-muted tracking-widest">RESOLUTION</th>
            <th className="p-5 text-xs font-bold text-text-muted tracking-widest">DATE</th>
            <th className="p-5 text-xs font-bold text-text-muted tracking-widest">SYMPTOMS</th>
          </tr>
        </thead>
        <tbody>
          {pastCases.map(c => (
            <tr key={c.id} className="border-b border-slate-50 hover:bg-slate-50 transition-colors">
              <td className="p-5 pl-8">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 bg-slate-100 text-slate-600 rounded-lg flex items-center justify-center text-xs font-bold">{c.initials}</div>
                  <span className="font-semibold text-sm">{c.patient_name}</span>
                </div>
              </td>
              <td className="p-5 text-sm text-slate-500">{c.stage}</td>
              <td className="p-5">
                <span className={`px-3 py-1 rounded-lg text-[10px] font-bold uppercase tracking-wider ${statusStyle[c.status] || 'bg-slate-100 text-slate-600'}`}>
                  {c.status.replace(/_/g, ' ')}
                </span>
              </td>
              <td className="p-5 text-sm text-slate-500">
                {c.resolved_at ? new Date(c.resolved_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'}
              </td>
              <td className="p-5 text-sm text-text-muted">
                {(c.symptoms || []).map(s => s.replace(/_/g, ' ')).join(', ')}
              </td>
            </tr>
          ))}
          {!loading && pastCases.length === 0 && (
            <tr>
              <td colSpan={5} className="p-12 text-center text-text-muted text-sm">No resolved cases yet</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function StandingOrdersSection({ orders, patients, onSave, showToast }) {
  const [patientId, setPatientId] = useState('');
  const [condition, setCondition] = useState('');
  const [intervention, setIntervention] = useState('');

  const handleSubmit = async () => {
    if (!condition || !intervention) return;
    try {
      await axios.post(`${BASE_URL}/standing-orders`, { patient_id: patientId || null, condition, intervention });
      showToast('Order authorized successfully');
      setCondition('');
      setIntervention('');
      onSave();
    } catch {
      showToast('Failed to save order');
    }
  };

  return (
    <div className="flex flex-col gap-8">
      <div className="card">
        <h2 className="text-xl font-semibold mb-6 flex items-center gap-2"><Activity className="text-primary" size={20}/> New Clinical Standing Order</h2>
        <div className="grid grid-cols-[1fr,1.5fr,1.5fr,auto] gap-4 items-end">
          <div className="flex flex-col gap-2">
            <label className="text-[11px] font-bold text-text-muted uppercase">Patient</label>
            <select value={patientId} onChange={e => setPatientId(e.target.value)} className="p-3 border border-border rounded-xl text-sm outline-none focus:ring-2 focus:ring-primary/20 bg-white">
              <option value="">Select patient...</option>
              {patients.map(p => (
                <option key={p.id} value={p.id}>{p.first_name} {p.last_name} · {p.gestational_stage}</option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-2">
            <label className="text-[11px] font-bold text-text-muted uppercase">Clinical Trigger</label>
            <input type="text" value={condition} onChange={e => setCondition(e.target.value)} placeholder="e.g. BP ≥ 140/90 on two readings" className="p-3 border border-border rounded-xl text-sm outline-none focus:ring-2 focus:ring-primary/20" />
          </div>
          <div className="flex flex-col gap-2">
            <label className="text-[11px] font-bold text-text-muted uppercase">Automated Intervention</label>
            <input type="text" value={intervention} onChange={e => setIntervention(e.target.value)} placeholder="e.g. Take labetalol 200mg, go to L&D" className="p-3 border border-border rounded-xl text-sm outline-none focus:ring-2 focus:ring-primary/20" />
          </div>
          <button className="btn btn-primary h-[46px] whitespace-nowrap" onClick={handleSubmit}>Authorize Order</button>
        </div>
      </div>

      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-bold text-text-muted uppercase tracking-widest px-2">Active Authorized Orders ({orders.length})</h3>
        {orders.length === 0 && (
          <div className="card text-center text-text-muted py-12 text-sm">No standing orders — authorize one above</div>
        )}
        {orders.map(o => (
          <div key={o.id} className="bg-white border border-border p-5 rounded-2xl flex justify-between items-center hover:shadow-sm transition-shadow">
            <div className="flex-1 min-w-0 mr-6">
              <div className="flex items-center gap-2 mb-1">
                <span className="font-semibold text-[15px]">{o.patient_name}</span>
                <span className="text-slate-300 mx-1">→</span>
                <span className="text-sm text-slate-700 truncate">{o.condition}</span>
              </div>
              <p className="text-sm text-primary font-medium">Intervention: {o.intervention}</p>
            </div>
            <div className="text-right shrink-0">
              <p className="text-[10px] text-text-muted uppercase font-bold tracking-tighter">Authorized by</p>
              <p className="text-sm font-semibold">{o.doctor_name}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AnalyticsView({ analytics, loading }) {
  const g = analytics.global_crisis || {};
  const l = analytics.lilly_stats || {};

  if (loading && !analytics.resolved_today) {
    return (
      <div className="flex items-center justify-center p-24 text-text-muted">
        <Loader2 size={24} className="animate-spin mr-3" /> Loading analytics...
      </div>
    );
  }

  return (
    <div className="grid grid-cols-[1fr,1.2fr] gap-8">
      <div className="flex flex-col gap-8">
        <div className="card border-l-[6px] border-primary">
          <h3 className="text-lg font-semibold mb-6 flex items-center gap-2">🌸 Lilly Operational Impact</h3>
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-bg p-4 rounded-xl">
              <p className="text-[11px] font-bold text-text-muted uppercase">Lives Saved (est)</p>
              <p className="text-2xl font-bold text-primary mt-1">{l.lives_saved_estimate ?? '—'}</p>
            </div>
            <div className="bg-bg p-4 rounded-xl">
              <p className="text-[11px] font-bold text-text-muted uppercase">Care Centers</p>
              <p className="text-2xl font-bold mt-1">{l.care_hubs ?? '—'}</p>
            </div>
            <div className="bg-bg p-4 rounded-xl">
              <p className="text-[11px] font-bold text-text-muted uppercase">Patients Monitored</p>
              <p className="text-2xl font-bold mt-1">{l.patients_monitored ?? '—'}</p>
            </div>
            <div className="bg-bg p-4 rounded-xl">
              <p className="text-[11px] font-bold text-text-muted uppercase">Critical Escalations</p>
              <p className="text-2xl font-bold text-danger mt-1">{l.critical_escalations ?? '—'}</p>
            </div>
          </div>
        </div>

        <div className="card border-l-[6px] border-danger">
          <h3 className="text-lg font-semibold mb-6 flex items-center gap-2 text-danger">🚨 Global Maternal Crisis</h3>
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-danger-soft p-4 rounded-xl">
              <p className="text-[11px] font-bold text-danger uppercase opacity-70">Daily Preventable Deaths</p>
              <p className="text-2xl font-bold text-danger mt-1">{g.daily_preventable_deaths ?? '—'}</p>
            </div>
            <div className="bg-bg p-4 rounded-xl">
              <p className="text-[11px] font-bold text-text-muted uppercase">Annual Mortality</p>
              <p className="text-2xl font-bold mt-1">{g.annual_maternal_mortality?.toLocaleString() ?? '—'}</p>
            </div>
            <div className="bg-bg p-4 rounded-xl">
              <p className="text-[11px] font-bold text-text-muted uppercase">Preeclampsia Rate</p>
              <p className="text-2xl font-bold mt-1">{g.preeclampsia_prevalence ?? '—'}</p>
            </div>
            <div className="bg-danger-soft p-4 rounded-xl">
              <p className="text-[11px] font-bold text-danger uppercase opacity-70">Preventable</p>
              <p className="text-2xl font-bold text-danger mt-1">{g.preventable_percentage ?? '—'}</p>
            </div>
          </div>
        </div>
      </div>

      <div className="card relative">
        <h3 className="text-lg font-semibold mb-8 flex items-center gap-2">Clinical Triage Velocity</h3>
        <div className="flex items-end justify-between h-[280px] gap-4 px-4">
          {[40, 65, 80, 55, 90, 45, 30].map((h, i) => (
            <motion.div
              key={i}
              initial={{height: 0}}
              animate={{height: `${h}%`}}
              className="flex-1 bg-primary-soft rounded-lg relative group cursor-pointer"
            >
              <div className="absolute inset-0 bg-primary opacity-0 group-hover:opacity-100 transition-opacity rounded-lg" />
              <small className="absolute -bottom-7 left-1/2 -translate-x-1/2 text-[10px] font-bold text-text-muted uppercase tracking-tighter">
                {['M','T','W','T','F','S','S'][i]}
              </small>
            </motion.div>
          ))}
        </div>
        <div className="mt-6 text-center text-xs text-text-muted pt-4">Cases handled per day this week</div>
      </div>
    </div>
  );
}
