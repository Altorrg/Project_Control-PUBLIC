const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../alkalmazas/statikus/alkalmazas.js'), 'utf8').replace(/\r\n/g, '\n');
function declaration(name) {
    let start = source.indexOf(`function ${name}(`);
    assert.notEqual(start, -1);
    if (source.slice(start - 6, start) === 'async ') start -= 6;
    const end = source.indexOf('\n}\n', start);
    assert.notEqual(end, -1);
    return source.slice(start, end + 3);
}
function chat(api) {
    const input = { value: 'Hogyan készítsek ajánlatkérést?' }, button = {}, status = {};
    const c = vm.createContext({state: {project: null, module: 'settings', aiAssistant: {messages: [], sending: false, lastMessage: ''}},
        $: selector => ({'#ai-assistant-input': input, '#ai-assistant-send': button, '#ai-assistant-status': status}[selector]),
        api, console: {error() {}}, renderAIAssistantMessages() {}, aiAssistantResponseText: p => p.answer});
    vm.runInContext(declaration('buildAIAssistantHistory') + declaration('sendAIAssistantMessage'), c);
    return {c, input, button, status};
}
test('Oracle failure preserves the question and allows a retry', async () => {
    let calls = 0;
    const f = chat(async () => {if (++calls === 1) throw Error('Nem elérhető'); return {answer: 'Válasz', sources: [{label: 'utmutato.md'}]};});
    await f.c.sendAIAssistantMessage();
    assert.equal(f.input.value, 'Hogyan készítsek ajánlatkérést?');
    assert.equal(f.button.disabled, false);
    await f.c.sendAIAssistantMessage();
    assert.equal(calls, 2);
    assert.equal(f.c.state.aiAssistant.messages.at(-1).sources[0].label, 'utmutato.md');
});
test('a failed request does not replace a newly typed draft', async () => {
    let reject;
    const f = chat(() => new Promise((_, r) => {reject = r;}));
    const pending = f.c.sendAIAssistantMessage();
    f.input.value = 'Új kérdés'; reject(Error('Időtúllépés')); await pending;
    assert.equal(f.input.value, 'Új kérdés');
});
test('long model replies do not make the next request exceed history limits', () => {
    const f = chat(async () => ({}));
    f.c.state.aiAssistant.messages = [{role: 'assistant', text: 'a'.repeat(8000)}, {role: 'error', text: 'Hiba'}, {role: 'user', text: 'Következő kérdés'}];
    const history = f.c.buildAIAssistantHistory();
    assert.equal(history.length, 1); assert.equal(history[0].content.length, 4000);
});
