import { writable } from 'svelte/store';

export interface StatusSource {
	mountpoint: string;
	alive: boolean;
	peer?: string;
	clients: number;
	bytes_received: number;
	latitude?: number;
	longitude?: number;
	antenna?: string;
	receiver?: string;
}

export interface CasterStatus {
	status: string;
	host: string;
	port: number;
	running: boolean;
	sources: StatusSource[];
	total_clients: number;
	active_connections: number;
}

export const status = writable<CasterStatus | null>(null);
export const lastUpdated = writable<number>(0);

export async function pollStatus(): Promise<void> {
	if (typeof document !== 'undefined' && document.hidden) return;
	try {
		const res = await fetch('/status', { credentials: 'include' });
		if (!res.ok) return;
		status.set((await res.json()) as CasterStatus);
		lastUpdated.set(Date.now());
	} catch {
		/* сервер недоступен — оставляем прошлое состояние */
	}
}
