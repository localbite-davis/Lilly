import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { 
  ClipboardList, 
  History, 
  FileText, 
  BarChart3, 
  AlertCircle, 
  CheckCircle2, 
  MessageSquare, 
  Clock, 
  Activity,
  ArrowUpRight,
  TrendingUp,
  TrendingDown
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

const BASE_URL = '/api/portal';

export default function App() {
  const [currentView, setCurrentView] = useState('queue');
  const [cases, setCases] = useState([]);
  const [pastCases, setPastCases] = useState([]);
  const [standingOrders, setStandingOrders] = useState([]);
  const [analytics, setAnalytics] = useState({});
  const [resolvedIds, setResolvedIds] = useState(new Set());
  const [timers, setTimers] = useState({});
  const [toast, setToast] = useState(null);

  // Fetch data on interval
  useEffect(() => {
    refreshData();
    const interval = setInterval(refreshData, 15000);
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

  const refreshData = async () => {
    try {
      if (currentView === 'queue') {
        const res = await axios.get(`${BASE_URL}/queue`);
        setCases(res.data);
        // Initialize timers for new cases
        setTimers(prev => {
          const next = { ...prev };
          res.data.forEach(c => {
            if (next[c.id] === undefined && c.timer !== null) {
              next[c.id] = c.timer;
            }
          });
          return next;
        });
      } else if (currentView === 'past') {
        const res = await axios.get(`${BASE_URL}/past`);
        setPastCases(res.data);
      } else if (currentView === 'standing') {
        const res = await axios.get(`${BASE_URL}/standing-orders`);
        setStandingOrders(res.data);
      } else if (currentView === 'analytics') {
        const res = await axios.get(`${BASE_URL}/analytics`);
        setAnalytics(res.data);
      }
    } catch (err) {
      console.error("Data refresh failed", err);
    }
  };

  const doAction = async (id, type, note = '') => {
    try {
      const res = await axios.post(`${BASE_URL}/cases/${id}/${type}`, { note });
      if (res.status === 200) {
        if (type !== 'note') {
          setResolvedIds(prev => new Set([...prev, id]));
          showToast(type === 'approve' ? 'Plan authorized' : 'Emergency escalation triggered');
        } else {
          showToast('Clinical note saved');
        }
        refreshData();
      }
    } catch (err) {
      showToast('Action failed');
    }
  };

  const showToast = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3000);
  };

  const formatTime = (s) => {
    if (s === null || s === undefined) return '--:--';
    return `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, '0')}`;
  };

  return (
    <div className="flex h-screen bg-[#f8fafc] text-[#0f172a] font-sans overflow-hidden">
      {/* Sidebar */}
      <aside className="w-[260px] bg-white border-r border-border p-8 flex flex-col gap-2 z-10">
        <div className="flex items-center gap-3 mb-10 px-3">
          <div className="w-8 height-8 bg-gradient-to-br from-primary to-secondary rounded-lg flex items-center justify-center text-white font-bold text-lg">L</div>
          <div className="text-2xl font-semibold tracking-tight">Lily<span className="text-primary">.</span></div>
        </div>
        
        <NavButton active={currentView === 'queue'} icon={<ClipboardList size={18}/>} label="Case Queue" onClick={() => setCurrentView('queue')} />
        <NavButton active={currentView === 'past'} icon={<History size={18}/>} label="Resolution History" onClick={() => setCurrentView('past')} />
        <NavButton active={currentView === 'standing'} icon={<FileText size={18}/>} label="Standing Orders" onClick={() => setCurrentView('standing')} />
        <NavButton active={currentView === 'analytics'} icon={<BarChart3 size={18}/>} label="Clinical Analytics" onClick={() => setCurrentView('analytics')} />

        <div className="mt-auto p-4 bg-bg rounded-xl flex items-center gap-3">
          <div className="w-8 h-8 bg-slate-200 rounded-full"></div>
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
          <div className="bg-[#ecfdf5] text-success px-3.5 py-1.5 rounded-full text-xs font-semibold flex items-center gap-2">
            <div className="w-2 h-2 bg-success rounded-full pulse-animation"></div>
            Live Monitoring Active
          </div>
        </header>

        <AnimatePresence mode="wait">
          {currentView === 'queue' && (
            <motion.div key="queue" initial={{opacity:0, y:10}} animate={{opacity:1, y:0}} exit={{opacity:0, y:-10}} className="flex flex-col gap-8">
              <StatsSummary cases={cases} resolvedCount={resolvedIds.size + 7} />
              <div className="flex flex-col gap-5">
                {cases.filter(c => !resolvedIds.has(c.id)).map(c => (
                  <CaseCard key={c.id} c={c} timer={timers[c.id]} onAction={doAction} formatTime={formatTime} />
                ))}
                {cases.filter(c => !resolvedIds.has(c.id)).length === 0 && (
                  <div className="p-16 text-center text-text-muted card">
                    <div className="text-5xl mb-4">✓</div>
                    <p>Queue is optimized. No active clinical escalations.</p>
                  </div>
                )}
              </div>
            </motion.div>
          )}

          {currentView === 'past' && (
            <motion.div key="past" initial={{opacity:0, y:10}} animate={{opacity:1, y:0}} exit={{opacity:0, y:-10}}>
              <PastCasesTable pastCases={pastCases} />
            </motion.div>
          )}

          {currentView === 'standing' && (
            <motion.div key="standing" initial={{opacity:0, y:10}} animate={{opacity:1, y:0}} exit={{opacity:0, y:-10}}>
              <StandingOrdersSection orders={standingOrders} onSave={refreshData} showToast={showToast} />
            </motion.div>
          )}

          {currentView === 'analytics' && (
            <motion.div key="analytics" initial={{opacity:0, y:10}} animate={{opacity:1, y:0}} exit={{opacity:0, y:-10}}>
              <AnalyticsView analytics={analytics} />
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

function NavButton({ active, icon, label, onClick }) {
  return (
    <div 
      onClick={onClick}
      className={`flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium cursor-pointer transition-all duration-200 ${
        active ? 'bg-primary text-white shadow-lg shadow-primary/30' : 'text-text-muted hover:bg-primary-soft hover:text-primary'
      }`}
    >
      {icon}
      {label}
    </div>
  );
}

function StatsSummary({ cases, resolvedCount }) {
  const activeCount = cases.length;
  const handoffCount = cases.filter(c => c.tier === 'hand_off').length;

  return (
    <div className="grid grid-cols-4 gap-6">
      <StatCard label="Active Escalations" value={activeCount} trend="↑ 12% vs yesterday" trendUp />
      <StatCard label="Urgent (Hand-off)" value={handoffCount} color="text-danger" trend="↓ 4% vs yesterday" />
      <StatCard label="Response Time (Avg)" value="11m" trend="Optimized" />
      <StatCard label="Resolved (Today)" value={resolvedCount} trend={`↑ 8 new`} trendUp />
    </div>
  );
}

function StatCard({ label, value, trend, trendUp, color }) {
  return (
    <div className="bg-white p-6 rounded-2xl border border-border flex flex-col gap-2 hover:translate-y-[-2px] transition-transform hover:shadow-md">
      <p className="text-[13px] text-text-muted font-medium">{label}</p>
      <p className={`text-3xl font-bold ${color}`}>{value}</p>
      <p className={`text-xs font-medium ${trendUp ? 'text-success' : 'text-text-muted'}`}>{trend}</p>
    </div>
  );
}

function CaseCard({ c, timer, onAction, formatTime }) {
  const [showNote, setShowNote] = useState(false);
  const [noteText, setNoteText] = useState('');
  const urgent = timer !== null && timer < 300;

  const tierMeta = {
    hand_off: { label: '🔴 Emergency Hand-off', style: 'bg-danger-soft text-danger' },
    hand_up: { label: '🟡 Physician Review', style: 'bg-warning-soft text-warning' },
    handle: { label: '🟢 AI Managed', style: 'bg-success-soft text-success' }
  }[c.tier] || { label: '🟡 Review', style: 'bg-slate-100 text-slate-600' };

  return (
    <div className="bg-white rounded-[20px] border border-border p-8 grid grid-cols-[1fr,240px] gap-8 shadow-sm hover:shadow-md transition-shadow">
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
          <VitalItem label="Heart Rate" value={`${c.hr} BPM`} />
          <VitalItem label="Oxygen (SpO₂)" value={c.spo2} />
        </div>

        <div className="flex flex-wrap gap-2 mb-6">
          {c.symptoms.map(s => <span key={s} className="bg-white border border-border px-3 py-1 rounded-lg text-xs text-text-muted">{s}</span>)}
        </div>

        <div className="bg-slate-50 border-l-4 border-primary p-4 rounded-r-xl text-sm leading-relaxed text-slate-600 mb-6 italic">
          "{c.sbar}"
        </div>

        <div className="flex gap-3">
          <button className="btn btn-primary" onClick={() => onAction(c.id, 'approve')}>Authorize Care Plan</button>
          <button className="btn btn-danger" onClick={() => onAction(c.id, 'escalate')}>Immediate Escalation</button>
          <button className="btn btn-outline" onClick={() => setShowNote(!showNote)}>Add Clinical Note</button>
        </div>

        {showNote && (
          <motion.div initial={{opacity:0, height:0}} animate={{opacity:1, height:'auto'}} className="mt-4">
            <textarea 
              value={noteText}
              onChange={(e) => setNoteText(e.target.value)}
              className="w-full p-4 border border-border rounded-xl text-sm focus:ring-2 focus:ring-primary/20 outline-none min-height-[100px]"
              placeholder={`Enter note for ${c.patient_name}'s record...`}
            />
            <button className="btn btn-primary mt-2" onClick={() => { onAction(c.id, 'note', noteText); setShowNote(false); setNoteText(''); }}>Save Clinical Note</button>
          </motion.div>
        )}
      </div>

      <div className="border-l border-border pl-8 flex flex-col justify-center items-center text-center">
        {timer !== null ? (
          <>
            <div className={`text-[42px] font-mono font-medium tracking-tighter mb-2 ${urgent ? 'timer-urgent' : ''}`}>
              {formatTime(timer)}
            </div>
            <p className="text-[12px] text-text-muted font-bold tracking-widest">SLA TARGET</p>
            {urgent && <p className="text-[11px] text-danger font-bold mt-2">⚠️ CRITICAL THRESHOLD</p>}
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
    </div>
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

function PastCasesTable({ pastCases }) {
  return (
    <div className="card p-0 overflow-hidden shadow-sm">
      <table className="w-full text-left border-collapse">
        <thead className="bg-slate-50 border-bottom border-border">
          <tr>
            <th className="p-5 pl-8 text-xs font-bold text-text-muted tracking-widest">PATIENT</th>
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
              <td className="p-5">
                <span className="bg-slate-100 text-slate-600 px-3 py-1 rounded-lg text-[10px] font-bold uppercase tracking-wider">{c.status.replace(/_/g, ' ')}</span>
              </td>
              <td className="p-5 text-sm text-slate-500">{new Date(c.resolved_at).toLocaleDateString()}</td>
              <td className="p-5 text-sm text-text-muted">{c.symptoms.join(', ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StandingOrdersSection({ orders, onSave, showToast }) {
  const [patient, setPatient] = useState('Maria G. · 32 weeks');
  const [condition, setCondition] = useState('');
  const [intervention, setIntervention] = useState('');

  const handleSubmit = async () => {
    if (!condition || !intervention) return;
    try {
      await axios.post(`${BASE_URL}/standing-orders`, { patient_name: patient, condition, intervention });
      showToast('Order authorized successfully');
      setCondition('');
      setIntervention('');
      onSave();
    } catch (err) {
      showToast('Failed to save order');
    }
  };

  return (
    <div className="flex flex-col gap-8">
      <div className="card">
        <h2 className="text-xl font-semibold mb-6 flex items-center gap-2"><Activity className="text-primary"/> New Clinical Standing Order</h2>
        <div className="grid grid-cols-[1fr,1fr,1fr,auto] gap-6 items-end">
          <div className="flex flex-col gap-2">
            <label className="text-[11px] font-bold text-text-muted uppercase">Patient</label>
            <select value={patient} onChange={e => setPatient(e.target.value)} className="p-3 border border-border rounded-xl text-sm outline-none focus:ring-2 focus:ring-primary/20">
              <option>Maria G. · 32 weeks</option>
              <option>Sarah L. · 24 weeks</option>
              <option>Denise H. · 28 weeks</option>
            </select>
          </div>
          <div className="flex flex-col gap-2">
            <label className="text-[11px] font-bold text-text-muted uppercase">Clinical Trigger</label>
            <input type="text" value={condition} onChange={e => setCondition(e.target.value)} placeholder="e.g. BP > 140/90" className="p-3 border border-border rounded-xl text-sm outline-none focus:ring-2 focus:ring-primary/20" />
          </div>
          <div className="flex flex-col gap-2">
            <label className="text-[11px] font-bold text-text-muted uppercase">Automated Intervention</label>
            <input type="text" value={intervention} onChange={e => setIntervention(e.target.value)} placeholder="e.g. Immediate Call" className="p-3 border border-border rounded-xl text-sm outline-none focus:ring-2 focus:ring-primary/20" />
          </div>
          <button className="btn btn-primary h-[46px]" onClick={handleSubmit}>Authorize Order</button>
        </div>
      </div>

      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-bold text-text-muted uppercase tracking-widest px-2">Active Authorized Orders</h3>
        {orders.map(o => (
          <div key={o.id} className="bg-white border border-border p-5 rounded-2xl flex justify-between items-center hover:shadow-sm transition-shadow">
            <div>
              <p className="font-semibold text-[15px]">{o.patient_name} <span className="mx-2 text-slate-300">→</span> {o.condition}</p>
              <p className="text-sm text-primary font-medium mt-1">Intervention: {o.intervention}</p>
            </div>
            <div className="text-right">
              <p className="text-[10px] text-text-muted uppercase font-bold tracking-tighter">Authorized by</p>
              <p className="text-sm font-semibold">{o.doctor_name}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AnalyticsView({ analytics }) {
  const g = analytics.global_crisis || {};
  const l = analytics.lilly_stats || {};

  return (
    <div className="grid grid-cols-[1fr,1.2fr] gap-8">
      <div className="flex flex-col gap-8">
        <div className="card border-l-[6px] border-primary">
          <h3 className="text-lg font-semibold mb-6 flex items-center gap-2">🌸 Lilly Operational Impact</h3>
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-bg p-4 rounded-xl">
              <p className="text-[11px] font-bold text-text-muted uppercase">Lives Saved (est)</p>
              <p className="text-2xl font-bold text-primary mt-1">{l.lives_saved_estimate || 0}</p>
            </div>
            <div className="bg-bg p-4 rounded-xl">
              <p className="text-[11px] font-bold text-text-muted uppercase">Care Centers</p>
              <p className="text-2xl font-bold mt-1">{l.care_hubs || 0}</p>
            </div>
          </div>
        </div>

        <div className="card border-l-[6px] border-danger">
          <h3 className="text-lg font-semibold mb-6 flex items-center gap-2 text-danger">🚨 Global Maternal Crisis</h3>
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-danger-soft p-4 rounded-xl">
              <p className="text-[11px] font-bold text-danger uppercase opacity-70">Daily Deaths</p>
              <p className="text-2xl font-bold text-danger mt-1">{g.daily_preventable_deaths || 0}</p>
            </div>
            <div className="bg-bg p-4 rounded-xl">
              <p className="text-[11px] font-bold text-text-muted uppercase">Preventable Rate</p>
              <p className="text-2xl font-bold mt-1">{g.preventable_percentage || '80%'}</p>
            </div>
          </div>
        </div>
      </div>

      <div className="card relative h-full">
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
      </div>
    </div>
  );
}
