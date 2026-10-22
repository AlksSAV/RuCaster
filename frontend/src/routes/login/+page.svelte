<script lang="ts">
	let login = $state('');
	let password = $state('');
	let error = $state('');
	let loading = $state(false);

	async function submit() {
		error = '';
		loading = true;
		try {
			const res = await fetch('/api/auth/login', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				credentials: 'include',
				body: JSON.stringify({ username: login, password })
			});
			if (res.ok) {
				window.location.href = '/dashboard';
			} else {
				const data = await res.json().catch(() => ({}));
				error = data.error ?? 'login failed';
			}
		} catch {
			error = 'server unavailable';
		} finally {
			loading = false;
		}
	}
</script>

<div class="box">
	<h2>Sign in</h2>
	<form
		onsubmit={(e) => {
			e.preventDefault();
			submit();
		}}
	>
		<label>
			Username or email
			<input type="text" bind:value={login} autocomplete="username" />
		</label>
		<label>
			Password
			<input type="password" bind:value={password} autocomplete="current-password" />
		</label>
		{#if error}<div class="error">{error}</div>{/if}
		<button class="btn" disabled={loading} type="submit">Login</button>
	</form>
	<p class="hint">No account? <a href="/register">Register</a></p>
</div>

<style>
	.box {
		max-width: 360px;
		margin: 60px auto;
		background: var(--surface, #fff);
		border: 1px solid var(--hairline, rgba(0, 0, 0, 0.1));
		border-radius: 12px;
		padding: 24px;
	}
	h2 {
		margin: 0 0 16px;
		font-size: 16px;
	}
	label {
		display: block;
		font-size: 12px;
		color: var(--ink-2, #52514e);
		margin-bottom: 12px;
	}
	input {
		display: block;
		width: 100%;
		margin-top: 4px;
		padding: 8px 10px;
		border: 1px solid var(--hairline, rgba(0, 0, 0, 0.15));
		border-radius: 8px;
		font-size: 13px;
		box-sizing: border-box;
	}
	.btn {
		width: 100%;
		padding: 9px;
		border: 1px solid transparent;
		border-radius: 8px;
		background: var(--accent, #2a78d6);
		color: #fff;
		font-size: 14px;
		font-weight: 600;
		cursor: pointer;
	}
	.btn:disabled {
		opacity: 0.6;
	}
	.error {
		font-size: 12px;
		color: var(--critical, #d03b3b);
		margin-bottom: 10px;
	}
	.hint {
		font-size: 12px;
		color: var(--muted, #898781);
		text-align: center;
		margin: 14px 0 0;
	}
</style>
