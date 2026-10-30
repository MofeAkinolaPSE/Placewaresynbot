/**
 * Every page's "Show me how" tour: what the page is for, then each tab and button on it in screen order.
 * One guide per route in App.tsx (checked by walkthroughs.spec.ts). The intro is also the welcome tour's text
 * when it walks every page a role can open.
 */
import type { PageGuide } from "../walkthroughs";
import { BOOKS_GUIDES } from "./guides-books";
import { FRONT_GUIDES } from "./guides-front";
import { STOCK_GUIDES } from "./guides-stock";

export const PAGE_GUIDES: PageGuide[] = [...FRONT_GUIDES, ...BOOKS_GUIDES, ...STOCK_GUIDES];
