<script lang="ts">
	import { onMount } from 'svelte';
	import type { Map as LeafletMap, LayerGroup } from 'leaflet';

	interface StatusSource {
		mountpoint: string;
		alive: boolean;
		clients: number;
		bytes_received: number;
		latitude: number | null;
		longitude: number | null;
		height: number | null;
		antenna: string | null;
		receiver: string | null;
	}

	interface StatusResponse {
		status: string;
		running: boolean;
		sources: StatusSource[];
		total_clients: number;
	}

	interface Position {
		mountpoint: string;
		ip: string;
		latitude: number | null;
		longitude: number | null;
		fix_quality: number | null;
		num_sats: number | null;
		altitude: number | null;
		hdop: number | null;
		age_seconds: number | null;
	}

	let status = $state<StatusResponse | null>(null);
	let positions = $state<Position[]>([]);
	let lastUpdated = $state('');
	let mapEl = $state<HTMLDivElement>();

	// Нереактивные ссылки на объекты Leaflet (реактивность им не нужна)
	let L: typeof import('leaflet') | null = null;
	let map: LeafletMap | null = null;
	let roverGroup: LayerGroup | null = null;
	let sourceGroup: LayerGroup | null = null;
	let timer: ReturnType<typeof setInterval> | null = null;

	async function loadData() {
		try {
			const [stRes, posRes] = await Promise.all([fetch('/status'), fetch('/positions')]);
			if (stRes.ok) status = await stRes.json();
			if (posRes.ok) positions = await posRes.json();
			lastUpdated = new Date().toLocaleTimeString('ru-RU');
		} catch {
			/* сервер недоступен */
		}
	}

	function updateMarkers() {
		if (!L || !roverGroup || !sourceGroup) return;
		roverGroup.clearLayers();
		sourceGroup.clearLayers();

		for (const p of positions) {
			if (p.latitude == null || p.longitude == null) continue;
			const marker = L.circleMarker([p.latitude, p.longitude], {
				radius: 8,
				fillColor: '#0ca30c',
				fillOpacity: 0.8,
				color: '#fff',
				weight: 2
			});
			marker.bindPopup(
				`<strong>${p.mountpoint}</strong><br>` +
					`IP: ${p.ip}<br>` +
					`Fix: ${p.fix_quality ?? '—'} · Спутники: ${p.num_sats ?? '—'}<br>` +
					`Высота: ${p.altitude ?? '—'} м · HDOP: ${p.hdop ?? '—'}<br>` +
					`Возраст: ${p.age_seconds != null ? p.age_seconds.toFixed(1) + ' с' : '—'}`
			);
			roverGroup.addLayer(marker);
		}

		for (const s of status?.sources ?? []) {
			if (s.latitude == null || s.longitude == null) continue;
			const marker = L.circleMarker([s.latitude, s.longitude], {
				radius: 10,
				fillColor: s.alive ? '#2a78d6' : '#898781',
				fillOpacity: 0.8,
				color: '#fff',
				weight: 2
			});
			marker.bindPopup(
				`<strong>${s.mountpoint}</strong><br>` +
					`Статус: ${s.alive ? '🟢 online' : '⚪ offline'}<br>` +
					`Антенна: ${s.antenna ?? '—'}<br>` +
					`Приёмник: ${s.receiver ?? '—'}<br>` +
					`Клиентов: ${s.clients} · Принято: ${(s.bytes_received / 1024).toFixed(1)} KB`
			);
			sourceGroup.addLayer(marker);
		}
	}

	onMount(() => {
		let destroyed = false;

		// Leaflet обращается к window — грузим только на клиенте
		void (async () => {
			const leaflet = await import('leaflet');
			L = leaflet.default;

			if (destroyed || !mapEl || !L) return;

			map = L.map(mapEl, { center: [55.75, 37.62], zoom: 4 });

			L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
				maxZoom: 19,
				attribution: '&copy; OpenStreetMap contributors'
			}).addTo(map);

			sourceGroup = L.layerGroup().addTo(map);
			roverGroup = L.layerGroup().addTo(map);

			await loadData();
			if (destroyed) return;
			updateMarkers();

			timer = setInterval(() => {
				loadData().then(updateMarkers);
			}, 10000);
		})();

		return () => {
			destroyed = true;
			if (timer) clearInterval(timer);
			map?.remove();
			map = null;
		};
	});
</script>

<svelte:head>
	<title>Map — RuCaster</title>
</svelte:head>

<h2>Map</h2>
<p class="hint">
	Базовые станции (синие) и роверы с позицией (зелёные). Клик по маркеру — детали. Обновление каждые 10 с.
</p>

<div bind:this={mapEl} id="map-container"></div>

<div class="legend">
	<div class="legend-item"><span class="lm rover"></span> Роверы с позицией: {positions.length}</div>
	<div class="legend-item">
		<span class="lm source"></span> Базы с координатами:
		{(status?.sources ?? []).filter((s) => s.latitude != null && s.longitude != null).length}
	</div>
	<div class="legend-updated">Обновлено: {lastUpdated || '—'}</div>
</div>

<style>
	h2 {
		font-size: 15px;
		margin: 0 0 4px;
	}
	.hint {
		font-size: 12.5px;
		color: var(--muted, #898781);
		margin: 0 0 12px;
	}
	#map-container {
		height: 600px;
		width: 100%;
		border-radius: 12px;
		border: 1px solid var(--hairline, rgba(0, 0, 0, 0.1));
		background: var(--surface, #fff);
	}
	.legend {
		margin-top: 10px;
		background: var(--surface, #fff);
		border: 1px solid var(--hairline, rgba(0, 0, 0, 0.1));
		border-radius: 12px;
		padding: 12px 16px;
		font-size: 12.5px;
		line-height: 1.6;
	}
	.legend-item {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.lm {
		display: inline-block;
		width: 10px;
		height: 10px;
		border-radius: 50%;
		border: 1.5px solid #fff;
		box-shadow: 0 0 2px rgba(0, 0, 0, 0.4);
	}
	.lm.rover {
		background: #0ca30c;
	}
	.lm.source {
		background: #2a78d6;
	}
	.legend-updated {
		margin-top: 4px;
		font-size: 10.5px;
		color: var(--muted, #898781);
	}
</style>
