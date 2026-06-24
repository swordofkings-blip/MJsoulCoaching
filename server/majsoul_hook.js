// ==UserScript==
// @name         Mahjong Soul WebSocket Hook
// @namespace    http://tampermonkey.net/
// @version      0.3
// @description  雀魂のWebSocket通信をフックし、ローカルのPythonサーバーへ転送します。
// @author       Antigravity
// @match        https://*.mahjongsoul.com/*
// @match        https://*.maj-soul.com/*
// @match        https://*.yo-star.com/*
// @icon         data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==
// @grant        unsafeWindow
// @grant        GM_xmlhttpRequest
// @run-at       document-start
// ==/UserScript==

/**
 * @title 雀魂WebSocketフックスクリプト (TypedArray対応版)
 * @description Unity WebGLが送信に使用する Uint8Array (ArrayBufferView) を正確にキャッチし、送信パケットの記録漏れによるデコードエラーを防止します。
 */
(function() {
    'use strict';

    console.log("[Mahjong Soul Hook] ユーザースクリプトの読み込みを開始しました。");
    console.log("[Mahjong Soul Hook] GM_xmlhttpRequestのステータス:", typeof GM_xmlhttpRequest);

    // ページ側の生のwindowオブジェクトを取得（サンドボックスを回避してゲーム本体のWebSocketオブジェクトに干渉するため）
    const targetWindow = typeof unsafeWindow !== 'undefined' ? unsafeWindow : window;

    // ローカルのパケット受信サーバーのURL（8080ポートを使用）
    const LOCAL_SERVER_URL = 'http://127.0.0.1:8080/packet';

    /**
     * @title Base64変換関数
     * @description ArrayBufferのバイナリデータをBase64文字列に変換します。
     * @param {ArrayBuffer} arrayBuffer - 変換対象のバイナリデータ
     * @returns {string} Base64エンコードされた文字列
     */
    function arrayBufferToBase64(arrayBuffer) {
        let binary = '';
        const bytes = new Uint8Array(arrayBuffer);
        const len = bytes.byteLength;
        for (let i = 0; i < len; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return window.btoa(binary);
    }

    // 転送パケットを順番通りに送信するためのキューとフラグ
    const packetQueue = [];
    let isSending = false;
    let packetCounter = 0;
    let droppedHeartbeats = 0;

    // Why: heartbeat (7 byte) や極小パケットをスキップしてキュー詰まりを防ぐ。
    // Majsoul の heartbeat は約 1 秒に 1 回送られ、queue を圧迫する。
    const MIN_PACKET_SIZE = 32;
    const QUEUE_TIMEOUT_MS = 5000;

    /**
     * @title キュー処理関数
     * @description キューに溜まったパケットを順次、ローカルサーバーへ送信します。
     *              ネットワーク障害や onload/onerror 未発火時も QUEUE_TIMEOUT_MS 経過で
     *              強制的に次のパケットを処理することでキュー詰まりを防止。
     * @returns {void}
     */
    function processQueue() {
        if (isSending) return;
        if (packetQueue.length === 0) return;
        isSending = true;

        const { payload, resolve, sizeHint } = packetQueue.shift();

        // 強制的にキューを進行させるタイマー。
        // onload/onerror/ontimeout が何らかの理由で発火しない場合 (WinError 10053 等) の安全装置。
        let timeoutFired = false;
        const forceNext = setTimeout(function () {
            timeoutFired = true;
            isSending = false;
            if (resolve) try { resolve(); } catch (e) {}
            processQueue();
        }, QUEUE_TIMEOUT_MS);

        const next = function () {
            if (timeoutFired) return;
            clearTimeout(forceNext);
            isSending = false;
            if (resolve) try { resolve(); } catch (e) {}
            // 次フレームで次のキューを処理 (完全に直列化するため)
            setTimeout(processQueue, 0);
        };

        if (typeof GM_xmlhttpRequest !== 'undefined') {
            GM_xmlhttpRequest({
                method: 'POST',
                url: LOCAL_SERVER_URL,
                headers: {
                    'Content-Type': 'application/json'
                },
                data: payload,
                timeout: QUEUE_TIMEOUT_MS,
                onload: next,
                onerror: next,
                ontimeout: next
            });
        } else {
            fetch(LOCAL_SERVER_URL, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: payload
            }).then(next).catch(next);
        }
    }

    /**
     * @title パケット転送関数
     * @description データをキューに追加し、送信順序を保証しながら非同期でローカルサーバーへ転送します。
     * @param {ArrayBuffer} buffer - 送受信されたパケットのバイナリデータ
     * @param {boolean} fromClient - クライアントからの送信であればtrue、サーバーからの受信であればfalse
     * @returns {void}
     */
    function forwardPacket(buffer, fromClient) {
        // メインスレッドを止めないために非同期でBase64変換を行い、送信キューに登録
        setTimeout(() => {
            try {
                // Why: heartbeat (7 byte) や極小パケットをスキップしてキュー詰まりを防ぐ。
                // Majsoul の heartbeat は約 1 秒に 1 回送られ、queue を圧迫する。
                if (!fromClient && buffer.byteLength < MIN_PACKET_SIZE) {
                    droppedHeartbeats++;
                    if (droppedHeartbeats <= 5 || droppedHeartbeats % 50 === 0) {
                        console.log("[Mahjong Soul Hook] Heartbeat/dropped:", droppedHeartbeats, "size=", buffer.byteLength);
                    }
                    return;
                }

                const base64Data = arrayBufferToBase64(buffer);
                const payload = JSON.stringify({
                    from_client: fromClient,
                    data: base64Data
                });

                packetCounter++;
                if (packetCounter <= 5 || packetCounter % 50 === 0) {
                    console.log("[Mahjong Soul Hook] Forwarding packet #" + packetCounter + " from_client=" + fromClient + " size=" + buffer.byteLength);
                }

                new Promise((resolve) => {
                    packetQueue.push({ payload, resolve });
                    processQueue();
                });
            } catch (e) {
                console.error("[Mahjong Soul Hook] Packet prepare error:", e);
            }
        }, 0);
    }

    // デバッグ用: 送受信カウンター
    let sendCount = 0;
    let recvCount = 0;

    // 元のWebSocketコンストラクタを保持
    const OriginalWebSocket = targetWindow.WebSocket;

    if (!OriginalWebSocket) {
        console.error("[Mahjong Soul Hook] ターゲットのWebSocketクラスが見つかりません。");
        return;
    }

    /**
     * @title 単一WebSocketクラスのsend/addEventListenerをラップする内部関数
     * @param {Function} WSClass - ラップ対象のWebSocketクラス
     * @param {string} sourceLabel - デバッグログ用のラベル ("window" / "Module")
     */
    function hookWebSocketClass(WSClass, sourceLabel) {
        if (!WSClass || !WSClass.prototype || WSClass.__hooked) {
            return false;
        }
        try {
            const origSend = WSClass.prototype.send;
            WSClass.prototype.send = function(data) {
                try {
                    sendCount++;
                    if (sendCount <= 5 || sendCount % 50 === 0) {
                        console.log("[" + sourceLabel + " send] Count:", sendCount, "Type:", typeof data);
                    }
                    extractArrayBuffer(data, (buf) => {
                        forwardPacket(buf, true);
                    });
                } catch (e) {
                    console.error("[" + sourceLabel + " send] error:", e);
                }
                return origSend.apply(this, arguments);
            };

            const origAdd = WSClass.prototype.addEventListener;
            WSClass.prototype.addEventListener = function(type, listener, options) {
                if (type === 'message') {
                    const self = this;
                    const wrapped = function(event) {
                        try {
                            recvCount++;
                            if (recvCount <= 5 || recvCount % 50 === 0) {
                                console.log("[" + sourceLabel + " msg] Count:", recvCount, "Type:", typeof event.data);
                            }
                            extractArrayBuffer(event.data, (buf) => {
                                forwardPacket(buf, false);
                            });
                        } catch (e) {
                            console.error("[" + sourceLabel + " msg] error:", e);
                        }
                        return listener.call(self, event);
                    };
                    return origAdd.call(this, type, wrapped, options);
                }
                return origAdd.apply(this, arguments);
            };
            WSClass.__hooked = true;
            console.log("[Mahjong Soul Hook] " + sourceLabel + " WebSocket prototype patched.");
            return true;
        } catch (e) {
            console.error("[Mahjong Soul Hook] " + sourceLabel + " hook failed:", e);
            return false;
        }
    }

    // 1. window.WebSocket をラップ
    hookWebSocketClass(OriginalWebSocket, "window");

    /**
     * @title パケットデータ抽出ヘルパー
     * @description 各種オブジェクト型（ArrayBuffer, ArrayBufferView, Blob）から生のArrayBufferを正確に抽出します。
     * @param {any} data - 送受信される元データ
     * @param {function} callback - ArrayBuffer取得後のコールバック関数
     * @returns {void}
     */
    function extractArrayBuffer(data, callback) {
        if (data instanceof ArrayBuffer) {
            callback(data.slice(0));
        } else if (ArrayBuffer.isView(data)) {
            // Uint8Array などの TypedArray や DataView の場合、そのスライスされた範囲のバッファを正確に切り出す
            const slicedBuffer = data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength);
            callback(slicedBuffer);
        } else if (data instanceof Blob) {
            data.arrayBuffer().then(buf => {
                callback(buf);
            }).catch(err => {
                console.error("[Mahjong Soul Hook] Blob decode error:", err);
            });
        } else if (typeof data === 'string') {
            // Why: Unity WebGL が WebSocket データを文字列で送る場合の対応。
            // UTF-8 文字列を ArrayBuffer に変換してコールバック。
            try {
                const encoder = new TextEncoder();
                const buf = encoder.encode(data).buffer;
                callback(buf);
            } catch (e) {
                console.error("[Mahjong Soul Hook] String encode error:", e);
            }
        } else if (data && typeof data === 'object' && data.byteLength !== undefined) {
            // その他の TypedArray 風オブジェクト
            try {
                const arr = new Uint8Array(data.byteLength);
                for (let i = 0; i < data.byteLength; i++) {
                    arr[i] = data[i] || 0;
                }
                callback(arr.buffer);
            } catch (e) {
                console.error("[Mahjong Soul Hook] Object extract error:", e);
            }
        } else {
            console.warn("[Mahjong Soul Hook] Unknown data type:", typeof data, data);
        }
    }

    // ----------------------------------------------------
    // Prototypeメソッドのフック開始
    // ----------------------------------------------------

    // 2. 受信処理 (addEventListener) のフック
    const originalAddEventListener = OriginalWebSocket.prototype.addEventListener;
    const originalRemoveEventListener = OriginalWebSocket.prototype.removeEventListener;
    const hookedWSInstances = new WeakSet();

    // 3. 登録解除 (removeEventListener) のフック
    OriginalWebSocket.prototype.removeEventListener = function(type, listener, options) {
        if (type === 'message' && this._wrappedListeners && this._wrappedListeners.has(listener)) {
            const wrappedListener = this._wrappedListeners.get(listener);
            this._wrappedListeners.delete(listener);
            return originalRemoveEventListener.call(this, type, wrappedListener, options);
        }
        return originalRemoveEventListener.apply(this, arguments);
    };

    // 4. `onmessage` プロパティの直接代入に対するフック
    Object.defineProperty(OriginalWebSocket.prototype, 'onmessage', {
        set: function(listener) {
            if (this._onmessageWrapped) {
                originalRemoveEventListener.call(this, 'message', this._onmessageWrapped);
                this._onmessageWrapped = null;
            }

            if (listener) {
                const wrappedListener = function(event) {
                    try {
                        extractArrayBuffer(event.data, (buf) => {
                            forwardPacket(buf, false);
                        });
                    } catch (e) {
                        console.error("[Mahjong Soul Hook] Receive error (onmessage):", e);
                    }
                    return listener.apply(this, arguments);
                };

                this._onmessageWrapped = wrappedListener;
                this._onmessageOriginal = listener;
                originalAddEventListener.call(this, 'message', wrappedListener);
            } else {
                this._onmessageOriginal = null;
            }
        },
        get: function() {
            return this._onmessageOriginal || null;
        },
        configurable: true,
        enumerable: true
    });

    console.log("[Mahjong Soul Hook] window WebSocket prototype patched.");

    // ----------------------------------------------------
    // Module.WebSocket の監視 (Unity WebGL は Module.WebSocket を使う)
    // ----------------------------------------------------
    let moduleCheckInterval = null;
    function tryHookModuleWebSocket() {
        try {
            const mod = targetWindow.Module;
            if (!mod) return false;
            const candidates = [];
            if (mod.WebSocket) candidates.push(mod.WebSocket);
            if (mod['WebSocket']) candidates.push(mod['WebSocket']);
            let hookedAny = false;
            for (const ws of candidates) {
                if (hookWebSocketClass(ws, "Module")) {
                    hookedAny = true;
                }
            }
            return hookedAny;
        } catch (e) {
            return false;
        }
    }

    // 即座に試行 (Unity の WebSocket 作成が先の場合に間に合わない)
    if (!tryHookModuleWebSocket()) {
        // 定期的に監視 (Module は Unity のロード後に設定される)
        moduleCheckInterval = setInterval(() => {
            if (tryHookModuleWebSocket()) {
                // フック成功。以降は監視不要。
                if (moduleCheckInterval) {
                    clearInterval(moduleCheckInterval);
                    moduleCheckInterval = null;
                }
            }
        }, 200);
        // 60秒経ったら監視停止
        setTimeout(() => {
            if (moduleCheckInterval) {
                clearInterval(moduleCheckInterval);
                moduleCheckInterval = null;
            }
        }, 60000);
    }

    // ----------------------------------------------------
    // Unity の WebSocket.jslib 内部関数 (Module._WS_*) をラップ
    // Unity は C++ から Module._WS_Create を呼ぶ。
    // 中で new WebSocket() するが、send/message は別関数で管理される。
    // ----------------------------------------------------
    function tryHookUnityWebSocketInternal() {
        try {
            const mod = targetWindow.Module;
            if (!mod) return false;
            const wsFuncs = ['_WS_Create', '_WS_Send', '_WS_Recv', '_WS_WaitForMessage', '_WS_Close'];
            let hookedAny = false;
            for (const fname of wsFuncs) {
                if (typeof mod[fname] === 'function' && !mod[fname].__hooked) {
                    const orig = mod[fname];
                    mod[fname] = function() {
                        try {
                            // 1. WS_Create の場合: 戻り値の socketId をログ
                            if (fname === '_WS_Create') {
                                console.log("[Mahjong Soul Hook] Module." + fname + " called. url=" + (arguments[0] || ""));
                            }
                            // 2. WS_Send の場合: データ引数を傍受
                            if (fname === '_WS_Send') {
                                const socketId = arguments[0];
                                const dataPtr = arguments[1];
                                const dataLen = arguments[2];
                                // メモリのポインタから ArrayBuffer を取り出す
                                if (typeof mod.HEAPU8 !== 'undefined' && dataPtr && dataLen) {
                                    try {
                                        const bytes = mod.HEAPU8.subarray(dataPtr, dataPtr + dataLen);
                                        const buf = bytes.slice().buffer;
                                        sendCount++;
                                        if (sendCount <= 5 || sendCount % 50 === 0) {
                                            console.log("[Module _WS_Send] Count:", sendCount, "Length:", dataLen);
                                        }
                                        forwardPacket(buf, true);
                                    } catch (e) {
                                        console.error("[Module _WS_Send] extract error:", e);
                                    }
                                }
                            }
                            // 3. WS_Recv の場合: 受信したデータを読み取る
                            if (fname === '_WS_Recv') {
                                // 関数を実行して結果を取得
                                const result = orig.apply(this, arguments);
                                // result が string (ポインタ) なら変換
                                if (typeof result === 'number' && typeof mod.UTF8ToString === 'function') {
                                    try {
                                        const str = mod.UTF8ToString(result);
                                        if (str) {
                                            recvCount++;
                                            if (recvCount <= 5 || recvCount % 50 === 0) {
                                                console.log("[Module _WS_Recv] Count:", recvCount, "Length:", str.length);
                                            }
                                            const bytes = new TextEncoder().encode(str);
                                            forwardPacket(bytes.buffer, false);
                                        }
                                    } catch (e) {
                                        console.error("[Module _WS_Recv] extract error:", e);
                                    }
                                }
                                return result;
                            }
                        } catch (e) {
                            console.error("[Mahjong Soul Hook] Module." + fname + " error:", e);
                        }
                        return orig.apply(this, arguments);
                    };
                    // 同じ prototype を継承
                    mod[fname].__hooked = true;
                    hookedAny = true;
                    console.log("[Mahjong Soul Hook] Module." + fname + " hooked.");
                }
            }
            return hookedAny;
        } catch (e) {
            return false;
        }
    }

    // Unity の _WS_* 関数を定期的に監視
    let unityCheckInterval = setInterval(() => {
        if (tryHookUnityWebSocketInternal()) {
            // フック成功
        }
    }, 200);
    setTimeout(() => {
        if (unityCheckInterval) {
            clearInterval(unityCheckInterval);
            unityCheckInterval = null;
        }
    }, 60000);

    // ----------------------------------------------------
    // 最終手段: WebSocket コンストラクタの完全置換
    // ----------------------------------------------------
    function installWebSocketConstructorPatch() {
        try {
            if (targetWindow.WebSocket.__patched) return;
            const OrigWebSocket = targetWindow.WebSocket;
            if (!OrigWebSocket || OrigWebSocket.__patched) return;
            function PatchedWebSocket(url, protocols) {
                const ws = protocols !== undefined ? new OrigWebSocket(url, protocols) : new OrigWebSocket(url);
                // インスタンスごとに send/addEventListener をラップ
                const origSend = ws.send.bind(ws);
                ws.send = function(data) {
                    try {
                        sendCount++;
                        if (sendCount <= 5 || sendCount % 50 === 0) {
                            console.log("[Patched send] Count:", sendCount, "Type:", typeof data);
                        }
                        extractArrayBuffer(data, (buf) => forwardPacket(buf, true));
                    } catch (e) {
                        console.error("[Patched send] error:", e);
                    }
                    return origSend(data);
                };
                const origAdd = ws.addEventListener.bind(ws);
                ws.addEventListener = function(type, listener, options) {
                    if (type === 'message') {
                        const wrapped = function(event) {
                            try {
                                recvCount++;
                                if (recvCount <= 5 || recvCount % 50 === 0) {
                                    console.log("[Patched msg] Count:", recvCount, "Type:", typeof event.data);
                                }
                                extractArrayBuffer(event.data, (buf) => forwardPacket(buf, false));
                            } catch (e) {
                                console.error("[Patched msg] error:", e);
                            }
                            return listener.call(ws, event);
                        };
                        return origAdd(type, wrapped, options);
                    }
                    return origAdd(type, listener, options);
                };
                return ws;
            }
            PatchedWebSocket.prototype = OrigWebSocket.prototype;
            PatchedWebSocket.CONNECTING = OrigWebSocket.CONNECTING;
            PatchedWebSocket.OPEN = OrigWebSocket.OPEN;
            PatchedWebSocket.CLOSING = OrigWebSocket.CLOSING;
            PatchedWebSocket.CLOSED = OrigWebSocket.CLOSED;
            PatchedWebSocket.__patched = true;
            Object.defineProperty(targetWindow, 'WebSocket', {
                value: PatchedWebSocket,
                writable: true,
                configurable: true
            });
            console.log("[Mahjong Soul Hook] WebSocket constructor replaced.");
        } catch (e) {
            console.error("[Mahjong Soul Hook] constructor patch failed:", e);
        }
    }
    installWebSocketConstructorPatch();

    console.log("[Mahjong Soul Hook] All hooks installed. Waiting for WebSocket packets...");

    // ----------------------------------------------------
    // 起動テスト: 3秒後にテストパケットを forwarder.py に送信
    // ----------------------------------------------------
    setTimeout(function() {
        try {
            const testData = btoa("test_packet_from_userscript_" + Date.now());
            const payload = JSON.stringify({ from_client: true, data: testData });
            console.log("[Mahjong Soul Hook] Sending TEST packet to forwarder...");
            GM_xmlhttpRequest({
                method: "POST",
                url: "http://127.0.0.1:8080/packet",
                data: payload,
                headers: { "Content-Type": "application/json" },
                onload: function(res) {
                    console.log("[Mahjong Soul Hook] TEST packet OK. status=" + res.status + " response=" + res.responseText);
                },
                onerror: function(err) {
                    console.error("[Mahjong Soul Hook] TEST packet FAILED:", err);
                }
            });
        } catch (e) {
            console.error("[Mahjong Soul Hook] TEST packet exception:", e);
        }
    }, 3000);
})();
