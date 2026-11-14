// ----- 定数 -----
const TILE_NAMES = {
    '1m': '1萬', '2m': '2萬', '3m': '3萬', '4m': '4萬', '5m': '5萬', '6m': '6萬', '7m': '7萬', '8m': '8萬', '9m': '9萬', '0m': '赤5萬',
    '1p': '1筒', '2p': '2筒', '3p': '3筒', '4p': '4筒', '5p': '5筒', '6p': '6筒', '7p': '7筒', '8p': '8筒', '9p': '9筒', '0p': '赤5筒',
    '1s': '1索', '2s': '2索', '3s': '3索', '4s': '4索', '5s': '5索', '6s': '6索', '7s': '7索', '8s': '8索', '9s': '9索', '0s': '赤5索',
    '1z': '東', '2z': '南', '3z': '西', '4z': '北', '5z': '白', '6z': '發', '7z': '中'
};

const WIND_NAMES = ['東', '南', '西', '北'];

// ----- 純粋関数・タイルユーティリティ -----

function compareTiles(a, b) {
    const suitOrder = { 'm': 0, 'p': 1, 's': 2, 'z': 3 };
    const suitA = a.slice(1);
    const suitB = b.slice(1);

    if (suitOrder[suitA] !== suitOrder[suitB]) {
        return suitOrder[suitA] - suitOrder[suitB];
    }

    const numA = a.charAt(0) === '0' ? 4.5 : parseInt(a.charAt(0)) || 0;
    const numB = b.charAt(0) === '0' ? 4.5 : parseInt(b.charAt(0)) || 0;

    return numA - numB;
}

function getMeldSlots(m, seat) {
    const type = m.type;
    const tiles = m.tiles;
    const froms = m.froms;

    if (type === 'ankan') {
        return [
            { type: 'back', tiles: [tiles[0]], froms: [froms[0]] },
            { type: 'vertical', tiles: [tiles[1]], froms: [froms[1]] },
            { type: 'vertical', tiles: [tiles[2]], froms: [froms[2]] },
            { type: 'back', tiles: [tiles[3]], froms: [froms[3]] }
        ];
    }

    let claimedIdx = -1;
    for (let i = 0; i < froms.length; i++) {
        if (froms[i] !== seat) {
            claimedIdx = i;
            break;
        }
    }

    if (claimedIdx === -1) {
        return tiles.map((t, idx) => ({
            type: 'vertical',
            tiles: [t],
            froms: [froms[idx]]
        }));
    }

    const donor = froms[claimedIdx];
    const diff = (donor - seat + 4) % 4;

    const ownedTiles = [];
    const ownedFroms = [];
    tiles.forEach((t, i) => {
        if (i !== claimedIdx) {
            ownedTiles.push(t);
            ownedFroms.push(froms[i]);
        }
    });

    if (type === 'minggang') {
        const slots = [];
        if (diff === 3) {
            slots.push({ type: 'horizontal', tiles: [tiles[claimedIdx]], froms: [donor] });
            ownedTiles.forEach((t, i) => slots.push({ type: 'vertical', tiles: [t], froms: [ownedFroms[i]] }));
        } else if (diff === 2) {
            slots.push({ type: 'vertical', tiles: [ownedTiles[0]], froms: [ownedFroms[0]] });
            slots.push({ type: 'horizontal', tiles: [tiles[claimedIdx]], froms: [donor] });
            slots.push({ type: 'vertical', tiles: [ownedTiles[1]], froms: [ownedFroms[1]] });
            slots.push({ type: 'vertical', tiles: [ownedTiles[2]], froms: [ownedFroms[2]] });
        } else {
            ownedTiles.forEach((t, i) => slots.push({ type: 'vertical', tiles: [t], froms: [ownedFroms[i]] }));
            slots.push({ type: 'horizontal', tiles: [tiles[claimedIdx]], froms: [donor] });
        }
        return slots;
    } else if (type === 'kankan') {
        const addedTile = ownedTiles.pop();
        const addedFrom = ownedFroms.pop();

        const slots = [];
        if (diff === 3) {
            slots.push({ type: 'vertical', tiles: [ownedTiles[0]], froms: [ownedFroms[0]] });
            slots.push({ type: 'vertical', tiles: [ownedTiles[1]], froms: [ownedFroms[1]] });
            slots.push({ type: 'stacked', tiles: [tiles[claimedIdx], addedTile], froms: [donor, addedFrom] });
        } else if (diff === 2) {
            slots.push({ type: 'vertical', tiles: [ownedTiles[0]], froms: [ownedFroms[0]] });
            slots.push({ type: 'stacked', tiles: [tiles[claimedIdx], addedTile], froms: [donor, addedFrom] });
            slots.push({ type: 'vertical', tiles: [ownedTiles[1]], froms: [ownedFroms[1]] });
        } else {
            slots.push({ type: 'stacked', tiles: [tiles[claimedIdx], addedTile], froms: [donor, addedFrom] });
            slots.push({ type: 'vertical', tiles: [ownedTiles[0]], froms: [ownedFroms[0]] });
            slots.push({ type: 'vertical', tiles: [ownedTiles[1]], froms: [ownedFroms[1]] });
        }
        return slots;
    } else {
        const zipped = ownedTiles.map((t, idx) => ({ tile: t, from: ownedFroms[idx] }));
        zipped.sort((a, b) => compareTiles(a.tile, b.tile));
        const sortedOwnedTiles = zipped.map(z => z.tile);
        const sortedOwnedFroms = zipped.map(z => z.from);

        const slots = [];
        if (diff === 3) {
            slots.push({ type: 'horizontal', tiles: [tiles[claimedIdx]], froms: [donor] });
            slots.push({ type: 'vertical', tiles: [sortedOwnedTiles[0]], froms: [sortedOwnedFroms[0]] });
            slots.push({ type: 'vertical', tiles: [sortedOwnedTiles[1]], froms: [sortedOwnedFroms[1]] });
        } else if (diff === 2) {
            slots.push({ type: 'vertical', tiles: [sortedOwnedTiles[0]], froms: [sortedOwnedFroms[0]] });
            slots.push({ type: 'horizontal', tiles: [tiles[claimedIdx]], froms: [donor] });
            slots.push({ type: 'vertical', tiles: [sortedOwnedTiles[1]], froms: [sortedOwnedFroms[1]] });
        } else {
            slots.push({ type: 'vertical', tiles: [sortedOwnedTiles[0]], froms: [sortedOwnedFroms[0]] });
            slots.push({ type: 'vertical', tiles: [sortedOwnedTiles[1]], froms: [sortedOwnedFroms[1]] });
            slots.push({ type: 'horizontal', tiles: [tiles[claimedIdx]], froms: [donor] });
        }
        return slots;
    }
}

function getTileClass(tile) {
    if (!tile) return '';
    if (tile.startsWith('0')) return 'tile-aka';
    const suite = tile.slice(1);
    return `tile-${suite}`;
}

function getTileText(tile) {
    if (!tile) return '';
    return TILE_NAMES[tile] || tile;
}

function convertTilesInString(str) {
    if (!str) return str;
    return str.replace(/(\d[zmps]r?)/g, function (m) {
        return TILE_NAMES[m] || m;
    });
}

function doraIndicatorToDora(indicator) {
    const suit = indicator[indicator.length - 1];
    let id;
    if (suit === 'm') id = parseInt(indicator[0]) - 1;
    else if (suit === 'p') id = 9 + (parseInt(indicator[0]) - 1);
    else if (suit === 's') id = 18 + (parseInt(indicator[0]) - 1);
    else id = 26 + parseInt(indicator[0]);

    let doraId;
    if (id < 27) {
        const base = Math.floor(id / 9) * 9;
        doraId = base + (id - base + 1) % 9;
    } else if (id < 31) {
        doraId = 27 + (id - 27 + 1) % 4;
    } else {
        doraId = 31 + (id - 31 + 1) % 3;
    }

    if (doraId < 9) return (doraId + 1) + 'm';
    if (doraId < 18) return (doraId - 9 + 1) + 'p';
    if (doraId < 27) return (doraId - 18 + 1) + 's';
    if (doraId === 27) return '1z';
    if (doraId === 28) return '2z';
    if (doraId === 29) return '3z';
    if (doraId === 30) return '4z';
    if (doraId === 31) return '5z';
    if (doraId === 32) return '6z';
    if (doraId === 33) return '7z';
    return indicator;
}

function _find_ankan_tile(hand) {
    const cnt = {};
    hand.forEach(t => { const k = t[0] === '0' ? '5' + t[1] : t; cnt[k] = (cnt[k] || 0) + 1; });
    for (const tile in cnt) {
        if (cnt[tile] >= 4) return tile;
    }
    return null;
}

// ----- DOM表示ユーティリティ -----
let _activeTile = null;
let _karagiriReason = '';

function clearBotCoachUI() {
    document.getElementById('botCoachWait').style.display = 'block';
    document.getElementById('botCoachStatus').innerText = '※手番ではありません';
    document.getElementById('botCoachRecommend').style.display = 'none';
    document.getElementById('botCoachRiichiPanel').style.display = 'none';
    document.getElementById('botCoachKanPanel').style.display = 'none';
    document.getElementById('botCoachKyushuPanel').style.display = 'none';
    document.getElementById('botCoachSufutsuPanel').style.display = 'none';
    document.getElementById('botCoachSpecialPanel').style.display = 'none';
    document.getElementById('botCoachStrategy').style.display = 'none';
    document.getElementById('botCoachTuplePanel').style.display = 'none';
    document.getElementById('botCoachFlyRisk').style.display = 'none';
    document.getElementById('botCoachReason').style.display = 'none';
    document.getElementById('botCoachEvalList').innerHTML = '';
    const df = document.getElementById('botCoachDetailFloating');
    if (df) df.classList.remove('is-shown');
}

function updateSpecialPanelVisibility() {
    const panel = document.getElementById('botCoachSpecialPanel');
    if (!panel) return;
    const rows = ['botCoachRiichiPanel', 'botCoachKanPanel', 'botCoachKyushuPanel', 'botCoachSufutsuPanel'];
    const anyVisible = rows.some(id => {
        const el = document.getElementById(id);
        return el && el.style.display !== 'none';
    });
    panel.style.display = anyVisible ? 'flex' : 'none';
}

(function() {
    const header = document.getElementById('botCoachStrategyHeader');
    const body = document.getElementById('botCoachStrategyBody');
    if (!header || !body) return;
    header.addEventListener('click', () => {
        const expanded = body.style.display !== 'none';
        body.style.display = expanded ? 'none' : 'block';
        header.classList.toggle('expanded', !expanded);
    });
})();

function renderStrategyDetails(details) {
    const box = document.getElementById('botCoachStrategy');
    const modeEl = document.getElementById('botCoachStrategyMode');
    const paramsEl = document.getElementById('botCoachStrategyParams');
    const threatEl = document.getElementById('botCoachStrategyThreat');

    if (!details) {
        box.style.display = 'none';
        return;
    }
    box.style.display = 'flex';

    const modeName = details.v2_mode_jp || details.mode || 'バランス';
    let badgeColor = '#10b981';
    let badgeBg = 'rgba(16, 185, 129, 0.15)';
    let badgeBorder = 'rgba(16, 185, 129, 0.3)';
    if (/攻撃|立直|副露|役満/.test(modeName)) {
        badgeColor = '#ef4444'; badgeBg = 'rgba(239, 68, 68, 0.15)'; badgeBorder = 'rgba(239, 68, 68, 0.3)';
    } else if (/防御|撤退|ベタオリ|守備/.test(modeName)) {
        badgeColor = '#3b82f6'; badgeBg = 'rgba(59, 130, 246, 0.15)'; badgeBorder = 'rgba(59, 130, 246, 0.3)';
    }
    modeEl.style.cssText = 'color:' + badgeColor + '; background:' + badgeBg + '; border:1px solid ' + badgeBorder + '; padding:3px 10px; border-radius:6px; font-size:0.78rem; font-weight:bold; text-shadow:0 0 6px ' + badgeColor + '40;';
    modeEl.innerText = modeName;

    const miniAttack = document.getElementById('botCoachMiniAttack');
    const miniThreat = document.getElementById('botCoachMiniThreat');
    const miniPush = document.getElementById('botCoachMiniPush');
    if (miniAttack) miniAttack.innerText = (details.v2_base_attack || 0).toFixed(2);
    if (miniThreat) miniThreat.innerText = (Math.max(0, ...(details.v2_opp_risks || [0]))).toFixed(2);
    if (miniPush) miniPush.innerText = (details.push_score || 0).toFixed(2);

    const flyRisk = details.fly_risk || {};
    const myScore = flyRisk.my_score !== undefined ? flyRisk.my_score : 25000;
    const estLoss = flyRisk.estimated_loss !== undefined ? flyRisk.estimated_loss : 8000;
    const threat = details.max_threat || 0.0;
    const attack = details.base_attack || 0.0;
    const push = details.push_score || 0.0;
    let flyBadge = '<span style="padding: 2px 6px; border-radius: 4px; font-size: 0.65rem; font-weight: bold; background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3);">安全 (Lv0)</span>';
    if (flyRisk.adjust < 0) {
        const severity = Math.abs(flyRisk.adjust) > 0.15 ? '危険 (Lv2)' : '警告 (Lv1)';
        const color = Math.abs(flyRisk.adjust) > 0.15 ? '#ef4444' : '#fbbf24';
        flyBadge = '<span style="padding: 2px 6px; border-radius: 4px; font-size: 0.65rem; font-weight: bold; background: ' + color + '20; color: ' + color + '; border: 1px solid ' + color + '40;">' + severity + '</span>';
    }
    const oppRisk = details.opponents_threat || [0.1, 0.1, 0.1];
    const shimoRisk = oppRisk[0] !== undefined ? oppRisk[0] : 0.1;
    const toimiRisk = oppRisk[1] !== undefined ? oppRisk[1] : 0.1;
    const kamiRisk = oppRisk[2] !== undefined ? oppRisk[2] : 0.1;
    const features = details.hand_features || {};
    const pair = features.pair_ratio !== undefined ? features.pair_ratio : 0.0;
    const honor = features.honor_ratio !== undefined ? features.honor_ratio : 0.0;
    const suit = features.suit_bias !== undefined ? features.suit_bias : 0.0;
    const yao = features.yaochu_ratio !== undefined ? features.yaochu_ratio : 0.0;
    const uke = features.ukeire_eff !== undefined ? features.ukeire_eff : 0.0;

    paramsEl.innerHTML = `
<div style="display:flex; flex-direction:column; gap:12px; font-family:var(--font-display); color:var(--text-main); grid-column: span 3; width: 100%;">
    <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:8px;">
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05); padding: 8px; border-radius: 8px; text-align: center;">
            <div style="font-size: 0.65rem; color: var(--text-muted); margin-bottom: 2px;">手牌早さ</div>
            <div style="font-size: 0.9rem; font-weight: 800; color: #8b5cf6;">${(details.fuzzy_inputs?.shanten_speed || 0).toFixed(2)}</div>
        </div>
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05); padding: 8px; border-radius: 8px; text-align: center;">
            <div style="font-size: 0.65rem; color: var(--text-muted); margin-bottom: 2px;">手牌高さ</div>
            <div style="font-size: 0.9rem; font-weight: 800; color: #fbbf24;">${(details.fuzzy_inputs?.hand_value || 0).toFixed(2)}</div>
        </div>
        <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05); padding: 8px; border-radius: 8px; text-align: center;">
            <div style="font-size: 0.65rem; color: var(--text-muted); margin-bottom: 2px;">手牌価値</div>
            <div style="font-size: 0.9rem; font-weight: 800; color: #10b981;">${attack.toFixed(2)}</div>
        </div>
    </div>
    <div style="background: rgba(255,255,255,0.01); border: 1px solid rgba(255,255,255,0.04); padding: 10px; border-radius: 8px; display: flex; flex-direction: column; gap: 6px;">
        <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.72rem;">
            <span style="color: var(--text-muted);">飛びリスク判定:</span>
            ${flyBadge}
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.72rem;">
            <span style="color: var(--text-muted);">順位・ラス圧補正:</span>
            <span style="font-weight: bold; color: ${details.rank_pressure > 0 ? '#fbbf24' : 'var(--text-main)'};">${(details.rank_pressure || 0.0).toFixed(2)}</span>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.72rem;">
            <span style="color: var(--text-muted);">最終押し引き度 (push):</span>
            <span style="font-weight: bold; color: #a855f7;">${push.toFixed(2)}</span>
        </div>
    </div>
    <div style="background: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.03); padding: 8px 12px; border-radius: 8px;">
        <div style="font-size: 0.65rem; color: var(--text-muted); margin-bottom: 6px; text-align: center;">他家放銃警戒度 (卓上配置)</div>
        <div style="display: grid; grid-template-columns: 1fr 1.2fr 1fr; gap: 4px; align-items: center; font-size: 0.7rem; text-align: center;">
            <div>
                <div style="color: var(--text-muted); font-size: 0.6rem;">上家 (左)</div>
                <div style="font-weight: bold; color: ${kamiRisk > 0.3 ? '#ef4444' : 'var(--text-main)'};">${kamiRisk.toFixed(2)}</div>
            </div>
            <div>
                <div style="color: var(--text-muted); font-size: 0.6rem;">対面 (正面)</div>
                <div style="font-weight: bold; color: ${toimiRisk > 0.3 ? '#ef4444' : 'var(--text-main)'};">${toimiRisk.toFixed(2)}</div>
            </div>
            <div>
                <div style="color: var(--text-muted); font-size: 0.6rem;">下家 (右)</div>
                <div style="font-weight: bold; color: ${shimoRisk > 0.3 ? '#ef4444' : 'var(--text-main)'};">${shimoRisk.toFixed(2)}</div>
            </div>
        </div>
    </div>
    <div style="display: flex; flex-direction: column; gap: 6px; font-size: 0.7rem; border-top: 1px dashed rgba(255,255,255,0.08); padding-top: 8px;">
        <div style="display: flex; align-items: center; justify-content: space-between;">
            <span style="color: var(--text-muted); width: 60px;">対子率:</span>
            <div style="flex: 1; background: rgba(255,255,255,0.05); height: 4px; border-radius: 2px; margin: 0 8px; position: relative; overflow: hidden;">
                <div style="background: #3b82f6; width: ${(pair*100).toFixed(0)}%; height: 100%;"></div>
            </div>
            <span style="font-family: monospace; font-weight: bold; width: 30px; text-align: right;">${pair.toFixed(2)}</span>
        </div>
        <div style="display: flex; align-items: center; justify-content: space-between;">
            <span style="color: var(--text-muted); width: 60px;">字牌率:</span>
            <div style="flex: 1; background: rgba(255,255,255,0.05); height: 4px; border-radius: 2px; margin: 0 8px; position: relative; overflow: hidden;">
                <div style="background: #10b981; width: ${(honor*100).toFixed(0)}%; height: 100%;"></div>
            </div>
            <span style="font-family: monospace; font-weight: bold; width: 30px; text-align: right;">${honor.toFixed(2)}</span>
        </div>
        <div style="display: flex; align-items: center; justify-content: space-between;">
            <span style="color: var(--text-muted); width: 60px;">一色偏り:</span>
            <div style="flex: 1; background: rgba(255,255,255,0.05); height: 4px; border-radius: 2px; margin: 0 8px; position: relative; overflow: hidden;">
                <div style="background: #a855f7; width: ${(suit*100).toFixed(0)}%; height: 100%;"></div>
            </div>
            <span style="font-family: monospace; font-weight: bold; width: 30px; text-align: right;">${suit.toFixed(2)}</span>
        </div>
        <div style="display: flex; align-items: center; justify-content: space-between;">
            <span style="color: var(--text-muted); width: 60px;">ヤオ九率:</span>
            <div style="flex: 1; background: rgba(255,255,255,0.05); height: 4px; border-radius: 2px; margin: 0 8px; position: relative; overflow: hidden;">
                <div style="background: #f59e0b; width: ${(yao*100).toFixed(0)}%; height: 100%;"></div>
            </div>
            <span style="font-family: monospace; font-weight: bold; width: 30px; text-align: right;">${yao.toFixed(2)}</span>
        </div>
    </div>
</div>
`;
    threatEl.innerText = '⚠ 脅威度根拠: ' + (details.threat_reason || '--');
}

function renderTuplePanel(ev) {
    const panel = document.getElementById('botCoachTuplePanel');
    const grid = document.getElementById('botCoachTupleGrid');
    if (!ev || !ev.tuple_values) {
        panel.style.display = 'none';
        return;
    }
    const tierNames = ev.tier_names || ['向聴数', '受入/安全度', '手役補正', '戦術ランク/愚形', 'ドラ損失/安全度', '安全度', '予備'];
    const values = ev.tuple_values;
    const deciding = ev._decidingLayer !== undefined ? ev._decidingLayer : -1;
    grid.style.cssText = "display: flex; flex-direction: column; gap: 6px; width: 100%; position: relative; margin-top: 8px;";
    let html = '';
    let numIndex = 1;
    for (let i = 0; i < Math.min(tierNames.length, values.length); i++) {
        const name = tierNames[i];
        if (!name || name === '予備' || name === '') continue;
        const v = values[i];
        const isDeciding = (i === deciding);
        const isPassed = (deciding !== -1 && i > deciding);
        let itemStyle = "display: flex; align-items: center; justify-content: space-between; padding: 6px 10px; border-radius: 6px; font-size: 0.75rem; transition: all 0.2s;";
        let numBadge = '<span style="font-size: 0.65rem; color: var(--text-muted); margin-right: 8px;">' + numIndex + '</span>';
        if (isDeciding) {
            itemStyle += " background: linear-gradient(90deg, rgba(245, 158, 11, 0.18) 0%, rgba(245, 158, 11, 0.03) 100%); border: 1px solid rgba(245, 158, 11, 0.35); box-shadow: 0 0 8px rgba(245, 158, 11, 0.1); color: #fbbf24; font-weight: bold;";
            numBadge = '<span style="font-size: 0.65rem; background: #fbbf24; color: #1e1b4b; padding: 1px 5px; border-radius: 4px; margin-right: 8px; font-weight: 900;">🎯 決定</span>';
        } else if (isPassed) {
            itemStyle += " opacity: 0.35; background: rgba(255,255,255,0.01); border: 1px solid transparent;";
        } else {
            itemStyle += " background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.05); color: var(--text-main);";
        }
        html += '<div style="' + itemStyle + '"><div style="display: flex; align-items: center;">' + numBadge + '<span>' + name + '</span></div><span style="font-family: monospace; font-weight: bold; font-size: 0.8rem;">' + v.toFixed(2) + '</span></div>';
        numIndex++;
    }
    grid.innerHTML = html;
    panel.style.display = 'flex';
}

function renderFlyRisk(flyRisk) {
    const panel = document.getElementById('botCoachFlyRisk');
    const barFill = document.getElementById('botCoachFlyRiskBarFill');
    const labels = document.getElementById('botCoachFlyRiskLabels');
    const details = document.getElementById('botCoachFlyRiskDetails');
    const header = document.getElementById('botCoachFlyRiskHeader');
    const body = document.getElementById('botCoachFlyRiskBody');
    const toggle = document.getElementById('botCoachFlyRiskToggle');

    if (!flyRisk) {
        panel.style.display = 'none';
        return;
    }

    panel.style.display = 'flex';

    const myScore = flyRisk.my_score || 25000;
    const estLoss = flyRisk.estimated_loss || 8000;
    const ratio = Math.min(1.0, estLoss / Math.max(1, myScore));
    barFill.style.width = `${(ratio * 100).toFixed(1)}%`;

    labels.innerHTML = `<span>安全 (${myScore})</span><span>危険 (${estLoss})</span>`;

    details.innerHTML = `
        <div class="bot-coach-flyrisk-detail-item"><span class="label">持ち点</span><span class="value">${myScore}</span></div>
        <div class="bot-coach-flyrisk-detail-item"><span class="label">推定損失</span><span class="value">${estLoss}</span></div>
        <div class="bot-coach-flyrisk-detail-item"><span class="label">残り局数</span><span class="value">${flyRisk.rem_rounds}/${flyRisk.max_rounds}</span></div>
        <div class="bot-coach-flyrisk-detail-item"><span class="label">手牌期待値</span><span class="value">${flyRisk.my_win_score}</span></div>
        <div class="bot-coach-flyrisk-detail-item"><span class="label">補正値</span><span class="value">${flyRisk.adjust}</span></div>
        <div class="bot-coach-flyrisk-detail-item"><span class="label">順位</span><span class="value">${flyRisk.rank + 1}位</span></div>
    `;

    const isOpen = flyRisk.adjust < 0;
    body.style.display = isOpen ? 'flex' : 'none';
    if (toggle) toggle.classList.toggle('open', isOpen);

    if (header && !header._flyRiskBound) {
        header._flyRiskBound = true;
        header.addEventListener('click', function() {
            const b = document.getElementById('botCoachFlyRiskBody');
            const t = document.getElementById('botCoachFlyRiskToggle');
            const nowOpen = b.style.display !== 'none';
            b.style.display = nowOpen ? 'none' : 'flex';
            if (t) t.classList.toggle('open', !nowOpen);
        });
    }
}

function renderReasonForTile(text) {
    const box = document.getElementById('botCoachReason');
    const txt = document.getElementById('botCoachReasonText');
    if (!text) {
        box.style.display = 'none';
        return;
    }
    box.style.display = 'flex';
    txt.innerHTML = text.replace(/\n/g, '<br>');
}

function selectEvalRow(row, ev, recommendedTile) {
    if (ev.tile === _activeTile) return;
    _activeTile = ev.tile;
    const list = document.getElementById('botCoachEvalList');
    Array.from(list.children).forEach(c => c.classList.remove('is-active'));
    row.classList.add('is-active');

    ev._isBest = (ev.tile === recommendedTile);
    const reasonText = ev.reason || '';
    const layerMatch = reasonText.match(/^[①②③④⑤⑥]/);
    const layerMap = {'①': 0, '②': 1, '③': 2, '④': 3, '⑤': 4, '⑥': 5};
    ev._decidingLayer = layerMatch ? (layerMap[layerMatch[0]] !== undefined ? layerMap[layerMatch[0]] : -1) : -1;
    renderTuplePanel(ev);

    let reasonTextFinal = reasonText || `「${ev.tile}」を打牌した場合 (評価値 ${ev.score.toFixed(0)})`;
    if (_karagiriReason) {
        reasonTextFinal += '<br>' + _karagiriReason;
    }
    renderReasonForTile(reasonTextFinal);
}

function highlightRecommendedTile(tile, nearTiles, tsumogiri) {
    const handEl = document.getElementById('hand' + perspectiveSeat);
    if (!handEl) return;
    handEl.querySelectorAll('.tile-recommended').forEach(el => el.classList.remove('tile-recommended'));
    handEl.querySelectorAll('.tile-near').forEach(el => el.classList.remove('tile-near'));
    if (!tile) return;
    const nearSet = new Set(nearTiles || []);

    let foundGap = false;
    let highlighted = false;

    handEl.querySelectorAll('*').forEach(el => {
        if (el.classList.contains('tsumo-gap')) {
            foundGap = true;
            return;
        }
        if (!el.classList.contains('tile') || el.classList.contains('tile-back')) return;

        // Why: 牌は SVG 絵柄で描画するため innerText ではなく data-tile (牌コード) で照合する
        const txt = el.dataset.tile;
        const isTsumoTile = foundGap;

        if (txt === tile) {
            if (tsumogiri) {
                if (isTsumoTile) {
                    el.classList.add('tile-recommended');
                    highlighted = true;
                }
            } else {
                if (!isTsumoTile) {
                    el.classList.add('tile-recommended');
                    highlighted = true;
                }
            }
        } else if (nearSet.has(txt)) {
            el.classList.add('tile-near');
        }
    });

    if (!highlighted) {
        handEl.querySelectorAll('.tile').forEach(el => {
            if (el.classList.contains('tile-back') || el.classList.contains('tsumo-gap')) return;
            if (el.dataset.tile === tile) {
                el.classList.add('tile-recommended');
            }
        });
    }
}

// ----- 副露レンダリング -----
function _render_breakdown(c) {
    const bd = document.getElementById('botCoachMeldBreakdown');
    if (!c || !c.meld_breakdowns || c.meld_breakdowns.length === 0) {
        bd.style.display = 'none';
        return;
    }
    let html = '<div style="font-size:0.65rem;color:var(--text-muted);margin-bottom:4px;font-weight:bold;">加減点内訳 (綱引き)</div>';
    c.meld_breakdowns.forEach(function(b) {
        const isPos = b.score > 0;
        const isNeg = b.score < 0;
        const color = isPos ? '#10b981' : (isNeg ? '#ef4444' : 'var(--text-muted)');
        const badge = isPos ? '<span class="bot-coach-meld-breakdown-badge" style="background:rgba(16,185,129,0.15);color:#10b981;">メリット</span>'
            : (isNeg ? '<span class="bot-coach-meld-breakdown-badge" style="background:rgba(239,68,68,0.15);color:#ef4444;">デメリット</span>'
            : '<span class="bot-coach-meld-breakdown-badge" style="background:rgba(255,255,255,0.05);color:var(--text-muted);">±0</span>');
        const sign = isPos ? '+' : (isNeg ? '' : '±');
        html += '<div class="bot-coach-meld-breakdown-item"><div>' + badge + '<span>' + b.name + '</span></div><div style="font-family:monospace;font-weight:bold;color:' + color + ';">' + sign + Math.abs(b.score).toFixed(0) + '</div></div>';
        if (b.reason) {
            html += '<div style="font-size:0.6rem;color:var(--text-muted);padding:0 6px 2px 6px;margin-top:-2px;">' + b.reason + '</div>';
        }
    });
    bd.innerHTML = html;
    bd.style.display = 'flex';
}

function _render_meld_eval(data, statusText, mp) {
    const best = data.recommended;
    let rec = best ? data.candidates.find(c => c.type === best) : null;

    const statusEl = document.getElementById('botCoachMeldStatus');
    const reasonEl = document.getElementById('botCoachMeldReasonText');
    const badgeEl = document.getElementById('botCoachMeldRecommendBadge');
    const actionLabel = document.getElementById('botCoachMeldActionLabel');
    const indicator = document.getElementById('botCoachMeldIndicator');
    const totalText = document.getElementById('botCoachMeldTotalText');

    rec = rec || data.candidates[0];
    statusEl.innerHTML = statusText;

    if (rec) {
        const isSkip = rec.type === 'skip';
        const isForbidden = rec.forbidden === true;
        if (isForbidden) {
            badgeEl.style.cssText = 'display:inline-block; padding:4px 12px; border-radius:20px; font-size:0.75rem; font-weight:bold; color:#ef4444; background:rgba(239,68,68,0.15); border:1px solid rgba(239,68,68,0.3); text-shadow:0 0 6px #ef444440;';
            badgeEl.innerText = '🚫 不許可';
            actionLabel.style.cssText = 'background:rgba(239,68,68,0.15); color:#ef4444; border:1px solid rgba(239,68,68,0.3); padding:4px 10px; border-radius:6px; font-size:0.75rem; font-weight:bold;';
            actionLabel.innerText = '禁止';
        } else if (isSkip) {
            badgeEl.style.cssText = 'display:inline-block; padding:4px 12px; border-radius:20px; font-size:0.75rem; font-weight:bold; color:#3b82f6; background:rgba(59,130,246,0.15); border:1px solid rgba(59,130,246,0.3); text-shadow:0 0 6px #3b82f640;';
            badgeEl.innerText = '⏸ スキップ推奨';
            actionLabel.style.cssText = 'background:rgba(255,255,255,0.05); color:var(--text-muted); padding:4px 10px; border-radius:6px; font-size:0.75rem; font-weight:bold;';
            actionLabel.innerText = 'スキップ';
        } else {
            badgeEl.style.cssText = 'display:inline-block; padding:4px 12px; border-radius:20px; font-size:0.75rem; font-weight:bold; color:#10b981; background:rgba(16,185,129,0.15); border:1px solid rgba(16,185,129,0.3); text-shadow:0 0 6px #10b98140;';
            badgeEl.innerText = '★ ' + rec.label + '推奨';
            actionLabel.style.cssText = 'background:rgba(16,185,129,0.15); color:#10b981; border:1px solid rgba(16,185,129,0.3); padding:4px 10px; border-radius:6px; font-size:0.75rem; font-weight:bold;';
            actionLabel.innerText = rec.label;
        }
    } else {
        badgeEl.style.display = 'none';
        actionLabel.innerText = '--';
    }

    if (rec && rec.reason) {
        reasonEl.style.display = 'block';
        let discardHtml = '';
        if (rec.type !== 'skip' && rec.best_discard) {
            const discClass = getTileClass(rec.best_discard);
            const discText = getTileText(rec.best_discard);
            discardHtml = '<div style="margin-top:6px; padding-top:6px; border-top:1px dashed rgba(255,255,255,0.1); display:flex; align-items:center; gap:6px; font-size:0.72rem;"><span style="color:var(--text-muted);">鳴いた後の切り牌:</span>' + tileFaceHtml(rec.best_discard, discClass) + '<span>' + discText + '</span></div>';
        }
        reasonEl.innerHTML = rec.reason + discardHtml;
    } else {
        reasonEl.style.display = 'none';
    }

    _render_breakdown(rec);

    const meldCand = data.candidates.find(function(x) { return x.type !== 'skip'; });
    const skipCand = data.candidates.find(function(x) { return x.type === 'skip'; });
    const totalVal = (meldCand && skipCand) ? (meldCand.best_score - skipCand.best_score) : 0;
    if (indicator) {
        const pct = Math.max(0, Math.min(100, ((totalVal + 1000) / 2000) * 100));
        indicator.style.left = pct + '%';
        indicator.style.borderBottomColor = totalVal > 100 ? '#10b981' : (totalVal < -100 ? '#3b82f6' : '#fbbf24');
    }
    if (totalText) {
        totalText.innerText = '差分: ' + (totalVal > 0 ? '+' : '') + totalVal.toFixed(0);
        totalText.style.color = totalVal > 100 ? '#10b981' : (totalVal < -100 ? '#3b82f6' : 'var(--text-main)');
    }

    const card = mp ? mp.querySelector('div[style*="border-radius: 12px"]') : null;
    if (card && !card._breakdownBound) {
        card._breakdownBound = true;
        card.style.cursor = 'pointer';
        card.title = 'クリックで加減点内訳を表示';
        card.addEventListener('click', function() {
            const cur = data.candidates.find(function(x) { return x.type !== 'skip'; }) || data.candidates[0];
            _render_breakdown(cur);
        });
    }
}

// ----- プロンプト・UIトグル -----
function copyGeminiPrompt() {
    const prompt = document.getElementById('promptPreview').innerText;
    navigator.clipboard.writeText(prompt).then(() => {
        const toast = document.getElementById('copyToast');
        toast.classList.add('show');
        setTimeout(() => {
            toast.classList.remove('show');
        }, 3000);
    }).catch(err => {
        alert('コピーに失敗しました: ' + err);
    });
}

function toggleLegend() {
    const overlay = document.getElementById('legendOverlay');
    overlay.classList.toggle('is-visible');
}

function toggleTacticalFlow() {
    const el = document.getElementById('tacticalFlowOverlay');
    if (el) el.classList.toggle('is-visible');
}

// ----- イベントリスナー (IIFE) -----
(function() {
    const closeBtn = document.getElementById('botCoachMeldClose');
    if (closeBtn) {
        closeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const mp = document.getElementById('botCoachMeldPanel');
            if (mp) {
                mp.classList.remove('is-visible');
                mp.classList.remove('is-loading');
                mp.dataset.active = "0";
            }
        });
    }
})();

(function() {
    const recommend = document.getElementById('botCoachRecommend');
    const detail = document.getElementById('botCoachDetailFloating');
    if (!recommend || !detail) return;
    let pinned = false;

    function showDetail() { detail.classList.add('is-shown'); }
    function hideDetail() {
        if (!pinned) detail.classList.remove('is-shown');
    }

    recommend.addEventListener('mouseenter', showDetail);
    recommend.addEventListener('mouseleave', hideDetail);
    detail.addEventListener('mouseenter', showDetail);
    detail.addEventListener('mouseleave', hideDetail);

    recommend.addEventListener('click', (e) => {
        e.stopPropagation();
        pinned = !pinned;
        if (pinned) showDetail();
        else hideDetail();
    });

    document.addEventListener('click', (e) => {
        if (!recommend.contains(e.target) && !detail.contains(e.target)) {
            pinned = false;
            detail.classList.remove('is-shown');
        }
    });
})();
