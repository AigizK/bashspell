(() => {
    'use strict';
    const spellingTab = document.getElementById('spelling_tab');
    const morphologyTab = document.getElementById('morphology_tab');
    const spellingPanel = document.getElementById('box');
    const morphologyPanel = document.getElementById('morphology_panel');
    const form = document.getElementById('morphology_form');
    const input = document.getElementById('morphology_word');
    const status = document.getElementById('morphology_status');
    const results = document.getElementById('morphology_results');
    const list = document.getElementById('analysis_list');
    const legend = document.getElementById('morphology_legend');
    let requestNumber = 0;
    let controller = null;

    function activateTab(morphology, focus = false) {
        spellingPanel.hidden = morphology;
        morphologyPanel.hidden = !morphology;
        for (const [tab, active] of [[spellingTab, !morphology], [morphologyTab, morphology]]) {
            tab.setAttribute('aria-selected', String(active));
            tab.tabIndex = active ? 0 : -1;
        }
        // Hiding the editor must not leave its suggestion menu visible.
        if (morphology) closeMenu();
        if (focus) (morphology ? morphologyTab : spellingTab).focus();
        // Fallback underlines need positions recalculated after showing the editor.
        if (!morphology && !hasHighlights) paintFallback();
    }
    spellingTab.addEventListener('click', () => {
        history.replaceState(null, '', location.pathname + location.search);
        activateTab(false);
    });
    morphologyTab.addEventListener('click', () => {
        history.replaceState(null, '', '#morphology');
        activateTab(true);
    });
    for (const tab of [spellingTab, morphologyTab]) {
        tab.addEventListener('keydown', event => {
            if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
            event.preventDefault();
            const morphology = event.key === 'End' || (event.key !== 'Home' && tab === spellingTab);
            (morphology ? morphologyTab : spellingTab).click();
            activateTab(morphology, true);
        });
    }
    window.addEventListener('hashchange', () => activateTab(location.hash === '#morphology'));
    activateTab(location.hash === '#morphology');

    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function render(data) {
        list.replaceChildren();
        legend.replaceChildren();
        if (!data.analyses.length) {
            results.hidden = true;
            status.textContent = 'Тулы анализ табылманы. Яҙылышын тикшерегеҙ йәки башҡа һүҙ яҙып ҡарағыҙ.';
            return;
        }
        const labels = new Map(data.legend.map(item => [item.tag, item]));
        document.getElementById('analyzed_word').textContent = data.word;
        document.getElementById('analysis_count').textContent = `Табылған варианттар: ${data.analyses.length}`;
        for (const [index, analysis] of data.analyses.entries()) {
            const article = element('article', 'word-analysis');
            const heading = element('div', 'analysis-heading');
            heading.append(element('span', 'analysis-number', String(index + 1).padStart(2, '0')));
            heading.append(element('h4', '', `Нигеҙе: ${analysis.stem}`));
            for (const pos of analysis.pos) {
                const tag = element('abbr', 'grammar-tag', pos);
                tag.title = labels.get(pos)?.label || pos;
                heading.append(tag, element('span', 'part-of-speech', labels.get(pos)?.label || pos));
            }
            const chain = element('div', 'morpheme-chain');
            chain.setAttribute('aria-label', 'Һүҙҙең өлөштәре');
            for (const [partIndex, part] of analysis.parts.entries()) {
                if (partIndex) {
                    const plus = element('span', 'morpheme-plus', '+');
                    plus.setAttribute('aria-hidden', 'true');
                    chain.append(plus);
                }
                const piece = element('div', `morpheme ${part.kind === 'stem' ? 'morpheme-stem' : ''}`);
                piece.append(element('span', 'morpheme-text', part.text || '∅'));
                const tags = element('span', 'morpheme-tags');
                if (part.kind === 'stem') tags.textContent = 'нигеҙ';
                else for (const code of part.tags) {
                    const tag = element('abbr', '', code);
                    tag.title = labels.get(code)?.label || code;
                    tags.append(tag, document.createTextNode(' '));
                }
                piece.append(tags);
                chain.append(piece);
            }
            article.append(heading, chain);
            if (analysis.changes.length) {
                const changes = analysis.changes.map(change => `${change.from} → ${change.to || '∅'}`).join('; ');
                article.append(element('p', 'analysis-changes', `Үҙгәрештәр: ${changes}.`));
            }
            list.append(article);
        }
        for (const item of data.legend) {
            const row = element('div', 'legend-entry');
            row.append(element('dt', '', item.tag));
            const description = element('dd');
            description.append(element('strong', '', item.label), element('span', '', item.description));
            row.append(description);
            legend.append(row);
        }
        results.hidden = false;
        status.textContent = '';
    }

    input.addEventListener('input', () => {
        requestNumber++;
        controller?.abort();
        status.textContent = '';
        results.hidden = true;
        form.setAttribute('aria-busy', 'false');
    });
    form.addEventListener('submit', async event => {
        event.preventDefault();
        const word = input.value.trim().normalize('NFC');
        controller?.abort();
        const current = ++requestNumber;
        results.hidden = true;
        if (!/^\p{L}+(?:[-'’]\p{L}+)*$/u.test(word)) {
            status.textContent = 'Бер генә һүҙ яҙығыҙ.';
            form.setAttribute('aria-busy', 'false');
            return;
        }
        controller = new AbortController();
        const activeController = controller;
        const timeout = setTimeout(() => activeController.abort(), 15000);
        status.textContent = 'Тикшерелә…';
        form.setAttribute('aria-busy', 'true');
        try {
            const response = await fetch('/analyze', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({word}), signal: activeController.signal
            });
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            if (current !== requestNumber) return;
            if (data.word !== word || !Array.isArray(data.analyses) || !Array.isArray(data.legend)) throw new Error('Invalid analysis response');
            render(data);
        } catch (error) {
            if (current !== requestNumber) return;
            status.textContent = 'Анализды тамамлап булманы. Ҡабатлап ҡарағыҙ.';
        } finally {
            clearTimeout(timeout);
            if (current === requestNumber) form.setAttribute('aria-busy', 'false');
        }
    });
    document.querySelectorAll('[data-analyze-word]').forEach(button => {
        button.addEventListener('click', () => {
            input.value = button.dataset.analyzeWord;
            form.requestSubmit();
        });
    });
})();
