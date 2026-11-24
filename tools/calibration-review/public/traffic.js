// The traffic E was shown, as a reviewer reads it (24 Nov 2026): each line of stage 1's traffic is one finding of O,
//   "<METHOD> <URL> · <field>: …<before>«<datum>»<after>… (<data type>)"
// where <field> is `header:<i>:<name>`, `body` or `path` (also "<field>: …«<why unreadable>»…", "content <why>" and
// "<data type> found in <field>"). A finding is split into its parts: the method, the host and path, the query's
// parameters, the field the datum was found in, the excerpt with the datum marked, and the data type. Findings at the
// same method and URL are shown as one request. A line that does not parse is shown as it is.

const escape = t => String(t ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'})[c]);

export function parseTraffic(text) {
    // a cited part or evidence item names the practice first ("P-1a2b3c: POST …"): not part of the message
    const m = /^([A-Z]+|\?) (\S+) · ([\s\S]*)$/.exec(String(text || '').replace(/^P-[0-9a-f]+: /, ''));
    if (!m) return null;
    const [, method, url, rest] = m;
    const out = {method, url, host: url, path: '', params: [], field: null, before: '', datum: '', after: '', node: null, note: null};
    try {
        const u = new URL(url.replace(/…$/, ''));
        out.host = u.host;
        out.path = u.pathname + (url.endsWith('…') && !u.search ? '…' : '');
        out.params = [...u.searchParams.entries()];
        if (url.endsWith('…') && u.search) out.params.push(['…', '']);
    } catch (e) { /* a URL the browser does not parse: shown whole as the host */ }
    let f;
    if ((f = /^content (.*)$/.exec(rest))) { out.note = `content ${f[1]}`; return out; }
    if ((f = /^(\S+) found in (\S+)$/.exec(rest))) { out.node = f[1]; out.field = field(f[2]); return out; }
    const at = rest.indexOf(': …');
    if (at < 0) { out.note = rest; return out; }
    out.field = field(rest.slice(0, at));
    let body = rest.slice(at + 3);
    const node = /\s\(([^()]+)\)$/.exec(body);
    if (node) { out.node = node[1]; body = body.slice(0, node.index); }
    body = body.replace(/…$/, '');
    const d = /^([\s\S]*?)«([\s\S]*?)»([\s\S]*)$/.exec(body);
    if (d) [, out.before, out.datum, out.after] = d;
    else out.before = body;
    return out;
}

function field(name) {
    const [base] = name.split('#');
    const h = /^header:\d+:(.+)$/.exec(base);
    if (h) return {kind: 'header', label: 'Header', name: h[1]};
    if (base === 'body') return {kind: 'body', label: 'Body', name: ''};
    if (base === 'path') return {kind: 'path', label: 'URL', name: ''};
    return {kind: 'other', label: base, name: ''};
}

// the lines of one method and URL as one request, in the order first met
export function groupTraffic(lines) {
    const groups = [];
    for (const line of lines || []) {
        const p = parseTraffic(line);
        const key = p ? `${p.method} ${p.url}` : `raw:${groups.length}`;
        const last = groups.find(g => g.key === key);
        if (last && p) last.findings.push(p);
        else groups.push({key, request: p, raw: p ? null : line, findings: p ? [p] : []});
    }
    return groups;
}

const STYLE = `
.http { border: 1px solid #dee2e6; border-radius: .3rem; margin-bottom: .5rem; background: #fff; font-size: .8rem; }
.http-head { display: flex; gap: .4rem; align-items: baseline; padding: .3rem .5rem; background: #f8f9fa; border-bottom: 1px solid #dee2e6; border-radius: .3rem .3rem 0 0; word-break: break-all; }
.http-method { font-family: ui-monospace, Menlo, monospace; font-weight: 700; font-size: .72rem; padding: 0 .35rem; border-radius: .2rem; background: #e7f1ff; color: #0a58ca; flex: none; }
.http-host { font-weight: 600; }
.http-path { color: #495057; font-family: ui-monospace, Menlo, monospace; }
.http-params { padding: .25rem .5rem; border-bottom: 1px dashed #e9ecef; font-family: ui-monospace, Menlo, monospace; font-size: .74rem; }
.http-params summary { cursor: pointer; color: #6c757d; font-family: system-ui, sans-serif; }
.http-param { word-break: break-all; }
.http-param b { color: #6f42c1; font-weight: 600; }
.http-part { padding: .35rem .5rem; }
.http-part + .http-part { border-top: 1px dashed #e9ecef; }
.http-part-head { display: flex; justify-content: space-between; gap: .5rem; flex-wrap: wrap; color: #6c757d; font-size: .74rem; margin-bottom: .15rem; }
.http-part-head b { color: #212529; }
.http-excerpt { margin: 0; white-space: pre-wrap; word-break: break-all; font-family: ui-monospace, Menlo, monospace; font-size: .76rem; background: #f8f9fa; border-radius: .2rem; padding: .25rem .4rem; }
.http-excerpt mark.datum { background: #ffd166; font-weight: 600; padding: 0 .15em; }
.http-note { padding: .35rem .5rem; color: #6c757d; font-style: italic; }
`;

// one request: its method, host, path and parameters once, then each finding: field, excerpt, data type
export const TrafficRequest = {
    props: {group: {type: Object, required: true}, query: {type: String, default: ''}},
    methods: {
        hi(text) {
            const html = escape(text);
            const q = (this.query || '').trim();
            if (q.length < 3) return html;
            const pattern = new RegExp(escape(q).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
            return html.replace(pattern, m => `<mark>${m}</mark>`);
        },
    },
    template: `
<div v-if="group.request" class="http">
    <div class="http-head"><span class="http-method">{{ group.request.method }}</span>
        <span><span class="http-host" v-html="hi(group.request.host)"></span><span class="http-path" v-html="hi(group.request.path)"></span></span></div>
    <details v-if="group.request.params.length" class="http-params">
        <summary>{{ group.request.params.length }} query {{ group.request.params.length === 1 ? 'parameter' : 'parameters' }}</summary>
        <div v-for="([k, v], i) in group.request.params" :key="i" class="http-param"><b v-html="hi(k)"></b><span v-if="v"> = </span><span v-html="hi(v)"></span></div>
    </details>
    <div v-for="(f, i) in group.findings" :key="i" class="http-part">
        <template v-if="f.note"><div class="http-note">{{ f.note }}</div></template>
        <template v-else>
            <div class="http-part-head">
                <span>found in <b>{{ f.field ? f.field.label : '?' }}</b><span v-if="f.field && f.field.name"> <b v-html="hi(f.field.name)"></b></span></span>
                <span v-if="f.node">data type <vocab-term kind="data" :id="f.node"></vocab-term></span>
            </div>
            <pre v-if="f.before || f.datum || f.after" class="http-excerpt">…<span v-html="hi(f.before)"></span><mark class="datum" v-html="hi(f.datum)"></mark><span v-html="hi(f.after)"></span>…</pre>
        </template>
    </div>
</div>
<div v-else class="http"><div class="http-note" style="font-style: normal" v-html="hi(group.raw)"></div></div>`,
};

// a list of traffic lines, grouped by request
export const TrafficList = {
    props: {lines: {type: Array, default: () => []}, query: {type: String, default: ''}},
    computed: { groups() { return groupTraffic(this.lines); } },
    template: `<div><traffic-request v-for="g in groups" :key="g.key" :group="g" :query="query"></traffic-request></div>`,
};

export function useTraffic(app) {
    if (typeof document !== 'undefined' && !document.getElementById('traffic-style')) {
        const style = document.createElement('style');
        style.id = 'traffic-style';
        style.textContent = STYLE;
        document.head.appendChild(style);
    }
    app.component('traffic-request', TrafficRequest);
    app.component('traffic-list', TrafficList);
}
