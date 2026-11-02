<template>
    <Transition enter-active-class="transition duration-200 ease-out" enter-from-class="opacity-0" leave-active-class="transition duration-150 ease-in" leave-to-class="opacity-0">
        <div v-if="visible" class="fixed inset-0 z-[70] flex items-center justify-center p-3 sm:p-6 bg-[#031a33]/60 backdrop-blur-sm" @click.self="close">
            <div class="relative w-full max-w-lg rounded-3xl overflow-hidden bg-white dark:bg-zinc-900 shadow-[0_40px_100px_rgba(3,26,51,0.55)] ring-1 ring-black/5 dark:ring-white/10"
                 role="dialog" aria-modal="true" aria-label="Update available">
                <div class="relative px-6 pt-6 pb-5 text-white bg-[radial-gradient(120%_140%_at_0%_0%,#0a4f92_0%,#013E74_45%,#062b52_100%)]">
                    <button @click="close" type="button" aria-label="Close"
                            class="absolute top-4 right-4 w-9 h-9 rounded-full flex items-center justify-center bg-white/10 hover:bg-white/20 transition">
                        <MaterialDesignIcon icon-name="close" class="w-5 h-5"/>
                    </button>
                    <div class="flex items-center gap-3">
                        <div class="w-11 h-11 rounded-2xl flex items-center justify-center bg-[#E8C86A] text-[#062b52]">
                            <MaterialDesignIcon icon-name="download" class="w-6 h-6"/>
                        </div>
                        <div>
                            <div class="text-lg font-semibold">LCS MeshChat {{ u.latest }} is available</div>
                            <div class="text-sm text-blue-100/90">You have version {{ u.current }}.</div>
                        </div>
                    </div>
                    <div class="absolute bottom-0 left-0 right-0 h-[3px] bg-gradient-to-r from-[#1e5aa0] via-[#E8C86A] to-[#062b52]"></div>
                </div>

                <div class="px-6 py-5 space-y-4">
                    <!-- desktop: the same kind of file that's installed now, from GitHub and from the LCS mirror -->
                    <template v-if="files.length">
                        <p class="text-sm text-gray-700 dark:text-zinc-300">{{ howTo }}</p>
                        <div class="space-y-2">
                            <button v-for="(d, i) in files" :key="d.source" @click="open(d.url)" type="button"
                                    class="w-full flex items-center gap-3 px-4 py-3 rounded-2xl text-left shadow-sm transition"
                                    :class="i === 0 ? 'text-white bg-[#013E74] hover:bg-[#0a4f92]' : 'text-[#013E74] bg-white ring-1 ring-[#013E74]/25 hover:bg-gray-50 dark:bg-zinc-800 dark:text-zinc-100 dark:ring-zinc-600'">
                                <MaterialDesignIcon icon-name="download" class="w-5 h-5 shrink-0"/>
                                <span class="min-w-0">
                                    <span class="block font-bold">Download from {{ d.source === 'GitHub' ? 'GitHub' : 'the LCS mirror' }}<span v-if="d.version !== u.latest" class="font-normal"> (version {{ d.version }})</span></span>
                                    <span class="block text-xs opacity-80 truncate">{{ d.file }}</span>
                                </span>
                            </button>
                        </div>
                    </template>
                    <template v-else-if="u.kind === 'docker'">
                        <p class="text-sm text-gray-700 dark:text-zinc-300">Update the container where MeshChat runs:</p>
                        <pre class="text-xs rounded-xl p-3 bg-gray-100 dark:bg-zinc-800 overflow-x-auto select-all">docker compose pull
docker compose up -d</pre>
                    </template>
                    <template v-else>
                        <button v-for="d in u.downloads" :key="d.source" @click="open(d.page)" type="button"
                                class="w-full inline-flex items-center justify-center gap-2 px-5 py-3 rounded-2xl font-bold text-white bg-[#013E74] hover:bg-[#0a4f92] shadow-sm transition">
                            <MaterialDesignIcon icon-name="open-in-new" class="w-5 h-5"/>
                            Open the downloads on {{ d.source === 'GitHub' ? 'GitHub' : 'the LCS mirror' }}
                        </button>
                    </template>

                    <details v-if="u.notes" class="group rounded-xl border border-gray-200 dark:border-zinc-700 px-4 py-2.5">
                        <summary class="cursor-pointer select-none text-sm font-semibold text-[#013E74] dark:text-[#8fb8e8] list-none flex items-center gap-2">
                            What's new
                            <MaterialDesignIcon icon-name="chevron-down" class="w-4 h-4 ml-auto transition-transform group-open:rotate-180"/>
                        </summary>
                        <div class="pt-2 max-h-48 overflow-y-auto whitespace-pre-wrap text-xs leading-relaxed text-gray-600 dark:text-zinc-400">{{ u.notes }}</div>
                    </details>
                    <div v-if="files.length" class="flex flex-wrap gap-x-4 gap-y-1">
                        <button v-for="d in u.downloads" :key="d.source + '-page'" @click="open(d.page)" type="button" class="text-xs text-gray-500 dark:text-zinc-400 underline underline-offset-2">All downloads on {{ d.source === 'GitHub' ? 'GitHub' : 'the LCS mirror' }}</button>
                    </div>
                </div>

                <div class="flex items-center gap-3 px-6 py-3.5 border-t border-gray-100 bg-gray-50/80 dark:bg-zinc-800/60 dark:border-zinc-800">
                    <label class="flex items-center gap-2 text-sm text-gray-600 dark:text-zinc-300 cursor-pointer select-none">
                        <input v-model="dontShowAgain" type="checkbox" class="rounded border-gray-300 text-[#013E74] focus:ring-[#013E74]"/>
                        Don't show this again
                    </label>
                    <button @click="close" type="button"
                            class="ml-auto px-5 py-2 rounded-xl text-sm font-semibold text-gray-700 bg-white border border-gray-200 hover:bg-gray-100 dark:bg-zinc-800 dark:text-zinc-100 dark:border-zinc-600 dark:hover:bg-zinc-700">
                        Not now
                    </button>
                </div>
            </div>
        </div>
    </Transition>
</template>

<script>
import MaterialDesignIcon from "./MaterialDesignIcon.vue";
import LcsGlobal from "../js/LcsGlobal";

export default {
    name: "AppUpdateModal",
    components: { MaterialDesignIcon },
    data() {
        return { lg: LcsGlobal, u: null, shown: false, closed: false, dontShowAgain: false };
    },
    computed: {
        // wait until the LCS Global start-up popup is out of the way
        visible() { return this.shown && !this.closed && !this.lg.popup; },
        // newest first; only links to a file of the same kind as this install
        files() { return (this.u?.downloads ?? []).filter((d) => d.url).sort((a, b) => (a.version === this.u.latest ? -1 : 0) - (b.version === this.u.latest ? -1 : 0)); },
        howTo() {
            return {
                "win-installer": "Download the new installer and run it. It installs over this version and keeps your messages and settings.",
                "win-portable": "Download the new portable app and use it in place of this one, in the same folder, so it finds your messages and settings.",
                "mac-arm64": "Download the new version, open it and drag it into Applications, replacing this one. Your messages and settings are kept.",
                "mac-x64": "Download the new version, open it and drag it into Applications, replacing this one. Your messages and settings are kept.",
                "linux-appimage": "Download the new AppImage, make it executable and use it in place of this one. Your messages and settings are kept.",
            }[this.u?.kind] ?? "Download the new version to replace this one.";
        },
    },
    async mounted() {
        // once at start-up (the backend asks at most every 12 hours). With Tor on, it waits for
        // Tor to connect, so ask again every 20 seconds for a few minutes.
        for (let tries = 0; tries < 15; tries++) {
            try {
                const response = await window.axios.get("/api/v1/app-update");
                this.u = response.data.update;
                this.shown = !!(this.u && this.u.available && !this.u.dismissed);
                if (!this.u?.waiting) break;
            } catch (e) {
                break; // offline: say nothing
            }
            await new Promise((resolve) => setTimeout(resolve, 20000));
        }
    },
    methods: {
        open(url) {
            window.open(url, "_blank", "noopener");
        },
        async close() {
            this.closed = true;
            if (this.dontShowAgain && this.u?.latest) {
                try {
                    await window.axios.post("/api/v1/app-update/dismiss", { version: this.u.latest });
                } catch (e) { /* shown again next start */ }
            }
        },
    },
};
</script>
