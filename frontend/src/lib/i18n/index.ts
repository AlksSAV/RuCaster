/**
 * Простой i18n: RU/EN, язык хранится в localStorage["rucaster_lang"].
 * Использование: t('dashboard') или t('sources_count', { n: 5 }).
 */

import { get, writable } from 'svelte/store';

type Dict = Record<string, string>;

const en: Dict = {
	dashboard: 'Dashboard',
	stations: 'Stations',
	admin: 'Users',
	settings: 'Settings',
	status: 'Status',
	sources: 'Sources',
	clients: 'Clients',
	rovers: 'Rovers with position',
	inbound_rate: 'Inbound rate',
	online: 'ONLINE',
	offline: 'OFFLINE',
	no_link: 'NO LINK',
	login: 'Login',
	logout: 'Logout',
	register: 'Register',
	password: 'Password',
	add: 'Add',
	delete: 'Delete',
	save: 'Save',
	approve: 'Approve',
	reject: 'Reject',
	block: 'Block',
	unblock: 'Unblock',
	no_sources: 'No sources'
};

const ru: Dict = {
	dashboard: 'Панель',
	stations: 'Станции',
	admin: 'Пользователи',
	settings: 'Настройки',
	status: 'Статус',
	sources: 'Источники',
	clients: 'Клиенты',
	rovers: 'Роверы с позицией',
	inbound_rate: 'Приём',
	online: 'В РАБОТЕ',
	offline: 'НЕТ ИСТОЧНИКОВ',
	no_link: 'НЕТ СВЯЗИ',
	login: 'Войти',
	logout: 'Выйти',
	register: 'Регистрация',
	password: 'Пароль',
	add: 'Добавить',
	delete: 'Удалить',
	save: 'Сохранить',
	approve: 'Одобрить',
	reject: 'Отклонить',
	block: 'Блок',
	unblock: 'Разблок',
	no_sources: 'Нет источников'
};

const dicts: Record<string, Dict> = { en, ru };

function detect(): string {
	if (typeof localStorage !== 'undefined') {
		const saved = localStorage.getItem('rucaster_lang');
		if (saved && dicts[saved]) return saved;
	}
	if (typeof navigator !== 'undefined' && navigator.language.startsWith('ru')) return 'ru';
	return 'en';
}

export const lang = writable<string>(detect());

if (typeof localStorage !== 'undefined') {
	lang.subscribe((v) => localStorage.setItem('rucaster_lang', v));
}

export function t(key: string, params?: Record<string, string | number>): string {
	// $lang (auto-subscription) доступен только внутри .svelte-компонентов,
	// поэтому в модуле читаем значение стора явно.
	let text = dicts[get(lang)]?.[key] ?? dicts.en[key] ?? key;
	if (params) {
		for (const [k, v] of Object.entries(params)) {
			text = text.replaceAll(`{${k}}`, String(v));
		}
	}
	return text;
}

export function toggleLang() {
	lang.update((l) => (l === 'ru' ? 'en' : 'ru'));
}
