import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		port: 5173,
		proxy: {
			'/api': 'http://localhost:8001',
			'/status': 'http://localhost:8001',
			'/clients': 'http://localhost:8001',
			'/positions': 'http://localhost:8001',
			'/connections': 'http://localhost:8001',
			'/statistics': 'http://localhost:8001',
			'/health': 'http://localhost:8001',
			'/ws': {
				target: 'ws://localhost:8001',
				ws: true
			}
		}
	}
});
