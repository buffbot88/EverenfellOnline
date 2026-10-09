# Java server inventory (generated)

Generated from `output/jar-inventory.json` (produced by `tools/jar_inventory.py` over `reference/TonNgoKhong/server/dntg_start.jar`). Per-command IDs and bytecode method names are in [java-command-map.md](java-command-map.md).

Notes are inferred from package and class names. The jar contains no source, so they are not verified against code. Entries marked "name-based guess" are unverified. Each note above is inferred from names, not verified against code.

Totals: 970 module classes, 886 command IDs, 94 package families.

| Family | Classes | Kinds | Command IDs | What it does (inferred) |
|---|---|---|---|---|
| `com.xianling.public_` | 205 | Action 16, Commands 14, Dao 42, Output 43, ServiceImpl 90 | `11001`, `11002`, `11003`, `11004`, `11005`, `11100`, `11101`, `11105`, `11110`, `11111` (+180) | Shared cross-system services: gamelog (event logs), rank (leaderboards), guild, booth (market stalls), shenshu, friend, jingji (arena), team, trade, teamfuben (team dungeons), question, pnotice, statistics, notice, robot, share, nodecontrol, microend. |
| `com.xianling.stage` | 155 | Action 38, Commands 6, Dao 13, Output 11, ServiceImpl 87 | `100017`, `1002`, `1004`, `10050`, `10051`, `102004`, `104003`, `108007`, `108008`, `110` (+224) | Scene (map) runtime: service, configure, easyaction, robot, guozhan (nation war), husong (escort), manorwar, prop, dao, qishengboss, xianshanghuodong, kuafu (cross-server), export, output, command, share, gm. |
| `com.xianling.bus.huodong` | 20 | Action 1, Commands 1, Dao 7, Output 2, ServiceImpl 9 | `101000`, `70000`, `70001`, `70100`, `70500`, `70501`, `70502`, `70505`, `70506`, `70507` (+21) | Timed events (huodong). |
| `com.xianling.bus.task` | 19 | Action 4, Commands 1, Dao 4, ServiceImpl 10 | `50000`, `50001`, `50002`, `50003`, `50004`, `50005`, `50006`, `50007`, `50008`, `50012` (+16) | Quests and tasks. |
| `com.xianling.bus.shenjiang` | 16 | Action 1, Commands 1, Dao 3, Output 5, ServiceImpl 6 | `30106`, `41000`, `41001`, `41002`, `41003`, `41004`, `41005`, `41021`, `41022`, `41023` (+9) | Reward system (shenjiang). |
| `com.xianling.bus.jiangli` | 15 | Action 1, Commands 1, Dao 4, Output 3, ServiceImpl 6 | `10060`, `10061`, `58003`, `58004`, `58005`, `58011`, `58012`, `58013`, `58014`, `58015` (+19) | Reward claims (jiangli). |
| `com.xianling.gamerule` | 15 | Output 1, ServiceImpl 14 | `100`, `101`, `102`, `103`, `104`, `107`, `108`, `121`, `122`, `123` (+10) | Game rule and balance formulas (ServiceImpl only, no commands). |
| `com.xianling.bus.kuafu` | 11 | Action 1, Commands 1, Dao 1, ServiceImpl 8 | `125000`, `125001`, `125008`, `125009`, `125012`, `125016` | Cross-server battles (kuafu). |
| `com.xianling.bus.role` | 11 | Action 2, Commands 1, Dao 1, Output 4, ServiceImpl 3 | `12001`, `12011`, `12050`, `12200`, `19001` | Character role data (create, get, settings). |
| `com.xianling.bus.toubao` | 11 | Action 1, Commands 1, Dao 2, Output 3, ServiceImpl 4 | `793000`, `793001`, `793002`, `793003`, `793004`, `793005`, `86000`, `86001`, `86002`, `86003` | Investment or bet (toubao; name-based guess). |
| `com.xianling.bus.vip` | 11 | Action 1, Commands 1, Dao 3, ServiceImpl 6 | `62000`, `62001`, `62002`, `62003`, `62004`, `62006`, `62020`, `62021`, `62022`, `88000` (+2) | VIP tiers and privileges. |
| `com.xianling.bus.dafuwong` | 10 | Action 1, Commands 1, Dao 1, ServiceImpl 7 | `105000`, `105001`, `105002`, `105003`, `109000` | Lucky-draw event (dafuwong; name-based guess). |
| `com.xianling.bus.pet` | 10 | Action 1, Commands 1, Dao 2, ServiceImpl 6 | `11101`, `136000`, `136001`, `136002`, `136003`, `136004`, `136005`, `136006`, `136007`, `136008` (+3) | Pets. |
| `com.xianling.bus.xunbao` | 10 | Action 1, Commands 1, Dao 3, ServiceImpl 5 | `11101`, `97000`, `97001`, `97002`, `97003`, `97004`, `97005` | Treasure hunt (xunbao). |
| `com.xianling.bus.zhouhuan` | 10 | Action 1, Commands 1, Dao 1, ServiceImpl 7 | `128000`, `128001`, `128002`, `128003`, `128004`, `128005` | Weekly cycle event (zhouhuan; name-based guess). |
| `com.xianling.sample` | 10 | Action 1, Dao 3, ServiceImpl 6 | `11223` | Sample or template module (Dao, Action, ServiceImpl). |
| `com.xianling.bus.giftcode` | 9 | Action 1, Commands 1, Dao 2, Output 1, ServiceImpl 4 | `57000`, `570001` | Gift codes. |
| `com.xianling.bus.shenqi` | 9 | Action 1, Commands 1, Dao 2, ServiceImpl 5 | `11101`, `132000`, `132001`, `132002`, `132003` | Divine weapons (shenqi). |
| `com.xianling.bus.zuoqi` | 9 | Action 1, Commands 1, Dao 2, Output 1, ServiceImpl 4 | `11101`, `12102`, `33000`, `33001`, `33003`, `33004`, `33005`, `33006`, `33007`, `33008` (+4) | Mounts (zuoqi). |
| `com.xianling.bus.attributebuff` | 8 | Action 1, Commands 1, Dao 1, ServiceImpl 5 | `85000`, `85010` | Stat buffs. |
| `com.xianling.bus.bag` | 8 | Action 1, Commands 1, Dao 2, Output 1, ServiceImpl 3 | `11005`, `30000`, `30001`, `30002`, `30003`, `30004`, `30005`, `30006`, `30100`, `30101` (+11) | Inventory bag. |
| `com.xianling.bus.baoshi` | 8 | Action 1, Commands 1, Dao 1, ServiceImpl 5 | `11101`, `37000`, `37001`, `37002` | Gems (baoshi). |
| `com.xianling.bus.equip` | 8 | Action 1, Commands 1, Dao 2, ServiceImpl 4 | `11101`, `30106`, `31000`, `31001`, `31015`, `31016`, `34000`, `34001`, `34003`, `34004` (+5) | Equipment slots and equip actions. |
| `com.xianling.bus.mall` | 8 | Action 1, Commands 1, Dao 1, Output 1, ServiceImpl 4 | `2000`, `32000`, `32001`, `32006` | Item mall. |
| `com.xianling.bus.shenmishop` | 8 | Action 1, Commands 1, Dao 3, ServiceImpl 3 | `11101`, `112000`, `112001`, `112002` | Mystery shop (shenmi shangdian). |
| `com.xianling.bus.shenmizhuanpan` | 8 | Action 1, Commands 1, Dao 3, ServiceImpl 3 | `11101`, `114000`, `114001`, `114002` | Mystery wheel (shenmi zhuanpan). |
| `com.xianling.bus.sixzhuanpan` | 8 | Action 1, Commands 1, Dao 2, ServiceImpl 4 | `11101`, `130000`, `130001`, `130002`, `130003`, `130004` | Six-wheel lottery (six zhuanpan). |
| `com.xianling.bus.skill` | 8 | Action 1, Commands 1, Dao 1, Output 2, ServiceImpl 3 | `42000`, `42003`, `42004` | Character skills. |
| `com.xianling.bus.xianjiechenhao` | 8 | Action 1, Commands 1, Dao 2, ServiceImpl 4 | `11101`, `91002`, `91003`, `91004`, `91005`, `91006`, `91007`, `91009` | Immortal-realm titles (xianjie chenghao). |
| `com.xianling.bus.email` | 7 | Action 1, Commands 1, Dao 2, ServiceImpl 3 | `000`, `63001`, `63002`, `63003`, `63004`, `63005`, `63006`, `63007`, `63008`, `63009` | In-game mail. |
| `com.xianling.bus.gonghuitask` | 7 | Action 1, Commands 1, Dao 1, ServiceImpl 4 | `81000`, `81001`, `81002`, `81003`, `81004`, `81005`, `81006`, `81007`, `81008`, `81009` (+1) | Guild quests (gonghuitask). |
| `com.xianling.bus.guildfuben` | 7 | Action 1, Commands 1, Dao 2, ServiceImpl 3 | `11003`, `11101`, `11130`, `118001`, `118002`, `118003`, `118004`, `118007` | Guild dungeons. |
| `com.xianling.bus.hecheng` | 7 | Action 1, Commands 1, Output 1, ServiceImpl 4 | `117000`, `117001`, `117002`, `117010`, `117011`, `30106` | Crafting and synthesis (hecheng). |
| `com.xianling.bus.hefuhuodong` | 7 | Action 1, Commands 1, Dao 3, ServiceImpl 2 | `113000`, `113001`, `113002`, `113003`, `113004`, `113005`, `113006` | Merged-server events (hefuhuodong). |
| `com.xianling.bus.marry` | 7 | Action 1, Commands 1, Dao 1, ServiceImpl 4 | `11101`, `11131`, `135000`, `135001`, `135002`, `135003`, `135004`, `135005`, `135006` | Marriage. |
| `com.xianling.bus.pozhen` | 7 | Action 1, Commands 1, Dao 1, ServiceImpl 4 | `48001`, `48002`, `48003`, `48004`, `48005`, `48006`, `48007`, `48008`, `48009`, `48010` | Formation or array battle (pozhen; name-based guess). |
| `com.xianling.bus.xianjiehuoyuedu` | 7 | Action 1, Commands 1, Dao 1, ServiceImpl 4 | `90000`, `90001`, `91000`, `91001` | Immortal-realm activity points (xianjie huoyuedu). |
| `com.xianling.bus.xianshibuy` | 7 | Action 1, Commands 1, Dao 3, ServiceImpl 2 | `119000`, `119001`, `119002`, `119003` | Limited-time purchases (xianshibuy). |
| `com.xianling.bus.zuwu` | 7 | Action 1, Commands 1, Dao 1, ServiceImpl 4 | `111000`, `111001`, `111002`, `111003`, `11101` | Group or party system (zuwu; name-based guess). |
| `com.xianling.bus.zuwufuben` | 7 | Action 1, Commands 1, Dao 1, ServiceImpl 4 | `108001`, `108002`, `108003`, `108004`, `108005`, `108006`, `108009`, `108010`, `108011` | Group dungeons (zuwufuben; name-based guess). |
| `com.xianling.bus.account` | 6 | Action 1, Commands 1, Dao 2, ServiceImpl 2 | `32010`, `35011`, `35012` | Account currency: yb, yxb and lingshi increments, freezes and claims. |
| `com.xianling.bus.baixian` | 6 | Action 1, Dao 1, ServiceImpl 4 | `71000`, `71001` | Immortal companion system and its feeding (baixian; name-based guess). |
| `com.xianling.bus.duihuangoods` | 6 | Action 1, Commands 1, Dao 1, ServiceImpl 3 | `93000`, `93001`, `93003` | Redeem goods for points (duihuan). |
| `com.xianling.bus.guangyi` | 6 | Action 1, Commands 1, Dao 1, ServiceImpl 3 | `102000`, `102001`, `102002`, `102003`, `11101` | Guangyi activity or system (name-based guess). |
| `com.xianling.bus.jijin` | 6 | Action 1, Commands 1, Dao 1, ServiceImpl 3 | `134000`, `134001`, `134002`, `134003` | Fund purchase (jijin). |
| `com.xianling.bus.jindi` | 6 | Action 1, Dao 2, ServiceImpl 3 | `65001`, `65002` | Restricted zone or dungeon (jindi; name-based guess). |
| `com.xianling.bus.jinfeng` | 6 | Action 1, Dao 2, ServiceImpl 3 | `000`, `001`, `002`, `111`, `11200`, `12304`, `14001` | GM sanctions: speech ban and title ban (jinyan, fenghao; name-based guess from class names). |
| `com.xianling.bus.juqingfuben` | 6 | Action 1, Commands 1, Dao 1, ServiceImpl 3 | `64001`, `64002`, `64004`, `64006`, `64007`, `64010`, `64012`, `64013` | Story dungeons (juqing fuben). |
| `com.xianling.bus.kapai` | 6 | Action 1, Commands 1, Dao 1, ServiceImpl 3 | `121000`, `121001`, `121002`, `121003` | Collectible cards (kapai). |
| `com.xianling.bus.lianchou` | 6 | Action 1, Commands 1, Dao 1, ServiceImpl 3 | `120100`, `120110`, `120111`, `120112`, `120113` | Multi-draw gacha (lianchou). |
| `com.xianling.bus.phone` | 6 | Action 1, Commands 1, Dao 1, ServiceImpl 3 | `116000`, `116001` | Phone binding and verification (phone). |
| `com.xianling.bus.qianfuhuodong` | 6 | Action 1, Commands 1, Dao 2, ServiceImpl 2 | `120000`, `120001`, `120002`, `120003`, `120004` | Thousand-server event (qianfu huodong). |
| `com.xianling.bus.qizhanbinqi` | 6 | Action 1, Commands 1, Dao 1, ServiceImpl 3 | `11101`, `87000`, `87001`, `87002` | Seven-battle weapons (qizhan binqi). |
| `com.xianling.bus.touxian` | 6 | Action 1, Commands 1, Dao 1, ServiceImpl 3 | `104000`, `104001`, `104002`, `104004`, `11101` | Titles (touxian). |
| `com.xianling.bus.vipqq` | 6 | Action 1, Dao 2, ServiceImpl 3 | `794000`, `794001`, `794002`, `88003`, `88004`, `88005` | VIP QQ-group rewards (name-based guess). |
| `com.xianling.bus.xianshituangou` | 6 | Action 1, Commands 1, Dao 2, ServiceImpl 2 | `122000`, `122001`, `122002` | Limited-time group buy (xianshi tuangou). |
| `com.xianling.bus.yuanshen` | 6 | Action 1, Commands 1, Dao 1, ServiceImpl 3 | `11101`, `124001`, `124002`, `124003` | Primordial spirit system (yuanshen). |
| `com.xianling.bus.zhizuntequan` | 6 | Action 1, Commands 1, Dao 1, ServiceImpl 3 | `131000`, `131001`, `131002`, `131003`, `131004` | Supreme privileges (zhizun tequan). |
| `com.xianling.bus.bagdummy` | 5 | Action 1, Commands 1, Dao 1, ServiceImpl 2 | `93002` | Placeholder or extra bag slots (name-based guess). |
| `com.xianling.bus.chengjiu` | 5 | Action 1, Commands 1, Dao 1, ServiceImpl 2 | `89000`, `89005` | Achievements (chengjiu). |
| `com.xianling.bus.client` | 5 | Action 2, Commands 1, ServiceImpl 2 | `000` | Client connection lifecycle: init, close and IO (BusInitAction, BusOutAction). |
| `com.xianling.bus.goodsbuyback` | 5 | Action 1, Commands 1, Dao 1, ServiceImpl 2 | `1003`, `1006`, `32002`, `32003`, `32004`, `32005`, `430405` | Buy back sold items. |
| `com.xianling.bus.jchuodong` | 5 | Action 1, Commands 1, Dao 1, ServiceImpl 2 | `129000`, `129001`, `129002` | Featured events (jingcai huodong). |
| `com.xianling.bus.jingyanyu` | 5 | Action 1, Commands 1, Dao 1, ServiceImpl 2 | `30106`, `30600`, `30601` | Experience-jade items and buffs (jingyanyu; name-based guess). |
| `com.xianling.bus.loginlibao` | 5 | Action 1, Commands 1, Dao 1, ServiceImpl 2 | `127000`, `127001` | Login gift packs (denglu libao). |
| `com.xianling.bus.loginlingjaing` | 5 | Action 1, Commands 1, Dao 1, ServiceImpl 2 | `103000`, `103001` | Login rewards (lingjiang). |
| `com.xianling.bus.lvlibao` | 5 | Action 1, Commands 1, Dao 1, ServiceImpl 2 | `58000`, `58001` | Level gift packs (lv libao). |
| `com.xianling.bus.meiren` | 5 | Action 1, Commands 1, Dao 1, ServiceImpl 2 | `11101`, `82000`, `82001`, `82002`, `82003`, `82004` | Beauty or companion system (meiren). |
| `com.xianling.bus.mingrentang` | 5 | Action 1, Commands 1, Dao 1, ServiceImpl 2 | `133000`, `133001`, `133002`, `133003`, `133004` | Hall of fame (mingrentang). |
| `com.xianling.bus.setting` | 5 | Action 1, Commands 1, Dao 1, ServiceImpl 2 | `13000`, `13001`, `13002`, `13003`, `13004` | Per-role UI settings (command 13000, implemented in Python). |
| `com.xianling.bus.share` | 5 | Dao 1, ServiceImpl 4 | - | Shared caches, schedules and role state (framework-style services). |
| `com.xianling.bus.skillbook` | 5 | Action 1, Commands 1, Dao 1, ServiceImpl 2 | `30106`, `99000`, `99001`, `99002` | Skill books and skill slots. |
| `com.xianling.bus.zhandouli` | 5 | Action 1, Commands 1, ServiceImpl 3 | `12010` | Combat power score (zhandouli). |
| `com.xianling.bus.zyzhuihui` | 5 | Action 1, Commands 1, Dao 1, ServiceImpl 2 | `107000`, `107001` | Resource recovery (ziyuan zhuihui). |
| `com.xianling.bus.changest` | 4 | Action 1, Commands 1, ServiceImpl 2 | `123000`, `123001` | 72-form transformation system (Change72; name-based guess). |
| `com.xianling.bus.goodsexchange` | 4 | Action 1, Commands 1, Dao 1, ServiceImpl 1 | - | Item exchange (no command IDs found). |
| `com.xianling.bus.movie` | 4 | Action 1, Commands 1, Dao 1, ServiceImpl 1 | `106000`, `106001` | Cutscenes or movies (movie). |
| `com.xianling.bus.recharge` | 4 | Action 1, Dao 1, ServiceImpl 2 | `1001`, `1003`, `1004`, `1005`, `12301` | Top-up and recharge records. |
| `com.xianling.bus.rolebusinessdata` | 4 | Action 1, Dao 1, ServiceImpl 2 | - | Per-role business statistics. |
| `com.xianling.bus.stagecontroll` | 4 | Action 1, Commands 1, ServiceImpl 2 | `10003`, `20000`, `20004`, `20005`, `21000`, `21001` | Scene control: enter world and map change (commands 10003, 20000, implemented in Python). |
| `com.xianling.global` | 4 | Commands 1, ServiceImpl 3 | - | Framework: cache loader, scheduled jobs (Quartz) and SQL map config. |
| `com.xianling.io` | 4 | Action 3, Commands 1 | `19000`, `19010`, `21000` | Network IO: ping, message out, and the 19000/19010/21000 commands. |
| `com.xianling.login` | 4 | Action 1, Commands 1, Output 1, ServiceImpl 1 | `10001`, `10002`, `16001`, `16002` | Login and session: 10001 login, 10002 create role (implemented in Python). |
| `com.kernel.data` | 3 | Dao 3 | - | Framework: DAO base classes (AbsBaseDao, AbsCacheDao) and the MyBatis/iBATIS accessor layer. |
| `com.xianling.bus.gm` | 3 | Action 1, Commands 1, ServiceImpl 1 | `100`, `101`, `102`, `103`, `104`, `107`, `111`, `113`, `114`, `115` (+8) | GM and admin commands (GmCommands, GmServiceImpl). |
| `com.xianling.bus.id` | 3 | Dao 1, ServiceImpl 2 | - | Global ID generator (IdGenExportServiceImpl). |
| `com.xianling.bus.server` | 3 | Dao 1, ServiceImpl 2 | - | Server info and status. |
| `com.xianling.bus.order` | 2 | ServiceImpl 2 | - | Order records (RoleOrderServiceImpl). |
| `com.xianling.configure` | 2 | Dao 1, ServiceImpl 1 | - | Framework: config export service and DAO. |
| `com.xianling.eventservice` | 2 | ServiceImpl 2 | - | Framework: event bus service. |
| `com.xianling.messageswap` | 2 | ServiceImpl 2 | - | Cross-node message routing (node swap). |
| `com.kernel.easyaction` | 1 | Action 1 | - | Framework: base class for action handlers (BaseEasyAction). |
| `com.xianling.bus.houtai` | 1 | ServiceImpl 1 | - | Backend operations service (HouTaiOperationServiceImpl). |
| `com.xianling.bus.webservice` | 1 | Commands 1 | - | Recharge web-service endpoint (RechargeCommands). |
