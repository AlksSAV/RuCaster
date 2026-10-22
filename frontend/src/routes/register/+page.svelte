<script lang="ts">
	let username = $state('');
	let email = $state('');
	let password = $state('');
	let message = $state('');
	let error = $state('');

	async function submit() {
		error = '';
		message = '';
		const res = await fetch('/api/auth/register', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			credentials: 'include',
			body: JSON.stringify({ username, email, password })
		});
		if (res.ok) {
			message = 'Registration submitted, waiting for admin approval';
		} else {
			const data = await res.json().catch(() => ({}));
			error = data.error ?? 'registration failed';
		}
	}
</script>

<div class="box">
	<h2>Register</h2>
	<form
		onsubmit={(e) => {
			e.preventDefault();
			submit();
		}}
	>
		<label>
			Username
			<input type="text" bind:value={username} autocomplete="username" />
		</label>
		<label>
			Email
			<input type="email" bind:value={email} autocomplete="email" />
		</label>
		<label>
			Password
			<input type="password" bind:value={password} autocomplete="new-password" />
		</label>
		{#if error}<div class="error">{error}</div>{/if}
		{#if message}<div class="ok">{message}</div>{/if}
		<button class="btn" type="submit">Register</button>
	</form>
	<p class="hint">Already registered? <a href="/login">Sign in</a></p>
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
	.error {
		font-size: 12px;
		color: var(--critical, #d03b3b);
		margin-bottom: 10px;
	}
	.ok {
		font-size: 12px;
		color: var(--good, #0ca30c);
		margin-bottom: 10px;
	}
	.hint {
		font-size: 12px;
		color: var(--muted, #898781);
		text-align: center;
		margin: 14px 0 0;
	}
</style>
