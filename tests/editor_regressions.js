// Open /tests/editor.html (also ?fallback) with a local HTTP server from the repo root.
(async () => {
    const output = document.getElementById('test_results');
    const passed = [];
    const assert = (condition, message) => { if (!condition) throw new Error(message); };
    const settle = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
    function selectEnd() {
        const selection = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(text_content); range.collapse(false);
        selection.removeAllRanges(); selection.addRange(range);
        text_content.focus();
    }
    async function reset(text = '') {
        document.getElementById('clean_text').click();
        await settle();
        text_content.textContent = text;
        selectEnd();
        onInput({inputType: 'insertFromPaste'});
        checkText();
        await settle();
    }
    async function test(name, action) {
        await action(); passed.push(name);
        output.textContent = passed.map(name => 'PASS ' + name).join('\n');
    }
    try {
        await test('Tokenization: numbers, abbreviations, quoted suffixes and Unicode', async () => {
            assert(JSON.stringify(splitTextIntoWords('1941-ҙән 20-нән «Даная»ның респ. БР М. тарихы башкорд')) === JSON.stringify(['Данаяның', 'тарихы', 'башкорд']), 'Tokenization regression');
            assert(splitTextIntoWords('йөрәк и\u0306өрәк')[1] === 'йөрәк', 'NFC normalization');
        });
        await test('Trailing empty paragraph, DOM and caret survive checking', async () => {
            await reset();
            text_content.innerHTML = 'башкорд<div><br></div><div><br></div>';
            const empty = text_content.lastChild;
            const selection = window.getSelection();
            selection.collapse(empty, 0);
            const html = text_content.innerHTML;
            checkText(); await settle();
            assert(text_content.innerHTML === html, 'Checking rewrote line breaks');
            assert(selection.anchorNode === empty && selection.anchorOffset === 0, 'Caret moved');
            assert(errors.length === 1, 'Error not highlighted');
        });
        await test('Enter and Shift+Enter preserve blank lines and subsequent typing', async () => {
            for (const command of ['insertParagraph', 'insertLineBreak']) {
                await reset('башҡорт'); selectEnd();
                document.execCommand(command);
                document.execCommand(command);
                const html = text_content.innerHTML;
                const text = text_content.innerText;
                const selection = window.getSelection();
                const node = selection.anchorNode, offset = selection.anchorOffset;
                checkText(); await settle();
                assert(text_content.innerHTML === html && text_content.innerText === text, command + ' lost a line');
                assert(selection.anchorNode === node && selection.anchorOffset === offset, command + ' moved caret');
                document.execCommand('insertText', false, 'һүҙ');
                assert(text_content.innerText.includes('\n\nһүҙ'), command + ' continued on wrong line');
            }
        });
        await test('Paste preserves whitespace and treats HTML as text', async () => {
            await reset();
            const original = '\nбашҡорт  һүҙ\n\n<img src=x>\n';
            stripStyles({preventDefault() {}, clipboardData: {getData: () => original}});
            const html = text_content.innerHTML, text = text_content.innerText;
            checkText(); await settle();
            assert(text_content.innerText === text && text_content.innerHTML === html, 'Paste changed after checking');
            assert(text.includes('  ') && text.includes('\n\n') && text.includes('<img src=x>'), 'Whitespace or literal markup lost');
            assert(!text_content.querySelector('img'), 'Paste interpreted HTML');
            assert(editorSnapshot().text === original, 'Copy would add/remove newlines: ' + JSON.stringify(editorSnapshot().text));
        });
        await test('Typing keeps 3000 ms debounce; punctuation and Enter run immediately', async () => {
            await reset('башҡорт');
            const nativeTimer = window.setTimeout;
            let delay;
            window.setTimeout = (callback, ms, ...args) => { delay = ms; return nativeTimer(callback, ms, ...args); };
            try {
                onInput({inputType: 'insertText', data: 'ҡ'});
                assert(delay === 3000, 'Typing debounce removed');
                for (const event of [{inputType: 'insertText', data: ' '}, {inputType: 'insertParagraph'}, {inputType: 'insertLineBreak'}, {inputType: 'insertFromPaste'}]) {
                    onInput(event); assert(delay === 0, 'Completed word was delayed');
                }
            } finally { window.setTimeout = nativeTimer; clearTimeout(timer); }
        });
        await test('Fast batches never request suggestions and cache repeated words', async () => {
            const before = requests.length;
            await reset(('башҡорт башкорд ').repeat(500));
            const fresh = requests.slice(before);
            assert(fresh.length === 1 && fresh[0].data.unverified_words.length === 2, 'Repeated words sent multiple times');
            assert(fresh[0].data.include_suggestions === false, 'Eager suggestions');
            assert(errors.length === 500, 'Wrong repeated-error count');
            checkText(); await settle();
            assert(requests.length === before + 1, 'Cached words requested again');
        });
        await test('Long text uses sequential batches of at most 100 unique words', async () => {
            const words = Array.from({length: 240}, (_, i) => 'һа' + String.fromCharCode(0x410 + Math.floor(i / 32), 0x410 + i % 32) + 'ҡа');
            const before = requests.length;
            await reset(words.join(' '));
            const fresh = requests.slice(before);
            assert(fresh.length === 3, 'Wrong batch count');
            assert(fresh.every(request => request.data.unverified_words.length <= 100), 'Oversized batch');
            assert(new Set(fresh.flatMap(request => request.data.unverified_words)).size === 240, 'Words lost or duplicated');
            assert(errors.length === 240 && maximumRequests === 1, 'Batches overlapped or results incomplete');
        });
        await test('Suggestions load only on click, stay outside editor, replacement is undoable', async () => {
            await reset('башкорд\n\nбашҡорт');
            const before = requests.length, html = text_content.innerHTML;
            await openMenu(errors[0]);
            assert(requests.length === before + 1 && requests.at(-1).url === '/suggestions', 'Missing lazy request');
            assert(text_content.innerHTML === html && !text_content.contains(menu), 'Menu polluted editor');
            optionsList.querySelector('button').click(); await settle();
            assert(text_content.innerText === 'башҡорт\n\nбашҡорт', 'Replacement lost whitespace');
            document.execCommand('undo');
            assert(text_content.innerText === 'башкорд\n\nбашҡорт', 'Replacement not undoable');
            clearTimeout(timer);
        });
        await test('Stale response never changes newly typed text or highlights partial input', async () => {
            await reset();
            let release;
            pendingResponse = new Promise(resolve => { release = resolve; });
            text_content.textContent = 'башкорд'; onInput({inputType: 'insertFromPaste'}); checkText();
            text_content.textContent = 'башкордтар'; selectEnd(); onInput({inputType: 'insertText', data: 'р'});
            const html = text_content.innerHTML;
            release(); await settle();
            assert(text_content.innerHTML === html && errors.length === 0, 'Stale response painted partial word');
            checkText(); await settle();
            assert(errors[0].word === 'башкордтар', 'New text was not checked');
            assert(maximumRequests === 1, 'Requests overlapped');
        });
        await test('Clear discards pending results and counters', async () => {
            await reset(); let release;
            pendingResponse = new Promise(resolve => { release = resolve; });
            text_content.textContent = 'башкорд'; checkText();
            document.getElementById('clean_text').click(); release(); await settle();
            assert(text_content.innerText === '' && results.size === 0 && errors.length === 0, 'Old result survived clear');
        });
        await test('Failure of a cleared request does not block the next text', async () => {
            await reset(); let release;
            pendingResponse = new Promise(resolve => { release = resolve; });
            failNext = true;
            text_content.textContent = 'башкорд'; checkText();
            document.getElementById('clean_text').click();
            text_content.textContent = 'һүҙ'; checkText();
            release(); await settle();
            assert(retryButton.hidden && errors.length === 1 && errors[0].word === 'һүҙ', 'Old failure blocked new document');
        });
        await test('Late suggestions do not reopen a closed menu or alter text', async () => {
            await reset('башкорд'); let release;
            pendingResponse = new Promise(resolve => { release = resolve; });
            const opened = openMenu(errors[0]);
            text_content.textContent = 'башҡорт'; onInput({inputType: 'insertText', data: 'т'});
            release(); await opened; await settle();
            assert(menu.style.display === 'none' && text_content.innerText === 'башҡорт', 'Late suggestions changed the editor');
        });
        await test('Partial response is rejected and can be retried', async () => {
            await reset(); const nativeFetch = window.fetch;
            window.fetch = async () => ({ok: true, json: async () => ({message: []})});
            text_content.textContent = 'башкорд'; checkText(); await settle();
            window.fetch = nativeFetch;
            assert(!retryButton.hidden && results.size === 0, 'Invalid response was cached');
            retryButton.click(); await settle();
            assert(retryButton.hidden && errors.length === 1, 'Retry failed after malformed response');
        });
        await test('Network failure is visible and retry succeeds', async () => {
            await reset(); failNext = true;
            text_content.textContent = 'башкорд'; checkText(); await settle();
            assert(!retryButton.hidden && results.size === 0, 'Failure reported as success');
            retryButton.click(); await settle();
            assert(retryButton.hidden && errors.length === 1, 'Retry did not recover');
        });
        await test('IME composition defers checks until composition ends', async () => {
            await reset('башҡорт'); const before = requests.length;
            text_content.dispatchEvent(new CompositionEvent('compositionstart'));
            text_content.textContent = 'һүҙ'; onInput({isComposing: true}); checkText(); await settle();
            assert(requests.length === before, 'Composition checked too early');
            text_content.dispatchEvent(new CompositionEvent('compositionend'));
            checkText(); await settle();
            assert(errors.length === 1, 'Composition result not checked');
        });
        clearTimeout(timer); closeMenu();
        output.textContent += `\n\n${passed.length} tests passed (${hasHighlights ? 'CSS highlights' : 'fallback underlines'}).`;
    } catch (error) {
        clearTimeout(timer);
        output.textContent += '\nFAIL ' + error.stack;
    }
})();
