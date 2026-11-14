/**
 * @title 半荘総評 (simulator_v2_review.js) のユニットテスト
 * @description 合成した牌譜と事前計算データで、一致率・ミスの判定・文脈による再判定
 *              (撤退準備・降り・差し込み)・全体評価を確認する。
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const { createBrowserContext, loadScripts, run } = require('./helpers/browser_env');

const ME = 2;
const BALANCE_TIERS = ['向聴数', '安牌温存', '良形受入', '愚形受入', 'ドラ損失期待値', '戦術ランク', '安全度'];

/**
 * 牌譜と事前計算データ (eval.json の actions) を組み立てるビルダー
 */
class RecordBuilder {
    constructor() {
        this.actions = [];
        this.pre = {};
    }

    newRound(chang, ju, ben, scores) {
        this.actions.push({ type: 1, result: { class_name: 'RecordNewRound', data: { chang, ju, ben, scores } } });
        return this;
    }

    /**
     * 打牌を 1 つ追加する。opts.recommended を省略すると「推奨通り」の打牌になる
     * opts: { recommended, recShanten, actShanten, actSafety, recSafety, reason, value, speed, threat, mode }
     */
    discard(seat, tile, opts = {}) {
        const idx = this.actions.length;
        this.actions.push({ type: 1, result: { class_name: 'RecordDiscardTile', data: { seat, tile } } });
        if (seat !== ME && !opts.force) return this;
        const rec = opts.recommended || tile;
        const ev = (t, shanten, safety, score, reason) => ({
            tile: t, score, shanten, reason,
            tier_names: BALANCE_TIERS,
            tuple_values: [shanten, 0, 0, 0, 0, 0, -safety],
        });
        const evaluations = [ev(rec, opts.recShanten ?? 1, opts.recSafety ?? 500, 1000, '')];
        if (rec !== tile) {
            evaluations.push(ev('9s', 9, 0, 990, ''));  // 中間の候補 (順位計算用)
            evaluations.push(ev(tile, opts.actShanten ?? (opts.recShanten ?? 1) + 1, opts.actSafety ?? 500, 980,
                opts.reason || `①向聴数: ${rec} を切ったほうが前進。`));
        }
        this.pre[String(idx)] = {
            recommended: rec, near_tiles: [], evaluations, is_riichi_active: false,
            strategy_details: {
                v2_mode_jp: opts.mode || 'バランス',
                v2_hand_value: opts.value ?? 0.5,
                v2_hand_speed: opts.speed ?? 0.5,
                max_threat: opts.threat ?? 0.1,
            },
        };
        return this;
    }

    /** seat の打牌を n 回 (推奨通り) 追加して巡目を進める */
    fillTurns(seat, n) {
        for (let i = 0; i < n; i++) this.discard(seat, '1z');
        return this;
    }

    hule(winnerSeat, zimo, oldScores, deltaScores) {
        const scores = oldScores.map((s, i) => s + deltaScores[i]);
        this.actions.push({
            type: 1,
            result: { class_name: 'RecordHule', data: { hules: [{ seat: winnerSeat, zimo }], oldScores, deltaScores, scores } },
        });
        return this;
    }

    noTile(deltaScores = [0, 0, 0, 0]) {
        this.actions.push({ type: 1, result: { class_name: 'RecordNoTile', data: { scores: [{ deltaScores }] } } });
        return this;
    }
}

function setup(builder, { finalPoints = [20000, 25000, 35000, 20000], grades = {} } = {}) {
    const ctx = createBrowserContext();
    loadScripts(ctx, [
        'server/static/js/simulator_v2_utils.js',
        'server/static/js/simulator_v2_main.js',
        'server/static/js/simulator_v2_review.js',
    ]);
    ctx.__data = {
        gameData: {
            head: {
                accounts: [0, 1, 2, 3].map(seat => ({ seat, nickname: `P${seat}` })),
                result: { players: finalPoints.map((p, seat) => ({ seat, partPoint1: p })) },
            },
            detail_records: { actions: builder.actions },
        },
        pre: builder.pre,
        grades,
    };
    run(ctx, `
        gameData = window.__data.gameData;
        window.__precomputedActions = window.__data.pre;
        window.__evalGrades = window.__data.grades;
    `);
    return ctx;
}

const review = (ctx, seat = ME) => run(ctx, `computeHanchanReview(${seat})`);

test('事前計算データが無ければ null', () => {
    const ctx = setup(new RecordBuilder().newRound(0, 0, 0, [25000, 25000, 25000, 25000]));
    run(ctx, 'window.__precomputedActions = {}');
    assert.equal(review(ctx), null);
});

test('AI 推奨との一致率を数える (他家の打牌は対象外)', () => {
    const b = new RecordBuilder().newRound(0, 0, 0, [25000, 25000, 25000, 25000])
        .discard(ME, '1z').discard(ME, '2z').discard(0, '3z')
        .discard(ME, '5m', { recommended: '9m', value: 0.8, speed: 0.8 })
        .noTile();
    const rv = review(setup(b));
    assert.equal(rv.judged, 3);
    assert.equal(rv.matchCount, 2);
    assert.equal(Math.round(rv.matchRate * 100), 67);
});

test('赤5と通常の5は同じ牌として一致判定する', () => {
    const b = new RecordBuilder().newRound(0, 0, 0, [25000, 25000, 25000, 25000]);
    b.discard(ME, '0p', { force: true });
    b.pre['1'].recommended = '5p';
    b.pre['1'].evaluations[0].tile = '5p';
    const rv = review(setup(b));
    assert.equal(rv.matchCount, 1);
});

test('手が良い局面で向聴数を落とす打牌は「向聴ロス」のミス', () => {
    const b = new RecordBuilder().newRound(0, 0, 0, [25000, 25000, 25000, 25000])
        .fillTurns(ME, 8)
        .discard(ME, '5m', { recommended: '1z', recShanten: 1, value: 0.8, speed: 0.8 })
        .noTile();
    const rv = review(setup(b));
    const dec = rv.decisions.find(d => !d.isMatch);
    assert.equal(dec.category, 'shanten');
    assert.equal(dec.good, null);
    assert.equal(rv.worst.length, 1);
    assert.equal(rv.catCounts.shanten, 1);
});

test('中盤以降も和了が遠く安い手で、安全牌を抱えて手を崩すのは「撤退準備」として妥当', () => {
    const b = new RecordBuilder().newRound(0, 0, 0, [25000, 25000, 25000, 25000])
        .fillTurns(ME, 7)
        // 8 巡目、推奨通りでも 2 向聴、打点低。AI は西 (安全度 900) を切りたいが、5萬 (安全度 300) を切って西を残した
        .discard(ME, '5m', { recommended: '3z', recShanten: 2, recSafety: 900, actSafety: 300, value: 0.3, speed: 0.2 })
        .noTile();
    const rv = review(setup(b));
    const dec = rv.decisions.find(d => !d.isMatch);
    assert.equal(dec.good.type, 'retreat');
    assert.equal(rv.worst.length, 0, 'ミス一覧には載らない');
    assert.equal(rv.catCounts.shanten, undefined, 'ミスの内訳にも数えない');
    assert.equal(rv.goodDeviationCount, 1);
    assert.ok(rv.adjustedRate > rv.matchRate);
});

test('序盤 (巡目が浅い) の手崩しは撤退とみなさない', () => {
    const b = new RecordBuilder().newRound(0, 0, 0, [25000, 25000, 25000, 25000])
        .fillTurns(ME, 2)
        .discard(ME, '5m', { recommended: '3z', recShanten: 2, recSafety: 900, actSafety: 300, value: 0.3, speed: 0.2 })
        .noTile();
    const dec = review(setup(b)).decisions.find(d => !d.isMatch);
    assert.equal(dec.good, null);
});

test('残した牌が安全牌でなければ撤退とみなさない', () => {
    const b = new RecordBuilder().newRound(0, 0, 0, [25000, 25000, 25000, 25000])
        .fillTurns(ME, 7)
        // AI が切りたかった 5筒 (安全度 600) は安全牌とは言えない
        .discard(ME, '4s', { recommended: '5p', recShanten: 2, recSafety: 600, actSafety: 300, value: 0.3, speed: 0.2 })
        .noTile();
    const dec = review(setup(b)).decisions.find(d => !d.isMatch);
    assert.equal(dec.good, null);
});

test('オーラスのトップ目なら巡目が浅くても撤退として妥当', () => {
    const b = new RecordBuilder()
        .newRound(1, 3, 0, [20000, 20000, 40000, 20000])  // 南4局、自分がトップ
        .fillTurns(ME, 1)
        .discard(ME, '5m', { recommended: '3z', recShanten: 3, recSafety: 900, actSafety: 300, value: 0.3, speed: 0.2 })
        .noTile();
    const dec = review(setup(b)).decisions.find(d => !d.isMatch);
    assert.equal(dec.good.type, 'retreat');
    assert.match(dec.good.text, /オーラスのトップ目/);
});

test('他家の攻撃に対し、遠い手で推奨より安全な牌を切るのは「降り判断」として妥当', () => {
    const b = new RecordBuilder().newRound(0, 0, 0, [25000, 25000, 25000, 25000])
        .fillTurns(ME, 8)
        .discard(ME, '1z', { recommended: '5m', recShanten: 2, recSafety: 200, actSafety: 1000, value: 0.3, speed: 0.2, threat: 0.7 })
        .noTile();
    const dec = review(setup(b)).decisions.find(d => !d.isMatch);
    assert.equal(dec.good.type, 'fold');
});

test('AI 推奨と違う牌での放銃は「致命的」として最上位に載る', () => {
    const b = new RecordBuilder().newRound(0, 0, 0, [25000, 25000, 25000, 25000])
        .fillTurns(ME, 3)
        .discard(ME, '9m', { recommended: '8m', value: 0.8, speed: 0.8 })  // 小さなミス
        .noTile()
        .newRound(0, 1, 0, [25000, 25000, 25000, 25000])
        .fillTurns(ME, 9)
        .discard(ME, '5s', { recommended: '1z', recShanten: 1, value: 0.3, threat: 0.7 })
        .hule(0, false, [25000, 25000, 25000, 25000], [8000, 0, -8000, 0]);
    const rv = review(setup(b));
    assert.equal(rv.dealIns.length, 1);
    assert.equal(rv.dealIns[0].isSashikomi, false);
    assert.equal(rv.worst[0].actual, '5s');
    assert.deepEqual({ ...run(setup(b), `_severityLabel(computeHanchanReview(${ME}).worst[0])`) }, { text: '致命的', cls: 'sev-fatal' });
    assert.equal(rv.verdict.avoidableCount, 1);
});

test('オーラスで順位を落とさずに終局させる放銃は「差し込み」として妥当', () => {
    const before = [20000, 30000, 40000, 10000];
    const b = new RecordBuilder()
        .newRound(1, 3, 0, before)
        .fillTurns(ME, 5)
        .discard(ME, '6p', { recommended: '4z', value: 0.3 })
        .hule(1, false, before, [0, 4000, -4000, 0]);  // 2着に 4000 放銃しても自分は 1 位のまま
    const rv = review(setup(b, { finalPoints: [20000, 34000, 36000, 10000] }));
    assert.equal(rv.dealIns[0].isSashikomi, true);
    const dec = rv.decisions.find(d => d.dealIn);
    assert.equal(dec.good.type, 'sashikomi');
    assert.equal(rv.worst.length, 0);
    assert.equal(rv.verdict.avoidableCount, 0);
});

test('オーラスでも順位が落ちる放銃は差し込みではない', () => {
    const before = [20000, 36000, 40000, 4000];
    const b = new RecordBuilder()
        .newRound(1, 3, 0, before)
        .fillTurns(ME, 5)
        .discard(ME, '6p', { recommended: '4z', value: 0.3 })
        .hule(1, false, before, [0, 8000, -8000, 0]);  // 逆転されて 2 位に落ちる
    const rv = review(setup(b, { finalPoints: [20000, 44000, 32000, 4000] }));
    assert.equal(rv.dealIns[0].isSashikomi, false);
});

test('見直したい打牌は 1 局につき最悪の 1 打だけ載せる', () => {
    const b = new RecordBuilder().newRound(0, 0, 0, [25000, 25000, 25000, 25000]).fillTurns(ME, 8);
    for (let i = 0; i < 3; i++) b.discard(ME, '5m', { recommended: '1z', value: 0.8, speed: 0.8 });
    b.noTile();
    const rv = review(setup(b));
    assert.equal(rv.worst.length, 1);
    assert.equal(rv.worst[0].othersInRound, 2);
});

test('和了・放銃・局ごとの収支を集計する', () => {
    const b = new RecordBuilder()
        .newRound(0, 0, 0, [25000, 25000, 25000, 25000]).fillTurns(ME, 3)
        .hule(ME, true, [25000, 25000, 25000, 25000], [-1000, -1000, 3000, -1000])
        .newRound(0, 1, 0, [24000, 24000, 28000, 24000]).fillTurns(ME, 3)
        .noTile([1000, 1000, -3000, 1000]);
    const rv = review(setup(b));
    // (vm 内で作られた配列なので、通常の配列にコピーしてから比較する)
    assert.deepEqual([...rv.rounds.map(r => r.delta)], [3000, -3000]);
    assert.equal(rv.wins.length, 1);
    assert.equal(rv.wins[0].points, 3000);
});

test('_rankOf は点数順 (同点は席順) で順位を返す', () => {
    const ctx = setup(new RecordBuilder());
    assert.equal(run(ctx, '_rankOf([30000, 20000, 40000, 10000], 2)'), 1);
    assert.equal(run(ctx, '_rankOf([30000, 20000, 40000, 10000], 3)'), 4);
    assert.equal(run(ctx, '_rankOf([25000, 25000, 25000, 25000], 0)'), 1);
    assert.equal(run(ctx, '_rankOf([25000, 25000, 25000, 25000], 3)'), 4);
    assert.equal(run(ctx, '_rankOf(null, 0)'), null);
});

test('_tileSafety は評価タプルの安全度 (符号反転) を返す', () => {
    const ctx = setup(new RecordBuilder());
    assert.equal(run(ctx, `_tileSafety({ tier_names: ${JSON.stringify(BALANCE_TIERS)}, tuple_values: [1, 0, 0, 0, 0, 0, -850] })`), 850);
    assert.equal(run(ctx, `_tileSafety({ tier_names: ['向聴数'], tuple_values: [1] })`), null);
    assert.equal(run(ctx, '_tileSafety(null)'), null);
});

test('全体評価: 一致率が高くミスが無ければ「上手に打てている」、低く放銃が多ければ「課題が多い」', () => {
    const ctx = setup(new RecordBuilder());
    const verdict = (rv) => {
        ctx.__rv = rv;
        return run(ctx, '_computeVerdict(window.__rv)');
    };
    const base = { decisions: [], dealIns: [], catCounts: {}, goodCounts: {}, wins: [], rounds: [{}, {}, {}, {}] };

    const great = verdict({ ...base, adjustedRate: 0.75, finalRank: 1 });
    assert.equal(great.level, '上手に打てている');
    assert.ok(great.score >= 75);

    const decisions = [{ actionIdx: 1, isMatch: false }, { actionIdx: 2, isMatch: false }, { actionIdx: 3, isMatch: false }];
    const dealIns = decisions.map(d => ({ actionIdx: d.actionIdx, loss: 8000, isSashikomi: false }));
    const bad = verdict({ ...base, adjustedRate: 0.4, finalRank: 4, decisions, dealIns, catCounts: { danger: 10 } });
    assert.equal(bad.level, '課題が多い');
    assert.equal(bad.avoidableCount, 3);
    assert.ok(bad.weaknesses.some(w => w.includes('放銃が 3回')));
});

test('タイムライン位置は打牌の直前の局面を指す', () => {
    const ctx = setup(new RecordBuilder());
    run(ctx, `
        timelineSteps = [0, 2, 4];
        window.__actionIdxToRawIdx = { 10: 3, 11: 5 };
    `);
    assert.equal(run(ctx, '_reviewStepForAction(10)'), 1);
    assert.equal(run(ctx, '_reviewStepForAction(11)'), 2);
    assert.equal(run(ctx, '_reviewStepForAction(99)'), -1);
});

test('牌の絵柄機能が無くても牌名の文字で表示できる', () => {
    const ctx = setup(new RecordBuilder());
    run(ctx, 'tileFaceHtml = undefined');
    assert.match(run(ctx, `_reviewTileHtml('7z')`), /review-tile-text.*>中</);
});
