import { useState } from 'react';
import { Database, FileText, ChevronDown, ChevronRight, Code2 } from 'lucide-react';

// Structured tool-result payloads emitted by the supervisor and persisted in
// message.meta, so a restored conversation re-renders tables + citations.
export interface GenieUI {
  type: 'genie';
  ok?: boolean;
  text?: string;
  sql?: string;
  columns?: string[];
  rows?: any[][];
  row_count?: number;
  error?: string;
}
export interface ContractUI {
  type: 'contract';
  ok?: boolean;
  answer?: string;
  citations?: { source_file?: string; page_id?: any }[];
  error?: string;
}
export type ToolUI = GenieUI | ContractUI;

function GenieTable({ ui }: { ui: GenieUI }) {
  const [showSql, setShowSql] = useState(false);
  const cols = ui.columns || [];
  const rows = ui.rows || [];
  return (
    <div className="overflow-hidden rounded-xl border border-sky-200 bg-sky-50/40">
      <div className="flex items-center gap-2 border-b border-sky-200 bg-sky-50 px-3 py-2 text-xs font-semibold text-sky-800">
        <Database size={14} /> Genie · your data
        {typeof ui.row_count === 'number' && (
          <span className="ml-auto font-normal text-sky-600">{ui.row_count} rows</span>
        )}
      </div>
      {ui.error ? (
        <div className="px-3 py-2 text-sm text-red-600">{ui.error}</div>
      ) : (
        <>
          {cols.length > 0 && rows.length > 0 && (
            <div className="max-h-80 overflow-auto">
              <table className="w-full border-collapse text-xs">
                <thead className="sticky top-0 bg-white">
                  <tr>
                    {cols.map((c) => (
                      <th key={c} className="border-b border-sky-100 px-3 py-1.5 text-left font-semibold text-neutral-700">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, 100).map((r, i) => (
                    <tr key={i} className="odd:bg-white even:bg-sky-50/40">
                      {r.map((cell, j) => (
                        <td key={j} className="border-b border-sky-50 px-3 py-1.5 text-neutral-700 tabular-nums">
                          {String(cell ?? '')}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {ui.sql && (
            <div className="border-t border-sky-100">
              <button
                onClick={() => setShowSql((v) => !v)}
                className="flex w-full items-center gap-1.5 px-3 py-1.5 text-xs text-sky-700 hover:bg-sky-50"
              >
                {showSql ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                <Code2 size={13} /> {showSql ? 'Hide' : 'View'} generated SQL
              </button>
              {showSql && (
                <pre className="max-h-56 overflow-auto bg-neutral-900 px-3 py-2 text-[11px] leading-relaxed text-neutral-100">
                  {ui.sql}
                </pre>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ContractCard({ ui }: { ui: ContractUI }) {
  const cites = ui.citations || [];
  return (
    <div className="overflow-hidden rounded-xl border border-amber-200 bg-amber-50/40">
      <div className="flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-800">
        <FileText size={14} /> Document search · grounded
      </div>
      {ui.error ? (
        <div className="px-3 py-2 text-sm text-red-600">{ui.error}</div>
      ) : (
        cites.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-3 py-2">
            {cites.map((c, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-white px-2 py-0.5 text-[11px] text-amber-900"
                title={c.source_file}
              >
                <FileText size={11} className="opacity-60" />
                <span className="max-w-[220px] truncate">{c.source_file}</span>
                {c.page_id !== undefined && c.page_id !== null && c.page_id !== '' && (
                  <span className="text-amber-500">p{String(c.page_id)}</span>
                )}
              </span>
            ))}
          </div>
        )
      )}
    </div>
  );
}

export function ToolResult({ ui }: { ui: ToolUI }) {
  if (!ui) return null;
  if (ui.type === 'genie') return <GenieTable ui={ui} />;
  if (ui.type === 'contract') return <ContractCard ui={ui} />;
  return null;
}
