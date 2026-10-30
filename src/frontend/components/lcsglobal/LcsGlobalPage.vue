<template>
    <div class="flex flex-col flex-1 overflow-hidden min-w-full sm:min-w-[500px] bg-gray-50 dark:bg-zinc-950">
        <div class="overflow-y-auto p-3 sm:p-6">
            <div class="max-w-3xl mx-auto space-y-4">

                <!-- hero -->
                <div class="relative overflow-hidden rounded-3xl text-white shadow-[0_24px_60px_rgba(1,62,116,0.28)] bg-[radial-gradient(120%_140%_at_0%_0%,#0a4f92_0%,#013E74_45%,#062b52_100%)]">
                    <div class="absolute inset-0 pointer-events-none bg-[radial-gradient(60%_80%_at_100%_0%,rgba(232,200,106,0.18),transparent_60%)]"></div>
                    <div class="relative flex flex-col sm:flex-row sm:items-center gap-5 p-6 sm:p-8">
                        <img src="/assets/images/lcs-global-logo-on-dark.png" alt="LCS Global" class="h-16 sm:h-20 w-auto self-start"/>
                        <div class="sm:ml-auto sm:text-right">
                            <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full text-sm font-semibold"
                                 :class="pillClass">
                                <span class="w-2 h-2 rounded-full" :class="lg.data?.connected ? 'bg-emerald-400' : 'bg-white/50'"></span>
                                {{ pillText }}
                            </div>
                            <div class="mt-2 text-sm text-blue-100/90 max-w-xs sm:ml-auto">{{ lg.describe() }}</div>
                            <div v-if="lg.state === 'trial'" class="mt-2 h-1.5 w-56 max-w-full sm:ml-auto rounded-full bg-white/15 overflow-hidden">
                                <div class="h-full rounded-full bg-[#E8C86A]" :style="{ width: trialProgress + '%' }"></div>
                            </div>
                        </div>
                    </div>
                    <div class="absolute bottom-0 left-0 right-0 h-[3px] bg-gradient-to-r from-[#1e5aa0] via-[#E8C86A] to-[#062b52]"></div>
                </div>

                <!-- actions for people who have it -->
                <div v-if="lg.state && lg.state !== 'none'" class="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    <button v-if="['active', 'grace', 'expired'].includes(lg.state)" @click="lg.manage()" :disabled="lg.busy" type="button" class="action text-[#013E74] dark:text-zinc-100">
                        <MaterialDesignIcon icon-name="credit-card-outline" class="w-5 h-5"/>Manage plan
                    </button>
                    <button @click="refresh" :disabled="lg.busy" type="button" class="action text-[#013E74] dark:text-zinc-100">
                        <MaterialDesignIcon icon-name="refresh" class="w-5 h-5" :class="{ 'animate-spin': checking }"/>Check again
                    </button>
                    <RouterLink :to="{ name: 'interfaces' }" class="action text-[#013E74] dark:text-zinc-100">
                        <MaterialDesignIcon icon-name="lan" class="w-5 h-5"/>Interfaces
                    </RouterLink>
                    <button v-if="lg.data?.has_interface" @click="lg.remove()" :disabled="lg.busy" type="button" class="action text-red-700 dark:text-red-300">
                        <MaterialDesignIcon icon-name="link-variant-off" class="w-5 h-5"/>Remove
                    </button>
                </div>

                <div class="rounded-3xl bg-white dark:bg-zinc-900 shadow-sm ring-1 ring-black/5 dark:ring-white/10 p-5 sm:p-7">
                    <LcsGlobalPanel :show-status="false"/>
                </div>

                <div class="text-center text-xs text-gray-400 dark:text-zinc-500 pb-4">
                    LCS Global is a service of Liberty Communication Systems, Inc. ·
                    <a href="https://lcs.network" target="_blank" class="underline underline-offset-2">lcs.network</a>
                </div>
            </div>
        </div>
    </div>
</template>

<script>
import MaterialDesignIcon from "../MaterialDesignIcon.vue";
import LcsGlobalPanel from "./LcsGlobalPanel.vue";
import LcsGlobal, { daysLeft } from "../../js/LcsGlobal";

export default {
    name: "LcsGlobalPage",
    components: { MaterialDesignIcon, LcsGlobalPanel },
    data() {
        return { lg: LcsGlobal, checking: false, timer: null };
    },
    computed: {
        trialProgress() {
            return Math.min(100, Math.max(4, (daysLeft(this.lg.status?.trial_ends) / this.lg.trialDays) * 100));
        },
        pillText() {
            if (this.lg.data?.connected) return "Connected";
            return { trial: "Free trial", active: "Active", grace: "Payment needed", trial_ended: "Trial ended", expired: "Ended", none: "Not set up" }[this.lg.state] ?? (this.lg.data?.offline ? "Offline" : "Checking…");
        },
        pillClass() {
            if (this.lg.data?.connected) return "bg-emerald-500/20 text-emerald-100 ring-1 ring-emerald-300/40";
            if (this.lg.state === "grace") return "bg-amber-400/20 text-amber-100 ring-1 ring-amber-300/40";
            return "bg-white/10 text-white ring-1 ring-white/20";
        },
    },
    mounted() {
        this.lg.notice = null;
        this.lg.load({ refresh: true, plans: true });
        // keep the connection light honest while the page is open
        this.timer = setInterval(() => this.lg.load(), 15000);
    },
    beforeUnmount() {
        clearInterval(this.timer);
    },
    methods: {
        async refresh() {
            this.checking = true;
            await this.lg.check();
            this.checking = false;
        },
    },
};
</script>

<style scoped>
.action {
    @apply inline-flex items-center justify-center gap-2 px-3 py-2.5 rounded-2xl text-sm font-semibold
        bg-white ring-1 ring-black/5 shadow-sm hover:shadow hover:bg-gray-50 transition
        dark:bg-zinc-900 dark:ring-white/10 dark:hover:bg-zinc-800 disabled:opacity-60;
}
</style>
