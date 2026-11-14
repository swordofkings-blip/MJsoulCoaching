/**
 * @title tile_faces.js (牌の絵柄 SVG) のユニットテスト
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const { createBrowserContext, loadScripts, run, makeElement } = require('./helpers/browser_env');

const ALL_TILES = [
    ...['m', 'p', 's'].flatMap(s => ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'].map(n => n + s)),
    '1z', '2z', '3z', '4z', '5z', '6z', '7z',
];

function setup() {
    const ctx = createBrowserContext();
    loadScripts(ctx, ['server/static/js/tile_faces.js', 'server/static/js/simulator_v2_utils.js']);
    return ctx;
}

test('全 37 種 (赤5含む) の牌で縦向きの SVG を生成する', () => {
    const ctx = setup();
    for (const t of ALL_TILES) {
        const svg = run(ctx, `tileFaceSvg(${JSON.stringify(t)})`);
        assert.match(svg, /^<svg class="tile-face-svg" viewBox="0 0 60 80"/, t);
        assert.ok(svg.length > 100, `${t} の絵柄が空`);
    }
});

test('絵柄は牌ごとに異なる', () => {
    const ctx = setup();
    const svgs = ALL_TILES.map(t => run(ctx, `tileFaceSvg(${JSON.stringify(t)})`));
    assert.equal(new Set(svgs).size, ALL_TILES.length);
});

test('萬子は漢数字と萬、字牌は漢字で描く', () => {
    const ctx = setup();
    assert.match(run(ctx, `tileFaceSvg('3m')`), />三<.*>萬</s);
    assert.match(run(ctx, `tileFaceSvg('5m')`), />伍</);
    assert.match(run(ctx, `tileFaceSvg('1z')`), />東</);
    assert.match(run(ctx, `tileFaceSvg('7z')`), />中</);
});

test('赤5は通常の5と違い、赤色だけで描く', () => {
    const ctx = setup();
    const red = run(ctx, 'TILE_FACE_COLORS.red');
    for (const suit of ['p', 's']) {
        const aka = run(ctx, `tileFaceSvg('0${suit}')`);
        const normal = run(ctx, `tileFaceSvg('5${suit}')`);
        assert.notEqual(aka, normal);
        const colors = new Set([...aka.matchAll(/(?:fill|stroke)="(#[0-9a-f]{6})"/g)].map(m => m[1]));
        assert.deepEqual([...colors], [red], `赤5${suit} に赤以外の色がある`);
    }
    // 赤5萬は数字も赤
    assert.match(run(ctx, `tileFaceSvg('0m')`), new RegExp(`fill="${red}"[^>]*>伍<`));
});

test('横向きは viewBox を入れ替えて回転させる', () => {
    const ctx = setup();
    const svg = run(ctx, `tileFaceSvg('5p', true)`);
    assert.match(svg, /viewBox="0 0 80 60"/);
    assert.match(svg, /rotate\(-90\)/);
});

test('不正な牌コードは空文字を返す', () => {
    const ctx = setup();
    for (const t of ['', null, 'x', '8z', '0z', 'am']) {
        assert.equal(run(ctx, `tileFaceSvg(${JSON.stringify(t)})`), '', String(t));
    }
});

test('setTileFace は data-tile・title・クラスを設定する', () => {
    const ctx = setup();
    ctx.__el = makeElement();
    run(ctx, `setTileFace(window.__el, '0p')`);
    assert.equal(ctx.__el.dataset.tile, '0p');
    assert.equal(ctx.__el.title, '赤5筒');
    assert.ok(ctx.__el.classList.contains('tile-face'));
    assert.match(ctx.__el.innerHTML, /^<svg/);
});

test('setTileFace は絵柄が無い牌では牌名の文字を表示する', () => {
    const ctx = setup();
    ctx.__el = makeElement();
    run(ctx, `setTileFace(window.__el, '?')`);
    assert.equal(ctx.__el.innerText, '?');
    assert.ok(!ctx.__el.classList.contains('tile-face'));
});

test('tileFaceHtml は data-tile 付きの小さな牌を返す', () => {
    const ctx = setup();
    const html = run(ctx, `tileFaceHtml('7z', 'extra')`);
    assert.match(html, /class="tile tile-face tile-mini extra"/);
    assert.match(html, /data-tile="7z"/);
    assert.match(html, /title="中"/);
});

test('推奨牌ハイライトは innerText ではなく data-tile で照合する', () => {
    const ctx = setup();
    const tile = (code) => {
        const el = makeElement();
        el.classList.add('tile');
        el.dataset.tile = code;
        el.innerText = '';  // SVG 描画なので文字は持たない
        return el;
    };
    const gap = makeElement();
    gap.classList.add('tsumo-gap');
    const hand = [tile('1m'), tile('5p'), tile('9s'), gap, tile('5p')];
    ctx._elements.hand0 = { querySelectorAll: () => hand };
    run(ctx, 'var perspectiveSeat = 0;');

    run(ctx, `highlightRecommendedTile('5p', ['9s'], false)`);
    assert.ok(hand[1].classList.contains('tile-recommended'), '手出しの 5筒 をハイライト');
    assert.ok(!hand[4].classList.contains('tile-recommended'), 'ツモ牌はハイライトしない');
    assert.ok(hand[2].classList.contains('tile-near'), '同等候補');

    run(ctx, `highlightRecommendedTile('5p', [], true)`);
    assert.ok(hand[4].classList.contains('tile-recommended'), 'ツモ切り推奨ならツモ牌');
});
