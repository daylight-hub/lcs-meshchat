<template>
    <div class="flex flex-col flex-1 overflow-hidden min-w-full sm:min-w-[500px] dark:bg-zinc-950">
        <div class="overflow-y-auto space-y-2 p-2">

            <!-- appearance -->
            <div class="bg-white dark:bg-zinc-800 rounded shadow">
                <div class="flex border-b border-gray-300 dark:border-zinc-700 text-gray-700 dark:text-gray-200 p-2 font-semibold">Tools</div>
                <div class="dark:divide-zinc-700 text-gray-900 dark:text-gray-100 p-2">
                    A collection of useful tools bundled with LCS MeshChat
                </div>
            </div>

            <!-- ping -->
            <RouterLink :to="{ name: 'ping' }" class="group flex bg-white dark:bg-zinc-800 p-2 rounded shadow hover:bg-gray-50 dark:hover:bg-zinc-700">
                <div class="mr-2">
                    <div class="flex bg-gray-300 text-gray-500 rounded shadow p-2">
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="size-10">
                            <path fill-rule="evenodd" d="M14.615 1.595a.75.75 0 0 1 .359.852L12.982 9.75h7.268a.75.75 0 0 1 .548 1.262l-10.5 11.25a.75.75 0 0 1-1.272-.71l1.992-7.302H3.75a.75.75 0 0 1-.548-1.262l10.5-11.25a.75.75 0 0 1 .913-.143Z" clip-rule="evenodd" />
                        </svg>
                    </div>
                </div>
                <div class="my-auto mr-auto dark:text-gray-200">
                    <div class="font-bold">Ping</div>
                    <div class="text-sm">Allows you to ping a destination hash.</div>
                </div>
                <div class="my-auto text-gray-400 group-hover:text-gray-500">
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6">
                        <path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5"></path>
                    </svg>
                </div>
            </RouterLink>

            <!-- rnode configuration tool (LCS) -->
            <a target="_blank" href="/rnode-config/index.html" class="group flex bg-white dark:bg-zinc-800 p-2 rounded shadow hover:bg-gray-50 dark:hover:bg-zinc-700">
                <div class="mr-2">
                    <div class="flex items-center justify-center size-14 rounded shadow bg-gradient-to-br from-[#1e5aa0] to-[#123a6b] p-1">
                        <img class="w-full h-full object-contain" src="/assets/images/lcs-logo.png" alt="Liberty Communication Systems" />
                    </div>
                </div>
                <div class="my-auto mr-auto dark:text-gray-200">
                    <div class="font-bold">RNode Configuration Tool</div>
                    <div class="text-sm">Flash and configure RNode LoRa radios.</div>
                </div>
                <div class="my-auto text-gray-400 group-hover:text-gray-500">
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6">
                        <path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5"></path>
                    </svg>
                </div>
            </a>

            <!-- transport node console -->
            <a target="_blank" href="/transport-console/index.html" class="group flex bg-white dark:bg-zinc-800 p-2 rounded shadow hover:bg-gray-50 dark:hover:bg-zinc-700">
                <div class="mr-2">
                    <div class="flex items-center justify-center size-14 rounded shadow text-white bg-gradient-to-br from-[#1e5aa0] to-[#123a6b]">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-8">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M6.75 7.5l3 2.25-3 2.25m4.5 0h3m-9 8.25h13.5A2.25 2.25 0 0021 18V6a2.25 2.25 0 00-2.25-2.25H5.25A2.25 2.25 0 003 6v12a2.25 2.25 0 002.25 2.25z" />
                        </svg>
                    </div>
                </div>
                <div class="my-auto mr-auto dark:text-gray-200">
                    <div class="font-bold">Transport Node Console</div>
                    <div class="text-sm">Configure and monitor RNode transport nodes.</div>
                </div>
                <div class="my-auto text-gray-400 group-hover:text-gray-500">
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6">
                        <path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5"></path>
                    </svg>
                </div>
            </a>

            <!-- read the holy bible (bundled KJV pdf) -->
            <a target="_blank" href="/bible/KJV-Bible.pdf" class="group flex bg-white dark:bg-zinc-800 p-2 rounded shadow hover:bg-gray-50 dark:hover:bg-zinc-700">
                <div class="mr-2">
                    <div class="flex items-center justify-center size-14 rounded shadow text-white bg-gradient-to-br from-[#1e5aa0] to-[#123a6b]">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-8">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25" />
                        </svg>
                    </div>
                </div>
                <div class="my-auto mr-auto dark:text-gray-200">
                    <div class="font-bold">Read the Holy Bible</div>
                    <div class="text-sm">King James Version &middot; available offline.</div>
                </div>
                <div class="my-auto text-gray-400 group-hover:text-gray-500">
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6">
                        <path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5"></path>
                    </svg>
                </div>
            </a>

            <!-- about reticulum - in-app LCS Network guide (LCS) -->
            <button type="button" @click="showGuide = true" class="text-left w-full group flex bg-white dark:bg-zinc-800 p-2 rounded shadow hover:bg-gray-50 dark:hover:bg-zinc-700">
                <div class="mr-2">
                    <div class="flex items-center justify-center size-14 rounded shadow bg-white p-1">
                        <img class="w-full h-full object-contain" src="/assets/images/reticulum_logo_512.png" alt="Reticulum" />
                    </div>
                </div>
                <div class="my-auto mr-auto dark:text-gray-200">
                    <div class="font-bold">About Reticulum</div>
                    <div class="text-sm">The LCS Network guide to Reticulum, LXMF and LXST.</div>
                </div>
                <div class="my-auto text-gray-400 group-hover:text-gray-500">
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6">
                        <path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5"></path>
                    </svg>
                </div>
            </button>

            <!-- purchase rnode mesh radios (LCS) -->
            <a target="_blank" href="https://lcs.network" class="group flex bg-white dark:bg-zinc-800 p-2 rounded shadow hover:bg-gray-50 dark:hover:bg-zinc-700">
                <div class="mr-2">
                    <div class="flex items-center justify-center size-14 rounded shadow text-white bg-gradient-to-br from-[#1e5aa0] to-[#123a6b]">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-8">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 3h1.386c.51 0 .955.343 1.087.835l.383 1.437M7.5 14.25a3 3 0 0 0-3 3h15.75m-12.75-3h11.218c1.121-2.3 2.1-4.684 2.924-7.138a60.114 60.114 0 0 0-16.536-1.84M7.5 14.25 5.106 5.272M6 20.25a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0Zm12.75 0a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0Z" />
                        </svg>
                    </div>
                </div>
                <div class="my-auto mr-auto dark:text-gray-200">
                    <div class="font-bold">Purchase RNode Mesh Radios</div>
                    <div class="text-sm">lcs.network</div>
                </div>
                <div class="my-auto text-gray-400 group-hover:text-gray-500">
                    <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-6">
                        <path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5"></path>
                    </svg>
                </div>
            </a>

        </div>

        <!-- LCS: About Reticulum - the complete LCS Network guide, in-app -->
        <div v-if="showGuide" @click.self="showGuide = false" class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-2 sm:p-4">
            <div class="bg-white dark:bg-zinc-900 rounded-xl shadow-2xl max-w-5xl w-full max-h-[92vh] flex flex-col overflow-hidden">

                <!-- title bar -->
                <div class="flex items-center justify-between px-5 py-3 border-b dark:border-zinc-700 bg-gradient-to-r from-[#123a6b] to-[#1e5aa0] text-white shrink-0">
                    <div class="flex items-center gap-x-3 min-w-0">
                        <img class="size-9 object-contain rounded bg-white/95 p-0.5 shrink-0" src="/assets/images/guide/lcs-logo.png" alt="LCS" />
                        <div class="min-w-0">
                            <div class="font-bold leading-tight truncate">The LCS Network</div>
                            <div class="text-xs text-blue-100 truncate">A Guide to Reticulum, LXMF and LXST</div>
                        </div>
                    </div>
                    <button type="button" @click="showGuide = false" class="text-white/80 hover:text-white shrink-0 ml-3">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="size-6">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
                        </svg>
                    </button>
                </div>

                <div class="overflow-y-auto px-5 sm:px-8 py-6 text-sm dark:text-gray-200 leading-relaxed">
                    <div class="max-w-3xl mx-auto space-y-8">

                        <p class="text-gray-600 dark:text-gray-300 text-base">
                            This explains what the LCS Network is, how it works, and what it requires. It is
                            written for someone who has never encountered Reticulum before, and applies to
                            <b>Liberty Chat</b>, <b>LCS MeshChat</b> and the <b>Liberty Deck</b>.
                        </p>

                        <!-- 1 -->
                        <section>
                            <h3 class="text-lg font-bold text-[#1e5aa0] dark:text-blue-400 pb-1 mb-3 border-b-2 border-[#1e5aa0]/30">1 &nbsp;·&nbsp; The Three-Layer Stack</h3>
                            <p class="mb-3">The LCS Network runs three open protocols, each handling one job.</p>
                            <div class="overflow-x-auto rounded-lg border dark:border-zinc-700 mb-3">
                                <table class="w-full text-xs">
                                    <thead class="bg-[#123a6b] text-white">
                                        <tr>
                                            <th class="text-left px-3 py-2 font-semibold">Layer</th>
                                            <th class="text-left px-3 py-2 font-semibold">Protocol</th>
                                            <th class="text-left px-3 py-2 font-semibold">Function</th>
                                            <th class="text-left px-3 py-2 font-semibold">Analogy</th>
                                        </tr>
                                    </thead>
                                    <tbody class="divide-y dark:divide-zinc-700">
                                        <tr><td class="px-3 py-2 font-semibold">Bottom</td><td class="px-3 py-2">Reticulum (RNS)</td><td class="px-3 py-2">Addressing, routing and encryption across any physical medium.</td><td class="px-3 py-2 text-gray-500 dark:text-gray-400">The road network</td></tr>
                                        <tr class="bg-gray-50 dark:bg-zinc-800/50"><td class="px-3 py-2 font-semibold">Middle</td><td class="px-3 py-2">LXMF</td><td class="px-3 py-2">Text, files, images and recorded voice — with store-and-forward delivery for offline recipients.</td><td class="px-3 py-2 text-gray-500 dark:text-gray-400">The postal service</td></tr>
                                        <tr><td class="px-3 py-2 font-semibold">Top</td><td class="px-3 py-2">LXST</td><td class="px-3 py-2">Live, encrypted voice calls.</td><td class="px-3 py-2 text-gray-500 dark:text-gray-400">The telephone</td></tr>
                                    </tbody>
                                </table>
                            </div>
                            <ul class="list-disc ml-5 space-y-1">
                                <li>Reticulum is the foundation. LXMF and LXST ride on top of it and inherit its encryption and routing automatically.</li>
                                <li>All three LCS apps are <b>LXMF clients</b>. They speak the same protocol and interoperate fully, including with third-party clients such as Sideband and Nomad Network.</li>
                            </ul>
                        </section>

                        <!-- 2 -->
                        <section>
                            <h3 class="text-lg font-bold text-[#1e5aa0] dark:text-blue-400 pb-1 mb-3 border-b-2 border-[#1e5aa0]/30">2 &nbsp;·&nbsp; Reticulum — The Network Foundation</h3>
                            <div class="sm:flex sm:gap-x-5 items-start">
                                <p class="mb-3 sm:mb-0 sm:flex-1">
                                    Reticulum is an open-source, cryptography-based networking stack built for links
                                    that are slow, intermittent and untrusted. It does not assume the existence of
                                    servers, providers or fixed infrastructure. It was built by <b>Mark Qvist</b>, who
                                    spent years perfecting this revolutionary communications breakthrough.
                                </p>
                                <img class="w-28 h-28 object-contain mx-auto sm:mx-0 shrink-0 dark:bg-white dark:rounded-lg dark:p-1" src="/assets/images/guide/rns-logo.png" alt="Reticulum" />
                            </div>
                            <h4 class="font-semibold mt-4 mb-2">Key characteristics</h4>
                            <ul class="list-disc ml-5 space-y-1">
                                <li><b>No central authority.</b> No registry, no account server, no gatekeeper. Any device running Reticulum is part of the network.</li>
                                <li><b>No addresses or ports.</b> A single concept — a <i>destination</i> — derived from cryptographic keys. No DHCP, subnetting or port forwarding.</li>
                                <li><b>Medium-agnostic.</b> The same packets travel over LoRa, packet radio, Wi-Fi, Ethernet, USB, Bluetooth or the internet, mixed freely in one network.</li>
                                <li><b>Encrypted by default.</b> Encryption is structural, not optional. Unencrypted traffic cannot be forwarded across multiple hops.</li>
                                <li><b>Extreme bandwidth tolerance.</b> Remains functional on links as slow as 5 bits per second.</li>
                                <li><b>Location-independent addresses.</b> A device keeps the same address on home Wi-Fi, a LoRa radio, or the public internet.</li>
                            </ul>
                            <h4 class="font-semibold mt-4 mb-2">Host device requirement</h4>
                            <p>
                                Reticulum is software. It must run on a <b>host device</b> — an Android phone, a
                                Windows/Mac/Linux computer, or a Command Center PRO Gateway. The host provides
                                processing, storage and the user interface. Physical access to the network is
                                provided by an <b>interface</b> attached to or configured on that host.
                            </p>
                            <p class="mt-3 border-l-4 border-amber-500 bg-amber-50 dark:bg-amber-500/10 pl-3 py-2 text-gray-700 dark:text-gray-300 rounded-r">
                                An RNode radio without a host is just a radio. A host without an interface cannot
                                reach anyone. Together they form a node on the network.
                            </p>
                        </section>

                        <!-- 3 -->
                        <section>
                            <h3 class="text-lg font-bold text-[#1e5aa0] dark:text-blue-400 pb-1 mb-3 border-b-2 border-[#1e5aa0]/30">3 &nbsp;·&nbsp; Applications and Host Devices</h3>
                            <div class="overflow-x-auto rounded-lg border dark:border-zinc-700">
                                <table class="w-full text-xs">
                                    <thead class="bg-[#123a6b] text-white">
                                        <tr>
                                            <th class="text-left px-3 py-2 font-semibold"></th>
                                            <th class="text-left px-3 py-2 font-semibold">Liberty Chat</th>
                                            <th class="text-left px-3 py-2 font-semibold">LCS MeshChat</th>
                                            <th class="text-left px-3 py-2 font-semibold">Liberty Deck</th>
                                        </tr>
                                    </thead>
                                    <tbody class="divide-y dark:divide-zinc-700">
                                        <tr><td class="px-3 py-2 font-semibold">Platform</td><td class="px-3 py-2">Android phones and tablets</td><td class="px-3 py-2">Windows, macOS, Linux</td><td class="px-3 py-2">Dedicated LCS handheld</td></tr>
                                        <tr class="bg-gray-50 dark:bg-zinc-800/50"><td class="px-3 py-2 font-semibold">Interface</td><td class="px-3 py-2">Native Android app</td><td class="px-3 py-2">Desktop app or browser</td><td class="px-3 py-2">On-device — no phone or PC</td></tr>
                                        <tr><td class="px-3 py-2 font-semibold">Connections</td><td class="px-3 py-2">Bluetooth LE, Wi-Fi, USB-C RNode, LCS Global</td><td class="px-3 py-2">Wi-Fi/Ethernet, USB or IP RNode, LCS Global, Tor, I2P</td><td class="px-3 py-2">Built-in LoRa radio; Wi-Fi where supported</td></tr>
                                        <tr class="bg-gray-50 dark:bg-zinc-800/50"><td class="px-3 py-2 font-semibold">Text and files</td><td class="px-3 py-2">Yes</td><td class="px-3 py-2">Yes (10 MB receive limit)</td><td class="px-3 py-2">Yes (storage limited)</td></tr>
                                        <tr><td class="px-3 py-2 font-semibold">PTT voice</td><td class="px-3 py-2">Codec2 and Opus</td><td class="px-3 py-2">Codec2 and Opus</td><td class="px-3 py-2">Limited</td></tr>
                                        <tr class="bg-gray-50 dark:bg-zinc-800/50"><td class="px-3 py-2 font-semibold">Live voice</td><td class="px-3 py-2">Yes, mid-call codec switching</td><td class="px-3 py-2">Yes, mid-call codec switching</td><td class="px-3 py-2">Basic</td></tr>
                                        <tr><td class="px-3 py-2 font-semibold">Propagation node</td><td class="px-3 py-2">Uses them</td><td class="px-3 py-2">Uses and can host one</td><td class="px-3 py-2">Uses them</td></tr>
                                    </tbody>
                                </table>
                            </div>
                            <ul class="list-disc ml-5 space-y-1 mt-3">
                                <li>Liberty Chat ships with LCS radio defaults: slot 51, 914.875 MHz, 22 dBm, Long Fast preset.</li>
                                <li>LCS MeshChat is the right choice for a machine that stays on, because it can host a propagation node for the whole local segment.</li>
                                <li>The <b>Command Center PRO Gateway</b> runs Reticulum continuously as fixed or mobile infrastructure, bridging LoRa, packet radio, Wi-Fi and Ethernet, and hosting MeshChat at <code>liberty.local</code>.</li>
                            </ul>
                        </section>

                        <!-- 4 -->
                        <section>
                            <h3 class="text-lg font-bold text-[#1e5aa0] dark:text-blue-400 pb-1 mb-3 border-b-2 border-[#1e5aa0]/30">4 &nbsp;·&nbsp; Instances, Nodes and Interfaces</h3>
                            <p class="mb-3"><b>Instance</b> — every host device running Reticulum. The word simply means "Reticulum is running here."</p>
                            <p class="mb-2"><b>Node</b> — an instance given a specific role:</p>
                            <div class="overflow-x-auto rounded-lg border dark:border-zinc-700 mb-3">
                                <table class="w-full text-xs">
                                    <thead class="bg-[#123a6b] text-white">
                                        <tr>
                                            <th class="text-left px-3 py-2 font-semibold">Node type</th>
                                            <th class="text-left px-3 py-2 font-semibold">What it does</th>
                                            <th class="text-left px-3 py-2 font-semibold">Enabled by</th>
                                        </tr>
                                    </thead>
                                    <tbody class="divide-y dark:divide-zinc-700">
                                        <tr><td class="px-3 py-2 font-semibold">Client node</td><td class="px-3 py-2">An endpoint. Sends and receives for a user; does not relay.</td><td class="px-3 py-2">Default — all instances start here.</td></tr>
                                        <tr class="bg-gray-50 dark:bg-zinc-800/50"><td class="px-3 py-2 font-semibold">Transport node</td><td class="px-3 py-2">A relay. Forwards others' encrypted traffic one hop closer, and cannot read it.</td><td class="px-3 py-2"><code>enable_transport = Yes</code></td></tr>
                                        <tr><td class="px-3 py-2 font-semibold">Propagation node</td><td class="px-3 py-2">A store-and-forward mailbox. Holds encrypted messages for offline recipients.</td><td class="px-3 py-2">The LXMF propagation node service.</td></tr>
                                    </tbody>
                                </table>
                            </div>
                            <p class="mb-3"><b>Interface</b> — the connection between the host and the physical medium. It is not a node; it is the on-ramp a node uses. One host can run several at once, and Reticulum selects among them automatically.</p>
                            <div class="overflow-x-auto rounded-lg border dark:border-zinc-700">
                                <table class="w-full text-xs">
                                    <thead class="bg-[#123a6b] text-white">
                                        <tr>
                                            <th class="text-left px-3 py-2 font-semibold">Interface</th>
                                            <th class="text-left px-3 py-2 font-semibold">Medium</th>
                                            <th class="text-left px-3 py-2 font-semibold">Notes</th>
                                        </tr>
                                    </thead>
                                    <tbody class="divide-y dark:divide-zinc-700">
                                        <tr><td class="px-3 py-2 font-semibold">RNode (LoRa)</td><td class="px-3 py-2">902–928 MHz ISM</td><td class="px-3 py-2">Licence-free. USB-C, Bluetooth LE, or Wi-Fi (IP RNode). ~341 bps – 21.88 kbps.</td></tr>
                                        <tr class="bg-gray-50 dark:bg-zinc-800/50"><td class="px-3 py-2 font-semibold">Packet Radio</td><td class="px-3 py-2">VHF 150–174 / UHF 450–470 MHz</td><td class="px-3 py-2">Long-haul links between gateways. FCC licence required for encrypted operation.</td></tr>
                                        <tr><td class="px-3 py-2 font-semibold">AutoInterface</td><td class="px-3 py-2">Local Wi-Fi or Ethernet</td><td class="px-3 py-2">Zero configuration. Requires UDP ports 29716 and 42671.</td></tr>
                                        <tr class="bg-gray-50 dark:bg-zinc-800/50"><td class="px-3 py-2 font-semibold">LCS Global</td><td class="px-3 py-2">Wi-Fi or mobile data</td><td class="px-3 py-2">Reaches the Liberty network from anywhere. Set up by its subscription; free 7-day trial.</td></tr>
                                        <tr><td class="px-3 py-2 font-semibold">Tor</td><td class="px-3 py-2">Wi-Fi or mobile data, through Tor</td><td class="px-3 py-2">Optional for LCS Global. Hides this device's internet address from LCS and from anyone watching the connection.</td></tr>
                                        <tr class="bg-gray-50 dark:bg-zinc-800/50"><td class="px-3 py-2 font-semibold">I2P</td><td class="px-3 py-2">Anonymizing overlay</td><td class="px-3 py-2">Reachable without a public IP; endpoint IPs are not exposed. Requires i2pd on the host.</td></tr>
                                        <tr><td class="px-3 py-2 font-semibold">Bluetooth LE</td><td class="px-3 py-2">Short-range personal radio</td><td class="px-3 py-2">Enabled by default in Liberty Chat.</td></tr>
                                        <tr class="bg-gray-50 dark:bg-zinc-800/50"><td class="px-3 py-2 font-semibold">Serial / USB-C</td><td class="px-3 py-2">Direct cable</td><td class="px-3 py-2">The most straightforward client connection.</td></tr>
                                    </tbody>
                                </table>
                            </div>
                            <p class="mt-3 text-gray-600 dark:text-gray-300">
                                A fresh Liberty Chat install uses AutoInterface and Bluetooth LE only. Nothing
                                reaches the internet until LCS Global is added.
                            </p>
                            <h4 class="font-semibold mt-4 mb-2">Combined function hardware</h4>
                            <p>
                                The <b>Solar Transport Node</b> and the <b>IP RNode</b> integrate Reticulum and the
                                radio into one enclosure. They need no separate host and relay traffic
                                automatically, operating like a repeater. The Solar Transport Node is self-powered
                                for unattended outdoor use; the IP RNode joins an existing Wi-Fi network so the radio
                                can sit near the antenna while the computer stays at a desk.
                            </p>
                        </section>

                        <!-- 5 -->
                        <section>
                            <h3 class="text-lg font-bold text-[#1e5aa0] dark:text-blue-400 pb-1 mb-3 border-b-2 border-[#1e5aa0]/30">5 &nbsp;·&nbsp; Identities and Addresses</h3>
                            <p class="mb-2">
                                A <b>Reticulum Identity</b> is a public/private key pair generated locally at first
                                launch. No registration, phone number or email address is required.
                            </p>
                            <ul class="list-disc ml-5 space-y-1 mb-3">
                                <li>The private key stays on the device. It decrypts inbound messages and produces signed delivery proofs.</li>
                                <li>The public key is shared so others can encrypt traffic only the holder can open.</li>
                                <li>Identities are portable files — exporting and importing one moves the address to new hardware.</li>
                                <li>A single identity can generate multiple addresses: messaging, voice, file hosting.</li>
                            </ul>
                            <p class="mb-3">
                                An <b>LXMF address</b> is derived from that identity — a 32-character hexadecimal
                                hash such as
                                <code class="text-xs bg-gray-100 dark:bg-zinc-800 px-1.5 py-0.5 rounded">13425ec15b621c1d928589718000d814</code>.
                                No registrar issues it, no authority can revoke it, and it cannot be impersonated.
                            </p>
                            <p class="border-l-4 border-red-500 bg-red-50 dark:bg-red-500/10 pl-3 py-2 text-gray-700 dark:text-gray-300 rounded-r">
                                Back up the identity file and treat it as carefully as a private key. Whoever holds
                                it controls that address.
                            </p>
                        </section>

                        <!-- 6 -->
                        <section>
                            <h3 class="text-lg font-bold text-[#1e5aa0] dark:text-blue-400 pb-1 mb-3 border-b-2 border-[#1e5aa0]/30">6 &nbsp;·&nbsp; The Announce System</h3>
                            <p class="mb-2">Reticulum has no directory server. Peer discovery is handled by <b>announces</b> — small signed broadcasts containing the destination address, its public key, an optional display name, a unique random value, and an Ed25519 signature.</p>
                            <h4 class="font-semibold mt-3 mb-2">How they propagate</h4>
                            <ul class="list-disc ml-5 space-y-1 mb-3">
                                <li>Any transport node that hears an announce records where it came from and re-broadcasts it after a short random delay.</li>
                                <li>No node learns the whole topology — each only knows the next hop toward a destination.</li>
                                <li>Announces stop after 128 hops, and announce traffic is capped at 2% of interface bandwidth, so a fast network cannot flood a slow LoRa segment.</li>
                            </ul>
                            <h4 class="font-semibold mb-2">In practice</h4>
                            <ul class="list-disc ml-5 space-y-1">
                                <li>A device that has never announced is not reachable. Press <b>Announce</b> once at setup.</li>
                                <li>Announcing makes your display name appear in others' peer lists automatically.</li>
                                <li>Re-announce after any change in how you connect — switching interfaces, attaching or removing an RNode, or joining a different network.</li>
                                <li>Announce sparingly. Flooding causes the network to down-prioritize you, making you <i>harder</i> to reach.</li>
                            </ul>
                        </section>

                        <!-- 7 -->
                        <section>
                            <h3 class="text-lg font-bold text-[#1e5aa0] dark:text-blue-400 pb-1 mb-3 border-b-2 border-[#1e5aa0]/30">7 &nbsp;·&nbsp; Packets and Links</h3>
                            <div class="overflow-x-auto rounded-lg border dark:border-zinc-700 mb-3">
                                <table class="w-full text-xs">
                                    <thead class="bg-[#123a6b] text-white">
                                        <tr>
                                            <th class="text-left px-3 py-2 font-semibold"></th>
                                            <th class="text-left px-3 py-2 font-semibold">Single Packet</th>
                                            <th class="text-left px-3 py-2 font-semibold">Established Link</th>
                                        </tr>
                                    </thead>
                                    <tbody class="divide-y dark:divide-zinc-700">
                                        <tr><td class="px-3 py-2 font-semibold">Best for</td><td class="px-3 py-2">Short messages, fire-and-forget</td><td class="px-3 py-2">Conversations, voice calls, file transfers</td></tr>
                                        <tr class="bg-gray-50 dark:bg-zinc-800/50"><td class="px-3 py-2 font-semibold">Setup overhead</td><td class="px-3 py-2">None</td><td class="px-3 py-2">3 packets, 297 bytes</td></tr>
                                        <tr><td class="px-3 py-2 font-semibold">Encryption</td><td class="px-3 py-2">Fresh key per packet</td><td class="px-3 py-2">Ephemeral shared key for the session</td></tr>
                                        <tr class="bg-gray-50 dark:bg-zinc-800/50"><td class="px-3 py-2 font-semibold">Forward secrecy</td><td class="px-3 py-2">With key ratchets enabled</td><td class="px-3 py-2">Always</td></tr>
                                        <tr><td class="px-3 py-2 font-semibold">Large data</td><td class="px-3 py-2">Not supported</td><td class="px-3 py-2">Yes — auto-split, compressed, verified</td></tr>
                                        <tr class="bg-gray-50 dark:bg-zinc-800/50"><td class="px-3 py-2 font-semibold">Idle cost</td><td class="px-3 py-2">None</td><td class="px-3 py-2">~0.45 bits per second</td></tr>
                                    </tbody>
                                </table>
                            </div>
                            <ul class="list-disc ml-5 space-y-1">
                                <li>A link is not a physical connection. It is an encrypted tunnel that can span many hops and stay open for hours.</li>
                                <li>Both ends authenticate cryptographically before any data flows.</li>
                                <li>A 1200 bps packet radio channel can sustain roughly 100 concurrent links while keeping most of its capacity for data.</li>
                            </ul>
                        </section>

                        <!-- 8 -->
                        <section>
                            <h3 class="text-lg font-bold text-[#1e5aa0] dark:text-blue-400 pb-1 mb-3 border-b-2 border-[#1e5aa0]/30">8 &nbsp;·&nbsp; LXMF — Messaging</h3>
                            <ul class="list-disc ml-5 space-y-1 mb-3">
                                <li>Protocol overhead is only <b>111 bytes</b> per message — small enough to transit LoRa and packet radio comfortably.</li>
                                <li>Every message is timestamped and Ed25519-signed, so the sender cannot be forged.</li>
                                <li>Messages carry a title, a body, and an extensible fields section for attachments, images, audio clips, location and telemetry.</li>
                                <li>All LXMF clients interoperate — Liberty Chat, LCS MeshChat, the Liberty Deck, Sideband and Nomad Network exchange messages freely.</li>
                            </ul>
                            <h4 class="font-semibold mb-2">Propagation nodes — offline delivery</h4>
                            <ul class="list-disc ml-5 space-y-1 mb-3">
                                <li>When a recipient is offline, the message is held and delivered automatically on reconnection.</li>
                                <li>Propagation nodes peer and synchronize with each other, forming a distributed store with no single point of failure.</li>
                            </ul>
                            <p class="border-l-4 border-[#1e5aa0] bg-blue-50 dark:bg-blue-500/10 pl-3 py-2 text-gray-700 dark:text-gray-300 rounded-r">
                                Propagation nodes store messages they cannot read. Content stays encrypted to the
                                recipient's key for as long as it is held.
                            </p>
                        </section>

                        <!-- 9 -->
                        <section>
                            <h3 class="text-lg font-bold text-[#1e5aa0] dark:text-blue-400 pb-1 mb-3 border-b-2 border-[#1e5aa0]/30">9 &nbsp;·&nbsp; LXST — Real-Time Voice</h3>
                            <div class="overflow-x-auto rounded-lg border dark:border-zinc-700 mb-3">
                                <table class="w-full text-xs">
                                    <thead class="bg-[#123a6b] text-white">
                                        <tr>
                                            <th class="text-left px-3 py-2 font-semibold">Codec</th>
                                            <th class="text-left px-3 py-2 font-semibold">Bit rate</th>
                                            <th class="text-left px-3 py-2 font-semibold">Suited to</th>
                                        </tr>
                                    </thead>
                                    <tbody class="divide-y dark:divide-zinc-700">
                                        <tr><td class="px-3 py-2 font-semibold">Codec2</td><td class="px-3 py-2">700 – 3,200 bps</td><td class="px-3 py-2">LoRa and packet radio — intelligible speech at minimal bandwidth</td></tr>
                                        <tr class="bg-gray-50 dark:bg-zinc-800/50"><td class="px-3 py-2 font-semibold">Opus</td><td class="px-3 py-2">~4.5 – 96 kbps</td><td class="px-3 py-2">Wi-Fi, Ethernet and internet — natural, high-quality voice</td></tr>
                                    </tbody>
                                </table>
                            </div>
                            <h4 class="font-semibold mb-2">Voice over LoRa</h4>
                            <ul class="list-disc ml-5 space-y-1">
                                <li>Live calls require a fast preset. <b>Short Fast</b> (≈10.9 kbps) is the slowest that can carry one.</li>
                                <li><b>Half-duplex</b> call mode is recommended on low-speed links.</li>
                                <li><b>Long Fast</b> (≈1.07 kbps) is the general-purpose preset for text and PTT, but cannot sustain a live call.</li>
                                <li>Where capacity is insufficient, use push-to-talk voice clips — recorded and sent as LXMF messages, which work on any link.</li>
                                <li>Codecs can be switched mid-call without dropping the call, and the change is signalled to the remote end.</li>
                            </ul>
                        </section>

                        <!-- 10 -->
                        <section>
                            <h3 class="text-lg font-bold text-[#1e5aa0] dark:text-blue-400 pb-1 mb-3 border-b-2 border-[#1e5aa0]/30">10 &nbsp;·&nbsp; Transport Modes</h3>
                            <div class="overflow-x-auto rounded-lg border dark:border-zinc-700 mb-3">
                                <table class="w-full text-xs">
                                    <thead class="bg-[#123a6b] text-white">
                                        <tr>
                                            <th class="text-left px-3 py-2 font-semibold">Mode</th>
                                            <th class="text-left px-3 py-2 font-semibold">Behaviour</th>
                                            <th class="text-left px-3 py-2 font-semibold">Typical use</th>
                                        </tr>
                                    </thead>
                                    <tbody class="divide-y dark:divide-zinc-700">
                                        <tr><td class="px-3 py-2 font-mono font-semibold">full</td><td class="px-3 py-2">Default. All discovery, meshing and transport active.</td><td class="px-3 py-2">Client devices and most links.</td></tr>
                                        <tr class="bg-gray-50 dark:bg-zinc-800/50"><td class="px-3 py-2 font-mono font-semibold">gateway</td><td class="px-3 py-2">Also resolves unknown paths for devices behind it.</td><td class="px-3 py-2">The LAN-facing side of a gateway.</td></tr>
                                        <tr><td class="px-3 py-2 font-mono font-semibold">access_point</td><td class="px-3 py-2">Quiet until used — no automatic announces, short-lived paths.</td><td class="px-3 py-2">Wide-area radio where users come and go.</td></tr>
                                        <tr class="bg-gray-50 dark:bg-zinc-800/50"><td class="px-3 py-2 font-mono font-semibold">roaming</td><td class="px-3 py-2">Marks a physically mobile interface.</td><td class="px-3 py-2">LoRa side of a vehicle-mounted gateway.</td></tr>
                                        <tr><td class="px-3 py-2 font-mono font-semibold">boundary</td><td class="px-3 py-2">Marks a transition to a very different segment.</td><td class="px-3 py-2">Internet side of a gateway whose local side is LoRa.</td></tr>
                                    </tbody>
                                </table>
                            </div>
                            <p class="text-gray-600 dark:text-gray-300">
                                Setting <code>boundary</code> on an internet-facing interface keeps a large network
                                from flooding a slow LoRa segment with announces. Transport is disabled by default —
                                client apps do not relay other users' traffic.
                            </p>
                        </section>

                        <!-- 11 -->
                        <section>
                            <h3 class="text-lg font-bold text-[#1e5aa0] dark:text-blue-400 pb-1 mb-3 border-b-2 border-[#1e5aa0]/30">11 &nbsp;·&nbsp; Security</h3>
                            <p class="mb-3">LXMF and LXST implement no separate cryptography — both inherit Reticulum's primitives.</p>
                            <div class="overflow-x-auto rounded-lg border dark:border-zinc-700 mb-3">
                                <table class="w-full text-xs">
                                    <thead class="bg-[#123a6b] text-white">
                                        <tr>
                                            <th class="text-left px-3 py-2 font-semibold">Primitive</th>
                                            <th class="text-left px-3 py-2 font-semibold">Purpose</th>
                                        </tr>
                                    </thead>
                                    <tbody class="divide-y dark:divide-zinc-700">
                                        <tr><td class="px-3 py-2 font-mono">X25519</td><td class="px-3 py-2">Key exchange for establishing shared secrets</td></tr>
                                        <tr class="bg-gray-50 dark:bg-zinc-800/50"><td class="px-3 py-2 font-mono">Ed25519</td><td class="px-3 py-2">Signatures — announces, messages, delivery proofs</td></tr>
                                        <tr><td class="px-3 py-2 font-mono">AES-256 (CBC, PKCS7)</td><td class="px-3 py-2">Payload encryption</td></tr>
                                        <tr class="bg-gray-50 dark:bg-zinc-800/50"><td class="px-3 py-2 font-mono">HMAC-SHA256</td><td class="px-3 py-2">Message authentication and integrity</td></tr>
                                        <tr><td class="px-3 py-2 font-mono">HKDF</td><td class="px-3 py-2">Key derivation</td></tr>
                                        <tr class="bg-gray-50 dark:bg-zinc-800/50"><td class="px-3 py-2 font-mono">SHA-256 / SHA-512</td><td class="px-3 py-2">Hashing</td></tr>
                                    </tbody>
                                </table>
                            </div>
                            <ul class="list-disc ml-5 space-y-1 mb-3">
                                <li><b>End-to-end encryption.</b> Relays, gateways and propagation nodes cannot read what they carry.</li>
                                <li><b>Forward secrecy.</b> Links negotiate ephemeral session keys, so a key compromised later does not expose past traffic.</li>
                                <li><b>Authenticity.</b> Every announce and message is Ed25519-signed. Addresses cannot be spoofed.</li>
                                <li><b>Initiator anonymity.</b> The device opening a link stays anonymous unless it chooses to identify, inside the encrypted channel.</li>
                                <li><b>No metadata collection.</b> No sign-up, no contact upload, no central log.</li>
                                <li><b>Optional network isolation.</b> Interfaces can carry a name and passphrase; packets without the right code are dropped at the perimeter.</li>
                            </ul>
                            <p class="border-l-4 border-amber-500 bg-amber-50 dark:bg-amber-500/10 pl-3 py-2 text-gray-700 dark:text-gray-300 rounded-r">
                                <b>Limitations.</b> Encryption protects content, not the existence of a transmission —
                                a radio signal is observable. An unlocked device or an exported identity file is
                                equivalent to holding the address. Encrypted operation on business-band frequencies
                                requires an FCC licence, and rules vary by jurisdiction.
                            </p>
                        </section>

                        <!-- 12 scenarios -->
                        <section>
                            <h3 class="text-lg font-bold text-[#1e5aa0] dark:text-blue-400 pb-1 mb-3 border-b-2 border-[#1e5aa0]/30">12 &nbsp;·&nbsp; Use-Case Scenarios</h3>

                            <div v-for="scenario in guideScenarios" :key="scenario.id" class="mb-7 last:mb-0">
                                <h4 class="font-bold text-[#123a6b] dark:text-blue-300 mb-2">{{ scenario.title }}</h4>
                                <button type="button" @click="guideZoom = scenario.image" class="block w-full mb-1">
                                    <img :src="scenario.image" :alt="scenario.title" class="w-full rounded-lg border dark:border-zinc-700 bg-white cursor-zoom-in shadow-sm" />
                                </button>
                                <div class="text-xs text-center text-gray-500 dark:text-gray-400 italic mb-3">{{ scenario.caption }} · tap to enlarge</div>

                                <div class="sm:grid sm:grid-cols-2 sm:gap-x-6">
                                    <div class="mb-3 sm:mb-0">
                                        <div class="font-semibold text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">Requirements</div>
                                        <ul class="list-disc ml-5 space-y-1">
                                            <li v-for="(r, i) in scenario.requirements" :key="i">{{ r }}</li>
                                        </ul>
                                    </div>
                                    <div>
                                        <div class="font-semibold text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">How it works</div>
                                        <ul class="list-disc ml-5 space-y-1">
                                            <li v-for="(h, i) in scenario.how" :key="i">{{ h }}</li>
                                        </ul>
                                    </div>
                                </div>
                                <div class="mt-3">
                                    <div class="font-semibold text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">Notes</div>
                                    <ul class="list-disc ml-5 space-y-1">
                                        <li v-for="(n, i) in scenario.notes" :key="i">{{ n }}</li>
                                    </ul>
                                </div>
                            </div>
                        </section>

                        <!-- 13 checklist -->
                        <section>
                            <h3 class="text-lg font-bold text-[#1e5aa0] dark:text-blue-400 pb-1 mb-3 border-b-2 border-[#1e5aa0]/30">13 &nbsp;·&nbsp; Requirements Checklist</h3>
                            <div class="grid sm:grid-cols-2 gap-4">
                                <div class="rounded-lg border dark:border-zinc-700 p-3">
                                    <div class="font-semibold mb-1">Every device</div>
                                    <ul class="list-disc ml-5 space-y-1 text-xs">
                                        <li>An identity — generated at first launch, backed up somewhere safe</li>
                                        <li>At least one interface — a radio, a Wi-Fi connection, or LCS Global</li>
                                        <li>An announce — sent once at setup, and again after any change in connection</li>
                                    </ul>
                                </div>
                                <div class="rounded-lg border dark:border-zinc-700 p-3">
                                    <div class="font-semibold mb-1">For offline delivery</div>
                                    <ul class="list-disc ml-5 space-y-1 text-xs">
                                        <li>At least one propagation node that stays powered — a Command Center Gateway, LCS Global, or a desktop running MeshChat</li>
                                    </ul>
                                </div>
                                <div class="rounded-lg border dark:border-zinc-700 p-3">
                                    <div class="font-semibold mb-1">For extended range</div>
                                    <ul class="list-disc ml-5 space-y-1 text-xs">
                                        <li>Transport nodes with <code>enable_transport = Yes</code>, positioned high</li>
                                        <li>Matching radio parameters on every device sharing a channel. A mismatch produces silence, not a slow link.</li>
                                    </ul>
                                </div>
                                <div class="rounded-lg border dark:border-zinc-700 p-3">
                                    <div class="font-semibold mb-1">For live voice</div>
                                    <ul class="list-disc ml-5 space-y-1 text-xs">
                                        <li>A link with enough capacity: Wi-Fi, Ethernet, LCS Global, or LoRa at Short Fast or faster. Otherwise use PTT voice clips.</li>
                                    </ul>
                                </div>
                                <div class="rounded-lg border dark:border-zinc-700 p-3">
                                    <div class="font-semibold mb-1">Legal</div>
                                    <ul class="list-disc ml-5 space-y-1 text-xs">
                                        <li>LoRa at 902–928 MHz is licence-free in the United States.</li>
                                        <li>Encrypted VHF/UHF business-band operation requires an FCC licence. Regulations vary by country.</li>
                                    </ul>
                                </div>
                                <div class="rounded-lg border dark:border-zinc-700 p-3">
                                    <div class="font-semibold mb-1">Not required</div>
                                    <ul class="list-disc ml-5 space-y-1 text-xs">
                                        <li>Accounts, subscriptions, SIM cards or phone numbers</li>
                                        <li>DNS, DHCP, port forwarding or static IP addresses</li>
                                        <li>Permission from any central authority to join or extend the network</li>
                                    </ul>
                                </div>
                            </div>
                        </section>

                        <!-- network diagram -->
                        <section>
                            <h3 class="text-lg font-bold text-[#1e5aa0] dark:text-blue-400 pb-1 mb-3 border-b-2 border-[#1e5aa0]/30">The LCS Network</h3>
                            <button type="button" @click="guideZoom = '/assets/images/guide/network-map.jpg'" class="block w-full">
                                <img src="/assets/images/guide/network-map.jpg" alt="LCS Network Map: Liberty Chat, LCS MeshChat, RNodes and Command Center PRO connected by LoRa, packet radio, Wi-Fi and LCS Global" class="w-full rounded-lg border dark:border-zinc-700 bg-white cursor-zoom-in shadow-sm" />
                            </button>
                            <div class="text-xs text-center text-gray-500 dark:text-gray-400 italic mt-1">AES-256 encrypted voice, text and data · tap to enlarge</div>
                        </section>

                        <!-- disclaimers -->
                        <section class="space-y-3">
                            <details class="rounded-lg border dark:border-zinc-700 overflow-hidden">
                                <summary class="cursor-pointer px-3 py-2 bg-gray-50 dark:bg-zinc-800 font-semibold text-xs">⚠ RF Radiation Warning (Wi-Fi / LoRa radio)</summary>
                                <div class="px-3 py-2 text-xs text-gray-600 dark:text-gray-400">
                                    This product transmits radiofrequency (RF) electromagnetic radiation via Wi-Fi and/or
                                    LoRa radio protocols. The International Agency for Research on Cancer (IARC) has
                                    classified RF radiation as a possible human carcinogen (Group 2B). Peer-reviewed
                                    research has identified potential associations between RF-EMF exposure and adverse
                                    effects on human fertility. Individuals with pacemakers, implantable cardiac
                                    defibrillators or other active medical implants, or those with known heart
                                    conditions, should consult a physician before use, as RF radiation may interfere
                                    with implanted devices. Prolonged close-range exposure should be minimized as a
                                    precautionary measure. Liberty Communication Systems, Inc. expressly disclaims all
                                    liability for any health effects, injury or damage arising from RF exposure
                                    associated with this product. By using this product, the user assumes all risk
                                    associated with RF exposure and acknowledges having read this warning.
                                </div>
                            </details>
                            <details class="rounded-lg border dark:border-zinc-700 overflow-hidden">
                                <summary class="cursor-pointer px-3 py-2 bg-gray-50 dark:bg-zinc-800 font-semibold text-xs">⚠ Lithium Battery Warning (Li / Li-ion / LiFePO₄)</summary>
                                <div class="px-3 py-2 text-xs text-gray-600 dark:text-gray-400">
                                    This product contains or is intended for use with lithium-based batteries. Lithium
                                    batteries present a risk of fire, explosion, severe burns and toxic gas release if
                                    punctured, crushed, short-circuited, overcharged, exposed to heat, or improperly
                                    handled, stored or disposed of. The U.S. Consumer Product Safety Commission has
                                    identified thermal runaway as an unreasonable risk of death and injury. Use only
                                    manufacturer-approved chargers; never charge unattended or on flammable surfaces;
                                    store in a cool, dry location away from children; and dispose of only at a certified
                                    battery recycling facility in accordance with federal, state and local regulations.
                                    Lithium batteries are regulated hazardous materials under 49 CFR Parts 171–180
                                    (DOT/PHMSA). Liberty Communication Systems, Inc. expressly disclaims all liability
                                    for any injury, death or property damage arising from misuse, improper charging,
                                    improper storage or improper disposal of any lithium-based battery.
                                </div>
                            </details>
                            <details class="rounded-lg border dark:border-zinc-700 overflow-hidden">
                                <summary class="cursor-pointer px-3 py-2 bg-gray-50 dark:bg-zinc-800 font-semibold text-xs">🔒 Encryption &amp; Legal Use Disclaimer</summary>
                                <div class="px-3 py-2 text-xs text-gray-600 dark:text-gray-400">
                                    This product incorporates end-to-end encryption and cryptographic authentication
                                    technology, including the Reticulum Network Stack and associated hardware, software
                                    and server infrastructure. It is intended solely for lawful purposes and must be used
                                    in full compliance with all applicable federal, state, local and international laws
                                    and regulations, including those governing encrypted communications, radio frequency
                                    transmission, unlicensed spectrum use, export controls and data privacy. The use of
                                    encryption technology for illegal purposes — including obstruction of law
                                    enforcement, facilitation of criminal activity, unauthorized interception of
                                    communications, or evasion of lawful surveillance — is strictly prohibited. Liberty
                                    Communication Systems, Inc. expressly disclaims all liability for any illegal,
                                    unauthorized or improper use of this hardware, network or server infrastructure by
                                    any end user or third party. By purchasing, activating or using this product, the
                                    user represents and warrants that they will use it exclusively for lawful purposes.
                                </div>
                            </details>
                        </section>

                        <!-- footer -->
                        <div class="pt-4 border-t dark:border-zinc-700 text-center space-y-2">
                            <a href="https://lcs.network/guide" target="_blank" class="inline-flex items-center gap-x-2 rounded-lg bg-[#1e5aa0] hover:bg-[#123a6b] px-4 py-2 text-white font-semibold shadow-sm transition">
                                Read the most recent guide at lcs.network/guide
                                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-4">
                                    <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                                </svg>
                            </a>
                            <div class="text-xs text-gray-500 dark:text-gray-400">
                                Liberty Communication Systems, Inc. · lcs.network
                            </div>
                        </div>

                    </div>
                </div>
            </div>
        </div>

        <!-- LCS: fullscreen zoom for guide figures -->
        <div v-if="guideZoom" @click="guideZoom = null" class="fixed inset-0 z-[60] flex items-center justify-center bg-black/90 p-2 cursor-zoom-out">
            <img :src="guideZoom" alt="Enlarged figure" class="max-w-full max-h-full object-contain rounded bg-white" />
            <button type="button" @click.stop="guideZoom = null" class="absolute top-4 right-4 text-white/80 hover:text-white">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="size-8">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
                </svg>
            </button>
        </div>

    </div>
</template>

<script>

export default {
    name: 'ToolsPage',
    data() {
        return {
            // LCS: About Reticulum guide dialog
            showGuide: false,
            guideZoom: null,
            guideScenarios: [
                {
                    id: 1,
                    title: "Scenario 1 — Two client RNodes with a solar transport node",
                    image: "/assets/images/guide/scenario1.png",
                    caption: "Off-grid LoRa messaging across a relay",
                    requirements: [
                        "One LCS Client RNode per household, connected by USB-C or Bluetooth to a phone or computer",
                        "One LCS Solar Transport Node, positioned high with line of sight to both homes",
                        "Matching frequency and preset on every radio unit",
                    ],
                    how: [
                        "The transport node re-broadcasts announces and forwards encrypted packets. No other device needs to be configured for it.",
                        "Each user announces once. Both households appear in each other's peer list by display name.",
                        "Messages route automatically across two hops, end-to-end encrypted, with signed delivery receipts.",
                    ],
                    notes: [
                        "Use Long Fast for maximum text range. PTT voice clips work well on this link.",
                        "Live voice calls require Short Fast or faster, which reduces range. Half-duplex mode is recommended.",
                        "The transport node is unattended and holds no messages. Offline devices receive messages when their host reconnects.",
                    ],
                },
                {
                    id: 2,
                    title: "Scenario 2 — Liberty Chat and LCS MeshChat over LCS Global",
                    image: "/assets/images/guide/scenario2.png",
                    caption: "Two applications meeting on LCS Global",
                    requirements: [
                        "An Android phone running Liberty Chat, on Wi-Fi or mobile data",
                        "A Windows or Mac computer running LCS MeshChat",
                        "LCS Global on each (free 7-day trial)",
                        "No radio hardware",
                    ],
                    how: [
                        "Both apps connect to LCS Global over Wi-Fi or mobile data. No public IP, static address or port forwarding is needed on either end.",
                        "LCS Global relays between them, learning both announces and routing messages and calls.",
                        "It holds messages for anyone offline and delivers them when they reconnect.",
                    ],
                    notes: [
                        "This is the fastest way to try the network before radio hardware is available.",
                        "LCS Global is fast enough for high-quality voice messages and live calls.",
                        "Turning on Tor hides both devices' internet addresses, with no change in how messaging works.",
                    ],
                },
                {
                    id: 3,
                    title: "Scenario 3 — Two mobile Command Center Gateways over packet radio",
                    image: "/assets/images/guide/scenario3.png",
                    caption: "Field deployment: two Wi-Fi islands bridged by packet radio",
                    requirements: [
                        "Two Command Center PRO Gateways in Wi-Fi AP mode",
                        "A push-to-talk radio on each gateway, driven by the built-in software modem",
                        "Android phones running Liberty Chat at each site, joined to their local gateway's Wi-Fi",
                        "FCC licence for encrypted operation on 150–174 MHz or 450–470 MHz",
                    ],
                    how: [
                        "Each gateway broadcasts its own Wi-Fi network. Phones join via AutoInterface with no IP configuration.",
                        "The gateways link to each other over packet radio using KISS framing through the software modem.",
                        "Announces from Site A propagate to Site B over the RF link; messages route automatically both ways.",
                    ],
                    notes: [
                        "Packet radio provides greater range than LoRa at comparable power, making it the right long-haul medium.",
                        "The link is half-duplex and slower than LoRa at short range — expect text and PTT clips rather than live calls.",
                        "Each gateway holds mail for its own site.",
                        "Assign a shared network name and passphrase to close the deployment to others on the same channel.",
                    ],
                },
                {
                    id: 4,
                    title: "Scenario 4 — Two homes with IP RNodes on the local Wi-Fi",
                    image: "/assets/images/guide/scenario4.png",
                    caption: "The radio near the antenna, the application anywhere on the LAN",
                    requirements: [
                        "One IP LoRa RNode per house, joined to that house's Wi-Fi network",
                        "LCS MeshChat on a PC or Mac in each house",
                        "An RNode interface configured with port = tcp://iprnode.local",
                    ],
                    how: [
                        "The RNode is reached over the LAN, so it can sit in an attic or by a window for antenna performance while the computer stays at a desk.",
                        "MeshChat treats the Wi-Fi-connected RNode identically to a USB-connected unit.",
                        "The two RNodes communicate directly over LoRa, carrying LXMF traffic between the houses.",
                    ],
                    notes: [
                        "Any other device on either LAN can also participate via AutoInterface with no configuration.",
                        "If the homes are out of direct LoRa range, add a solar transport node between them — the path simply becomes two hops.",
                        "Run MeshChat as a propagation node on at least one machine so offline devices receive queued messages.",
                    ],
                },
                {
                    id: 5,
                    title: "Scenario 5 — Two RNode user clusters joined by packet radio",
                    image: "/assets/images/guide/scenario5.png",
                    caption: "Two local LoRa clusters bridged over packet radio",
                    requirements: [
                        "Two Command Center PRO Gateways, positioned for best antenna performance at each site",
                        "A push-to-talk radio on each gateway, driven by the built-in software modem",
                        "A cluster of LCS Client RNodes at each site — one per user",
                        "FCC licence for encrypted operation on the business band",
                    ],
                    how: [
                        "Within a cluster, users reach the gateway and often each other directly over LoRa. Local traffic never touches the packet radio link.",
                        "Between clusters, each gateway bridges LoRa to packet radio — three hops: LoRa in, packet radio across, LoRa out.",
                        "Announces propagate the same path, so users simply see the other site's users appear by name.",
                        "Both gateways run as transport and propagation nodes, holding mail for their own segment.",
                    ],
                    notes: [
                        "Each radio medium is used where it is most effective — LoRa for short local links, packet radio for the single long hop.",
                        "It scales by adding gateways: a third site joins on the same packet radio channel with no client reconfiguration.",
                        "Segments keep working if the backbone fails; cross-site messages queue until the link returns.",
                        "All RNodes in a cluster must share frequency, bandwidth, spreading factor and coding rate. A mismatch produces silence, not a degraded link.",
                    ],
                },
            ],
        };
    },
}
</script>
