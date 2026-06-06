import { useState, useEffect } from 'react';

// URL нашего бэкенда (из Docker или локальный)
// @ts-ignore
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';
// Ключ доступа для фронтенда (как мы прописали в main.py)
const USER_KEY = 'secret-react-user-key';

export default function App() {
  const [ticketId, setTicketId] = useState<number>(7001); // ID тестового тикета
  const [n8nWebhookUrl, setN8nWebhookUrl] = useState<string>('http://localhost:5678/webhook/start-agent');

  const [isRunning, setIsRunning] = useState(false);
  const [proposal, setProposal] = useState<any>(null);
  const [editCommand, setEditCommand] = useState<string>('');
  const [logs, setLogs] = useState<string[]>([]);

  // Цикл опроса (Polling): раз в 2 секунды спрашиваем бэкенд, есть ли предложения от ИИ
  useEffect(() => {
    if (!isRunning) return;

    const interval = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/tickets/${ticketId}/proposal`, {
          headers: { 'X-API-Key': USER_KEY }
        });
        const data = await res.json();

        if (data.status === 'needs_approval' && data.proposal) {
          // Если ИИ прислал команду и мы ее еще не вывели на экран
          if (!proposal || proposal.original_command !== data.proposal.original_command) {
            setProposal(data.proposal);
            setEditCommand(data.proposal.original_command); // Записываем команду в поле для редактирования
          }
        } else {
          setProposal(null);
        }
      } catch (e) {
        console.error("Ошибка опроса бэкенда:", e);
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [isRunning, ticketId, proposal]);

  // 1. ЗАПУСК n8n
  const handleStartAgent = async () => {
    setIsRunning(true);
    setLogs(prev => [...prev, `[SYSTEM] Запуск агента n8n для тикета #${ticketId}...`]);

    try {
      // Отправляем сигнал в самую первую ноду (Webhook) твоего n8n
      await fetch(n8nWebhookUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticket_id: ticketId })
      });
      setLogs(prev => [...prev, `[SYSTEM] Агент запущен! Ожидание предложений...`]);
    } catch (e) {
      setLogs(prev => [...prev, `[ERROR] Не удалось достучаться до n8n: ${e}`]);
      setIsRunning(false);
    }
  };

  // 2. ОДОБРЕНИЕ КОМАНДЫ (Approve)
  const handleApprove = async () => {
    setLogs(prev => [...prev, `[HUMAN APPROVED] Выполняется: ${editCommand}`]);
    setProposal(null); // Прячем панель кнопок

    try {
      const res = await fetch(`${API_BASE}/api/tickets/${ticketId}/approve`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': USER_KEY
        },
        body: JSON.stringify({ command: editCommand })
      });
      const data = await res.json();
      setLogs(prev => [...prev, `[SERVER OUTPUT]\n${data.output}`]);
    } catch (e) {
      setLogs(prev => [...prev, `[ERROR] Ошибка выполнения: ${e}`]);
    }
  };

  // 3. ОТКЛОНЕНИЕ КОМАНДЫ (Reject)
  const handleReject = async () => {
    setLogs(prev => [...prev, `[HUMAN REJECTED] Команда отклонена.`]);
    setProposal(null);

    try {
      await fetch(`${API_BASE}/api/tickets/${ticketId}/reject`, {
        method: 'POST',
        headers: { 'X-API-Key': USER_KEY }
      });
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", maxWidth: 900, margin: "40px auto", padding: 24 }}>
      <h1>AI Service Desk Autopilot 🤖</h1>
      
      {/* ПАНЕЛЬ НАСТРОЕК */}
      <div style={{ background: '#f5f5f7', padding: 16, borderRadius: 8, marginBottom: 24 }}>
        <div style={{ display: 'flex', gap: 10, marginBottom: 10 }}>
          <input 
            type="text" 
            value={n8nWebhookUrl} 
            onChange={e => setN8nWebhookUrl(e.target.value)} 
            placeholder="URL Webhook'а из n8n"
            style={{ flex: 1, padding: 8 }}
          />
          <input 
            type="number" 
            value={ticketId} 
            onChange={e => setTicketId(Number(e.target.value))} 
            style={{ width: 100, padding: 8 }}
          />
          <button 
            onClick={handleStartAgent} 
            disabled={isRunning}
            style={{ padding: '8px 16px', background: '#007aff', color: 'white', border: 'none', borderRadius: 4, cursor: 'pointer' }}
          >
            {isRunning ? 'Агент работает...' : 'Начать диагностику'}
          </button>
        </div>
      </div>

      {/* ПАНЕЛЬ ОЖИДАНИЯ АПРУВА (Появляется только когда ИИ прислал команду) */}
      {proposal && (
        <div style={{ background: '#ffe58f', padding: 16, borderRadius: 8, border: '2px solid #faad14', marginBottom: 24 }}>
          <h3 style={{ marginTop: 0 }}>⚠️ Агент (Этап: {proposal.stage}) предлагает команду:</h3>
          <input 
            type="text" 
            value={editCommand} 
            onChange={e => setEditCommand(e.target.value)} 
            style={{ width: '100%', padding: 12, fontSize: '16px', fontFamily: 'monospace', marginBottom: 12 }}
          />
          <div style={{ display: 'flex', gap: 10 }}>
            <button onClick={handleApprove} style={{ background: '#52c41a', color: 'white', border: 'none', padding: '10px 20px', borderRadius: 4, cursor: 'pointer', fontWeight: 'bold' }}>✅ Разрешить (Approve)</button>
            <button onClick={handleReject} style={{ background: '#ff4d4f', color: 'white', border: 'none', padding: '10px 20px', borderRadius: 4, cursor: 'pointer', fontWeight: 'bold' }}>❌ Запретить (Reject)</button>
          </div>
        </div>
      )}

      {/* ТЕРМИНАЛ (Логи) */}
      <div style={{ background: '#1e1e1e', color: '#00ff00', padding: 16, borderRadius: 8, height: 400, overflowY: 'auto', fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>
        {logs.length === 0 ? "Ожидание действий..." : logs.map((log, idx) => (
          <div key={idx} style={{ marginBottom: 8 }}>{log}</div>
        ))}
      </div>
    </main>
  );
}