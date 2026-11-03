// In-browser stand-in for the FastAPI server, used only by the static demo
// build (VITE_DEMO=static). install() wraps fetch so /api/* is answered from
// synthetic data in memory; every other request passes through untouched.
import {
  appConfig, demoUser, genieSpaces, genericGenieText, pickStory, seedHistory,
  cigna, leakage, type ConvSummary, type Story,
} from './mockData';

interface StoredMsg { role: 'user' | 'assistant'; content: string; meta?: string }

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function metaFor(s: Story): string | undefined {
  const tools = [s.ui, s.docUi].filter(Boolean);
  return tools.length ? JSON.stringify({ tools }) : undefined;
}

export interface MockServer {
  handle(path: string, method: string, body: string): Promise<Response>;
}

export function createMockServer(opts: { delayScale?: number } = {}): MockServer {
  const scale = opts.delayScale ?? 1;
  const pause = (ms: number) => wait(ms * scale);
  const history: ConvSummary[] = seedHistory();
  const stored = new Map<string, StoredMsg[]>();
  let counter = 0;

  function conversation(id: string): StoredMsg[] | null {
    const own = stored.get(id);
    if (own) return own;
    const h = history.find((c) => c.conversation_id === id);
    if (!h) return null;
    const s = id === 'c-cigna' ? cigna : leakage;
    return [
      { role: 'user', content: h.title },
      { role: 'assistant', content: s.text, meta: metaFor(s) },
    ];
  }

  function chat(body: string): Response {
    let req: { message?: string; conversation_id?: string | null } = {};
    try { req = JSON.parse(body || '{}'); } catch { /* empty body */ }
    const message = (req.message || '').trim();
    const s = pickStory(message);

    let id = req.conversation_id && stored.has(req.conversation_id) ? req.conversation_id : null;
    if (!id) {
      counter += 1;
      id = `c-new-${counter}`;
      stored.set(id, []);
      const title = message.length > 60 ? `${message.slice(0, 57)}...` : message || 'New chat';
      history.unshift({ conversation_id: id, title });
    }
    const convId = id;

    const enc = new TextEncoder();
    let cancelled = false;
    const stream = new ReadableStream<Uint8Array>({
      async start(controller) {
        const send = (e: unknown) => { if (!cancelled) controller.enqueue(enc.encode(`data: ${JSON.stringify(e)}\n\n`)); };
        send({ type: 'meta', conversation_id: convId });
        if (s.tool && s.ui) {
          send({ type: 'tool_call', ...s.tool }); await pause(700);
          send({ type: 'tool_result', name: s.tool.name, ui: s.ui }); await pause(300);
        }
        if (s.doc && s.docUi) {
          send({ type: 'tool_call', ...s.doc }); await pause(700);
          send({ type: 'tool_result', name: s.doc.name, ui: s.docUi }); await pause(200);
        }
        for (const piece of s.text.match(/[\s\S]{1,24}/g) || []) {
          if (cancelled) return;
          send({ type: 'token', delta: piece }); await pause(12);
        }
        stored.get(convId)?.push({ role: 'user', content: message }, { role: 'assistant', content: s.text, meta: metaFor(s) });
        send({ type: 'done' });
        if (!cancelled) controller.close();
      },
      cancel() { cancelled = true; },
    });
    return new Response(stream, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
    });
  }

  async function handle(path: string, method: string, body: string): Promise<Response> {
    if (path === '/api/config/app') return json(appConfig);
    if (path === '/api/me') return json(demoUser);
    if (path === '/api/genie/spaces') return json(genieSpaces);
    if (path === '/api/conversations') return json({ conversations: history });
    if (path.startsWith('/api/conversations/')) {
      const msgs = conversation(decodeURIComponent(path.slice('/api/conversations/'.length)));
      return msgs ? json({ messages: msgs }) : json({ detail: 'Not found' }, 404);
    }
    if (path === '/api/genie/query' && method === 'POST') {
      let q = '';
      try { q = JSON.parse(body || '{}').question || ''; } catch { /* empty body */ }
      await pause(600);
      const s = pickStory(q);
      if (!s.ui) return json({ ok: true, text: genericGenieText, conversation_id: 'g1' });
      return json({ ...s.ui, text: 'Here is what I found.', conversation_id: 'g1' });
    }
    if (path === '/api/chat' && method === 'POST') return chat(body);
    return json({ detail: 'Not found' }, 404);
  }

  return { handle };
}

export function install(target: { fetch: typeof fetch } = globalThis, opts: { delayScale?: number } = {}): void {
  const original = target.fetch.bind(target);
  const server = createMockServer(opts);
  const base = (globalThis as { location?: Location }).location?.href ?? 'http://localhost/';
  const origin = new URL(base).origin;

  target.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const raw = input instanceof Request ? input.url : String(input);
    const url = new URL(raw, base);
    if (url.origin !== origin || !(url.pathname === '/api' || url.pathname.startsWith('/api/'))) {
      return original(input, init);
    }
    const method = (init?.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    let body = '';
    if (typeof init?.body === 'string') body = init.body;
    else if (input instanceof Request) body = await input.clone().text();
    return server.handle(url.pathname, method, body);
  };
}
