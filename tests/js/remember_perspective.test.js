/**
 * @title 視点の記憶 (remember-perspective) のユニットテスト
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const { createBrowserContext, loadScripts, run } = require('./helpers/browser_env');

const ACCOUNTS = [
    { seat: 0, nickname: 'TonPlayer' },
    { seat: 1, nickname: 'NanPlayer' },
    { seat: 2, nickname: 'Me' },
    { seat: 3, nickname: 'PeiPlayer' },
];

/** loadGame が取得する牌譜 (配牌のみの最小構成) */
function makeRecord(accounts) {
    return {
        head: { uuid: 'u1', accounts },
        detail_records: {
            actions: [{
                type: 1,
                result: {
                    class_name: 'RecordNewRound',
                    data: {
                        chang: 0, ju: 0, ben: 0, scores: [25000, 25000, 25000, 25000],
                        tiles0: ['1m'], tiles1: ['2m'], tiles2: ['3m'], tiles3: ['4m'],
                    },
                },
            }],
        },
    };
}

function setup({ stored = null, accounts = ACCOUNTS } = {}) {
    const ctx = createBrowserContext();
    if (stored) ctx._storage.set('mjcoach.myNickname', stored);
    ctx.location.search = '?uuid=u1';
    ctx.fetch = async (url) => {
        if (String(url).startsWith('/api/record?')) return { ok: true, json: async () => makeRecord(accounts) };
        return { ok: false, json: async () => ({}) };
    };
    loadScripts(ctx, ['server/static/js/simulator_v2_utils.js', 'server/static/js/simulator_v2_main.js']);
    // 描画は対象外
    run(ctx, 'renderBoard = () => {}; updatePromptPreview = () => {}; fitMahjongTable = () => {};');
    return ctx;
}

test('記憶が無ければ従来どおり席0で開く', async () => {
    const ctx = setup();
    await run(ctx, 'loadGame()');
    assert.equal(run(ctx, 'perspectiveSeat'), 0);
});

test('記憶したニックネームが参加していれば、その席を初期視点にする', async () => {
    const ctx = setup({ stored: 'Me' });
    await run(ctx, 'loadGame()');
    assert.equal(run(ctx, 'perspectiveSeat'), 2);
    assert.equal(ctx._elements.pers2.checked, true);
});

test('記憶したニックネームが参加していない牌譜では席0のまま', async () => {
    const ctx = setup({ stored: 'SomeoneElse' });
    await run(ctx, 'loadGame()');
    assert.equal(run(ctx, 'perspectiveSeat'), 0);
});

test('視点を変えるとそのプレイヤーのニックネームを記憶する', async () => {
    const ctx = setup();
    await run(ctx, 'loadGame()');
    run(ctx, 'changePerspective(3)');
    assert.equal(run(ctx, 'perspectiveSeat'), 3);
    assert.equal(ctx._storage.get('mjcoach.myNickname'), 'PeiPlayer');
});

test('アカウント情報が無い席を選んでも記憶は変えない', async () => {
    const ctx = setup({ stored: 'Me', accounts: ACCOUNTS.filter(a => a.seat !== 1) });
    await run(ctx, 'loadGame()');
    run(ctx, 'changePerspective(1)');
    assert.equal(ctx._storage.get('mjcoach.myNickname'), 'Me');
});
