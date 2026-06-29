import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import 'katex/dist/katex.min.css';

// Normalize LaTeX delimiters so all common styles render: models emit
// \( ... \) and \[ ... \] as well as $ ... $ / $$ ... $$. remark-math only
// understands the dollar forms, so convert the backslash forms first.
export function normalizeMath(s: string): string {
  return s
    .replace(/\\\[((?:.|\n)*?)\\\]/g, (_m, inner) => `\n$$\n${inner}\n$$\n`)
    .replace(/\\\(((?:.|\n)*?)\\\)/g, (_m, inner) => `$${inner}$`);
}

// Shared markdown renderer with math (KaTeX) + syntax-highlighted code blocks.
export function MD({ children }: { children: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[[rehypeKatex, { throwOnError: false, errorColor: '#9ca3af' }]]}
      components={{
        code({ inline, className, children, ...props }: any) {
          const match = /language-(\w+)/.exec(className || '');
          if (!inline && match) {
            return (
              <SyntaxHighlighter style={oneLight} language={match[1]} PreTag="div" customStyle={{ borderRadius: 8, fontSize: 12 }}>
                {String(children).replace(/\n$/, '')}
              </SyntaxHighlighter>
            );
          }
          return (
            <code className={className} {...props}>
              {children}
            </code>
          );
        },
      }}
    >
      {normalizeMath(children)}
    </ReactMarkdown>
  );
}
