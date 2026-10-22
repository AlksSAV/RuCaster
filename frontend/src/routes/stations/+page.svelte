<script lang="ts">
	interface Source {
		id: string;
		mountpoint: string;
		connected: boolean;
		owner: string;
		mine: boolean;
		editable: boolean;
	}

	let sources = $state<Source[]>([]);
	let newMp = $state('');
	let newPass = $state('');
	let message = $state('');

	async function load() {
		try {
			const res = await fetch('/api/sources', { credentials: 'include' });
			if (res.ok) sources = await res.json();
		} catch {
			/* ignore */
		}
	}

	async function addSource() {
		message = '';
		if (!newMp || !newPass) {
			message = 'mountpoint and password required';
			return;
		}
		const res = await fetch('/api/sources', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			credentials: 'include',
			body: JSON.stringify({ mountpoint: newMp, password: newPass })
		});
		if (res.ok) {
			newMp = '';
			newPass = '';
			await load();
		} else {
			const err = await res.json().catch(() => ({}));
			message = err.error ?? err.detail ?? 'failed';
		}
	}

	async function remove(mp: string) {
		if (!confirm(`Delete ${mp}?`)) return;
		await fetch(`/api/sources/${mp}`, { method: 'DELETE', credentials: 'include' });
		await load();
	}

	$effect(() => {
		load();
		const timer = setInterval(load, 10000);
		return () => clearInterval(timer);
	});
</script>

<h2>Stations</h2>

<div class="card form">
	<div class="field">
		<label for="mp">Mountpoint</label>
		<input id="mp" bind:value={newMp} placeholder="MYBASE" />
	</div>
	<div class="field">
		<label for="pw">Password</label>
		<input id="pw" bind:value={newPass} placeholder="strong_password" />
	</div>
	<button class="btn" onclick={addSource}>Add</button>
	{#if message}<span class="msg">{message}</span>{/if}
</div>

<div class="card">
	<table>
		<thead>
			<tr><th>Mountpoint</th><th>Status</th><th>Owner</th><th></th></tr>
		</thead>
		<tbody>
			{#if sources.length === 0}
				<tr><td colspan="4" class="empty">No sources</td></tr>
			{:else}
				{#each sources as s (s.id)}
					<tr>
						<td>{s.mountpoint}</td>
						<td class={s.connected ? 'good' : ''}>{s.connected ? 'online' : 'offline'}</td>
						<td>{s.owner}</td>
						<td>{#if s.editable}<button class="btn danger" onclick={() => remove(s.mountpoint)}>Delete</button>{/if}</td>
					</tr>
				{/each}
			{/if}
		</tbody>
	</table>
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
		margin-bottom: 14px;
	}
	.form {
		display: flex;
		gap: 10px;
		align-items: flex-end;
		flex-wrap: wrap;
	}
	.field label {
		display: block;
		font-size: 11px;
		color: var(--muted, #898781);
		margin-bottom: 3px;
	}
	.field input {
		padding: 6px 9px;
		border: 1px solid var(--hairline, rgba(0, 0, 0, 0.15));
		border-radius: 7px;
		font-size: 13px;
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
	.btn.danger {
		background: var(--critical, #d03b3b);
		padding: 4px 10px;
		font-size: 12px;
	}
	.msg {
		font-size: 12px;
		color: var(--critical, #d03b3b);
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 13px;
	}
	th {
		text-align: left;
		font-size: 11.5px;
		font-weight: 600;
		color: var(--muted, #898781);
		padding: 4px 8px 6px;
		border-bottom: 1px solid var(--grid, #e1e0d9);
	}
	td {
		padding: 6px 8px;
		border-bottom: 1px solid var(--hairline, rgba(0, 0, 0, 0.08));
	}
	.good {
		color: var(--good, #0ca30c);
	}
	.empty {
		color: var(--muted, #898781);
	}
</style>
