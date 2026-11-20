// Vocabularies in the review pages (author, 12 Nov 2026): the DPV purposes and Skuld's data types as trees.
//  - <vocab-term kind="purpose|data" :id="…">: a value shown in code type; a click opens it in its vocabulary (view mode),
//    selected and with its path expanded, beside its broader node, its siblings and its narrower nodes, so that a
//    reviewer sees it in its context (exact, too broad, too narrow?);
//  - <node-picker>: a field for a DPV purpose with suggestions while typing and a button that opens the tree (select
//    mode);
//  - <vocab-browser>: the tree, in view or select mode.
// A page provides `openVocab(kind, id)` (provide/inject) and shows <vocab-browser> while its `browser` is set.

const STYLE = `
    .tiny { font-size: .72rem; }
    code.vocab-link { cursor: pointer; text-decoration: underline dotted; text-underline-offset: 2px; }
    code.vocab-link:hover { background: #fde2ef; }
    .picker-menu { position: absolute; z-index: 30; right: 0; min-width: 100%; width: min(26rem, 80vw); max-height: 18rem; overflow-y: auto; box-shadow: 0 .4rem 1rem rgba(0,0,0,.15); }
    .picker-menu .list-group-item.active .text-secondary { color: #e9ecef !important; }
    .browser-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.35); z-index: 1050; display: flex; align-items: center; justify-content: center; }
    .browser { width: min(1100px, 94vw); height: min(780px, 88vh); display: flex; flex-direction: column; }
    .browser .card-body { min-height: 0; }
    .browser .tree { flex: 1 1 58%; overflow-y: auto; border-right: 1px solid #dee2e6; padding-right: .5rem; }
    .browser .detail { flex: 1 1 42%; overflow-y: auto; }
    .tree-row { cursor: pointer; padding: .1rem .3rem; border-radius: .2rem; font-size: .88rem; white-space: nowrap; }
    .tree-row:hover { background: #eef2f7; }
    .tree-row.sel { background: #0d6efd; color: #fff; }
    .tree-row.origin:not(.sel) { background: #fff3cd; }
    .tree-row.hit { font-weight: 600; }
    .tree-row .tw { display: inline-block; width: 1rem; color: #6c757d; }
    .tree-row.sel .tw { color: #fff; }
    .tree-row .origin-mark { font-size: .7rem; margin-left: .4rem; padding: 0 .3rem; border-radius: .2rem; background: #ffc107; color: #000; }
`;
const style = document.createElement('style');
style.textContent = STYLE;
document.head.appendChild(style);

const indexOf = vocab => Object.fromEntries((vocab || []).map(n => [n.id, n]));

// the titles from the top down to a node's parent, along its first parent
export const pathOf = (id, idx) => {
    const out = [], seen = new Set([id]);
    let cur = idx[id];
    while (cur && (cur.parents || []).length) {
        const parent = idx[cur.parents[0]];
        if (!parent || seen.has(parent.id)) break;
        seen.add(parent.id);
        out.unshift(parent.title);
        cur = parent;
    }
    return out;
};
const words = id => id.split(/(?=[A-Z])|[.\-_]/).map(w => w.toLowerCase()).filter(Boolean);

export const VocabTerm = {
    props: {kind: {type: String, required: true}, id: String},
    inject: ['openVocab'],
    template: `<code v-if="id" class="vocab-link" role="button" :title="'Show ' + id + ' in its vocabulary'" @click.stop="openVocab(kind, id)">{{ id }}</code><span v-else>–</span>`,
};

// a text field for a DPV purpose node, with suggestions as one types and a button that opens the tree
export const NodePicker = {
    props: {modelValue: {type: String, default: ''}, vocab: {type: Array, default: () => []}, placeholder: String},
    emits: ['update:modelValue', 'browse'],
    data: () => ({open: false, active: 0}),
    computed: {
        idx() { return indexOf(this.vocab); },
        valid() { return !this.modelValue || !!this.idx[this.modelValue]; },
        suggestions() {
            const q = (this.modelValue || '').trim().toLowerCase();
            if (!q || this.idx[this.modelValue]) return [];
            const scored = [];
            for (const n of this.vocab) {
                const id = n.id.toLowerCase(), title = (n.title || '').toLowerCase();
                let s = null;
                if (id.startsWith(q) || title.startsWith(q)) s = 0;
                else if (words(n.id).some(w => w.startsWith(q)) || title.split(/\s+/).some(w => w.startsWith(q))) s = 1;
                else if (id.includes(q.replace(/\s+/g, '')) || title.includes(q)) s = 2;
                else if (q.length >= 3 && (n.description || '').toLowerCase().includes(q)) s = 3;
                if (s !== null) scored.push([s, title.length, n]);
            }
            return scored.sort((a, b) => a[0] - b[0] || a[1] - b[1]).slice(0, 8).map(x => x[2]);
        },
    },
    methods: {
        path(n) { return pathOf(n.id, this.idx); },
        choose(n) { this.$emit('update:modelValue', n.id); this.open = false; },
        input(e) { this.$emit('update:modelValue', e.target.value); this.open = true; this.active = 0; },
        key(e) {
            const n = this.suggestions.length;
            if (e.key === 'ArrowDown' && n) { e.preventDefault(); this.open = true; this.active = (this.active + 1) % n; }
            else if (e.key === 'ArrowUp' && n) { e.preventDefault(); this.active = (this.active - 1 + n) % n; }
            else if (e.key === 'Enter' && this.open && n) { e.preventDefault(); this.choose(this.suggestions[this.active]); }
            else if (e.key === 'Escape') this.open = false;
        },
    },
    template: `<div class="position-relative">
        <div class="input-group input-group-sm">
            <input class="form-control" :class="{'is-invalid': !valid && !open}" :value="modelValue" :placeholder="placeholder"
                   @input="input" @focus="open = true" @blur="open = false" @keydown.stop="key" @click.stop>
            <button class="btn btn-outline-secondary" type="button" title="Browse the DPV purposes" @click.stop="$emit('browse')"><i class="bi bi-diagram-3"></i></button>
        </div>
        <div v-if="!valid && !(open && suggestions.length)" class="tiny text-danger mt-1">not a DPV purpose: pick one from the suggestions or browse</div>
        <div v-if="open && suggestions.length" class="list-group picker-menu">
            <button v-for="(n, i) in suggestions" :key="n.id" type="button" class="list-group-item list-group-item-action py-1"
                    :class="{active: i === active}" @mousedown.prevent="choose(n)" @mouseenter="active = i">
                <div class="small"><b>{{ n.title }}</b> <code :class="{'text-white': i === active}">{{ n.id }}</code></div>
                <div class="tiny text-secondary">{{ path(n).join(' › ') || 'top level' }}</div>
            </button>
        </div>
    </div>`,
};

// one node of the tree and, when open, the nodes under it
export const NodeTree = {
    name: 'node-tree',
    props: ['id', 'depth', 'idx', 'children', 'expanded', 'visible', 'hits', 'selected', 'origin'],
    emits: ['pick', 'choose', 'toggle'],
    computed: {
        kids() { return (this.children[this.id] || []).filter(c => !this.visible || this.visible.has(c)); },
        isOpen() { return !!this.expanded[this.id] || (!!this.visible && this.kids.length > 0); },
    },
    template: `<div>
        <div class="tree-row" :class="{sel: id === selected, origin: id === origin, hit: hits && hits.has(id)}"
             :style="{paddingLeft: (depth * 1.1 + .3) + 'rem'}" :data-node="id" @click="$emit('pick', id)" @dblclick="$emit('choose', id)">
            <span class="tw" @click.stop="$emit('toggle', id)">{{ kids.length ? (isOpen ? '▾' : '▸') : '·' }}</span>{{ idx[id].title }}<span v-if="id === origin" class="origin-mark">shown in the unit</span>
        </div>
        <template v-if="isOpen">
            <node-tree v-for="c in kids" :key="c" :id="c" :depth="depth + 1" :idx="idx" :children="children" :expanded="expanded"
                       :visible="visible" :hits="hits" :selected="selected" :origin="origin"
                       @pick="$emit('pick', $event)" @choose="$emit('choose', $event)" @toggle="$emit('toggle', $event)"></node-tree>
        </template>
    </div>`,
};

// the vocabulary as a tree, in a modal: view (a value of the unit, in its context) or select (a node for a field)
export const VocabBrowser = {
    components: {NodeTree},
    props: {vocab: {type: Array, default: () => []}, mode: {type: String, default: 'view'}, initial: String, title: String},
    emits: ['close', 'choose'],
    data: () => ({query: '', expanded: {}, selected: null}),
    computed: {
        idx() { return indexOf(this.vocab); },
        children() {
            const out = {};
            for (const n of this.vocab) for (const p of n.parents || []) if (this.idx[p]) (out[p] = out[p] || []).push(n.id);
            for (const k of Object.keys(out)) out[k].sort((a, b) => this.idx[a].title.localeCompare(this.idx[b].title));
            return out;
        },
        roots() {
            return this.vocab.filter(n => !(n.parents || []).some(p => this.idx[p])).map(n => n.id)
                .sort((a, b) => this.idx[a].title.localeCompare(this.idx[b].title));
        },
        // the filter: the nodes that match, and their ancestors so that the tree shows the way to them
        hits() {
            const q = this.query.trim().toLowerCase();
            if (q.length < 2) return new Set();
            return new Set(this.vocab.filter(n => n.id.toLowerCase().includes(q.replace(/\s+/g, '')) || (n.title || '').toLowerCase().includes(q)
                || (n.description || '').toLowerCase().includes(q)).map(n => n.id));
        },
        visible() {
            if (this.query.trim().length < 2) return null;
            const out = new Set();
            const up = id => { if (out.has(id)) return; out.add(id); for (const p of (this.idx[id] || {}).parents || []) if (this.idx[p]) up(p); };
            for (const id of this.hits) up(id);
            return out;
        },
        visibleRoots() { return this.roots.filter(r => !this.visible || this.visible.has(r)); },
        node() { return this.idx[this.selected]; },
        broader() { return ((this.node || {}).parents || []).filter(p => this.idx[p]); },
        siblings() {
            const parent = this.broader[0];
            return parent ? (this.children[parent] || []).filter(c => c !== this.selected) : [];
        },
        unknown() { return this.initial && !this.idx[this.initial]; },
    },
    methods: {
        path(id) { return pathOf(id, this.idx); },
        toggle(id) { this.expanded = {...this.expanded, [id]: !this.expanded[id]}; },
        expandAll(open) { this.expanded = open ? Object.fromEntries(Object.keys(this.children).map(k => [k, true])) : {}; },
        reveal(id) {
            this.selected = id;
            const expanded = {...this.expanded};
            for (let cur = this.idx[id]; cur && (cur.parents || []).length; cur = this.idx[cur.parents[0]]) {
                if (expanded[cur.parents[0]]) break;
                expanded[cur.parents[0]] = true;
            }
            this.expanded = expanded;
            this.$nextTick(() => {
                const row = this.$el.querySelector(`.tree-row[data-node="${CSS.escape(id)}"]`);
                if (row) row.scrollIntoView({block: 'center'});
            });
        },
        choose(id) { if (this.mode === 'select' && this.idx[id]) this.$emit('choose', id); },
        dblclick(id) { if (this.mode === 'select') this.choose(id); else this.reveal(id); },
    },
    mounted() {
        if (this.initial && this.idx[this.initial]) this.reveal(this.initial);
        this.$nextTick(() => this.mode === 'select' && this.$refs.search && this.$refs.search.focus());
    },
    template: `<div class="browser-backdrop" @click.self="$emit('close')">
        <div class="card browser shadow">
            <div class="card-header d-flex align-items-center gap-3">
                <b class="text-nowrap">{{ title }}</b>
                <input ref="search" class="form-control form-control-sm" v-model="query" placeholder="Filter by name, id or description"
                       @keydown.stop @keydown.esc="$emit('close')">
                <span class="small text-secondary text-nowrap" v-if="query.trim().length >= 2">{{ hits.size }} match(es)</span>
                <button class="btn btn-sm btn-outline-secondary text-nowrap" @click="expandAll(true)">Expand all</button>
                <button class="btn btn-sm btn-outline-secondary text-nowrap" @click="expandAll(false)">Collapse</button>
                <button class="btn-close" @click="$emit('close')"></button>
            </div>
            <div class="card-body d-flex gap-3">
                <div class="tree">
                    <div v-if="!vocab.length" class="text-secondary small">This sample carries no such vocabulary.</div>
                    <node-tree v-for="r in visibleRoots" :key="r" :id="r" :depth="0" :idx="idx" :children="children" :expanded="expanded"
                               :visible="visible" :hits="hits" :selected="selected" :origin="mode === 'view' ? initial : null"
                               @pick="id => (selected = id)" @choose="dblclick" @toggle="toggle"></node-tree>
                    <div v-if="vocab.length && !visibleRoots.length" class="text-secondary small">Nothing matches.</div>
                </div>
                <div class="detail">
                    <div v-if="unknown" class="alert alert-warning small py-2"><code>{{ initial }}</code> is not a node of this vocabulary.</div>
                    <template v-if="node">
                        <div class="small text-secondary">{{ path(selected).join(' › ') || 'top level' }}</div>
                        <h2 class="h5 mt-1 mb-0">{{ node.title }}</h2>
                        <code>{{ selected }}</code>
                        <span v-if="mode === 'view' && selected === initial" class="badge text-bg-warning ms-2">shown in the unit</span>
                        <p class="small mt-2">{{ node.description || 'No description.' }}</p>
                        <div class="small mb-1" v-if="broader.length"><span class="text-secondary">Broader:&nbsp;</span>
                            <template v-for="(c, i) in broader" :key="c"><a href="#" @click.prevent="reveal(c)">{{ idx[c].title }}</a>{{ i + 1 < broader.length ? ', ' : '' }}</template></div>
                        <div class="small mb-1" v-if="siblings.length"><span class="text-secondary">Alongside:&nbsp;</span>
                            <template v-for="(c, i) in siblings" :key="c"><a href="#" @click.prevent="reveal(c)">{{ idx[c].title }}</a>{{ i + 1 < siblings.length ? ', ' : '' }}</template></div>
                        <div class="small mb-1" v-if="(children[selected] || []).length"><span class="text-secondary">Narrower:&nbsp;</span>
                            <template v-for="(c, i) in children[selected]" :key="c"><a href="#" @click.prevent="reveal(c)">{{ idx[c].title }}</a>{{ i + 1 < children[selected].length ? ', ' : '' }}</template></div>
                        <button v-if="mode === 'select'" class="btn btn-primary mt-3" @click="choose(selected)"><i class="bi bi-check-lg"></i> Select this purpose</button>
                        <button v-else-if="initial && selected !== initial && idx[initial]" class="btn btn-sm btn-outline-secondary mt-3" @click="reveal(initial)">Back to the value shown in the unit</button>
                    </template>
                    <div v-else-if="!unknown" class="text-secondary small">Click a node to see its description{{ mode === 'select' ? '; double-click, or Select, to use it' : '' }}.</div>
                </div>
            </div>
        </div>
    </div>`,
};

// what a page registers and provides; it keeps `browser` ({kind, mode, initial, title, setter}) and `vocabs`
export function useVocabularies(app) {
    app.component('vocab-term', VocabTerm);
    app.component('node-picker', NodePicker);
    app.component('node-tree', NodeTree);
    app.component('vocab-browser', VocabBrowser);
}
export const TITLES = {purpose: 'DPV purposes', data: 'Data types'};
export async function loadVocabularies(api) {
    const [purpose, data] = await Promise.all([api('/vocabulary?kind=purpose'), api('/vocabulary?kind=data')]);
    return {purpose, data};
}
