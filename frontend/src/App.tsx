import {useState, useEffect, useMemo, useCallback} from 'react';
import './index.css';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';
const USER_KEY = import.meta.env.VITE_BACKEND_USER_KEY || 'dev-user-key';

// 0 — самый критичный. Неизвестный приоритет уезжает в конец.
const PRIORITY_ORDER: Record<string, number> = {CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3};
const prio = (p?: string) => PRIORITY_ORDER[(p || '').toUpperCase()] ?? 99;

// --- Типы ---
interface Ticket {
    id: number;
    title: string;
    description?: string;
    priority: string;
    status: string;
    customer_id?: number;
    customer_name?: string;
}

interface SystemInfo {
    ip: string;
    port?: number;
    username?: string;
    os?: string;
    notes?: string;
}

interface CustomerSystem {
    ticket_id: number;
    customer_id: number;
    system: SystemInfo;
}

interface Proposal {
    stage: string;
    original_command: string;
    target_ip: string;
    safety_ok?: boolean;
    safety_reason?: string;
}

type SortKey = 'priority' | 'date' | 'status';

const authHeaders = {'X-API-Key': USER_KEY};
const jsonAuthHeaders = {'Content-Type': 'application/json', 'X-API-Key': USER_KEY};

export default function App() {
    const [n8nWebhookUrl, setN8nWebhookUrl] = useState<string>(
        'https://sflvr.app.n8n.cloud/webhook/troubleshoot-ticket'
    );
    const [tickets, setTickets] = useState<Ticket[]>([]);
    const [activeTicketId, setActiveTicketId] = useState<number | null>(null);
    const [system, setSystem] = useState<CustomerSystem | null>(null);
    const [isRunning, setIsRunning] = useState(false);
    const [proposal, setProposal] = useState<Proposal | null>(null);
    const [editCommand, setEditCommand] = useState<string>('');
    const [logs, setLogs] = useState<string[]>([]);
    const [sortKey, setSortKey] = useState<SortKey>('priority');
    const [showActivity, setShowActivity] = useState(false);

    const log = useCallback((line: string) => setLogs(p => [...p, line]), []);

    // Загрузка тикетов
    useEffect(() => {
        (async () => {
            try {
                const res = await fetch(`${API_BASE}/api/tickets`, {headers: authHeaders});
                const data = await res.json();
                if (Array.isArray(data.tickets) && data.tickets.length > 0) {
                    setTickets(data.tickets);
                } else {
                    console.error('Тикеты не найдены или ошибка:', data);
                }
            } catch (e) {
                console.error('Ошибка запроса тикетов:', e);
            }
        })();
    }, []);

    // Сортировка
    const sortedTickets = useMemo(() => {
        const arr = [...tickets];
        if (sortKey === 'priority') arr.sort((a, b) => prio(a.priority) - prio(b.priority));
        else if (sortKey === 'status') arr.sort((a, b) => (a.status || '').localeCompare(b.status || ''));
        else arr.sort((a, b) => b.id - a.id); // date ~ по id (новые сверху)
        return arr;
    }, [tickets, sortKey]);

    // Авто-выбор первого тикета
    useEffect(() => {
        if (sortedTickets.length > 0 && activeTicketId === null) {
            setActiveTicketId(sortedTickets[0].id);
        }
    }, [sortedTickets, activeTicketId]);

    // Подгрузка customer-system при выборе тикета
    useEffect(() => {
        if (activeTicketId === null) return;
        setSystem(null);
        (async () => {
            try {
                const res = await fetch(`${API_BASE}/api/tickets/${activeTicketId}/customer-system`, {
                    headers: authHeaders,
                });
                if (res.ok) setSystem(await res.json());
            } catch (e) {
                console.error('Ошибка загрузки customer-system:', e);
            }
        })();
    }, [activeTicketId]);

    // Поллинг предложений от n8n
    useEffect(() => {
        if (!isRunning || activeTicketId === null) return;
        const interval = setInterval(async () => {
            try {
                const res = await fetch(`${API_BASE}/api/tickets/${activeTicketId}/proposal`, {
                    headers: authHeaders,
                });
                const data = await res.json();
                if (data.status === 'needs_approval' && data.proposal) {
                    const p: Proposal = data.proposal;
                    if (!proposal || proposal.original_command !== p.original_command) {
                        setProposal(p);
                        setEditCommand(p.original_command);
                    }
                } else {
                    setProposal(null);
                }
            } catch (e) {
                console.error('Ошибка поллинга:', e);
            }
        }, 2000);
        return () => clearInterval(interval);
    }, [isRunning, activeTicketId, proposal]);

    const resetForTicket = (id: number) => {
        setActiveTicketId(id);
        setLogs([]);
        setIsRunning(false);
        setProposal(null);
        setShowActivity(false);
    };
    const handleStartAgent = async () => {
        if (activeTicketId === null) {
            alert('Сначала выберите тикет из списка!');
            return;
        }
        setIsRunning(true);
        setLogs([`[SYSTEM] Запуск ИИ-агента для тикета #${activeTicketId}...`]);
        try {
            const res = await fetch(`${API_BASE}/api/runs/start`, {
                method: 'POST',
                headers: jsonAuthHeaders,
                body: JSON.stringify({ticket_id: activeTicketId, webhook_url: n8nWebhookUrl}),
            });
            if (!res.ok) {
                const txt = await res.text();
                throw new Error(`backend ${res.status}: ${txt}`);
            }
            log('[SYSTEM] Агент работает. Ожидание диагностики...');
        } catch (e) {
            log(`[ERROR] Ошибка запуска агента: ${e}`);
            setIsRunning(false);
        }
    };
    const handleAbort = () => {
        setIsRunning(false);
        setProposal(null);
        log('[SYSTEM] ⛔ Работа агента остановлена техником (abort).');
    };

    const handleApprove = async () => {
        log(`[HUMAN APPROVED] Выполняем: ${editCommand}`);
        setProposal(null);
        try {
            const res = await fetch(`${API_BASE}/api/tickets/${activeTicketId}/approve`, {
                method: 'POST',
                headers: jsonAuthHeaders,
                body: JSON.stringify({command: editCommand}),
            });
            const data = await res.json();
            log(`[SERVER OUTPUT]\n${data.output}`);
        } catch (e) {
            log(`[ERROR] ${e}`);
        }
    };

    const handleReject = async () => {
        log('[HUMAN REJECTED] Команда отклонена. ИИ ищет другой путь...');
        setProposal(null);
        try {
            await fetch(`${API_BASE}/api/tickets/${activeTicketId}/reject`, {
                method: 'POST',
                headers: authHeaders,
            });
        } catch (e) {
            log(`[ERROR] ${e}`);
        }
    };

    const handleMarkDone = async () => {
        if (activeTicketId === null) return;
        try {
            await fetch(`${API_BASE}/api/tickets/${activeTicketId}/status`, {
                method: 'PATCH',
                headers: jsonAuthHeaders,
                body: JSON.stringify({status: 'DONE'}),
            });
            log('[SYSTEM] ✅ Тикет помечен как DONE в ERP.');
            setTickets(ts => ts.map(t => (t.id === activeTicketId ? {...t, status: 'DONE'} : t)));
        } catch (e) {
            log(`[ERROR] ${e}`);
        }
    };

    const activeTicket = tickets.find(t => t.id === activeTicketId);

    return (
        <div className="app">
            <div className="topbar">
                <span className="topbar-logo">techbold <span>· autopilot</span></span>
                <span className="topbar-pill">AI AGENT</span>
                <input
                    style={{
                        marginLeft: 20,
                        width: 350,
                        padding: '4px 8px',
                        borderRadius: 4,
                        border: '1px solid #333',
                        background: '#1a1f2e',
                        color: 'white'
                    }}
                    value={n8nWebhookUrl}
                    onChange={e => setN8nWebhookUrl(e.target.value)}
                    placeholder="n8n Webhook URL"
                />
            </div>

            <div className="main">
                {/* Список тикетов */}
                <div className="sidebar">
                    <div className="sidebar-header">
                        <div className="sidebar-title">Ticket Queue</div>
                        <select
                            value={sortKey}
                            onChange={e => setSortKey(e.target.value as SortKey)}
                            style={{
                                background: '#1a1f2e',
                                color: 'white',
                                border: '1px solid #333',
                                borderRadius: 4,
                                fontSize: 11,
                                padding: '2px 4px'
                            }}
                        >
                            <option value="priority">Sort: Priority</option>
                            <option value="date">Sort: Date</option>
                            <option value="status">Sort: Status</option>
                        </select>
                    </div>
                    <div className="ticket-list">
                        {sortedTickets.map(t => (
                            <div
                                key={t.id}
                                className={`ticket-item ${t.id === activeTicketId ? 'active' : ''}`}
                                onClick={() => resetForTicket(t.id)}
                            >
                                <div className="ticket-row1">
                                    <span className="ticket-id">#{t.id}</span>
                                    <span className={`priority-dot ${t.priority}`}></span>
                                    <span className="ticket-title">{t.title}</span>
                                </div>
                                <div className="ticket-row2">
                                    <span className={`status-badge ${t.status}`}>{t.status}</span>
                                    <span style={{fontSize: 10, color: '#8892a4'}}>
                    {t.customer_name || t.priority}
                  </span>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Рабочая область */}
                <div className="workspace">
                    <div className="ticket-detail">
                        <div className="detail-section">
                            <div className="detail-label">Ticket Details</div>
                            <div style={{fontSize: 14, fontWeight: 'bold', marginBottom: 6}}>{activeTicket?.title}</div>
                            {activeTicket?.description && (
                                <div style={{
                                    fontSize: 12,
                                    color: '#aeb6c2',
                                    marginBottom: 10
                                }}>{activeTicket.description}</div>
                            )}

                            {/* Customer system info */}
                            <div className="detail-label" style={{marginTop: 8}}>Customer System</div>
                            {system ? (
                                <div style={{fontSize: 12, color: '#aeb6c2', marginBottom: 10, lineHeight: 1.6}}>
                                    <div>IP: <b>{system.system.ip}</b>:{system.system.port ?? 22}</div>
                                    <div>User: {system.system.username} · OS: {system.system.os}</div>
                                    {system.system.notes && <div>Notes: {system.system.notes}</div>}
                                </div>
                            ) : (
                                <div style={{fontSize: 12, color: '#67707f', marginBottom: 10}}>Загрузка системной
                                    информации…</div>
                            )}

                            <div style={{display: 'flex', gap: 8}}>
                                <button
                                    onClick={handleStartAgent}
                                    disabled={isRunning}
                                    style={{
                                        flex: 1,
                                        padding: '8px',
                                        background: '#3b82f6',
                                        color: 'white',
                                        border: 'none',
                                        borderRadius: 6,
                                        cursor: 'pointer',
                                        fontWeight: 'bold'
                                    }}
                                >
                                    {isRunning ? '🤖 Агент работает...' : '▶ Запустить ИИ'}
                                </button>
                                {isRunning && (
                                    <button
                                        onClick={handleAbort}
                                        style={{
                                            padding: '8px 12px',
                                            background: '#374151',
                                            color: 'white',
                                            border: 'none',
                                            borderRadius: 6,
                                            cursor: 'pointer'
                                        }}
                                    >
                                        ⛔ Abort
                                    </button>
                                )}
                            </div>
                        </div>
                    </div>

                    {/* Терминал */}
                    <div className="terminal-pane">
                        <div className="terminal-header">
                            <div style={{flex: 1, fontSize: 12, color: '#8892a4', fontWeight: 'bold'}}>Agent Console
                            </div>
                            <button
                                onClick={() => setShowActivity(s => !s)}
                                style={{
                                    fontSize: 11,
                                    background: 'transparent',
                                    color: '#8892a4',
                                    border: '1px solid #333',
                                    borderRadius: 4,
                                    cursor: 'pointer',
                                    padding: '2px 8px'
                                }}
                            >
                                {showActivity ? 'Hide activity' : 'Finish & submit'}
                            </button>
                        </div>

                        <div className="terminal-body">
                            {logs.length === 0
                                ? "Выберите тикет и нажмите 'Запустить ИИ'..."
                                : logs.map((l, i) => <div key={i} style={{marginBottom: 8}}>{l}</div>)}
                        </div>

                        {proposal && (
                            <div className="action-panel">
                                <div style={{color: '#f97316', fontSize: 12, fontWeight: 'bold', marginBottom: 8}}>
                                    ⚠️ ИИ предлагает команду (этап: {proposal.stage}):
                                </div>
                                {proposal.safety_ok === false && (
                                    <div style={{color: '#ef4444', fontSize: 11, marginBottom: 8}}>
                                        🛑 Safety: {proposal.safety_reason} — выполнение будет заблокировано.
                                    </div>
                                )}
                                <input className="action-input" value={editCommand}
                                       onChange={e => setEditCommand(e.target.value)}/>
                                <div className="action-buttons">
                                    <button className="btn-action btn-approve" onClick={handleApprove}>✅ Approve
                                    </button>
                                    <button className="btn-action btn-reject" onClick={handleReject}>❌ Reject</button>
                                </div>
                            </div>
                        )}

                        {showActivity && (
                            <div className="action-panel">
                                <div style={{fontSize: 12, color: '#8892a4', marginBottom: 8}}>
                                    Завершение тикета. Отчёт (activity) формирует n8n из audit-log; здесь техник ставит
                                    финальный статус.
                                </div>
                                <button
                                    onClick={handleMarkDone}
                                    style={{
                                        width: '100%',
                                        padding: '8px',
                                        background: '#16a34a',
                                        color: 'white',
                                        border: 'none',
                                        borderRadius: 6,
                                        cursor: 'pointer',
                                        fontWeight: 'bold'
                                    }}
                                >
                                    ✅ Mark ticket as DONE
                                </button>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}