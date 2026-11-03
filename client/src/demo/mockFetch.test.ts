import { describe, it, expect, beforeEach, vi } from 'vitest';
import { install } from './mockFetch';

type Fetch = typeof fetch;

function setup(delayScale = 0) {
  const passthrough = vi.fn(async () => new Response('passed', { status: 200 }));
  const target = { fetch: passthrough as unknown as Fetch };
  install(target, { delayScale });
  return { f: target.fetch, passthrough };
}

async function readEvents(resp: Response) {
  const reader = resp.body!.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  let chunks = 0;
  const events: any[] = [];
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks += 1;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split('\n\n');
    buf = parts.pop() || '';
    for (const p of parts) if (p.startsWith('data: ')) events.push(JSON.parse(p.slice(6)));
  }
  return { events, chunks };
}

const post = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

describe('mockFetch routes', () => {
  let f: Fetch;
  let passthrough: ReturnType<typeof vi.fn>;
  beforeEach(() => { ({ f, passthrough } = setup()); });

  it('serves app config with only branding and home', async () => {
    const r = await f('/api/config/app');
    expect(r.status).toBe(200);
    const d = await r.json();
    expect(Object.keys(d).sort()).toEqual(['branding', 'home']);
    expect(d.branding.name).toBe('Contract Intelligence');
    expect(d.home.suggestions.length).toBeGreaterThan(0);
    expect(JSON.stringify(d)).not.toContain('system_prompt');
  });

  it('serves a demo user on an example domain', async () => {
    const d = await (await f('/api/me')).json();
    expect(d.email).toMatch(/@example\.com$/);
  });

  it('serves genie spaces', async () => {
    const d = await (await f('/api/genie/spaces')).json();
    expect(d.default_space_id).toBe('rc');
    expect(d.spaces.map((s: any) => s.space_id)).toEqual(['rc', 'pc']);
  });

  it('lists conversations and loads one by id', async () => {
    const list = await (await f('/api/conversations')).json();
    expect(list.conversations.length).toBe(4);
    const d = await (await f('/api/conversations/c-cigna')).json();
    expect(d.messages.map((m: any) => m.role)).toEqual(['user', 'assistant']);
    const meta = JSON.parse(d.messages[1].meta);
    expect(meta.tools.map((t: any) => t.type)).toEqual(['genie', 'contract']);
    expect(d.messages[1].content).toContain('Cigna');
  });

  it('returns 404 for an unknown conversation and unknown /api paths', async () => {
    expect((await f('/api/conversations/nope')).status).toBe(404);
    expect((await f('/api/does-not-exist')).status).toBe(404);
    expect((await f('/api/chat')).status).toBe(404); // GET is not a route
    expect(passthrough).not.toHaveBeenCalled();
  });

  it('answers a genie query with a table', async () => {
    const d = await (await f('/api/genie/query', post({ question: 'Cigna denials by quarter', space_id: 'rc' }))).json();
    expect(d.type).toBe('genie');
    expect(d.columns.length).toBeGreaterThan(0);
    expect(d.rows.length).toBe(6);
    expect(d.conversation_id).toBe('g1');
  });

  it('answers an off-script genie query with guidance and no table', async () => {
    const d = await (await f('/api/genie/query', post({ question: 'what is the weather' }))).json();
    expect(d.rows).toBeUndefined();
    expect(d.text).toContain('scripted questions');
  });

  it('passes non-api requests through untouched', async () => {
    const r = await f('/assets/index.js');
    expect(await r.text()).toBe('passed');
    await f('https://fonts.googleapis.com/css2?family=Inter');
    await f('/apiary');
    expect(passthrough).toHaveBeenCalledTimes(3);
  });

  it('handles Request objects', async () => {
    const r = await f(new Request('http://localhost/api/me'));
    expect((await r.json()).email).toBeTruthy();
  });
});

describe('mockFetch chat stream', () => {
  it('streams a scripted story in the mock event order over many chunks', async () => {
    const { f } = setup();
    const r = await f('/api/chat', post({ message: 'Which payers underpaid us last quarter?' }));
    expect(r.headers.get('content-type')).toBe('text/event-stream');
    const { events, chunks } = await readEvents(r);
    expect(chunks).toBeGreaterThan(1);
    const types = events.map((e) => e.type);
    expect(types.slice(0, 5)).toEqual(['meta', 'tool_call', 'tool_result', 'tool_call', 'tool_result']);
    expect(types[types.length - 1]).toBe('done');
    expect(types.slice(5, -1).every((t) => t === 'token')).toBe(true);
    expect(types.filter((t) => t === 'token').length).toBeGreaterThan(3);
    expect(events[2].ui.type).toBe('genie');
    expect(events[4].ui.type).toBe('contract');
    const text = events.filter((e) => e.type === 'token').map((e) => e.delta).join('');
    expect(text).toContain('UnitedHealthcare');
  });

  it('routes cigna questions to the cigna story', async () => {
    const { f } = setup();
    const { events } = await readEvents(await f('/api/chat', post({ message: 'Show Cigna timely-filing denials' })));
    expect(events[1].question).toMatch(/Cigna/);
  });

  it('answers off-script questions with the generic reply and no tools', async () => {
    const { f } = setup();
    const { events } = await readEvents(await f('/api/chat', post({ message: 'Tell me a joke' })));
    const types = events.map((e) => e.type);
    expect(types[0]).toBe('meta');
    expect(types[types.length - 1]).toBe('done');
    expect(types).not.toContain('tool_call');
    const text = events.filter((e) => e.type === 'token').map((e) => e.delta).join('');
    expect(text).toContain('scripted questions');
  });

  it('adds new chats to the in-memory history and stores their messages', async () => {
    const { f } = setup();
    const { events } = await readEvents(await f('/api/chat', post({ message: 'Tell me a joke' })));
    const id = events[0].conversation_id;
    const list = await (await f('/api/conversations')).json();
    expect(list.conversations[0]).toEqual({ conversation_id: id, title: 'Tell me a joke' });
    const d = await (await f(`/api/conversations/${id}`)).json();
    expect(d.messages.map((m: any) => m.content)[0]).toBe('Tell me a joke');
    // A follow-up in the same conversation appends instead of creating a new one.
    await readEvents(await f('/api/chat', post({ message: 'Cigna denials?', conversation_id: id })));
    const d2 = await (await f(`/api/conversations/${id}`)).json();
    expect(d2.messages.length).toBe(4);
    expect((await (await f('/api/conversations')).json()).conversations.length).toBe(5);
  });

  it('paces events with real delays at the default timing', async () => {
    const { f } = setup(1);
    const t0 = Date.now();
    const { events } = await readEvents(await f('/api/chat', post({ message: 'Cigna denials by quarter' })));
    expect(Date.now() - t0).toBeGreaterThanOrEqual(1900);
    expect(events[events.length - 1].type).toBe('done');
  });
});
