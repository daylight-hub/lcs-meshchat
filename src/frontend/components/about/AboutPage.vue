<template>
    <div class="flex flex-col flex-1 overflow-hidden min-w-full sm:min-w-[500px] dark:bg-zinc-950">
        <div class="overflow-y-auto space-y-2 p-2">

            <!-- app info -->
            <div v-if="appInfo" class="bg-white dark:bg-zinc-900 rounded shadow">
                <div class="flex border-b border-gray-300 dark:border-zinc-700 text-gray-700 dark:text-zinc-200 p-2 font-semibold">App Info</div>
                <div class="divide-y divide-gray-200 dark:divide-zinc-800 text-gray-900 dark:text-zinc-200">

                    <!-- version, and the update check (GitHub first, then the LCS mirror) -->
                    <div class="p-1">
                        <div class="flex">
                            <div class="mr-auto">
                                <div>Versions</div>
                                <div class="text-sm text-gray-700 dark:text-zinc-400">
                                    LCS MeshChat v{{ appInfo.version }} • RNS v{{ appInfo.rns_version }} • LXMF v{{ appInfo.lxmf_version }} • LXST v{{ appInfo.lxst_version }} • Python v{{ appInfo.python_version }}
                                </div>
                            </div>
                            <div class="mx-2 my-auto shrink-0">
                                <button @click="checkForUpdates" :disabled="updateChecking"
                                    type="button"
                                    class="my-auto inline-flex items-center gap-x-1 rounded-md bg-gray-500 dark:bg-zinc-700 px-2 py-1 text-sm font-semibold text-white shadow-sm hover:bg-gray-400 dark:hover:bg-zinc-600 disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-500 dark:focus-visible:outline-zinc-600">
                                    <svg v-if="updateChecking" class="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="3" stroke-opacity="0.3"/><path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" stroke-width="3" stroke-linecap="round"/></svg>
                                    {{ updateChecking ? "Checking…" : "Check for Updates" }}
                                </button>
                            </div>
                        </div>

                        <!-- result of the check -->
                        <div v-if="updateWaiting" class="mt-1 text-sm text-gray-700 dark:text-zinc-400">Waiting for Tor to connect…</div>
                        <div v-else-if="update && update.available && update.download" class="mt-2 flex flex-wrap items-center gap-2">
                            <span class="text-sm font-semibold text-gray-900 dark:text-zinc-100">
                                Update available: v{{ update.latest }}
                                <span class="font-normal text-gray-600 dark:text-zinc-400">from {{ update.download.source === 'GitHub' ? 'GitHub' : 'the LCS mirror' }}</span>
                            </span>
                            <button v-if="update.download.url" @click="openLink(update.download.url)" type="button"
                                class="inline-flex items-center gap-x-1 rounded-md bg-[#013E74] hover:bg-[#0a4f92] px-2 py-1 text-sm font-semibold text-white shadow-sm">
                                Download update
                            </button>
                            <span v-else-if="update.kind === 'docker'" class="text-sm text-gray-700 dark:text-zinc-400">
                                Run <code class="px-1 rounded bg-gray-100 dark:bg-zinc-800">docker compose pull</code> then <code class="px-1 rounded bg-gray-100 dark:bg-zinc-800">docker compose up -d</code>
                            </span>
                            <button @click="openLink(update.download.page)" type="button"
                                class="text-sm text-gray-600 dark:text-zinc-400 underline underline-offset-2">
                                {{ update.download.url || update.kind === 'docker' ? 'All downloads' : 'Open the downloads' }}
                            </button>
                        </div>
                        <div v-else-if="update && update.error" class="mt-1 text-sm text-red-600 dark:text-red-400">{{ update.error }}</div>
                        <div v-else-if="update && update.checked" class="mt-1 text-sm text-gray-700 dark:text-zinc-400">Up to date (v{{ update.current }})</div>
                    </div>

                    <!-- reticulum config path -->
                    <div class="flex p-1">
                        <div class="mr-auto">
                            <div>Reticulum Config Path</div>
                            <div class="text-sm text-gray-700 dark:text-zinc-400 break-all">{{ appInfo.reticulum_config_path }}</div>
                        </div>
                        <div v-if="isElectron" class="mx-2 my-auto">
                            <button @click="showReticulumConfigFile" 
                                type="button" 
                                class="my-auto inline-flex items-center gap-x-1 rounded-md bg-gray-500 dark:bg-zinc-700 px-2 py-1 text-sm font-semibold text-white shadow-sm hover:bg-gray-400 dark:hover:bg-zinc-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-500 dark:focus-visible:outline-zinc-600">
                                Show in Folder
                            </button>
                        </div>
                    </div>

                    <!-- database path -->
                    <div class="flex p-1">
                        <div class="mr-auto">
                            <div>Database Path</div>
                            <div class="text-sm text-gray-700 dark:text-zinc-400 break-all">{{ appInfo.database_path }}</div>
                        </div>
                        <div v-if="isElectron" class="mx-2 my-auto">
                            <button @click="showDatabaseFile" 
                                type="button" 
                                class="my-auto inline-flex items-center gap-x-1 rounded-md bg-gray-500 dark:bg-zinc-700 px-2 py-1 text-sm font-semibold text-white shadow-sm hover:bg-gray-400 dark:hover:bg-zinc-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-500 dark:focus-visible:outline-zinc-600">
                                Show in Folder
                            </button>
                        </div>
                    </div>

                    <!-- database file size -->
                    <div class="p-1">
                        <div>Database File Size</div>
                        <div class="text-sm text-gray-700 dark:text-zinc-400">{{ formatBytes(appInfo.database_file_size) }}</div>
                    </div>

                </div>
            </div>

            <!-- reticulum status -->
            <div v-if="appInfo" class="bg-white dark:bg-zinc-900 rounded shadow">
                <div class="flex border-b border-gray-300 dark:border-zinc-700 text-gray-700 dark:text-zinc-200 p-2 font-semibold">Reticulum Status</div>
                <div class="divide-y divide-gray-200 dark:divide-zinc-800 text-gray-900 dark:text-zinc-200">

                    <!-- instance mode -->
                    <div class="p-1">
                        <div>Instance Mode</div>
                        <div class="text-sm text-gray-700 dark:text-zinc-400">
                            <span v-if="appInfo.is_connected_to_shared_instance" class="text-orange-600 dark:text-orange-400">Connected to Shared Instance</span>
                            <span v-else class="text-green-600 dark:text-green-400">Running as Standalone Instance</span>
                        </div>
                    </div>

                    <!-- transport mode -->
                    <div class="p-1">
                        <div>Transport Mode</div>
                        <div class="text-sm text-gray-700 dark:text-zinc-400">
                            <span v-if="appInfo.is_transport_enabled" class="text-green-600 dark:text-green-400">Transport Enabled</span>
                            <span v-else class="text-orange-600 dark:text-orange-400">Transport Disabled</span>
                        </div>
                    </div>

                </div>
            </div>

            <!-- my addresses -->
            <div v-if="config" class="bg-white dark:bg-zinc-900 rounded shadow">
                <div class="flex border-b border-gray-300 dark:border-zinc-700 text-gray-700 dark:text-zinc-200 p-2 font-semibold">My Addresses</div>
                <div class="divide-y divide-gray-200 dark:divide-zinc-800 text-gray-900 dark:text-zinc-200">
                    <div class="p-1">
                        <div>Identity Hash</div>
                        <div class="text-sm text-gray-700 dark:text-zinc-400">{{ config.identity_hash }}</div>
                    </div>
                    <div class="p-1">
                        <div>LXMF Address</div>
                        <div class="text-sm text-gray-700 dark:text-zinc-400">{{ config.lxmf_address_hash }}</div>
                    </div>
                    <div class="p-1">
                        <div>LXMF Propagation Node Address</div>
                        <div class="text-sm text-gray-700 dark:text-zinc-400">{{ config.lxmf_local_propagation_node_address_hash }}</div>
                    </div>
                    <div class="p-1">
                        <div>Audio Call Address</div>
                        <div class="text-sm text-gray-700 dark:text-zinc-400">{{ config.audio_call_address_hash }}</div>
                    </div>
                </div>
            </div>

            <!-- credits and licenses (plain text, as the licenses require the notices to be included) -->
            <div class="bg-white dark:bg-zinc-900 rounded shadow">
                <div class="flex border-b border-gray-300 dark:border-zinc-700 text-gray-700 dark:text-zinc-200 p-2 font-semibold">Credits and Licenses</div>
                <div class="p-2 space-y-3 text-sm text-gray-700 dark:text-zinc-300">
                    <p>LCS MeshChat is made by Liberty Communication Systems, Inc. It is built on these open-source projects, used under their licenses:</p>
                    <ul class="space-y-2 list-disc pl-5">
                        <li><span class="font-semibold text-gray-900 dark:text-zinc-100">Reticulum MeshChat</span>: Copyright © 2024 Liam Cottle. MIT License. LCS MeshChat is a modified version of Reticulum MeshChat. The LCS name, logos and LCS's changes are not covered by that license.</li>
                        <li><span class="font-semibold text-gray-900 dark:text-zinc-100">Reticulum (RNS)</span>: Copyright © 2016–2026 Mark Qvist. Reticulum License.</li>
                        <li><span class="font-semibold text-gray-900 dark:text-zinc-100">LXMF</span>: Copyright © 2020–2025 Mark Qvist. Reticulum License.</li>
                        <li><span class="font-semibold text-gray-900 dark:text-zinc-100">LXST</span> (voice calls): Copyright © Mark Qvist. Creative Commons BY-NC-ND 4.0.</li>
                        <li><span class="font-semibold text-gray-900 dark:text-zinc-100">Tor</span>: Copyright © 2001–2004 Roger Dingledine, © 2004–2006 Roger Dingledine and Nick Mathewson, © 2007–2019 The Tor Project, Inc. 3-clause BSD License. "Tor" is a trademark of The Tor Project, Inc.</li>
                        <li>Plus other open-source components (including Electron, Vue and aiohttp), each under its own license.</li>
                    </ul>
                    <p>These projects are independent and are not affiliated with, or endorsed by, Liberty Communication Systems, Inc.</p>
                    <div>
                        <button @click="toggleLicenses" type="button"
                                class="inline-flex items-center gap-x-1 rounded-md bg-gray-500 dark:bg-zinc-700 px-2 py-1 text-sm font-semibold text-white shadow-sm hover:bg-gray-400 dark:hover:bg-zinc-600">
                            {{ licensesText !== null ? "Hide full license texts" : "Show full license texts" }}
                        </button>
                    </div>
                    <pre v-if="licensesText !== null" class="max-h-96 overflow-auto whitespace-pre-wrap rounded bg-gray-50 dark:bg-zinc-950 border border-gray-200 dark:border-zinc-800 p-3 text-xs leading-relaxed text-gray-700 dark:text-zinc-400">{{ licensesText }}</pre>
                </div>
            </div>

        </div>
    </div>
</template>

<script>
import Utils from "../../js/Utils";
import ElectronUtils from "../../js/ElectronUtils";
export default {
    name: 'AboutPage',
    data() {
        return {
            appInfo: null,
            config: null,
            licensesText: null,
            update: null,
            updateChecking: false,
            updateWaiting: false,
        };
    },
    mounted() {
        this.getAppInfo();
        this.getConfig();
    },
    methods: {
        // same check as the start-up popup: GitHub first, then the LCS mirror if GitHub can't be
        // reached or has no file of the kind installed here
        async checkForUpdates() {
            this.updateChecking = true;
            this.updateWaiting = false;
            try {
                for (let tries = 0; tries < 10; tries++) {
                    const response = await window.axios.get("/api/v1/app-update", { params: { refresh: 1 } });
                    this.update = response.data.update;
                    if (!this.update?.waiting) break;
                    this.updateWaiting = true; // Tor is on and still connecting
                    await new Promise((resolve) => setTimeout(resolve, 6000));
                }
                if (this.update?.waiting) {
                    this.update = { error: "Tor hasn't connected yet. Try again in a minute." };
                }
            } catch (e) {
                this.update = { error: "Couldn't check for updates. Check your internet connection." };
            } finally {
                this.updateChecking = false;
                this.updateWaiting = false;
            }
        },
        openLink(url) {
            window.open(url, "_blank", "noopener");
        },
        async toggleLicenses() {
            if (this.licensesText !== null) {
                this.licensesText = null;
                return;
            }
            try {
                const response = await fetch("/licenses/THIRD-PARTY-LICENSES.txt");
                this.licensesText = response.ok ? await response.text() : "The license texts couldn't be loaded.";
            } catch (e) {
                this.licensesText = "The license texts couldn't be loaded.";
            }
        },
        async getAppInfo() {
            try {
                const response = await window.axios.get("/api/v1/app/info");
                this.appInfo = response.data.app_info;
            } catch(e) {
                // do nothing if failed to load app info
                console.log(e);
            }
        },
        async getConfig() {
            try {
                const response = await window.axios.get("/api/v1/config");
                this.config = response.data.config;
            } catch(e) {
                // do nothing if failed to load config
                console.log(e);
            }
        },
        showReticulumConfigFile() {
            const reticulumConfigPath = this.appInfo.reticulum_config_path;
            if(reticulumConfigPath){
                ElectronUtils.showPathInFolder(reticulumConfigPath);
            }
        },
        showDatabaseFile() {
            const databasePath = this.appInfo.database_path;
            if(databasePath){
                ElectronUtils.showPathInFolder(databasePath);
            }
        },
        formatBytes: function(bytes) {
            return Utils.formatBytes(bytes);
        },
    },
    computed: {
        isElectron() {
            return ElectronUtils.isElectron();
        },
    },
}
</script>
