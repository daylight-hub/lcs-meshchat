// LCS Global: shared state and actions for the popup, the LCS Global page and the
// interface screens. The backend (src/backend/lcs_global.py) does the talking to LCS.
import { reactive } from "vue";
import DialogUtils from "./DialogUtils";

const DAY = 86400;

const LcsGlobal = reactive({
    loaded: false,
    busy: false,
    data: null,          // the backend's ui_status()
    notice: null,        // { text, error } shown inside the popup / page
    popup: null,         // null | { mode: "startup" | "offer" | "reminder", reminder? }

    get status() { return this.data?.status ?? null; },
    get state() { return this.status?.state ?? null; },
    get plans() { return this.data?.plans ?? []; },
    get trialDays() { return this.data?.trial_days ?? 7; },
    get hasAccess() { return ["trial", "active", "grace"].includes(this.state); },

    async load({ refresh = false, plans = false } = {}) {
        try {
            const params = [];
            if (refresh) params.push("refresh=1");
            if (plans) params.push("plans=1");
            const response = await window.axios.get("/api/v1/lcs-global/status" + (params.length ? "?" + params.join("&") : ""));
            this.data = response.data.lcs_global;
            this.loaded = true;
        } catch (e) {
            console.log("LCS Global status unavailable", e);
        }
        return this.data;
    },

    async post(path, body = {}) {
        this.busy = true;
        this.notice = null;
        try {
            const response = await window.axios.post("/api/v1/lcs-global/" + path, body);
            this.data = response.data.lcs_global ?? this.data;
            return response.data;
        } catch (e) {
            const data = e?.response?.data ?? {};
            this.data = data.lcs_global ?? this.data;
            this.notice = { text: data.message ?? "Couldn't reach LCS. Check your internet connection and try again.", error: true };
            return null;
        } finally {
            this.busy = false;
        }
    },

    open(url) {
        // the desktop app opens this in the system browser; the web version in a new tab
        window.open(url, "_blank", "noopener");
    },

    async startTrial() {
        const result = await this.post("trial");
        if (result) this.notice = { text: result.message, error: false };
        return !!result;
    },

    async subscribe(plan) {
        const result = await this.post("subscribe", { plan });
        if (result?.url) {
            this.open(result.url);
            this.notice = { text: "Finish paying on lcs.network. LCS Global connects here by itself as soon as payment goes through.", error: false };
            this.watchAfterCheckout();
            return true;
        }
        return false;
    },

    async manage() {
        const result = await this.post("manage");
        if (result?.url) this.open(result.url);
    },

    async linkDevice() {
        const result = await this.post("link-device");
        if (result?.url) {
            this.open(result.url);
            this.notice = { text: result.message, error: false };
            this.watchAfterCheckout();
        }
    },

    async redeem(code) {
        const result = await this.post("redeem", { code });
        if (result) this.notice = { text: result.message, error: false };
        return !!result;
    },

    async check() {
        await this.post("check");
        await this.load({ refresh: true });
    },

    async remove() {
        if (!await DialogUtils.confirm("Remove LCS Global from this computer?\n\nYour trial or plan stays as it is, and you can add it again any time.")) {
            return;
        }
        await this.post("remove");
        await this.load({ refresh: true });
    },

    async dismissStartupPopup(dontShowAgain) {
        if (dontShowAgain) {
            await this.post("prefs", { popup_dismissed: true });
        }
        this.popup = null;
    },

    // After sending someone to checkout, look again every few seconds for a while (the backend
    // is doing the same), so the page flips to "Active" the moment payment goes through.
    watchAfterCheckout() {
        let rounds = 0;
        clearInterval(this._watch);
        this._watch = setInterval(async () => {
            rounds++;
            await this.load({ refresh: true });
            if (this.state === "active" || rounds > 180) {
                clearInterval(this._watch);
                if (this.state === "active") {
                    this.notice = { text: "Payment received. LCS Global is on.", error: false };
                }
            }
        }, 10000);
    },

    // ------------------------------------------------------------------ wording

    describe() {
        const s = this.status;
        if (!s) return this.data?.offline ? "Can't reach LCS right now. It keeps trying by itself." : "Checking…";
        switch (s.state) {
            case "none":
                return s.trial_available ? `Not started. Try it free for ${this.trialDays} days.` : "Not subscribed. The free trial was already used on this computer.";
            case "trial":
                return `Free trial: ${daysLeft(s.trial_ends)} day(s) left, until ${formatDate(s.trial_ends)}.`;
            case "trial_ended":
                return "Your free trial has ended.";
            case "active": {
                if (s.unlimited) return `Active${s.plan ? " (" + s.plan + ")" : ""}. No time limit.`;
                const plan = s.plan ? ((s.lines ?? 1) > 1 && s.line ? `${s.plan}, line ${s.line}` : s.plan) : null;
                const prefix = plan ? `Active (${plan}).` : "Active.";
                if (s.cancelled) return `${prefix} Cancelled: no more charges. Service continues until ${formatDate(s.paid_through)}, then ends.`;
                if (s.auto_renew) return `${prefix} Renews automatically on ${formatDate(s.paid_through)}.`;
                return `${prefix} Paid through ${formatDate(s.paid_through)}.`;
            }
            case "grace":
                return `Payment needed: LCS Global stays on until ${formatDate(s.grace_ends)}, then stops.`;
            case "expired":
                return "Your subscription has ended.";
            default:
                return s.state;
        }
    },

    // One reminder at a time, at most once a day each (twice a day while payment is due).
    reminder() {
        const s = this.status;
        if (!s || !this.data?.has_interface) return null;
        if (s.state === "trial" && daysLeft(s.trial_ends) <= 2) {
            return { id: "trial_ending", title: "Free trial ends soon", every: DAY, action: "Subscribe", account: false,
                body: `Your LCS Global trial ends ${formatDate(s.trial_ends)}. Subscribe to stay connected; family plans are available.` };
        }
        if (s.state === "trial_ended") {
            return { id: "trial_ended", title: "Your free trial has ended", every: DAY, action: "Subscribe", account: false,
                body: "LCS Global is off for this computer. Local Wi-Fi, LoRa and your other interfaces still work. Subscribe to reconnect over the internet." };
        }
        if (s.state === "grace") {
            return { id: "grace", title: "Renew your LCS Global", every: DAY / 2, action: "Renew", account: true,
                body: s.auto_renew === false
                    ? `Your paid period ended. LCS Global stays on until ${formatDate(s.grace_ends)}. Renew on lcs.network to keep it.`
                    : `Your renewal payment didn't go through. LCS Global stays on until ${formatDate(s.grace_ends)}. Update your card or renew on lcs.network.` };
        }
        if (s.state === "expired") {
            return { id: "expired", title: "Your subscription has ended", every: DAY, action: "Renew", account: true,
                body: "LCS Global is off for this computer. Renew on lcs.network to reconnect." };
        }
        return null;
    },

    reminderDue(reminder) {
        try {
            const key = `lcs_global_reminder:${this.data?.lxmf_address}:${reminder.id}`;
            const last = Number(localStorage.getItem(key) || 0);
            return Date.now() / 1000 - last >= reminder.every;
        } catch (e) {
            return true;
        }
    },

    reminderShown(reminder) {
        try {
            localStorage.setItem(`lcs_global_reminder:${this.data?.lxmf_address}:${reminder.id}`, String(Math.floor(Date.now() / 1000)));
        } catch (e) { /* private window: show it again next time */ }
    },
});

export function formatDate(epochSeconds) {
    if (!epochSeconds) return "";
    return new Date(epochSeconds * 1000).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function daysLeft(epochSeconds) {
    if (!epochSeconds) return 0;
    return Math.max(0, Math.floor((epochSeconds * 1000 - Date.now()) / (DAY * 1000)));
}

// Plans as the website shows them: a Monthly / Yearly switch and Just me / Family cards.
export function planGroups(plans) {
    const groups = {};
    for (const p of plans) {
        const period = /monthly$/.test(p.plan) || p.plan === "monthly" ? "month" : "year";
        const lines = p.lines || 1;
        (groups[lines] ??= {})[period] = p;
    }
    return Object.keys(groups).map(Number).sort((a, b) => a - b).map((lines) => ({
        lines,
        title: lines === 1 ? "Just me" : `Family of ${lines}`,
        month: groups[lines].month ?? null,
        year: groups[lines].year ?? null,
    }));
}

export const TERMS = "Cancel any time on lcs.network. Billing stops when you cancel and your service continues until the end of the period you already paid for (the rest of the month on monthly plans, the rest of the year on yearly plans), then ends. No refunds.";

export default LcsGlobal;
