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

    /**
     * @title キュー処理関数
     * @description キューに溜まったパケットを順次、同期的にローカルサーバーへ送信します。
     * @returns {void}
     */
    function processQueue() {
        if (isSending || packetQueue.length === 0) return;
        isSending = true;

        const { payload, resolve } = packetQueue.shift();

        // ネットワーク障害やタイムアウト時もキューが詰まらないように次のキューを実行
        const next = () => {
            isSending = false;
            resolve();
            processQueue();
        };

        if (typeof GM_xmlhttpRequest !== 'undefined') {
            GM_xmlhttpRequest({
                method: 'POST',
                url: LOCAL_SERVER_URL,
                headers: {
                    'Content-Type': 'application/json'
                },
                data: payload,
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
                const base64Data = arrayBufferToBase64(buffer);
                const payload = JSON.stringify({
                    from_client: fromClient,
                    data: base64Data
                });

                new Promise((resolve) => {
                    packetQueue.push({ payload, resolve });
                    processQueue();
                });
            } catch (e) {
                console.error("[Mahjong Soul Hook] パケット準備エラー:", e);
            }
        }, 0);
    }

    // 元のWebSocketコンストラクタを保持
    const OriginalWebSocket = targetWindow.WebSocket;

    if (!OriginalWebSocket) {
        console.error("[Mahjong Soul Hook] ターゲットのWebSocketクラスが見つかりません。");
        return;
    }

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
                console.error("[Mahjong Soul Hook] Blobデコードエラー:", err);
            });
        }
    }

    // ----------------------------------------------------
    // Prototypeメソッドのフック開始
    // ----------------------------------------------------

    // 1. 送信処理 (send) のフック
    const originalSend = OriginalWebSocket.prototype.send;
    OriginalWebSocket.prototype.send = function(data) {
        try {
            extractArrayBuffer(data, (buf) => {
                forwardPacket(buf, true);
            });
        } catch (e) {
            console.error("[Mahjong Soul Hook] 送信データ取得エラー:", e);
        }
        // 元の送信メソッドを実行
        return originalSend.apply(this, arguments);
    };

    // 2. 受信処理 (addEventListener) のフック
    const originalAddEventListener = OriginalWebSocket.prototype.addEventListener;
    OriginalWebSocket.prototype.addEventListener = function(type, listener, options) {
        if (type === 'message') {
            const wrappedListener = function(event) {
                try {
                    extractArrayBuffer(event.data, (buf) => {
                        forwardPacket(buf, false);
                    });
                } catch (e) {
                    console.error("[Mahjong Soul Hook] 受信データ取得エラー (addEventListener):", e);
                }
                // ゲーム側の本来の処理を実行
                return listener.apply(this, arguments);
            };

            // 動的な removeEventListener 呼び出しに対応するため、関連を保存
            if (!this._wrappedListeners) {
                this._wrappedListeners = new Map();
            }
            this._wrappedListeners.set(listener, wrappedListener);

            return originalAddEventListener.call(this, type, wrappedListener, options);
        }
        return originalAddEventListener.apply(this, arguments);
    };

    // 3. 登録解除 (removeEventListener) のフック
    const originalRemoveEventListener = OriginalWebSocket.prototype.removeEventListener;
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
                        console.error("[Mahjong Soul Hook] 受信データ取得エラー (onmessage):", e);
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

    console.log("[Mahjong Soul Hook] WebSocketプロトタイプのフックに成功しました。");
})();
