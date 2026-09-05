// Synthetic responses isolate tab/form behavior from the real grammar tests.
const morphologyMock = {requests: [], hold: null, failNext: false};
// srcdoc cannot rewrite its URL. Hash navigation is checked separately on the
// real app; this fixture isolates the panel and request behavior.
history.replaceState = () => {};
window.fetch = async (url, options) => {
    const payload = JSON.parse(options.body);
    morphologyMock.requests.push({url, payload});
    if (morphologyMock.hold) {
        const pending = morphologyMock.hold;
        morphologyMock.hold = null;
        await pending; // Deliberately ignore abort to exercise stale-response guards.
    }
    if (morphologyMock.failNext) {
        morphologyMock.failNext = false;
        return {ok: false, status: 503};
    }
    if (url === '/data_processing') return {ok: true, json: async () => ({message: payload.unverified_words.map(word => ({word, correct: true, variants: []}))})};
    const word = payload.word;
    const analyses = [];
    const final = word.endsWith('дыр') ? 'дыр' : 'мы';
    const endingTag = final === 'дыр' ? 'Indf' : 'Q';
    if (word === 'халыҡтарҙыңмы' || word === 'халыҡтарҙыңдыр') {
        for (const [stem, pos] of [['халыҡ', 'Noun'], ['халыҡ', 'A'], ['халыҡтар', 'Noun']]) {
            const parts = [{text: stem, tags: [], kind: 'stem'}];
            if (stem === 'халыҡ') parts.push({text: 'тар', tags: ['Pl'], kind: 'suffix'});
            parts.push({text: 'ҙың', tags: ['Gen'], kind: 'suffix'}, {text: final, tags: [endingTag], kind: 'suffix'});
            analyses.push({stem, pos: [pos], tags: parts.flatMap(part => part.tags), parts, changes: []});
        }
    }
    const labels = {Noun:'Исем', A:'Сифат', Pl:'Күплек һан', Gen:'Эйәлек килеш', Q:'Һорау киҫәксәһе', Indf:'Фаразлау киҫәксәһе'};
    const tags = [...new Set(analyses.flatMap(item => [...item.pos, ...item.tags]))];
    return {ok: true, json: async () => ({word, analyses, legend: tags.map(tag => ({tag, label: labels[tag], description: labels[tag]}))})};
};
