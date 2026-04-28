(function () {
  'use strict';

  const root = document.getElementById('placeware-chat-root');
  if (!root) return;

  // PlacewareConfig is injected by WordPress via wp_localize_script.
  // Fall back to localhost for dev environments if the object is missing.
  const _cfg   = window.PlacewareConfig || {};
  const API_URL   = (_cfg.apiUrl  || 'http://localhost:8000').replace(/\/$/, '');
  const SITE_KEY  = _cfg.siteKey  || '';
  const STORAGE_KEY = 'pw_chat_history';
  const MAX_HISTORY = 20; // messages kept in localStorage

  // ── SVG icons ──────────────────────────────────────────────────────────────
  const ICON_CHAT = `<svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/>
  </svg>`;

  const ICON_SEND = `<svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
  </svg>`;

  const ICON_CLOSE = `<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
    <path fill="white" d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
  </svg>`;

  const GREETING = "Hi! I'm Warebot, your Placeware Nigeria assistant.\nHow can I help you today?";

  // ── Build DOM ───────────────────────────────────────────────────────────────
  const launcher = document.createElement('button');
  launcher.className = 'pw-launcher';
  launcher.setAttribute('aria-label', 'Open chat');
  launcher.innerHTML = ICON_CHAT;

  const windowEl = document.createElement('div');
  windowEl.className = 'pw-window';
  windowEl.setAttribute('role', 'dialog');
  windowEl.setAttribute('aria-label', 'Warebot chat');
  windowEl.innerHTML = `
    <div class="pw-header">
      <div class="pw-header-title">
        <div class="pw-header-avatar">🤖</div>
        <div>
          <div>Warebot</div>
          <div class="pw-header-subtitle">Placeware Nigeria · Powered by AI</div>
        </div>
      </div>
      <button class="pw-close" aria-label="Close chat">${ICON_CLOSE}</button>
    </div>
    <div class="pw-messages" id="pw-messages" aria-live="polite" aria-atomic="false"></div>
    <div class="pw-input-area">
      <input
        type="text"
        class="pw-input"
        id="pw-input"
        placeholder="Ask a question… (Enter to send)"
        autocomplete="off"
        maxlength="500"
      />
      <button class="pw-send" id="pw-send" aria-label="Send message">${ICON_SEND}</button>
    </div>
    <div class="pw-disclaimer">
      For informational purposes only. Not medical or professional advice.
    </div>
  `;

  root.appendChild(windowEl);
  root.appendChild(launcher);

  // ── Refs ────────────────────────────────────────────────────────────────────
  const msgsEl  = document.getElementById('pw-messages');
  const inputEl = document.getElementById('pw-input');
  const sendBtn = document.getElementById('pw-send');
  const closeBtn = windowEl.querySelector('.pw-close');

  let isOpen   = false;
  let isBusy   = false;
  let typingEl = null;

  // ── Session persistence ────────────────────────────────────────────────────
  function loadHistory() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
    } catch (_) { return []; }
  }

  function saveHistory(msgs) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(msgs.slice(-MAX_HISTORY)));
    } catch (_) {}
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  function appendMsg(text, sender, persist) {
    const div = document.createElement('div');
    div.className = `pw-msg ${sender}`;
    // Use textContent to prevent XSS — never inject raw HTML from server
    div.textContent = text;
    msgsEl.appendChild(div);
    msgsEl.scrollTop = msgsEl.scrollHeight;

    if (persist !== false) {
      const history = loadHistory();
      history.push({ sender, text });
      saveHistory(history);
    }
  }

  function showTyping() {
    if (typingEl) return;
    typingEl = document.createElement('div');
    typingEl.className = 'pw-typing';
    typingEl.innerHTML = '<span></span><span></span><span></span>';
    msgsEl.appendChild(typingEl);
    msgsEl.scrollTop = msgsEl.scrollHeight;
  }

  function hideTyping() {
    if (typingEl) {
      typingEl.remove();
      typingEl = null;
    }
  }

  // ── Init from stored history ───────────────────────────────────────────────
  function initMessages() {
    msgsEl.innerHTML = '';
    const history = loadHistory();
    if (history.length === 0) {
      appendMsg(GREETING, 'bot', false);
    } else {
      history.forEach(({ sender, text }) => appendMsg(text, sender, false));
    }
  }

  // ── Toggle open/close ──────────────────────────────────────────────────────
  function openWidget() {
    isOpen = true;
    windowEl.classList.add('open');
    launcher.setAttribute('aria-expanded', 'true');
    inputEl.focus();
  }

  function closeWidget() {
    isOpen = false;
    windowEl.classList.remove('open');
    launcher.setAttribute('aria-expanded', 'false');
  }

  launcher.addEventListener('click', () => {
    if (!isOpen) {
      initMessages();
      openWidget();
    } else {
      closeWidget();
    }
  });

  closeBtn.addEventListener('click', closeWidget);

  // Close on Escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && isOpen) closeWidget();
  });

  // ── Send message ────────────────────────────────────────────────────────────
  async function sendMessage() {
    const text = inputEl.value.trim();
    if (!text || isBusy) return;

    inputEl.value = '';
    appendMsg(text, 'user');

    isBusy = true;
    sendBtn.disabled = true;
    showTyping();

    try {
      const headers = { 'Content-Type': 'application/json' };
      // Always send X-Site-Key — backend rejects unauthenticated widget requests
      // when WIDGET_SITE_KEYS is configured in the backend .env
      if (SITE_KEY) headers['X-Site-Key'] = SITE_KEY;

      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 30000); // 30 s timeout

      const res = await fetch(`${API_URL}/chat`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ question: text, mode: 'customer' }),
        signal: controller.signal,
      });
      clearTimeout(timeout);

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const data = await res.json();
      hideTyping();

      const answer = (data && typeof data.answer === 'string' && data.answer.trim())
        ? data.answer.trim()
        : null;

      if (answer) {
        appendMsg(answer, 'bot');
      } else {
        appendMsg("I didn't receive a valid response. Please try again.", 'bot');
      }
    } catch (err) {
      hideTyping();
      if (err.name === 'AbortError') {
        appendMsg('The request timed out. Please check your connection and try again.', 'bot');
      } else {
        appendMsg("I'm having trouble connecting right now. Please try again shortly.", 'bot');
      }
    } finally {
      isBusy = false;
      sendBtn.disabled = false;
      inputEl.focus();
    }
  }

  sendBtn.addEventListener('click', sendMessage);
  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Init on first load (no window open yet; just primes history load)
})();

