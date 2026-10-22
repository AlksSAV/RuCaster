<script lang="ts">
	let settings = $state({
		registration: true,
		auto_approve: false,
		anonymous_rovers: false,
		default_sources: 10,
		default_substitutions: 10
	});
	let message = $state('');

	async function save() {
		message = '';
		const res = await fetch('/api/settings/registration', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			credentials: 'include',
			body: JSON.stringify({
				enabled: settings.registration,
				auto_approve: settings.auto_approve
			})
		});
		message = res.ok ? 'saved' : 'failed';
	}
</script>

<h2>Settings</h2>

<div class="card">
	<label class="row">
		<input type="checkbox" bind:checked={settings.registration} />
		Registration enabled
	</label>
	<label class="row">
		<input type="checkbox" bind:checked={settings.auto_approve} />
		Auto-approve new users
	</label>
	<label class="row">
		<input type="checkbox" bind:checked={settings.anonymous_rovers} />
		Allow anonymous rovers
	</label>
	<div class="row">
		<label>
			Default sources quota
			<input type="number" bind:value={settings.default_sources} min="0" />
		</label>
		<label>
			Default substitutions quota
			<input type="number" bind:value={settings.default_substitutions} min="0" />
		</label>
	</div>
	<button class="btn" onclick={save}>Save</button>
	{#if message}<span class="msg">{message}</span>{/if}
</div>

<style>
	h2 {
		font-size: 15px;
		margin: 0 0 14px;
	}
	.card {
		background: var(--surface, #fff);
		border: 1px solid var(--hairline, rgba(0, 0, 0, 0.1));
		border-radius: 12px;
		padding: 16px 18px;
	}
	.row {
		display: flex;
		gap: 10px;
		align-items: center;
		margin-bottom: 10px;
		font-size: 13px;
	}
	label input[type='number'] {
		width: 70px;
		margin-left: 8px;
		padding: 5px 8px;
		border: 1px solid var(--hairline, rgba(0, 0, 0, 0.15));
		border-radius: 7px;
	}
	.btn {
		padding: 7px 14px;
		border: 1px solid transparent;
		border-radius: 8px;
		background: var(--accent, #2a78d6);
		color: #fff;
		cursor: pointer;
		font-size: 13px;
		font-weight: 600;
	}
	.msg {
		font-size: 12px;
		margin-left: 10px;
	}
</style>
