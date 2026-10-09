/**
 * In-app replacements for window.prompt / window.confirm.
 *
 * The browser's own pop-ups are blocked or silently return nothing in embedded browsers (the
 * VS Code browser, some kiosk/WebView set-ups), so buttons that relied on them - Void, Delete
 * entry, Reverse, Reopen - did nothing. These open the app's own dialog instead:
 *
 *   const reason = await askText("Why is this invoice being voided?");   // string | null
 *   if (await askConfirm("Close FY 2026?")) { ... }                       // boolean
 *
 * <AskHost /> is mounted once in App.tsx.
 */
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";

type Req = { kind: "text" | "confirm"; message: string; defaultValue?: string; resolve: (v: string | boolean | null) => void };

let push: ((r: Req) => void) | null = null;
const waiting: Req[] = [];

function enqueue(r: Req) {
  if (push) push(r);
  else waiting.push(r);
}

/** Ask for a line of text (a reason, a name, a date). Resolves to null when cancelled, "" when left empty. */
export function askText(message: string, defaultValue?: string): Promise<string | null> {
  return new Promise((resolve) => enqueue({ kind: "text", message, defaultValue, resolve: (v) => resolve(v as string | null) }));
}

/** Ask the user to confirm. Resolves to true only when they press the confirm button. */
export function askConfirm(message: string): Promise<boolean> {
  return new Promise((resolve) => enqueue({ kind: "confirm", message, resolve: (v) => resolve(v === true) }));
}

export function AskHost() {
  const [queue, setQueue] = useState<Req[]>([]);
  const [value, setValue] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    push = (r) => setQueue((q) => [...q, r]);
    if (waiting.length) setQueue((q) => [...q, ...waiting.splice(0)]);
    return () => { push = null; };
  }, []);
  const cur = queue[0];
  useEffect(() => {
    setValue(cur?.defaultValue ?? "");
    if (cur?.kind === "text") setTimeout(() => input.current?.focus(), 50);
  }, [cur]);
  const done = (v: string | boolean | null) => {
    cur?.resolve(v);
    setQueue((q) => q.slice(1));
  };
  // the first line is the question; anything after it is explanation
  const [title, ...rest] = (cur?.message ?? "").split("\n");
  return (
    <Dialog open={!!cur} onOpenChange={(o) => { if (!o) done(cur?.kind === "confirm" ? false : null); }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-base">{title}</DialogTitle>
          {rest.join("\n").trim() && <DialogDescription className="whitespace-pre-line">{rest.join("\n").trim()}</DialogDescription>}
        </DialogHeader>
        {cur?.kind === "text" && (
          <Textarea ref={input} rows={2} value={value} onChange={(e) => setValue(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); done(value.trim()); } }} />
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => done(cur?.kind === "confirm" ? false : null)}>Cancel</Button>
          <Button onClick={() => done(cur?.kind === "confirm" ? true : value.trim())}>{cur?.kind === "confirm" ? "Yes, continue" : "OK"}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
