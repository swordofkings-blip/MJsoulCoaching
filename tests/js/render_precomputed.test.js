/**
 * @title _renderFromPrecomputed のユニットテスト
 * @description 事前計算された推奨打牌は「次に打牌するのが視点の席」のときだけ表示されること
 *              (手番でない局面で他家の推奨手が自分の推奨として表示されないこと) を確認する。
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const { createBrowserContext, loadScripts, run } = require('./helpers/browser_env');

function setup() {
    const ctx = createBrowserContext();
    loadScripts(ctx, ['server/static/js/simulator_v2_utils.js', 'server/static/js/simulator_v2_main.js']);
    // 描画系は呼ばれたかどうかだけを記録する
    ctx.__rendered = [];
    run(ctx, `
        renderBotCoachUI = (data) => window.__rendered.push(data.recommended);
        renderReasonForTile = () => {};
        highlightRecommendedTile = () => {};
    `);
    // 東1局: 配牌 → 席0 が打牌 → 席1 がツモ → 席1 が打牌
    run(ctx, `
        rawActionsList = [
            { result: { class_name: 'RecordNewRound', data: { chang: 0, ju: 0 } } },
            { result: { class_name: 'RecordDiscardTile', data: { seat: 0, tile: '1z' } } },
            { result: { class_name: 'RecordDealTile', data: { seat: 1, tile: '5m' } } },
            { result: { class_name: 'RecordDiscardTile', data: { seat: 1, tile: '9p' } } },
        ];
        timelineSteps = [0, 2];
        window.__rawIdxToActionIdx = { 0: 0, 1: 1, 2: 2, 3: 3 };
        window.__precomputedActions = {
            '1': { recommended: '1z', evaluations: [] },
            '3': { recommended: '9p', evaluations: [] },
        };
    `);
    return ctx;
}

test('次の打牌者が視点の席なら事前計算の推奨を表示する', () => {
    const ctx = setup();
    run(ctx, 'perspectiveSeat = 0; currentActionIndex = 0;');
    assert.equal(run(ctx, '_renderFromPrecomputed()'), true);
    assert.deepEqual([...ctx.__rendered], ['1z']);
});

test('次の打牌者が他家なら表示しない (他家の推奨手を自分の推奨として出さない)', () => {
    const ctx = setup();
    run(ctx, 'perspectiveSeat = 2; currentActionIndex = 0;');
    assert.equal(run(ctx, '_renderFromPrecomputed()'), false);
    assert.equal(ctx.__rendered.length, 0);
});

test('ツモ後の局面でもツモった本人の視点でだけ表示する', () => {
    const ctx = setup();
    run(ctx, 'perspectiveSeat = 1; currentActionIndex = 1;');
    assert.equal(run(ctx, '_renderFromPrecomputed()'), true);
    assert.deepEqual([...ctx.__rendered], ['9p']);

    run(ctx, 'perspectiveSeat = 0;');
    assert.equal(run(ctx, '_renderFromPrecomputed()'), false);
});

test('次のアクションが無い (局の最後) 場合は表示しない', () => {
    const ctx = setup();
    run(ctx, 'perspectiveSeat = 1; timelineSteps = [0, 3]; currentActionIndex = 1;');
    assert.equal(run(ctx, '_renderFromPrecomputed()'), false);
});
