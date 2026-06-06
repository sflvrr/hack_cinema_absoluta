// Skeleton — build the technician workspace here.
//
// Suggested flow: list tickets -> open a ticket (show the customer system) ->
// run the agent with visible progress and a human approve/reject on each action
// -> review and submit the activity. How it looks and how it talks to your
// backend is entirely up to you. The backend is at import.meta.env.VITE_API_BASE
// (default http://localhost:8000).

export default function App() {
  return (
    <main style={{ fontFamily: "system-ui, sans-serif", maxWidth: 680, margin: "12vh auto", padding: 24 }}>
      <h1>AI Service Desk Autopilot</h1>
      <p>React + Vite + TypeScript skeleton. Replace this with your technician workspace.</p>
      <p style={{ color: "#666" }}>See <code>README.md</code> and <code>docs/phoenix-openapi.yaml</code> to get started.</p>
    </main>
  );
}
