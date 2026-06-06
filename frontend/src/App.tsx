import { useState, useEffect, useMemo } from 'react';
import './index.css';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';
const USER_KEY = 'secret-react-user-key';

// Логика сортировки (0 - самый критичный)
const PRIORITY_ORDER: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 };



export default function App() {
  const [n8nWebhookUrl, setN8nWebhookUrl] = useState<string>('https://sflvr.app.n8n.cloud/webhook-test/troubleshoot-ticket');
  const [tickets, setTickets] = useState<any[]>([]);
  // Загружаем реальные тикеты из бэкенда при открытии страницы
  useEffect(() => {
    const fetchTickets = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/tickets`, {
          headers: { 'X-API-Key': USER_KEY }
        });
        const data = await res.json();
        if (data.tickets && data.tickets.length > 0) {
          setTickets(data.tickets);
        } else {
          console.error("Тикеты не найдены или произошла ошибка:", data);
        }
      } catch (e) {
        console.error("Ошибка запроса тикетов:", e);
      }
    };
    fetchTickets();
  }, []);
  const [activeTicketId, setActiveTicketId] = useState<number | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [proposal, setProposal] = useState<any>(null);
  const [editCommand, setEditCommand] = useState<string>('');
  const [logs, setLogs] = useState<string[]>([]);

  // СОРТИРОВКА: Автоматически сортируем по критичности
  const sortedTickets = useMemo(() => {
    return [...tickets].sort((a, b) => PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority]);
  }, [tickets]);

  // Авто-выбор самого критичного тикета при загрузке
  useEffect(() => {
    if (sortedTickets.length > 0 && !activeTicketId) {
      setActiveTicketId(sortedTickets[0].id);
    }
  }, [sortedTickets, activeTicketId]);

  // Поллинг бэкенда на предмет новых команд от n8n
  useEffect(() => {
    if (!isRunning || !activeTicketId) return;
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/tickets/${activeTicketId}/proposal`, {
          headers: { 'X-API-Key': USER_KEY }
        });
        const data = await res.json();

        if (data.status === 'needs_approval' && data.proposal) {
          if (!proposal || proposal.original_command !== data.proposal.original_command) {
            setProposal(data.proposal);
            setEditCommand(data.proposal.original_command);
          }
        } else {
          setProposal(null);
        }
      } catch (e) {
        console.error("Ошибка поллинга:", e);
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [isRunning, activeTicketId, proposal]);

  const handleStartAgent = async () => {
    setIsRunning(true);
    setLogs([`[SYSTEM] Запуск ИИ-агента для тикета #${activeTicketId}...`]);
    try {
      await fetch(n8nWebhookUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticket_id: activeTicketId })
      });
      setLogs(p => [...p, `[SYSTEM] Агент работает. Ожидание диагностики...`]);
    } catch (e) {
      setLogs(p => [...p, `[ERROR] Ошибка подключения к n8n: ${e}`]);
      setIsRunning(false);
    }
  };

  const handleApprove = async () => {
    setLogs(p => [...p, `[HUMAN APPROVED] Выполняем: ${editCommand}`]);
    setProposal(null);
    try {
      const res = await fetch(`${API_BASE}/api/tickets/${activeTicketId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-API-Key': USER_KEY },
        body: JSON.stringify({ command: editCommand })
      });
      const data = await res.json();
      setLogs(p => [...p, `[SERVER OUTPUT]\n${data.output}`]);
    } catch (e) {
      setLogs(p => [...p, `[ERROR] ${e}`]);
    }
  };

  const handleReject = async () => {
    setLogs(p => [...p, `[HUMAN REJECTED] Команда отклонена. ИИ ищет другой путь...`]);
    setProposal(null);
    await fetch(`${API_BASE}/api/tickets/${activeTicketId}/reject`, {
      method: 'POST', headers: { 'X-API-Key': USER_KEY }
    });
  };

  const activeTicket = tickets.find(t => t.id === activeTicketId);

  return (
    <div className="app">
      {/* Шапка */}
      <div className="topbar">
        <span className="topbar-logo">techbold <span>· autopilot</span></span>
        <span className="topbar-pill">AI AGENT</span>
        <input
          style={{marginLeft: 20, width: 350, padding: '4px 8px', borderRadius: 4, border: '1px solid #333', background: '#1a1f2e', color: 'white'}}
          value={n8nWebhookUrl} onChange={e => setN8nWebhookUrl(e.target.value)} placeholder="n8n Webhook URL"
        />
      </div>

      <div className="main">
        {/* Левая панель: Список тикетов */}
        <div className="sidebar">
          <div className="sidebar-header">
            <div className="sidebar-title">Ticket Queue (Sorted by Priority)</div>
          </div>
          <div className="ticket-list">
            {sortedTickets.map(t => (
              <div key={t.id} className={`ticket-item ${t.id === activeTicketId ? 'active' : ''}`} onClick={() => { setActiveTicketId(t.id); setLogs([]); setIsRunning(false); setProposal(null); }}>
                <div className="ticket-row1">
                  <span className="ticket-id">#{t.id}</span>
                  <span className={`priority-dot ${t.priority}`}></span>
                  <span className="ticket-title">{t.title}</span>
                </div>
                <div className="ticket-row2">
                  <span className={`status-badge ${t.status}`}>{t.status}</span>
                  <span style={{fontSize: 10, color: '#8892a4'}}>{t.priority}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Правая панель: Рабочая область */}
        <div className="workspace">
          {/* Детали тикета */}
          <div className="ticket-detail">
            <div className="detail-section">
              <div className="detail-label">Ticket Details</div>
              <div style={{fontSize: 14, fontWeight: 'bold', marginBottom: 10}}>{activeTicket?.title}</div>
              <button onClick={handleStartAgent} disabled={isRunning} style={{width: '100%', padding: '8px', background: '#3b82f6', color: 'white', border: 'none', borderRadius: 6, cursor: 'pointer', fontWeight: 'bold'}}>
                {isRunning ? '🤖 Агент работает...' : '▶ Запустить ИИ'}
              </button>
            </div>
          </div>

          {/* Терминал */}
          <div className="terminal-pane">
            <div className="terminal-header">
              <div style={{flex: 1, fontSize: 12, color: '#8892a4', fontWeight: 'bold'}}>Agent Console</div>
            </div>

            <div className="terminal-body">
              {logs.length === 0 ? "Выберите тикет и нажмите 'Запустить ИИ'..." : logs.map((log, i) => (
                <div key={i} style={{marginBottom: 8}}>{log}</div>
              ))}
            </div>

            {/* Панель подтверждения команд (появляется только когда n8n присылает команду) */}
            {proposal && (
              <div className="action-panel">
                <div style={{color: '#f97316', fontSize: 12, fontWeight: 'bold', marginBottom: 10}}>⚠️ ИИ предлагает выполнить команду (Этап: {proposal.stage}):</div>
                <input
                  className="action-input"
                  value={editCommand}
                  onChange={e => setEditCommand(e.target.value)}
                />
                <div className="action-buttons">
                  <button className="btn-action btn-approve" onClick={handleApprove}>✅ Разрешить (Approve)</button>
                  <button className="btn-action btn-reject" onClick={handleReject}>❌ Отклонить (Reject)</button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}