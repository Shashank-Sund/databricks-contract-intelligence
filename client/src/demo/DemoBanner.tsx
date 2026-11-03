// Small fixed pill shown only in the static demo build. It sits over the
// sidebar footer (the signed-in user line), clear of every button and input.
const REPO_URL = 'https://github.com/Shashank-Sund/databricks-contract-intelligence';

export function DemoBanner() {
  return (
    <a
      href={REPO_URL}
      target="_blank"
      rel="noopener noreferrer"
      data-testid="demo-banner"
      // Inline color: the global content-link rule would otherwise recolor it.
      style={{ color: '#ffffff' }}
      className="fixed bottom-2 left-1 z-50 whitespace-nowrap rounded-full bg-neutral-900 px-2.5 py-1.5 text-[11px] font-medium leading-4 text-white shadow-md hover:bg-neutral-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 focus-visible:ring-offset-2"
    >
      Demo with synthetic data. <span className="underline underline-offset-2">View source on GitHub</span>
    </a>
  );
}
