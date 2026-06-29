import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  ArrowUp, Plus, Loader2, MessageSquare, Database, FileText,
  Sparkles, X, ChevronDown, ChevronRight,
} from 'lucide-react';
import { MD } from '../components/Markdown';
import { ToolResult, ToolUI } from '../components/ToolResult';

interface AppCfg {
  branding: { name: string; tagline?: string; subtitle?: string };
  home?: { title?: string; description?: string; suggestions?: string[] };
}
interface ToolStep {
  name: string;
  question?: string;
  ui?: ToolUI | null;
}
interface Msg {
  role: 'user' | 'assistant';
  content: string;
  status?: 'thinking' | 'streaming' | 'done' | 'error';
  tools?: ToolStep[];
}
interface ConvSummary {
  conversation_id: string;
  title: string;
}
interface GenieSpace {
  space_id: string;
  title: string;
  description?: string;
}

const FALLBACK_CFG: AppCfg = {
  branding: { name: 'Contract Intelligence', tagline: '', subtitle: '' },
};

// Generic starter prompts. The deployed instance overrides these via the config
// `home.suggestions` array, so they match whatever domain the app is configured for.
const FALLBACK_SUGGESTIONS = [
  'Summarize what this assistant can help me with.',
  'What questions can I ask about my data?',
  'What can you find in my documents?',
  'Give me an example of a question that uses both my data and my documents.',
];

// Generic, name-driven labels for the agent's tool calls. The two shipped tool
// backends are Genie (structured data) and Vector Search (documents); we match on
// either the template tool names (query_data / search_documents) or common
// domain names (genie_query / contract_search), and otherwise show the raw name.
function toolLabel(name: string) {
  const n = name.toLowerCase();
  if (n.includes('genie') || n.includes('data') || n.includes('query'))
    return { label: 'Genie · querying your data', icon: Database, color: 'text-sky-600' };
  if (n.includes('search') || n.includes('document') || n.includes('contract') || n.includes('doc'))
    return { label: 'Searching your documents', icon: FileText, color: 'text-amber-600' };
  return { label: name, icon: Sparkles, color: 'text-neutral-500' };
}

export function ChatPage() {
  const [cfg, setCfg] = useState<AppCfg>(FALLBACK_CFG);
  const [email, setEmail] = useState('');
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [convs, setConvs] = useState<ConvSummary[]>([]);
  const [convId, setConvId] = useState<string | null>(null);
  const [loadingConv, setLoadingConv] = useState<string | null>(null);
  const [spaces, setSpaces] = useState<GenieSpace[]>([]);
  const [defaultSpaceId, setDefaultSpaceId] = useState<string | null>(null);
  const [spacesOpen, setSpacesOpen] = useState(true);
  const [genieSpace, setGenieSpace] = useState<GenieSpace | null>(null); // direct-query panel

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const atBottomRef = useRef(true);
  const taRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    fetch('/api/config/app').then((r) => r.json()).then((c: AppCfg) => setCfg(c)).catch(() => {});
    fetch('/api/me').then((r) => r.json()).then((m) => setEmail(m.email || '')).catch(() => {});
    fetch('/api/genie/spaces')
      .then((r) => r.json())
      .then((d) => { setSpaces(d.spaces || []); setDefaultSpaceId(d.default_space_id || null); })
      .catch(() => {});
    refreshConversations();
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && atBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  function onScroll() {
    const el = scrollRef.current;
    if (!el) return;
    atBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }

  function autoGrow() {
    const el = taRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  }

  function refreshConversations() {
    fetch('/api/conversations').then((r) => r.json()).then((d) => setConvs(d.conversations || [])).catch(() => {});
  }

  function buildHistory(): { role: 'user' | 'assistant'; content: string }[] {
    return messages
      .filter((m) => m.content && m.content.trim())
      .map((m) => ({ role: m.role, content: m.content }));
  }

  function newChat() {
    setMessages([]);
    setConvId(null);
    setGenieSpace(null);
  }

  // Rebuild a stored conversation. Assistant rows carry a meta JSON blob with
  // the tool UI payloads (Genie tables, contract citations) so they re-render.
  function rebuild(raw: any[]): Msg[] {
    return raw.map((m) => {
      if (m.role === 'user') return { role: 'user', content: m.content } as Msg;
      let tools: ToolStep[] | undefined;
      if (m.meta) {
        try {
          const parsed = JSON.parse(m.meta);
          if (parsed?.tools?.length) {
            tools = parsed.tools.map((ui: ToolUI) => ({
              name: ui.type === 'genie' ? 'genie_query' : 'contract_search',
              ui,
            }));
          }
        } catch { /* ignore */ }
      }
      return { role: 'assistant', content: m.content, status: 'done', tools } as Msg;
    });
  }

  async function loadConversation(id: string) {
    setConvId(id);
    setGenieSpace(null);
    setLoadingConv(id);
    try {
      const r = await fetch(`/api/conversations/${id}`);
      const d = await r.json();
      setMessages(rebuild(d.messages || []));
    } catch {
      toast.error('Could not load that conversation.');
    } finally {
      setLoadingConv(null);
    }
  }

  async function readSSE(resp: Response, onEvent: (evt: any) => void) {
    if (!resp.ok || !resp.body) throw new Error('Request failed');
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const parts = buf.split('\n\n');
      buf = parts.pop() || '';
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith('data:')) continue;
        const payload = line.slice(5).trim();
        if (!payload) continue;
        try { onEvent(JSON.parse(payload)); } catch { /* partial */ }
      }
    }
  }

  function patchLast(fn: (m: Msg) => Msg) {
    setMessages((cur) => {
      const copy = [...cur];
      copy[copy.length - 1] = fn(copy[copy.length - 1]);
      return copy;
    });
  }

  async function send(text?: string) {
    const msg = (text ?? input).trim();
    if (!msg || streaming) return;
    setInput('');
    if (taRef.current) taRef.current.style.height = 'auto';
    const history = buildHistory();
    setMessages((cur) => [
      ...cur,
      { role: 'user', content: msg },
      { role: 'assistant', content: '', status: 'thinking', tools: [] },
    ]);
    setStreaming(true);
    try {
      const resp = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg, conversation_id: convId, history }),
      });
      await readSSE(resp, (evt) => {
        if (evt.type === 'meta' && evt.conversation_id) {
          setConvId(evt.conversation_id);
        } else if (evt.type === 'tool_call') {
          patchLast((m) => ({ ...m, status: 'thinking', tools: [...(m.tools || []), { name: evt.name, question: evt.question }] }));
        } else if (evt.type === 'tool_result') {
          patchLast((m) => {
            const tools = [...(m.tools || [])];
            // attach ui to the most recent matching tool step without a ui
            for (let i = tools.length - 1; i >= 0; i--) {
              if (tools[i].name === evt.name && !tools[i].ui) { tools[i] = { ...tools[i], ui: evt.ui }; break; }
            }
            return { ...m, tools };
          });
        } else if (evt.type === 'token') {
          patchLast((m) => ({ ...m, status: 'streaming', content: m.content + evt.delta }));
        } else if (evt.type === 'error') {
          patchLast((m) => ({ ...m, status: 'error', content: m.content || `Error: ${evt.message}` }));
          toast.error(evt.message || 'Agent error');
        } else if (evt.type === 'done') {
          patchLast((m) => ({ ...m, status: m.status === 'error' ? 'error' : 'done' }));
          refreshConversations();
        }
      });
    } catch {
      patchLast((m) => ({ ...m, status: 'error', content: m.content || 'Something went wrong.' }));
      toast.error('Something went wrong talking to the agent.');
    } finally {
      setStreaming(false);
    }
  }

  const brand = cfg.branding?.name || 'Contract Intelligence';
  const suggestions = cfg.home?.suggestions?.length ? cfg.home.suggestions : FALLBACK_SUGGESTIONS;

  return (
    <div className="flex h-screen bg-neutral-50 text-neutral-900">
      {/* Sidebar */}
      <aside className="flex w-72 flex-col border-r border-neutral-200 bg-white">
        <button
          onClick={newChat}
          className="mx-3 mt-4 flex items-center gap-2 rounded-xl border border-neutral-200 bg-white px-3 py-2.5 text-sm font-medium text-neutral-700 shadow-sm transition hover:border-neutral-300 hover:bg-neutral-50"
        >
          <Plus size={16} /> New chat
        </button>

        {/* Conversation history */}
        <div className="mt-3 px-3 text-[11px] font-semibold uppercase tracking-wide text-neutral-400">Recent</div>
        <div className="mt-1 flex-1 overflow-y-auto px-2">
          {convs.length === 0 && <div className="px-2 py-2 text-xs text-neutral-400">No conversations yet.</div>}
          {convs.map((c) => (
            <button
              key={c.conversation_id}
              onClick={() => loadConversation(c.conversation_id)}
              className={`mb-0.5 flex w-full items-center gap-2 truncate rounded-md px-2 py-2 text-left text-sm hover:bg-neutral-100 ${
                convId === c.conversation_id && !genieSpace ? 'bg-neutral-100' : ''
              }`}
            >
              {loadingConv === c.conversation_id ? (
                <Loader2 size={14} className="shrink-0 animate-spin text-neutral-400" />
              ) : (
                <MessageSquare size={14} className="shrink-0 text-neutral-400" />
              )}
              <span className="truncate">{c.title || 'Untitled'}</span>
            </button>
          ))}
        </div>

        {/* Genie spaces panel */}
        <div className="border-t border-neutral-200">
          <button
            onClick={() => setSpacesOpen((v) => !v)}
            className="flex w-full items-center gap-2 px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-neutral-400 hover:text-neutral-600"
          >
            {spacesOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            <Database size={13} /> Genie spaces
          </button>
          {spacesOpen && (
            <div className="max-h-56 overflow-y-auto px-2 pb-2">
              {spaces.length === 0 && <div className="px-2 py-1 text-xs text-neutral-400">No accessible spaces.</div>}
              {spaces.map((s) => (
                <button
                  key={s.space_id}
                  onClick={() => { setGenieSpace(s); setMessages([]); }}
                  title={s.description || s.title}
                  className={`mb-0.5 flex w-full items-center gap-2 truncate rounded-md px-2 py-1.5 text-left text-xs hover:bg-sky-50 ${
                    genieSpace?.space_id === s.space_id ? 'bg-sky-50 text-sky-700' : 'text-neutral-600'
                  }`}
                >
                  <Database size={12} className="shrink-0 text-sky-500" />
                  <span className="truncate">{s.title}</span>
                  {s.space_id === defaultSpaceId && <span className="ml-auto rounded bg-neutral-100 px-1 text-[9px] text-neutral-500">chat</span>}
                </button>
              ))}
            </div>
          )}
        </div>

        {email && (
          <div className="truncate border-t border-neutral-200 px-4 py-3 text-xs text-neutral-500">{email}</div>
        )}
      </aside>

      {/* Main */}
      <main className="flex flex-1 flex-col">
        {genieSpace ? (
          <GeniePanel space={genieSpace} onClose={() => setGenieSpace(null)} />
        ) : (
          <>
            <div ref={scrollRef} onScroll={onScroll} className="flex-1 overflow-y-auto px-6 py-8">
              {messages.length === 0 ? (
                <div className="mx-auto mt-12 max-w-2xl text-center">
                  <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-[#1B4D6B] text-white">
                    <Sparkles size={22} />
                  </div>
                  <h1 className="mt-4 text-2xl font-semibold text-neutral-800">{cfg.home?.title || brand}</h1>
                  <p className="mx-auto mt-2 max-w-xl text-sm leading-relaxed text-neutral-500">
                    {cfg.home?.description ||
                      'Ask questions about your data and your documents. I read your structured tables through a Genie space and your documents through grounded search, then answer with the numbers and the source text together.'}
                  </p>
                  <div className="mx-auto mt-8 grid max-w-2xl grid-cols-1 gap-2 sm:grid-cols-2">
                    {suggestions.map((s) => (
                      <button
                        key={s}
                        onClick={() => send(s)}
                        className="rounded-xl border border-neutral-200 bg-white px-4 py-3 text-left text-sm text-neutral-700 shadow-sm transition hover:border-[#1B4D6B] hover:bg-neutral-50"
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="mx-auto max-w-3xl space-y-6">
                  {messages.map((m, i) =>
                    m.role === 'user' ? (
                      <div key={i} className="flex justify-end">
                        <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-[#1B4D6B] px-4 py-2.5 text-[15px] leading-relaxed text-white shadow-sm">
                          {m.content}
                        </div>
                      </div>
                    ) : (
                      <AssistantBubble key={i} m={m} />
                    )
                  )}
                </div>
              )}
            </div>

            {/* Composer — blends into the thread: no divider, floating input */}
            <div className="bg-transparent px-6 pb-5 pt-1">
              <div className="mx-auto max-w-3xl">
                <div className="relative flex items-end rounded-[1.75rem] border border-neutral-200 bg-white shadow-lg shadow-neutral-300/30 transition focus-within:border-[#1B4D6B]/40 focus-within:shadow-neutral-400/30">
                  <textarea
                    ref={taRef}
                    value={input}
                    onChange={(e) => { setInput(e.target.value); autoGrow(); }}
                    onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
                    rows={1}
                    placeholder="Ask about your data and your documents…"
                    style={{ backgroundColor: 'transparent', color: '#18181b', colorScheme: 'light' }}
                    className="flex-1 resize-none overflow-y-auto bg-transparent py-3.5 pl-5 pr-14 text-[15px] leading-relaxed placeholder:text-neutral-400 focus:outline-none"
                  />
                  <button
                    onClick={() => send()}
                    disabled={streaming || !input.trim()}
                    className="absolute bottom-2 right-2 flex h-9 w-9 items-center justify-center rounded-full bg-[#1B4D6B] text-white transition hover:bg-[#163e57] disabled:opacity-30"
                    title="Send"
                  >
                    {streaming ? <Loader2 size={17} className="animate-spin" /> : <ArrowUp size={17} />}
                  </button>
                </div>
                <div className="mt-2 text-center text-[11px] text-neutral-400">
                  Runs in your tenant under your Unity Catalog permissions.{cfg.branding?.subtitle ? ` ${cfg.branding.subtitle}` : ''}
                </div>
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function AssistantBubble({ m }: { m: Msg }) {
  const showThinking = m.status === 'thinking' || (m.status === 'streaming' && !m.content);
  return (
    <div className="flex justify-start gap-3">
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[#1B4D6B] text-white">
        <Sparkles size={14} />
      </div>
      <div className="min-w-0 flex-1 space-y-2.5">
        {/* Tool trace */}
        {(m.tools || []).map((t, i) => {
          const meta = toolLabel(t.name);
          const Icon = meta.icon;
          return (
            <div key={i} className="space-y-2">
              <div className={`flex items-center gap-2 text-xs font-medium ${meta.color}`}>
                <Icon size={13} />
                {meta.label}
                {t.question && <span className="truncate text-neutral-400">: {t.question}</span>}
                {!t.ui && m.status !== 'done' && <Loader2 size={12} className="animate-spin" />}
              </div>
              {t.ui && <ToolResult ui={t.ui} />}
            </div>
          );
        })}

        {/* Answer — borderless, flows on the page (modern chat style) */}
        {(m.content || showThinking) &&
          (showThinking && !m.content ? (
            <div className="flex items-center gap-2 py-1 text-sm text-neutral-400">
              <Loader2 size={14} className="animate-spin" /> Thinking…
            </div>
          ) : (
            <div className="prose prose-sm max-w-none prose-neutral prose-table:my-2 prose-headings:font-semibold">
              <MD>{m.content || ' '}</MD>
            </div>
          ))}
      </div>
    </div>
  );
}

// Direct Genie space chat panel (separate from the supervisor chat).
// Multi-turn: keeps the Genie conversation_id so follow-up questions build on
// prior turns (chain-of-thought), and shows the full thread as history.
interface GenieTurn { role: 'user' | 'assistant'; text?: string; ui?: ToolUI }

function GeniePanel({ space, onClose }: { space: GenieSpace; onClose: () => void }) {
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(false);
  const [turns, setTurns] = useState<GenieTurn[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  // Reset the thread whenever the user switches to a different space.
  useEffect(() => {
    setTurns([]);
    setConversationId(null);
    setQ('');
  }, [space.space_id]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [turns, loading]);

  function newConversation() {
    if (loading) return;
    setTurns([]);
    setConversationId(null);
  }

  async function run(question?: string) {
    const text = (question ?? q).trim();
    if (!text || loading) return;
    setLoading(true);
    setQ('');
    setTurns((t) => [...t, { role: 'user', text }]);
    try {
      const r = await fetch('/api/genie/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: text,
          space_id: space.space_id,
          conversation_id: conversationId,
        }),
      });
      const d = await r.json();
      if (d.conversation_id) setConversationId(d.conversation_id);
      setTurns((t) => [...t, { role: 'assistant', text: d.text, ui: { type: 'genie', ...d } }]);
    } catch {
      setTurns((t) => [...t, { role: 'assistant', ui: { type: 'genie', ok: false, error: 'Query failed.' } }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-2 border-b border-neutral-200 bg-white px-6 py-3">
        <Database size={16} className="text-sky-600" />
        <div className="font-semibold text-neutral-800">{space.title}</div>
        <span className="rounded bg-sky-50 px-2 py-0.5 text-[11px] text-sky-700">
          {conversationId ? 'Genie chat · multi-turn' : 'Genie chat'}
        </span>
        <button
          onClick={newConversation}
          disabled={loading || turns.length === 0}
          className="ml-auto rounded-md px-2 py-1 text-[12px] text-neutral-500 hover:bg-neutral-100 disabled:opacity-40"
          title="Start a new Genie conversation"
        >
          New conversation
        </button>
        <button onClick={onClose} className="rounded-md p-1 text-neutral-400 hover:bg-neutral-100" title="Back to chat">
          <X size={16} />
        </button>
      </header>
      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto max-w-3xl space-y-5">
          {turns.length === 0 && !loading && (
            <div className="text-sm text-neutral-400">
              {space.description
                ? <span className="whitespace-pre-wrap">{space.description}</span>
                : 'Ask this space a question. Follow-ups keep the conversation context, so you can drill down step by step.'}
            </div>
          )}
          {turns.map((turn, i) =>
            turn.role === 'user' ? (
              <div key={i} className="flex justify-end">
                <div className="max-w-[85%] rounded-2xl rounded-br-md bg-sky-600 px-4 py-2.5 text-sm leading-relaxed text-white shadow-sm">{turn.text}</div>
              </div>
            ) : (
              <div key={i} className="space-y-3">
                {turn.text && (
                  <div className="prose prose-sm max-w-none prose-neutral">
                    <MD>{turn.text}</MD>
                  </div>
                )}
                {turn.ui && <ToolResult ui={turn.ui} />}
              </div>
            )
          )}
          {loading && (
            <div className="flex items-center gap-2 text-sm text-neutral-400">
              <Loader2 size={14} className="animate-spin" /> Running query in Genie…
            </div>
          )}
          <div ref={endRef} />
        </div>
      </div>
      <div className="bg-transparent px-6 pb-5 pt-1">
        <div className="mx-auto max-w-3xl">
          <div className="relative flex items-end rounded-[1.75rem] border border-neutral-200 bg-white shadow-lg shadow-neutral-300/30 transition focus-within:border-sky-400/50">
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') run(); }}
              placeholder={conversationId ? 'Ask a follow-up…' : `Ask ${space.title}…`}
              style={{ backgroundColor: 'transparent', color: '#18181b', colorScheme: 'light' }}
              className="flex-1 bg-transparent py-3.5 pl-5 pr-14 text-[15px] placeholder:text-neutral-400 focus:outline-none"
            />
            <button
              onClick={() => run()}
              disabled={loading || !q.trim()}
              className="absolute bottom-2 right-2 flex h-9 w-9 items-center justify-center rounded-full bg-sky-600 text-white transition hover:bg-sky-700 disabled:opacity-30"
              title="Send"
            >
              {loading ? <Loader2 size={17} className="animate-spin" /> : <ArrowUp size={17} />}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
