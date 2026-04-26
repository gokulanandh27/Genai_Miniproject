import React, { useState, useRef, useEffect } from 'react';

const API_BASE = 'http://127.0.0.1:8000';

const QUICK_SITES = [
  { label: 'Amazon IN', url: 'https://www.amazon.in/' },
  { label: 'eBay', url: 'https://www.ebay.com/' },
  { label: 'Flipkart', url: 'https://www.flipkart.com/' },
  { label: 'Books to Scrape', url: 'https://books.toscrape.com/' },
  { label: 'JMAN Group', url: 'https://jmangroup.com/' },
];

export default function App() {
  const [url, setUrl] = useState('');
  const [prompt, setPrompt] = useState('');
  const [limit, setLimit] = useState(10);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);
  const [logs, setLogs] = useState([]);
  const [error, setError] = useState(null);
  const logRef = useRef(null);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs]);

  const log = (msg, type = 'info') =>
    setLogs(p => [...p, { msg, type, t: new Date().toLocaleTimeString('en-IN', { hour12: false }) }]);

  const handleRun = async (e) => {
    e.preventDefault();
    if (!url || !prompt) return;
    setLoading(true);
    setData(null);
    setError(null);
    setLogs([]);
    log(`Target: ${url}`);
    log(`Prompt: ${prompt}`);
    log(`Limit: ${limit} items`);
    log('Connecting to scraper engine...');

    try {
      const res = await fetch(`${API_BASE}/scrape`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, prompt, limit: Number(limit), export: 'json' }),
        signal: AbortSignal.timeout(125000), // slightly above server timeout
      });

      const json = await res.json();

      if (!res.ok) {
        throw new Error(json.detail || json.error || `HTTP ${res.status}`);
      }

      if (json.not_applicable) {
        log(`Not applicable: ${json.message}`, 'warn');
        setError(json.message);
      } else if (json.success) {
        log(`Scraped ${json.pages_scraped || 1} page(s)`, 'success');
        log(`Extracted ${json.count} item(s)`, 'success');
        setData(json);
      } else {
        throw new Error(json.error || 'Unknown error');
      }
    } catch (err) {
      const msg = err.name === 'TimeoutError' ? 'Request timed out. Try a simpler query or different site.' : err.message;
      log(`Error: ${msg}`, 'error');
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const downloadCSV = async () => {
    const res = await fetch(`${API_BASE}/scrape`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, prompt, limit: Number(limit), export: 'csv' }),
    });
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'results.csv';
    a.click();
  };

  const copyJSON = () => {
    if (data) navigator.clipboard.writeText(JSON.stringify(data.data, null, 2));
  };

  const logStyle = { info: '#60a5fa', success: '#4ade80', error: '#f87171', warn: '#facc15', system: '#a78bfa' };

  return (
    <div style={styles.page}>
      <div style={styles.container}>

        {/* ── HEADER ── */}
        <header style={styles.header}>
          <div>
            <div style={styles.logoRow}>
              <div style={styles.logoDot} />
              <span style={styles.logoText}>Universal Web Scraper</span>
            </div>
            <p style={styles.subtitle}>AI-powered data extraction from any website</p>
          </div>
          <div style={styles.statusBadge}>
            <div style={styles.statusDot} />
            <span style={styles.statusText}>System Active</span>
          </div>
        </header>

        {/* ── MAIN GRID ── */}
        <div style={styles.grid}>

          {/* LEFT — Controls */}
          <div style={styles.panel}>
            <form onSubmit={handleRun}>

              {/* Quick select */}
              <div style={styles.field}>
                <label style={styles.label}>Quick Select</label>
                <div style={styles.chipRow}>
                  {QUICK_SITES.map(s => (
                    <button key={s.url} type="button"
                      onClick={() => setUrl(s.url)}
                      style={{ ...styles.chip, ...(url === s.url ? styles.chipActive : {}) }}>
                      {s.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* URL */}
              <div style={styles.field}>
                <label style={styles.label}>Website URL</label>
                <input type="url" value={url} onChange={e => setUrl(e.target.value)}
                  placeholder="https://example.com" required
                  style={styles.input} />
              </div>

              {/* Prompt */}
              <div style={styles.field}>
                <label style={styles.label}>What to extract</label>
                <textarea value={prompt} onChange={e => setPrompt(e.target.value)} rows={3}
                  placeholder="e.g. List 20 mobile phones under ₹20000 with name and price"
                  required style={{ ...styles.input, resize: 'vertical', fontFamily: 'inherit' }} />
              </div>

              {/* Limit slider */}
              <div style={styles.field}>
                <label style={styles.label}>
                  Result Limit &nbsp;<strong style={{ color: '#818cf8' }}>{limit}</strong>
                </label>
                <input type="range" min={1} max={50} value={limit}
                  onChange={e => setLimit(e.target.value)}
                  style={{ width: '100%', accentColor: '#818cf8', cursor: 'pointer' }} />
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: '#475569', marginTop: 4 }}>
                  <span>1</span><span>25</span><span>50</span>
                </div>
              </div>

              {/* Button */}
              <button type="submit" disabled={loading} style={{
                ...styles.btn,
                background: loading
                  ? 'linear-gradient(135deg, #374151, #1f2937)'
                  : 'linear-gradient(135deg, #6366f1, #8b5cf6)',
                cursor: loading ? 'not-allowed' : 'pointer',
              }}>
                {loading
                  ? <><span style={styles.spinner} /> Extracting...</>
                  : '⚡ Run Extraction'}
              </button>
            </form>

            {error && (
              <div style={styles.errorBox}>
                <span style={{ fontSize: 16 }}>⚠</span>
                <p style={{ margin: 0, fontSize: 13 }}>{error}</p>
              </div>
            )}
          </div>

          {/* RIGHT — Console */}
          <div style={styles.console}>
            <div style={styles.consoleHeader}>
              <span style={styles.consoleDot1} /><span style={styles.consoleDot2} /><span style={styles.consoleDot3} />
              <span style={{ marginLeft: 10, fontSize: 11, color: '#475569', fontFamily: 'monospace' }}>extraction-monitor</span>
            </div>
            <div ref={logRef} style={styles.consoleBody}>
              {logs.length === 0
                ? <span style={{ color: '#1e293b' }}>Awaiting command...</span>
                : logs.map((l, i) => (
                  <div key={i} style={{ marginBottom: 3 }}>
                    <span style={{ color: '#334155', fontFamily: 'monospace' }}>{l.t} </span>
                    <span style={{ color: logStyle[l.type] || '#e2e8f0' }}>{l.msg}</span>
                  </div>
                ))
              }
              {loading && <div style={{ color: '#6366f1', marginTop: 4 }}>▌</div>}
            </div>
          </div>
        </div>

        {/* ── RESULTS ── */}
        {data && data.count > 0 && (
          <div style={{ marginTop: 32 }}>
            <div style={styles.resultHeader}>
              <div>
                <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>
                  Results
                  <span style={styles.countBadge}>{data.count} items</span>
                </h2>
                <p style={{ margin: '4px 0 0', fontSize: 12, color: '#475569' }}>
                  Source: {data.page_url}
                </p>
              </div>
              <div style={{ display: 'flex', gap: 10 }}>
                <button onClick={copyJSON} style={styles.actionBtn}>Copy JSON</button>
                <button onClick={downloadCSV} style={{ ...styles.actionBtn, ...styles.actionBtnPrimary }}>
                  ↓ Download CSV
                </button>
              </div>
            </div>

            <div style={styles.cardGrid}>
              {data.data.map((item, i) => (
                <div key={i} style={styles.card}
                  onMouseEnter={e => { e.currentTarget.style.borderColor = '#6366f1'; e.currentTarget.style.transform = 'translateY(-2px)'; }}
                  onMouseLeave={e => { e.currentTarget.style.borderColor = 'rgba(255,255,255,0.06)'; e.currentTarget.style.transform = 'none'; }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10, alignItems: 'center' }}>
                    <span style={{ fontSize: 10, color: '#334155', fontWeight: 700 }}>#{i + 1}</span>
                    {(item.price || item.Price) &&
                      <span style={{ fontSize: 14, fontWeight: 700, color: '#4ade80' }}>
                        {item.price || item.Price}
                      </span>
                    }
                  </div>
                  {Object.entries(item).map(([k, v]) => (
                    <div key={k} style={{ marginBottom: 8 }}>
                      <div style={{ fontSize: 9, textTransform: 'uppercase', color: '#475569', letterSpacing: 1, fontWeight: 700 }}>{k}</div>
                      <div style={{ fontSize: 12.5, color: '#cbd5e1', marginTop: 2, lineHeight: 1.5, wordBreak: 'break-word' }}>{String(v)}</div>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>
        )}

        {data && data.count === 0 && (
          <div style={styles.emptyState}>
            <div style={{ fontSize: 36, marginBottom: 12 }}>🔍</div>
            <p style={{ margin: 0, color: '#475569' }}>No items found. Try a different prompt or URL.</p>
          </div>
        )}
      </div>
    </div>
  );
}

const styles = {
  page: { minHeight: '100vh', background: 'linear-gradient(160deg, #0a0a14 0%, #0f1120 60%, #0a0a14 100%)', color: '#e2e8f0', fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif", padding: '28px 20px' },
  container: { maxWidth: 1200, margin: '0 auto' },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 32, flexWrap: 'wrap', gap: 16 },
  logoRow: { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 },
  logoDot: { width: 10, height: 10, borderRadius: '50%', background: 'linear-gradient(135deg, #6366f1, #8b5cf6)', boxShadow: '0 0 12px #6366f1' },
  logoText: { fontSize: 22, fontWeight: 800, letterSpacing: -0.5, color: '#f1f5f9' },
  subtitle: { margin: 0, fontSize: 13, color: '#475569' },
  statusBadge: { display: 'flex', alignItems: 'center', gap: 8, background: 'rgba(74,222,128,0.07)', border: '1px solid rgba(74,222,128,0.2)', borderRadius: 20, padding: '6px 14px' },
  statusDot: { width: 7, height: 7, borderRadius: '50%', background: '#4ade80', boxShadow: '0 0 8px #4ade80', animation: 'pulse 2s infinite' },
  statusText: { fontSize: 12, color: '#4ade80', fontWeight: 600 },
  grid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 },
  panel: { background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 20, padding: 28 },
  field: { marginBottom: 20 },
  label: { display: 'block', fontSize: 11, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: 1.2, marginBottom: 10 },
  chipRow: { display: 'flex', flexWrap: 'wrap', gap: 7 },
  chip: { fontSize: 12, padding: '5px 12px', borderRadius: 8, border: '1px solid rgba(255,255,255,0.08)', background: 'transparent', color: '#64748b', cursor: 'pointer', transition: 'all 0.15s' },
  chipActive: { borderColor: 'rgba(99,102,241,0.5)', background: 'rgba(99,102,241,0.12)', color: '#818cf8' },
  input: { width: '100%', padding: '11px 14px', background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 12, color: '#e2e8f0', fontSize: 13.5, outline: 'none', boxSizing: 'border-box', transition: 'border-color 0.2s' },
  btn: { width: '100%', padding: '13px', border: 'none', borderRadius: 14, color: '#fff', fontSize: 14, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, letterSpacing: 0.5, transition: 'opacity 0.2s' },
  spinner: { width: 14, height: 14, border: '2px solid rgba(255,255,255,0.2)', borderTop: '2px solid #fff', borderRadius: '50%', animation: 'spin 0.8s linear infinite', display: 'inline-block' },
  errorBox: { marginTop: 16, background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 12, padding: '14px 18px', display: 'flex', gap: 12, alignItems: 'flex-start', color: '#fca5a5' },
  console: { background: '#080811', border: '1px solid rgba(255,255,255,0.05)', borderRadius: 20, overflow: 'hidden', display: 'flex', flexDirection: 'column', minHeight: 380 },
  consoleHeader: { background: '#0d0d1a', padding: '12px 16px', display: 'flex', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.05)' },
  consoleDot1: { width: 10, height: 10, borderRadius: '50%', background: '#ff5f57', marginRight: 6 },
  consoleDot2: { width: 10, height: 10, borderRadius: '50%', background: '#febc2e', marginRight: 6 },
  consoleDot3: { width: 10, height: 10, borderRadius: '50%', background: '#28c840' },
  consoleBody: { flex: 1, padding: '16px 20px', overflowY: 'auto', fontFamily: 'monospace', fontSize: 12.5, lineHeight: 1.7, color: '#e2e8f0' },
  resultHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20, flexWrap: 'wrap', gap: 12 },
  countBadge: { marginLeft: 12, fontSize: 12, background: 'rgba(99,102,241,0.15)', color: '#818cf8', border: '1px solid rgba(99,102,241,0.3)', padding: '2px 12px', borderRadius: 20, fontWeight: 600 },
  actionBtn: { padding: '8px 16px', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 10, color: '#94a3b8', cursor: 'pointer', fontSize: 13, transition: 'all 0.15s' },
  actionBtnPrimary: { background: 'rgba(99,102,241,0.1)', borderColor: 'rgba(99,102,241,0.3)', color: '#818cf8' },
  cardGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 14 },
  card: { background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 16, padding: 18, transition: 'all 0.2s' },
  emptyState: { marginTop: 32, textAlign: 'center', padding: '48px', background: 'rgba(255,255,255,0.02)', borderRadius: 20, border: '1px dashed rgba(255,255,255,0.08)' },
};
