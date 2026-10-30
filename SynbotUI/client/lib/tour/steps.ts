/**
 * Building blocks for walkthrough steps, so each guide reads as a list of what is on the screen.
 * Labels are the controls' exact on-screen text (matched from the start, so "Reorder plan" finds "Reorder plan (36)").
 */
import type { TargetKind, WalkthroughStep } from "../walkthroughs";

type Opt = Partial<WalkthroughStep>;

/** A tab: safe - the step advances when the person clicks it. */
export const tab = (label: string, title: string, body: string, o: Opt = {}): WalkthroughStep =>
  ({ title, body, target: label, kind: "tab", action: "click", cue: `Click the "${label}" tab`, ...o });

/** A control explained, not pressed (it opens a form, filters, or simply shows something). */
export const see = (label: string, title: string, body: string, o: Opt = {}): WalkthroughStep =>
  ({ title, body, target: label, kind: "any", action: "observe", ...o });

/** A safe control to press now: a filter, a search box, Print, CSV, opening a panel. Advances when pressed. */
export const tryIt = (label: string, title: string, body: string, o: Opt = {}): WalkthroughStep =>
  ({ title, body, target: label, kind: "any", action: "click", cue: `Click "${label}"`, ...o });

/** Saves, posts, approves, voids, sends or deletes for real - shown in amber, never pressed during training. */
export const careful = (label: string, title: string, body: string, o: Opt = {}): WalkthroughStep =>
  ({ title, body, target: label, kind: "any", action: "observe", caution: true, ...o });

/** "Open any record in the list" - clicking a row opens its panel; the next steps explain the panel's buttons. */
export const openRow = (title: string, body: string, o: Opt = {}): WalkthroughStep =>
  ({ title, body, kind: "row", action: "click", cue: "Click any row in the list to open it", ...o });

/** A field or box on a form. */
export const field = (label: string, title: string, body: string, o: Opt = {}): WalkthroughStep =>
  ({ title, body, target: label, kind: "field" as TargetKind, action: "observe", ...o });

/** Plain explanation - nothing to point at. */
export const note = (title: string, body: string, o: Opt = {}): WalkthroughStep => ({ title, body, ...o });
