(async () => {
    const output = parent.document.getElementById('test_results');
    const passed = [];
    const get = id => document.getElementById(id);
    const assert = (condition, message) => { if (!condition) throw new Error(message); };
    const settle = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
    const type = text => { get('morphology_word').value = text; get('morphology_word').dispatchEvent(new Event('input', {bubbles:true})); };
    const submit = async word => { type(word); get('morphology_form').requestSubmit(); await settle(); };
    async function test(name, run) {
        await run(); passed.push(name);
        output.textContent = passed.map(name => 'PASS ' + name).join('\n');
    }
    try {
        await test('Switching tabs preserves the original editor text and line breaks', async () => {
            get('text_content').textContent = 'башҡорт\n\nһүҙ\n';
            const html = get('text_content').innerHTML;
            get('morphology_tab').click();
            assert(get('box').hidden && !get('morphology_panel').hidden, 'Wrong panel visible');
            get('spelling_tab').click();
            assert(get('text_content').innerHTML === html, 'Tab switch changed editor');
            assert(get('spelling_tab').getAttribute('aria-selected') === 'true', 'Tab selection missing');
            get('morphology_tab').click();
        });
        await test('Examples show all analyses, complete parts and Bashkir legend', async () => {
            document.querySelector('[data-analyze-word="халыҡтарҙыңмы"]').click(); await settle();
            assert(document.querySelectorAll('.word-analysis').length === 3, 'Alternatives lost');
            assert([...document.querySelector('.morpheme-chain').querySelectorAll('.morpheme-text')].map(node => node.textContent).join('') === 'халыҡтарҙыңмы', 'Incomplete word');
            assert(get('morphology_legend').textContent.includes('Күплек һан') && get('morphology_legend').textContent.includes('Эйәлек килеш'), 'Missing Bashkir legend');
        });
        await test('Unknown word reports no complete analysis and clears previous results', async () => {
            await submit('йцукен');
            assert(get('morphology_results').hidden, 'Old analysis still visible');
            assert(get('morphology_status').textContent.includes('Тулы анализ табылманы'), 'Unknown word guessed or ignored');
        });
        await test('Multiple words are rejected before a network request', async () => {
            const before = morphologyMock.requests.length;
            await submit('ике һүҙ');
            assert(morphologyMock.requests.length === before, 'Multiple words sent');
            assert(get('morphology_status').textContent === 'Бер генә һүҙ яҙығыҙ.', 'Missing input message');
        });
        await test('Service errors remain visible and resubmission recovers', async () => {
            morphologyMock.failNext = true; await submit('халыҡтарҙыңмы');
            assert(get('morphology_results').hidden && get('morphology_status').textContent.includes('тамамлап булманы'), 'Service error became a result');
            await submit('халыҡтарҙыңмы');
            assert(!get('morphology_results').hidden, 'Retry failed');
        });
        await test('Slow old response cannot overwrite a newer analysis', async () => {
            let release;
            morphologyMock.hold = new Promise(resolve => { release = resolve; });
            type('халыҡтарҙыңмы'); get('morphology_form').requestSubmit();
            assert(get('morphology_form').getAttribute('aria-busy') === 'true', 'Missing loading state');
            await submit('халыҡтарҙыңдыр');
            release(); await settle();
            assert(get('analyzed_word').textContent === 'халыҡтарҙыңдыр', 'Stale response replaced current result');
            assert(get('morphology_form').getAttribute('aria-busy') === 'false', 'Loading state stuck');
        });
        await test('Editing while a request is pending cancels its visible result', async () => {
            let release; morphologyMock.hold = new Promise(resolve => { release = resolve; });
            type('халыҡтарҙыңмы'); get('morphology_form').requestSubmit();
            type('халыҡтар'); release(); await settle();
            assert(get('morphology_results').hidden && get('morphology_status').textContent === '', 'A response appeared for the wrong input');
        });
        await test('Keyboard tab navigation updates visibility and accessibility state', async () => {
            get('morphology_tab').dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowLeft',bubbles:true}));
            assert(!get('box').hidden && get('morphology_panel').hidden, 'Arrow key did not switch tools');
            get('spelling_tab').dispatchEvent(new KeyboardEvent('keydown', {key:'End',bubbles:true}));
            assert(get('morphology_tab').getAttribute('aria-selected') === 'true', 'End did not select last tab');
        });
        output.textContent += `\n\n${passed.length} morphology browser tests passed.`;
    } catch (error) { output.textContent += '\nFAIL ' + error.stack; }
})();
