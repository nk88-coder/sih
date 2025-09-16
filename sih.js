const messagesEl = document.getElementById('messages');
const inputEl = document.getElementById('prompt');
const sendBtn = document.getElementById('send');
const pickBtn = document.getElementById('pickFile');
const askBtn = document.getElementById('askBtn');
const tgBtn = document.getElementById('tgBtn');
const ocrBtn = document.getElementById('ocrBtn');
let ocrPending = false; // if true, run OCR right after file pick
const fileInput = document.getElementById('fileInput');
let lastPickedFile = null; // keep in frontend only
const voiceToggle = document.getElementById('voiceToggle');

function addMessage(role, content, thinking=false) {
  const wrap = document.createElement('div');
  wrap.className = `msg ${role} ${thinking ? 'thinking' : ''}`;
  // Tailwind flair per role
  try {
    wrap.classList.add('transition', 'duration-300', 'ease-out', 'transform');
    wrap.classList.add('shadow-2xl', 'backdrop-blur', 'border', 'border-white/15');
    wrap.classList.add('rounded-2xl', 'p-4');
    if (role === 'user') {
      wrap.classList.add('bg-black/70', 'text-white');
    } else {
      wrap.classList.add('bg-white', 'text-black');
    }
  } catch (e) {}
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
      const text = data.reply || '[empty]';
      addMessage('assistant', text);
      if (voiceToggle && voiceToggle.checked && text && text.length > 1) {
        try {
          const tts = await fetch('/api/sih-tts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text })
          });
          if (tts.ok) {
            const blob = await tts.blob();
            const url = URL.createObjectURL(blob);
            const audio = new Audio(url);
            audio.play().catch(() => {});
          }
        } catch (e) {}
      }
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
        // Not a PDF; allow images for OCR flow
      }
      // keep in memory until Ask is clicked
      lastPickedFile = f;

      // If OCR was requested, and the file is an image, trigger OCR now
      if (ocrPending) {
        ocrPending = false;
        const name = (lastPickedFile?.name || '').toLowerCase();
        if (name.endsWith('.png') || name.endsWith('.jpg') || name.endsWith('.jpeg')) {
          // simulate click of OCR flow
          if (ocrBtn) {
            try { ocrBtn.click(); } catch (e) {}
          }
        } else {
          addMessage('assistant', 'Please select an image (.png/.jpg) for OCR.');
        }
      }
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
      if (voiceToggle && voiceToggle.checked && answer && answer.length > 1) {
        try {
          const tts = await fetch('/api/sih-tts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: answer })
          });
          if (tts.ok) {
            const blob = await tts.blob();
            const url = URL.createObjectURL(blob);
            const audio = new Audio(url);
            audio.play().catch(() => {});
          }
        } catch (e) {}
      }
    } catch (e) {
      addMessage('assistant', `Network error: ${e}`);
    }
  });
}

// OCR selected image and print text
if (ocrBtn) {
  ocrBtn.addEventListener('click', async () => {
    try {
      if (!lastPickedFile) {
        // Prompt file manager for selecting an image, then run OCR after selection
        ocrPending = true;
        try { fileInput.click(); } catch (e) {}
        return;
      }
      const name = lastPickedFile.name.toLowerCase();
      if (!(name.endsWith('.png') || name.endsWith('.jpg') || name.endsWith('.jpeg'))) {
        // Ask to pick an image now
        ocrPending = true;
        try { fileInput.click(); } catch (e) {}
        return;
      }
      const query = inputEl.value.trim();
      if (!query) {
        addMessage('assistant', 'Type your question in the box, then click 🖼️ again.');
        return;
      }
      const thinking = addMessage('assistant', '');
      thinking.contentEl.appendChild(typingIndicator());

      const form = new FormData();
      form.append('file', lastPickedFile);
      form.append('query', query);
      const res = await fetch('/api/sih-ask-ocr', { method: 'POST', body: form });
      const data = await res.json().catch(() => ({}));
      thinking.wrap.remove();
      if (!res.ok) {
        addMessage('assistant', `OCR Ask error: ${data.error || res.status}`);
        return;
      }
      const answer = data.answer || '[No answer]';
      addMessage('assistant', answer);
      if (voiceToggle && voiceToggle.checked && answer && answer.length > 1) {
        try {
          const tts = await fetch('/api/sih-tts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: answer })
          });
          if (tts.ok) {
            const blob = await tts.blob();
            const url = URL.createObjectURL(blob);
            const audio = new Audio(url);
            audio.play().catch(() => {});
          }
        } catch (e) {}
      }
    } catch (e) {
      addMessage('assistant', `OCR network error: ${e}`);
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


