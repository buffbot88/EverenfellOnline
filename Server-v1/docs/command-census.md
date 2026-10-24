# Java-vs-Python command census

Mechanical diff: `*Commands` string constants from dntg_start.jar` (497 distinct numeric IDs) vs the `Session.handle` dispatcher (319 distinct values). Dispatch registration is counted, not behavioral parity.

## Totals

- total Java numeric command IDs: 497
- implemented: 246
- implemented-untested: 8
- partial: 0
- dispatched-no-direct-handler: 0
- inline: 5
- inline-untested: 0
- stub: 2
- push-only: 26
- known-unhandled: 0
- missing: 210
- accounted: 497 of 497 (exact)

`implemented` = dispatched, handler not stub-marked, and the ID string appears in the focused tests. `implemented-untested` = same without a test reference.

Void-reply inbound IDs proven by a wire/handler test (TESTED_BY_EVIDENCE) count as implemented:
- 81008: test_gonghui.py wire dispatch

## Counting methods (why 497 != ~600)

497 counts distinct numeric command IDs (one wire value = one row). The earlier ~600 figure counts method mappings: `javacmds.txt` holds 684 `*Commands` constant rows (30 share a numeric ID with another name; the rest are non-numeric strings, not commands), and `actionmethods.txt` holds 844 public action methods (overloads, push/notify variants, and helpers that share one command ID). Neither figure is wrong; progress percentages must use one denominator consistently. This ledger uses distinct numeric IDs.

## Per-module status (implemented+untested / stub / push-only / missing+known / total)

| module | done | untested | stub | push | missing | total |
| --- | --- | --- | --- | --- | --- | --- |
| gm | 1 | 0 | 0 | 0 | 24 | 25 |
| huodong | 12 | 0 | 0 | 2 | 24 | 38 |
| kuafu | 0 | 0 | 0 | 0 | 7 | 7 |
| xianjiechenhao | 0 | 0 | 0 | 0 | 7 | 7 |
| hefuhuodong | 0 | 0 | 0 | 0 | 7 | 7 |
| shenqi | 0 | 0 | 0 | 0 | 6 | 6 |
| sixzhuanpan | 0 | 0 | 0 | 0 | 6 | 6 |
| xunbao | 0 | 1 | 0 | 0 | 6 | 7 |
| zhouhuan | 0 | 0 | 0 | 0 | 6 | 6 |
| role | 3 | 1 | 0 | 0 | 5 | 9 |
| hecheng | 0 | 0 | 0 | 0 | 5 | 5 |
| lianchou | 0 | 0 | 0 | 0 | 5 | 5 |
| zhizuntequan | 0 | 0 | 0 | 0 | 5 | 5 |
| mingrentang | 0 | 0 | 0 | 0 | 5 | 5 |
| stagecontroll | 3 | 1 | 0 | 0 | 4 | 8 |
| equip | 11 | 0 | 0 | 0 | 4 | 15 |
| pet | 9 | 0 | 0 | 0 | 4 | 13 |
| shenmishop | 0 | 0 | 0 | 0 | 4 | 4 |
| yuanshen | 0 | 0 | 0 | 0 | 4 | 4 |
| zuwu | 1 | 0 | 0 | 0 | 4 | 5 |
| shenjiang | 7 | 0 | 0 | 0 | 4 | 11 |
| toubao | 0 | 0 | 0 | 0 | 4 | 4 |
| vipqq | 2 | 0 | 0 | 0 | 4 | 6 |
| xianjiehuoyuedu | 0 | 0 | 0 | 0 | 4 | 4 |
| zuwufuben | 5 | 1 | 1 | 0 | 4 | 11 |
| qianfuhuodong | 1 | 0 | 0 | 0 | 4 | 5 |
| jijin | 0 | 0 | 0 | 0 | 4 | 4 |
| guildfuben | 5 | 0 | 0 | 0 | 3 | 8 |
| bag | 17 | 1 | 1 | 0 | 3 | 22 |
| guangyi | 3 | 0 | 0 | 0 | 3 | 6 |
| shenmizhuanpan | 0 | 1 | 0 | 0 | 3 | 4 |
| zuoqi | 10 | 0 | 0 | 0 | 3 | 13 |
| jingyanyu | 0 | 0 | 0 | 0 | 3 | 3 |
| duihuangoods | 0 | 0 | 0 | 0 | 3 | 3 |
| jchuodong | 0 | 0 | 0 | 0 | 3 | 3 |
| juqingfuben | 8 | 0 | 0 | 0 | 2 | 10 |
| meiren | 4 | 0 | 0 | 0 | 2 | 6 |
| touxian | 3 | 0 | 0 | 0 | 2 | 5 |
| jinfeng | 0 | 0 | 0 | 0 | 2 | 2 |
| recharge | 0 | 0 | 0 | 0 | 2 | 2 |
| vip | 10 | 0 | 0 | 0 | 2 | 12 |
| email | 7 | 0 | 0 | 0 | 2 | 9 |
| jindi | 0 | 0 | 0 | 0 | 2 | 2 |
| attributebuff | 0 | 0 | 0 | 0 | 2 | 2 |
| movie | 0 | 0 | 0 | 0 | 2 | 2 |
| phone | 0 | 0 | 0 | 0 | 2 | 2 |
| kapai | 2 | 0 | 0 | 0 | 2 | 4 |
| xianshituangou | 1 | 0 | 0 | 0 | 2 | 3 |
| changest | 0 | 0 | 0 | 0 | 2 | 2 |
| client | 0 | 0 | 0 | 0 | 1 | 1 |
| jiangli | 13 | 0 | 0 | 0 | 1 | 14 |
| pozhen | 11 | 0 | 0 | 0 | 1 | 12 |
| baoshi | 3 | 0 | 0 | 0 | 1 | 4 |
| marry | 6 | 0 | 0 | 2 | 1 | 9 |
| qizhanbinqi | 3 | 0 | 0 | 0 | 1 | 4 |
| command | 1 | 0 | 0 | 0 | 1 | 2 |
| goodsbuyback | 3 | 0 | 0 | 0 | 1 | 4 |
| skill | 2 | 0 | 0 | 0 | 1 | 3 |
| giftcode | 0 | 0 | 1 | 0 | 1 | 2 |
| io | 2 | 0 | 0 | 0 | 0 | 2 |
| zhandouli | 1 | 0 | 0 | 0 | 0 | 1 |
| setting | 1 | 4 | 0 | 0 | 0 | 5 |
| mall | 5 | 0 | 0 | 0 | 0 | 5 |
| account | 2 | 1 | 0 | 0 | 0 | 3 |
| booth | 18 | 0 | 0 | 1 | 0 | 19 |
| task | 14 | 1 | 0 | 11 | 0 | 26 |
| friend | 11 | 0 | 0 | 6 | 0 | 17 |
| lvlibao | 2 | 0 | 0 | 0 | 0 | 2 |
| baixian | 2 | 0 | 0 | 0 | 0 | 2 |
| gonghuitask | 7 | 0 | 0 | 4 | 0 | 11 |
| chengjiu | 2 | 0 | 0 | 0 | 0 | 2 |
| bagdummy | 1 | 0 | 0 | 0 | 0 | 1 |
| skillbook | 3 | 0 | 0 | 0 | 0 | 3 |
| loginlingjaing | 2 | 0 | 0 | 0 | 0 | 2 |
| dafuwong | 5 | 0 | 0 | 0 | 0 | 5 |
| zyzhuihui | 2 | 0 | 0 | 0 | 0 | 2 |
| xianshibuy | 3 | 1 | 0 | 0 | 0 | 4 |
| loginlibao | 2 | 0 | 0 | 0 | 0 | 2 |

`push-only` IDs are confirmed Java S2C notifies with no inbound handler; the port asserts them in peer outboxes instead of dispatching them.

## Missing IDs by module (id: const / python handler)

- gm (24): 100 (GM_100), 101 (GM_101), 102 (GM_102), 103 (GM_103), 104 (GM_104), 105 (GM_105), 106 (GM_106), 107 (GM_107), 108 (GM_108), 109 (GM_109), 110 (GM_110), 111 (GM_111), 113 (GM_113), 114 (GM_114), 115 (GM_115), 116 (GM_116), 117 (GM_117), 118 (GM_118), 120 (GM_120), 130 (GM_130), 131 (GM_131), 140 (GM_140), 141 (GM_141), 200 (GM_200)
- huodong (24): 70100 (h70100), 70502 (h70502), 70503 (h70503), 70504 (h70504), 70505 (h70505), 70509 (h70509), 70510 (h70510), 70511 (h70511), 70530 (h70530), 70552 (CMD_70552), 70553 (CMD_70553), 70554 (CMD_70554), 70556 (ZUOQI_JINJIE), 70558 (GET_PROP), 70559 (RECHARGE_YB), 94002 (RANKHUODONG_LIST), 94003 (RANKHUODONG_SINGLE), 94004 (RANKHUODONG_MONSTER), 94005 (RANKHUODONG_GAIN), 94100 (RANKHUODONG2_LIST), 94101 (RANKHUODONG2_SINGLE), 94102 (RANKHUODONG2_MONSTER), 94103 (RANKHUODONG2_GAIN), 101000 (CMD_101000)
- xianjiechenhao (7): 91002 (CMD_91002), 91003 (CMD_91003), 91004 (CMD_91004), 91005 (CMD_91005), 91006 (CMD_91006), 91007 (CMD_91007), 91009 (CMD_91009)
- hefuhuodong (7): 113000 (CMD_113000), 113001 (CMD_113001), 113002 (CMD_113002), 113003 (CMD_113003), 113004 (CMD_113004), 113005 (CMD_113005), 113006 (CMD_113006)
- kuafu (6): 125000 (CMD_125000), 125001 (CMD_125001), 125008 (CMD_125008), 125009 (CMD_125009), 125012 (CMD_125012), 125016 (_125016)
- zhouhuan (6): 128000 (CMD_128000), 128001 (CMD_128001), 128002 (CMD_128002), 128003 (CMD_128003), 128004 (CMD_128004), 128005 (CMD_128005)
- role (5): 12001 (ADD_EXP), 12007 (MONSTER_EXP), 12009 (SHENGWANG_CHANGE), 12050 (ZHENQI_CHANGE), 12304 (CHANGE_ROLE_TYPE)
- xunbao (5): 97000 (H97000), 97002 (H97002), 97003 (H97003), 97004 (H97004), 97005 (H97005)
- hecheng (5): 117000 (CMD_117000), 117001 (CMD_117001), 117002 (CMD_117002), 117010 (CMD_117010), 117011 (CMD_117011)
- lianchou (5): 120100 (GET_CONFIG), 120110 (GET_THINGS), 120111 (FLUSH), 120112 (FAN_PAI), 120113 (CHOU_PAI)
- sixzhuanpan (5): 130000 (GET_CONFIG), 130001 (ZHUAN), 130002 (GET_LOG), 130003 (FLUSH), 130004 (GET_THINGS)
- zhizuntequan (5): 131000 (_131000), 131001 (_131001), 131002 (_131002), 131003 (_131003), 131004 (_131004)
- mingrentang (5): 133000 (CMD_133000), 133001 (CMD_133001), 133002 (CMD_133002), 133003 (CMD_133003), 133004 (CMD_133004)
- stagecontroll (4): 20004 (APPLY_CHANGE_LINE), 20005 (GET_MAP_LINES), 21001 (CHANGE_LINE), 50500 (s50500)
- toubao (4): 86000 (t86000), 86001 (t86001), 86002 (t86002), 86003 (t86003)
- vipqq (4): 88005 (CAN_REWARDS), 89001 (GET_VIPQQ), 89008 (ROLEQQLIST_CHANGE), 89009 (VIPQQ_CHANGE)
- xianjiehuoyuedu (4): 90000 (CMD_90000), 90001 (CMD_90001), 91000 (CMD_91000), 91001 (CMD_91001)
- zuwufuben (4): 108003 (CMD_108003), 108005 (CMD_108005), 108007 (CMD_108007), 108008 (CMD_108008)
- qianfuhuodong (4): 120001 (CMD_120001), 120002 (CMD_120002), 120003 (CMD_120003), 120004 (CMD_120004)
- shenqi (4): 132000 (CMD_132000), 132001 (CMD_132001), 132002 (CMD_132002), 132003 (CMD_132003)
- jijin (4): 134000 (CMD_134000), 134001 (CMD_134001), 134002 (CMD_134002), 134003 (CMD_134003)
- bag (3): 30104 (GOODS_UPDATE), 30105 (GOODS_ADD), 301050 (GOODS_ADD_EXTEND)
- equip (3): 30106 (GOODS_UPDATE), 31015 (QIANGHUA_NOTICE), 31016 (JINJIE_NOTICE)
- shenjiang (3): 41005 (s_41005), 41022 (s_41022), 41024 (s_41024)
- duihuangoods (3): 93000 (CMD_93000), 93001 (CMD_93001), 93003 (CMD_93003)
- zuwu (3): 111001 (UPGRADE), 111002 (JINGJIE), 111003 (YIJIANG_UPGRADE)
- shenmishop (3): 112000 (GET_CONFIG), 112001 (GET_THINGS), 112002 (BUY)
- yuanshen (3): 124001 (GETINFO), 124002 (UPGRADE_LEVEL), 124003 (JINJIE)
- jchuodong (3): 129000 (CMD_129000), 129001 (CMD_129001), 129002 (CMD_129002)
- pet (3): 136007 (CMD_136007), 136010 (CMD_136010), 136011 (CMD_136011)
- guildfuben (2): 11003 (GUILDGUANGBO), 11130 (_11130)
- jinfeng (2): 11200 (JINYAN), 14001 (GM_JINYAN)
- recharge (2): 12300 (_12300), 12301 (_12301)
- jingyanyu (2): 30600 (USE_JINGYANYU), 30601 (GET_USE_COUNT)
- zuoqi (2): 33010 (LINGHUN), 33012 (LINGLIONG)
- vip (2): 62003 (VIP_CHANGE), 62006 (VIP_PROP)
- email (2): 63005 (NOTIFY_NEW), 63009 (CHECK_NEW)
- jindi (2): 65001 (INFO), 65002 (ENTER)
- attributebuff (2): 85000 (CMD_85000), 85010 (CMD_85010)
- guangyi (2): 102001 (CMD_102001), 102005 (CMD_102005)
- movie (2): 106000 (CMD_106000), 106001 (CMD_106001)
- shenmizhuanpan (2): 114001 (GET_LOG), 114002 (ZHUAN)
- phone (2): 116000 (GETINFO), 116001 (REWARD)
- kapai (2): 121002 (CMD_121002), 121003 (CMD_121003)
- xianshituangou (2): 122000 (GET), 122001 (DUIHUAN)
- changest (2): 123000 (CMD_123000), 123001 (CMD_123001)
- client (1): 000 (ROLE_IN)
- juqingfuben (1): 11100 (SYSTEM_BROADCAST)
- baoshi (1): 11101 (NOTICE_ALL)
- command (1): 19010 (_19010)
- goodsbuyback (1): 32005 (DELETE_BACK_GOODS_NOTIFY)
- skill (1): 42004 (STUDY_SKILL)
- jiangli (1): 58016 (J58016)
- meiren (1): 82004 (MEIREN_82004)
- touxian (1): 104004 (CMD_104004)
- giftcode (1): 570001 (USE5CODE)

