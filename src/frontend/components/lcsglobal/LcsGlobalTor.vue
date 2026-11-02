<template>
    <div class="rounded-3xl bg-white dark:bg-zinc-900 shadow-sm ring-1 ring-black/5 dark:ring-white/10 p-5 sm:p-6">
        <div class="flex items-start gap-4">
            <div class="shrink-0 w-11 h-11 rounded-2xl flex items-center justify-center"
                 :class="on ? 'bg-[#4b2a73] text-[#e3cfff]' : 'bg-gray-100 text-gray-500 dark:bg-zinc-800 dark:text-zinc-400'">
                <MaterialDesignIcon icon-name="incognito" class="w-6 h-6"/>
            </div>
            <div class="flex-1 min-w-0">
                <div class="flex items-center gap-3">
                    <div class="font-bold text-gray-900 dark:text-white">Connect through Tor</div>
                    <button type="button" role="switch" :aria-checked="on" @click="toggle" :disabled="saving"
                            class="ml-auto relative inline-flex h-7 w-12 shrink-0 items-center rounded-full transition disabled:opacity-60"
                            :class="on ? 'bg-[#6d3fb0]' : 'bg-gray-300 dark:bg-zinc-600'">
                        <span class="inline-block h-5 w-5 rounded-full bg-white shadow transition"
                              :class="on ? 'translate-x-6' : 'translate-x-1'"></span>
                    </button>
                </div>
                <p class="mt-1 text-sm text-gray-600 dark:text-zinc-400">
                    Sends LCS Global through the Tor network to the gateway's private onion address, so neither LCS
                    nor anyone watching your connection sees this computer's internet address. Messages work as
                    usual; voice calls get a noticeable delay (often ½ to 1 second).
                </p>

                <!-- status while on -->
                <div v-if="on" class="mt-3 rounded-2xl px-4 py-3 text-sm" :class="tone">
                    <div class="flex items-center gap-2 font-semibold">
                        <MaterialDesignIcon :icon-name="icon" class="w-5 h-5 shrink-0" :class="{ 'animate-spin': tor.state === 'starting' }"/>
                        <span>{{ headline }}</span>
                    </div>
                    <div v-if="tor.state === 'starting'" class="mt-2 h-1.5 rounded-full bg-black/10 dark:bg-white/10 overflow-hidden">
                        <div class="h-full rounded-full bg-[#6d3fb0] transition-all duration-500" :style="{ width: Math.max(4, tor.progress) + '%' }"></div>
                    </div>
                    <div v-if="tor.message && tor.state !== 'ready'" class="mt-1 opacity-90">{{ tor.message }}</div>
                    <div v-if="tor.state === 'ready'" class="mt-1 opacity-80">{{ sourceText }}</div>
                </div>
                <p v-else class="mt-2 text-xs text-gray-400 dark:text-zinc-500">Off: Tor doesn't run, and LCS Global connects directly.</p>
            </div>
        </div>
    </div>
</template>

<script>
import MaterialDesignIcon from "../MaterialDesignIcon.vue";
import LcsGlobal from "../../js/LcsGlobal";

export default {
    name: "LcsGlobalTor",
    components: { MaterialDesignIcon },
    data() {
        return { lg: LcsGlobal, saving: false, timer: null };
    },
    computed: {
        tor() { return this.lg.data?.tor ?? { enabled: false, state: "off", progress: 0, message: "" }; },
        on() { return !!this.tor.enabled; },
        headline() {
            switch (this.tor.state) {
                case "starting": return `Connecting to the Tor network… ${this.tor.progress}%`;
                case "ready": return this.lg.data?.connected ? "LCS Global is connected through Tor" : "Tor is ready. LCS Global is connecting…";
                case "unavailable": return "Tor isn't available";
                case "error": return "Tor couldn't start";
                default: return "Starting Tor…";
            }
        },
        icon() {
            return { starting: "loading", ready: "check-circle-outline", unavailable: "alert-circle-outline", error: "alert-circle-outline" }[this.tor.state] ?? "loading";
        },
        tone() {
            if (this.tor.state === "ready") return "bg-emerald-50 text-emerald-900 ring-1 ring-emerald-200 dark:bg-emerald-950/30 dark:text-emerald-100 dark:ring-emerald-900";
            if (["unavailable", "error"].includes(this.tor.state)) return "bg-red-50 text-red-800 ring-1 ring-red-200 dark:bg-red-950/40 dark:text-red-200 dark:ring-red-900";
            return "bg-[#f4effb] text-[#3d2263] ring-1 ring-[#d9c8f2] dark:bg-[#21172e] dark:text-[#e3cfff] dark:ring-[#3d2a5c]";
        },
        sourceText() {
            const v = this.tor.version ? ` ${this.tor.version}` : "";
            return {
                "built-in": `Using MeshChat's built-in Tor${v}.`,
                "built-in-image": `Using the Tor built into this MeshChat image${v}.`,
                "system": `Using the Tor program on this computer${v}.`,
                "tor-browser": "Using the Tor Browser that's open on this computer. Keep it open.",
                "tor-service": "Using the Tor service on this computer.",
            }[this.tor.source] ?? "";
        },
    },
    watch: {
        "tor.state": { handler() { this.schedule(); }, immediate: true },
    },
    beforeUnmount() {
        clearTimeout(this.timer);
    },
    methods: {
        async toggle() {
            this.saving = true;
            await this.lg.post("tor", { enabled: !this.on });
            await this.lg.load();
            this.saving = false;
            this.schedule();
        },
        // poll quickly while Tor starts, so the progress bar moves
        schedule() {
            clearTimeout(this.timer);
            if (this.on && (this.tor.state === "starting" || (this.tor.state === "ready" && !this.lg.data?.connected))) {
                this.timer = setTimeout(async () => { await this.lg.load(); this.schedule(); }, 2000);
            }
        },
    },
};
</script>
