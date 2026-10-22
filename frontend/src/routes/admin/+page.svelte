<script lang="ts">
	interface AdminUser {
		username: string;
		email: string;
		role: string;
		status: string;
		created_at: string | null;
	}

	let users = $state<AdminUser[]>([]);
	let error = $state('');

	async function load() {
		const res = await fetch('/api/users', { credentials: 'include' });
		if (res.status === 403) {
			error = 'admin only';
			return;
		}
		if (res.ok) users = await res.json();
	}

	async function act(username: string, action: string) {
		await fetch(`/api/users/${username}/${action}`, {
			method: 'POST',
			credentials: 'include'
		});
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
	<div class="card">
		<table>
			<thead>
				<tr><th>Username</th><th>Email</th><th>Role</th><th>Status</th><th></th></tr>
			</thead>
			<tbody>
				{#if users.length === 0}
					<tr><td colspan="5" class="empty">No users</td></tr>
				{:else}
					{#each users as u (u.username)}
						<tr>
							<td>{u.username}</td>
							<td>{u.email}</td>
							<td>{u.role}</td>
							<td>{u.status}</td>
							<td class="actions">
								{#if u.status === 'pending'}
									<button class="btn" onclick={() => act(u.username, 'approve')}>Approve</button>
									<button class="btn danger" onclick={() => act(u.username, 'reject')}>Reject</button>
								{:else if u.status === 'blocked'}
									<button class="btn" onclick={() => act(u.username, 'unblock')}>Unblock</button>
								{:else}
									<button class="btn danger" onclick={() => act(u.username, 'block')}>Block</button>
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
