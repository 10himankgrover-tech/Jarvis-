/* ============================================================
   COLORFUL PDF NOTES
   1. Button calls /api/notes  -> Gemini returns structured JSON
   2. buildNotesHtml() fills a colorful template with that JSON
   3. html2pdf turns the template into a downloadable A4 PDF
   ============================================================ */

const PDF_THEMES = {
  ocean:  ['#0369A1', '#0F766E', '#B45309', '#6D28D9'],
  sunset: ['#D62839', '#C2570C', '#9D174D', '#0F766E'],
  forest: ['#2D6A4F', '#0F766E', '#A16207', '#6B4C9A'],
  grape:  ['#6D28D9', '#BE185D', '#0369A1', '#15803D']
};

function getPdfThemeKey() {
  const saved = localStorage.getItem('jarvis_pdf_theme');
  return PDF_THEMES[saved] ? saved : 'ocean';
}

function setPdfTheme(key) {
  if (PDF_THEMES[key]) localStorage.setItem('jarvis_pdf_theme', key);
}

function pdfEsc(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function hexToRgba(hex, alpha) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

function slugify(title) {
  const slug = String(title || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 50);
  return slug || 'jarvis-notes';
}

function buildNotesHtml(n, colors) {
  const C = colors;
  const tint = (i, a = 0.09) => hexToRgba(C[i % C.length], a);
  const icons = ['📘', '📗', '📙', '📕', '📓', '📒'];
  const serif = "Georgia, 'Times New Roman', serif";
  const mono = "Consolas, 'Courier New', monospace";
  const today = new Date().toLocaleDateString(undefined, { year: 'numeric', month: 'long', day: 'numeric' });

  const bullets = (list, color) => (list || []).map(p => `
    <div style="position:relative;padding-left:16px;margin:4px 0;">
      <span style="position:absolute;left:0;top:7px;width:7px;height:7px;border-radius:50%;background:${color};"></span>
      ${pdfEsc(p)}
    </div>`).join('');

  const blockTitle = (icon, text, color) => `
    <div style="font-family:${serif};font-size:17px;font-weight:bold;color:${color};border-bottom:2.5px solid ${color};padding-bottom:4px;margin-bottom:8px;">
      ${icon} ${pdfEsc(text)}
    </div>`;

  const brandGradient = 'linear-gradient(135deg, #00c2f0 0%, #7c5cff 55%, #ff2fb0 120%)';
  const cover = `
    <div class="keep" style="background:${brandGradient};color:#ffffff;border-radius:18px;padding:24px 26px;margin-bottom:18px;box-shadow:0 8px 24px rgba(124,92,255,0.25);">
      <div style="font-family:${serif};font-size:29px;font-weight:bold;line-height:1.2;">${pdfEsc(n.title)}</div>
      ${n.subtitle ? `<div style="font-size:14px;margin-top:7px;opacity:0.95;">${pdfEsc(n.subtitle)}</div>` : ''}
      <div style="font-size:12px;margin-top:14px;opacity:0.85;">Notes by Jarvis &nbsp;•&nbsp; ${pdfEsc(today)}</div>
    </div>`;

  const overview = n.overview ? `
    <div class="keep" style="border-left:6px solid ${C[0]};background:${tint(0, 0.1)};padding:10px 14px;border-radius:0 14px 14px 0;margin-bottom:16px;">
      <b style="color:${C[0]};">In short</b>
      <div style="margin-top:3px;">${pdfEsc(n.overview)}</div>
    </div>` : '';

  const sections = (n.sections || []).map((s, i) => {
    const color = C[i % C.length];
    return `
    <div class="keep" style="margin-bottom:16px;">
      <div style="background:${color};color:#ffffff;padding:9px 14px;border-radius:14px 14px 0 0;font-family:${serif};font-size:17px;font-weight:bold;">
        ${icons[i % icons.length]} ${pdfEsc(s.heading)}
      </div>
      <div style="border:1.5px solid ${color};border-top:none;border-radius:0 0 14px 14px;padding:12px 14px;background:${tint(i)};">
        ${s.explanation ? `<div style="margin-bottom:6px;">${pdfEsc(s.explanation)}</div>` : ''}
        ${bullets(s.points, color)}
        ${s.formula ? `
          <div style="margin-top:10px;padding:10px;text-align:center;background:#ffffff;border:1.5px solid ${color};border-radius:8px;">
            <div style="font-size:12px;font-weight:bold;color:${color};margin-bottom:4px;">Formula</div>
            <div style="font-family:${mono};font-size:15px;font-weight:bold;">${pdfEsc(s.formula)}</div>
          </div>` : ''}
        ${s.example ? `
          <div style="margin-top:10px;padding:10px 12px;background:#ffffff;border:1.5px dashed ${color};border-radius:8px;">
            <div style="font-size:12px;font-weight:bold;color:${color};margin-bottom:3px;">💡 Example</div>
            ${pdfEsc(s.example)}
          </div>` : ''}
      </div>
    </div>`;
  }).join('');

  const terms = (n.key_terms || []).length ? `
    <div class="keep" style="margin-bottom:16px;">
      ${blockTitle('🔑', 'Key terms', C[1])}
      ${n.key_terms.map((t, i) => `
        <div style="padding:5px 0;border-bottom:1px dotted #cbd5e1;">
          <b style="color:${C[i % C.length]};">${pdfEsc(t.term)}:</b> ${pdfEsc(t.meaning)}
        </div>`).join('')}
    </div>` : '';

  const remember = (n.remember || []).length ? `
    <div class="keep" style="background:${C[3]};color:#ffffff;border-radius:16px;padding:15px 17px;margin-bottom:16px;">
      <div style="font-family:${serif};font-size:17px;font-weight:bold;margin-bottom:6px;">⭐ Remember this</div>
      ${n.remember.map(r => `
        <div style="position:relative;padding-left:16px;margin:4px 0;">
          <span style="position:absolute;left:0;top:7px;width:7px;height:7px;border-radius:50%;background:#ffffff;"></span>
          ${pdfEsc(r)}
        </div>`).join('')}
    </div>` : '';

  const quiz = (n.quiz || []).length ? `
    <div class="keep" style="margin-bottom:12px;">
      ${blockTitle('🧠', 'Test yourself', C[2])}
      ${n.quiz.map((q, i) => `
        <div style="padding:6px 0;border-bottom:1px dotted #cbd5e1;">
          <div><b>Q${i + 1}.</b> ${pdfEsc(q.question)}</div>
          <div style="color:${C[2]};margin-top:2px;"><b>Answer:</b> ${pdfEsc(q.answer)}</div>
        </div>`).join('')}
    </div>` : '';

  return `
    <div style="font-family:system-ui,-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;font-size:13.5px;line-height:1.55;color:#1f2937;">
      ${cover}${overview}${sections}${terms}${remember}${quiz}
      <div style="text-align:center;font-size:11px;color:#94a3b8;margin-top:8px;">Made with Jarvis</div>
    </div>`;
}

async function makePdf(btn, topic, text) {
  if (typeof html2pdf === 'undefined') {
    alert('The PDF tool did not load. Check your internet connection and refresh the page.');
    return;
  }

  const originalHtml = btn.innerHTML;
  const setLabel = (msg) => { const s = btn.querySelector('span'); if (s) s.textContent = msg; else btn.textContent = msg; };

  btn.disabled = true;
  setLabel('Building your notes...');

  try {
    const res = await fetch('/api/notes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic: topic, text: text })
    });
    const data = await res.json();
    if (!res.ok || !data.notes) throw new Error(data.reply || 'Could not build the notes.');

    const colors = PDF_THEMES[getPdfThemeKey()];
    const holder = document.createElement('div');
    holder.innerHTML = buildNotesHtml(data.notes, colors);

    await html2pdf().set({
      margin: [12, 10, 14, 10],
      filename: slugify(data.notes.title) + '.pdf',
      image: { type: 'jpeg', quality: 0.95 },
      html2canvas: { scale: 2, useCORS: true, backgroundColor: '#ffffff' },
      jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
      pagebreak: { mode: ['css', 'legacy'], avoid: '.keep' }
    }).from(holder).save();

    setLabel('Saved! Tap to download again');
  } catch (err) {
    console.error(err);
    // Show the real reason (e.g. a Gemini quota limit) instead of a generic failure
    const reason = (err && err.message) ? err.message : 'Something went wrong.';
    setLabel(reason.length > 60 ? reason.slice(0, 57) + '...' : reason);
    btn.title = reason;
  } finally {
    btn.disabled = false;
    setTimeout(() => { btn.innerHTML = originalHtml; btn.title = ''; }, 5000);
  }
}

window.getPdfThemeKey = getPdfThemeKey;
window.setPdfTheme = setPdfTheme;
window.makePdf = makePdf;
