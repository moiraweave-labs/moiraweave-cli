# Changelog

> **Migration notice (2026-05-20)**: The CLI command was previously `inferflow`. It is now `moira`. No legacy aliases are maintained.

## [0.3.3](https://github.com/moiraweave-labs/moiraweave-cli/compare/v0.3.2...v0.3.3) (2026-07-02)


### Documentation

* clarify PyPI install boundary ([ee33c1a](https://github.com/moiraweave-labs/moiraweave-cli/commit/ee33c1af66247bb60ebb2bf130930a9c6934ca2b))

## [0.3.2](https://github.com/moiraweave-labs/moiraweave-cli/compare/v0.3.1...v0.3.2) (2026-06-30)


### Features

* add agent template runtime probes ([17c40a2](https://github.com/moiraweave-labs/moiraweave-cli/commit/17c40a28dcc10eee9c7ed587272c090bc77fdc5d))
* add deployment controller runner ([6a8b224](https://github.com/moiraweave-labs/moiraweave-cli/commit/6a8b22403ede735b2e42c94af1f61e43fc11b613))
* add doctor readiness guide ([3b43bfb](https://github.com/moiraweave-labs/moiraweave-cli/commit/3b43bfb186583df5fb1f90c2d022ac61dbe0f303))
* add local onboarding doctor ([9ecdd8a](https://github.com/moiraweave-labs/moiraweave-cli/commit/9ecdd8a197d2a8315156b1fd0387bb56df8a13ad))
* add one-shot agent chat ([5c925f7](https://github.com/moiraweave-labs/moiraweave-cli/commit/5c925f7c50b1fa853342a67051bc888525b395aa))
* add secret inventory command ([4f5f696](https://github.com/moiraweave-labs/moiraweave-cli/commit/4f5f696dd833b8b47923ac1f62215fc1299dc491))
* add workload and agent ops commands ([2471c3d](https://github.com/moiraweave-labs/moiraweave-cli/commit/2471c3d70e115084e04d763439e46f92b6e283ea))
* add workload preflight command ([2256013](https://github.com/moiraweave-labs/moiraweave-cli/commit/2256013176ca08762271b3c6681b4e73c8326d90))
* check kubernetes secret inventory ([d286086](https://github.com/moiraweave-labs/moiraweave-cli/commit/d2860861bf9dfd33be9a02be8a1c7c6a36a4b71f))
* **cli:** add local product up flow ([1516d31](https://github.com/moiraweave-labs/moiraweave-cli/commit/1516d312a46507a9e40e097e824da981258021c6))
* **cli:** add moira job list command ([94fbde0](https://github.com/moiraweave-labs/moiraweave-cli/commit/94fbde0f98e853fbb4bf1b087dea6a5fa0c68711))
* **cli:** add production ops commands ([c3bb3ef](https://github.com/moiraweave-labs/moiraweave-cli/commit/c3bb3efdd661b833ee1476e495262005d245d625))
* **cli:** filter runs by environment ([818d445](https://github.com/moiraweave-labs/moiraweave-cli/commit/818d4451845b91197525e40ce111f59b1f09ff21))
* **cli:** heartbeat deployment controller ops ([3876057](https://github.com/moiraweave-labs/moiraweave-cli/commit/3876057e16bb78e049f236d53923b8cc783760ab))
* **cli:** refresh controller lease during commands ([a68b1b3](https://github.com/moiraweave-labs/moiraweave-cli/commit/a68b1b310e11d5e6d579de8f87b5cf8c03c03681))
* **cli:** translate Spanish strings to English, add --version, improve pipeline run UX ([5085147](https://github.com/moiraweave-labs/moiraweave-cli/commit/508514742fb7a38f5f0fb7f40880f7f211093a4b))
* configure agent runtime manifests ([9cc567e](https://github.com/moiraweave-labs/moiraweave-cli/commit/9cc567e58a5e90935031147174c9b1412018f42c))
* configure workload placement ([681f5fb](https://github.com/moiraweave-labs/moiraweave-cli/commit/681f5fbd84da270e841ded5d6c90e6003893b122))
* include UI in initialized compose ([45d69a6](https://github.com/moiraweave-labs/moiraweave-cli/commit/45d69a667d5efc2416eef671812ef3cfdae1c022))
* manage identity from cli ([1411c1b](https://github.com/moiraweave-labs/moiraweave-cli/commit/1411c1b56afa1b42f20a04b99577473b4fea746a))
* publish cli controller image ([b42ccd9](https://github.com/moiraweave-labs/moiraweave-cli/commit/b42ccd9e641e89d1bb52c1f010cf1901b9955b6c))
* register deployment environments ([557bdea](https://github.com/moiraweave-labs/moiraweave-cli/commit/557bdeada33f21e32aaac64a689c71801edd2e9f))
* register workload deployments ([489e004](https://github.com/moiraweave-labs/moiraweave-cli/commit/489e004394a840950b8957fae0909278f539e4b0))
* **release:** add release-please config files and use config-file approach ([005adbf](https://github.com/moiraweave-labs/moiraweave-cli/commit/005adbf6f7751aab2b56eb1ed8f1e3bca3c34d3e))
* run controller without workspace ([451ee55](https://github.com/moiraweave-labs/moiraweave-cli/commit/451ee5564a331d5939909d0bfa1613df6bc03b07))
* **run:** manage dead-letter entries ([8427cf9](https://github.com/moiraweave-labs/moiraweave-cli/commit/8427cf9e3c80dc3bd61e65ba997612bca3052f61))
* scaffold runtime-owned agents ([90185b8](https://github.com/moiraweave-labs/moiraweave-cli/commit/90185b8530103238ca0411fe0482ea0304cbe7a3))
* **security:** remove team members ([d7e1865](https://github.com/moiraweave-labs/moiraweave-cli/commit/d7e18659ffa118567901220d64fe1dcf593a4fb4))
* seed agent templates from moira up ([9af7b2e](https://github.com/moiraweave-labs/moiraweave-cli/commit/9af7b2e82cdaa8d694386d13f69682347cb88b0a))
* self-contained workspace — generate compose on init, override on dev, auth hints on push ([2d6986e](https://github.com/moiraweave-labs/moiraweave-cli/commit/2d6986ef9902e6a487e8e3281c7d238bdbaf5284))
* support runtime-owned channels ([d9b9a68](https://github.com/moiraweave-labs/moiraweave-cli/commit/d9b9a68e690ce0ec0467984e79f4030a9daeefce))
* wait for UI during local up ([90d33d2](https://github.com/moiraweave-labs/moiraweave-cli/commit/90d33d2aed7342cc670e45809da3279862977296))


### Bug Fixes

* avoid duplicate agent workspace mounts ([5fad0f0](https://github.com/moiraweave-labs/moiraweave-cli/commit/5fad0f045e0ac99578f8f2b110fa74bd1e567127))
* avoid embedding downloads during local up ([e03d9a4](https://github.com/moiraweave-labs/moiraweave-cli/commit/e03d9a47558249b4508635bee898a227ca0810b1))
* **cli:** correct job-status URL and helm upgrade flag ([f4cdac3](https://github.com/moiraweave-labs/moiraweave-cli/commit/f4cdac37306d60ca5a565ea8539c60ee77055d58))
* **cli:** flow handler reads step 'id' instead of non-existent 'name' ([aa6af1e](https://github.com/moiraweave-labs/moiraweave-cli/commit/aa6af1e3b2f26352910d5d4b94ee7d3bce8d4039))
* **cli:** reclaim expired controller operations ([15c2cb8](https://github.com/moiraweave-labs/moiraweave-cli/commit/15c2cb89762c67ad2d3e3f77359c224c4631060a))
* **cli:** translate remaining Spanish strings in flow, handlers, and io ([c7e8395](https://github.com/moiraweave-labs/moiraweave-cli/commit/c7e8395912ee5bc158e5e1956189f37196cd4a27))
* ignore local workspace state ([94f8cbd](https://github.com/moiraweave-labs/moiraweave-cli/commit/94f8cbd5d1ce4e92e317bb0c3399ad95ba8fdaf1))
* **lint:** apply ruff format to test_e2e.py ([ee01ffd](https://github.com/moiraweave-labs/moiraweave-cli/commit/ee01ffd83f00fac4ef690f8999e3851ec7f543cb))
* **lint:** remove unused Path imports (ruff F401) ([4e49120](https://github.com/moiraweave-labs/moiraweave-cli/commit/4e4912093fdea7607501d5a23124b1b08f359ec2))
* persist local cli auth token ([27dd5a6](https://github.com/moiraweave-labs/moiraweave-cli/commit/27dd5a68abc26dcc8719b3ab7970fdf1de5cd086))
* protect persisted cli token ([f89bbb6](https://github.com/moiraweave-labs/moiraweave-cli/commit/f89bbb69cb5508ad0ae271448f4b400c7f49d04b))
* respect ready endpoint state ([db6c065](https://github.com/moiraweave-labs/moiraweave-cli/commit/db6c065e2b727890b080c2a4426d531fec7755fa))
* retry doctor image checks ([f6f5f54](https://github.com/moiraweave-labs/moiraweave-cli/commit/f6f5f54dc6ab9acd4d1f698790bb46975edbc36b))
* simplify agent template secrets ([814cebd](https://github.com/moiraweave-labs/moiraweave-cli/commit/814cebd283b7115df1ff07dfafdd842bb7f74184))
* **step-new:** improve test scaffold and pyproject.toml generation ([de61d4c](https://github.com/moiraweave-labs/moiraweave-cli/commit/de61d4c0e859d87caa1e71cdcef70c7ce45693e3))
* tolerate transient image checks ([72d7b09](https://github.com/moiraweave-labs/moiraweave-cli/commit/72d7b09e2cd253709681b64e43ba0447fe53c204))
* use patched helm kubectl in cli image ([824658c](https://github.com/moiraweave-labs/moiraweave-cli/commit/824658c9e85259d7aa54180fb62734103c80d443))


### Documentation

* add docs badge linking to moiraweave-labs.github.io ([3742c3b](https://github.com/moiraweave-labs/moiraweave-cli/commit/3742c3b0710b039fdb7be75a98b0aa7585eff3af))
* **changelog:** add rebrand migration notice ([2796254](https://github.com/moiraweave-labs/moiraweave-cli/commit/2796254db2695a857933f93dbc8079a1ff32518b))
* clarify agent channel ingress ([c403dc9](https://github.com/moiraweave-labs/moiraweave-cli/commit/c403dc9c4b282d59787f0aea579784d64b22c6f3))
* clarify local up readiness ([f7ba578](https://github.com/moiraweave-labs/moiraweave-cli/commit/f7ba57812c5be903cf561addf3cb59c529ae7c49))
* document image check warnings ([58be91a](https://github.com/moiraweave-labs/moiraweave-cli/commit/58be91a9dffbb848f00a4dc9e2013fcc52dbb0fd))
* note ghcr visibility for onboarding ([662b24b](https://github.com/moiraweave-labs/moiraweave-cli/commit/662b24b178bfb83e0569eb1c49aced3456b1ea29))
* point first run to agent console ([fb1c20a](https://github.com/moiraweave-labs/moiraweave-cli/commit/fb1c20ae518d65909cfa8e507844d34b3007f442))

## [0.3.0](https://github.com/moiraweave-labs/moiraweave-cli/compare/v0.2.0...v0.3.0) (2026-05-17)


### Features

* **cli:** comando 'flow' para visualizar árbol del workspace ([16f03d2](https://github.com/moiraweave-labs/moiraweave-cli/commit/16f03d2889711dad4b2cbe083af0ae3b16df4d06))


### Documentation

* **env:** añade comentarios explicativos al .env generado ([d68c227](https://github.com/moiraweave-labs/moiraweave-cli/commit/d68c227b4e56ef917aacbc8932d60528f4d87fff))

## [0.2.0](https://github.com/moiraweave-labs/moiraweave-cli/compare/v0.1.0...v0.2.0) (2026-05-17)


### Features

* create command orchestration layer for all domains ([73c8d9a](https://github.com/moiraweave-labs/moiraweave-cli/commit/73c8d9a4d3993da61eb3660faf4ccf5a38d23b0b))
* create presenter layer for output formatting ([3095f89](https://github.com/moiraweave-labs/moiraweave-cli/commit/3095f8990614b47c403edc0eca9418c967371844))
* integrate command/presenter layers into main.py commands ([5d151ba](https://github.com/moiraweave-labs/moiraweave-cli/commit/5d151bafa1b08aed971755836640c7c88914b68b))
* refactor CLI without backward compat, consolidate dirs to .moiraweave/, create all handlers ([706568a](https://github.com/moiraweave-labs/moiraweave-cli/commit/706568af5f1c5bd6d3c9ab474f807b46e238eaaf))
* refactor step_build, step_push, task_new, task_show with new architecture ([45fff6a](https://github.com/moiraweave-labs/moiraweave-cli/commit/45fff6a2394231ab1558e074b7090a33caf120ee))
* refactor step_show and step_add into layered architecture ([3490822](https://github.com/moiraweave-labs/moiraweave-cli/commit/34908226986cc16063c43559badc767e58d8e016))
* refactor step_test, models, job commands with new architecture ([b195ad6](https://github.com/moiraweave-labs/moiraweave-cli/commit/b195ad6958875fcf9b728e444db9eb19803eddb3))


### Documentation

* **readme:** professionalize project overview and badges ([b25f539](https://github.com/moiraweave-labs/moiraweave-cli/commit/b25f5399eda3dff487a627a9e0a3223371b72730))

## 0.1.0 (2026-05-16)


### Features

* implement CLI-first workspace initialization and step catalog support ([ca4a014](https://github.com/moiraweave-labs/moiraweave-cli/commit/ca4a0148826fd24996d4d6d50a0a76a0c24db4e0))

## 0.1.0

- Initial standalone release of the MoiraWeave CLI repository.
