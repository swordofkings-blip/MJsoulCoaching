/**
 * @title ブラウザ用スクリプトのテスト環境
 * @description server/static/js/ のスクリプト (ES モジュールではない通常のスクリプト) を
 *              node:vm のコンテキストに読み込み、最小限の DOM スタブ上でテストできるようにする。
 *              トップレベルの let/const は同じコンテキスト内の後続スクリプトから参照できるため、
 *              run(ctx, '式') で内部状態を読み書きできる。
 */
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..', '..', '..');

function makeClassList() {
    const set = new Set();
    return {
        add: (...c) => c.forEach(x => set.add(x)),
        remove: (...c) => c.forEach(x => set.delete(x)),
        contains: c => set.has(c),
        toggle: (c, force) => {
            const on = force === undefined ? !set.has(c) : !!force;
            if (on) set.add(c); else set.delete(c);
            return on;
        },
        toString: () => [...set].join(' '),
    };
}

function makeElement(id = '') {
    const el = {
        id,
        style: {},
        dataset: {},
        children: [],
        classList: makeClassList(),
        innerHTML: '',
        innerText: '',
        textContent: '',
        title: '',
        value: '',
        checked: false,
        appendChild(child) { this.children.push(child); return child; },
        setAttribute() {},
        addEventListener() {},
        querySelector() { return makeElement(); },
        querySelectorAll() { return []; },
    };
    return el;
}

/**
 * @title テスト用のブラウザ風コンテキストを作る
 * @returns {object} vm コンテキスト (window === グローバル)。_elements / _storage でスタブの中身を参照できる
 */
function createBrowserContext() {
    const elements = {};
    const storage = new Map();
    const ctx = {
        console,
        setTimeout, clearTimeout, setInterval, clearInterval,
        URL, URLSearchParams,
        requestAnimationFrame: fn => fn(),
        ResizeObserver: class { observe() {} },
        alert() {},
        fetch: async () => ({ ok: false, json: async () => ({}) }),
        localStorage: {
            getItem: k => (storage.has(k) ? storage.get(k) : null),
            setItem: (k, v) => storage.set(k, String(v)),
            removeItem: k => storage.delete(k),
        },
        document: {
            getElementById: id => elements[id] || (elements[id] = makeElement(id)),
            // Why: simulator_v2_main.js は .simulator-pane が見つかるまで setTimeout で再試行するため、
            //      常に要素を返してタイマーが残らないようにする
            querySelector: () => makeElement(),
            querySelectorAll: () => [],
            createElement: () => makeElement(),
            addEventListener() {},
            head: makeElement('head'),
        },
        _elements: elements,
        _storage: storage,
    };
    ctx.window = ctx;
    ctx.location = { search: '', href: '' };
    ctx.window.addEventListener = () => {};
    return vm.createContext(ctx);
}

/** リポジトリ直下からの相対パスでスクリプトを読み込む */
function loadScripts(ctx, relPaths) {
    for (const rel of relPaths) {
        const file = path.join(ROOT, rel);
        vm.runInContext(fs.readFileSync(file, 'utf8'), ctx, { filename: file });
    }
    return ctx;
}

/** コンテキスト内で式・文を実行して結果を返す (トップレベルの let/const も参照できる) */
function run(ctx, code) {
    return vm.runInContext(code, ctx);
}

module.exports = { createBrowserContext, loadScripts, run, makeElement, ROOT };
