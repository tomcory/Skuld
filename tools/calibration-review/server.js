// Review of a sample of E's output, in one of two kinds:
// - a calibration sample (skuld calibrate draw): blind; serves the items and the collections' documents, never E's
//   outcomes (key.json), and stores each decision in reviews.json. A prior review (prior-review.json: another
//   reviewer's decision and note per item) is shown with its item where there is one;
// - a review of aggregated concerns (skuld review draw, sample kind "aggregate-review"): non-blind, blind to the model
//   run (key.json, which names it, is never served); stores the criteria, phrases and overall judgment per unit in
//   reviews.json, and the recall pass per application in recall.json. A unit drawn to be shown blind first is served
//   without E's output until its blind decision is saved; a unit of declared purposes drawn with its phrases
//   (`blind_phrases`, samples drawn since 20 Nov 2026) is served with its phrases only until each is judged blind;
// - a review of the expectation stage's predictions (skuld review expect-draw, kind "expectation-review"): non-blind,
//   blind to the model run; per practice, the answers per purpose and dependency, the purposes missed, a note, and
//   `done` once every question asked is answered (the server refuses `done` before).
// Run with `npm start -- <folder>` (or CALIBRATION=<folder>), then open http://localhost:3001.

const express = require('express');
const fs = require('fs');
const path = require('path');

const FOLDER = path.resolve(process.argv[2] || process.env.CALIBRATION || '.');
const SAMPLE = path.join(FOLDER, 'sample.json');
const REVIEWS = path.join(FOLDER, 'reviews.json');
const POSITION = path.join(FOLDER, 'review-position.json');
const PRIOR = path.join(FOLDER, 'prior-review.json');
const PORT = Number(process.env.PORT || 3001);
const DECISIONS = ['fails', 'holds', 'unsure'];
const RECALL = path.join(FOLDER, 'recall.json');
const OVERALL = ['agree', 'disagree', 'unsure'];
// a verdict derived from the phrases (declared purposes E holds not specific) may also be partly: some phrases as E says
const DERIVED = [...OVERALL, 'partly'];
// the criteria's values: the sample's (since skuld.review 3, with mostly), else those of a sample drawn before
const criteria = () => ((sample().questions || {}).criteria) || {evidence: ['yes', 'partly', 'no', 'none_cited'], follows: ['yes', 'partly', 'no']};
const PHRASE = ['specific', 'not_specific', 'unsure'];

if (!fs.existsSync(SAMPLE)) {
    console.error(`no sample.json in ${FOLDER}: draw one with \`skuld calibrate draw\`, \`skuld review draw\` or \`skuld review expect-draw\``);
    process.exit(1);
}

// a missing file gives the fallback; a file that is there but unreadable is an error, so that saving over it cannot
// drop the reviews it holds
function readJson(file, fallback) {
    try {
        return JSON.parse(fs.readFileSync(file, 'utf-8'));
    } catch (e) {
        if (fallback !== undefined && e.code === 'ENOENT') return fallback;
        throw e;
    }
}

// write to a temporary file first, so that a crash never leaves half a file behind
function writeJson(file, data) {
    fs.writeFileSync(file + '.tmp', JSON.stringify(data, null, 1));
    fs.renameSync(file + '.tmp', file);
}

const sample = () => readJson(SAMPLE);
const items = () => sample().items;
const reviews = () => readJson(REVIEWS, {});
const AGGREGATE = sample().kind === 'aggregate-review';
const EXPECT = sample().kind === 'expectation-review';

// what an aggregate unit shows before its blind decision: the subject and the question, none of E's output
function blindView(item) {
    const keep = ['subject', 'data', 'recipient', 'purpose', 'declared', 'statement'];
    return {
        id: item.id, application: item.application, requirement: item.requirement, question: item.question,
        step: item.step, kind: item.kind, blind_first: true, blind_now: true,
        members: item.members.map(m => Object.fromEntries(Object.entries(m).filter(([k]) => keep.includes(k)))),
    };
}

// what a unit of declared purposes shows before its phrases are judged blind: the phrases, none of E's output (its
// status, label, reasons and evidence)
function phrasesView(item) {
    return {
        id: item.id, application: item.application, requirement: item.requirement, question: item.question,
        step: item.step, kind: item.kind, blind_phrases_now: true,
        members: item.blind_phrases.map(p => ({concern: p.concern, statement: p.statement})),
    };
}

// the phrases of a unit judged blind, each specific, not specific or unsure
const blindPhrasesDone = (item, review) => {
    const judged = review && review.blind_phrases && review.blind_phrases.phrases;
    return !!judged && item.blind_phrases.every(p => PHRASE.includes(judged[p.concern]));
};

// an aggregate review is decided once its overall judgment is given, an expectation review once it is done
const decided = r => (EXPECT ? !!(r && r.done) : AGGREGATE ? r && DERIVED.includes(r.overall) : r && DECISIONS.includes(r.decision));

// the unit's verdict is its phrases' where it is a unit of declared purposes E holds not specific
const derivedUnit = item => item.kind === 'declared' && item.status === 'supported';
function derive(item, phrases) {
    if (!phrases || item.members.some(m => !PHRASE.includes(phrases[m.concern]))) return undefined;
    const judged = item.members.map(m => phrases[m.concern]).filter(v => v !== 'unsure');
    if (!judged.length) return 'unsure';
    const agree = judged.filter(v => v === 'not_specific').length;
    return agree === judged.length ? 'agree' : agree === 0 ? 'disagree' : 'partly';
}

// an item's prior review, with who made it and when, or null
function priorReview(id) {
    const prior = readJson(PRIOR, null);
    const entry = prior && prior.items && prior.items[id];
    if (!entry || !DECISIONS.includes(entry.decision)) return null;
    return {decision: entry.decision, note: entry.note || '', reviewer: prior.reviewer || null, reviewed: prior.reviewed || null};
}

function progress() {
    const all = items();
    if (EXPECT) {
        const done = reviews();
        const reviewed = all.filter(i => decided(done[i.id])).length;
        return {calibration: path.basename(FOLDER), kind: 'expectation-review', total: all.length, reviewed,
                counts: {done: reviewed, started: all.filter(i => done[i.id] && !decided(done[i.id])).length}};
    }
    const done = reviews();
    const labels = AGGREGATE ? DERIVED : DECISIONS;
    const counts = Object.fromEntries(labels.map(d => [d, 0]));
    const field = AGGREGATE ? 'overall' : 'decision';
    Object.values(done).filter(decided).forEach(r => counts[r[field]]++);
    const reviewed = all.filter(i => decided(done[i.id])).length;
    return {calibration: path.basename(FOLDER), kind: AGGREGATE ? 'aggregate-review' : 'calibration', total: all.length, reviewed, counts};
}

const app = express();
app.use(express.json({limit: '5mb'}));
// the page for the sample's kind
app.get(['/', '/index.html'], (req, res) => res.sendFile(path.join(__dirname, 'public', EXPECT ? 'expectation.html' : AGGREGATE ? 'aggregate.html' : 'index.html')));
app.use(express.static(path.join(__dirname, 'public')));
app.use('/vendor/vue.js', express.static(path.join(__dirname, 'node_modules/vue/dist/vue.esm-browser.prod.js')));
app.use('/vendor/bootstrap.css', express.static(path.join(__dirname, 'node_modules/bootstrap/dist/css/bootstrap.min.css')));
app.use('/vendor/icons', express.static(path.join(__dirname, 'node_modules/bootstrap-icons/font')));
// only the collections' documents: E's outcomes stay in key.json, which is never served
app.use('/documents', express.static(path.join(FOLDER, 'documents')));
// the screenshots stage 1 was given of the screens the units show (skuld review_screens), named by digest
app.use('/screenshots', express.static(path.join(FOLDER, 'screenshots')));

app.get('/api/progress', (req, res) => res.send(progress()));

// a vocabulary the sample carries (?kind=purpose: the DPV purposes; ?kind=data: Skuld's data types), or none: the pages
// show the values of a unit in their vocabulary and pick purpose nodes from it, without a network
app.get('/api/vocabulary', (req, res) => {
    const s = sample();
    const kind = req.query.kind === 'data' ? 'data' : 'purpose';
    res.send((s.vocabularies || {})[kind] || (kind === 'purpose' ? s.purpose_vocabulary : null) || []);
});

app.get('/api/resume', (req, res) => res.send(readJson(POSITION, {index: 0})));

app.get('/api/items/:index', (req, res) => {
    const all = items();
    const index = Number(req.params.index);
    const item = all[index];
    if (!item) return res.status(404).send('no such item');
    writeJson(POSITION, {index});
    const review = reviews()[item.id] || null;
    if (EXPECT) return res.send({...item, index, total: all.length, review, questions: sample().questions});
    if (AGGREGATE) {
        const app_ = sample().applications[item.application] || {};
        const blindNow = item.blind_first && !(review && review.blind && DECISIONS.includes(review.blind.decision));
        const phrasesNow = !blindNow && item.blind_phrases && !blindPhrasesDone(item, review);
        const shown = blindNow ? blindView(item) : phrasesNow ? phrasesView(item) : item;
        return res.send({...shown, index, total: all.length, review, documents: app_.documents || [], questions: sample().questions || null,
                         application_units: all.filter(i => i.application === item.application).map(i => i.id)});
    }
    res.send({...item, index, total: all.length, review, prior_review: priorReview(item.id)});
});

// an application's practices and declared purpose nodes, for the recall pass, and the pass so far
app.get('/api/recall/:application', (req, res) => {
    if (!AGGREGATE) return res.status(404).send('no recall pass in a calibration sample');
    const entry = sample().applications[req.params.application];
    if (!entry) return res.status(404).send('no such application');
    const all = items().filter(i => i.application === req.params.application);
    const done = reviews();
    res.send({application: req.params.application, practices: entry.practices, declared_nodes: entry.declared_nodes,
              units: all.length, units_decided: all.filter(i => decided(done[i.id])).length,
              recall: readJson(RECALL, {})[req.params.application] || {missed: [], done: false, note: ''}});
});

app.put('/api/recall/:application', (req, res) => {
    if (!AGGREGATE) return res.status(404).send('no recall pass in a calibration sample');
    if (!sample().applications[req.params.application]) return res.status(404).send('no such application');
    const {missed, done, note} = req.body;
    if (!Array.isArray(missed) || missed.some(m => !m || typeof m.note !== 'string' || !m.note.trim())) {
        return res.status(400).send('missed must be a list of {requirement, subject, note} with a note');
    }
    const all = readJson(RECALL, {});
    all[req.params.application] = {
        missed: missed.map(m => ({requirement: m.requirement || '', subject: m.subject || '', note: m.note.trim()})),
        done: !!done, note: note || '', reviewed: new Date().toISOString(),
    };
    writeJson(RECALL, all);
    res.send(all[req.params.application]);
});

// the first item without a decision after the given index (or from the start)
app.get('/api/next-open', (req, res) => {
    const all = items();
    const done = reviews();
    const after = Number(req.query.after ?? -1);
    const open = all.map((item, index) => ({item, index})).filter(x => !decided(done[x.item.id]));
    const next = open.find(x => x.index > after) || open[0];
    res.send({index: next ? next.index : null});
});

// an aggregate unit's judgment: the blind decision (units shown blind first), the phrases judged blind (units of
// declared purposes drawn with them), the criteria, the phrases and the overall judgment; each part may come on its
// own, and a saved part is kept until it is replaced, except the blind ones, which are never changed
function aggregateReview(req, res) {
    const item = items().find(i => i.id === req.params.id);
    if (!item) return res.status(404).send('no such item');
    const done = reviews();
    const prior = done[req.params.id] || {};
    const {blind, blind_phrases: blindPhrases, evidence, follows, phrases, overall, note} = req.body;
    const EVIDENCE = criteria().evidence, FOLLOWS = criteria().follows;
    // the criteria's reasons (mostly, partly): `<criterion>_reasons`, `<criterion>_other`, checked against the sample's lists
    const reasonFields = {};
    for (const c of ['evidence', 'follows']) {
        for (const f of [`${c}_reasons`, `${c}_other`]) {
            if (req.body[f] === undefined) continue;
            const e = reasonField(req.params.id, f, req.body[f], sample().questions || {});
            if (e) return res.status(400).send(e);
            reasonFields[f] = req.body[f];
        }
    }
    const bad = (value, allowed) => value !== undefined && value !== null && !allowed.includes(value);
    if (blind !== undefined && (!blind || !DECISIONS.includes(blind.decision))) return res.status(400).send(`blind decision must be one of ${DECISIONS}`);
    if (bad(evidence, EVIDENCE)) return res.status(400).send(`evidence must be one of ${EVIDENCE}`);
    if (bad(follows, FOLLOWS)) return res.status(400).send(`follows must be one of ${FOLLOWS}`);
    if (bad(overall, OVERALL)) return res.status(400).send(`overall must be one of ${OVERALL}`);
    if (blindPhrases !== undefined) {
        if (!item.blind_phrases) return res.status(400).send('this unit has no phrases to judge blind');
        const judged = blindPhrases && blindPhrases.phrases;
        if (!judged || typeof judged !== 'object' || item.blind_phrases.some(p => !PHRASE.includes(judged[p.concern]))
            || Object.keys(judged).some(c => !item.blind_phrases.some(p => p.concern === c))) {
            return res.status(400).send(`blind_phrases must map each of the unit's phrases to one of ${PHRASE}`);
        }
    }
    if (phrases !== undefined) {
        const concerns = new Set(item.members.map(m => m.concern));
        if (typeof phrases !== 'object' || Object.entries(phrases).some(([c, v]) => !concerns.has(c) || !PHRASE.includes(v))) {
            return res.status(400).send(`phrases must map the unit's concerns to one of ${PHRASE}`);
        }
    }
    // E's output stays hidden until the blind decision of a unit shown blind first
    const blindDone = (blind && DECISIONS.includes(blind.decision)) || (prior.blind && DECISIONS.includes(prior.blind.decision));
    if (item.blind_first && !blindDone && (evidence || follows || overall || phrases)) {
        return res.status(409).send('this unit is shown blind first: save the blind decision before judging E\'s output');
    }
    const phrasesDone = blindPhrasesDone(item, prior) || (blindPhrases !== undefined && blindPhrasesDone(item, {blind_phrases: blindPhrases}));
    if (item.blind_phrases && !phrasesDone && (evidence || follows || overall || phrases)) {
        return res.status(409).send('judge this unit\'s phrases blind before judging E\'s output');
    }
    if (derivedUnit(item) && overall !== undefined && overall !== null) {
        return res.status(400).send('the verdict of this unit is derived from its phrases: send the phrases, not an overall judgment');
    }
    const next = {...prior, reviewed: new Date().toISOString()};
    if (blind !== undefined && !prior.blind) next.blind = {decision: blind.decision, note: blind.note || '', reviewed: next.reviewed};
    if (blindPhrases !== undefined && !blindPhrasesDone(item, prior)) {
        next.blind_phrases = {phrases: {...blindPhrases.phrases}, note: blindPhrases.note || '', reviewed: next.reviewed};
    }
    for (const [k, v] of Object.entries({evidence, follows, overall, ...reasonFields})) if (v !== undefined) next[k] = v;
    // a criterion answered with no reasons asked drops those given for another answer
    for (const c of ['evidence', 'follows']) {
        const reasons = ((sample().questions || {}).reasons || {})[c];
        if (reasons && !reasons.when.includes(next[c])) { delete next[`${c}_reasons`]; delete next[`${c}_other`]; }
    }
    if (phrases !== undefined) next.phrases = phrases;
    if (derivedUnit(item)) {
        const verdict = derive(item, next.phrases);
        if (verdict === undefined) delete next.overall; else next.overall = verdict;
        next.derived = true;
    }
    if (note !== undefined) next.note = note;
    done[req.params.id] = next;
    writeJson(REVIEWS, done);
    res.send(progress());
}

// the questions a purpose asks: `cites` only for a supported one
const askedOf = (p, questions) => Object.keys(questions.purpose).filter(q => q !== 'cites' || p.status === 'supported');

// a question's reasons (mostly, partly) not complete: none named, or Other without its text; null where complete
function reasonsOpen(q, a, questions) {
    const reasons = (questions.reasons || {})[q];
    if (!reasons || !reasons.when.includes(a[q])) return null;
    if (!(a[`${q}_reasons`] || []).length) return 'reasons';
    if (reasons.free && a[`${q}_reasons`].includes(reasons.free) && !String(a[`${q}_other`] || '').trim()) return 'other reason';
    return null;
}

// an answer's reason fields (`<question>_reasons`, `<question>_other`) checked against the sample's lists: an error or null
function reasonField(k, q, v, questions) {
    const base = q.replace(/_(reasons|other)$/, '');
    const reasons = (questions.reasons || {})[base];
    if (!reasons) return `${k}: ${q} is not asked`;
    if (q.endsWith('_other')) return !reasons.free ? `${k}: ${q} is not asked` : typeof v !== 'string' ? `${k} ${q} must be text` : null;
    const known = reasons.options.map(o => o.id);
    return !Array.isArray(v) || v.some(x => !known.includes(x)) ? `${k} ${q} must be a list of ${known}` : null;
}

// what keeps an expectation review from being done: the questions asked and not answered
function expectationOpen(item, review, questions) {
    const open = [];
    for (const p of item.purposes) {
        const a = (review.purposes || {})[p.key] || {};
        for (const q of askedOf(p, questions)) {
            if (!questions.purpose[q].includes(a[q])) open.push(`${p.key} ${q}`);
            else { const r = reasonsOpen(q, a, questions); if (r) open.push(`${p.key} ${q} ${r}`); }
        }
        for (const d of p.dependencies.filter(d => d.asked)) {
            const b = (review.dependencies || {})[d.key] || {};
            for (const q of Object.keys(questions.dependency)) {
                if (!questions.dependency[q].includes(b[q])) open.push(`${d.key} ${q}`);
                else { const r = reasonsOpen(q, b, questions); if (r) open.push(`${d.key} ${q} ${r}`); }
            }
        }
    }
    return open;
}

function expectationReview(req, res) {
    const item = items().find(i => i.id === req.params.id);
    if (!item) return res.status(404).send('no such item');
    const questions = sample().questions;
    const {purposes = {}, dependencies = {}, missed = [], note = '', done = false} = req.body;
    const purposeKeys = new Map(item.purposes.map(p => [p.key, p]));
    const dependencyKeys = new Set(item.purposes.flatMap(p => p.dependencies.filter(d => d.asked).map(d => d.key)));
    for (const [k, a] of Object.entries(purposes)) {
        if (!purposeKeys.has(k) || typeof a !== 'object') return res.status(400).send(`no purpose ${k} in this unit`);
        for (const [q, v] of Object.entries(a)) {
            if (q === 'better_node') { if (typeof v !== 'string') return res.status(400).send('better_node must be text'); continue; }
            if (/_(reasons|other)$/.test(q)) { const e = reasonField(k, q, v, questions); if (e) return res.status(400).send(e); continue; }
            if (q === 'overlaps') {  // the other purposes of the practice this one overlaps: [{with, relation}], optional
                const relations = questions.overlaps || [];
                if (!relations.length) return res.status(400).send(`${k}: overlaps is not asked`);
                if (!Array.isArray(v) || v.some(o => !o || o.with === k || !purposeKeys.has(o.with) || !relations.includes(o.relation))) {
                    return res.status(400).send(`${k} overlaps must be a list of {with: another purpose of the unit, relation: one of ${relations}}`);
                }
                continue;
            }
            if (!askedOf(purposeKeys.get(k), questions).includes(q)) return res.status(400).send(`${k}: ${q} is not asked`);
            if (v !== null && !questions.purpose[q].includes(v)) return res.status(400).send(`${k} ${q} must be one of ${questions.purpose[q]}`);
        }
    }
    for (const [k, b] of Object.entries(dependencies)) {
        if (!dependencyKeys.has(k) || typeof b !== 'object') return res.status(400).send(`no dependency ${k} asked in this unit`);
        for (const [q, v] of Object.entries(b)) {
            if (/_(reasons|other)$/.test(q)) { const e = reasonField(k, q, v, questions); if (e) return res.status(400).send(e); continue; }
            if (!(q in questions.dependency)) return res.status(400).send(`${k}: ${q} is not asked`);
            if (v !== null && !questions.dependency[q].includes(v)) return res.status(400).send(`${k} ${q} must be one of ${questions.dependency[q]}`);
        }
    }
    if (!Array.isArray(missed) || missed.some(m => !m || typeof m.note !== 'string' || !m.note.trim())) {
        return res.status(400).send('missed must be a list of {note, functional} with a note');
    }
    const review = {purposes, dependencies, note,
                    missed: missed.map(m => ({note: m.note.trim(), functional: !!m.functional, node: m.node || ''}))};
    const open = expectationOpen(item, review, questions);
    if (done && open.length) return res.status(400).send(`not every question is answered: ${open.join(', ')}`);
    const all = reviews();
    all[item.id] = {...review, done: !!done, reviewed: new Date().toISOString()};
    writeJson(REVIEWS, all);
    res.send(progress());
}

app.put('/api/reviews/:id', (req, res) => {
    if (EXPECT) return expectationReview(req, res);
    if (AGGREGATE) return aggregateReview(req, res);
    const {decision, note} = req.body;
    if (!DECISIONS.includes(decision)) return res.status(400).send(`decision must be one of ${DECISIONS}`);
    if (!items().some(i => i.id === req.params.id)) return res.status(404).send('no such item');
    const done = reviews();
    done[req.params.id] = {decision, note: note || '', reviewed: new Date().toISOString()};
    writeJson(REVIEWS, done);
    res.send(progress());
});

app.delete('/api/reviews/:id', (req, res) => {
    const done = reviews();
    // a blind decision or blind phrases, once saved, are never removed: the unit has been seen with E's output since
    const prior = done[req.params.id];
    const kept = AGGREGATE && prior ? Object.fromEntries(['blind', 'blind_phrases'].filter(k => prior[k]).map(k => [k, prior[k]])) : {};
    if (Object.keys(kept).length) done[req.params.id] = kept;
    else delete done[req.params.id];
    writeJson(REVIEWS, done);
    res.send(progress());
});

if (require.main === module) {
    // on this computer only: the reviews are not served to the network
    app.listen(PORT, '127.0.0.1', () => console.log(`calibration review: http://localhost:${PORT} (sample in ${FOLDER})`));
}

module.exports = app;
