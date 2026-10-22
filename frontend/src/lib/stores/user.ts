import { writable } from 'svelte/store';

export interface UserInfo {
	username: string;
	email?: string;
	role: 'user' | 'admin';
	status?: string;
	can_record?: boolean;
}

export const currentUser = writable<UserInfo | null>(null);

export async function loadUser(): Promise<UserInfo | null> {
	try {
		const res = await fetch('/api/auth/me', { credentials: 'include' });
		if (!res.ok) {
			currentUser.set(null);
			return null;
		}
		const user = (await res.json()) as UserInfo;
		currentUser.set(user);
		return user;
	} catch {
		currentUser.set(null);
		return null;
	}
}

export async function logout(): Promise<void> {
	await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
	currentUser.set(null);
	window.location.href = '/login';
}
