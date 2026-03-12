(function() {
  const root = document.getElementById('placeware-chat-root');
  if (!root || !window.PlacewareConfig) return;

  const API_URL = window.PlacewareConfig.apiUrl;
  
  // Create Launcher
  const launcher = document.createElement('div');
  launcher.className = 'pw-launcher';
  launcher.innerHTML = `<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"></path></svg>`;
  
  // Create Window
  const windowEl = document.createElement('div');
  windowEl.className = 'pw-window';
  windowEl.innerHTML = `
    <div class="pw-header">
      <span>PlacewareBot Assistant</span>
      <span class="pw-close">×</span>
    </div>
    <div class="pw-messages" id="pw-messages">
       <div class="pw-msg bot">Hello! How can I help you today?</div>
    </div>
    <div class="pw-input-area">
      <input type="text" class="pw-input" placeholder="Type a message..." id="pw-input" />
      <button class="pw-send" id="pw-send">➤</button>
    </div>
    <div class="pw-disclaimer">Not medical advice. Information only.</div>
  `;

  root.appendChild(windowEl);
  root.appendChild(launcher);

  // State
  let isOpen = false;
  const msgsContainer = document.getElementById('pw-messages');
  const input = document.getElementById('pw-input');
  const sendBtn = document.getElementById('pw-send');
  const closeBtn = windowEl.querySelector('.pw-close');

  // Toggle
  function toggle() {
    isOpen = !isOpen;
    if (isOpen) {
      windowEl.classList.add('open');
      input.focus();
    } else {
      windowEl.classList.remove('open');
    }
  }

  launcher.addEventListener('click', toggle);
  closeBtn.addEventListener('click', toggle);

  // Send message
  async function sendMessage() {
    const text = input.value.trim();
    if (!text) return;

    appendMsg(text, 'user');
    input.value = '';
    
    // Show typing or loading state if desired
    
    try {
      const headers = {
        'Content-Type': 'application/json',
      };
      if (window.PlacewareConfig.siteKey) {
        headers['X-Site-Key'] = window.PlacewareConfig.siteKey;
      }
      const res = await fetch(`${API_URL}/chat`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ question: text, mode: 'customer' })
      });
      
      const data = await res.json();
      if (data.answer) {
        appendMsg(data.answer, 'bot');
      } else if (data.error) {
        appendMsg("Sorry, I had trouble connecting. Please try again.", 'bot');
      }
    } catch (e) {
      appendMsg("Network error. Please enable CORS or check connection.", 'bot');
    }
  }

  function appendMsg(text, sender) {
    const div = document.createElement('div');
    div.className = `pw-msg ${sender}`;
    div.innerText = text;
    msgsContainer.appendChild(div);
    msgsContainer.scrollTop = msgsContainer.scrollHeight;
  }

  sendBtn.addEventListener('click', sendMessage);
  input.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendMessage();
  });

})();
