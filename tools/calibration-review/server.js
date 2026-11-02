// Blind review of a calibration sample (skuld calibrate draw): serves the sample's items and the collections'
// documents, never E's outcomes (key.json), and stores each decision in the sample's reviews.json. A prior review
// (prior-review.json: another reviewer's decision and note per item) is shown with its item where there is one.
// Run with `npm start -- <calibration folder>` (or CALIBRATION=<folder>), then open http://localhost:3001.

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

if (!fs.existsSync(SAMPLE)) {
    console.error(`no sample.json in ${FOLDER}: draw one with \`skuld calibrate draw\``);
    process.exit(1);
}

function readJson(file, fallback) {
    try {
        return JSON.parse(fs.readFileSync(file, 'utf-8'));
    } catch (e) {
        if (fallback !== undefined) return fallback;
        throw e;
    }
}

// write to a temporary file first, so that a crash never leaves half a file behind
function writeJson(file, data) {
    fs.writeFileSync(file + '.tmp', JSON.stringify(data, null, 1));
    fs.renameSync(file + '.tmp', file);
}

const items = () => readJson(SAMPLE).items;
const reviews = () => readJson(REVIEWS, {});

// an item's prior review, with who made it and when, or null
function priorReview(id) {
    const prior = readJson(PRIOR, null);
    const entry = prior && prior.items && prior.items[id];
    if (!entry || !DECISIONS.includes(entry.decision)) return null;
    return {decision: entry.decision, note: entry.note || '', reviewer: prior.reviewer || null, reviewed: prior.reviewed || null};
}

function progress() {
    const all = items();
    const done = reviews();
    const counts = Object.fromEntries(DECISIONS.map(d => [d, 0]));
    Object.values(done).forEach(r => counts[r.decision]++);
    return {calibration: path.basename(FOLDER), total: all.length, reviewed: Object.keys(done).length, counts};
}

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));
app.use('/vendor/vue.js', express.static(path.join(__dirname, 'node_modules/vue/dist/vue.esm-browser.prod.js')));
app.use('/vendor/bootstrap.css', express.static(path.join(__dirname, 'node_modules/bootstrap/dist/css/bootstrap.min.css')));
app.use('/vendor/icons', express.static(path.join(__dirname, 'node_modules/bootstrap-icons/font')));
// only the collections' documents: E's outcomes stay in key.json, which is never served
app.use('/documents', express.static(path.join(FOLDER, 'documents')));

app.get('/api/progress', (req, res) => res.send(progress()));

app.get('/api/resume', (req, res) => res.send(readJson(POSITION, {index: 0})));

app.get('/api/items/:index', (req, res) => {
    const all = items();
    const index = Number(req.params.index);
    const item = all[index];
    if (!item) return res.status(404).send('no such item');
    writeJson(POSITION, {index});
    res.send({...item, index, total: all.length, review: reviews()[item.id] || null, prior_review: priorReview(item.id)});
});

// the first item without a decision after the given index (or from the start)
app.get('/api/next-open', (req, res) => {
    const all = items();
    const done = reviews();
    const after = Number(req.query.after ?? -1);
    const open = all.map((item, index) => ({item, index})).filter(x => !(x.item.id in done));
    const next = open.find(x => x.index > after) || open[0];
    res.send({index: next ? next.index : null});
});

app.put('/api/reviews/:id', (req, res) => {
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
    delete done[req.params.id];
    writeJson(REVIEWS, done);
    res.send(progress());
});

if (require.main === module) {
    app.listen(PORT, () => console.log(`calibration review: http://localhost:${PORT} (sample in ${FOLDER})`));
}

module.exports = app;
