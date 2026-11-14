/**
 * @title 麻雀牌の絵柄 (SVG) 生成
 * @description 牌コード ('1m', '0p', '7z' など) から本物の牌に近い絵柄の SVG を生成する。
 *              萬子=漢数字+萬、筒子=丸、索子=竹、字牌=漢字。外部画像を使わず自前で描画する。
 *              座標系は縦向きの牌 60x80 (viewBox) を基準とする。
 */

const TILE_FACE_COLORS = {
    red: '#c8102e',
    green: '#11753b',
    blue: '#1d3f8f',
    black: '#1a1a1a',
};

const _MAN_KANJI = ['', '一', '二', '三', '四', '伍', '六', '七', '八', '九'];
const _HONOR_KANJI = { 1: '東', 2: '南', 3: '西', 4: '北', 5: '白', 6: '發', 7: '中' };
const _KANJI_FONT = "'Noto Serif JP','Yu Mincho','YuMincho','Hiragino Mincho ProN','MS Mincho',serif";

function _svgText(x, y, size, color, text, extra = '') {
    return `<text x="${x}" y="${y}" font-size="${size}" fill="${color}" font-family="${_KANJI_FONT}" font-weight="700" text-anchor="middle" dominant-baseline="central" ${extra}>${text}</text>`;
}

/** 筒子の丸 1 個 (外輪 + 内円 + 中心点) */
function _pin(cx, cy, r, color) {
    return `<circle cx="${cx}" cy="${cy}" r="${r * 0.86}" fill="none" stroke="${color}" stroke-width="${r * 0.28}"/>`
        + `<circle cx="${cx}" cy="${cy}" r="${r * 0.42}" fill="${color}"/>`
        + `<circle cx="${cx}" cy="${cy}" r="${r * 0.16}" fill="#fff"/>`;
}

/** 索子の竹 1 本 (節つき) */
function _stick(cx, cy, h, color, w = 7) {
    const x = cx - w / 2, y = cy - h / 2;
    return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${w / 2}" fill="${color}"/>`
        + `<line x1="${x}" y1="${cy}" x2="${x + w}" y2="${cy}" stroke="#fff" stroke-width="1.4"/>`
        + `<line x1="${cx}" y1="${y + 2}" x2="${cx}" y2="${y + h - 2}" stroke="rgba(255,255,255,0.45)" stroke-width="1"/>`;
}

function _manFace(n, isAka) {
    const numColor = isAka ? TILE_FACE_COLORS.red : TILE_FACE_COLORS.black;
    return _svgText(30, 25, 27, numColor, _MAN_KANJI[n]) + _svgText(30, 59, 29, TILE_FACE_COLORS.red, '萬');
}

function _pinFace(n, isAka) {
    const { red: R, green: G, blue: B } = TILE_FACE_COLORS;
    const c = (color) => (isAka ? R : color);
    switch (n) {
        case 1:
            return `<circle cx="30" cy="40" r="23" fill="none" stroke="${G}" stroke-width="3"/>`
                + `<circle cx="30" cy="40" r="18" fill="none" stroke="${B}" stroke-width="4" stroke-dasharray="3 2.2"/>`
                + `<circle cx="30" cy="40" r="11" fill="${R}"/>`
                + `<circle cx="30" cy="40" r="6" fill="none" stroke="#fff" stroke-width="1.6"/>`
                + `<circle cx="30" cy="40" r="2" fill="#fff"/>`;
        case 2:
            return _pin(30, 21, 14, c(G)) + _pin(30, 59, 14, c(B));
        case 3:
            return _pin(15, 16, 10.5, c(B)) + _pin(30, 40, 10.5, c(R)) + _pin(45, 64, 10.5, c(G));
        case 4:
            return _pin(17, 22, 12, c(B)) + _pin(43, 22, 12, c(G)) + _pin(17, 58, 12, c(G)) + _pin(43, 58, 12, c(B));
        case 5:
            return _pin(16, 17, 10.5, c(B)) + _pin(44, 17, 10.5, c(G)) + _pin(30, 40, 10.5, R)
                + _pin(16, 63, 10.5, c(G)) + _pin(44, 63, 10.5, c(B));
        case 6:
            return _pin(17, 15, 10, c(G)) + _pin(43, 15, 10, c(G))
                + _pin(17, 45, 10, R) + _pin(43, 45, 10, R) + _pin(17, 67, 10, R) + _pin(43, 67, 10, R);
        case 7:
            return _pin(12, 11, 8, c(G)) + _pin(30, 19, 8, c(G)) + _pin(48, 27, 8, c(G))
                + _pin(18, 48, 9, R) + _pin(42, 48, 9, R) + _pin(18, 68, 9, R) + _pin(42, 68, 9, R);
        case 8:
            return [13, 31, 49, 67].map(y => _pin(18, y, 9, c(B)) + _pin(42, y, 9, c(B))).join('');
        case 9:
            return [[16, B], [40, R], [64, G]].map(([y, col]) =>
                _pin(13, y, 8.5, c(col)) + _pin(30, y, 8.5, c(col)) + _pin(47, y, 8.5, c(col))).join('');
    }
    return '';
}

function _souFace(n, isAka) {
    const { red: R, green: G, blue: B } = TILE_FACE_COLORS;
    const c = (color) => (isAka ? R : color);
    switch (n) {
        case 1:
            // 一索: 鳥 (孔雀) を簡略化して描画
            return `<path d="M30 70 C18 64 14 50 20 40 C26 30 40 32 42 42 C44 52 38 60 30 70 Z" fill="${G}"/>`
                + `<path d="M24 44 C28 38 36 38 38 46" fill="none" stroke="${R}" stroke-width="2.4"/>`
                + `<path d="M30 70 L22 76 M30 70 L30 77 M30 70 L38 76" stroke="${B}" stroke-width="2.4" stroke-linecap="round"/>`
                + `<circle cx="38" cy="22" r="7" fill="${G}"/>`
                + `<path d="M34 28 C34 32 36 34 38 34" fill="none" stroke="${G}" stroke-width="5"/>`
                + `<circle cx="40" cy="20" r="1.8" fill="#fff"/>`
                + `<path d="M44 21 L50 23 L44 25 Z" fill="${R}"/>`
                + `<path d="M36 15 L33 7 M38 15 L38 6 M40 15 L43 7" stroke="${R}" stroke-width="2" stroke-linecap="round"/>`;
        case 2:
            return _stick(30, 22, 30, c(G)) + _stick(30, 58, 30, c(B));
        case 3:
            return _stick(30, 22, 30, c(G)) + _stick(19, 58, 30, c(B)) + _stick(41, 58, 30, c(B));
        case 4:
            return _stick(19, 22, 30, c(G)) + _stick(41, 22, 30, c(B)) + _stick(19, 58, 30, c(B)) + _stick(41, 58, 30, c(G));
        case 5:
            return _stick(15, 22, 30, c(G)) + _stick(45, 22, 30, c(B)) + _stick(30, 40, 30, R)
                + _stick(15, 58, 30, c(B)) + _stick(45, 58, 30, c(G));
        case 6:
            return [14, 30, 46].map(x => _stick(x, 22, 30, c(G)) + _stick(x, 58, 30, c(B))).join('');
        case 7:
            return _stick(30, 13, 20, R)
                + [14, 30, 46].map(x => _stick(x, 40, 22, c(G)) + _stick(x, 66, 22, c(B))).join('');
        case 8:
            // 八索: 上段は M 字、下段は W 字
            return `<g transform="translate(0,0)">`
                + _rotStick(12, 22, 30, 0, c(G)) + _rotStick(25, 22, 30, 28, c(G))
                + _rotStick(35, 22, 30, -28, c(G)) + _rotStick(48, 22, 30, 0, c(G))
                + _rotStick(12, 58, 30, 0, c(B)) + _rotStick(25, 58, 30, -28, c(B))
                + _rotStick(35, 58, 30, 28, c(B)) + _rotStick(48, 58, 30, 0, c(B))
                + `</g>`;
        case 9:
            return [14, 40, 66].map(y =>
                _stick(14, y, 22, c(G)) + _stick(30, y, 22, R) + _stick(46, y, 22, c(B))).join('');
    }
    return '';
}

function _rotStick(cx, cy, h, deg, color) {
    return `<g transform="rotate(${deg} ${cx} ${cy})">${_stick(cx, cy, h, color, 6.5)}</g>`;
}

function _honorFace(n) {
    if (n === 5) {
        // 白: 青い枠のみ
        return `<rect x="11" y="13" width="38" height="54" rx="4" fill="none" stroke="#3b6fd4" stroke-width="3.2"/>`
            + `<rect x="16" y="18" width="28" height="44" rx="2" fill="none" stroke="#3b6fd4" stroke-width="1.2"/>`;
    }
    const color = n === 6 ? TILE_FACE_COLORS.green : (n === 7 ? TILE_FACE_COLORS.red : TILE_FACE_COLORS.black);
    return _svgText(30, 41, 40, color, _HONOR_KANJI[n]);
}

/**
 * @title 牌の絵柄 SVG 文字列を返す
 * @param {string} tile - 牌コード ('1m'〜'9m', '0m' (赤5), '1z'〜'7z' 等)
 * @param {boolean} sideways - true なら横向き (左に 90 度倒した) 牌として描画
 * @returns {string} SVG 文字列 (不明な牌は空文字)
 */
function tileFaceSvg(tile, sideways = false) {
    if (!tile || tile.length < 2) return '';
    const suit = tile[tile.length - 1];
    // 赤5 ('0m' など) は数牌のみ。'0z' のような不正コードは赤5として扱わない
    const isAka = tile[0] === '0' && 'mps'.includes(suit);
    const n = isAka ? 5 : parseInt(tile[0], 10);
    if (!(n >= 1 && n <= 9)) return '';
    let face = '';
    if (suit === 'm') face = _manFace(n, isAka);
    else if (suit === 'p') face = _pinFace(n, isAka);
    else if (suit === 's') face = _souFace(n, isAka);
    else if (suit === 'z' && n <= 7) face = _honorFace(n);
    if (!face) return '';
    if (sideways) {
        return `<svg class="tile-face-svg" viewBox="0 0 80 60" preserveAspectRatio="xMidYMid meet" aria-hidden="true"><g transform="translate(0,60) rotate(-90)">${face}</g></svg>`;
    }
    return `<svg class="tile-face-svg" viewBox="0 0 60 80" preserveAspectRatio="xMidYMid meet" aria-hidden="true">${face}</svg>`;
}

/**
 * @title 要素に牌の絵柄を設定する
 * @description data-tile 属性に牌コードを保存し (推奨牌ハイライトの照合用)、title に牌名を設定する。
 */
function setTileFace(el, tile, sideways = false) {
    const svg = tileFaceSvg(tile, sideways);
    el.dataset.tile = tile || '';
    el.title = typeof getTileText === 'function' ? getTileText(tile) : (tile || '');
    if (svg) {
        el.classList.add('tile-face');
        el.innerHTML = svg;
    } else {
        el.innerText = typeof getTileText === 'function' ? getTileText(tile) : (tile || '');
    }
}

/** innerHTML 用: 小さな牌 1 枚の HTML を返す */
function tileFaceHtml(tile, extraClass = '') {
    const name = typeof getTileText === 'function' ? getTileText(tile) : tile;
    return `<span class="tile tile-face tile-mini ${extraClass}" data-tile="${tile}" title="${name}">${tileFaceSvg(tile)}</span>`;
}
