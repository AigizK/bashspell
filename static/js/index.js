const SPELLCHECK_ABBREVIATIONS = new Set([
    'авг', 'акад', 'басс', 'биол', 'гәз', 'геол', 'гр', 'ғин',
    'губерн', 'диам', 'див', 'дир', 'етәкс', 'иҡт', 'каф', 'кг',
    'км', 'ком', 'лаб', 'м', 'мәҫ', 'мед', 'млн', 'млрд', 'мм',
    'муз', 'нач', 'нефтехим', 'окт', 'өлк', 'орд', 'респ', 'реж',
    'сент', 'см', 'соц', 'станц', 'т', 'терр', 'февр', 'проф', 'ҡсб'
]);
const SPELLCHECK_ACRONYMS = new Set([
    'ААЙ', 'АССР', 'БАССР', 'БДУ', 'БР', 'БССР', 'ВИЧ', 'ҒПП',
    'КПСС', 'ПОЛИЭФ', 'РСФСР', 'РФ', 'СДПА', 'СССР', 'ФДУП',
    'ЭЭМ', 'ЮНЕСКО', 'ӨДАТУ'
]);

const text_content = document.getElementById('text_content');
const box = document.getElementById('box');
const placeholder = document.getElementById('placeholder');
const inform = document.getElementById('inform');
const statusText = document.getElementById('check_status');
const retryButton = document.getElementById('retry_check');
const results = new Map();
const suggestionCache = new Map();
const ignored = new Set();
const TYPING_DELAY = 3000;
const BATCH_SIZE = 100;
const hasHighlights = typeof CSS !== 'undefined' && CSS.highlights && typeof Highlight !== 'undefined';
if (!text_content.isContentEditable) text_content.contentEditable = 'true';
let timer, revision = 0, parsedRevision = -1, session = 0;
let tokens = [], errors = [], checking = false, composing = false;
let activeError = null, menuVersion = 0, currentIndex = -1;

function shouldIgnoreFrontendWord(word) {
    return /\d/u.test(word) || SPELLCHECK_ABBREVIATIONS.has(word.toLowerCase()) || SPELLCHECK_ACRONYMS.has(word);
}

// Keep source offsets: normalization must never rewrite the user's text.
function tokenize(text) {
    const letter = String.raw`\p{L}[\p{L}\p{M}]*`;
    const word = `${letter}(?:[-'’]${letter})*`;
    const pattern = new RegExp(`[«“„"](${word})[»”"](${letter})|(${word})`, 'gu');
    const found = [];
    for (const match of text.matchAll(pattern)) {
        const value = (match[1] ? match[1] + match[2] : match[3]).normalize('NFC');
        let start = match.index, end = start + match[0].length;
        let left = start, right = end;
        while (left && /[\p{L}\p{M}\p{N}_'’‐‑‒–—―-]/u.test(text[left - 1])) left--;
        while (right < text.length && /[\p{L}\p{M}\p{N}_'’‐‑‒–—―-]/u.test(text[right])) right++;
        if (/\d/u.test(text.slice(left, right)) || (value.length === 1 && text[end] === '.') || shouldIgnoreFrontendWord(value)) continue;
        found.push({word: value, start, end, quoted: Boolean(match[1]), source: match[0]});
    }
    return found;
}

function splitTextIntoWords(text) {
    return tokenize(text).map(token => token.word);
}

// Read text nodes and block boundaries without touching <div>, <br>, whitespace,
// selection or the browser's undo history. Ranges point into the original DOM.
function editorSnapshot() {
    const chunks = [], nodes = [];
    let length = 0;
    function append(value) { chunks.push(value); length += value.length; }
    const isBlock = node => node && /^(DIV|P|LI|BLOCKQUOTE|PRE|H[1-6])$/.test(node.nodeName);
    function walk(parent) {
        for (const node of parent.childNodes) {
            const previous = node.previousSibling;
            if (previous && previous.nodeName !== 'BR' && (isBlock(node) || isBlock(previous))) append('\n');
            if (node.nodeType === Node.TEXT_NODE) {
                nodes.push({node, start: length, end: length + node.length});
                append(node.data);
            } else if (node.nodeType === Node.ELEMENT_NODE) {
                // The final <br> is the browser's caret placeholder. Counting
                // it as text would add blank lines whenever the user copies.
                if (node.tagName === 'BR') { if (node.nextSibling) append('\n'); }
                else walk(node);
            }
        }
    }
    walk(text_content);
    return {text: chunks.join(''), nodes};
}

function readEditor(snapshot = editorSnapshot()) {
    const {text, nodes} = snapshot;
    let index = 0;
    return tokenize(text).map(token => {
        while (index < nodes.length && nodes[index].end <= token.start) index++;
        const first = nodes[index];
        let endIndex = index;
        while (endIndex < nodes.length && nodes[endIndex].end < token.end) endIndex++;
        const last = nodes[endIndex];
        const range = document.createRange();
        range.setStart(first.node, token.start - first.start);
        range.setEnd(last.node, token.end - last.start);
        return {...token, range};
    });
}

const fallbackMarks = document.createElement('div');
fallbackMarks.id = 'spellcheck_marks';
fallbackMarks.setAttribute('aria-hidden', 'true');
box.appendChild(fallbackMarks);

function paintErrors() {
    errors = tokens.filter(token => results.get(token.word) === false && !ignored.has(token.word));
    if (hasHighlights) {
        const highlight = new Highlight();
        for (const token of errors) highlight.add(token.range);
        CSS.highlights.set('spelling', highlight);
    } else {
        // Older browsers get a separate underline layer, never extra editor HTML.
        paintFallback();
    }
    document.getElementById('count_error').textContent = errors.length;
    for (const id of ['error_btn', 'error_btn2']) {
        document.getElementById(id).style.display = errors.length > 1 ? 'inline-block' : 'none';
    }
    currentIndex = Math.min(currentIndex, errors.length - 1);
}

function paintFallback() {
    const editorRect = text_content.getBoundingClientRect();
    const boxRect = box.getBoundingClientRect();
    fallbackMarks.style.left = `${editorRect.left - boxRect.left - box.clientLeft}px`;
    fallbackMarks.style.top = `${editorRect.top - boxRect.top - box.clientTop}px`;
    fallbackMarks.style.width = `${text_content.clientWidth}px`;
    fallbackMarks.style.height = `${text_content.clientHeight}px`;
    const fragment = document.createDocumentFragment();
    for (const token of errors) {
        for (const rect of token.range.getClientRects()) {
            const line = document.createElement('span');
            line.style.cssText = `left:${rect.left - editorRect.left}px;top:${rect.bottom - editorRect.top - 2}px;width:${rect.width}px`;
            fragment.appendChild(line);
        }
    }
    fallbackMarks.replaceChildren(fragment);
}

function updateCounters(text = editorSnapshot().text) {
    placeholder.style.display = text.trim() ? 'none' : 'block';
    inform.style.display = text.length ? 'block' : 'none';
    document.getElementById('count_symbol').textContent = text.length;
    document.getElementById('count_word').textContent = tokens.length;
}

function setStatus(state) {
    statusText.textContent = state === 'checking' ? 'Тикшерелә…' : state === 'error' ? 'Тикшереп булманы.' : '';
    retryButton.hidden = state !== 'error';
    text_content.setAttribute('aria-busy', String(state === 'checking'));
}

async function postJSON(url, data) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
        const response = await fetch(url, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(data), signal: controller.signal
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } finally {
        clearTimeout(timeout);
    }
}

// Only one batch at a time. Further edits reuse the pending word results and
// each next batch is taken from the current text, not an obsolete pasted text.
async function processQueue() {
    if (checking) return;
    checking = true;
    let requestSession = session;
    try {
        while (parsedRevision === revision) {
            const words = [...new Set(tokens.map(token => token.word))]
                .filter(word => !results.has(word) && !ignored.has(word)).slice(0, BATCH_SIZE);
            if (!words.length) { setStatus(''); break; }
            setStatus('checking');
            requestSession = session;
            const data = await postJSON('/data_processing', {unverified_words: words, include_suggestions: false});
            if (requestSession !== session) continue;
            if (!Array.isArray(data.message) || data.message.length !== words.length ||
                data.message.some((item, index) => item.word !== words[index] || typeof item.correct !== 'boolean')) {
                throw new Error('Invalid spellcheck response');
            }
            for (const item of data.message) results.set(item.word, item.correct);
            if (parsedRevision === revision) paintErrors();
        }
    } catch (error) {
        if (requestSession === session && parsedRevision === revision) {
            setStatus('error');
            console.error('Spellcheck failed:', error);
        }
    } finally {
        checking = false;
        // Clearing or replacing text while an old request fails must not stop
        // a new document's queue or resurrect an error for the cleared text.
        if (requestSession !== session && parsedRevision === revision) processQueue();
    }
}

function checkText() {
    clearTimeout(timer);
    if (composing) return;
    const snapshot = editorSnapshot();
    tokens = readEditor(snapshot);
    parsedRevision = revision;
    updateCounters(snapshot.text);
    paintErrors();
    processQueue();
}

function onInput(event) {
    clearTimeout(timer);
    revision++;
    closeMenu();
    tokens = [];
    paintErrors();
    updateCounters();
    setStatus('');
    if (event.isComposing || composing) return;
    const finished = /^(insertFromPaste|insertFromDrop|insertParagraph|insertLineBreak)$/.test(event.inputType) ||
        /[\s,.?!:;]$/u.test(event.data || '');
    timer = setTimeout(checkText, finished ? 0 : TYPING_DELAY);
}
text_content.addEventListener('input', onInput);
text_content.addEventListener('compositionstart', () => { composing = true; clearTimeout(timer); });
text_content.addEventListener('compositionend', () => { composing = false; onInput({}); });

function stripStyles(event) {
    event.preventDefault();
    const text = event.clipboardData.getData('text/plain').replace(/\r\n?/g, '\n');
    // insertText preserves native undo and treats angle brackets as literal text.
    document.execCommand('insertText', false, text);
    clearTimeout(timer);
    timer = setTimeout(checkText, 0);
}

const menu = document.createElement('div');
menu.id = 'rightWordDiv';
menu.setAttribute('role', 'dialog');
menu.setAttribute('aria-label', 'Ихтимал булған төҙәтмә');
const menuTitle = document.createElement('div');
menuTitle.id = 'lineOne';
menuTitle.textContent = 'Ихтимал булған төҙәтмә';
const optionsList = document.createElement('ul');
optionsList.id = 'dropdownlist';
const ignoreButton = document.createElement('button');
ignoreButton.id = 'ignor';
ignoreButton.textContent = 'Ҡалдырырға';
menu.append(menuTitle, optionsList, ignoreButton);
box.appendChild(menu);

function closeMenu() {
    menu.style.display = 'none';
    activeError = null;
    menuVersion++;
}

function positionMenu(token) {
    const rect = token.range.getBoundingClientRect();
    const parent = box.getBoundingClientRect();
    menu.style.display = 'block';
    menu.style.left = `${Math.max(0, Math.min(rect.left - parent.left - box.clientLeft, box.clientWidth - menu.offsetWidth))}px`;
    menu.style.top = `${rect.bottom - parent.top - box.clientTop + 5}px`;
}

async function openMenu(token) {
    closeMenu();
    activeError = token;
    currentIndex = errors.indexOf(token);
    const version = menuVersion;
    optionsList.textContent = 'Төҙәтмәләр эҙләнә…';
    positionMenu(token);
    try {
        if (!suggestionCache.has(token.word)) {
            const data = await postJSON('/suggestions', {word: token.word});
            if (!Array.isArray(data.variants)) throw new Error('Invalid suggestions');
            if (version !== menuVersion) return;
            suggestionCache.set(token.word, data.variants);
        }
        if (version !== menuVersion) return;
        optionsList.replaceChildren();
        for (const value of suggestionCache.get(token.word)) {
            const item = document.createElement('li');
            const button = document.createElement('button');
            button.textContent = value;
            button.addEventListener('click', () => replaceWord(token, value));
            item.appendChild(button);
            optionsList.appendChild(item);
        }
        if (!optionsList.childNodes.length) optionsList.textContent = 'Төҙәтмәләр табылманы.';
    } catch (error) {
        if (version !== menuVersion) return;
        optionsList.replaceChildren();
        const retry = document.createElement('button');
        retry.textContent = 'Ҡабатларға';
        retry.addEventListener('click', () => openMenu(token));
        optionsList.appendChild(retry);
    }
}

function replaceWord(token, value) {
    if (activeError !== token) return;
    const selection = window.getSelection();
    text_content.focus();
    selection.removeAllRanges();
    selection.addRange(token.range);
    // Retain quotes around a quoted name and its case suffix when possible.
    if (token.quoted) {
        const parts = token.source.match(/^([«“„"])(.*)([»”"])([\p{L}\p{M}]+)$/u);
        const suffix = parts[4];
        value = value.endsWith(suffix) ? parts[1] + value.slice(0, -suffix.length) + parts[3] + suffix : parts[1] + value + parts[3];
    }
    document.execCommand('insertText', false, value);
    closeMenu();
    checkText();
}

ignoreButton.addEventListener('click', () => {
    if (!activeError) return;
    ignored.add(activeError.word);
    closeMenu();
    paintErrors();
});

text_content.addEventListener('click', event => {
    if (parsedRevision !== revision || !window.getSelection().isCollapsed) return;
    const token = errors.find(item => [...item.range.getClientRects()].some(rect =>
        event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom + 3));
    if (token) openMenu(token);
    else closeMenu();
});
document.addEventListener('click', event => {
    if (!box.contains(event.target) || event.target.closest('#head_container') && !event.target.closest('#dbl_btn')) closeMenu();
});
document.addEventListener('keydown', event => { if (event.key === 'Escape') closeMenu(); });
text_content.addEventListener('scroll', () => { closeMenu(); if (!hasHighlights) paintFallback(); });
window.addEventListener('resize', () => { closeMenu(); if (!hasHighlights) paintFallback(); });

function navigateError(direction) {
    if (!errors.length) return;
    currentIndex = (currentIndex + direction + errors.length) % errors.length;
    const token = errors[currentIndex];
    const rect = token.range.getBoundingClientRect();
    const editorRect = text_content.getBoundingClientRect();
    if (rect.top < editorRect.top || rect.bottom > editorRect.bottom) {
        text_content.scrollTop += rect.top - editorRect.top - 20;
        requestAnimationFrame(() => {
            if (errors.includes(token)) openMenu(token);
        });
    } else {
        openMenu(token);
    }
}
document.getElementById('error_btn').addEventListener('click', () => navigateError(-1));
document.getElementById('error_btn2').addEventListener('click', () => navigateError(1));
document.getElementById('clean_text').addEventListener('click', () => {
    clearTimeout(timer);
    session++;
    revision++;
    results.clear(); suggestionCache.clear(); ignored.clear();
    text_content.replaceChildren();
    closeMenu(); currentIndex = -1;
    checkText();
});
document.getElementById('copy_text_btn').addEventListener('click', async () => {
    closeMenu();
    try {
        await navigator.clipboard.writeText(editorSnapshot().text);
    } catch (error) {
        const selection = window.getSelection();
        const saved = selection.rangeCount ? selection.getRangeAt(0).cloneRange() : null;
        const range = document.createRange();
        range.selectNodeContents(text_content);
        selection.removeAllRanges(); selection.addRange(range);
        document.execCommand('copy');
        selection.removeAllRanges();
        if (saved) selection.addRange(saved);
    }
});
retryButton.addEventListener('click', checkText);
updateCounters();
