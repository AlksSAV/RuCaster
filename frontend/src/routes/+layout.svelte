<script lang="ts">
	import '../app.css';
	import type { Snippet } from 'svelte';
	let { children }: { children: Snippet } = $props();
</script>

<div class="app">
	<header class="header">
		<div class="wrap header-row">
			<h1>RuCaster</h1>
			<nav>
				<a href="/dashboard">Dashboard</a>
				<a href="/stations">Stations</a>
				<a href="/admin">Admin</a>
				<a href="/settings">Settings</a>
			</nav>
		</div>
	</header>

	<main class="wrap">
		{@render children()}
	</main>

	<footer class="footer">
		<div class="wrap">© 2026 RuCaster</div>
	</footer>
</div>

<style>
	.header {
		border-bottom: 1px solid var(--hairline, rgba(0, 0, 0, 0.1));
		background: var(--surface, #fff);
	}
	.wrap {
		max-width: 1100px;
		margin: 0 auto;
		padding: 0 20px;
	}
	.header-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding-top: 14px;
		padding-bottom: 14px;
	}
	h1 {
		margin: 0;
		font-size: 17px;
		font-weight: 650;
	}
	nav {
		display: flex;
		gap: 16px;
	}
	nav a {
		font-size: 13px;
		color: var(--accent, #2a78d6);
		text-decoration: none;
	}
	main {
		padding: 20px 0 40px;
	}
	.footer {
		border-top: 1px solid var(--hairline, rgba(0, 0, 0, 0.1));
		padding: 14px 0;
		text-align: center;
		color: var(--muted, #888);
		font-size: 12px;
	}
</style>
