/**
 * WebSocket-клиент с автопереподключением.
 * События бэкенда приходят как JSON: {type: string, data: unknown}.
 */

import { writable } from 'svelte/store';

export type WsMessage = { type: string; data?: unknown };

export const wsConnected = writable(false);

let socket: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
const listeners = new Set<(msg: WsMessage) => void>();

function wsUrl(): string {
	const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
	return `${proto}//${location.host}/ws`;
}

function connect() {
	if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
		return;
	}

	socket = new WebSocket(wsUrl());

	socket.onopen = () => {
		wsConnected.set(true);
	};

	socket.onmessage = (event) => {
		try {
			const msg = JSON.parse(event.data) as WsMessage;
			listeners.forEach((fn) => fn(msg));
		} catch {
			/* игнорируем не-JSON кадры */
		}
	};

	socket.onclose = () => {
		wsConnected.set(false);
		socket = null;
		// экспоненциальная задержка до 30 с
		if (!reconnectTimer) {
			reconnectTimer = setTimeout(() => {
				reconnectTimer = null;
				connect();
			}, 2000);
		}
	};

	socket.onerror = () => socket?.close();
}

export function onWs(fn: (msg: WsMessage) => void): () => void {
	listeners.add(fn);
	connect();
	return () => listeners.delete(fn);
}

export function sendWs(msg: unknown) {
	if (socket?.readyState === WebSocket.OPEN) {
		socket.send(JSON.stringify(msg));
	}
}
