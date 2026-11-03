// Small fixed pill shown only in the static demo build, clear of every button
// and input: on desktop it sits over the sidebar footer (the signed-in user
// line); below md it sits in the top bar, to the right of the menu button.
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
      className="fixed left-14 right-2 top-3 z-50 whitespace-nowrap text-center md:bottom-2 md:left-1 md:right-auto md:top-auto md:text-left rounded-full bg-neutral-900 px-2.5 py-1.5 text-[11px] font-medium leading-4 text-white shadow-md hover:bg-neutral-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 focus-visible:ring-offset-2"
    >
      Demo with synthetic data. <span className="underline underline-offset-2">View source on GitHub</span>
    </a>
  );
}
