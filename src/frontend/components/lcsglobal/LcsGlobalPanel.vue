<template>
    <div class="space-y-5">

        <!-- where you stand -->
        <div v-if="showStatus && status && state !== 'none'" class="flex items-start gap-3 rounded-xl px-4 py-3 border"
             :class="statusTone">
            <span class="mt-1.5 w-2.5 h-2.5 rounded-full shrink-0" :class="statusDot"></span>
            <div class="min-w-0">
                <div class="font-semibold text-sm">{{ statusTitle }}</div>
                <div class="text-sm opacity-90">{{ lg.describe() }}</div>
                <div v-if="state === 'trial'" class="mt-2 h-1.5 w-56 max-w-full rounded-full bg-black/10 dark:bg-white/10 overflow-hidden">
                    <div class="h-full rounded-full bg-[#E8C86A]" :style="{ width: trialProgress + '%' }"></div>
                </div>
            </div>
            <button v-if="['active', 'grace', 'expired'].includes(state)" @click="lg.manage()" :disabled="lg.busy" type="button"
                    class="ml-auto shrink-0 text-sm font-semibold px-3 py-1.5 rounded-lg bg-white/80 hover:bg-white text-[#013E74] border border-[#013E74]/20 dark:bg-zinc-800 dark:text-zinc-100 dark:border-zinc-600 dark:hover:bg-zinc-700">
                {{ state === 'active' ? 'Manage plan' : 'Renew' }}
            </button>
        </div>

        <!-- messages: at the top, so they're seen without scrolling -->
        <div v-if="lg.notice" class="flex items-center gap-3 rounded-xl px-4 py-3 text-sm"
             :class="lg.notice.error ? 'bg-red-50 text-red-800 border border-red-200 dark:bg-red-950/40 dark:text-red-200 dark:border-red-900' : 'bg-emerald-50 text-emerald-900 border border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:border-emerald-900'">
            <MaterialDesignIcon :icon-name="lg.notice.error ? 'alert-circle-outline' : 'check-circle-outline'" class="w-5 h-5 shrink-0"/>
            <div class="flex-1">{{ lg.notice.text }}</div>
            <button v-if="lg.notice.error" @click="lg.check()" :disabled="lg.busy" type="button"
                    class="shrink-0 text-sm font-semibold px-3 py-1.5 rounded-lg bg-white/80 hover:bg-white border border-red-200 dark:bg-zinc-800 dark:border-red-900">
                Try again
            </button>
        </div>

        <!-- free trial -->
        <div v-if="trialAvailable && !compact" class="rounded-2xl p-4 bg-gradient-to-br from-[#fff8e6] to-[#fdf1cf] border border-[#E8C86A]/60 dark:from-[#2a2410] dark:to-[#211c0c] dark:border-[#E8C86A]/30">
            <div class="flex flex-col sm:flex-row sm:items-center gap-3">
                <div class="flex-1">
                    <div class="font-bold text-gray-900 dark:text-white">Try it free for {{ lg.trialDays }} days</div>
                    <div class="text-sm text-gray-700 dark:text-zinc-300">Full access with unlimited data. No card, no account, nothing to type in.</div>
                </div>
                <button @click="startTrial" :disabled="lg.busy" type="button"
                        class="shrink-0 inline-flex items-center justify-center gap-2 px-5 py-3 rounded-xl font-bold text-[#062b52] bg-[#E8C86A] hover:bg-[#f0d47f] shadow-sm hover:shadow transition active:scale-[0.98] disabled:opacity-60">
                    <MaterialDesignIcon icon-name="rocket-launch-outline" class="w-5 h-5"/>
                    Start {{ lg.trialDays }}-day free trial
                </button>
            </div>
        </div>

        <!-- what it is -->
        <p v-if="!compact || !hasAccess" class="text-[15px] leading-relaxed text-gray-700 dark:text-zinc-300">
            Local Wi-Fi and LoRa reach the people near you. <b class="text-gray-900 dark:text-white">LCS Global</b> connects
            LCS MeshChat to the wider Liberty network over the internet, so your messages and calls reach family,
            friends and Liberty Chat users wherever they are.
        </p>

        <div v-if="!compact || !hasAccess" class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div v-for="f in features" :key="f.title" class="flex gap-3 rounded-xl p-3 bg-gray-50 border border-gray-100 dark:bg-zinc-800/60 dark:border-zinc-700/60">
                <div class="shrink-0 w-9 h-9 rounded-lg flex items-center justify-center bg-[#013E74] text-[#E8C86A]">
                    <MaterialDesignIcon :icon-name="f.icon" class="w-5 h-5"/>
                </div>
                <div class="min-w-0">
                    <div class="font-semibold text-sm text-gray-900 dark:text-white">{{ f.title }}</div>
                    <div class="text-xs leading-relaxed text-gray-600 dark:text-zinc-400">{{ f.text }}</div>
                </div>
            </div>
        </div>

        <details v-if="!compact || !hasAccess" class="group rounded-xl border border-gray-200 dark:border-zinc-700 px-4 py-2.5">
            <summary class="cursor-pointer select-none text-sm font-semibold text-[#013E74] dark:text-[#8fb8e8] list-none flex items-center gap-2">
                <MaterialDesignIcon icon-name="shield-key-outline" class="w-4 h-4"/>
                How the encryption works
                <MaterialDesignIcon icon-name="chevron-down" class="w-4 h-4 ml-auto transition-transform group-open:rotate-180"/>
            </summary>
            <div class="pt-2 space-y-2 text-xs leading-relaxed text-gray-600 dark:text-zinc-400">
                <p>LCS MeshChat runs on Reticulum. Every message, call and file is encrypted on this computer for the
                    one person it's going to, before it leaves: X25519 elliptic-curve key exchange, Ed25519 signatures,
                    and AES-256 encryption (CBC mode) authenticated with HMAC-SHA256.</p>
                <p>Calls and file transfers run over Reticulum links, which make fresh keys for every session, so a key
                    taken later can't unlock what was sent before (forward secrecy). Your private key never leaves this
                    computer.</p>
                <p>LCS Global only carries the encrypted packets between you and the rest of the network. It can't read
                    them, and it doesn't need your name, phone number or email.</p>
            </div>
        </details>

        <!-- plans -->
        <div v-if="showPlans" ref="plans" class="space-y-3">
            <div class="flex items-center justify-between gap-3">
                <div class="font-bold text-gray-900 dark:text-white">{{ state === 'trial' || trialAvailable ? 'Then choose a plan' : 'Choose a plan' }}</div>
                <div class="inline-flex p-1 rounded-xl bg-gray-100 dark:bg-zinc-800">
                    <button v-for="p in ['month', 'year']" :key="p" @click="period = p" type="button"
                            class="px-3 py-1.5 rounded-lg text-sm font-semibold transition"
                            :class="period === p ? 'bg-white text-[#013E74] shadow-sm dark:bg-zinc-700 dark:text-white' : 'text-gray-500 dark:text-zinc-400'">
                        {{ p === 'month' ? 'Monthly' : 'Yearly' }}
                        <span v-if="p === 'year' && saving > 0" class="ml-1 text-[11px] font-bold text-[#a07a10] dark:text-[#E8C86A]">save {{ saving }}%</span>
                    </button>
                </div>
            </div>
            <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <button v-for="g in groups" :key="g.lines" type="button" @click="chosenLines = g.lines" :disabled="!g[period]"
                        class="relative text-left rounded-2xl p-4 border-2 transition disabled:opacity-40"
                        :class="chosenLines === g.lines
                            ? 'border-[#013E74] bg-[#013E74]/[0.04] shadow-[0_0_0_3px_rgba(232,200,106,0.45)] dark:border-[#8fb8e8] dark:bg-white/5'
                            : 'border-gray-200 hover:border-gray-300 dark:border-zinc-700 dark:hover:border-zinc-500'">
                    <span v-if="chosenLines === g.lines" class="absolute top-3 right-3 w-5 h-5 rounded-full bg-[#013E74] text-white flex items-center justify-center dark:bg-[#8fb8e8] dark:text-zinc-900">
                        <MaterialDesignIcon icon-name="check" class="w-3.5 h-3.5"/>
                    </span>
                    <div class="font-semibold text-gray-900 dark:text-white">{{ g.title }}</div>
                    <div class="mt-1 text-2xl font-extrabold tracking-tight text-[#013E74] dark:text-[#8fb8e8]">
                        {{ priceOf(g[period]) }}<span class="text-sm font-medium text-gray-500 dark:text-zinc-400">/{{ period }}</span>
                    </div>
                    <div class="text-xs text-gray-500 dark:text-zinc-400 min-h-[1rem]">{{ subOf(g, period) }}</div>
                    <div class="mt-2 flex items-center gap-1 text-xs font-semibold text-emerald-700 dark:text-emerald-400">
                        <MaterialDesignIcon icon-name="infinity" class="w-4 h-4"/> Unlimited data
                    </div>
                </button>
            </div>
            <button @click="subscribe" :disabled="lg.busy || !chosenPlan" type="button"
                    class="w-full inline-flex items-center justify-center gap-2 px-5 py-3 rounded-xl font-bold text-white bg-gradient-to-br from-[#1e5aa0] to-[#013E74] hover:from-[#2f6fc0] hover:to-[#0a4f92] shadow-md transition active:scale-[0.99] disabled:opacity-60">
                <MaterialDesignIcon icon-name="lock-outline" class="w-5 h-5"/>
                Continue to secure checkout
            </button>
            <div class="text-xs text-center text-gray-500 dark:text-zinc-400">
                Every plan includes unlimited data. Pay on lcs.network (cards processed by Square); LCS Global
                turns on here by itself as soon as you've paid. No codes to enter.
            </div>
        </div>

        <!-- already subscribe -->
        <div class="rounded-xl border border-gray-200 dark:border-zinc-700">
            <button @click="showAlready = !showAlready" type="button" class="w-full flex items-center gap-2 px-4 py-2.5 text-sm font-semibold text-gray-700 dark:text-zinc-200">
                <MaterialDesignIcon icon-name="key-outline" class="w-4 h-4"/>
                I already subscribe / have a code
                <MaterialDesignIcon icon-name="chevron-down" class="w-4 h-4 ml-auto transition-transform" :class="{ 'rotate-180': showAlready }"/>
            </button>
            <div v-if="showAlready" class="px-4 pb-4 space-y-3 text-sm text-gray-600 dark:text-zinc-400">
                <p>A family member's line or a gift: enter the code. It starts when you do.</p>
                <div class="flex gap-2">
                    <input v-model="code" @input="code = code.toUpperCase()" type="text" placeholder="XXXX-XXXX-XXXX" spellcheck="false"
                           class="flex-1 font-mono tracking-wider rounded-lg border border-gray-300 bg-white px-3 py-2 text-gray-900 dark:bg-zinc-900 dark:border-zinc-600 dark:text-white"/>
                    <button @click="redeem" :disabled="lg.busy || codeLength < 12" type="button"
                            class="px-4 py-2 rounded-lg font-semibold text-white bg-[#013E74] hover:bg-[#0a4f92] disabled:opacity-50">Redeem</button>
                </div>
                <p>Bought it from Liberty Chat on another device, or on lcs.network with your LXMF address? Those
                    connect by themselves. To move a plan to this computer, sign in to My Account on lcs.network:</p>
                <button @click="lg.linkDevice()" :disabled="lg.busy" type="button" class="font-semibold text-[#013E74] dark:text-[#8fb8e8] underline underline-offset-2">
                    Link this computer on lcs.network
                </button>
                <div v-if="lg.data?.lxmf_address" class="pt-1">
                    <div class="text-xs uppercase tracking-wide text-gray-400">Your LXMF address</div>
                    <div class="flex items-center gap-2">
                        <code class="text-xs text-gray-800 dark:text-zinc-200 break-all">{{ lg.data.lxmf_address }}</code>
                        <button @click="copyAddress" type="button" class="text-xs font-semibold text-[#013E74] dark:text-[#8fb8e8]">{{ copied ? 'Copied' : 'Copy' }}</button>
                    </div>
                </div>
            </div>
        </div>

        <div v-if="lg.data?.message" class="text-xs text-amber-700 dark:text-amber-300">{{ lg.data.message }}</div>

        <p class="text-[11px] leading-relaxed text-gray-400 dark:text-zinc-500">{{ terms }}</p>
    </div>
</template>

<script>
import MaterialDesignIcon from "../MaterialDesignIcon.vue";
import LcsGlobal, { planGroups, TERMS, daysLeft } from "../../js/LcsGlobal";

export default {
    name: "LcsGlobalPanel",
    components: { MaterialDesignIcon },
    props: {
        // the LCS Global page shows the full information; the popup hides it once you're connected
        compact: { type: Boolean, default: false },
        // the LCS Global page shows where you stand in its own header
        showStatus: { type: Boolean, default: true },
    },
    data() {
        return {
            lg: LcsGlobal,
            period: "year",
            chosenLines: 1,
            showAlready: false,
            code: "",
            copied: false,
            terms: TERMS,
            features: [
                { icon: "shield-lock-outline", title: "End-to-end encrypted", text: "Messages, voice calls, pictures and files. Only the person you're talking to can read them." },
                { icon: "incognito", title: "No phone number or email", text: "Your identity is a key on this computer. No account is needed to chat." },
                { icon: "earth", title: "Works from anywhere", text: "Over Wi-Fi, Ethernet or mobile data. Unlimited data on every plan." },
                { icon: "account-group-outline", title: "One Liberty network", text: "Reach LCS MeshChat and Liberty Chat users near and far." },
            ],
        };
    },
    computed: {
        status() { return this.lg.status; },
        state() { return this.lg.state; },
        hasAccess() { return this.lg.hasAccess; },
        // shown until the server says otherwise, so it's there even before the first status check comes back
        trialAvailable() { return (this.state === "none" || this.state === null) && this.status?.trial_available !== false; },
        showPlans() { return this.state !== "active"; },
        groups() { return planGroups(this.lg.plans); },
        chosenPlan() { return this.groups.find((g) => g.lines === this.chosenLines)?.[this.period]?.plan ?? null; },
        codeLength() { return this.code.replace(/[^A-Z0-9]/g, "").length; },
        saving() {
            const one = this.groups.find((g) => g.lines === 1);
            const m = this.cents(one?.month?.label), y = this.cents(one?.year?.label);
            return m && y ? Math.round((1 - y / (m * 12)) * 100) : 0;
        },
        trialProgress() {
            const left = daysLeft(this.status?.trial_ends);
            return Math.min(100, Math.max(4, (left / this.lg.trialDays) * 100));
        },
        statusTitle() {
            return { trial: "Free trial", trial_ended: "Trial ended", active: "Active", grace: "Payment needed", expired: "Ended" }[this.state] ?? "LCS Global";
        },
        statusTone() {
            if (this.state === "active" || this.state === "trial") return "bg-emerald-50 border-emerald-200 text-emerald-900 dark:bg-emerald-950/30 dark:border-emerald-900 dark:text-emerald-100";
            if (this.state === "grace") return "bg-amber-50 border-amber-200 text-amber-900 dark:bg-amber-950/30 dark:border-amber-900 dark:text-amber-100";
            return "bg-gray-50 border-gray-200 text-gray-800 dark:bg-zinc-800/60 dark:border-zinc-700 dark:text-zinc-100";
        },
        statusDot() {
            if (this.state === "active" || this.state === "trial") return this.lg.data?.connected ? "bg-emerald-500 shadow-[0_0_0_4px_rgba(16,185,129,0.2)]" : "bg-emerald-400";
            if (this.state === "grace") return "bg-amber-500";
            return "bg-gray-400";
        },
    },
    methods: {
        cents(label) {
            const m = /([0-9]+(?:\.[0-9]+)?)/.exec(label ?? "");
            return m ? Math.round(parseFloat(m[1]) * 100) : 0;
        },
        priceOf(plan) {
            return plan ? (/^[^0-9]*[0-9.,]+/.exec(plan.label)?.[0] ?? plan.label) : "—";
        },
        subOf(group, period) {
            const p = group[period];
            if (!p) return "";
            if (p.per_line) return p.per_line.replace(/ per line$/, " per person");
            if (period === "year") {
                const c = this.cents(p.label);
                return c ? `Just $${(c / 1200).toFixed(2)} a month` : "";
            }
            return "";
        },
        async startTrial() {
            await this.lg.startTrial();
            this.$emit("done");
        },
        async subscribe() {
            if (this.chosenPlan) await this.lg.subscribe(this.chosenPlan);
        },
        async redeem() {
            if (await this.lg.redeem(this.code)) {
                this.code = "";
                this.$emit("done");
            }
        },
        async copyAddress() {
            const text = this.lg.data.lxmf_address;
            try {
                await navigator.clipboard.writeText(text);
            } catch (e) {
                // plain-http web builds have no clipboard API: fall back to a hidden text box
                const box = document.createElement("textarea");
                box.value = text;
                box.style.position = "fixed";
                box.style.opacity = "0";
                document.body.appendChild(box);
                box.select();
                try { document.execCommand("copy"); } catch (err) { /* the address is selectable anyway */ }
                document.body.removeChild(box);
            }
            this.copied = true;
            setTimeout(() => { this.copied = false; }, 1500);
        },
        scrollToPlans() {
            this.$refs.plans?.scrollIntoView({ behavior: "smooth", block: "center" });
        },
    },
    emits: ["done"],
};
</script>
