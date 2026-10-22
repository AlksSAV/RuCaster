<script lang="ts">
	let status = {
		running: false,
		sources: 0,
		total_clients: 0,
		rovers: 0,
		rate: '—',
		totalBytes: 0
	};

	let error = $state(false);

	async function loadStatus() {
		if (document.hidden) return;
		try {
			const res = await fetch('/status', { credentials: 'include' });
			if (!res.ok) throw new Error('not ok');
			const data = await res.json();
			status.running = data.running;
			status.sources = data.sources?.length ?? 0;
			status.total_clients = data.total_clients ?? 0;
			error = false;
		} catch {
			error = true;
		}
	}

	$effect(() => {
		loadStatus();
		const timer = setInterval(loadStatus, 5000);
		return () => clearInterval(timer);
	});
</script>

<section class="kpi-row">
	<div class="card">
		<div class="label">Status</div>
		<div class="value" class:good={status.running} class:bad={error}>
			{error ? 'NO LINK' : status.running ? 'ONLINE' : 'OFFLINE'}
		</div>
	</div>
	<div class="card">
		<div class="label">Sources</div>
		<div class="value">{status.sources}</div>
	</div>
	<div class="card">
		<div class="label">Clients</div>
		<div class="value">{status.total_clients}</div>
	</div>
	<div class="card">
		<div class="label">Rovers with position</div>
		<div class="value">{status.rovers}</div>
	</div>
	<div class="card">
		<div class="label">Inbound rate</div>
		<div class="value">{status.rate}</div>
	</div>
</section>

<style>
	.kpi-row {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
		gap: 14px;
	}
	.card {
		background: var(--surface, #fff);
		border: 1px solid var(--hairline, rgba(0, 0, 0, 0.1));
		border-radius: 12px;
		padding: 16px 18px;
	}
	.label {
		font-size: 12px;
		color: var(--ink-2, #52514e);
	}
	.value {
		font-size: 28px;
		font-weight: 600;
		margin-top: 2px;
	}
	.good {
		color: var(--good, #0ca30c);
	}
	.bad {
		color: var(--critical, #d03b3b);
	}
</style>
