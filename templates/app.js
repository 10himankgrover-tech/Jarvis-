/* ============================================================
   STATE
   ============================================================ */
let currentSessionId = null;
let voiceEnabled = true;
let recognition = null;
let currentMode = 'chat';
let thinkingEnabled = false;
let attachedPhoto = null;       // { dataUrl, name } or null
let currentAbortController = null;
let isStreaming = false;

const STARTERS = {
  chat: ["What can you help me with?", "Give me 3 ideas for a weekend project", "Explain a topic simply"],
  study: ["Explain photosynthesis simply", "Help me revise for a test", "Turn this into flashcards"],
  code: ["Debug this error for me", "Explain this code line by line", "Write a function that..."],
  writer: ["Help me write an email", "Improve this paragraph", "Draft a short story about..."]
};

function uid() { return 'm_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8); }

/* ============================================================
   SPEECH RECOGNITION (mic input)
   ============================================================ */
if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = 'en-US';
  recognition.onstart = () => { document.getElementById('micBtn').classList.add('listening'); };
  recognition.onresult = (event) => {
    document.getElementById('userInput').value = event.results[0][0].transcript;
    sendQuery();
  };
  recognition.onerror = stopMicUI;
  recognition.onend = stopMicUI;
}

function startListening() {
  if (!recognition) { alert("Speech recognition is not supported on this browser."); return; }
  try { recognition.start(); } catch (e) { recognition.stop(); }
}
function stopMicUI() { document.getElementById('micBtn').classList.remove('listening'); }

/* ============================================================
   VOICE OUTPUT (text to speech)
   ============================================================ */
function cleanTextForSpeech(text) {
  return text
    .replace(/Jarvis/gi, "Jarvis")
    .replace(/```[\s\S]*?```/g, " code block omitted ")
    .replace(/[*_#`~]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function speak(text) {
  if (!voiceEnabled || !('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(cleanTextForSpeech(text));
  const voices = window.speechSynthesis.getVoices();
  const preferred = voices.find(v => v.lang.startsWith('en') && (
    v.name.includes('David') || v.name.includes('George') || v.name.includes('Guy') ||
    v.name.includes('Mark') || v.name.includes('Alex') || v.name.includes('Daniel') ||
    v.name.includes('Male')
  )) || voices.find(v => v.lang.startsWith('en')) || voices[0];
  if (preferred) utterance.voice = preferred;
  utterance.pitch = 0.9;
  utterance.rate = 1;
  window.speechSynthesis.speak(utterance);
}

function stopSpeaking() {
  if ('speechSynthesis' in window) window.speechSynthesis.cancel();
}

function toggleVoice() {
  voiceEnabled = !voiceEnabled;
  const btn = document.getElementById('voiceToggleBtn');
  if (voiceEnabled) { btn.textContent = '🔊 Voice ON'; btn.style.opacity = '1'; }
  else { btn.textContent = '🔇 Muted'; btn.style.opacity = '0.6'; stopSpeaking(); }
}

if (typeof speechSynthesis !== 'undefined') {
  window.speechSynthesis.onvoiceschanged = () => window.speechSynthesis.getVoices();
}

/* ============================================================
   THEME, MODE, THINK-HARDER
   ============================================================ */
function toggleMobileHistory() { document.getElementById('historyPanel').classList.toggle('active'); }

function toggleTheme() {
  const body = document.body;
  const btn = document.getElementById('themeToggleBtn');
  if (body.getAttribute('data-theme') === 'light') { body.removeAttribute('data-theme'); btn.textContent = '☀️ Light'; }
  else { body.setAttribute('data-theme', 'light'); btn.textContent = '🌙 Dark'; }
}

function toggleThinking() {
  thinkingEnabled = !thinkingEnabled;
  document.getElementById('thinkToggleBtn').classList.toggle('active-toggle', thinkingEnabled);
}

function setMode(value) {
  currentMode = value;
  localStorage.setItem('jarvis_mode', value);
  const labels = { chat: 'AI Assistant', study: 'Study Tutor', code: 'Code Helper', writer: 'Writing Assistant' };
  document.getElementById('modeSubtitle').textContent = labels[value] || 'AI Assistant';
  renderStarterRow();
}

/* ============================================================
   ONLINE STATUS DOT
   ============================================================ */
function setStatus(state) {
  const dot = document.getElementById('statusDot');
  dot.classList.remove('online', 'offline', 'checking');
  dot.classList.add(state);
  dot.title = state === 'online' ? 'Jarvis is online' : state === 'offline' ? 'Jarvis may be unreachable' : 'Checking connection...';
}

function checkStatus() {
  setStatus('checking');
  fetch('/', { method: 'HEAD', cache: 'no-store' })
    .then(res => setStatus(res.ok ? 'online' : 'offline'))
    .catch(() => setStatus('offline'));
}

/* ============================================================
   SESSIONS (saved in this browser only)
   ============================================================ */
function getSessions() { return JSON.parse(localStorage.getItem('jarvis_sessions') || '[]'); }
function saveSessions(sessions) { localStorage.setItem('jarvis_sessions', JSON.stringify(sessions)); renderHistoryList(); }

function startNewChat() {
  currentSessionId = uid();
  let sessions = getSessions();
  sessions.unshift({
    id: currentSessionId,
    title: 'New Conversation',
    messages: [{ id: uid(), sender: 'bot', text: 'Hi, I\'m Jarvis. How can I help today?', time: Date.now() }]
  });
  saveSessions(sessions);
  loadSession(currentSessionId);
  if (window.innerWidth <= 768) document.getElementById('historyPanel').classList.remove('active');
}

function loadSession(id) {
  currentSessionId = id;
  const session = getSessions().find(s => s.id === id);
  const chatBox = document.getElementById('chatBox');
  chatBox.innerHTML = '';
  if (session) session.messages.forEach(msg => appendMessageUI(msg));
  renderHistoryList();
  renderStarterRow();
  chatBox.scrollTop = chatBox.scrollHeight;
}

function renderHistoryList() {
  const list = document.getElementById('historyList');
  if (!list) return;
  const sessions = getSessions();
  list.innerHTML = '';
  sessions.forEach(s => {
    const row = document.createElement('div');
    row.className = `history-item ${s.id === currentSessionId ? 'active' : ''}`;

    const title = document.createElement('span');
    title.className = 'history-item-title';
    title.textContent = s.title;
    title.onclick = () => { loadSession(s.id); if (window.innerWidth <= 768) document.getElementById('historyPanel').classList.remove('active'); };

    const renameBtn = document.createElement('button');
    renameBtn.className = 'history-item-btn'; renameBtn.textContent = '✏️'; renameBtn.title = 'Rename';
    renameBtn.onclick = (e) => { e.stopPropagation(); renameSession(s.id); };

    const delBtn = document.createElement('button');
    delBtn.className = 'history-item-btn'; delBtn.textContent = '🗑️'; delBtn.title = 'Delete';
    delBtn.onclick = (e) => { e.stopPropagation(); deleteSession(s.id); };

    row.append(title, renameBtn, delBtn);
    list.appendChild(row);
  });
}

function renameSession(id) {
  const sessions = getSessions();
  const s = sessions.find(x => x.id === id);
  if (!s) return;
  const next = prompt('Rename this chat:', s.title);
  if (next && next.trim()) { s.title = next.trim().slice(0, 60); saveSessions(sessions); }
}

function deleteSession(id) {
  if (!confirm('Delete this chat? This cannot be undone.')) return;
  let sessions = getSessions().filter(s => s.id !== id);
  saveSessions(sessions);
  if (id === currentSessionId) {
    if (sessions.length) loadSession(sessions[0].id); else startNewChat();
  }
}

function clearAllSessions() {
  if (!confirm('Clear ALL chats? This cannot be undone.')) return;
  localStorage.removeItem('jarvis_sessions');
  startNewChat();
}

function saveMessageToSession(msg) {
  const sessions = getSessions();
  const session = sessions.find(s => s.id === currentSessionId);
  if (!session) return;
  if (session.title === 'New Conversation' && msg.sender === 'user') {
    session.title = msg.text ? (msg.text.length > 28 ? msg.text.slice(0, 28) + '...' : msg.text) : '📷 Photo';
  }
  session.messages.push(msg);
  saveSessions(sessions);
}

function replaceLastBotMessage(session, msg) {
  for (let i = session.messages.length - 1; i >= 0; i--) {
    if (session.messages[i].sender === 'bot') { session.messages[i] = msg; break; }
  }
  saveSessions(getSessions().map(s => s.id === session.id ? session : s));
}

/* ============================================================
   STARTER QUESTIONS
   ============================================================ */
function renderStarterRow() {
  const row = document.getElementById('starterRow');
  const session = getSessions().find(s => s.id === currentSessionId);
  const onlyGreeting = session && session.messages.length === 1 && session.messages[0].sender === 'bot';
  row.innerHTML = '';
  if (!onlyGreeting) return;
  (STARTERS[currentMode] || STARTERS.chat).forEach(text => {
    const chip = document.createElement('button');
    chip.className = 'starter-chip';
    chip.textContent = text;
    chip.onclick = () => { document.getElementById('userInput').value = text; sendQuery(); };
    row.appendChild(chip);
  });
}

/* ============================================================
   CAMERA / PHOTO ATTACHMENT
   ============================================================ */
function onPhotoChosen(file) {
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    attachedPhoto = { dataUrl: reader.result, name: file.name || 'photo.jpg' };
    document.getElementById('photoPreviewImg').src = attachedPhoto.dataUrl;
    document.getElementById('photoPreviewName').textContent = attachedPhoto.name;
    document.getElementById('photoPreviewRow').style.display = 'flex';
  };
  reader.readAsDataURL(file);
}

function clearAttachedPhoto() {
  attachedPhoto = null;
  document.getElementById('photoInput').value = '';
  document.getElementById('photoPreviewRow').style.display = 'none';
}

/* ============================================================
   MESSAGE RENDERING
   ============================================================ */
function formatTime(ts) {
  try { return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
  catch (e) { return ''; }
}

function appendMessageUI(msg) {
  const chatBox = document.getElementById('chatBox');
  const wrapper = document.createElement('div');
  wrapper.className = `message ${msg.sender === 'user' ? 'user-msg' : 'bot-msg'}`;
  wrapper.dataset.msgId = msg.id || uid();

  if (msg.photo) {
    const img = document.createElement('img');
    img.className = 'msg-photo'; img.src = msg.photo; img.alt = 'Attached photo';
    wrapper.appendChild(img);
  }

  const body = document.createElement('div');
  if (msg.sender === 'bot') {
    body.className = 'msg-md';
    if (window.renderMarkdownInto) window.renderMarkdownInto(body, msg.text || '');
    else body.textContent = msg.text || '';
  } else {
    body.className = 'message-text';
    body.textContent = msg.text || '';
  }
  wrapper.appendChild(body);

  const meta = document.createElement('div');
  meta.className = 'msg-meta';
  const time = document.createElement('span');
  time.textContent = formatTime(msg.time || Date.now());
  meta.appendChild(time);

  const actions = document.createElement('div');
  actions.className = 'msg-actions';

  if (msg.sender === 'bot' && msg.text) {
    const copyBtn = document.createElement('button');
    copyBtn.className = 'msg-action-btn'; copyBtn.textContent = '📋 Copy';
    copyBtn.onclick = () => navigator.clipboard && navigator.clipboard.writeText(msg.text).catch(() => {});
    actions.appendChild(copyBtn);

    if (!msg.isError) {
      const regenBtn = document.createElement('button');
      regenBtn.className = 'msg-action-btn'; regenBtn.textContent = '↻ Regenerate';
      regenBtn.onclick = () => regenerateMessage(wrapper.dataset.msgId);
      actions.appendChild(regenBtn);
    }
  }
  if (msg.sender === 'user') {
    const editBtn = document.createElement('button');
    editBtn.className = 'msg-action-btn'; editBtn.textContent = '✏️ Edit';
    editBtn.onclick = () => { document.getElementById('userInput').value = msg.text || ''; document.getElementById('userInput').focus(); };
    actions.appendChild(editBtn);
  }
  meta.appendChild(actions);
  wrapper.appendChild(meta);

  if (msg.canPdf) {
    const pdfBtn = document.createElement('button');
    pdfBtn.className = 'pdf-btn'; pdfBtn.textContent = '📄 Make colorful PDF';
    pdfBtn.onclick = () => makePdf(pdfBtn, msg.topic || '', msg.text || '');
    wrapper.appendChild(pdfBtn);
  }

  chatBox.appendChild(wrapper);
  chatBox.scrollTop = chatBox.scrollHeight;
  return wrapper;
}

/* ============================================================
   SEND / STREAM / STOP
   ============================================================ */
function buildHistoryPayload(session) {
  if (!session) return [];
  return session.messages
    .filter(m => m.text)
    .map(m => ({ role: m.sender === 'user' ? 'user' : 'bot', text: m.text }));
}

function setStreamingUI(active) {
  isStreaming = active;
  document.getElementById('sendBtn').style.display = active ? 'none' : '';
  document.getElementById('stopBtn').style.display = active ? '' : 'none';
}

async function sendQuery() {
  if (isStreaming) return;
  const inputField = document.getElementById('userInput');
  const text = inputField.value.trim();
  if (!text && !attachedPhoto) return;

  const session = getSessions().find(s => s.id === currentSessionId);
  const historyPayload = buildHistoryPayload(session);

  const userMsg = { id: uid(), sender: 'user', text, time: Date.now(), photo: attachedPhoto ? attachedPhoto.dataUrl : null };
  appendMessageUI(userMsg);
  saveMessageToSession(userMsg);

  const photoToSend = attachedPhoto ? attachedPhoto.dataUrl : null;
  inputField.value = '';
  clearAttachedPhoto();
  document.getElementById('starterRow').innerHTML = '';

  await streamReply({ prompt: text, image: photoToSend, history: historyPayload, topic: text });
}

async function regenerateMessage(botMsgId) {
  if (isStreaming) return;
  const session = getSessions().find(s => s.id === currentSessionId);
  if (!session) return;
  const idx = session.messages.findIndex(m => m.id === botMsgId);
  if (idx === -1) return;
  let userIdx = idx - 1;
  while (userIdx >= 0 && session.messages[userIdx].sender !== 'user') userIdx--;
  if (userIdx < 0) return;
  const userMsg = session.messages[userIdx];
  const historyPayload = buildHistoryPayload({ messages: session.messages.slice(0, userIdx) });

  session.messages = session.messages.slice(0, idx);
  saveSessions(getSessions().map(s => s.id === session.id ? session : s));
  loadSession(session.id);

  await streamReply({ prompt: userMsg.text, image: userMsg.photo, history: historyPayload, topic: userMsg.text });
}

async function streamReply(payload) {
  currentAbortController = new AbortController();
  setStreamingUI(true);

  const botWrapper = appendMessageUI({ id: uid(), sender: 'bot', text: '', time: Date.now() });
  const bodyEl = botWrapper.querySelector('.msg-md');
  bodyEl.innerHTML = '<div class="typing-dots"><span></span><span></span><span></span></div>';

  let fullText = '';
  let firstChunk = true;

  const clientTime = new Date().toString();
  const clientTz = Intl.DateTimeFormat().resolvedOptions().timeZone || '';

  try {
    await window.streamJarvisChat(
      { prompt: payload.prompt, image: payload.image, history: payload.history, mode: currentMode, thinking: thinkingEnabled, client_time: clientTime, client_timezone: clientTz },
      {
        onChunk: (piece) => {
          if (firstChunk) { bodyEl.innerHTML = ''; firstChunk = false; }
          fullText += piece;
          window.renderMarkdownInto(bodyEl, fullText);
          document.getElementById('chatBox').scrollTop = document.getElementById('chatBox').scrollHeight;
        },
        onError: (message) => {
          if (firstChunk) bodyEl.innerHTML = '';
          bodyEl.textContent = message;
          const finalMsg = { id: botWrapper.dataset.msgId, sender: 'bot', text: message, time: Date.now(), isError: true };
          saveMessageToSession(finalMsg);
        },
        onDone: () => {
          const canPdf = fullText.trim().length > 60;
          const finalMsg = { id: botWrapper.dataset.msgId, sender: 'bot', text: fullText, time: Date.now(), canPdf, topic: payload.topic };
          saveMessageToSession(finalMsg);
          if (canPdf) {
            const pdfBtn = document.createElement('button');
            pdfBtn.className = 'pdf-btn'; pdfBtn.textContent = '📄 Make colorful PDF';
            pdfBtn.onclick = () => makePdf(pdfBtn, finalMsg.topic || '', finalMsg.text);
            botWrapper.appendChild(pdfBtn);
          }
          speak(fullText);
        }
      },
      currentAbortController.signal
    );
  } catch (err) {
    if (err && err.name !== 'AbortError') {
      bodyEl.textContent = 'Connection failed. Please try again.';
    } else if (fullText) {
      const finalMsg = { id: botWrapper.dataset.msgId, sender: 'bot', text: fullText + '\n\n_(stopped)_', time: Date.now(), canPdf: fullText.length > 60, topic: payload.topic };
      saveMessageToSession(finalMsg);
    }
  } finally {
    setStreamingUI(false);
    currentAbortController = null;
  }
}

function stopStreaming() {
  if (currentAbortController) currentAbortController.abort();
}

/* ============================================================
   INIT
   ============================================================ */
window.onload = function () {
  const savedMode = localStorage.getItem('jarvis_mode');
  if (savedMode) { currentMode = savedMode; document.getElementById('modeSelect').value = savedMode; setMode(savedMode); }
  if (window.getPdfThemeKey) document.getElementById('pdfThemeSelect').value = window.getPdfThemeKey();

  checkStatus();
  setInterval(checkStatus, 60000);

  const sessions = getSessions();
  if (sessions.length === 0) startNewChat(); else loadSession(sessions[0].id);

  window.__jarvisReady = true;
};
