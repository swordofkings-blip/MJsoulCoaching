// ----- グローバル状態 -----
let gameData = null;
let rawActionsList = [];
let timelineSteps = [];
let currentActionIndex = 0;
let isPlaying = false;
let playInterval = null;
let perspectiveSeat = 0;
// 自分のニックネーム (視点選択時に記憶し、次回以降の初期視点に使う)
const MY_NICKNAME_KEY = 'mjcoach.myNickname';

// ----- BOTコーチング制御変数 -----
let _coachEvalSeq = 0;
let _coachEvalAbort = null;
let _meldEvalSeq = 0;
let _meldEvalAbort = null;
let _lastCoachHash = null;

// ----- 麻雀エンジン -----
class MahjongEngine {
    constructor() {
        this.reset();
    }

    reset() {
        this.roundName = '東1局';
        this.ben = 0;
        this.leftTileCount = 69;
        this.liqibang = 0;
        this.doras = [];
        this.hands = [[], [], [], []];
        this.discards = [[], [], [], []];
        this.melds = [[], [], [], []];
        this.scores = [25000, 25000, 25000, 25000];
        this.activeSeat = -1;
        this.lastTsumo = [null, null, null, null];
    }

    initRound(data) {
        const windNames = ['東', '南', '西', '北'];
        const roundName = windNames[data.chang] + (data.ju + 1) + '局';

        this.roundName = roundName;
        this.ben = data.ben || 0;
        this.liqibang = data.liqibang || 0;
        this.leftTileCount = data.leftTileCount !== undefined ? data.leftTileCount : 69;
        this.doras = data.doras ? [...data.doras] : [];
        this.scores = data.scores ? [...data.scores] : [25000, 25000, 25000, 25000];

        this.hands[0] = data.tiles0 ? [...data.tiles0].sort(compareTiles) : [];
        this.hands[1] = data.tiles1 ? [...data.tiles1].sort(compareTiles) : [];
        this.hands[2] = data.tiles2 ? [...data.tiles2].sort(compareTiles) : [];
        this.hands[3] = data.tiles3 ? [...data.tiles3].sort(compareTiles) : [];

        this.discards = [[], [], [], []];
        this.melds = [[], [], [], []];
        this.lastTsumo = [null, null, null, null];
        this.activeSeat = data.operation ? data.operation.seat : 0;
    }

    applyAction(action) {
        if (!action || !action.result) return;
        const type = action.result.class_name;
        const data = action.result.data;
        if (!data) return;

        switch (type) {
            case 'RecordNewRound':
                this.initRound(data);
                break;

            case 'RecordDiscardTile': {
                const seat = data.seat;
                this.activeSeat = seat;
                const tile = data.tile;

                const hand = this.hands[seat];
                let tileIdx = hand.indexOf(tile);
                if (tileIdx === -1 && tile === '0m') tileIdx = hand.indexOf('5m');
                if (tileIdx === -1 && tile === '5m') tileIdx = hand.indexOf('0m');
                if (tileIdx === -1 && tile === '0p') tileIdx = hand.indexOf('5p');
                if (tileIdx === -1 && tile === '5p') tileIdx = hand.indexOf('0p');
                if (tileIdx === -1 && tile === '0s') tileIdx = hand.indexOf('5s');
                if (tileIdx === -1 && tile === '5s') tileIdx = hand.indexOf('0s');

                if (tileIdx !== -1) {
                    hand.splice(tileIdx, 1);
                }
                hand.sort(compareTiles);
                this.lastTsumo[seat] = null;

                this.discards[seat].push({
                    tile: tile,
                    isLiqi: data.isLiqi || false,
                    moqie: data.moqie || false,
                    claimed: false
                });
                break;
            }

            case 'RecordDealTile': {
                const seat = data.seat;
                this.activeSeat = seat;
                this.leftTileCount = data.leftTileCount !== undefined ? data.leftTileCount : this.leftTileCount - 1;
                this.hands[seat].push(data.tile);
                this.lastTsumo[seat] = data.tile;
                break;
            }

            case 'RecordChiPengGang': {
                const seat = data.seat;
                this.activeSeat = seat;
                const tiles = data.tiles;
                const froms = data.froms;

                let targetSeat = -1;
                let targetTile = null;
                for (let i = 0; i < froms.length; i++) {
                    if (froms[i] !== seat) {
                        targetSeat = froms[i];
                        targetTile = tiles[i];
                        break;
                    }
                }

                if (targetSeat !== -1 && targetTile) {
                    const disc = this.discards[targetSeat];
                    for (let i = disc.length - 1; i >= 0; i--) {
                        if ((disc[i].tile === targetTile || (targetTile.startsWith('5') && disc[i].tile.startsWith('0')) || (targetTile.startsWith('0') && disc[i].tile.startsWith('5'))) && !disc[i].claimed) {
                            disc[i].claimed = true;
                            break;
                        }
                    }
                }

                const hand = this.hands[seat];
                tiles.forEach((t, i) => {
                    if (froms[i] === seat) {
                        let idx = hand.indexOf(t);
                        if (idx === -1 && t === '0m') idx = hand.indexOf('5m');
                        if (idx === -1 && t === '5m') idx = hand.indexOf('0m');
                        if (idx === -1 && t === '0p') idx = hand.indexOf('5p');
                        if (idx === -1 && t === '5p') idx = hand.indexOf('0p');
                        if (idx === -1 && t === '0s') idx = hand.indexOf('5s');
                        if (idx === -1 && t === '5s') idx = hand.indexOf('0s');

                        if (idx !== -1) hand.splice(idx, 1);
                    }
                });

                this.melds[seat].push({
                    type: data.type === 2 ? 'minggang' : (tiles.length === 4 ? 'minggang' : 'cpg'),
                    tiles: [...tiles],
                    froms: [...froms]
                });

                this.lastTsumo[seat] = null;
                break;
            }

            case 'RecordAnGangAddGang': {
                const seat = data.seat;
                this.activeSeat = seat;
                const tile = data.tiles;
                const type = data.type;

                const hand = this.hands[seat];

                if (type === 3) {
                    for (let i = 0; i < 4; i++) {
                        let idx = hand.indexOf(tile);
                        if (idx === -1 && tile === '5m') idx = hand.indexOf('0m');
                        if (idx === -1 && tile === '0m') idx = hand.indexOf('5m');
                        if (idx === -1 && tile === '5p') idx = hand.indexOf('0p');
                        if (idx === -1 && tile === '0p') idx = hand.indexOf('5p');
                        if (idx === -1 && tile === '5s') idx = hand.indexOf('0s');
                        if (idx === -1 && tile === '0s') idx = hand.indexOf('5s');

                        if (idx !== -1) hand.splice(idx, 1);
                    }
                    this.melds[seat].push({
                        type: 'ankan',
                        tiles: [tile, tile, tile, tile],
                        froms: [seat, seat, seat, seat]
                    });
                } else {
                    let idx = hand.indexOf(tile);
                    if (idx === -1 && tile === '5m') idx = hand.indexOf('0m');
                    if (idx === -1 && tile === '0m') idx = hand.indexOf('5m');
                    if (idx === -1 && tile === '5p') idx = hand.indexOf('0p');
                    if (idx === -1 && tile === '0p') idx = hand.indexOf('5p');
                    if (idx === -1 && tile === '5s') idx = hand.indexOf('0s');
                    if (idx === -1 && tile === '0s') idx = hand.indexOf('5s');
                    if (idx !== -1) hand.splice(idx, 1);

                    const seatMelds = this.melds[seat];
                    let upgraded = false;
                    for (let i = 0; i < seatMelds.length; i++) {
                        const m = seatMelds[i];
                        const isMatch = m.tiles.every(t => t.slice(1) === tile.slice(1) || (t.startsWith('0') && tile.slice(1) === 'm') || (t.startsWith('0') && tile.slice(1) === 'p') || (t.startsWith('0') && tile.slice(1) === 's'));
                        if (isMatch && m.tiles.length === 3) {
                            m.tiles.push(tile);
                            m.froms.push(seat);
                            m.type = 'kankan';
                            upgraded = true;
                            break;
                        }
                    }
                    if (!upgraded) {
                        this.melds[seat].push({
                            type: 'kankan',
                            tiles: [tile, tile, tile, tile],
                            froms: [seat, seat, seat, seat]
                        });
                    }
                }
                this.lastTsumo[seat] = null;
                break;
            }

            case 'RecordHule':
            case 'RecordNoTile':
                if (data.scores && data.scores.length > 0) {
                    const scoreData = data.scores[0];
                    if (scoreData.scores) {
                        this.scores = [...scoreData.scores];
                    } else if (data.scores) {
                        this.scores = [...data.scores];
                    }
                }
                break;
        }
    }
}

const engine = new MahjongEngine();

// ----- 読み込み・ナビゲーション -----
async function loadGame() {
    const urlParams = new URLSearchParams(window.location.search);
    const uuid = urlParams.get('uuid');
    if (!uuid) {
        alert('UUIDが指定されていません');
        window.location.href = '/';
        return;
    }

    try {
        const response = await fetch(`/api/record?uuid=${uuid}`);
        if (!response.ok) throw new Error('牌譜データの読み込みに失敗しました');

        gameData = await response.json();

        window.__precomputedActions = {};
        window.__precomputedMeldDecisions = {};
        try {
            const evalResp = await fetch(`/api/eval-actions?uuid=${uuid}`);
            if (evalResp.ok) {
                const evalJson = await evalResp.json();
                if (evalJson) {
                    window.__precomputedActions = evalJson.actions || {};
                    window.__precomputedMeldDecisions = evalJson.precomputed_meld_decisions || {};
                }
            }
        } catch (e) {
        }

        const mjaiToInternal = {
            'E': '1z', 'S': '2z', 'W': '3z', 'N': '4z', 'P': '5z', 'F': '6z', 'C': '7z'
        };
        function normTile(t) {
            if (!t || t.length === 0) return t;
            if (t === '?') return t;
            if (mjaiToInternal[t]) return mjaiToInternal[t];
            return t;
        }
        function normTiles(arr) {
            if (!arr) return arr;
            if (typeof arr === 'string') return normTile(arr);
            if (Array.isArray(arr)) return arr.map(t => typeof t === 'string' ? normTile(t) : t);
            return arr;
        }
        (gameData.detail_records.actions || []).forEach(act => {
            if (!act.result || !act.result.data) return;
            const d = act.result.data;
            if (d.tile) d.tile = normTile(d.tile);
            if (d.tiles) d.tiles = normTiles(d.tiles);
            if (d.pai) d.pai = normTile(d.pai);
            if (d.consumed) d.consumed = normTiles(d.consumed);
            for (let si = 0; si < 4; si++) {
                const key = 'tiles' + si;
                if (d[key]) d[key] = normTiles(d[key]);
            }
            if (d.hand) d.hand = normTiles(d.hand);
            if (d.huTile) d.huTile = normTile(d.huTile);
            if (d.doras) d.doras = normTiles(d.doras);
            if (d.liDoras) d.liDoras = normTiles(d.liDoras);
            if (d.dora_marker) d.dora_marker = normTile(d.dora_marker);
        });
        if (gameData.head && gameData.head.accounts) {
            gameData.head.accounts.forEach(acc => {
                const nameEl = document.querySelector(`#seatInfo${acc.seat} .seat-name`);
                if (nameEl) nameEl.innerText = acc.nickname;
                const radioLabel = document.querySelector(`label[for="pers${acc.seat}"]`);
                if (radioLabel) radioLabel.innerText = acc.nickname;
            });

            // Why: 視点は従来 席0 固定だったため、自分以外 (東家) の分析が表示されていた。
            //      前回選んだ視点のニックネームを記憶し、同じプレイヤーがいればその席を初期視点にする。
            const myNickname = localStorage.getItem(MY_NICKNAME_KEY);
            const me = myNickname && gameData.head.accounts.find(acc => acc.nickname === myNickname);
            if (me && typeof me.seat === 'number') {
                perspectiveSeat = me.seat;
                const radio = document.getElementById(`pers${me.seat}`);
                if (radio) radio.checked = true;
            }
        }

        const allActions = gameData.detail_records.actions || [];
        const validClassNames = [
            'RecordNewRound',
            'RecordDiscardTile',
            'RecordDealTile',
            'RecordChiPengGang',
            'RecordAnGangAddGang',
            'RecordHule',
            'RecordNoTile'
        ];

        rawActionsList = allActions.filter(act => {
            return act.result && validClassNames.includes(act.result.class_name);
        });

        window.__rawIdxToActionIdx = {};
        window.__actionIdxToRawIdx = {};
        {
            let ai = 0;
            for (let ri = 0; ri < rawActionsList.length; ri++) {
                while (ai < allActions.length && allActions[ai] !== rawActionsList[ri]) ai++;
                if (ai < allActions.length) {
                    window.__rawIdxToActionIdx[ri] = ai;
                    window.__actionIdxToRawIdx[ai] = ri;
                    ai++;
                }
            }
        }

        timelineSteps = [];
        rawActionsList.forEach((act, idx) => {
            if (act.result.class_name !== 'RecordDiscardTile') {
                timelineSteps.push(idx);
            }
        });

        const roundSelect = document.getElementById('roundSelect');
        roundSelect.innerHTML = '';

        timelineSteps.forEach((rawIdx, stepIdx) => {
            const act = rawActionsList[rawIdx];
            if (act.result && act.result.class_name === 'RecordNewRound') {
                const data = act.result.data;
                const windNames = ['東', '南', '西', '北'];
                const roundLabel = `${windNames[data.chang]}${data.ju + 1}局 ${data.ben}本場`;
                const opt = document.createElement('option');
                opt.value = stepIdx;
                opt.innerText = roundLabel;
                roundSelect.appendChild(opt);
            }
        });

        const slider = document.getElementById('actionSlider');
        slider.max = timelineSteps.length - 1;
        document.getElementById('timelineEnd').innerText = `最大: ${timelineSteps.length - 1}`;

        jumpToAction(0);
        fitMahjongTable();

    } catch (err) {
        console.error(err);
        alert(`初期化エラー: ${err.message}`);
    }
}

function fitMahjongTable() {
    const pane = document.querySelector('.simulator-pane');
    const table = document.querySelector('.mahjong-table');
    if (!pane || !table) return;
    const availW = pane.clientWidth;
    const availH = pane.clientHeight;
    const designW = table.offsetWidth;
    const designH = table.offsetHeight;
    const scale = Math.min(availW / designW, availH / designH, 1.0);
    table.style.transform = scale < 1.0 ? `scale(${scale})` : '';
}

const _paneResizeObserver = new ResizeObserver(() => fitMahjongTable());
(function watchPane() {
    const pane = document.querySelector('.simulator-pane');
    if (pane) { _paneResizeObserver.observe(pane); return; }
    setTimeout(watchPane, 100);
})();

function jumpToAction(targetStepIndex, isFromAutoPlay = false) {
    if (targetStepIndex < 0 || targetStepIndex >= timelineSteps.length) return;

    if (!isFromAutoPlay) {
        isPlaying = false;
        document.getElementById('btnPlay').innerText = '自動再生';
        if (playInterval) clearInterval(playInterval);
    }

    currentActionIndex = targetStepIndex;

    document.getElementById('actionSlider').value = targetStepIndex;
    document.getElementById('timelineCurrent').innerText = `手番: ${targetStepIndex}`;

    engine.reset();

    const maxRawIdx = timelineSteps[targetStepIndex];
    for (let i = 0; i <= maxRawIdx; i++) {
        engine.applyAction(rawActionsList[i]);
    }

    _renderFromPrecomputed();

    requestAnimationFrame(() => {
        renderBoard();
        updatePromptPreview();
    });
}

function jumpToRoundStart(actionIndexStr) {
    if (!actionIndexStr) return;
    jumpToAction(parseInt(actionIndexStr));
}

function step(direction, isFromAutoPlay = false) {
    const nextIdx = currentActionIndex + direction;
    if (nextIdx >= 0 && nextIdx < timelineSteps.length) {
        jumpToAction(nextIdx, isFromAutoPlay);
    }
}

function stepOwnTurn(direction) {
    let idx = currentActionIndex + direction;
    while (idx >= 0 && idx < timelineSteps.length) {
        const rawIdx = timelineSteps[idx];
        const act = rawActionsList[rawIdx];
        if (act && act.result && act.result.data) {
            const cls = act.result.class_name;
            const seat = act.result.data.seat;
            if ((cls === 'RecordDealTile' || cls === 'RecordDiscardTile') && seat === perspectiveSeat) {
                jumpToAction(idx);
                return;
            }
            if ((cls === 'RecordChiPengGang' || cls === 'RecordAnGangAddGang') && seat === perspectiveSeat) {
                jumpToAction(idx);
                return;
            }
            if (cls === 'RecordDealTile' && seat !== perspectiveSeat) {
                for (let ri = rawIdx - 1; ri >= 0; ri--) {
                    const pa = rawActionsList[ri];
                    if (pa && pa.result && pa.result.class_name === 'RecordDiscardTile') {
                        const pd = pa.result.data;
                        if (pd && pd.seat !== undefined && pd.tile) {
                            if (pd.seat === perspectiveSeat) break;
                            const hand = engine ? engine.hands[perspectiveSeat] : null;
                            if (hand && hand.length >= 1) {
                                const cnt = {};
                                hand.forEach(t => { cnt[t] = (cnt[t] || 0) + 1; });
                                if ((cnt[pd.tile] || 0) >= 2) { jumpToAction(idx); return; }
                            }
                        }
                        break;
                    }
                }
            }
        }
        idx += direction;
    }
}

function togglePlay() {
    const btn = document.getElementById('btnPlay');
    if (isPlaying) {
        isPlaying = false;
        btn.innerText = '自動再生';
        clearInterval(playInterval);
    } else {
        isPlaying = true;
        btn.innerText = '一時停止';
        playInterval = setInterval(() => {
            if (currentActionIndex < timelineSteps.length - 1) {
                step(1, true);
            } else {
                togglePlay();
            }
        }, 1000);
    }
}

document.addEventListener('keydown', function (event) {
    const tag = (event.target && event.target.tagName) || '';
    if (tag === 'SELECT' || tag === 'INPUT' || tag === 'TEXTAREA') {
        return;
    }
    if (event.key === 'ArrowLeft') {
        event.preventDefault();
        step(-1);
    } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        step(1);
    } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        stepOwnTurn(-1);
    } else if (event.key === 'ArrowDown') {
        event.preventDefault();
        stepOwnTurn(1);
    }
});

function changePerspective(seat) {
    perspectiveSeat = seat;
    const acc = gameData && gameData.head && (gameData.head.accounts || []).find(a => a.seat === seat);
    if (acc && acc.nickname) localStorage.setItem(MY_NICKNAME_KEY, acc.nickname);
    renderBoard();
    updatePromptPreview();
}

function switchTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    if (tab === 'coach') {
        document.querySelector('.tab-btn:first-child').classList.add('active');
        document.getElementById('contentCoach').classList.add('active');
    } else {
        document.querySelectorAll('.tab-btn')[1].classList.add('active');
        document.getElementById('contentPrompt').classList.add('active');
        updatePromptPreview();
    }
}

// ----- 卓面レンダリング -----
function renderBoard() {
    document.getElementById('displayRound').innerText = engine.roundName;
    document.getElementById('displayBen').innerText = `${engine.ben}本場`;
    const lb = document.getElementById('displayLiqibang');
    if (engine.liqibang > 0) {
        lb.innerText = `供託${engine.liqibang}本棒`;
        lb.style.display = '';
    } else {
        lb.style.display = 'none';
    }
    document.getElementById('displayLeftTiles').innerText = engine.leftTileCount;

    const doraContainer = document.getElementById('displayDoras');
    doraContainer.innerHTML = '';
    engine.doras.forEach(d => {
        const tileEl = document.createElement('div');
        tileEl.className = `tile ${getTileClass(d)}`;
        tileEl.innerText = getTileText(d);
        doraContainer.appendChild(tileEl);
    });
    for (let i = engine.doras.length; i < 5; i++) {
        const emptyTile = document.createElement('div');
        emptyTile.className = 'tile tile-back';
        doraContainer.appendChild(emptyTile);
    }

    const relativeSeats = [];
    for (let i = 0; i < 4; i++) {
        relativeSeats.push((perspectiveSeat + i) % 4);
    }
    const positions = ['bottom', 'right', 'top', 'left'];

    positions.forEach((pos, idx) => {
        const realSeat = relativeSeats[idx];

        const seatInfoEl = document.getElementById(`seatInfo${realSeat}`);
        seatInfoEl.className = `seat-info ${pos}`;
        if (engine.activeSeat === realSeat) {
            seatInfoEl.classList.add('active');
        }

        let ju = 0;
        const match = engine.roundName.match(/\d/);
        if (match) {
            ju = parseInt(match[0]) - 1;
        }
        const playerWindIdx = (realSeat - ju + 4) % 4;
        seatInfoEl.querySelector('.seat-wind').innerText = WIND_NAMES[playerWindIdx];
        seatInfoEl.querySelector('.seat-score').innerText = engine.scores[realSeat];

        const areaEl = document.getElementById(`area${realSeat}`);
        areaEl.setAttribute('data-pos', pos);
        areaEl.className = 'player-area';

        const diffsEl = document.getElementById(`seatDiffs${realSeat}`);
        if (pos === 'bottom') {
            const myScore = engine.scores[realSeat];
            const dirLabels = ['上家', '対面', '下家'];
            const otherSeats = [relativeSeats[3], relativeSeats[2], relativeSeats[1]];
            const diffs = otherSeats.map(s => {
                const diff = myScore - engine.scores[s];
                return diff;
            });
            diffsEl.style.display = 'inline-flex';
            diffsEl.innerHTML = diffs.map((d, i) => {
                const cls = d >= 0 ? 'seat-diff-plus' : 'seat-diff-minus';
                const sign = d >= 0 ? '+' : '';
                return `<span class="${cls}">${dirLabels[i]}:${sign}${d}</span>`;
            }).join('');
        } else {
            diffsEl.style.display = 'none';
        }

        const handEl = document.getElementById(`hand${realSeat}`);
        handEl.innerHTML = '';
        handEl.style.display = 'flex';
        handEl.style.gap = '2px';
        handEl.style.flexDirection = 'row';

        const hand = [...engine.hands[realSeat]];
        const lastTsumo = engine.lastTsumo[realSeat];

        if (lastTsumo) {
            const tsumoIdx = hand.lastIndexOf(lastTsumo);
            if (tsumoIdx !== -1) hand.splice(tsumoIdx, 1);
        }

        if (pos === 'bottom') {
            hand.forEach(t => {
                const tileEl = document.createElement('div');
                tileEl.className = `tile ${getTileClass(t)}`;
                tileEl.innerText = getTileText(t);
                handEl.appendChild(tileEl);
            });

            if (lastTsumo) {
                const gap = document.createElement('div');
                gap.className = 'tsumo-gap';
                handEl.appendChild(gap);

                const tsumoEl = document.createElement('div');
                tsumoEl.className = `tile ${getTileClass(lastTsumo)}`;
                tsumoEl.innerText = getTileText(lastTsumo);
                handEl.appendChild(tsumoEl);
            }
        } else {
            hand.forEach(t => {
                const tileEl = document.createElement('div');
                tileEl.className = 'tile tile-back';
                handEl.appendChild(tileEl);
            });

            if (lastTsumo) {
                const gap = document.createElement('div');
                gap.className = 'tsumo-gap';
                handEl.appendChild(gap);

                const tsumoEl = document.createElement('div');
                tsumoEl.className = 'tile tile-back';
                handEl.appendChild(tsumoEl);
            }
        }

        const riverEl = document.getElementById(`river${realSeat}`);
        riverEl.className = `river-${pos}`;
        riverEl.innerHTML = '';

        const discards = engine.discards[realSeat];
        discards.forEach((d, k) => {
            const tileEl = document.createElement('div');
            tileEl.className = `tile ${getTileClass(d.tile)}`;
            if (d.claimed) tileEl.classList.add('tile-claimed');
            if (d.moqie) tileEl.classList.add('tile-moqie');

            let rowIdx = 0;
            let colIdx = 0;
            if (k < 18) {
                rowIdx = Math.floor(k / 6);
                colIdx = k % 6;
            } else {
                rowIdx = 2;
                colIdx = k - 12;
            }

            if (pos === 'bottom') {
                tileEl.style.gridRow = `${rowIdx + 1}`;
                tileEl.style.gridColumn = `${colIdx + 1}`;
            } else if (pos === 'top') {
                tileEl.style.gridRow = `${3 - rowIdx}`;
                tileEl.style.gridColumn = `${12 - colIdx}`;
            } else if (pos === 'left') {
                tileEl.style.gridRow = `${colIdx + 1}`;
                tileEl.style.gridColumn = `${3 - rowIdx}`;
            } else if (pos === 'right') {
                tileEl.style.gridRow = `${12 - colIdx}`;
                tileEl.style.gridColumn = `${rowIdx + 1}`;
            }

            if (d.isLiqi) {
                if (pos === 'bottom' || pos === 'top') {
                    tileEl.classList.add('tile-horizontal');
                } else if (pos === 'right') {
                    tileEl.style.transform = 'rotate(180deg)';
                } else if (pos === 'left') {
                    tileEl.style.transform = 'rotate(0deg)';
                }
            } else {
                if (pos === 'right') {
                    tileEl.classList.add('tile-rotated-right');
                } else if (pos === 'left') {
                    tileEl.classList.add('tile-rotated-left');
                } else if (pos === 'top') {
                    tileEl.classList.add('tile-rotated-top');
                }
            }

            tileEl.innerText = getTileText(d.tile);
            riverEl.appendChild(tileEl);
        });

        const meldsEl = document.getElementById(`melds${realSeat}`);
        meldsEl.innerHTML = '';
        meldsEl.style.display = 'flex';
        meldsEl.style.gap = '8px';
        meldsEl.style.flexDirection = 'row';

        const baseRotationsDeg = {
            'bottom': 0,
            'right': -90,
            'top': 180,
            'left': 90
        };

        const melds = engine.melds[realSeat];
        melds.forEach(m => {
            const meldBlock = document.createElement('div');
            meldBlock.style.display = 'flex';
            meldBlock.style.gap = '2px';
            meldBlock.style.flexDirection = 'row';
            meldBlock.style.alignItems = 'flex-end';

            const slots = getMeldSlots(m, realSeat);

            slots.forEach(slot => {
                const slotEl = document.createElement('div');

                if (slot.type === 'stacked') {
                    slotEl.style.display = 'flex';
                    slotEl.style.gap = '2px';
                    slotEl.style.flexDirection = 'column';
                }

                slot.tiles.forEach((t, tileIdx) => {
                    const tileEl = document.createElement('div');

                    if (slot.type === 'back') {
                        tileEl.className = 'tile tile-back';
                    } else {
                        tileEl.className = `tile ${getTileClass(t)}`;
                        tileEl.innerText = getTileText(t);
                    }

                    let isVerticalOnScreen = (slot.type === 'vertical' || slot.type === 'back');

                    if (isVerticalOnScreen) {
                        tileEl.style.width = '32px';
                        tileEl.style.height = '44px';
                    } else {
                        tileEl.style.width = '44px';
                        tileEl.style.height = '32px';
                    }

                    tileEl.style.transform = 'rotate(0deg)';
                    slotEl.appendChild(tileEl);
                });

                meldBlock.appendChild(slotEl);
            });
            meldsEl.appendChild(meldBlock);
        });
    });

    if (typeof requestBotCoachEvaluation === 'function') {
        requestBotCoachEvaluation();
    }
    if (typeof requestBotCoachMeldEvaluation === 'function') {
        requestBotCoachMeldEvaluation();
    }
}

// ----- Geminiプロンプト生成 -----
function generatePromptText() {
    const names = ['席0', '席1', '席2', '席3'];
    if (gameData && gameData.head && gameData.head.accounts) {
        gameData.head.accounts.forEach(acc => {
            names[acc.seat] = acc.nickname;
        });
    }

    let ju = 0;
    const match = engine.roundName.match(/\d/);
    if (match) {
        ju = parseInt(match[0]) - 1;
    }
    const myWind = WIND_NAMES[(perspectiveSeat - ju + 4) % 4];
    const changWind = engine.roundName.charAt(0);

    const hand = [...engine.hands[perspectiveSeat]];
    const lastTsumo = engine.lastTsumo[perspectiveSeat];

    if (lastTsumo) {
        const tsumoIdx = hand.lastIndexOf(lastTsumo);
        if (tsumoIdx !== -1) hand.splice(tsumoIdx, 1);
    }
    hand.sort(compareTiles);

    let handStr = hand.map(t => getTileText(t)).join(' ');
    let tsumoStr = lastTsumo ? getTileText(lastTsumo) : 'なし';

    let meldsStr = 'なし';
    const melds = engine.melds[perspectiveSeat];
    if (melds.length > 0) {
        meldsStr = melds.map(m => {
            const tiles = m.tiles.map(t => getTileText(t)).join(', ');
            const fromName = m.froms.some(f => f !== perspectiveSeat) ? '鳴き' : '暗槓';
            return `[${tiles}] (${fromName})`;
        }).join(' / ');
    }

    let otherMeldsStr = '';
    for (let i = 0; i < 4; i++) {
        if (i === perspectiveSeat) continue;
        const oMelds = engine.melds[i];
        if (oMelds.length > 0) {
            const oMeldText = oMelds.map(m => `[${m.tiles.map(t => getTileText(t)).join(', ')}]`).join(' ');
            otherMeldsStr += `* ${names[i]} (${WIND_NAMES[(i - ju + 4) % 4]}家): ${oMeldText}\n`;
        }
    }
    if (!otherMeldsStr) otherMeldsStr = '* なし\n';

    let riversStr = '';
    for (let i = 0; i < 4; i++) {
        const discards = engine.discards[i];
        const discText = discards.map(d => {
            let t = getTileText(d.tile);
            if (d.isLiqi) t += '(立直)';
            if (d.moqie) t += '(ツモ切り)';
            if (d.claimed) t += '(鳴かれ)';
            return t;
        }).join(' -> ');
        const label = i === perspectiveSeat ? `${names[i]} (自分 / ${WIND_NAMES[(i - ju + 4) % 4]}家)` : `${names[i]} (${WIND_NAMES[(i - ju + 4) % 4]}家)`;
        riversStr += `* ${label}の河: ${discText || 'なし'}\n`;
    }

    const myTurnCount = engine.discards[perspectiveSeat].length + (lastTsumo ? 1 : 0);

    let prompt = `### 麻雀 局面検討プロンプト

現在の状況において、以下の観点を考慮して思考プロセスを含め詳細に検討してください:
- 何を切るのが最適か (牌効率、点数状況、他家の副露状況、巡目、残り山牌数)
- 最もテンパイに近い打牌候補 と 安全牌を考慮した守備的な打牌候補 (それぞれメリット・デメリット)
- ドラ表示牌に対応するドラ牌 (実際にアガリ時に翻がつく牌)

#### 1. 基本情報
* 局情報: ${engine.roundName} ${engine.ben}本場
* 積み棒: ${engine.ben}本 (供託立直棒: ${engine.liqibang}本)
* 残り山牌数: ${engine.leftTileCount}枚
* ドラ表示牌: ${engine.doras.map(d => `${getTileText(d)}（ドラ${getTileText(doraIndicatorToDora(d))}）`).join(', ')}
* 現在の巡目: ${myTurnCount}巡目

#### 2. 自風・点数状況
* 場風: ${changWind}
* 自風: ${myWind}
* 席状況と点数:
`;

    for (let i = 0; i < 4; i++) {
        const wind = WIND_NAMES[(i - ju + 4) % 4];
        const isMe = i === perspectiveSeat ? ' (自分)' : '';
        prompt += `  * ${wind}家: ${names[i]}${isMe} / ${engine.scores[i]}点\n`;
    }

    prompt += `
#### 3. 自分の手牌
* 手牌 (13枚): ${hand.map(t => getTileText(t)).join(' ')}
* ツモ牌: ${tsumoStr}
* 副露 (フーロ): ${meldsStr}

#### 4. 他家の副露 (フーロ) 状況
${otherMeldsStr}
#### 5. 全員の河 (捨て牌履歴)
${riversStr}
`;
    return prompt;
}

function updatePromptPreview() {
    if (!gameData) return;
    const prompt = generatePromptText();
    document.getElementById('promptPreview').innerText = prompt;
}

window.addEventListener('DOMContentLoaded', loadGame);

// ----- BOTコーチング -----
function buildCoachPayload(includeTsumo) {
    if (!engine) return null;
    const mySeat = perspectiveSeat;
    const hand = [...engine.hands[mySeat]];
    const tsumo = engine.lastTsumo[mySeat];
    const myTsumoCount = engine.discards[mySeat].length + (tsumo ? 1 : 0);
    const tsumoCount = 4 * (myTsumoCount - 1) + (mySeat + 1);

    if (includeTsumo !== false && tsumo) {
        const idx = hand.indexOf(tsumo);
        if (idx !== -1) hand.splice(idx, 1);
        hand.push(tsumo);
    }

    const river = [[], [], [], []];
    const river_moqie = [[], [], [], []];
    for (let i = 0; i < 4; i++) {
        river[i] = engine.discards[i].map(d => d.tile);
        river_moqie[i] = engine.discards[i].map(d => !!(d && d.moqie));
    }

    const melds = [[], [], [], []];
    for (let i = 0; i < 4; i++) {
        melds[i] = engine.melds[i].map(m => ({
            type: m.type,
            tiles: m.tiles,
            froms: m.froms,
            tile_states: m.tile_states || []
        }));
    }

    const reach_states = [];
    for (let i = 0; i < 4; i++) {
        const seatDiscards = engine.discards[i] || [];
        let isReach = false;
        let reachTurn = -1;
        let totalPrior = 0;
        for (let k = 0; k < seatDiscards.length; k++) {
            if (seatDiscards[k].isLiqi) {
                isReach = true;
                reachTurn = totalPrior;
                break;
            }
            totalPrior += 1;
        }
        reach_states.push({
            is_reach: isReach,
            reach_turn: reachTurn,
            is_ippatsu: false
        });
    }

    let ju = 0;
    const match = engine.roundName.match(/\d/);
    if (match) ju = parseInt(match[0]) - 1;
    const chang = Math.floor(ju / 4);

    const payload = {
        my_seat: mySeat,
        hand: hand,
        tsumo: (includeTsumo !== false) ? null : tsumo,
        melds: melds,
        river: river,
        river_moqie: river_moqie,
        scores: engine.scores,
        doras: engine.doras,
        tsumo_count: tsumoCount,
        chang: chang,
        ju: ju % 4,
        ben: engine.ben,
        liqibang: engine.liqibang,
        left_tile_count: engine.leftTileCount,
        reach_states: reach_states
    };
    const ps = gameData && gameData.head && gameData.head.player_stats;
    if (ps) {
        payload.player_stats = ps;
    }
    return payload;
}

function _hashPayload(p) {
    return JSON.stringify({
        h: p.hand, m: p.melds, r: p.river, d: p.doras,
        t: p.tsumo_count, l: p.left_tile_count, s: p.scores, x: p.my_seat
    });
}

function _renderFromPrecomputed() {
    if (!window.__precomputedActions || !window.__rawIdxToActionIdx) return false;
    const cri = timelineSteps[currentActionIndex];
    if (cri === undefined) return false;
    const nextRawIdx = cri + 1;
    const actionIdx = window.__rawIdxToActionIdx[nextRawIdx];
    if (actionIdx === undefined) return false;
    const pre = window.__precomputedActions[String(actionIdx)];
    if (!pre || !pre.recommended) return false;
    const data = {
        status: 'ok',
        recommended: pre.recommended,
        near_tiles: pre.near_tiles || [],
        push_score: pre.push_score || 0,
        strategy_details: pre.strategy_details || {},
        evaluations: pre.evaluations || [],
        should_riichi: pre.should_riichi !== undefined ? pre.should_riichi : null,
        riichi_reason: pre.riichi_reason || '',
        kyushu_kyuhai: pre.kyushu_kyuhai || null,
        sufutsusenru: pre.sufutsusenru || null,
        summary: pre.summary || null,
        recommended_tsumogiri: pre.recommended_tsumogiri || false,
        karagiri_reason: pre.karagiri_reason || '',
    };
    renderBotCoachUI(data);
    const recommendedEval = (pre.evaluations || []).find(e => e.tile === pre.recommended);
    let reasonText = recommendedEval && recommendedEval.reason
        ? recommendedEval.reason
        : (pre.reason || `「${pre.recommended}」推奨`);
    if (data.karagiri_reason) {
        reasonText += '<br>' + data.karagiri_reason;
    }
    renderReasonForTile(reasonText);
    window.__lastCoachRecommended = data.recommended;
    window.__lastCoachNear = pre.near_tiles;
    highlightRecommendedTile(data.recommended, pre.near_tiles, data.recommended_tsumogiri);
    return true;
}

function renderBotCoachUI(data) {
    if (!data || data.status !== 'ok') {
        clearBotCoachUI();
        return;
    }
    document.getElementById('botCoachWait').style.display = 'none';

    const isRiichi = data.is_riichi_active || false;

    if (isRiichi) {
        document.getElementById('botCoachStatus').innerHTML = `手番: ${data.summary ? data.summary.tsumo_count : 0} / <strong>リーチ中</strong>`;

        const recBox = document.getElementById('botCoachRecommend');
        recBox.style.display = 'flex';
        const recTile = document.getElementById('botCoachRecommendTile');

        if (data.can_kan) {
            recTile.className = 'bot-coach-recommend-tile ' + getTileClass(data.kan_tile);
            recTile.innerText = getTileText(data.kan_tile);
            document.getElementById('botCoachRecommendText').innerHTML =
                `<strong>暗槓可能牌があります</strong>`;
        } else {
            recTile.className = 'bot-coach-recommend-tile ' + getTileClass(data.recommended);
            recTile.innerText = getTileText(data.recommended);
            document.getElementById('botCoachRecommendText').innerHTML =
                `<strong>ツモ切りを推奨します</strong>`;
        }

        document.getElementById('botCoachNear').style.display = 'none';
        document.getElementById('botCoachStrategy').style.display = 'none';
        document.getElementById('botCoachEvalList').innerHTML = '';
    } else {
        _karagiriReason = data.karagiri_reason || '';
        document.getElementById('botCoachStatus').innerHTML = `手番: ${data.summary ? data.summary.tsumo_count : 0} / 推奨: <strong>${getTileText(data.recommended) || '-'}</strong>`;

        const recBox = document.getElementById('botCoachRecommend');
        recBox.style.display = 'flex';
        const recTile = document.getElementById('botCoachRecommendTile');
        recTile.className = 'bot-coach-recommend-tile ' + getTileClass(data.recommended);
        recTile.innerText = getTileText(data.recommended);
        document.getElementById('botCoachRecommendText').innerHTML =
            `<strong>${getTileText(data.recommended)}</strong> を切るのが最も評価値が高いと算出されました。`;

        if (data.near_tiles && data.near_tiles.length > 0) {
            document.getElementById('botCoachNear').style.display = 'block';
            document.getElementById('botCoachNearLabel').innerText = '同等候補: ';
            document.getElementById('botCoachNearTiles').innerHTML = data.near_tiles.map(t =>
                `<span class="tile ${getTileClass(t)}" style="display:inline-block;padding:2px 6px;margin:1px;border-radius:4px;font-size:0.75rem;">${getTileText(t)}</span>`
            ).join('');
        } else {
            document.getElementById('botCoachNear').style.display = 'none';
        }

        renderStrategyDetails(data.strategy_details);
        renderFlyRisk(data.strategy_details ? data.strategy_details.fly_risk : null);
    }

    const riichiPanel = document.getElementById('botCoachRiichiPanel');
    if (!isRiichi && data.should_riichi !== null && data.should_riichi !== undefined) {
        riichiPanel.style.display = 'flex';
        const decisionEl = document.getElementById('botCoachRiichiDecision');
        const reasonEl = document.getElementById('botCoachRiichiReason');
        if (data.should_riichi) {
            decisionEl.innerText = '立直推奨';
            decisionEl.style.color = '#3498db';
            riichiPanel.style.background = 'rgba(52, 152, 219, 0.15)';
            riichiPanel.style.borderColor = '#3498db';
        } else {
            decisionEl.innerText = '黙聴 (ダマテン) 推奨';
            decisionEl.style.color = '#e67e22';
            riichiPanel.style.background = 'rgba(230, 126, 34, 0.15)';
            riichiPanel.style.borderColor = '#e67e22';
            riichiPanel.style.borderLeftColor = '#e67e22';
        }
        const reasonText = (data.riichi_reason || '').replace(/\n/g, '<br>');
        reasonEl.innerHTML = reasonText;
    } else {
        riichiPanel.style.display = 'none';
    }

    const kanPanel = document.getElementById('botCoachKanPanel');
    if (isRiichi && data.can_kan) {
        kanPanel.style.display = 'flex';
        const decisionEl = document.getElementById('botCoachKanDecision');
        const reasonEl = document.getElementById('botCoachKanReason');
        if (data.should_kan) {
            decisionEl.innerText = '暗槓推奨';
            decisionEl.style.color = '#2ecc71';
            kanPanel.style.background = 'rgba(46, 204, 113, 0.15)';
            kanPanel.style.borderColor = '#2ecc71';
        } else {
            decisionEl.innerText = '暗槓せずツモ切り推奨';
            decisionEl.style.color = '#95a5a6';
            kanPanel.style.background = 'rgba(149, 165, 166, 0.15)';
            kanPanel.style.borderColor = '#95a5a6';
            kanPanel.style.borderLeftColor = '#95a5a6';
        }
        reasonEl.innerHTML = (data.kan_reason || '').replace(/\n/g, '<br>');
    } else {
        kanPanel.style.display = 'none';
    }

    const kyushuPanel = document.getElementById('botCoachKyushuPanel');
    if (data.kyushu_kyuhai && data.kyushu_kyuhai.can_declare) {
        kyushuPanel.style.display = 'flex';
        const decisionEl = document.getElementById('botCoachKyushuDecision');
        const reasonEl = document.getElementById('botCoachKyushuReason');
        if (data.kyushu_kyuhai.recommend_declare) {
            decisionEl.innerText = '流局推奨';
            decisionEl.style.color = '#8b5cf6';
            kyushuPanel.style.background = 'rgba(139, 92, 246, 0.15)';
            kyushuPanel.style.borderColor = '#8b5cf6';
        } else {
            decisionEl.innerText = '国士無双推奨（流局しない）';
            decisionEl.style.color = '#2ecc71';
            kyushuPanel.style.background = 'rgba(46, 204, 113, 0.15)';
            kyushuPanel.style.borderColor = '#2ecc71';
            kyushuPanel.style.borderLeftColor = '#2ecc71';
        }
        reasonEl.innerHTML = (data.kyushu_kyuhai.reason || '').replace(/\n/g, '<br>');
    } else {
        kyushuPanel.style.display = 'none';
    }

    const sufutsuPanel = document.getElementById('botCoachSufutsuPanel');
    if (data.sufutsusenru && data.sufutsusenru.is_possible) {
        sufutsuPanel.style.display = 'flex';
        const decisionEl = document.getElementById('botCoachSufutsuDecision');
        const reasonEl = document.getElementById('botCoachSufutsuReason');
        if (data.sufutsusenru.recommend_discard) {
            decisionEl.innerText = '四風子連打で流局推奨';
            decisionEl.style.color = '#fbbf24';
            sufutsuPanel.style.background = 'rgba(251, 191, 36, 0.15)';
            sufutsuPanel.style.borderColor = '#fbbf24';
        } else {
            decisionEl.innerText = '四風子連打回避推奨';
            decisionEl.style.color = '#2ecc71';
            sufutsuPanel.style.background = 'rgba(46, 204, 113, 0.15)';
            sufutsuPanel.style.borderColor = '#2ecc71';
            sufutsuPanel.style.borderLeftColor = '#2ecc71';
        }
        reasonEl.innerHTML = (data.sufutsusenru.reason || '').replace(/\n/g, '<br>');
    } else {
        sufutsuPanel.style.display = 'none';
    }

    updateSpecialPanelVisibility();

    const list = document.getElementById('botCoachEvalList');
    if (!isRiichi) {
        const tierNames = (data.strategy_details && data.strategy_details.v2_tier_names) || ['向聴数', '受入/安全度', '手役補正', '戦術ランク/愚形', 'ドラ損失/安全度', '安全度', '予備'];
        _activeTile = null;
        list.innerHTML = '';
        const evals = data.evaluations || [];
        const maxAbs = Math.max(1, ...evals.map(e => Math.abs(e.score)));
        evals.forEach(ev => {
            ev.tier_names = ev.tier_names || tierNames;
            const row = document.createElement('div');
            row.className = 'bot-coach-eval-row' + (ev.tile === data.recommended ? ' is-recommended' : '') + (ev.is_blunder ? ' is-blunder' : '');
            row.dataset.tile = ev.tile;

            const tileEl = document.createElement('div');
            tileEl.className = 'bot-coach-eval-tile ' + getTileClass(ev.tile);
            tileEl.innerText = getTileText(ev.tile);

            const bar = document.createElement('div');
            bar.className = 'bot-coach-eval-bar';
            const fill = document.createElement('div');
            fill.className = 'bot-coach-eval-bar-fill' + (ev.score < 0 ? ' negative' : '');
            const pct = Math.max(0, Math.min(100, (Math.abs(ev.score) / maxAbs) * 100));
            fill.style.width = pct.toFixed(1) + '%';
            bar.appendChild(fill);

            const score = document.createElement('div');
            score.className = 'bot-coach-eval-score';
            const shanten = ev.shanten;
            let shantenLabel;
            if (shanten <= -1) shantenLabel = '和了';
            else if (shanten === 0) shantenLabel = '聴牌';
            else shantenLabel = `${shanten}向`;
            score.innerText = `${ev.score.toFixed(0)} (${shantenLabel})`;

            const meta = document.createElement('div');
            meta.className = 'bot-coach-eval-meta';
            let metaHtml = `<span>${ev.safety_desc || ''}</span> <span>${ev.attack_desc || ''}</span>`;
            if (ev.is_blunder) {
                metaHtml += ` <span style="color:#e74c3c;font-weight:bold;">⚠ -${ev.blunder_score}</span>`;
            }
            meta.innerHTML = metaHtml;

            const rightCol = document.createElement('div');
            rightCol.style.cssText = 'display:flex;flex-direction:column;gap:2px;min-width:0;';
            const topRow = document.createElement('div');
            topRow.style.cssText = 'display:flex;align-items:center;gap:6px;';
            topRow.appendChild(bar);
            topRow.appendChild(score);
            rightCol.appendChild(topRow);
            rightCol.appendChild(meta);

            row.appendChild(tileEl);
            row.appendChild(rightCol);

            row.addEventListener('mouseenter', () => selectEvalRow(row, ev, data.recommended));
            row.addEventListener('click', () => selectEvalRow(row, ev, data.recommended));
            list.appendChild(row);
        });

        const recEntry = evals.find(e => e.tile === data.recommended);
        if (recEntry) {
            _activeTile = recEntry.tile;
            const recRow = list.querySelector(`.bot-coach-eval-row[data-tile="${data.recommended}"]`);
            if (recRow) {
                recRow.classList.add('is-active');
                recEntry._isBest = true;
                const reasonMatch = (recEntry.reason || '').match(/^[①②③④⑤⑥]/);
                const layerMap = {'①': 0, '②': 1, '③': 2, '④': 3, '⑤': 4, '⑥': 5};
                recEntry._decidingLayer = reasonMatch ? (layerMap[reasonMatch[0]] !== undefined ? layerMap[reasonMatch[0]] : -1) : -1;
                renderTuplePanel(recEntry);
                let reasonText = recEntry.reason || `「${getTileText(data.recommended)}」推奨 (総合スコア最高)。`;
                if (_karagiriReason) {
                    reasonText += '<br>' + _karagiriReason;
                }
                renderReasonForTile(reasonText);
            }
        }
    } else {
        _karagiriReason = data.karagiri_reason || '';
        if (data.can_kan) {
            renderReasonForTile(data.kan_reason);
        } else {
            renderReasonForTile("リーチ中につき、基本的にはツモ牌をそのまま切ります。");
        }
    }
}

function requestBotCoachEvaluation() {
    const payload = buildCoachPayload();
    if (!payload) {
        clearBotCoachUI();
        return;
    }
    const tsumoTile = engine ? engine.lastTsumo[perspectiveSeat] : null;
    if (tsumoTile === null) {
        const mySeat = payload.my_seat || 0;
        const myMelds = (payload.melds && payload.melds[mySeat]) || [];
        const myMeldTiles = myMelds.reduce((s, m) => s + (m.tiles ? m.tiles.length : 0), 0);
        const totalTiles = (payload.hand ? payload.hand.length : 0) + myMeldTiles;
        if (totalTiles < 14) {
            clearBotCoachUI();
            return;
        }
    } else if (!payload.hand.includes(tsumoTile)) {
        clearBotCoachUI();
        return;
    }
    const hash = _hashPayload(payload);
    if (hash === _lastCoachHash && _coachEvalSeq > 0) return;
    _lastCoachHash = hash;

    if (_renderFromPrecomputed()) return;

    if (_coachEvalAbort) {
        try { _coachEvalAbort.abort(); } catch (_) {}
    }
    const mySeq = ++_coachEvalSeq;
    const ac = new AbortController();
    _coachEvalAbort = ac;
    fetch('/api/evaluate-v2', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: ac.signal
    })
        .then(r => r.json())
        .then(data => {
            if (mySeq !== _coachEvalSeq) return;
            renderBotCoachUI(data);
            window.__lastCoachRecommended = data.recommended || null;
            window.__lastCoachNear = data.near_tiles || [];
            highlightRecommendedTile(data.recommended || null, data.near_tiles, data.recommended_tsumogiri || false);
        })
        .catch(err => {
            if (err && err.name === 'AbortError') return;
            console.warn('coach api error', err);
        });
}

function requestBotCoachMeldEvaluation() {
    const mp = document.getElementById("botCoachMeldPanel");
    if (!mp) return;
    if (!engine || currentActionIndex < 0) { mp.classList.remove('is-visible'); mp.dataset.active = "0"; return; }
    mp.classList.remove('is-visible');
    mp.dataset.active = "0";
    const mySeat = perspectiveSeat;
    let hand = [...engine.hands[mySeat]];
    if (!hand || hand.length < 1) return;
    if (currentActionIndex >= timelineSteps.length) return;
    const cri = timelineSteps[currentActionIndex];
    let di = -1, dt = null;
    if (cri > 0) {
        const a = rawActionsList[cri - 1];
        if (a && a.result && a.result.class_name === "RecordDiscardTile") {
            const dd = a.result.data;
            if (dd && dd.seat !== undefined && dd.seat !== mySeat && dd.tile) { di = dd.seat; dt = dd.tile; }
        }
    }
    const tsumo = engine.lastTsumo ? engine.lastTsumo[mySeat] : null;
    if (tsumo && engine.melds && engine.melds[mySeat]) {
        for (const meld of engine.melds[mySeat]) {
            if (meld.tiles && meld.tiles.length === 3 && meld.tiles[0] === tsumo) {
                const candidates = [{ type: "skip", label: "スキップ", tiles: [], froms: [] }];
                candidates.push({ type: "kakan", label: "加槓", tiles: [tsumo], froms: [mySeat] });
                const payload = buildCoachPayload(true);
                if (!payload) return;
                payload.meld_candidates = candidates;
                _send_meld_eval(payload, '加槓可能です', mp);
                return;
            }
        }
    }
    const ankanTile = _find_ankan_tile(hand);
    if (ankanTile) {
        const candidates = [{ type: "skip", label: "スキップ", tiles: [], froms: [] }];
        candidates.push({ type: "ankan", label: "暗槓", tiles: [ankanTile, ankanTile, ankanTile, ankanTile], froms: [mySeat, mySeat, mySeat, mySeat] });
        const payload = buildCoachPayload(true);
        if (!payload) return;
        payload.meld_candidates = candidates;
        _send_meld_eval(payload, '暗槓可能です', mp);
        return;
    }
    if (di < 0) return;
    const curAct = rawActionsList[cri];
    if (curAct && curAct.result && curAct.result.class_name === 'RecordChiPengGang') {
        const cd = curAct.result.data;
        if (cd && cd.seat === mySeat) {
            cd.tiles.forEach((t, i) => {
                if (cd.froms[i] === mySeat) {
                    hand.push(t);
                }
            });
        }
    }
    const sl = ["東", "南", "西", "北"];
    const hc = {}; hand.forEach(t => { const k = t[0] === '0' ? '5' + t[1] : t; hc[k] = (hc[k] || 0) + 1; });
    const dtBase = dt[0] === '0' ? '5' + dt[1] : dt;
    const candidates = [{ type: "skip", label: "スキップ", tiles: [], froms: [] }];
    let found = false;
    if ((hc[dtBase] || 0) >= 2) {
        candidates.push({ type: "pon", label: "ポン", tiles: [dtBase, dtBase, dtBase], froms: [di, mySeat, mySeat] });
        found = true;
    }
    const cs = (di + 1) % 4;
    if (cs === mySeat) {
        const tt = dtBase.slice(-1);
        if ("mps".includes(tt)) {
            const n = parseInt(dtBase[0]);
            if (!isNaN(n)) {
                for (let a = Math.max(1, n - 2); a <= Math.min(7, n); a++) {
                    if (![a, a + 1, a + 2].includes(n)) continue;
                    const con = [a, a + 1, a + 2].filter(x => x !== n);
                    const ta = con[0] + tt, tb = con[1] + tt;
                    if ((hc[ta] || 0) >= 1 && (hc[tb] || 0) >= 1) {
                        candidates.push({ type: "chi", label: "チー(" + ta + tb + ")", tiles: [dtBase, ta, tb], froms: [di, mySeat, mySeat] });
                        found = true; break;
                    }
                }
            }
        }
    }
    if ((hc[dtBase] || 0) >= 3) {
        candidates.push({ type: "daiminkan", label: "大明槓", tiles: [dtBase, dtBase, dtBase, dtBase], froms: [di, mySeat, mySeat, mySeat] });
        found = true;
    }
    if (!found) return;
    const payload = buildCoachPayload(false);
    if (!payload) return;
    if (curAct && curAct.result && curAct.result.class_name === 'RecordChiPengGang') {
        const cd = curAct.result.data;
        if (cd && cd.seat === mySeat) {
            cd.tiles.forEach((t, i) => {
                if (cd.froms[i] === mySeat) {
                    payload.hand.push(t);
                }
            });
            payload.melds[mySeat].pop();
        }
    }
    payload.meld_candidates = candidates;
    _send_meld_eval(payload, sl[di] + '家が <b>' + getTileText(dt) + '</b> を捨てました', mp);
}

function _send_meld_eval(payload, statusText, mp) {
    payload.meld_candidates = payload.meld_candidates || [];
    const statusEl = document.getElementById('botCoachMeldStatus');
    statusEl.innerHTML = '<span style="color:var(--text-muted);">評価中...</span>';
    mp.dataset.active = "1";
    mp.classList.add('is-loading');
    mp.classList.add('is-visible');

    try {
        const mySeat = perspectiveSeat;
        const cri = timelineSteps[currentActionIndex];
        if (cri !== undefined && window.__rawIdxToActionIdx) {
            const actionIdx = window.__rawIdxToActionIdx[cri];
            const preMeld = window.__precomputedMeldDecisions && window.__precomputedMeldDecisions[String(actionIdx)];
            if (preMeld && preMeld[String(mySeat)] && preMeld[String(mySeat)].candidates && preMeld[String(mySeat)].candidates.length) {
                const seatData = preMeld[String(mySeat)];
                const validCands = seatData.candidates.filter(c => !c.forbidden);
                let recommendedType = null;
                if (validCands.length) {
                    const best = validCands.reduce((a, b) => (a.best_score || -Infinity) > (b.best_score || -Infinity) ? a : b);
                    recommendedType = best.type;
                }
                const data = { status: 'ok', recommended: recommendedType, candidates: seatData.candidates };
                mp.classList.remove('is-loading');
                _render_meld_eval(data, statusText, mp);
                return;
            }
        }
    } catch (e) {
    }

    if (_meldEvalAbort) {
        try { _meldEvalAbort.abort(); } catch (_) {}
    }
    const mySeq = ++_meldEvalSeq;
    const ac = new AbortController();
    _meldEvalAbort = ac;
    fetch('/api/evaluate-meld-v2', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: ac.signal
    }).then(r => r.json()).then(data => {
        if (mySeq !== _meldEvalSeq) return;
        mp.classList.remove('is-loading');
        if (data.status !== 'ok' || !data.candidates) { mp.classList.remove('is-visible'); return; }
        _render_meld_eval(data, statusText, mp);
    }).catch(function () { mp.classList.remove('is-loading'); mp.classList.remove('is-visible'); });
}
