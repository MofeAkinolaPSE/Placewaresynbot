import { useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

/**
 * In-app Back/Forward, distinct from relying on the browser's own back
 * button (easy to miss, especially full-screen/kiosk-style during
 * training). Deliberately uses navigate(-1)/navigate(1) rather than a
 * hand-rolled history stack -- react-router's HashRouter already pushes a
 * real browser history entry for every navigation in this app (sidebar
 * links, quick-action buttons, programmatic navigate() calls all go
 * through the same one stack), so this stays perfectly consistent with
 * that stack instead of risking a second, divergent one.
 *
 * canGoBack comes straight from history.state.idx (react-router's `history`
 * package sets this on every push, so it's reliable). canGoForward has no
 * native equivalent (browsers don't expose "how many forward entries
 * exist"), so it's tracked as "have we been deeper than this before, in
 * this tab" -- exactly how a real browser's forward button behaves.
 */
export function useBackForward() {
  const location = useLocation();
  const navigate = useNavigate();

  const readIdx = () => (window.history.state && typeof window.history.state.idx === "number")
    ? window.history.state.idx
    : 0;

  const [idx, setIdx] = useState(readIdx);
  const [maxIdx, setMaxIdx] = useState(readIdx);

  useEffect(() => {
    const current = readIdx();
    setIdx(current);
    setMaxIdx((prev) => Math.max(prev, current));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location]);

  const canGoBack = idx > 0;
  const canGoForward = idx < maxIdx;

  const goBack = useCallback(() => {
    if (canGoBack) navigate(-1);
  }, [canGoBack, navigate]);

  const goForward = useCallback(() => {
    if (canGoForward) navigate(1);
  }, [canGoForward, navigate]);

  return { goBack, goForward, canGoBack, canGoForward };
}
