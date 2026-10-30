<template>
    <Transition enter-active-class="transition duration-200 ease-out" enter-from-class="opacity-0" leave-active-class="transition duration-150 ease-in" leave-to-class="opacity-0">
        <div v-if="lg.popup" class="fixed inset-0 z-[60] flex items-center justify-center p-3 sm:p-6 bg-[#031a33]/60 backdrop-blur-sm" @click.self="close">
            <div class="relative w-full max-w-2xl max-h-full flex flex-col rounded-3xl overflow-hidden bg-white dark:bg-zinc-900 shadow-[0_40px_100px_rgba(3,26,51,0.55)] ring-1 ring-black/5 dark:ring-white/10"
                 role="dialog" aria-modal="true" aria-label="LCS Global">

                <!-- brand header -->
                <div class="relative shrink-0 px-6 pt-6 pb-5 text-white bg-[radial-gradient(120%_140%_at_0%_0%,#0a4f92_0%,#013E74_45%,#062b52_100%)]">
                    <div class="absolute inset-0 pointer-events-none bg-[radial-gradient(60%_80%_at_100%_0%,rgba(232,200,106,0.18),transparent_60%)]"></div>
                    <button @click="close" type="button" aria-label="Close"
                            class="absolute top-4 right-4 w-9 h-9 rounded-full flex items-center justify-center bg-white/10 hover:bg-white/20 text-white transition">
                        <MaterialDesignIcon icon-name="close" class="w-5 h-5"/>
                    </button>
                    <img src="/assets/images/lcs-global-logo-on-dark.png" alt="LCS Global" class="relative h-14 sm:h-16 w-auto"/>
                    <div class="relative mt-3 text-lg sm:text-xl font-semibold tracking-tight">{{ headline }}</div>
                    <div class="relative text-sm text-blue-100/90">{{ subline }}</div>
                    <button v-if="trialAvailable" @click="startTrial" :disabled="lg.busy" type="button"
                            class="relative mt-4 inline-flex items-center gap-2 px-5 py-2.5 rounded-xl font-bold text-[#062b52] bg-[#E8C86A] hover:bg-[#f0d47f] shadow-sm hover:shadow transition active:scale-[0.98] disabled:opacity-60">
                        <MaterialDesignIcon icon-name="rocket-launch-outline" class="w-5 h-5"/>
                        Start {{ lg.trialDays }}-day free trial
                        <span class="font-medium text-[#062b52]/70">· no card needed</span>
                    </button>
                    <div class="absolute bottom-0 left-0 right-0 h-[3px] bg-gradient-to-r from-[#1e5aa0] via-[#E8C86A] to-[#062b52]"></div>
                </div>

                <!-- body -->
                <div class="flex-1 overflow-y-auto px-6 py-5">
    <!-- reminder -->
                    <div v-if="reminder" class="mb-5">
                        <div class="flex items-start gap-3 rounded-2xl p-4 border"
                             :class="reminder.account ? 'bg-amber-50 border-amber-200 dark:bg-amber-950/30 dark:border-amber-900' : 'bg-[#fff8e6] border-[#E8C86A]/60 dark:bg-[#2a2410] dark:border-[#E8C86A]/30'">
                            <MaterialDesignIcon :icon-name="reminder.account ? 'credit-card-clock-outline' : 'timer-sand'" class="w-6 h-6 shrink-0 text-[#a07a10] dark:text-[#E8C86A]"/>
                            <div class="flex-1 text-sm text-gray-800 dark:text-zinc-100">{{ reminder.body }}</div>
                            <button v-if="reminder.account" @click="lg.manage()" type="button"
                                    class="shrink-0 px-4 py-2 rounded-xl font-semibold text-white bg-[#013E74] hover:bg-[#0a4f92]">{{ reminder.action }}</button>
                        </div>
                    </div>
                    <LcsGlobalPanel ref="panel" :compact="true" @done="onDone"/>
                </div>

                <!-- footer -->
                <div class="shrink-0 flex items-center gap-3 px-6 py-3.5 border-t border-gray-100 bg-gray-50/80 dark:bg-zinc-800/60 dark:border-zinc-800">
                    <label v-if="lg.popup.mode === 'startup'" class="flex items-center gap-2 text-sm text-gray-600 dark:text-zinc-300 cursor-pointer select-none">
                        <input v-model="dontShowAgain" type="checkbox" class="rounded border-gray-300 text-[#013E74] focus:ring-[#013E74]"/>
                        Don't show this message again
                    </label>
                    <RouterLink v-else :to="{ name: 'lcs-global' }" @click="close" class="text-sm font-semibold text-[#013E74] dark:text-[#8fb8e8]">
                        Open LCS Global settings
                    </RouterLink>
                    <button @click="close" type="button"
                            class="ml-auto px-5 py-2 rounded-xl text-sm font-semibold text-gray-700 bg-white border border-gray-200 hover:bg-gray-100 dark:bg-zinc-800 dark:text-zinc-100 dark:border-zinc-600 dark:hover:bg-zinc-700">
                        {{ lg.hasAccess ? 'Done' : 'Not now' }}
                    </button>
                </div>
            </div>
        </div>
    </Transition>
</template>

<script>
import MaterialDesignIcon from "../MaterialDesignIcon.vue";
import LcsGlobalPanel from "./LcsGlobalPanel.vue";
import LcsGlobal from "../../js/LcsGlobal";

export default {
    name: "LcsGlobalModal",
    components: { MaterialDesignIcon, LcsGlobalPanel },
    data() {
        return { lg: LcsGlobal, dontShowAgain: false };
    },
    computed: {
        trialAvailable() {
            return !this.reminder && (this.lg.state === "none" || this.lg.state === null) && this.lg.status?.trial_available !== false;
        },
        reminder() { return this.lg.popup?.mode === "reminder" ? this.lg.popup.reminder : null; },
        headline() {
            if (this.reminder) return this.reminder.title;
            if (this.lg.state === "trial" || this.lg.state === "active") return "You're connected to the Liberty network";
            return "The Liberty network, from anywhere";
        },
        subline() {
            if (this.reminder) return "LCS Global for LCS MeshChat";
            if (this.lg.state === "active") return "Encrypted messages and calls with anyone on the Liberty network, from anywhere.";
            if (this.lg.state === "trial") return `Your free trial is on. Plans start at ${this.fromPrice}.`;
            return `Encrypted messages and calls over the internet. Free for ${this.lg.trialDays} days, then from ${this.fromPrice}.`;
        },
        fromPrice() {
            const p = this.lg.plans.find((x) => x.plan === "monthly") ?? this.lg.plans.find((x) => (x.lines ?? 1) === 1);
            return p?.label ?? "$5/month";
        },
    },
    watch: {
        "lg.popup"(value) {
            this.dontShowAgain = false;
            if (value?.mode === "reminder" && !value.reminder.account) {
                this.$nextTick(() => this.$refs.panel?.scrollToPlans());
            }
        },
    },
    methods: {
        close() {
            if (this.lg.popup?.mode === "startup") {
                this.lg.dismissStartupPopup(this.dontShowAgain);
            } else {
                this.lg.popup = null;
            }
            this.lg.notice = null;
        },
        async startTrial() {
            if (await this.lg.startTrial()) this.onDone();
        },
        onDone() {
            // trial started or code redeemed: show the result in place for a moment, then close
            setTimeout(() => { if (this.lg.hasAccess) this.close(); }, 2200);
        },
    },
};
</script>
