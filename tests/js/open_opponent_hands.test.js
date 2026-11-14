/**
 * @title 相手の手牌表示 (open-opponent-hands) のユニットテスト
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createBrowserContext, loadScripts, run, ROOT } = require('./helpers/browser_env');

// 牌の絵柄機能 (tile_faces.js) とマージされた後も動くよう、存在すれば読み込む
const SCRIPTS = ['server/static/js/simulator_v2_utils.js', 'server/static/js/simulator_v2_main.js'];
if (fs.existsSync(path.join(ROOT, 'server/static/js/tile_faces.js'))) SCRIPTS.unshift('server/static/js/tile_faces.js');

function setup({ stored = null } = {}) {
    const ctx = createBrowserContext();
    if (stored !== null) ctx._storage.set('mjcoach.showOpponentHands', stored);
    loadScripts(ctx, SCRIPTS);
    run(ctx, `
        requestBotCoachEvaluation = () => {};
        requestBotCoachMeldEvaluation = () => {};
        engine.hands = [['1m', '2m'], ['3p', '4p'], ['5s', '6s'], ['1z', '2z']];
        engine.lastTsumo = [null, '4p', null, null];
    `);
    return ctx;
}

/** 各席の手牌エリアに描画された牌 (ツモ前のすきまを除く) */
function handTiles(ctx, seat) {
    return ctx._elements[`hand${seat}`].children.filter(el => el.className !== 'tsumo-gap');
}

const isBack = el => el.className.includes('tile-back');

test('既定では相手の手牌は裏向き', () => {
    const ctx = setup();
    assert.equal(run(ctx, 'showOpponentHands'), false);
    run(ctx, 'perspectiveSeat = 0; renderBoard();');
    assert.ok(handTiles(ctx, 0).every(el => !isBack(el)), '自分の手牌は表');
    for (const seat of [1, 2, 3]) {
        assert.ok(handTiles(ctx, seat).every(isBack), `席${seat} は裏`);
    }
});

test('ON にすると相手 3 人の手牌 (ツモ牌含む) を表向きで描画する', () => {
    const ctx = setup();
    run(ctx, 'perspectiveSeat = 0; toggleOpponentHands(true);');
    for (const seat of [1, 2, 3]) {
        const tiles = handTiles(ctx, seat);
        assert.ok(tiles.length > 0);
        assert.ok(tiles.every(el => !isBack(el)), `席${seat} が表`);
    }
    // 席1 はツモ牌 4筒 を手牌の右に分けて表示する
    // (牌の絵柄機能がある場合は data-tile、無い場合は牌名の文字で判定する)
    const seat1 = handTiles(ctx, 1);
    const last = seat1[seat1.length - 1];
    assert.ok(last.dataset.tile === '4p' || last.innerText === getText(ctx, '4p'));
});

test('設定は localStorage に保存し、次回読み込み時に引き継ぐ', () => {
    const ctx = setup();
    run(ctx, 'toggleOpponentHands(true)');
    assert.equal(ctx._storage.get('mjcoach.showOpponentHands'), '1');
    run(ctx, 'toggleOpponentHands(false)');
    assert.equal(ctx._storage.get('mjcoach.showOpponentHands'), '0');

    const reloaded = setup({ stored: '1' });
    assert.equal(run(reloaded, 'showOpponentHands'), true);
});

function getText(ctx, tile) {
    return run(ctx, `getTileText(${JSON.stringify(tile)})`);
}
