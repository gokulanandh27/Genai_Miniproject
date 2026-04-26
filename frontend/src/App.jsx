import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { 
  Search, 
  Download, 
  Terminal, 
  CheckCircle2, 
  AlertCircle, 
  Loader2, 
  ExternalLink,
  ChevronRight,
  Database,
  Layers,
  FileJson,
  FileSpreadsheet,
  Trash2
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

const API_BASE = 'http://127.0.0.1:8000';

export default function App() {
  const [url, setUrl] = useState('');
  const [prompt, setPrompt] = useState('');
  const [limit, setLimit] = useState(10);
  const [isScraping, setIsScraping] = useState(false);
  const [results, setResults] = useState(null);
  const [logs, setLogs] = useState([]);
  const [error, setError] = useState(null);
  const logEndRef = useRef(null);

  // Auto-scroll logs
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  const addLog = (msg, type = 'info') => {
    setLogs(prev => [...prev, { msg, type, time: new Date().toLocaleTimeString() }]);
  };

  const handleScrape = async (e) => {
    e.preventDefault();
    if (!url || !prompt) return;

    setIsScraping(true);
    setResults(null);
    setLogs([]);
    setError(null);
    addLog(`Initiating scrape for: ${url}`, 'info');

    try {
      const response = await axios.post(`${API_BASE}/scrape`, {
        url,
        prompt,
        export: 'json'
      });

      if (response.data.success) {
        setResults(response.data);
        addLog(`Successfully extracted ${response.data.count} items.`, 'success');
      } else if (response.data.not_applicable) {
        setError(response.data.message);
        addLog(response.data.message, 'warning');
      } else {
        throw new Error(response.data.error || 'Scrape failed');
      }
    } catch (err) {
      const msg = err.response?.data?.detail || err.message;
      setError(msg);
      addLog(`Error: ${msg}`, 'error');
    } finally {
      setIsScraping(false);
    }
  };

  const downloadFile = async (type) => {
    try {
      const response = await axios.post(`${API_BASE}/scrape`, {
        url,
        prompt,
        export: type
      }, { responseType: 'blob' });
      
      const fileURL = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = fileURL;
      link.setAttribute('download', `results.${type}`);
      document.body.appendChild(link);
      link.click();
    } catch (err) {
      console.error('Download failed', err);
    }
  };

  return (
    <div className="min-h-screen p-4 md:p-8 max-w-6xl mx-auto space-y-8">
      {/* Header */}
      <header className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-accent to-purple-400">
            Universal AI Scraper
          </h1>
          <p className="text-gray-500 text-sm">Professional AI-Guided Universal Web Extraction</p>
        </div>
        <div className="flex items-center gap-4 bg-card px-4 py-2 rounded-xl border border-white/5">
          <div className="flex flex-col items-end">
            <span className="text-[10px] text-gray-500 uppercase tracking-widest font-bold">Status</span>
            <span className="flex items-center gap-2 text-xs text-green-500 font-medium">
              <div className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
              SYSTEM ACTIVE
            </span>
          </div>
        </div>
      </header>

      <main className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Left Column: Input */}
        <div className="lg:col-span-7 space-y-6">
          <section className="glass rounded-3xl p-6 md:p-8 space-y-6">
            <form onSubmit={handleScrape} className="space-y-6">
              <div className="space-y-4">
                <label className="text-sm font-medium text-gray-400">Target Environment</label>
                <div className="relative group">
                  <div className="absolute inset-y-0 left-4 flex items-center pointer-events-none text-gray-500 group-focus-within:text-accent transition-colors">
                    <Layers size={18} />
                  </div>
                  <input
                    type="url"
                    placeholder="https://example.com"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    className="w-full bg-black/40 border border-white/10 rounded-2xl py-4 pl-12 pr-4 focus:outline-none focus:border-accent/50 focus:ring-4 focus:ring-accent/10 transition-all text-sm"
                    required
                  />
                </div>
              </div>

              <div className="space-y-4">
                <label className="text-sm font-medium text-gray-400">Extraction Intent</label>
                <div className="relative group">
                  <div className="absolute top-4 left-4 text-gray-500 group-focus-within:text-accent transition-colors">
                    <Search size={18} />
                  </div>
                  <textarea
                    placeholder="Describe what you want to find (e.g., 'Latest tech news headlines')"
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    className="w-full bg-black/40 border border-white/10 rounded-2xl py-4 pl-12 pr-4 min-h-[120px] focus:outline-none focus:border-accent/50 focus:ring-4 focus:ring-accent/10 transition-all text-sm"
                    required
                  />
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-6">
                <div className="flex-1 min-w-[150px] space-y-3">
                  <label className="text-[10px] uppercase tracking-wider text-gray-500 font-bold">Max Density</label>
                  <input
                    type="number"
                    value={limit}
                    onChange={(e) => setLimit(e.target.value)}
                    className="w-full bg-black/40 border border-white/10 rounded-xl py-2 px-4 focus:outline-none focus:border-accent/50 text-sm"
                  />
                </div>
                <button
                  type="submit"
                  disabled={isScraping}
                  className="flex-[2] min-w-[200px] h-[52px] bg-accent hover:bg-accent/90 disabled:opacity-50 text-white rounded-2xl font-bold flex items-center justify-center gap-3 transition-all active:scale-95 glow-accent mt-6"
                >
                  {isScraping ? (
                    <>
                      <Loader2 size={20} className="animate-spin" />
                      EXTRACTING...
                    </>
                  ) : (
                    <>
                      <Database size={20} />
                      RUN EXTRACTION
                    </>
                  )}
                </button>
              </div>
            </form>
          </section>

          {/* Results Area */}
          <AnimatePresence>
            {results && (
              <motion.section
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className="space-y-4"
              >
                <div className="flex items-center justify-between">
                  <h3 className="text-lg font-bold flex items-center gap-2">
                    <Database size={18} className="text-accent" />
                    Extraction Output
                    <span className="text-xs bg-accent/20 text-accent px-2 py-1 rounded-full font-bold ml-2">
                      {results.count} ITEMS
                    </span>
                  </h3>
                  <div className="flex gap-2">
                    <button 
                      onClick={() => downloadFile('csv')}
                      className="p-2 hover:bg-white/5 rounded-lg text-gray-400 hover:text-white transition-colors"
                      title="Download CSV"
                    >
                      <FileSpreadsheet size={20} />
                    </button>
                    <button 
                      onClick={() => downloadFile('json')}
                      className="p-2 hover:bg-white/5 rounded-lg text-gray-400 hover:text-white transition-colors"
                      title="Download JSON"
                    >
                      <FileJson size={20} />
                    </button>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {results.data.map((item, i) => (
                    <motion.div
                      key={i}
                      initial={{ opacity: 0, scale: 0.95 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{ delay: i * 0.05 }}
                      className="glass rounded-2xl p-5 space-y-3 hover:border-white/20 transition-all cursor-default"
                    >
                      <div className="flex justify-between items-start gap-2">
                        <h4 className="font-bold text-sm line-clamp-2">{item.title || item.name || 'Untitled'}</h4>
                        {item.price && <span className="text-xs font-bold text-green-400 shrink-0">{item.price}</span>}
                      </div>
                      <p className="text-xs text-gray-500 line-clamp-3 leading-relaxed">
                        {item.description || item.summary || 'No description available'}
                      </p>
                      {item.rating && (
                        <div className="flex items-center gap-1 text-[10px] text-yellow-500/80 uppercase font-bold">
                          ★ {item.rating}
                        </div>
                      )}
                    </motion.div>
                  ))}
                </div>
              </motion.section>
            )}
          </AnimatePresence>
        </div>

        {/* Right Column: Console/Logs */}
        <div className="lg:col-span-5 space-y-6">
          <section className="bg-black/60 rounded-3xl p-6 border border-white/5 flex flex-col h-[600px]">
            <div className="flex items-center justify-between mb-4 pb-4 border-b border-white/5">
              <h3 className="text-sm font-bold flex items-center gap-2 text-gray-400">
                <Terminal size={16} />
                REAL-TIME MONITOR
              </h3>
              <button 
                onClick={() => setLogs([])}
                className="text-gray-600 hover:text-gray-400 transition-colors"
              >
                <Trash2 size={14} />
              </button>
            </div>
            
            <div className="flex-1 overflow-y-auto space-y-3 pr-2 custom-scrollbar">
              {logs.length === 0 ? (
                <div className="h-full flex flex-col items-center justify-center text-center space-y-4 opacity-30">
                  <Loader2 size={48} className="text-gray-800" />
                  <p className="text-sm">Awaiting instruction sequence...</p>
                </div>
              ) : (
                logs.map((log, i) => (
                  <div key={i} className="text-[13px] leading-relaxed group">
                    <span className="text-gray-600 font-mono mr-2">[{log.time}]</span>
                    <span className={`
                      ${log.type === 'success' ? 'text-green-500' : ''}
                      ${log.type === 'error' ? 'text-red-500 font-bold' : ''}
                      ${log.type === 'warning' ? 'text-yellow-500' : ''}
                      ${log.type === 'info' ? 'text-blue-400' : ''}
                    `}>
                      {log.msg}
                    </span>
                  </div>
                ))
              )}
              <div ref={logEndRef} />
            </div>
          </section>

          {error && (
            <div className="p-5 rounded-2xl bg-red-500/10 border border-red-500/20 flex gap-4 items-start">
              <AlertCircle className="text-red-500 shrink-0" size={20} />
              <div className="space-y-1">
                <p className="text-xs font-bold text-red-500 uppercase tracking-widest">System Warning</p>
                <p className="text-sm text-gray-400">{error}</p>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
