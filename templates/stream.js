/* ============================================================
   STREAMING: talks to /api/jarvis and hands chunks back to app.js
   ============================================================ */
async function streamJarvisChat(payload, handlers, signal) {
  let res;
  try {
    res = await fetch('/api/jarvis', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal
    });
  } catch (err) {
    if (err && err.name === 'AbortError') throw err;
    handlers.onError('Central command connection failed.');
    return;
  }

  if (!res.ok || !res.body) {
    handlers.onError('Central command servers are currently experiencing high demand. Please try again in a few moments.');
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    let chunkResult;
    try {
      chunkResult = await reader.read();
    } catch (err) {
      if (err && err.name === 'AbortError') throw err;
      break;
    }
    const { value, done } = chunkResult;
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop();

    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith('data:')) continue;
      let evt;
      try { evt = JSON.parse(line.slice(5).trim()); } catch (e) { continue; }

      if (evt.chunk) handlers.onChunk(evt.chunk);
      else if (evt.error) { handlers.onError(evt.error); return; }
      else if (evt.done) { handlers.onDone(); return; }
    }
  }
  handlers.onDone(); // stream ended without an explicit event
}

/* ============================================================
   MARKDOWN RENDERING
   A small hand-written renderer: headings, bold/italic, lists,
   blockquotes, fenced code blocks (with a Copy button), inline
   code, and light styling for $inline$ and $$block$$ math.
   ============================================================ */
function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function inlineFormat(str) {
  let out = str;
  out = out.replace(/`([^`]+)`/g, (m, code) => `<code>${code}</code>`);
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');
  out = out.replace(/\$([^$\n]+)\$/g, '<span style="font-style:italic;">$1</span>');
  return out;
}

function mdToHtml(raw) {
  const codeBlocks = [];
  let text = String(raw || '').replace(/```(\w*)\n?([\s\S]*?)```/g, (m, lang, code) => {
    codeBlocks.push({ lang: lang || 'text', code });
    return `\u0000CODE${codeBlocks.length - 1}\u0000`;
  });

  // Block math ($$...$$) spans multiple lines, so pull it out before escaping/splitting
  const mathBlocks = [];
  text = text.replace(/\$\$([\s\S]+?)\$\$/g, (m, expr) => {
    mathBlocks.push(expr.trim());
    return `\u0000MATH${mathBlocks.length - 1}\u0000`;
  });

  text = escapeHtml(text);

  const lines = text.split('\n');
  let html = '';
  let listType = null;
  let para = [];

  const flushPara = () => { if (para.length) { html += `<p>${inlineFormat(para.join(' '))}</p>`; para = []; } };
  const closeList = () => { if (listType) { html += `</${listType}>`; listType = null; } };

  for (const rawLine of lines) {
    const line = rawLine;
    const codeMatch = line.match(/^\u0000CODE(\d+)\u0000$/);
    const mathMatch = line.match(/^\u0000MATH(\d+)\u0000$/);
    const h = line.match(/^(#{1,3})\s+(.*)/);
    const quote = line.match(/^&gt;\s?(.*)/);
    const ul = line.match(/^[-*]\s+(.*)/);
    const ol = line.match(/^\d+\.\s+(.*)/);

    if (codeMatch) {
      flushPara(); closeList();
      const block = codeBlocks[Number(codeMatch[1])];
      const idx = codeMatch[1];
      html += `<pre><code data-code-idx="${idx}">${escapeHtml(block.code.replace(/\n$/, ''))}</code><button type="button" class="code-copy-btn" data-code-idx="${idx}">Copy</button></pre>`;
    } else if (mathMatch) {
      flushPara(); closeList();
      const expr = mathBlocks[Number(mathMatch[1])];
      html += `<div style="text-align:center;font-style:italic;margin:8px 0;">${escapeHtml(expr)}</div>`;
    } else if (h) {
      flushPara(); closeList();
      const level = h[1].length;
      html += `<h${level}>${inlineFormat(h[2])}</h${level}>`;
    } else if (quote) {
      flushPara(); closeList();
      html += `<blockquote>${inlineFormat(quote[1])}</blockquote>`;
    } else if (ul) {
      flushPara();
      if (listType !== 'ul') { closeList(); html += '<ul>'; listType = 'ul'; }
      html += `<li>${inlineFormat(ul[1])}</li>`;
    } else if (ol) {
      flushPara();
      if (listType !== 'ol') { closeList(); html += '<ol>'; listType = 'ol'; }
      html += `<li>${inlineFormat(ol[1])}</li>`;
    } else if (line.trim() === '') {
      flushPara(); closeList();
    } else {
      para.push(line);
    }
  }
  flushPara(); closeList();

  return { html, codeBlocks };
}

function renderMarkdownInto(el, text) {
  const { html, codeBlocks } = mdToHtml(text);
  el.innerHTML = html || '';
  el.querySelectorAll('.code-copy-btn').forEach(btn => {
    btn.onclick = () => {
      const idx = Number(btn.dataset.codeIdx);
      const code = codeBlocks[idx] ? codeBlocks[idx].code : '';
      if (navigator.clipboard) {
        navigator.clipboard.writeText(code).then(() => {
          btn.textContent = 'Copied!';
          setTimeout(() => { btn.textContent = 'Copy'; }, 1200);
        }).catch(() => {});
      }
    };
  });
}

window.streamJarvisChat = streamJarvisChat;
window.renderMarkdownInto = renderMarkdownInto;
