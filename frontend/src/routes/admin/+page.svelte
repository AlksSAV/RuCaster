<script lang="ts">
	interface AdminUser {
		username: string;
		email: string;
		role: string;
		status: string;
		quotas: { sources: number; substitutions: number };
		can_record: boolean;
		created_at: string | null;
	}

	let users = $state<AdminUser[]>([]);
	let error = $state('');
	let message = $state('');
	// локальный черновик квот: username -> {sources, substitutions}
	let drafts = $state<Record<string, { sources: number; substitutions: number }>>({});

	async function load() {
		const res = await fetch('/api/users', { credentials: 'include' });
		if (res.status === 403) {
			error = 'admin only';
			return;
		}
		if (!res.ok) {
			error = 'failed to load users';
			return;
		}
		error = '';
		users = await res.json();
		drafts = Object.fromEntries(
			users.map((u) => [
				u.username,
				{
					sources: u.quotas?.sources ?? 0,
					substitutions: u.quotas?.substitutions ?? 0
				}
			])
		);
	}

	async function act(username: string, action: string) {
		const res = await fetch(`/api/users/${username}/${action}`, {
			method: 'POST',
			credentials: 'include'
		});
		if (!res.ok) message = `${action} failed: ${res.status}`;
		else message = '';
		await load();
	}

	async function saveQuota(username: string) {
		const d = drafts[username];
		const res = await fetch(`/api/users/${username}/quota`, {
			method: 'PATCH',
			credentials: 'include',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				quotas_sources: d.sources,
				quotas_substitutions: d.substitutions
			})
		});
		message = res.ok ? '' : `quota update failed: ${res.status}`;
		await load();
	}

	async function toggleRecord(username: string, value: boolean) {
		const res = await fetch(`/api/users/${username}/can-record`, {
			method: 'POST',
			credentials: 'include',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ can_record: value })
		});
		message = res.ok ? '' : `can-record update failed: ${res.status}`;
		await load();
	}

	async function remove(username: string) {
		if (!confirm(`Delete user ${username}?`)) return;
		const res = await fetch(`/api/users/${username}`, {
			method: 'DELETE',
			credentials: 'include'
		});
		if (res.status === 409) message = 'user has sources — delete them first';
		else if (!res.ok) message = `delete failed: ${res.status}`;
		else message = '';
		await load();
	}

	$effect(() => {
		load();
	});
</script>

<h2>Users</h2>

{#if error}
	<div class="card empty">{error}</div>
{:else}
	{#if message}
		<div class="banner">{message}</div>
	{/if}
	<div class="card">
		<table>
			<thead>
				<tr>
					<th>Username</th>
					<th>Email</th>
					<th>Role</th>
					<th>Status</th>
					<th>Quota: sources</th>
					<th>Quota: subst.</th>
					<th>Record</th>
					<th></th>
				</tr>
			</thead>
			<tbody>
				{#if users.length === 0}
					<tr><td colspan="8" class="empty">No users</td></tr>
				{:else}
					{#each users as u (u.username)}
						<tr>
							<td>{u.username}</td>
							<td>{u.email}</td>
							<td>{u.role}</td>
							<td>{u.status}</td>
							<td>
								<input
									type="number"
									min="0"
									class="quota"
									bind:value={drafts[u.username].sources}
									disabled={u.role === 'admin'}
								/>
							</td>
							<td>
								<input
									type="number"
									min="0"
									class="quota"
									bind:value={drafts[u.username].substitutions}
									disabled={u.role === 'admin'}
								/>
							</td>
							<td>
								<input
									type="checkbox"
									checked={u.can_record}
									disabled={u.role === 'admin'}
									onchange={(e) =>
										toggleRecord(u.username, (e.target as HTMLInputElement).checked)}
								/>
							</td>
							<td class="actions">
								{#if u.role !== 'admin'}
									<button class="btn" onclick={() => saveQuota(u.username)}>Save</button>
								{/if}
								{#if u.status === 'pending'}
									<button class="btn" onclick={() => act(u.username, 'approve')}>Approve</button>
									<button class="btn danger" onclick={() => act(u.username, 'reject')}>Reject</button>
								{:else if u.status === 'blocked'}
									<button class="btn" onclick={() => act(u.username, 'unblock')}>Unblock</button>
								{:else if u.role !== 'admin'}
									<button class="btn danger" onclick={() => act(u.username, 'block')}>Block</button>
								{/if}
								{#if u.role !== 'admin'}
									<button class="btn danger" onclick={() => remove(u.username)}>Delete</button>
								{/if}
							</td>
						</tr>
					{/each}
				{/if}
			</tbody>
		</table>
	</div>
{/if}

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
	.banner {
		background: var(--critical-bg, rgba(208, 59, 59, 0.08));
		color: var(--critical, #d03b3b);
		font-size: 12.5px;
		padding: 8px 12px;
		border-radius: 8px;
		margin-bottom: 12px;
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
		vertical-align: middle;
	}
	.quota {
		width: 64px;
		padding: 3px 6px;
		font-size: 12.5px;
		border: 1px solid var(--hairline, rgba(0, 0, 0, 0.15));
		border-radius: 6px;
		background: var(--surface, #fff);
		color: inherit;
	}
	.actions {
		white-space: nowrap;
	}
	.btn {
		padding: 4px 10px;
		border: 1px solid transparent;
		border-radius: 7px;
		background: var(--accent, #2a78d6);
		color: #fff;
		cursor: pointer;
		font-size: 12px;
		margin-right: 6px;
	}
	.btn.danger {
		background: var(--critical, #d03b3b);
	}
	.empty {
		color: var(--muted, #898781);
	}
</style>
