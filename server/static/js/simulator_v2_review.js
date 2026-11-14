/**
 * @title 半荘総評
 * @description 事前計算された AI 評価 (eval.json の actions) と牌譜を突き合わせ、
 *              視点プレイヤーの半荘全体の打牌を採点・総評する。
 *              - AI 推奨との一致率、ズレの傾向 (カテゴリ別回数)
 *              - 文脈を考慮した再判定: 和了が遠く安い手での撤退 (安牌を抱える手崩し)・降り、
 *                オーラスの差し込みは「ミス」ではなく「良い判断」として扱う
 *              - 全体評価 (上手か・課題が多いか) と長所・課題
 *              - 重大度順のワースト打牌 (その局面へジャンプ可能)
 */

// ズレの判断理由 (評価タプルの決定層名) → カテゴリ
const REVIEW_CATEGORIES = {
    danger: { label: '危険牌', base: 60, advice: '他家の攻撃 (リーチ・副露) に対して危険度の高い牌を切っています。押す価値が薄い手では安全度を優先しましょう。' },
    shanten: { label: '向聴ロス', base: 50, advice: '和了を目指せる手で向聴数を落とす打牌がありました。手が良い・打点が見込める局面では手を進める牌を選びましょう。' },
    ukeire: { label: '受入ロス', base: 30, advice: '有効牌の枚数が少なくなる選択がありました。受け入れ枚数・良形になる変化を比較しましょう。' },
    value: { label: '打点ロス', base: 30, advice: '役やドラを失う打牌がありました。打点を保てる牌の残し方を意識しましょう。' },
    safeKeep: { label: '安牌管理', base: 15, advice: '安全牌を先に手放す場面がありました。不要な安牌は終盤まで残すと押し引きが楽になります。' },
    order: { label: '手順', base: 10, advice: '切る順番の細かな差です。字牌や端牌の切り順を整えると河から読まれにくくなります。' },
    other: { label: 'その他', base: 20, advice: '' },
};

/** 牌 1 枚の HTML。牌の絵柄 (tile_faces.js) が読み込まれていなければ牌名の文字で表示する */
function _reviewTileHtml(tile, extraClass = '') {
    if (typeof tileFaceHtml === 'function') return tileFaceHtml(tile, extraClass);
    return `<span class="tile tile-mini review-tile-text ${getTileClass(tile)} ${extraClass}">${getTileText(tile)}</span>`;
}

const _REVIEW_LAYER_MAP = { '①': 0, '②': 1, '③': 2, '④': 3, '⑤': 4, '⑥': 5, '⑦': 6 };

// 文脈判定のしきい値
// Why: 「中盤に差し掛かっても手が遠く安い」手は、和了を追うより守備に回す方が期待値が高い。
//      AI の打牌評価はその局面単体の手牌効率を優先するため、総評側で文脈を補う。
const REVIEW_CONTEXT = {
    midTurn: 7,          // 自分の打牌数 (≒巡目) がこれ以上を中盤とみなす
    earlyTurn: 5,        // 3 向聴以上ならこの巡目から「遠い」とみなす
    farShanten: 2,       // 推奨通り切っても残る向聴数がこれ以上なら「遠い」
    veryFarShanten: 3,
    lowValue: 0.35,      // v2_hand_value (0-1) がこれ以下なら「安い」
    lowSpeed: 0.3,       // v2_hand_speed (0-1) がこれ以下なら「遅い」
    threat: 0.5,         // max_threat (0-1) がこれ以上なら他家の攻撃あり
    safeTile: 800,       // 安全度 (0-1000) がこれ以上なら「安全牌」とみなす
};

/** 字牌・老頭牌 (1/9) か */
function _isYaochu(tile) {
    if (!tile) return false;
    const suit = tile[tile.length - 1];
    return suit === 'z' || tile[0] === '1' || tile[0] === '9';
}

function _reviewCategory(tierName) {
    const n = tierName || '';
    if (/危険|安全度/.test(n)) return 'danger';
    if (/向聴/.test(n)) return 'shanten';
    if (/安牌/.test(n)) return 'safeKeep';
    if (/受入/.test(n)) return 'ukeire';
    if (/手役|ドラ|打点/.test(n)) return 'value';
    if (/戦術|愚形/.test(n)) return 'order';
    return 'other';
}

function _normTile(t) {
    return t && t[0] === '0' ? '5' + t.slice(1) : t;
}

/** 評価タプルから打牌の安全度 (0-1000, 大きいほど安全) を取り出す。無ければ null */
function _tileSafety(ev) {
    if (!ev || !ev.tuple_values) return null;
    const i = (ev.tier_names || []).indexOf('安全度');
    if (i < 0 || typeof ev.tuple_values[i] !== 'number') return null;
    // Why: 評価タプルは昇順ソート (小さいほど良い) のため、安全度は -safety_score で格納されている
    return -ev.tuple_values[i];
}

/** scores 配列から seat の順位 (1-4) を返す。同点は起家に近い席を上位とする */
function _rankOf(scores, seat) {
    if (!scores || scores.length < 4) return null;
    let rank = 1;
    for (let s = 0; s < 4; s++) {
        if (s === seat) continue;
        if (scores[s] > scores[seat] || (scores[s] === scores[seat] && s < seat)) rank++;
    }
    return rank;
}

/** 牌譜の action 配列 index から、その打牌直前の局面を表示するタイムライン位置を求める */
function _reviewStepForAction(actionIdx) {
    const rawIdx = window.__actionIdxToRawIdx ? window.__actionIdxToRawIdx[actionIdx] : undefined;
    if (rawIdx === undefined) return -1;
    let best = -1;
    for (let i = 0; i < timelineSteps.length; i++) {
        if (timelineSteps[i] < rawIdx) best = i;
        else break;
    }
    return best;
}

/**
 * @title AI 推奨と違う打牌を文脈から再判定する
 * @description 和了が遠く安い手で、安全牌を残して手を崩した (撤退準備) / 攻撃に対して安全な牌を選んだ (降り)
 *              場合は「良い判断」とする。該当しなければ null。
 */
function _judgeDeviationByContext(dec) {
    const C = REVIEW_CONTEXT;
    if (dec.recShanten === null || dec.turn === null) return null;
    // Why: オーラスのトップ目は和了より放銃回避が最優先のため、巡目に関係なく 2 向聴以上を「遠い」とみなす
    const isAllLastTop = dec.isAllLast && dec.rankAtStart === 1;
    const isFar = (dec.turn >= C.midTurn && dec.recShanten >= C.farShanten)
        || (dec.turn >= C.earlyTurn && dec.recShanten >= C.veryFarShanten)
        || (isAllLastTop && dec.recShanten >= C.farShanten);
    const isCheapOrSlow = (dec.handValue !== null && dec.handValue <= C.lowValue)
        || (dec.handSpeed !== null && dec.handSpeed <= C.lowSpeed);
    if (!isFar || !isCheapOrSlow) return null;
    if (dec.actSafety === null || dec.recSafety === null) return null;

    const handDesc = (isAllLastTop ? 'オーラスのトップ目で、' : '')
        + `${dec.turn}巡目で推奨通りでも${dec.recShanten}向聴・打点も低い和了の遠い手`;
    // 手に残した (AI が切りたかった) 牌が本当に安全牌か
    const keptIsSafe = _isYaochu(dec.recommended) || dec.recSafety >= C.safeTile;
    if (dec.maxThreat >= C.threat) {
        // 他家の攻撃がある: AI 推奨より安全な牌を切った → 降り
        if (dec.actSafety > dec.recSafety) {
            return { type: 'fold', label: '降り判断', text: `${handDesc}。他家の攻撃に対して、手を進めるより安全な牌 (安全度 ${dec.actSafety} > ${dec.recSafety}) を選んだ降り判断です。` };
        }
    } else if (keptIsSafe && dec.actSafety < dec.recSafety && ['shanten', 'ukeire', 'order', 'value'].includes(dec.category)) {
        // まだ攻撃が無い: 後で危険になる牌を先に処理し、安全牌を手に残した → 撤退準備
        return { type: 'retreat', label: '撤退準備', text: `${handDesc}。安全牌 (${getTileText(dec.recommended)}) を抱えて手を崩し、他家の攻撃に備えた判断です。` };
    }
    return null;
}

/**
 * @title 半荘総評の計算
 * @param {number} seat - 総評対象の席
 * @returns {object|null} 総評データ (事前計算データが無ければ null)
 */
function computeHanchanReview(seat) {
    if (!gameData || !gameData.detail_records) return null;
    const pre = window.__precomputedActions || {};
    if (Object.keys(pre).length === 0) return null;
    const actions = gameData.detail_records.actions || [];
    const windNames = ['東', '南', '西', '北'];

    // 最終局の判定用: 最後の RecordNewRound の位置
    let lastNewRoundIdx = -1;
    actions.forEach((a, i) => { if (a.result && a.result.class_name === 'RecordNewRound') lastNewRoundIdx = i; });

    let lastRoundKey = null;
    actions.forEach(a => {
        if (a.result && a.result.class_name === 'RecordNewRound') lastRoundKey = `${a.result.data.chang || 0}-${a.result.data.ju || 0}`;
    });
    let isAllLast = false;
    let rankAtStart = null;

    let roundLabel = '';
    let turnInRound = 0;
    let lastDiscard = null;
    const decisions = [];
    const rounds = [];
    const dealIns = [];
    const wins = [];

    actions.forEach((act, idx) => {
        const r = act.result;
        if (!r || !r.data) return;
        const d = r.data;
        switch (r.class_name) {
            case 'RecordNewRound':
                roundLabel = `${windNames[d.chang || 0]}${(d.ju || 0) + 1}局 ${d.ben || 0}本場`;
                turnInRound = 0;
                lastDiscard = null;
                isAllLast = `${d.chang || 0}-${d.ju || 0}` === lastRoundKey;
                rankAtStart = _rankOf(d.scores, seat);
                break;
            case 'RecordDiscardTile': {
                lastDiscard = { idx, seat: d.seat, tile: d.tile };
                if (d.seat !== seat) break;
                turnInRound += 1;
                const p = pre[String(idx)];
                if (!p || !p.recommended || p.is_riichi_active) break;
                const evs = p.evaluations || [];
                const sd = p.strategy_details || {};
                const actual = d.tile;
                const near = p.near_tiles || [];
                const isMatch = _normTile(actual) === _normTile(p.recommended)
                    || near.some(t => _normTile(t) === _normTile(actual));
                const actEv = evs.find(e => e.tile === actual) || evs.find(e => _normTile(e.tile) === _normTile(actual));
                const recEv = evs.find(e => e.tile === p.recommended);
                const dec = {
                    actionIdx: idx, roundLabel, turn: turnInRound, actual, recommended: p.recommended,
                    isMatch, category: null, severity: 0, reason: '', recReason: recEv ? recEv.reason : '',
                    shantenDiff: 0, mode: sd.v2_mode_jp || '', dealIn: null, good: null,
                    recShanten: recEv && typeof recEv.shanten === 'number' ? recEv.shanten : null,
                    handValue: typeof sd.v2_hand_value === 'number' ? sd.v2_hand_value : null,
                    handSpeed: typeof sd.v2_hand_speed === 'number' ? sd.v2_hand_speed : null,
                    maxThreat: typeof sd.max_threat === 'number' ? sd.max_threat : 0,
                    actSafety: _tileSafety(actEv), recSafety: _tileSafety(recEv),
                    isAllLast, rankAtStart,
                };
                if (!isMatch && actEv) {
                    const layer = _REVIEW_LAYER_MAP[(actEv.reason || '').charAt(0)];
                    const tierNames = actEv.tier_names || sd.v2_tier_names || [];
                    const cat = _reviewCategory(layer !== undefined ? tierNames[layer] : '');
                    const sorted = [...evs].sort((a, b) => b.score - a.score);
                    const pos = sorted.findIndex(e => e === actEv);
                    const rankRatio = sorted.length > 1 ? pos / (sorted.length - 1) : 0;
                    dec.category = cat;
                    dec.reason = actEv.reason || '';
                    dec.shantenDiff = recEv ? Math.max(0, actEv.shanten - recEv.shanten) : 0;
                    // Why: ベタオリ中は向聴数を落とすのが正しいため、向聴差は「向聴ロス」の時だけ加点する
                    dec.severity = REVIEW_CATEGORIES[cat].base + rankRatio * 40
                        + (cat === 'shanten' ? Math.min(dec.shantenDiff, 2) * 10 : 0)
                        + (actEv.is_blunder ? (actEv.blunder_score || 30) : 0);
                    dec.good = _judgeDeviationByContext(dec);
                    if (dec.good) dec.severity = 0;
                }
                decisions.push(dec);
                break;
            }
            case 'RecordHule': {
                const delta = d.deltaScores || [];
                const isFinal = idx > lastNewRoundIdx;
                (d.hules || []).forEach(h => {
                    if (h.seat === seat) {
                        wins.push({ roundLabel, points: delta[seat] || 0, zimo: !!h.zimo });
                    } else if (!h.zimo && lastDiscard && lastDiscard.seat === seat) {
                        const loss = -(delta[seat] || 0);
                        const rankBefore = _rankOf(d.oldScores, seat);
                        const rankAfter = _rankOf(d.scores, seat);
                        // Why: オーラスで放銃しても順位が落ちずに終局するなら、終局させるための差し込みとみなす
                        const isSashikomi = isFinal && rankAfter !== null && rankBefore !== null && rankAfter <= rankBefore;
                        dealIns.push({ roundLabel, tile: lastDiscard.tile, loss, winner: h.seat, actionIdx: lastDiscard.idx, isSashikomi });
                        let dec = decisions.find(x => x.actionIdx === lastDiscard.idx);
                        if (!dec) {
                            // リーチ後のツモ切りなど、打牌が固定されていた局面での放銃
                            dec = {
                                actionIdx: lastDiscard.idx, roundLabel, turn: null, actual: lastDiscard.tile, recommended: null,
                                isMatch: true, category: null, severity: 150, reason: 'リーチ後などで打牌が固定されていた局面での放銃です。',
                                recReason: '', shantenDiff: 0, mode: '', dealIn: null, good: null,
                            };
                            decisions.push(dec);
                        }
                        dec.dealIn = { loss, winner: h.seat, isSashikomi, rankAfter };
                        if (isSashikomi) {
                            dec.good = {
                                type: 'sashikomi', label: '差し込み',
                                text: `オーラスで ${_reviewNickname(h.seat)} に差し込み (-${loss})、${rankAfter}位のまま終局させました。順位を守る好判断です。`,
                            };
                            dec.severity = 0;
                        } else {
                            dec.severity += 200 + loss / 200;
                        }
                    }
                });
                rounds.push({ roundLabel, delta: delta[seat] || 0, result: 'hule' });
                break;
            }
            case 'RecordNoTile': {
                const sc = (d.scores && d.scores[0]) || {};
                const delta = sc.deltaScores || [];
                rounds.push({ roundLabel, delta: delta[seat] || 0, result: 'notile' });
                break;
            }
            case 'RecordLiuJu':
                rounds.push({ roundLabel, delta: 0, result: 'liuju' });
                break;
        }
    });

    const judged = decisions.filter(x => x.recommended);
    const matchCount = judged.filter(x => x.isMatch).length;
    const goodDeviationCount = judged.filter(x => !x.isMatch && x.good).length;
    const catCounts = {};
    decisions.forEach(x => {
        if (x.category && !x.good) catCounts[x.category] = (catCounts[x.category] || 0) + 1;
    });

    // Why: ベタオリ中の連続したズレなどで同じ局が一覧を埋めないよう、1 局につき最悪の 1 打だけ載せる
    const sortedMistakes = decisions
        .filter(x => !x.good && (!x.isMatch || x.dealIn))
        .sort((a, b) => b.severity - a.severity);
    const perRound = {};
    sortedMistakes.forEach(x => { perRound[x.roundLabel] = (perRound[x.roundLabel] || 0) + 1; });
    const seenRounds = new Set();
    const worst = [];
    for (const x of sortedMistakes) {
        if (seenRounds.has(x.roundLabel)) continue;
        seenRounds.add(x.roundLabel);
        worst.push({ ...x, othersInRound: perRound[x.roundLabel] - 1 });
        if (worst.length >= 6) break;
    }

    // 良い判断: 差し込みを優先し、撤退・降りは 1 局 1 件まで
    const goods = [];
    const goodRounds = new Set();
    decisions.filter(x => x.good)
        .sort((a, b) => (a.good.type === 'sashikomi' ? -1 : 0) - (b.good.type === 'sashikomi' ? -1 : 0))
        .forEach(x => {
            if (x.good.type !== 'sashikomi' && goodRounds.has(x.roundLabel)) return;
            goodRounds.add(x.roundLabel);
            goods.push(x);
        });
    const goodCounts = {};
    decisions.forEach(x => { if (x.good) goodCounts[x.good.type] = (goodCounts[x.good.type] || 0) + 1; });

    // 最終順位・点数
    const players = (gameData.head && gameData.head.result && gameData.head.result.players) || [];
    const ordered = [...players].sort((a, b) => (b.partPoint1 || 0) - (a.partPoint1 || 0));
    const rankIdx = ordered.findIndex(p => (p.seat || 0) === seat);
    const me = players.find(p => (p.seat || 0) === seat);
    const grade = (window.__evalGrades || {})[String(seat)] || null;

    const rv = {
        seat, decisions, judged: judged.length, matchCount, goodDeviationCount,
        matchRate: judged.length ? matchCount / judged.length : 0,
        adjustedRate: judged.length ? (matchCount + goodDeviationCount) / judged.length : 0,
        catCounts, worst, goods, goodCounts, dealIns, wins, rounds,
        finalRank: rankIdx >= 0 ? rankIdx + 1 : null,
        finalScore: me ? me.partPoint1 : null,
        grade,
    };
    rv.verdict = _computeVerdict(rv);
    return rv;
}

/**
 * @title 全体評価 (上手か・課題が多いか) を算出する
 * @description 文脈補正後の一致率を土台に、回避できた放銃・危険牌のミス・最終順位で加減点する。
 *              一致率 40% で 40 点、60% で 70 点になるよう線形に換算 (人間の打牌は AI と完全一致しないため)。
 */
function _computeVerdict(rv) {
    const avoidable = rv.dealIns.filter(di => {
        if (di.isSashikomi) return false;
        const dec = rv.decisions.find(x => x.actionIdx === di.actionIdx);
        return dec && !dec.isMatch;
    });
    const dangerCount = rv.catCounts.danger || 0;
    const rankBonus = { 1: 6, 2: 3, 3: -3, 4: -6 }[rv.finalRank] || 0;

    let score = 40 + (rv.adjustedRate - 0.4) * 150;
    score -= avoidable.length * 6;
    score -= Math.min(dangerCount * 0.6, 8);
    score += rankBonus;
    score += Math.min((rv.goodCounts.sashikomi || 0) * 3, 6);
    score = Math.max(0, Math.min(100, Math.round(score)));

    let level, levelCls, headline;
    if (score >= 75) {
        level = '上手に打てている'; levelCls = 'verdict-great';
        headline = '全体的に判断の質が高く、大きな崩れのない半荘でした。細かな精度を詰めればさらに安定します。';
    } else if (score >= 60) {
        level = '安定している'; levelCls = 'verdict-good';
        headline = '基本は押さえられています。いくつかの判断ミスを減らせば一段上のレベルです。';
    } else if (score >= 45) {
        level = '平均的・伸びしろあり'; levelCls = 'verdict-mid';
        headline = '良い判断もある一方で、繰り返し出ている課題があります。下の課題を重点的に見直しましょう。';
    } else {
        level = '課題が多い'; levelCls = 'verdict-bad';
        headline = '判断のズレや失点につながるミスが目立ちます。まずは致命的な打牌から見直しましょう。';
    }

    // 長所
    const strengths = [];
    const nRounds = rv.rounds.length || 1;
    if (rv.finalRank === 1) strengths.push('トップを取り切った');
    if (rv.wins.length / nRounds >= 0.3) strengths.push(`和了率が高い (${rv.wins.length}/${nRounds}局)`);
    if (rv.dealIns.filter(d => !d.isSashikomi).length === 0) strengths.push('不要な放銃がない');
    if (rv.goodCounts.sashikomi) strengths.push('オーラスの差し込みで順位を確定させた');
    const defensive = (rv.goodCounts.retreat || 0) + (rv.goodCounts.fold || 0);
    if (defensive >= 2) strengths.push(`和了の遠い手で無理せず守備に回れている (${defensive}回)`);
    if (rv.adjustedRate >= 0.6) strengths.push('AI と近い牌選択ができている');

    // 課題
    const weaknesses = [];
    if (avoidable.length > 0) weaknesses.push(`AI 推奨と違う牌での放銃が ${avoidable.length}回 (計 -${avoidable.reduce((s, d) => s + d.loss, 0)})`);
    Object.entries(rv.catCounts).sort((a, b) => b[1] - a[1]).slice(0, 2).forEach(([cat, n]) => {
        const c = REVIEW_CATEGORIES[cat];
        if (c && c.advice && n >= 3) weaknesses.push(`【${c.label} ×${n}】${c.advice}`);
    });

    return { score, level, levelCls, headline, strengths, weaknesses, avoidableCount: avoidable.length };
}

function _severityLabel(dec) {
    if (dec.dealIn && !dec.isMatch) return { text: '致命的', cls: 'sev-fatal' };
    if (dec.dealIn) return { text: '放銃 (避けにくい)', cls: 'sev-major' };
    if (dec.severity >= 60) return { text: '大きなミス', cls: 'sev-major' };
    return { text: '小さなミス', cls: 'sev-minor' };
}

function _reviewNickname(seat) {
    const acc = gameData && gameData.head && (gameData.head.accounts || []).find(a => a.seat === seat);
    return acc ? acc.nickname : `席${seat}`;
}

function _escapeHtml(s) {
    return String(s || '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

/** 局面の文脈 (巡目・向聴・打点・他家の攻撃) を短い文字列にする */
function _contextLine(dec) {
    const parts = [];
    if (dec.turn) parts.push(`${dec.turn}巡目`);
    if (dec.recShanten !== null && dec.recShanten !== undefined) parts.push(dec.recShanten <= 0 ? '推奨でテンパイ' : `推奨でも${dec.recShanten}向聴`);
    if (dec.handValue !== null && dec.handValue !== undefined) parts.push(`打点見込み ${dec.handValue <= REVIEW_CONTEXT.lowValue ? '低' : (dec.handValue >= 0.6 ? '高' : '中')}`);
    if (dec.maxThreat !== undefined) parts.push(dec.maxThreat >= REVIEW_CONTEXT.threat ? '他家の攻撃あり' : '他家の攻撃なし');
    return parts.join(' / ');
}

function _tileCompareHtml(dec) {
    const recHtml = dec.recommended
        ? `<span class="review-arrow">→ AI推奨</span>${_reviewTileHtml(dec.recommended)}<span class="review-tilename">${getTileText(dec.recommended)}</span>` : '';
    return `<div class="review-tiles">
            <span class="review-label">実際</span>${_reviewTileHtml(dec.actual)}<span class="review-tilename">${getTileText(dec.actual)}</span>
            ${dec.isMatch ? '' : recHtml}
        </div>`;
}

function _jumpButtonHtml(dec) {
    const step = _reviewStepForAction(dec.actionIdx);
    return step >= 0 ? `<button class="btn review-jump" onclick="toggleHanchanReview(false); jumpToAction(${step});">この局面を見る ▶</button>` : '';
}

/** 総評の文章 (概要コメント) を組み立てる */
function _buildOverallComment(rv) {
    const lines = [];
    const pct = Math.round(rv.matchRate * 100);
    const adj = Math.round(rv.adjustedRate * 100);
    lines.push(`AI 推奨との一致率 <b>${pct}%</b> (${rv.matchCount}/${rv.judged} 打)。`
        + (rv.goodDeviationCount > 0 ? `推奨と違っても局面上妥当な判断 ${rv.goodDeviationCount} 打を含めると <b>${adj}%</b>。` : ''));

    const winSum = rv.wins.reduce((s, w) => s + w.points, 0);
    const lossSum = rv.dealIns.reduce((s, d) => s + d.loss, 0);
    const sashikomi = rv.dealIns.filter(d => d.isSashikomi).length;
    lines.push(`和了 <b>${rv.wins.length}回 (+${winSum})</b>、放銃 <b>${rv.dealIns.length}回 (-${lossSum})</b>`
        + (sashikomi ? ` (うち差し込み ${sashikomi}回)` : '') + '。');
    return lines.map(l => `<p>${l}</p>`).join('');
}

function renderHanchanReview() {
    const body = document.getElementById('reviewBody');
    if (!body) return;
    const seat = perspectiveSeat;
    const rv = computeHanchanReview(seat);
    document.getElementById('reviewTitleName').innerText = _reviewNickname(seat);
    if (!rv) {
        body.innerHTML = '<p class="review-empty">AI 分析データがまだありません。トップページで分析完了を待ってから開いてください。</p>';
        return;
    }
    const v = rv.verdict;

    const gradeHtml = rv.grade
        ? `<span class="grade-pill grade-${rv.grade.grade.toLowerCase()}" title="AI一致度グレード">${rv.grade.grade}</span>` : '';
    const rankHtml = rv.finalRank ? `${rv.finalRank}位 / ${rv.finalScore}点` : '';

    const catHtml = Object.entries(rv.catCounts).sort((a, b) => b[1] - a[1])
        .map(([cat, n]) => `<span class="review-chip">${REVIEW_CATEGORIES[cat].label} ×${n}</span>`).join('');

    const listHtml = (items) => items.map(s => `<li>${_escapeHtml(s)}</li>`).join('');

    const worstHtml = rv.worst.length === 0
        ? '<p class="review-empty">大きなミスは見つかりませんでした。</p>'
        : rv.worst.map((dec, i) => {
            const sev = _severityLabel(dec);
            const cat = dec.category ? REVIEW_CATEGORIES[dec.category].label : '';
            let dealInHtml = dec.dealIn
                ? `<div class="review-dealin">💥 この牌で ${_escapeHtml(_reviewNickname(dec.dealIn.winner))} に放銃 (-${dec.dealIn.loss})</div>` : '';
            // Why: AI の理由文は手牌効率の観点だけなので、放銃時は押し引きの観点を補足する
            if (dec.dealIn && dec.maxThreat >= REVIEW_CONTEXT.threat && dec.recShanten >= 1
                && dec.handValue !== null && dec.handValue <= REVIEW_CONTEXT.lowValue) {
                dealInHtml += `<div class="review-reason">打点の低い${dec.recShanten}向聴の手で他家の攻撃に押しての放銃です。和了しても安い手なので、安全な牌で降りることも検討すべき局面でした。</div>`;
            }
            const ctx = dec.turn ? _contextLine(dec) : '';
            return `
                <div class="review-item">
                    <div class="review-item-head">
                        <span class="review-rank">#${i + 1}</span>
                        <span class="review-sev ${sev.cls}">${sev.text}</span>
                        <span class="review-where">${_escapeHtml(dec.roundLabel)}${dec.turn ? ` ${dec.turn}打目` : ''}</span>
                        ${cat ? `<span class="review-chip">${cat}</span>` : ''}
                        ${dec.mode ? `<span class="review-mode">AI方針: ${_escapeHtml(dec.mode)}</span>` : ''}
                    </div>
                    ${_tileCompareHtml(dec)}
                    ${ctx ? `<div class="review-context">${_escapeHtml(ctx)}</div>` : ''}
                    ${dealInHtml}
                    ${dec.reason ? `<div class="review-reason">${convertTilesInString(_escapeHtml(dec.reason))}</div>` : ''}
                    ${dec.othersInRound > 0 ? `<div class="review-reason">(この局では他にも ${dec.othersInRound} 打、AI 推奨と違う打牌があります)</div>` : ''}
                    ${_jumpButtonHtml(dec)}
                </div>`;
        }).join('');

    const goodsHtml = rv.goods.slice(0, 5).map(dec => `
        <div class="review-item review-item-good">
            <div class="review-item-head">
                <span class="review-sev sev-good">${_escapeHtml(dec.good.label)}</span>
                <span class="review-where">${_escapeHtml(dec.roundLabel)}${dec.turn ? ` ${dec.turn}打目` : ''}</span>
            </div>
            ${_tileCompareHtml(dec)}
            <div class="review-reason">${_escapeHtml(dec.good.text)}</div>
            ${_jumpButtonHtml(dec)}
        </div>`).join('');

    const roundsHtml = rv.rounds.map(r => {
        const cls = r.delta > 0 ? 'seat-diff-plus' : (r.delta < 0 ? 'seat-diff-minus' : '');
        const sign = r.delta > 0 ? '+' : '';
        return `<tr><td>${_escapeHtml(r.roundLabel)}</td><td class="${cls}">${sign}${r.delta}</td></tr>`;
    }).join('');

    body.innerHTML = `
        <div class="review-verdict ${v.levelCls}">
            <div class="review-verdict-head">
                <span class="review-verdict-level">${_escapeHtml(v.level)}</span>
                <span class="review-verdict-score">総合 ${v.score} / 100</span>
            </div>
            <div class="review-verdict-text">${_escapeHtml(v.headline)}</div>
        </div>
        <div class="review-summary">
            <div class="review-summary-row">${gradeHtml}<span class="review-final">${rankHtml}</span></div>
            <div class="review-comment">${_buildOverallComment(rv)}</div>
            ${v.strengths.length ? `<div class="review-list-title good">👍 長所</div><ul class="review-list">${listHtml(v.strengths)}</ul>` : ''}
            ${v.weaknesses.length ? `<div class="review-list-title bad">🛠 課題</div><ul class="review-list">${listHtml(v.weaknesses)}</ul>` : ''}
            ${catHtml ? `<div class="review-chips"><span class="review-label">ミスとみなしたズレの内訳</span>${catHtml}</div>` : ''}
        </div>
        <div class="review-section-title">⚠ 見直したい打牌 (重大度順)</div>
        ${worstHtml}
        ${goodsHtml ? `<div class="review-section-title">✅ AI 推奨と違うが妥当な判断</div>${goodsHtml}` : ''}
        <div class="review-section-title">📈 局ごとの収支</div>
        <table class="review-rounds">${roundsHtml}</table>
        <p class="review-note">※ 「妥当な判断」は、巡目・向聴数・打点見込み・他家の攻撃・牌の安全度から機械的に推定しています。</p>
    `;
}

function toggleHanchanReview(show) {
    const el = document.getElementById('reviewOverlay');
    if (!el) return;
    const visible = show === undefined ? !el.classList.contains('is-visible') : show;
    if (visible) renderHanchanReview();
    el.classList.toggle('is-visible', visible);
}
