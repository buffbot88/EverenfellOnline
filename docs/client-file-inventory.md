# Client file inventory (generated)

Scope: `MKO_Client/Assets/` (199 SWFs, 52,757 files, of which 52,754 are under `res/`). Source for every SWF is the file on disk; descriptions come from the boot-chain notes in [boot-chain.md](boot-chain.md) and the decompiled readable scripts. Most SWFs are not decompilable as-is, so their function is listed only where the file name says it.

## Delivery chain

| File | Header | Role |
|---|---|---|
| `Assets/MainLoader.swf` | standard CWS | Top-level loader; its internals are not audited yet |
| `Assets/res/Main.swf` | standard CWS | `Platform` bootstrapper: downloads `PlatformLoader.swf`, checks its size (`Version.HASH`=82921), then starts `assets/tg.swf` |
| `Assets/res/PlatformLoader.swf` | standard CWS | Shell with an Alchemy C core (`cmodule/ccode`); loads the embedded `EnLoader` |
| `Assets/res/assets/tg.swf` | encrypted (`08 1F 86`) | Main game client. Its decrypt step is `RFPluginUtils.decodeFunction`; the stock decode is a no-op for it, so the game code is still unreadable |
| `Assets/res/lib.swf` | standard FWS | Shared library classes |
| `Assets/res/MPlayer.swf` | standard CWS | Secondary player SWF (tried as a Ruffle sidecar, reverted) |
| `Assets/playerProductInstall.swf` | standard CWS | Stock Flash product-install helper |

## Locale branches

`res/config/` holds one branch per locale. The default in the boot notes is `tw` (Traditional Chinese). Branches: `tw`, `tw_branchs`, `zhcn`, `zhcn_branchs`, `kokr`, `ko_KR`, `kokr_branchs`, `us`, `us_branchs`, `thai`, `thai_branchs`, `dama`, `dama_branchs`, and `backup`. A stray file named `tw_branchstranassetsout - tw.txt` and an `undefined` folder also exist. These are part of the translation work.

## Readable decompiled scripts

Files in `output/ffdec/decompiled-main/scripts/` (17 files) and `decompiled-r/scripts/` (4 files), plus `decompiled-pl/scripts/` (193 files, mostly the `cmodule/ccode` C core output, not game logic).

| Script | Role |
|---|---|
| `Platform.as`, `Platform__loc_1.as`, `Version.as` | Bootstrapper, embedded loader asset, version hash |
| `show/Show.as`, `show/ShowObj.as` | Progress/loading text display |
| `com/youbt/core/Container.as`, `RFSprite.as` | Display containers and base sprite |
| `com/youbt/events/RFEvent.as` | Custom event class |
| `com/youbt/manager/RFSystemManager*.as` | Global display and system manager |
| `com/youbt/utils/NameUtil.as` | Name helper |
| `com/youbt/utils/RFPluginUtils.as` | Plugin decode hook (the "decrypt" function) |
| `com/youbt/asm/Op.as`, `__asm.as` | Obfuscation markers (`__asm(...)` control-flow calls) |
| `mx/core/*.as` | Flex framework stubs (`ByteArrayAsset`, `IFlexAsset`, `mx_internal`) |
| `EnLoader.as` (decompiled-r) | Downloads and loads the next URL in the embedded loader |

## SWF counts by category

Categories come from file names: UI panel (`*UI*`), plugin (`*Plugin*`), library/loader, other scene/feature. The header column shows whether the file can be read as a SWF at all.

| Category | Standard header | Encrypted or non-standard |
|---|---|---|
| UI panel | 0 | 117 |
| Plugin | 0 | 11 |
| Library/loader | 5 | 7 |
| Other scene/feature | 1 | 58 |

Totals: 199 SWFs, 32.8 MB. Only 6 have a standard SWF header, and `tg.swf` is the encrypted boot blob. The other 192 SWFs have a non-standard header.

## Other assets by extension

| Extension | Files |
|---|---|
| `.jpg` | 45278 |
| `.png` | 4005 |
| `.pak` | 954 |
| `.dat` | 761 |
| `.ani` | 684 |
| `.mp3` | 223 |
| `.mm` | 220 |
| `.swf` | 199 |
| `.gz` | 144 |
| `.db` | 105 |
| `.mpq` | 63 |
| `.jat` | 55 |
| `.txt` | 21 |
| `.psd` | 16 |
| `.xml` | 14 |
| `.bak` | 2 |
| `.csv` | 2 |
| `.exe` | 2 |
| `.(none)` | 2 |
| `.html` | 1 |
| `.js` | 1 |
| `.gif` | 1 |
| `.json` | 1 |
| `.pac` | 1 |
| `.pas` | 1 |
| `.bat` | 1 |

`.jat` and `.mm` are the config tables the Java server reads (see [game-data-inventory.md](game-data-inventory.md)). The purposes of `.dat`, `.gz`, `.db`, `.mpq`, `.pak`, `.ani`, `.mp3`, and `.txt` are not audited yet. Images are mostly `jpg`, plus `png` and `psd` sources.

## All SWFs

| Path (under `MKO_Client/Assets/`) | Header | Bytes |
|---|---|---:|
| `MainLoader.swf` | standard (CWS) | 125128 |
| `playerProductInstall.swf` | standard (CWS) | 657 |
| `res/MPlayer.swf` | standard (CWS) | 1420 |
| `res/Main.swf` | standard (CWS) | 16832 |
| `res/PlatformLoader.swf` | standard (CWS) | 82921 |
| `res/assets/Shop.swf` | non-standard header | 129989 |
| `res/assets/StoreUI.swf` | non-standard header | 9408 |
| `res/assets/VIPzhuanpanUI.swf` | non-standard header | 119351 |
| `res/assets/bagUI.swf` | non-standard header | 24964 |
| `res/assets/baicaoyuan.swf` | non-standard header | 88297 |
| `res/assets/baixian.swf` | non-standard header | 201890 |
| `res/assets/baozang.swf` | non-standard header | 116023 |
| `res/assets/baseFace.swf` | non-standard header | 300407 |
| `res/assets/bianqiangUI.swf` | non-standard header | 102854 |
| `res/assets/biguanUI.swf` | non-standard header | 31467 |
| `res/assets/boothPlugin.swf` | non-standard header | 685 |
| `res/assets/boothUI.swf` | non-standard header | 29109 |
| `res/assets/bossUI.swf` | non-standard header | 371320 |
| `res/assets/cangkuUI.swf` | non-standard header | 18163 |
| `res/assets/chengjiuUI.swf` | non-standard header | 242070 |
| `res/assets/chongzhiUI.swf` | non-standard header | 155719 |
| `res/assets/chooseRole.swf` | non-standard header | 40694 |
| `res/assets/chooseRolePlugin.swf` | non-standard header | 3373 |
| `res/assets/clanPlugin.swf` | non-standard header | 41821 |
| `res/assets/clanUI.swf` | non-standard header | 77951 |
| `res/assets/createRolePlugin.swf` | non-standard header | 16141 |
| `res/assets/createRoleV2.swf` | non-standard header | 796717 |
| `res/assets/createUI.swf` | non-standard header | 210241 |
| `res/assets/cuilianUI.swf` | non-standard header | 250265 |
| `res/assets/czleijiUI.swf` | non-standard header | 135046 |
| `res/assets/daoFaPlugin.swf` | non-standard header | 684 |
| `res/assets/dayslandUI.swf` | non-standard header | 66068 |
| `res/assets/dujie.swf` | non-standard header | 402912 |
| `res/assets/emailUI.swf` | non-standard header | 11837 |
| `res/assets/embed.swf` | non-standard header | 510903 |
| `res/assets/fabaoUI.swf` | non-standard header | 154581 |
| `res/assets/friendPlugin.swf` | non-standard header | 683 |
| `res/assets/friendUI.swf` | non-standard header | 24574 |
| `res/assets/fuben.swf` | non-standard header | 497506 |
| `res/assets/gStoreUI.swf` | non-standard header | 116384 |
| `res/assets/gameUI.swf` | non-standard header | 47936 |
| `res/assets/gemUI.swf` | non-standard header | 276453 |
| `res/assets/guaji.swf` | non-standard header | 8980 |
| `res/assets/guajiUI.swf` | non-standard header | 6821 |
| `res/assets/guozhan.swf` | non-standard header | 370701 |
| `res/assets/huodong.swf` | non-standard header | 44441 |
| `res/assets/huoyue.swf` | non-standard header | 45547 |
| `res/assets/intensifyUI.swf` | non-standard header | 111178 |
| `res/assets/jingjiPK.swf` | non-standard header | 441069 |
| `res/assets/jingjichang.swf` | non-standard header | 288931 |
| `res/assets/kaifuUI.swf` | non-standard header | 221352 |
| `res/assets/levelGifs.swf` | non-standard header | 24959 |
| `res/assets/lib.swf` | non-standard header | 121950 |
| `res/assets/lingjiang.swf` | non-standard header | 330168 |
| `res/assets/lingqiUI.swf` | non-standard header | 300845 |
| `res/assets/lixian.swf` | non-standard header | 10323 |
| `res/assets/loading.swf` | non-standard header | 166201 |
| `res/assets/mailUI.swf` | non-standard header | 43169 |
| `res/assets/mapPlugin.swf` | non-standard header | 21371 |
| `res/assets/meirenUI.swf` | non-standard header | 190324 |
| `res/assets/mojieUI.swf` | non-standard header | 61803 |
| `res/assets/mubiaoUI.swf` | non-standard header | 105554 |
| `res/assets/otherRoleUI.swf` | non-standard header | 453357 |
| `res/assets/paihang.swf` | non-standard header | 219219 |
| `res/assets/paihangUI.swf` | non-standard header | 246036 |
| `res/assets/panelLoad.swf` | non-standard header | 64715 |
| `res/assets/pata.swf` | non-standard header | 409335 |
| `res/assets/pozhen.swf` | non-standard header | 491381 |
| `res/assets/roleUI.swf` | non-standard header | 176133 |
| `res/assets/setting.swf` | non-standard header | 3846 |
| `res/assets/settingUI.swf` | non-standard header | 7827 |
| `res/assets/shenjiang.swf` | non-standard header | 1564 |
| `res/assets/shenshu.swf` | non-standard header | 212588 |
| `res/assets/shenshuUI.swf` | non-standard header | 249050 |
| `res/assets/shoufeiUI.swf` | non-standard header | 163738 |
| `res/assets/sjUI.swf` | non-standard header | 300410 |
| `res/assets/skillPanelPlugin.swf` | non-standard header | 9313 |
| `res/assets/skillUI.swf` | non-standard header | 7089 |
| `res/assets/slotSucess.swf` | non-standard header | 118286 |
| `res/assets/sportwzUI.swf` | non-standard header | 26768 |
| `res/assets/task.swf` | non-standard header | 103761 |
| `res/assets/taskPlugin.swf` | non-standard header | 27092 |
| `res/assets/taskUI.swf` | non-standard header | 106088 |
| `res/assets/taskmotion.swf` | non-standard header | 61923 |
| `res/assets/tasknew.swf` | non-standard header | 32760 |
| `res/assets/teamPlugin.swf` | non-standard header | 684 |
| `res/assets/teamUI.swf` | non-standard header | 35417 |
| `res/assets/tg.swf` | encrypted (tg.swf boot blob) | 1551064 |
| `res/assets/tiaozhanUI.swf` | non-standard header | 217163 |
| `res/assets/transactionUI.swf` | non-standard header | 10968 |
| `res/assets/trumpPanelPlugin.swf` | non-standard header | 37249 |
| `res/assets/tw/bagUI.swf` | non-standard header | 2933 |
| `res/assets/tw/baixianUI.swf` | non-standard header | 179568 |
| `res/assets/tw/baseFace.swf` | non-standard header | 633471 |
| `res/assets/tw/bdshuru.swf` | non-standard header | 122259 |
| `res/assets/tw/bianqiangUI.swf` | non-standard header | 53544 |
| `res/assets/tw/boothUI.swf` | non-standard header | 27610 |
| `res/assets/tw/bossplaces.swf` | non-standard header | 121490 |
| `res/assets/tw/campaign7day.swf` | non-standard header | 170912 |
| `res/assets/tw/campaignmerge.swf` | non-standard header | 805563 |
| `res/assets/tw/cangbaoUI.swf` | non-standard header | 86755 |
| `res/assets/tw/cangbaogeUI.swf` | non-standard header | 22691 |
| `res/assets/tw/cangkuUI.swf` | non-standard header | 5493 |
| `res/assets/tw/cardUI.swf` | non-standard header | 164865 |
| `res/assets/tw/chibangUI.swf` | non-standard header | 106955 |
| `res/assets/tw/clanFubenUI.swf` | non-standard header | 129074 |
| `res/assets/tw/clanTargetUI.swf` | non-standard header | 64038 |
| `res/assets/tw/clanUI.swf` | non-standard header | 124578 |
| `res/assets/tw/createUI.swf` | non-standard header | 211713 |
| `res/assets/tw/danaobdUI.swf` | non-standard header | 8314 |
| `res/assets/tw/emailUI.swf` | non-standard header | 10905 |
| `res/assets/tw/firstSeasonUI.swf` | non-standard header | 117154 |
| `res/assets/tw/friendUI.swf` | non-standard header | 20048 |
| `res/assets/tw/gameui.swf` | non-standard header | 596076 |
| `res/assets/tw/guajiUI.swf` | non-standard header | 6466 |
| `res/assets/tw/guozhanResultUI.swf` | non-standard header | 89281 |
| `res/assets/tw/guozhanUI.swf` | non-standard header | 544955 |
| `res/assets/tw/hcningdan.swf` | non-standard header | 74479 |
| `res/assets/tw/hechengUI.swf` | non-standard header | 38841 |
| `res/assets/tw/hechengv2.swf` | non-standard header | 82954 |
| `res/assets/tw/husongUI.swf` | non-standard header | 378185 |
| `res/assets/tw/jiandingUI.swf` | non-standard header | 103598 |
| `res/assets/tw/jiangliUI.swf` | non-standard header | 434005 |
| `res/assets/tw/jichengUI.swf` | non-standard header | 82784 |
| `res/assets/tw/kaichangUI.swf` | non-standard header | 686509 |
| `res/assets/tw/kaifuUI.swf` | non-standard header | 274405 |
| `res/assets/tw/kefuUI.swf` | non-standard header | 2814 |
| `res/assets/tw/kuafuUI.swf` | non-standard header | 135249 |
| `res/assets/tw/lib.swf` | non-standard header | 133582 |
| `res/assets/tw/libaoUI.swf` | non-standard header | 2272 |
| `res/assets/tw/lingdizhanResultUI.swf` | non-standard header | 89933 |
| `res/assets/tw/lingquMR.swf` | non-standard header | 128757 |
| `res/assets/tw/lixian.swf` | non-standard header | 18420 |
| `res/assets/tw/lixianjingji.swf` | non-standard header | 240977 |
| `res/assets/tw/loading.swf` | non-standard header | 150302 |
| `res/assets/tw/luckydraw2UI.swf` | non-standard header | 158233 |
| `res/assets/tw/luckydrawUI.swf` | non-standard header | 162424 |
| `res/assets/tw/meirenUI.swf` | non-standard header | 331292 |
| `res/assets/tw/mysticUI.swf` | non-standard header | 34500 |
| `res/assets/tw/newkaifuUI.swf` | non-standard header | 274484 |
| `res/assets/tw/newlibao.swf` | non-standard header | 62059 |
| `res/assets/tw/newqingdian.swf` | non-standard header | 97579 |
| `res/assets/tw/newsj.swf` | non-standard header | 416053 |
| `res/assets/tw/newsj72.swf` | non-standard header | 491018 |
| `res/assets/tw/newsj72content.swf` | non-standard header | 90669 |
| `res/assets/tw/paihangUI.swf` | non-standard header | 380382 |
| `res/assets/tw/pozhenUI.swf` | non-standard header | 448477 |
| `res/assets/tw/qianfuUI.swf` | non-standard header | 274307 |
| `res/assets/tw/qianzhuangUI.swf` | non-standard header | 151402 |
| `res/assets/tw/qidashengUI.swf` | non-standard header | 153125 |
| `res/assets/tw/qingdianUI.swf` | non-standard header | 194569 |
| `res/assets/tw/qizhanUI.swf` | non-standard header | 75924 |
| `res/assets/tw/roleUI.swf` | non-standard header | 440692 |
| `res/assets/tw/sellUI.swf` | non-standard header | 484023 |
| `res/assets/tw/settingUI.swf` | non-standard header | 3971 |
| `res/assets/tw/shenshu.swf` | non-standard header | 212606 |
| `res/assets/tw/shopUI.swf` | non-standard header | 91180 |
| `res/assets/tw/shouchongUI.swf` | non-standard header | 83899 |
| `res/assets/tw/sjUI.swf` | non-standard header | 269650 |
| `res/assets/tw/skillUI.swf` | non-standard header | 7306 |
| `res/assets/tw/storeUI.swf` | non-standard header | 6237 |
| `res/assets/tw/taskUI.swf` | non-standard header | 169422 |
| `res/assets/tw/teamFuben.swf` | non-standard header | 266649 |
| `res/assets/tw/teamUI.swf` | non-standard header | 66436 |
| `res/assets/tw/tequanVIPUI.swf` | non-standard header | 58450 |
| `res/assets/tw/tiaozhanUI.swf` | non-standard header | 454288 |
| `res/assets/tw/timeLimitBuyUI.swf` | non-standard header | 94058 |
| `res/assets/tw/timelimitStore.swf` | non-standard header | 28500 |
| `res/assets/tw/touxianUI.swf` | non-standard header | 40193 |
| `res/assets/tw/treasureUI.swf` | non-standard header | 200016 |
| `res/assets/tw/vipUI.swf` | non-standard header | 72795 |
| `res/assets/tw/vipfubenUI.swf` | non-standard header | 204622 |
| `res/assets/tw/viplotteryUI.swf` | non-standard header | 50714 |
| `res/assets/tw/vipnewUI.swf` | non-standard header | 165297 |
| `res/assets/tw/welcome.swf` | non-standard header | 86457 |
| `res/assets/tw/worldMapUI.swf` | non-standard header | 417988 |
| `res/assets/tw/wulianchou.swf` | non-standard header | 158400 |
| `res/assets/tw/xianfuxunbao.swf` | non-standard header | 119945 |
| `res/assets/tw/xianjieUI.swf` | non-standard header | 67134 |
| `res/assets/tw/xinqu.swf` | non-standard header | 55447 |
| `res/assets/tw/xinquhuodong.swf` | non-standard header | 183002 |
| `res/assets/tw/yuanshenUI.swf` | non-standard header | 52300 |
| `res/assets/tw/zhuanpanUI.swf` | non-standard header | 172147 |
| `res/assets/tw/zhufuUI.swf` | non-standard header | 5342 |
| `res/assets/tw/zuwuFubenUI.swf` | non-standard header | 127583 |
| `res/assets/tw/zuwuUI.swf` | non-standard header | 141699 |
| `res/assets/tzBoss.swf` | non-standard header | 252615 |
| `res/assets/vipUI.swf` | non-standard header | 731666 |
| `res/assets/worldMap.swf` | non-standard header | 218061 |
| `res/assets/worldMapUI.swf` | non-standard header | 218216 |
| `res/assets/xianfajingjieUI.swf` | non-standard header | 101225 |
| `res/assets/xianfuUI.swf` | non-standard header | 174393 |
| `res/assets/xianjing.swf` | non-standard header | 153130 |
| `res/assets/xiantiandaofa.swf` | non-standard header | 14482 |
| `res/assets/zfzUI.swf` | non-standard header | 40418 |
| `res/assets/zhuanpan.swf` | non-standard header | 137427 |
| `res/assets/zhuxian.swf` | non-standard header | 224766 |
| `res/assets/zuoqi.swf` | non-standard header | 106064 |
| `res/lib.swf` | standard (FWS) | 54 |
