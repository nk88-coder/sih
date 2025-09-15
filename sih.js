const messagesEl = document.getElementById('messages');
const inputEl = document.getElementById('prompt');
const sendBtn = document.getElementById('send');
const pickBtn = document.getElementById('pickFile');
const askBtn = document.getElementById('askBtn');
const tgBtn = document.getElementById('tgBtn');
const fileInput = document.getElementById('fileInput');
let lastPickedFile = null; // keep in frontend only

function addMessage(role, content, thinking=false) {
  const wrap = document.createElement('div');
  wrap.className = `msg ${role} ${thinking ? 'thinking' : ''}`;
  const roleEl = document.createElement('div');
  roleEl.className = 'role';
  roleEl.textContent = role;
  const contentEl = document.createElement('div');
  contentEl.className = 'content';
  contentEl.textContent = content;
  wrap.appendChild(roleEl);
  wrap.appendChild(contentEl);
  messagesEl.appendChild(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return { wrap, contentEl };
}

function typingIndicator() {
  const wrap = document.createElement('span');
  wrap.className = 'typing';
  for (let i = 0; i < 3; i++) {
    const d = document.createElement('span');
    d.className = 'dot';
    wrap.appendChild(d);
  }
  return wrap;
}

async function sendPrompt() {
  const prompt = inputEl.value.trim();
  if (!prompt) return;
  inputEl.value = '';
  inputEl.focus();

  addMessage('user', prompt);
  const thinking = addMessage('assistant', '');
  thinking.contentEl.appendChild(typingIndicator());
  sendBtn.disabled = true;

  try {
    const res = await fetch('/api/sih', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt })
    });
    const data = await res.json();
    thinking.wrap.remove();
    if (!res.ok || data.error) {
      addMessage('assistant', `Error: ${data.error || res.status}`);
    } else {
      addMessage('assistant', data.reply || '[empty]');
    }
  } catch (e) {
    thinking.wrap.remove();
    addMessage('assistant', `Network error: ${e}`);
  } finally {
    sendBtn.disabled = false;
  }
}

sendBtn.addEventListener('click', sendPrompt);
inputEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendPrompt();
  }
});

// File picker behavior
if (pickBtn && fileInput) {
  pickBtn.addEventListener('click', () => {
    try {
      fileInput.value = '';
      fileInput.click();
    } catch (e) {
      addMessage('assistant', `File dialog error: ${e}`);
    }
  });

  fileInput.addEventListener('change', () => {
    try {
      const f = fileInput.files && fileInput.files[0];
      if (!f) {
        addMessage('assistant', 'No file selected.');
        return;
      }
      const info = `Picked file: name=${f.name}, size=${f.size} bytes, type=${f.type || 'n/a'}`;
      console.log('[SIH:file]', f);
      addMessage('assistant', info);

      if (!f.name.toLowerCase().endsWith('.pdf')) {
        addMessage('assistant', 'Only .pdf files are allowed.');
        return;
      }
      // keep in memory until Ask is clicked
      lastPickedFile = f;
    } catch (e) {
      addMessage('assistant', `File read error: ${e}`);
    }
  });
}

// Ask over PDF using RAG
if (askBtn) {
  askBtn.addEventListener('click', async () => {
    try {
      if (!lastPickedFile) {
        addMessage('assistant', 'Pick a PDF first.');
        return;
      }
      if (!lastPickedFile.name.toLowerCase().endsWith('.pdf')) {
        addMessage('assistant', 'Only .pdf files are allowed.');
        return;
      }
      const query = inputEl.value.trim();
      if (!query) {
        addMessage('assistant', 'Type a question in the input box.');
        return;
      }
      const thinking = addMessage('assistant', '');
      thinking.contentEl.appendChild(typingIndicator());

      const form = new FormData();
      form.append('file', lastPickedFile);
      form.append('query', query);

      const res = await fetch('/api/sih-ask', { method: 'POST', body: form });
      const data = await res.json().catch(() => ({}));
      thinking.wrap.remove();
      if (!res.ok) {
        addMessage('assistant', `Ask error: ${data.error || res.status}`);
        return;
      }
      const answer = data.answer || '[No answer]';
      addMessage('assistant', answer);
    } catch (e) {
      addMessage('assistant', `Network error: ${e}`);
    }
  });
}

// Telegram button opens bot link
if (tgBtn) {
  tgBtn.addEventListener('click', () => {
    const tgLink = 'https://t.me/Studentshelperbot_bot';
    addMessage('assistant', `Here is your Telegram bot link:\n${tgLink}`);
  });
}


